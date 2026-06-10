import os

from fastapi import FastAPI, HTTPException

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import (
    DataClass,
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
)
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.llm_gateway.providers.ollama import OllamaProvider
from suite.llm_gateway.providers.openai_compatible import OpenAICompatibleProvider
from suite.rag.models import RagQuery, RagResponse
from suite.rag.pipeline import RagPipeline
from suite.rag.repositories import InMemoryAclAuthorizer, InMemorySourceRepository, InMemoryVectorStore
from suite.voice.models import VoiceTranscriptRequest, VoiceTranscriptResponse
from suite.voice.privacy import VoicePrivacyGuard


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

    default_policy = TenantPolicy(
        tenant_id="tenant-demo",
        ai_enabled=True,
        allowed_model_ids={"mock-summarizer"},
        allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL},
        rag_enabled=True,
        voice_enabled=True,
        raw_audio_storage_allowed=False,
    )
    default_user = UserContext(
        user_id="user-demo",
        tenant_id="tenant-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"doc-1", "mail-1"},
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/ai/inference", response_model=InferenceResponse)
    def infer(request: InferenceRequest) -> InferenceResponse:
        try:
            return llm_gateway.infer(
                request=request,
                user_context=default_user,
                tenant_policy=default_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/rag/query", response_model=RagResponse)
    def rag_query(query: RagQuery) -> RagResponse:
        try:
            return rag_pipeline.answer(
                query=query,
                user_context=default_user,
                tenant_policy=default_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/voice/transcripts", response_model=VoiceTranscriptResponse)
    def voice_transcript(request: VoiceTranscriptRequest) -> VoiceTranscriptResponse:
        try:
            return voice_guard.accept_transcript(
                request=request,
                user_context=default_user,
                tenant_policy=default_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    app.state.audit_logger = audit_logger
    app.state.llm_gateway = llm_gateway
    app.state.rag_pipeline = rag_pipeline
    app.state.voice_guard = voice_guard

    return app


app = build_app()
