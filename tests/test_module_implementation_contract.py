import json
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_JSON = REPO_ROOT / "docs/modules/module_implementation_contract.json"
CONTRACT_DOC = REPO_ROOT / "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md"


def load_contract() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(CONTRACT_JSON.read_text(encoding="utf-8")))


def test_module_implementation_contract_defines_required_metadata() -> None:
    contract = load_contract()
    fields = set(contract["required_metadata_fields"])

    assert {
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
    } <= fields


def test_module_implementation_contract_defines_control_gates() -> None:
    contract = load_contract()
    controls = set(contract["required_controls"])

    assert {
        "tenant_context",
        "module_gate",
        "feature_gate",
        "object_read_authorization",
        "rls_enabled",
        "no_hard_delete",
        "audit_metadata_only",
        "backup_restore_domain",
        "restore_drill_evidence",
        "migration_evidence",
        "decommission_evidence",
        "candidate_only_search",
        "rag_authoritative_acl",
        "rag_source_citations",
        "local_llm_gateway",
        "tenant_ai_policy",
        "human_confirmation_for_destructive_actions",
        "voice_explicit_activation",
    } <= controls


def test_module_implementation_contract_prepares_future_modules() -> None:
    contract = load_contract()
    families = contract["future_module_families"]
    assert isinstance(families, list)

    by_family = {entry["module_family"]: entry for entry in families}

    assert {
        "knowledge_base",
        "lms",
        "tasks_activities",
        "tickets_incidents",
        "time_tracking",
    } <= set(by_family)

    for entry in families:
        assert entry["first_objects"]
        assert entry["first_slice"]
        assert entry["default_feature_gate"]
        assert entry["continuity_domain"]
        assert all("." in object_type for object_type in entry["first_objects"])


def test_module_implementation_contract_docs_cover_security_and_continuity() -> None:
    doc = CONTRACT_DOC.read_text(encoding="utf-8")

    for expected in (
        "Tenant Context",
        "module gate",
        "feature gate",
        "RLS",
        "Legal Hold",
        "Backup",
        "Restore",
        "Local LLM Gateway",
        "Candidate-only",
        "explicit human confirmation",
        "knowledge base",
        "LMS",
        "tasks and activities",
        "ticket",
        "Time tracking",
    ):
        assert expected.lower() in doc.lower()


def test_existing_module_planning_docs_reference_implementation_contract() -> None:
    required_paths = [
        REPO_ROOT / "docs/modules/MODULE_CHARTER_TEMPLATE.md",
        REPO_ROOT / "docs/ROADMAP.md",
        REPO_ROOT / "COMPLIANCE_MATRIX.md",
    ]
    optional_paths = [
        REPO_ROOT / "PLANS.md",
    ]

    for path in required_paths + [path for path in optional_paths if path.exists()]:
        assert "MODULE_IMPLEMENTATION_CONTRACT.md" in path.read_text(encoding="utf-8")
