import pytest

from suite.ai_control_plane.models import DataClass, InferenceRequest, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry


def test_ai_is_deny_by_default() -> None:
    model_registry = InMemoryModelRegistry.default()
    prompt_registry = InMemoryPromptRegistry.default()
    engine = PolicyEngine(model_registry=model_registry)
    request = InferenceRequest(input_text="Summarize this")
    policy = TenantPolicy(tenant_id="tenant-1")
    user = UserContext(user_id="user-1", tenant_id="tenant-1")

    with pytest.raises(PolicyViolation, match="AI is disabled"):
        engine.authorize_inference(
            request=request,
            prompt_template=prompt_registry.get(request.prompt_template_id),
            user_context=user,
            tenant_policy=policy,
        )


def test_policy_blocks_unregistered_tool() -> None:
    model_registry = InMemoryModelRegistry.default()
    prompt_registry = InMemoryPromptRegistry.default()
    engine = PolicyEngine(model_registry=model_registry)
    request = InferenceRequest(
        input_text="Send this mail",
        requested_tool="mail.send",
    )
    policy = TenantPolicy(
        tenant_id="tenant-1",
        ai_enabled=True,
        allowed_model_ids={"mock-summarizer"},
        allowed_data_classes={DataClass.INTERNAL},
    )
    user = UserContext(user_id="user-1", tenant_id="tenant-1", role_ids={"knowledge-worker"})

    with pytest.raises(PolicyViolation, match="tool is not registered"):
        engine.authorize_inference(
            request=request,
            prompt_template=prompt_registry.get(request.prompt_template_id),
            user_context=user,
            tenant_policy=policy,
        )


def test_policy_blocks_unauthorized_data_class() -> None:
    model_registry = InMemoryModelRegistry.default()
    prompt_registry = InMemoryPromptRegistry.default()
    engine = PolicyEngine(model_registry=model_registry)
    request = InferenceRequest(
        input_text="Summarize this",
        data_classes={DataClass.CONFIDENTIAL},
    )
    policy = TenantPolicy(
        tenant_id="tenant-1",
        ai_enabled=True,
        allowed_model_ids={"mock-summarizer"},
        allowed_data_classes={DataClass.INTERNAL},
    )
    user = UserContext(user_id="user-1", tenant_id="tenant-1")

    with pytest.raises(PolicyViolation, match="data classes"):
        engine.authorize_inference(
            request=request,
            prompt_template=prompt_registry.get(request.prompt_template_id),
            user_context=user,
            tenant_policy=policy,
        )
