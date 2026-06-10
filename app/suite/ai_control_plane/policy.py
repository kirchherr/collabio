from suite.ai_control_plane.models import InferenceRequest, ModelConfig, PromptTemplate, TenantPolicy, UserContext
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryToolPermissionRegistry


class PolicyViolation(Exception):
    """Raised when an AI, RAG, or voice request violates tenant policy."""


class PolicyEngine:
    def __init__(
        self,
        model_registry: InMemoryModelRegistry,
        tool_permission_registry: InMemoryToolPermissionRegistry | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.tool_permission_registry = tool_permission_registry or InMemoryToolPermissionRegistry.default()

    def require_tenant_match(self, user_context: UserContext, tenant_policy: TenantPolicy) -> None:
        if user_context.tenant_id != tenant_policy.tenant_id:
            raise PolicyViolation("User tenant does not match tenant policy")

    def authorize_inference(
        self,
        *,
        request: InferenceRequest,
        prompt_template: PromptTemplate,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
    ) -> ModelConfig:
        self.require_tenant_match(user_context, tenant_policy)
        if not tenant_policy.ai_enabled:
            raise PolicyViolation("AI is disabled for this tenant")
        model = self.model_registry.get(request.model_id)
        if model.model_id not in tenant_policy.allowed_model_ids:
            raise PolicyViolation("Model is not allowed for this tenant")
        if request.purpose in model.blocked_for:
            raise PolicyViolation("Model is blocked for this purpose")
        if request.purpose not in model.approved_for:
            raise PolicyViolation("Model is not approved for this purpose")
        if not request.data_classes <= tenant_policy.allowed_data_classes:
            raise PolicyViolation("Tenant policy blocks one or more data classes")
        if not request.data_classes <= model.allowed_data_classes:
            raise PolicyViolation("Model blocks one or more data classes")
        if not request.data_classes <= prompt_template.allowed_data_classes:
            raise PolicyViolation("Prompt template blocks one or more data classes")
        unauthorized_sources = set(request.source_object_ids) - user_context.readable_object_ids
        if unauthorized_sources:
            raise PolicyViolation("User cannot read one or more requested sources")
        if request.requested_tool:
            self.authorize_tool(requested_tool=request.requested_tool, user_context=user_context)
        return model

    def requires_human_approval(self, request: InferenceRequest, tenant_policy: TenantPolicy) -> bool:
        if request.risk_level in tenant_policy.human_approval_required_for:
            return True
        if request.requested_tool:
            permission = self.tool_permission_registry.get(request.requested_tool)
            return permission.requires_human_approval or permission.risk_level in tenant_policy.human_approval_required_for
        return False

    def authorize_tool(self, *, requested_tool: str, user_context: UserContext) -> None:
        try:
            permission = self.tool_permission_registry.get(requested_tool)
        except LookupError as exc:
            raise PolicyViolation("Requested tool is not registered") from exc
        if user_context.role_ids.isdisjoint(permission.allowed_role_ids):
            raise PolicyViolation("User role cannot use requested tool")

    def authorize_rag(self, *, user_context: UserContext, tenant_policy: TenantPolicy) -> None:
        self.require_tenant_match(user_context, tenant_policy)
        if not tenant_policy.ai_enabled:
            raise PolicyViolation("AI is disabled for this tenant")
        if not tenant_policy.rag_enabled:
            raise PolicyViolation("RAG is disabled for this tenant")

    def authorize_voice(self, *, user_context: UserContext, tenant_policy: TenantPolicy) -> None:
        self.require_tenant_match(user_context, tenant_policy)
        if not tenant_policy.voice_enabled:
            raise PolicyViolation("Voice is disabled for this tenant")
