from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.lms_module import (
    LMS_AI_ASSIST_FEATURE_ID,
    LMS_COMPLETION_EVIDENCE_FEATURE_ID,
    LMS_CONTINUITY_DOMAIN,
    LMS_COURSES_READ_FEATURE_ID,
    LMS_ENROLLMENTS_READ_FEATURE_ID,
    LMS_RAG_INDEXING_FEATURE_ID,
    LMS_REQUIRED_OBJECT_METADATA_FIELDS,
    LmsSubfeatureArea,
    build_default_lms_object_rule_manifest,
    build_default_lms_subfeature_registry,
    default_lms_enabled_features,
    lms_object_rule_registry_summary,
    lms_subfeature_registry_summary,
)
from suite.platform.modules import ModuleLifecycleError, ModuleStatus, default_module_registry

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_lms_subfeature_registry_declares_first_safe_feature_set() -> None:
    registry = build_default_lms_subfeature_registry()
    summary = lms_subfeature_registry_summary(registry)

    assert registry.feature_ids == (
        LMS_COURSES_READ_FEATURE_ID,
        LMS_ENROLLMENTS_READ_FEATURE_ID,
        LMS_COMPLETION_EVIDENCE_FEATURE_ID,
        LMS_RAG_INDEXING_FEATURE_ID,
        LMS_AI_ASSIST_FEATURE_ID,
    )
    assert summary == {
        "module_id": "lms",
        "registry_version": "lms_subfeatures.v1",
        "feature_count": 5,
        "default_enabled_count": 2,
        "approval_required_count": 3,
        "compliance_relevant_count": 1,
        "manifest_hash": registry.manifest_hash,
    }
    assert registry.manifest_hash.startswith("sha256:")
    assert registry.enabled_feature_defaults == default_lms_enabled_features()

    completion = registry.feature(LMS_COMPLETION_EVIDENCE_FEATURE_ID)
    rag = registry.feature(LMS_RAG_INDEXING_FEATURE_ID)
    ai_assist = registry.feature(LMS_AI_ASSIST_FEATURE_ID)

    assert completion.area == LmsSubfeatureArea.COMPLIANCE
    assert completion.requires_approval
    assert completion.compliance_relevant
    assert "compliance_worker" in completion.worker_surfaces
    assert "legal_hold_check" in completion.evidence_required

    assert rag.requires_approval
    assert rag.dependency_feature_ids == (LMS_COURSES_READ_FEATURE_ID, LMS_ENROLLMENTS_READ_FEATURE_ID)
    assert "authoritative_acl_validation" in rag.evidence_required

    assert ai_assist.requires_approval
    assert ai_assist.dependency_feature_ids == (LMS_RAG_INDEXING_FEATURE_ID,)
    assert "local_llm_gateway_audit" in ai_assist.evidence_required


def test_lms_object_rules_enforce_module_contract_before_tables_or_api() -> None:
    registry = build_default_lms_subfeature_registry()
    manifest = build_default_lms_object_rule_manifest()
    summary = lms_object_rule_registry_summary(manifest)

    assert tuple(rule.object_type for rule in manifest.object_rules) == (
        "lms.course",
        "lms.enrollment",
        "lms.completion_evidence",
    )
    assert summary == {
        "module_id": "lms",
        "registry_version": "lms_object_rules.v1",
        "object_type_count": 3,
        "personal_object_type_count": 2,
        "manifest_hash": manifest.manifest_hash,
    }
    assert manifest.manifest_hash.startswith("sha256:")
    manifest.validate_subfeature_registry(registry)

    for rule in manifest.object_rules:
        assert set(LMS_REQUIRED_OBJECT_METADATA_FIELDS).issubset(rule.required_metadata_fields)
        assert rule.rls_required
        assert rule.audit_required
        assert rule.kms_key_ref_required
        assert rule.legal_hold_supported
        assert rule.search_candidate_only
        assert not rule.rag_indexing_default_enabled
        assert rule.destructive_actions_require_approval
        assert rule.backup_domain_id == LMS_CONTINUITY_DOMAIN

    assert manifest.rule("lms.course").classification == DataClass.INTERNAL
    assert manifest.rule("lms.enrollment").classification == DataClass.PERSONAL
    assert manifest.rule("lms.completion_evidence").classification == DataClass.PERSONAL


def test_lms_foundation_registers_catalog_entry_without_install_or_tenant_activation() -> None:
    module_registry = default_module_registry()

    catalog_entry = module_registry.get_catalog_entry("lms")

    assert catalog_entry.status == ModuleStatus.NOT_INSTALLED
    assert catalog_entry.required_migration_versions == ("0007", "0008", "0009", "0010", "0011", "0046")
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None

    with pytest.raises(ModuleLifecycleError, match="Module is not installed: lms"):
        module_registry.provision_tenant_module(
            tenant_id="tenant-demo",
            module_id="lms",
            policy_snapshot_hash="sha256:lms-demo-policy",
            changed_by="tenant-admin",
            audit_chain_ref="audit:lms-provision-blocked",
            enabled_features=default_lms_enabled_features(),
        )


def test_lms_module_charter_documents_contract_gates_and_deferred_scope() -> None:
    charter = (REPO_ROOT / "docs/modules/LMS_MODULE_CHARTER.md").read_text(encoding="utf-8")

    for expected in (
        "`lms`",
        "Tenant Context",
        "feature permission",
        "object authorization",
        "Legal Hold",
        "retention",
        "backup",
        "restore",
        "candidate IDs only",
        "Local LLM Gateway",
        "No LMS API route is enabled by this charter",
        "lms_training_records",
        "package-installation-readiness",
        "package-installation-executor-skeleton",
        "package-installation-dry-run-plan",
        "package-installation-dry-run-execution-boundary",
        "package-installation-dry-run-execution-skeleton",
        "package-installation-dry-run-executor-implementation-review",
        "package-installation-dry-run-result-contract",
        "package-installation-dry-run-execution-gate",
        "package-installation-dry-run-execution-request-boundary",
        "package-installation-dry-run-executor-runtime-boundary",
        "package-installation-dry-run-execution-preflight",
        "package-installation-dry-run-execution-receipt-boundary",
        "package-installation-dry-run-result-persistence-boundary",
        "package-installation-dry-run-execution-activation-boundary",
        "package-installation-dry-run-execution-start-boundary",
        "package-installation-dry-run-execution-dispatch-boundary",
        "package-installation-dry-run-execution-worker-boundary",
        "package-installation-dry-run-execution-final-readiness-gate",
        "package-installation-dry-run-execution-approval-boundary",
        "SCORM/xAPI runtime",
    ):
        assert expected in charter
