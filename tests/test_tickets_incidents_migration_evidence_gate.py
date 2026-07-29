from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import InMemoryModuleRegistry, default_module_registry
from suite.platform.tickets_incidents_migration_evidence_gate import (
    TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT,
    TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_RESULT_CONTRACT,
    TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_SCHEMA_VERSION,
    TICKETS_INCIDENTS_RESTORE_REVIEW_NEXT_ACTION,
    build_tickets_incidents_migration_evidence_gate_response,
)


def test_tickets_incidents_migration_evidence_gate_is_metadata_only_before_storage() -> None:
    module_registry = default_module_registry()
    response = build_tickets_incidents_migration_evidence_gate_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.catalog_readiness_endpoint == "/v1/platform/modules/families/tickets-incidents/catalog-readiness"
    assert response.catalog_status == "not_installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.module_package_installed is False
    assert response.tenant_module_state_present is False
    assert response.catalog_registration_migration_present is True
    assert response.migration_evidence_gate_ready is True
    assert response.storage_migration_evidence_ready is True
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
    assert response.planned_object_types == ("ticket.ticket", "ticket.event")
    assert response.existing_tickets_migration_versions == ("0051", "0052", "0053")
    assert response.existing_tickets_storage_migration_versions == ("0052", "0053")
    assert response.feature_manifest_hash.startswith("sha256:")
    assert response.object_rule_manifest_hash.startswith("sha256:")
    assert "backup_restore_ticket_incident_records_update" in response.required_storage_migration_evidence
    assert "no_tenant_state_creation_confirmed" in response.required_storage_migration_evidence
    assert "no_business_api_or_worker_activation_confirmed" in response.required_storage_migration_evidence
    assert response.summary.tickets_manifest_migration_count == 3
    assert response.summary.tickets_storage_migration_count == 2
    assert response.summary.planned_object_type_count == 2
    assert response.summary.required_storage_evidence_count == len(response.required_storage_migration_evidence)
    assert response.summary.blocking_reason_count == 0
    assert response.blocking_reasons == ()
    assert "app/suite/platform/tickets_incidents_migration_evidence_gate.py" in response.evidence_refs
    assert "tests/test_tickets_incidents_migration_evidence_gate.py" in response.evidence_refs
    assert "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql" in response.evidence_refs
    assert "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql" in response.evidence_refs
    assert (
        "app/suite/persistence/migrations/0053_tickets_incidents_dry_run_execution_approval_records.sql"
        in response.evidence_refs
    )
    assert response.next_action == TICKETS_INCIDENTS_RESTORE_REVIEW_NEXT_ACTION

    assert module_registry.get_catalog_entry("tickets_incidents").status.value == "not_installed"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_migration_evidence_gate_blocks_without_catalog_or_manifest() -> None:
    response = build_tickets_incidents_migration_evidence_gate_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=InMemoryModuleRegistry(),
        migration_manifest_entries=(),
    )

    assert response.catalog_status is None
    assert response.module_catalog_entry_present is False
    assert response.catalog_registration_migration_present is False
    assert response.migration_evidence_gate_ready is False
    assert response.storage_migration_evidence_ready is False
    assert "tickets_incidents_catalog_entry_missing" in response.blocking_reasons
    assert "tickets_incidents_catalog_registration_migration_missing" in response.blocking_reasons
    assert response.next_action == "repair_tickets_incidents_catalog_or_manifest_before_storage_evidence"


def test_tickets_incidents_migration_evidence_gate_is_tenant_scoped_without_side_effects() -> None:
    module_registry = default_module_registry()
    manifest = load_migration_manifest()

    first = build_tickets_incidents_migration_evidence_gate_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )
    second = build_tickets_incidents_migration_evidence_gate_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.feature_manifest_hash == second.feature_manifest_hash
    assert first.object_rule_manifest_hash == second.object_rule_manifest_hash
    assert first.migration_evidence_gate_ready is True
    assert second.migration_evidence_gate_ready is True
    assert first.storage_migration_evidence_ready is True
    assert second.storage_migration_evidence_ready is True
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-a", module_id="tickets_incidents") is None
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-b", module_id="tickets_incidents") is None
