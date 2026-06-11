import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from suite.ai_control_plane.audit import JsonlAuditLogger
from suite.ai_control_plane.models import (
    InferenceRequest,
    InferenceResponse,
    TenantPolicy,
    UserContext,
)
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import (
    InMemoryModelRegistry,
    InMemoryPromptRegistry,
    InMemoryToolPermissionRegistry,
    JsonFileModelRegistry,
    JsonFilePromptRegistry,
    JsonFileToolPermissionRegistry,
)
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.llm_gateway.providers.ollama import OllamaProvider
from suite.llm_gateway.providers.openai_compatible import OpenAICompatibleProvider
from suite.platform.admin_models import TenantAiPolicyUpdate
from suite.platform.context import TenantRequestContext
from suite.platform.modules import InMemoryModuleRegistry, PlatformModulesResponse, default_module_registry
from suite.platform.storage_paths import suite_data_dir
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository, JsonFileTenantPolicyRepository
from suite.rag.embedding_model_admin import (
    EmbeddingModelVersionAdminService,
    EmbeddingModelVersionApprovalRequest,
    EmbeddingModelVersionRegistrationRequest,
    EmbeddingModelVersionRetirementRequest,
    EmbeddingModelVersionView,
    JsonFileEmbeddingModelVersionRegistry,
)
from suite.rag.models import RagQuery, RagResponse
from suite.rag.pipeline import RagPipeline
from suite.rag.repositories import InMemoryAclAuthorizer, InMemorySourceRepository, InMemoryVectorStore
from suite.rag.source_indexing import InMemoryEmbeddingModelVersionRegistry
from suite.voice.models import VoiceTranscriptRequest, VoiceTranscriptResponse
from suite.voice.privacy import VoicePrivacyGuard


def parse_csv_header(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def get_tenant_request_context(
    request: Request,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    role_ids: Annotated[str | None, Header(alias="X-Role-Ids")] = None,
    readable_object_ids: Annotated[str | None, Header(alias="X-Readable-Object-Ids")] = None,
) -> TenantRequestContext:
    if not tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context requires X-Tenant-Id and X-User-Id headers",
        )

    policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
    try:
        tenant_policy = policy_repository.get(tenant_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant policy is not available",
        ) from exc

    return TenantRequestContext(
        user_context=UserContext(
            user_id=user_id,
            tenant_id=tenant_id,
            role_ids=parse_csv_header(role_ids),
            readable_object_ids=parse_csv_header(readable_object_ids),
        ),
        tenant_policy=tenant_policy,
    )


ADMIN_ROLE_IDS = {"tenant-admin", "security-admin"}


def require_tenant_admin(
    context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
) -> TenantRequestContext:
    if context.user_context.role_ids.isdisjoint(ADMIN_ROLE_IDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin role required",
        )
    return context


def require_security_admin(
    context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
) -> TenantRequestContext:
    if "security-admin" not in context.user_context.role_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security admin role required",
        )
    return context


