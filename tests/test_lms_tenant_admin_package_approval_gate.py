from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_tenant_admin_package_approval_gate import (
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_ENDPOINT,
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_RESULT_CONTRACT,
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_SCHEMA_VERSION,
    build_lms_tenant_admin_package_approval_gate_hash,
    build_lms_tenant_admin_package_approval_gate_response,
)
from suite.platform.modules import default_module_registry


def test_lms_tenant_admin_package_approval_gate_allows_human_record_without_installing_lms() -> None:
    module_registry = default_module_registry()

    response = build_lms_tenant_admin_package_approval_gate_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"tenant_admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_SCHEMA_VERSION
    assert response.endpoint == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_ENDPOINT
    assert response.result_contract == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.module_package_installed is False
    assert response.tenant_module_state_present is False
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.lms_restore_drill_evidence_endpoint == "/v1/platform/modules/families/lms/restore-drill-evidence"
    assert response.lms_restore_drill_evidence_hash is not None
    assert response.lms_restore_drill_evidence_hash.startswith("sha256:")
    assert response.approval_gate_ready is True
    assert response.human_approval_record_allowed is True
    assert response.human_approval_record_created is False
    assert response.human_approval_ready is False
    assert response.package_installation_ready is False
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.lms_business_api_allowed is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.existing_lms_migration_versions == ("0045", "0046", "0047", "0048", "0049")
    assert "install_lms_package_for_tenant" in response.approval_scope
    assert "bind_lms_restore_drill_evidence_hash" in response.approval_scope
    assert "tenant_admin_identity" in response.required_approval_evidence
    assert "future_installation_execution_gate_required" in response.required_approval_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash.startswith("sha256:")
    assert response.evidence_hash == build_lms_tenant_admin_package_approval_gate_hash(response)
    assert response.summary.lms_manifest_migration_count == 5
    assert response.summary.required_approval_evidence_count == len(response.required_approval_evidence)
    assert response.summary.approval_scope_count == len(response.approval_scope)
    assert response.summary.blocking_reason_count == 0
    assert "app/suite/platform/lms_tenant_admin_package_approval_gate.py" in response.evidence_refs
    assert response.next_action == "record_tenant_admin_package_install_approval_with_explicit_human_confirmation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_tenant_admin_package_approval_gate_is_tenant_scoped_without_state_side_effects() -> None:
    module_registry = default_module_registry()

    first = build_lms_tenant_admin_package_approval_gate_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"tenant_admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    second = build_lms_tenant_admin_package_approval_gate_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"tenant_admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.approval_gate_ready is True
    assert second.approval_gate_ready is True
    assert first.human_approval_record_created is False
    assert second.human_approval_record_created is False
    assert first.evidence_hash != second.evidence_hash
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="lms") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="lms") is None
