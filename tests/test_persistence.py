import json
from pathlib import Path

from suite.ai_control_plane.audit import JsonlAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.ai_control_plane.registries import (
    InMemoryModelRegistry,
    InMemoryPromptRegistry,
    InMemoryToolPermissionRegistry,
    JsonFileModelRegistry,
    JsonFilePromptRegistry,
    JsonFileToolPermissionRegistry,
)
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository, JsonFileTenantPolicyRepository


def test_json_registries_seed_and_reload(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registries"

    model_registry = JsonFileModelRegistry.load_or_seed(
        registry_dir / "models.json",
        seed=InMemoryModelRegistry.default(),
    )
    prompt_registry = JsonFilePromptRegistry.load_or_seed(
        registry_dir / "prompts.json",
        seed=InMemoryPromptRegistry.default(),
    )
    tool_registry = JsonFileToolPermissionRegistry.load_or_seed(
        registry_dir / "tool_permissions.json",
        seed=InMemoryToolPermissionRegistry.default(),
    )
    tenant_repository = JsonFileTenantPolicyRepository.load_or_seed(
        registry_dir / "tenant_policies.json",
        seed=InMemoryTenantPolicyRepository.default(),
    )

    assert model_registry.get("mock-summarizer").provider == "mock"
    assert prompt_registry.get("rag_answer_v1").required_sources
    assert tool_registry.get("legal_hold.set").requires_human_approval
    assert tenant_repository.get("tenant-demo").ai_enabled

    updated_policy = tenant_repository.get("tenant-demo").model_copy(update={"external_ai_enabled": True})
    tenant_repository.update(updated_policy)

    reloaded_models = JsonFileModelRegistry.load_or_seed(
        registry_dir / "models.json",
        seed=InMemoryModelRegistry(models={}),
    )
    reloaded_tenants = JsonFileTenantPolicyRepository.load_or_seed(
        registry_dir / "tenant_policies.json",
        seed=InMemoryTenantPolicyRepository(policies={}),
    )
    assert reloaded_models.get("mock-summarizer").checksum == "sha256:mock"
    assert reloaded_tenants.get("tenant-demo").external_ai_enabled


def test_prompt_registry_adds_missing_system_prompts_without_overwriting_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "prompts.json"
    seed = InMemoryPromptRegistry.default()
    existing = seed.get("document_summary_v1").model_copy(update={"version": "tenant-pinned"})
    path.write_text(json.dumps([existing.model_dump(mode="json")]), encoding="utf-8")

    registry = JsonFilePromptRegistry.load_or_seed(path, seed=seed)

    assert registry.get("document_summary_v1").version == "tenant-pinned"
    assert registry.get("document_rewrite_v1").approval_status == "approved"
    assert registry.get("document_tone_professional_v1").approval_status == "approved"
    assert registry.get("document_translate_de_v1").approval_status == "approved"
    assert registry.get("document_translate_uk_v1").approval_status == "approved"
    assert registry.get("document_outline_concise_v1").approval_status == "approved"
    assert registry.get("document_outline_detailed_v1").approval_status == "approved"
    assert registry.get("document_policy_comparison_v1").approval_status == "approved"
    assert registry.get("document_risk_marking_v1").approval_status == "approved"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert next(row for row in stored if row["prompt_template_id"] == "document_summary_v1")["version"] == (
        "tenant-pinned"
    )


def test_jsonl_audit_logger_persists_and_reloads_chain(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit" / "events.jsonl"
    user = UserContext(user_id="user-1", tenant_id="tenant-1")

    logger = JsonlAuditLogger.load(audit_path)
    first = logger.record(user_context=user, event_type="ai.inference", input_text="prompt")
    second = logger.record(user_context=user, event_type="rag.retrieval", input_text="question")

    assert audit_path.exists()
    assert second.previous_event_hash == first.event_hash

    reloaded = JsonlAuditLogger.load(audit_path)
    result = reloaded.verify()
    assert result.ok
    assert result.verified_events == 2
    assert reloaded.events[0].event_hash == first.event_hash
