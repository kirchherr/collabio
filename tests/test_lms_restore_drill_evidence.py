from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_restore_drill_evidence import (
    LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT,
    LMS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT,
    LMS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION,
    build_lms_restore_drill_evidence_hash,
    build_lms_restore_drill_evidence_response,
)
from suite.platform.modules import default_module_registry


def test_lms_restore_drill_evidence_verifies_metadata_schema_without_installing_lms() -> None:
    module_registry = default_module_registry()

    response = build_lms_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == LMS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION
    assert response.endpoint == LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    assert response.result_contract == LMS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.module_package_installed is False
    assert response.tenant_module_state_present is False
    assert response.migration_plan_ready is True
    assert response.catalog_registration_migration_present is True
    assert response.metadata_schema_migration_present is True
    assert response.approval_record_store_migration_present is True
    assert response.table_restore_verified is True
    assert response.approval_record_store_restore_verified is True
    assert response.job_outbox_migration_present is True
    assert response.job_outbox_restore_verified is True
    assert response.rls_restore_verified is True
    assert response.tenant_isolation_restore_verified is True
    assert response.retention_restore_verified is True
    assert response.legal_hold_restore_verified is True
    assert response.kms_reference_restore_verified is True
    assert response.audit_reference_restore_verified is True
    assert response.no_content_payload_restore_verified is True
    assert response.restore_evidence_ready is True
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.existing_lms_migration_versions == ("0045", "0046", "0047", "0048", "0049")
    assert response.restored_tables == (
        "lms.courses",
        "lms.enrollments",
        "lms.package_install_approval_records",
        "lms.dry_run_execution_approval_records",
        "lms.dry_run_execution_job_outbox",
    )
    assert response.restored_object_types == ("lms.course", "lms.enrollment")
    assert "lms_metadata_schema_migration_0046" in response.required_restore_evidence
    assert "lms_package_install_approval_record_store_migration_0047" in response.required_restore_evidence
    assert "lms_dry_run_execution_approval_record_store_migration_0048" in response.required_restore_evidence
    assert "lms_dry_run_execution_job_outbox_migration_0049" in response.required_restore_evidence
    assert "lms_dry_run_execution_job_outbox_restore_check" in response.required_restore_evidence
    assert "lms_approval_record_store_restore_check" in response.required_restore_evidence
    assert "no_lms_package_or_tenant_activation_confirmed" in response.required_restore_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash.startswith("sha256:")
    assert response.evidence_hash == build_lms_restore_drill_evidence_hash(response)
    assert response.summary.lms_manifest_migration_count == 5
    assert response.summary.restored_table_count == 5
    assert response.summary.restored_object_type_count == 2
    assert response.summary.required_restore_evidence_count == len(response.required_restore_evidence)
    assert response.summary.blocking_reason_count == 0
    assert "app/suite/platform/lms_restore_drill_evidence.py" in response.evidence_refs
    assert response.next_action == "capture_tenant_admin_package_install_approval_gate"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_restore_drill_evidence_is_tenant_scoped_without_state_side_effects() -> None:
    module_registry = default_module_registry()

    first = build_lms_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    second = build_lms_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.restore_evidence_ready is True
    assert second.restore_evidence_ready is True
    assert first.evidence_hash != second.evidence_hash
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="lms") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="lms") is None
