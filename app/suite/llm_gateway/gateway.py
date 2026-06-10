from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import InferenceRequest, InferenceResponse, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyEngine
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.llm_gateway.providers.base import LLMProvider


class LocalLLMGateway:
    def __init__(
        self,
        *,
        providers: dict[str, LLMProvider],
        model_registry: InMemoryModelRegistry,
        prompt_registry: InMemoryPromptRegistry,
        policy_engine: PolicyEngine,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.providers = providers
        self.model_registry = model_registry
        self.prompt_registry = prompt_registry
        self.policy_engine = policy_engine
        self.audit_logger = audit_logger

    def infer(
        self,
        *,
        request: InferenceRequest,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        sources_text: str = "",
    ) -> InferenceResponse:
        prompt_template = self.prompt_registry.get(request.prompt_template_id)
        model = self.policy_engine.authorize_inference(
            request=request,
            prompt_template=prompt_template,
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        provider = self.providers[model.provider]
        prompt = prompt_template.template.format(input_text=request.input_text, sources=sources_text)
        answer = provider.complete(model_id=model.model_id, prompt=prompt)
        audit_event = self.audit_logger.record(
            user_context=user_context,
            event_type="ai.inference",
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            source_object_ids=request.source_object_ids,
            input_text=request.input_text,
            output_text=answer,
            metadata={"purpose": request.purpose, "risk_level": request.risk_level},
        )
        return InferenceResponse(
            answer=answer,
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            audit_event_id=audit_event.event_id,
            requires_human_approval=self.policy_engine.requires_human_approval(request, tenant_policy),
            source_object_ids=request.source_object_ids,
        )
