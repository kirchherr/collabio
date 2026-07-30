from pathlib import Path

from suite.ai_control_plane.models import DataClass
from suite.platform.time_tracking_module import (
    TIME_APPROVALS_READ_FEATURE_ID,
    TIME_COMPLIANCE_EVIDENCE_FEATURE_ID,
    TIME_ENTRIES_READ_FEATURE_ID,
    TIME_ENTRIES_WRITE_FEATURE_ID,
    TIME_EXPORT_FEATURE_ID,
    TIME_TRACKING_CONTINUITY_DOMAIN,
    TIME_TRACKING_REQUIRED_OBJECT_METADATA_FIELDS,
    build_default_time_tracking_object_rule_manifest,
    build_default_time_tracking_subfeature_registry,
    default_time_tracking_enabled_features,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_time_tracking_registry_declares_guarded_first_slice() -> None:
    registry = build_default_time_tracking_subfeature_registry()

    assert registry.feature_ids == (
        TIME_ENTRIES_READ_FEATURE_ID,
        TIME_APPROVALS_READ_FEATURE_ID,
        TIME_ENTRIES_WRITE_FEATURE_ID,
        TIME_COMPLIANCE_EVIDENCE_FEATURE_ID,
        TIME_EXPORT_FEATURE_ID,
    )
    assert len(registry.features) == 5
    assert sum(feature.default_enabled for feature in registry.features) == 2
    assert sum(feature.requires_approval for feature in registry.features) == 3
    assert registry.enabled_feature_defaults == default_time_tracking_enabled_features()
    assert registry.manifest_hash.startswith("sha256:")

    write = registry.feature(TIME_ENTRIES_WRITE_FEATURE_ID)
    assert write.compliance_relevant is True
    assert write.dependency_feature_ids == (TIME_ENTRIES_READ_FEATURE_ID, TIME_APPROVALS_READ_FEATURE_ID)
    assert "atomic_entry_approval_acl_receipt_write" in write.evidence_required


def test_time_tracking_object_rules_bind_personal_records_to_continuity() -> None:
    registry = build_default_time_tracking_subfeature_registry()
    manifest = build_default_time_tracking_object_rule_manifest()
    manifest.validate_subfeature_registry(registry)

    assert tuple(rule.object_type for rule in manifest.object_rules) == ("time.entry", "time.approval")
    assert manifest.manifest_hash.startswith("sha256:")
    for rule in manifest.object_rules:
        assert rule.classification == DataClass.PERSONAL
        assert set(TIME_TRACKING_REQUIRED_OBJECT_METADATA_FIELDS).issubset(rule.required_metadata_fields)
        assert rule.rls_required and rule.audit_required and rule.legal_hold_supported
        assert rule.backup_domain_id == TIME_TRACKING_CONTINUITY_DOMAIN


def test_time_tracking_charter_documents_first_slice_and_deferred_effects() -> None:
    charter = (REPO_ROOT / "docs/modules/TIME_TRACKING_MODULE_CHARTER.md").read_text(encoding="utf-8")

    for expected in (
        "`time_tracking`",
        "time.entry",
        "time.approval",
        "not_submitted",
        "Tenant Context",
        "Legal Hold",
        "retention",
        "backup",
        "restore",
        "payroll",
        "human confirmation",
        "POST /v1/time-tracking/entries",
        "time_tracking_records",
    ):
        assert expected in charter
