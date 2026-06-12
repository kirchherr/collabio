from __future__ import annotations

import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import default_crm_erp_target_profiles
from suite.platform.crm_erp_object_rules import (
    CRM_ERP_SCHEMA_NAMES,
    REQUIRED_OBJECT_METADATA_FIELDS,
    CrmErpLifecycleState,
    CrmErpObjectRule,
    CrmErpObjectRuleError,
    CrmErpObjectRuleManifest,
    build_default_crm_erp_object_rule_manifest,
    crm_erp_object_rule_registry_summary,
)
from suite.platform.crm_erp_subfeatures import build_default_crm_erp_subfeature_registry


def test_default_crm_erp_object_rule_manifest_declares_schema_and_object_plan() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()
    summary = crm_erp_object_rule_registry_summary(manifest)

    assert tuple(schema.schema_name for schema in manifest.schemas) == CRM_ERP_SCHEMA_NAMES
    assert tuple(rule.object_type for rule in manifest.object_rules) == (
        "crm.account",
        "crm.contact",
        "crm.activity",
        "crm.note",
        "erp.product",
        "erp.supplier",
        "erp.order",
        "erp.order_item",
        "erp.invoice",
        "erp.invoice_item",
        "erp.delivery_note",
        "erp.contract",
        "legacy.row",
    )
    assert manifest.schema_definition("crm").owns_object_types == (
        "crm.account",
        "crm.activity",
        "crm.contact",
        "crm.note",
    )
    assert manifest.schema_definition("erp").owns_object_types == (
        "erp.contract",
        "erp.delivery_note",
        "erp.invoice",
        "erp.invoice_item",
        "erp.order",
        "erp.order_item",
        "erp.product",
        "erp.supplier",
    )
    assert summary == {
        "module_id": "crm_erp",
        "registry_version": "crm_erp_object_rules.v1",
        "schema_count": 4,
        "object_type_count": 13,
        "gobd_object_type_count": 6,
        "legacy_object_type_count": 1,
        "manifest_hash": manifest.manifest_hash,
    }
    assert manifest.manifest_hash.startswith("sha256:")


def test_crm_erp_object_rules_match_mapping_profiles_and_subfeatures() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()

    manifest.validate_target_profiles(default_crm_erp_target_profiles())
    manifest.validate_subfeature_registry(build_default_crm_erp_subfeature_registry())

    for object_type, profile in default_crm_erp_target_profiles().items():
        rule = manifest.rule(object_type)
        assert rule.feature_id == profile.feature_id
        assert rule.classification == profile.classification
        assert rule.retention_policy_id == profile.retention_policy_id
        assert rule.gobd_relevant == profile.gobd_relevant


def test_crm_erp_object_rules_enforce_core_compliance_metadata_and_boundaries() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()

    for rule in manifest.object_rules:
        assert set(REQUIRED_OBJECT_METADATA_FIELDS).issubset(rule.required_metadata_fields)
        assert rule.rls_required
        assert rule.audit_required
        assert rule.kms_key_ref_required
        assert rule.legal_hold_supported
        assert rule.source_system_required
        assert rule.search_candidate_only
        assert not rule.rag_indexing_default_enabled
        assert not rule.raw_import_payload_allowed
        assert rule.destructive_actions_require_approval
        assert rule.backup_domain_id == "crm_erp_business_records"

    invoice = manifest.rule("erp.invoice")
    assert invoice.schema_name == "erp"
    assert invoice.classification == DataClass.GOBD
    assert invoice.retention_policy_id == "rp-gobd-10y"
    assert invoice.gobd_relevant
    assert invoice.worm_candidate
    assert CrmErpLifecycleState.RECORD in invoice.lifecycle_states

    legacy_row = manifest.rule("legacy.row")
    assert legacy_row.schema_name == "crm_erp_legacy"
    assert legacy_row.classification == DataClass.CONFIDENTIAL
    assert legacy_row.retention_policy_id == "rp-restricted"
    assert CrmErpLifecycleState.QUARANTINED in legacy_row.lifecycle_states


def test_crm_erp_object_rule_manifest_rejects_schema_drift() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()
    broken_schema = manifest.schemas[1].model_copy(update={"owns_object_types": ("crm.account",)})

    with pytest.raises(ValueError, match="owns_object_types"):
        CrmErpObjectRuleManifest(
            schemas=(manifest.schemas[0], broken_schema, *manifest.schemas[2:]),
            object_rules=manifest.object_rules,
            manifest_hash="sha256:broken",
        )


def test_crm_erp_object_rule_rejects_gobd_without_gobd_retention() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()
    invoice = manifest.rule("erp.invoice")

    with pytest.raises(ValueError, match="GoBD"):
        CrmErpObjectRule.model_validate(invoice.model_copy(update={"retention_policy_id": "rp-standard"}).model_dump())


def test_crm_erp_object_rules_detect_profile_drift() -> None:
    manifest = build_default_crm_erp_object_rule_manifest()
    profiles = default_crm_erp_target_profiles()
    drifted_profile = profiles["crm.account"].model_copy(update={"retention_policy_id": "rp-restricted"})

    with pytest.raises(CrmErpObjectRuleError, match="retention drift"):
        manifest.validate_target_profiles({**profiles, "crm.account": drifted_profile})
