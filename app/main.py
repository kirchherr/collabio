import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import (
    InferenceRequest,
    InferenceResponse,
    UserContext,
)
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import (
    InMemoryModelRegistry,
    InMemoryPromptRegistry,
    InMemoryToolPermissionRegistry,
)
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.llm_gateway.providers.ollama import OllamaProvider
from suite.llm_gateway.providers.openai_compatible import OpenAICompatibleProvider
from suite.platform.context import TenantRequestContext
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.rag.models import RagQuery, RagResponse
from suite.rag.pipeline import RagPipeline
from suite.rag.repositories import InMemoryAclAuthorizer, InMemorySourceRepository, InMemoryVectorStore
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


def build_app() -> FastAPI:
    app = FastAPI(title="Compliance-First Enterprise Suite", version="0.1.0")

    audit_logger = InMemoryAuditLogger()
    model_registry = InMemoryModelRegistry.default()
    prompt_registry = InMemoryPromptRegistry.default()
    tool_permission_registry = InMemoryToolPermissionRegistry.default()
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
    tenant_policy_repository = InMemoryTenantPolicyRepository.default()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
    app.state.rag_pipeline = rag_pipeline
    app.state.tenant_policy_repository = tenant_policy_repository
    app.state.voice_guard = voice_guard

    return app


app = build_app()
