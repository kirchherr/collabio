from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_readiness import (
    LMS_PACKAGE_INSTALLATION_READINESS_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_READINESS_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_READINESS_SCHEMA_VERSION,
    build_lms_package_installation_readiness_response,
)
from suite.platform.modules import default_module_registry


def test_lms_package_installation_readiness_blocks_install_until_approval_exists() -> None:
    response = build_lms_package_installation_readiness_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_READINESS_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_READINESS_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_READINESS_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.module_package_installed is False
    assert response.tenant_module_state_present is False
    assert response.package_installation_ready is False
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.human_approval_ready is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.lms_business_api_allowed is False
    assert response.content_included is False
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.existing_lms_migration_versions == ("0045", "0046", "0047", "0048", "0049")
    assert response.existing_lms_business_migration_versions == ("0046", "0049")
    assert response.planned_first_object_types == ("lms.course", "lms.enrollment")
    assert response.lms_restore_drill_evidence_endpoint == "/v1/platform/modules/families/lms/restore-drill-evidence"
    assert response.lms_restore_drill_evidence_hash is not None
    assert response.lms_restore_drill_evidence_hash.startswith("sha256:")
    assert (
        response.tenant_admin_approval_gate_endpoint
        == "/v1/platform/modules/families/lms/tenant-admin-package-approval-gate"
    )
    assert response.tenant_admin_approval_gate_hash is not None
    assert response.tenant_admin_approval_gate_hash.startswith("sha256:")
    assert response.tenant_admin_approval_gate_ready is True
    assert response.tenant_admin_approval_record_allowed is True
    assert (
        response.tenant_admin_approval_record_endpoint
        == "/v1/platform/modules/families/lms/tenant-admin-package-approval-records"
    )
    assert response.tenant_admin_approval_record_hash is None
    assert "lms_metadata_schema_migration_sql" in response.required_installation_evidence
    assert "lms_restore_drill_evidence_hash" in response.required_installation_evidence
    assert "tenant_admin_package_install_approval_gate_hash" in response.required_installation_evidence
    assert "tenant_admin_package_install_approval_record_hash" in response.required_installation_evidence
    assert "lms_business_metadata_migration_missing" not in response.blocking_reasons
    assert "lms_backup_restore_drill_evidence_missing" not in response.blocking_reasons
    assert "tenant_admin_package_install_approval_gate_missing" not in response.blocking_reasons
    assert "tenant_admin_package_install_approval_missing" in response.blocking_reasons
    assert response.summary.lms_manifest_migration_count == 5
    assert response.summary.lms_business_migration_count == 2
    assert response.summary.blocking_reason_count == len(response.blocking_reasons)
    assert "app/suite/platform/lms_package_installation_readiness.py" in response.evidence_refs
    assert response.next_action == "record_tenant_admin_package_install_approval_with_explicit_human_confirmation"


def test_lms_package_installation_readiness_is_tenant_scoped_without_state_side_effects() -> None:
    module_registry = default_module_registry()

    first = build_lms_package_installation_readiness_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    second = build_lms_package_installation_readiness_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.existing_lms_migration_versions == second.existing_lms_migration_versions
    assert first.package_installation_ready is False
    assert second.package_installation_ready is False
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="lms") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="lms") is None
