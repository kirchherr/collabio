from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import InMemoryModuleRegistry, default_module_registry
from suite.platform.tickets_incidents_storage_migration_evidence import (
    TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION,
    TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_ENDPOINT,
    TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_RESULT_CONTRACT,
    TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_SCHEMA_VERSION,
    build_tickets_incidents_storage_migration_evidence_hash,
    build_tickets_incidents_storage_migration_evidence_response,
)


def test_tickets_incidents_storage_migration_evidence_drafts_schema_without_execution() -> None:
    module_registry = default_module_registry()
    response = build_tickets_incidents_storage_migration_evidence_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.migration_evidence_gate_endpoint == (
        "/v1/platform/modules/families/tickets-incidents/migration-evidence-gate"
    )
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.migration_evidence_gate_ready is True
    assert response.catalog_registration_migration_present is True
    assert response.storage_migration_evidence_ready is True
    assert response.table_design_review_ready is True
    assert response.rls_policy_plan_ready is True
    assert response.tenant_isolation_plan_ready is True
    assert response.retention_legal_hold_plan_ready is True
    assert response.kms_audit_reference_plan_ready is True
    assert response.backup_failover_update_planned is True
    assert response.no_content_payload_columns_planned is True
    assert response.metadata_schema_migration_file_created is False
    assert response.metadata_schema_migration_registered is False
    assert response.storage_migration_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.tickets_business_api_allowed is False
    assert response.business_tables_created is False
    assert response.content_included is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.planned_schema_name == "tickets"
    assert response.planned_migration_name == "tickets_incidents_metadata_schema"
    assert response.planned_object_types == ("ticket.ticket", "ticket.event")
    assert tuple(table.table_name for table in response.planned_tables) == (
        "tickets.ticket_items",
        "tickets.ticket_events",
    )
    assert response.planned_tables[0].primary_key == "ticket_id"
    assert response.planned_tables[1].primary_key == "event_id"
    assert "tenant_id" in response.planned_tables[0].required_columns
    assert "retention_policy_id" in response.planned_tables[0].required_columns
    assert "legal_hold_state" in response.planned_tables[0].required_columns
    assert "kms_key_ref" in response.planned_tables[0].required_columns
    assert "audit_chain_ref" in response.planned_tables[0].required_columns
    assert "tickets_ticket_items_tenant_select" in response.planned_tables[0].planned_rls_policies
    assert "description" in response.planned_tables[0].forbidden_payload_columns_absent
    assert "description" not in response.planned_tables[0].required_columns
    assert "raw_message" not in response.planned_tables[1].required_columns
    assert "backup_restore_ticket_incident_records_update" in response.required_storage_migration_evidence
    assert "no_storage_migration_file_created_confirmed" in response.required_storage_migration_evidence
    assert "no_storage_migration_execution_confirmed" in response.required_storage_migration_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash.startswith("sha256:")
    assert response.evidence_hash == build_tickets_incidents_storage_migration_evidence_hash(response)
    assert response.summary.planned_table_count == 2
    assert response.summary.planned_object_type_count == 2
    assert response.summary.required_storage_evidence_count == len(response.required_storage_migration_evidence)
    assert response.summary.blocking_reason_count == 0
    assert "app/suite/platform/tickets_incidents_storage_migration_evidence.py" in response.evidence_refs
    assert "tests/test_tickets_incidents_storage_migration_evidence.py" in response.evidence_refs
    assert response.next_action == TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION

    assert module_registry.get_catalog_entry("tickets_incidents").status.value == "not_installed"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_storage_migration_evidence_blocks_without_gate_readiness() -> None:
    response = build_tickets_incidents_storage_migration_evidence_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=InMemoryModuleRegistry(),
        migration_manifest_entries=(),
    )

    assert response.catalog_status is None
    assert response.migration_evidence_gate_ready is False
    assert response.catalog_registration_migration_present is False
    assert response.storage_migration_evidence_ready is False
    assert "tickets_incidents_migration_evidence_gate_not_ready" in response.blocking_reasons
    assert response.next_action == "repair_tickets_incidents_migration_evidence_gate_before_storage_draft"


def test_tickets_incidents_storage_migration_evidence_is_tenant_scoped_without_state_side_effects() -> None:
    module_registry = default_module_registry()
    manifest = load_migration_manifest()

    first = build_tickets_incidents_storage_migration_evidence_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )
    second = build_tickets_incidents_storage_migration_evidence_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.storage_migration_evidence_ready is True
    assert second.storage_migration_evidence_ready is True
    assert first.evidence_hash != second.evidence_hash
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="tickets_incidents") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="tickets_incidents") is None
