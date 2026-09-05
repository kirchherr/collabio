from pathlib import Path

from suite.ai_control_plane.models import DataClass
from suite.platform.tasks_activities_module import (
    TASKS_ACTIVITIES_CONTINUITY_DOMAIN,
    TASKS_ACTIVITIES_REQUIRED_OBJECT_METADATA_FIELDS,
    TASKS_ACTIVITY_READ_FEATURE_ID,
    TASKS_AI_ASSIST_FEATURE_ID,
    TASKS_COMPLIANCE_EVIDENCE_FEATURE_ID,
    TASKS_ITEMS_READ_FEATURE_ID,
    TASKS_RAG_INDEXING_FEATURE_ID,
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
    TasksActivitiesSubfeatureArea,
    build_default_tasks_activities_object_rule_manifest,
    build_default_tasks_activities_subfeature_registry,
    default_tasks_activities_enabled_features,
    tasks_activities_object_rule_registry_summary,
    tasks_activities_subfeature_registry_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tasks_activities_subfeature_registry_declares_first_safe_feature_set() -> None:
    registry = build_default_tasks_activities_subfeature_registry()
    summary = tasks_activities_subfeature_registry_summary(registry)

    assert registry.feature_ids == (
        TASKS_ITEMS_READ_FEATURE_ID,
        TASKS_ACTIVITY_READ_FEATURE_ID,
        TASKS_WORKFLOW_WRITE_FEATURE_ID,
        TASKS_COMPLIANCE_EVIDENCE_FEATURE_ID,
        TASKS_RAG_INDEXING_FEATURE_ID,
        TASKS_AI_ASSIST_FEATURE_ID,
    )
    assert summary == {
        "module_id": "tasks_activities",
        "registry_version": "tasks_activities_subfeatures.v1",
        "feature_count": 6,
        "default_enabled_count": 2,
        "approval_required_count": 4,
        "compliance_relevant_count": 2,
        "manifest_hash": registry.manifest_hash,
    }
    assert registry.manifest_hash.startswith("sha256:")
    assert registry.enabled_feature_defaults == default_tasks_activities_enabled_features()

    compliance = registry.feature(TASKS_COMPLIANCE_EVIDENCE_FEATURE_ID)
    workflow_write = registry.feature(TASKS_WORKFLOW_WRITE_FEATURE_ID)
    rag = registry.feature(TASKS_RAG_INDEXING_FEATURE_ID)
    ai_assist = registry.feature(TASKS_AI_ASSIST_FEATURE_ID)

    assert workflow_write.requires_approval
    assert workflow_write.compliance_relevant
    assert workflow_write.dependency_feature_ids == (
        TASKS_ITEMS_READ_FEATURE_ID,
        TASKS_ACTIVITY_READ_FEATURE_ID,
    )
    assert compliance.area == TasksActivitiesSubfeatureArea.COMPLIANCE
    assert compliance.requires_approval
    assert compliance.compliance_relevant
    assert "compliance_worker" in compliance.worker_surfaces
    assert "legal_hold_check" in compliance.evidence_required

    assert rag.requires_approval
    assert rag.dependency_feature_ids == (TASKS_ITEMS_READ_FEATURE_ID, TASKS_ACTIVITY_READ_FEATURE_ID)
    assert "authoritative_acl_validation" in rag.evidence_required

    assert ai_assist.requires_approval
    assert ai_assist.dependency_feature_ids == (TASKS_RAG_INDEXING_FEATURE_ID,)
    assert "local_llm_gateway_audit" in ai_assist.evidence_required


def test_tasks_activities_object_rules_enforce_module_contract_before_tables_or_api() -> None:
    registry = build_default_tasks_activities_subfeature_registry()
    manifest = build_default_tasks_activities_object_rule_manifest()
    summary = tasks_activities_object_rule_registry_summary(manifest)

    assert tuple(rule.object_type for rule in manifest.object_rules) == ("task.task", "task.activity")
    assert summary == {
        "module_id": "tasks_activities",
        "registry_version": "tasks_activities_object_rules.v1",
        "object_type_count": 2,
        "personal_object_type_count": 2,
        "manifest_hash": manifest.manifest_hash,
    }
    assert manifest.manifest_hash.startswith("sha256:")
    manifest.validate_subfeature_registry(registry)

    for rule in manifest.object_rules:
        assert set(TASKS_ACTIVITIES_REQUIRED_OBJECT_METADATA_FIELDS).issubset(rule.required_metadata_fields)
        assert rule.rls_required
        assert rule.audit_required
        assert rule.kms_key_ref_required
        assert rule.legal_hold_supported
        assert rule.search_candidate_only
        assert not rule.rag_indexing_default_enabled
        assert rule.destructive_actions_require_approval
        assert rule.backup_domain_id == TASKS_ACTIVITIES_CONTINUITY_DOMAIN

    assert manifest.rule("task.task").classification == DataClass.PERSONAL
    assert manifest.rule("task.activity").classification == DataClass.PERSONAL


def test_tasks_activities_module_charter_documents_contract_gates_and_deferred_scope() -> None:
    charter = (REPO_ROOT / "docs/modules/TASKS_ACTIVITIES_MODULE_CHARTER.md").read_text(encoding="utf-8")

    for expected in (
        "`tasks_activities`",
        "Tenant Context",
        "feature permission",
        "object authorization",
        "Legal Hold",
        "retention",
        "backup",
        "restore",
        "candidate IDs only",
        "Local LLM Gateway",
        "POST /v1/tasks/items",
        "/v1/platform/modules/families/tasks-activities/catalog-readiness",
        "task_activity_records",
        "0050_tasks_activities_catalog_registration.sql",
        "0059_tasks_activities_productive_slice.sql",
        "task.task",
        "task.activity",
        "notifications",
        "workflow automations",
    ):
        assert expected in charter
