from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import InMemoryModuleRegistry, default_module_registry
from suite.platform.tickets_incidents_restore_drill_evidence import (
    TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_ENDPOINT,
    TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT,
    TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION,
    build_tickets_incidents_restore_drill_evidence_hash,
    build_tickets_incidents_restore_drill_evidence_response,
)


def test_tickets_incidents_restore_drill_evidence_verifies_metadata_schema_without_activation() -> None:
    module_registry = default_module_registry()

    response = build_tickets_incidents_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.module_package_installed is False
    assert response.tenant_module_state_present is False
    assert response.storage_migration_evidence_ready is True
    assert response.migration_plan_ready is True
    assert response.catalog_registration_migration_present is True
    assert response.metadata_schema_migration_present is True
    assert response.approval_record_migration_present is True
    assert response.approval_record_restore_verified is True
    assert response.table_restore_verified is True
    assert response.rls_restore_verified is True
    assert response.tenant_isolation_restore_verified is True
    assert response.retention_restore_verified is True
    assert response.legal_hold_restore_verified is True
    assert response.kms_reference_restore_verified is True
    assert response.audit_reference_restore_verified is True
    assert response.sla_state_restore_verified is True
    assert response.no_content_payload_restore_verified is True
    assert response.restore_evidence_ready is True
    assert response.tenant_provisioning_allowed is False
    assert response.tickets_business_api_allowed is False
    assert response.worker_activation_allowed is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.existing_tickets_migration_versions == ("0051", "0052", "0053")
    assert response.restored_tables == (
        "tickets.ticket_items",
        "tickets.ticket_events",
        "tickets.activation_dry_run_execution_approval_records",
    )
    assert response.restored_object_types == ("ticket.ticket", "ticket.event")
    assert "tickets_incidents_metadata_schema_migration_0052" in response.required_restore_evidence
    assert "tickets_incidents_approval_record_migration_0053" in response.required_restore_evidence
    assert "tickets_activation_approval_record_append_only_restore_check" in response.required_restore_evidence
    assert "tickets_items_table_restore_check" in response.required_restore_evidence
    assert "tickets_events_table_restore_check" in response.required_restore_evidence
    assert "tickets_tenant_rls_restore_check" in response.required_restore_evidence
    assert "tickets_sla_state_restore_check" in response.required_restore_evidence
    assert "ticket_incident_records_backup_restore_policy_update" in response.required_restore_evidence
    assert "no_tickets_content_payload_restore_confirmed" in response.required_restore_evidence
    assert "no_tickets_tenant_activation_or_worker_confirmed" in response.required_restore_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash.startswith("sha256:")
    assert response.evidence_hash == build_tickets_incidents_restore_drill_evidence_hash(response)
    assert response.summary.tickets_manifest_migration_count == 3
    assert response.summary.restored_table_count == 3
    assert response.summary.restored_object_type_count == 2
    assert response.summary.required_restore_evidence_count == len(response.required_restore_evidence)
    assert response.summary.blocking_reason_count == 0
    assert "app/suite/platform/tickets_incidents_restore_drill_evidence.py" in response.evidence_refs
    assert "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql" in response.evidence_refs
    assert (
        "app/suite/persistence/migrations/0053_tickets_incidents_dry_run_execution_approval_records.sql"
        in response.evidence_refs
    )
    assert "tests/test_tickets_incidents_restore_drill_evidence.py" in response.evidence_refs
    assert (
        response.next_action
        == "prepare_tickets_incidents_tenant_admin_activation_approval_gate_without_runtime_activation"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_restore_drill_evidence_blocks_without_catalog_or_manifest() -> None:
    response = build_tickets_incidents_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=InMemoryModuleRegistry(),
        migration_manifest_entries=(),
    )

    assert response.catalog_status is None
    assert response.module_catalog_entry_present is False
    assert response.storage_migration_evidence_ready is False
    assert response.migration_plan_ready is False
    assert response.catalog_registration_migration_present is False
    assert response.metadata_schema_migration_present is False
    assert response.approval_record_migration_present is False
    assert response.approval_record_restore_verified is True
    assert response.table_restore_verified is True
    assert response.restore_evidence_ready is False
    assert "tickets_incidents_catalog_entry_missing" in response.blocking_reasons
    assert "tickets_incidents_storage_migration_evidence_not_ready" in response.blocking_reasons
    assert "tickets_incidents_restore_migration_plan_missing" in response.blocking_reasons


def test_tickets_incidents_restore_drill_evidence_is_tenant_scoped_without_state_side_effects() -> None:
    module_registry = default_module_registry()
    manifest = load_migration_manifest()

    first = build_tickets_incidents_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )
    second = build_tickets_incidents_restore_drill_evidence_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.restore_evidence_ready is True
    assert second.restore_evidence_ready is True
    assert first.evidence_hash != second.evidence_hash
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="tickets_incidents") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="tickets_incidents") is None