def build_app() -> FastAPI:
    app = FastAPI(title="Compliance-First Enterprise Suite", version="0.1.0")

    data_dir = suite_data_dir()
    registry_dir = data_dir / "registries"

    audit_logger = JsonlAuditLogger.load(data_dir / "audit" / "events.jsonl")
    model_registry = JsonFileModelRegistry.load_or_seed(
        registry_dir / "models.json",
        seed=InMemoryModelRegistry.default(),
    )
    prompt_registry = JsonFilePromptRegistry.load_or_seed(
        registry_dir / "prompts.json",
        seed=InMemoryPromptRegistry.default(),
    )
    tool_permission_registry = JsonFileToolPermissionRegistry.load_or_seed(
        registry_dir / "tool_permissions.json",
        seed=InMemoryToolPermissionRegistry.default(),
    )
    embedding_model_registry = JsonFileEmbeddingModelVersionRegistry.load_or_seed(
        registry_dir / "embedding_models.json",
        seed=InMemoryEmbeddingModelVersionRegistry.approved_single_model(),
    )
    policy_engine = PolicyEngine(
        model_registry=model_registry,
        tool_permission_registry=tool_permission_registry,
    )
    llm_gateway = LocalLLMGateway(
        providers={
            "mock": MockLLMProvider(),
            "ollama": OllamaProvider(base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")),
            "vllm": OpenAICompatibleProvider(base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1")),
        },
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        policy_engine=policy_engine,
        audit_logger=audit_logger,
    )
    rag_pipeline = RagPipeline(
        vector_store=InMemoryVectorStore.demo(),
        source_repository=InMemorySourceRepository.demo(),
        acl_authorizer=InMemoryAclAuthorizer.demo(),
        llm_gateway=llm_gateway,
        audit_logger=audit_logger,
    )
    voice_guard = VoicePrivacyGuard(audit_logger=audit_logger)
    tenant_policy_repository = JsonFileTenantPolicyRepository.load_or_seed(
        registry_dir / "tenant_policies.json",
        seed=InMemoryTenantPolicyRepository.default(),
    )
    module_registry = default_module_registry()
    embedding_model_admin = EmbeddingModelVersionAdminService(
        repository=embedding_model_registry,
        audit_logger=audit_logger,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/platform/modules", response_model=PlatformModulesResponse)
    def list_platform_modules(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> PlatformModulesResponse:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        return module_registry.discover_tenant_modules(context.user_context.tenant_id)

    @app.get("/v1/admin/tenant-policy", response_model=TenantPolicy)
    def get_tenant_policy(
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantPolicy:
        return context.tenant_policy

    @app.patch("/v1/admin/tenant-policy/ai-settings", response_model=TenantPolicy)
    def update_tenant_ai_settings(
        update: TenantAiPolicyUpdate,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantPolicy:
        update_fields = update.model_dump(exclude_unset=True)
        if not update_fields:
            return context.tenant_policy

        requested_model_ids = update.allowed_model_ids
        if requested_model_ids is not None:
            for model_id in requested_model_ids:
                try:
                    model_registry.get(model_id)
                except LookupError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown model: {model_id}",
                    ) from exc

        policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
        updated_policy = context.tenant_policy.model_copy(update=update_fields)
        try:
            persisted_policy = policy_repository.update(updated_policy)
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant policy is not available",
            ) from exc

        audit_logger.record(
            user_context=context.user_context,
            event_type="tenant_policy.ai_settings.update",
            source_object_ids=[persisted_policy.tenant_id],
            metadata={
                "changed_fields": sorted(update_fields),
                "ai_enabled": persisted_policy.ai_enabled,
                "rag_enabled": persisted_policy.rag_enabled,
                "voice_enabled": persisted_policy.voice_enabled,
                "external_ai_enabled": persisted_policy.external_ai_enabled,
                "allowed_model_count": len(persisted_policy.allowed_model_ids),
            },
        )
        return persisted_policy

    @app.get("/v1/admin/embedding-models", response_model=list[EmbeddingModelVersionView])
    def list_embedding_model_versions(
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> list[EmbeddingModelVersionView]:
        del context
        return list(embedding_model_admin.list_model_versions())

    @app.post("/v1/admin/embedding-models", response_model=EmbeddingModelVersionView)
    def register_embedding_model_version(
        registration: EmbeddingModelVersionRegistrationRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.register(registration, user_context=context.user_context)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/embedding-models/{embedding_model_id}/versions/{embedding_model_version}/approve",
        response_model=EmbeddingModelVersionView,
    )
    def approve_embedding_model_version(
        embedding_model_id: str,
        embedding_model_version: str,
        approval: EmbeddingModelVersionApprovalRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.approve(
                embedding_model_id=embedding_model_id,
                embedding_model_version=embedding_model_version,
                request=approval,
                user_context=context.user_context,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/embedding-models/{embedding_model_id}/versions/{embedding_model_version}/retire",
        response_model=EmbeddingModelVersionView,
    )
    def retire_embedding_model_version(
        embedding_model_id: str,
        embedding_model_version: str,
        retirement: EmbeddingModelVersionRetirementRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.retire(
                embedding_model_id=embedding_model_id,
                embedding_model_version=embedding_model_version,
                request=retirement,
                user_context=context.user_context,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/ai/inference", response_model=InferenceResponse)
    def infer(
        inference_request: InferenceRequest,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> InferenceResponse:
        try:
            return llm_gateway.infer(
                request=inference_request,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/rag/query", response_model=RagResponse)
    def rag_query(
        query: RagQuery,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> RagResponse:
        try:
            return rag_pipeline.answer(
                query=query,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/voice/transcripts", response_model=VoiceTranscriptResponse)
    def voice_transcript(
        transcript_request: VoiceTranscriptRequest,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> VoiceTranscriptResponse:
        try:
            return voice_guard.accept_transcript(
                request=transcript_request,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    app.state.audit_logger = audit_logger
    app.state.llm_gateway = llm_gateway
    app.state.embedding_model_admin = embedding_model_admin
    app.state.embedding_model_registry = embedding_model_registry
    app.state.model_registry = model_registry
    app.state.module_registry = module_registry
    app.state.rag_pipeline = rag_pipeline
    app.state.tenant_policy_repository = tenant_policy_repository
    app.state.voice_guard = voice_guard

    return app


app = build_app()
