import os
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from suite.ai_control_plane.audit import JsonlAuditLogger, canonical_json, stable_hash
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
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.admin_models import TenantAiPolicyUpdate
from suite.platform.context import (
    DevHeaderAuthError,
    JwtAuthenticationError,
    PrincipalResolutionError,
    TenantRequestContext,
    build_default_principal_resolver,
    require_dev_header_auth_allowed,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleDecommissionBlockCommand,
    ModuleDecommissionCancelCommand,
    ModuleDecommissionCheck,
    ModuleDecommissionCompletionCommand,
    ModuleDecommissionReopenCommand,
    ModuleDecommissionRequestCommand,
    ModuleGateDecision,
    ModuleGateSurface,
    ModuleLifecycleCommand,
    ModuleLifecycleError,
    PlatformModulesResponse,
    TenantModuleAdminView,
    default_module_registry,
    tenant_module_admin_view,
)
from suite.platform.runtime import suite_auth_mode
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
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    role_ids: Annotated[str | None, Header(alias="X-Role-Ids")] = None,
    readable_object_ids: Annotated[str | None, Header(alias="X-Readable-Object-Ids")] = None,
) -> TenantRequestContext:
    auth_mode = suite_auth_mode()
    if auth_mode == "dev":
        return get_dev_header_tenant_request_context(
            request=request,
            tenant_id=tenant_id,
            user_id=user_id,
            role_ids=role_ids,
            readable_object_ids=readable_object_ids,
        )
    if auth_mode in {"jwt", "oidc"}:
        return get_jwt_tenant_request_context(request=request, authorization=authorization)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unsupported SUITE_AUTH_MODE: {auth_mode}",
    )


def get_dev_header_tenant_request_context(
    *,
    request: Request,
    tenant_id: str | None,
    user_id: str | None,
    role_ids: str | None,
    readable_object_ids: str | None,
) -> TenantRequestContext:
    try:
        require_dev_header_auth_allowed()
    except DevHeaderAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

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


def get_jwt_tenant_request_context(*, request: Request, authorization: str | None) -> TenantRequestContext:
    principal_resolver = request.app.state.principal_resolver
    try:
        user_context = principal_resolver.resolve_authorization_header(authorization)
    except (JwtAuthenticationError, PrincipalResolutionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
    try:
        tenant_policy = policy_repository.get(user_context.tenant_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant policy is not available",
        ) from exc
    return TenantRequestContext(user_context=user_context, tenant_policy=tenant_policy)


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


def require_module_api_gate(
    *,
    module_id: str,
    feature_id: str | None = None,
    compliance: bool = False,
) -> Callable[..., ModuleGateDecision]:
    surface = ModuleGateSurface.COMPLIANCE_API if compliance else ModuleGateSurface.NORMAL_API

    def dependency(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> ModuleGateDecision:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            return module_registry.require_module_gate(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                surface=surface,
                feature_id=feature_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return dependency


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
    migration_manifest = load_migration_manifest()
    embedding_model_admin = EmbeddingModelVersionAdminService(
        repository=embedding_model_registry,
        audit_logger=audit_logger,
    )
    principal_resolver = build_default_principal_resolver()

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

    def tenant_policy_snapshot_hash(policy: TenantPolicy) -> str:
        return stable_hash(canonical_json(policy.model_dump(mode="json")))

    def module_audit_ref(
        *,
        action: str,
        module_id: str,
        command: ModuleLifecycleCommand,
        context: TenantRequestContext,
        target_status: str,
    ) -> str:
        event = audit_logger.record(
            user_context=context.user_context,
            event_type=f"tenant_module.{action}",
            source_object_ids=[f"module:{module_id}"],
            input_text=command.reason,
            metadata={
                "module_id": module_id,
                "approval_reference": command.approval_reference,
                "target_status": target_status,
                "feature_count": len(command.enabled_features or {}),
            },
        )
        return f"audit:{event.event_id}"

    @app.post("/v1/admin/tenant-modules/{module_id}/provision", response_model=TenantModuleAdminView)
    def provision_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.provision_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="provisioned",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
                enabled_features=command.enabled_features,
                migration_manifest_entries=request.app.state.migration_manifest,
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/enable", response_model=TenantModuleAdminView)
    def enable_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.enable_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="enabled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="enabled",
                ),
                enabled_features=command.enabled_features,
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/disable", response_model=TenantModuleAdminView)
    def disable_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.disable_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="disabled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/suspend", response_model=TenantModuleAdminView)
    def suspend_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.suspend_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="suspended",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="suspended",
                ),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/admin/tenant-modules/{module_id}/decommission-check", response_model=ModuleDecommissionCheck)
    def check_tenant_module_decommission(
        module_id: str,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> ModuleDecommissionCheck:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            check = module_registry.decommission_check(tenant_id=context.user_context.tenant_id, module_id=module_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        audit_logger.record(
            user_context=context.user_context,
            event_type="tenant_module.decommission_check",
            source_object_ids=[f"module:{module_id}"],
            metadata={
                "module_id": module_id,
                "status": check.status,
                "can_decommission": check.can_decommission,
                "blocking_reason_count": len(check.blocking_reasons),
                "required_evidence_count": len(check.required_evidence),
            },
        )
        return check

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-request", response_model=TenantModuleAdminView)
    def request_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionRequestCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.request_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_requested",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_requested",
                ),
                decommission_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-block", response_model=TenantModuleAdminView)
    def block_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionBlockCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.block_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_blocked",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_blocked",
                ),
                blocker_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-cancel", response_model=TenantModuleAdminView)
    def cancel_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionCancelCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.cancel_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_cancelled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
                cancel_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-reopen", response_model=TenantModuleAdminView)
    def reopen_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionReopenCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.reopen_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_reopened",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_requested",
                ),
                reopen_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-complete", response_model=TenantModuleAdminView)
    def complete_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionCompletionCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.complete_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_completed",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommissioned",
                ),
                completion_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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
    app.state.migration_manifest = migration_manifest
    app.state.module_registry = module_registry
    app.state.principal_resolver = principal_resolver
    app.state.rag_pipeline = rag_pipeline
    app.state.tenant_policy_repository = tenant_policy_repository
    app.state.voice_guard = voice_guard

    return app


app = build_app()
