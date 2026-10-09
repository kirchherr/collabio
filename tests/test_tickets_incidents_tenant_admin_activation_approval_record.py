import os
from datetime import UTC, datetime

import pytest

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.persistence.migrator import apply_migrations
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_tenant_admin_activation_approval_gate import (
    build_tickets_incidents_tenant_admin_activation_approval_gate_response,
)
from suite.platform.tickets_incidents_tenant_admin_activation_approval_record import (
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_ENDPOINT,
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RESULT_CONTRACT,
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_SCHEMA_VERSION,
    InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    PgTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
    build_default_tickets_incidents_tenant_admin_activation_approval_record_store,
    build_tickets_incidents_tenant_admin_activation_approval_record_hash,
    build_tickets_incidents_tenant_admin_activation_approval_record_response,
)


def _approval_command(
    approval_gate_evidence_hash: str,
) -> TicketsIncidentsTenantAdminActivationApprovalRecordCommand:
    return TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
        approval_gate_evidence_hash=approval_gate_evidence_hash,
        approval_record_ref="tickets-approval:record-demo",
        approval_ticket_ref="ticket:tickets-activation-demo",
        human_confirmation_reference="confirmation:tickets-activation-demo",
        human_confirmation_statement=TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
        change_request_ref="change:tickets-activation-demo",
        idempotency_key_ref="idempotency:tickets-activation-demo",
        approved_at_utc=datetime(2026, 7, 9, 8, 0, tzinfo=UTC),
        audit_chain_ref="audit:tickets-activation-demo",
    )


def test_tickets_incidents_tenant_admin_activation_approval_record_is_metadata_only() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    response = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.approval_gate_evidence_hash == approval_gate.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_gate.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.human_confirmation_statement_hash.startswith("sha256:")
    assert response.approver_role_allowed is True
    assert response.record_status == "approved_for_activation_execution_gate"
    assert response.approval_record_created is True
    assert response.human_confirmation_captured is True
    assert response.human_confirmation_statement_matched is True
    assert response.future_activation_execution_gate_required is True
    assert response.activation_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.tickets_business_api_allowed is False
    assert response.worker_activation_allowed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "exact_human_confirmation_statement_hash" in response.required_approval_evidence
    assert "future_activation_execution_gate_required" in response.required_approval_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_tenant_admin_activation_approval_record_hash(response)
    assert response.next_action == "review_tickets_incidents_activation_execution_boundary"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_approval_record_store_is_idempotent_without_activation() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    record = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    store = InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore()

    assert store.append(record) == record
    assert store.append(record) == record
    assert (
        store.latest_for_gate(tenant_id="tenant-demo", approval_gate_evidence_hash=approval_gate.evidence_hash)
        == record
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_tenant_approval_store_backend_selection_is_explicit() -> None:
    assert isinstance(
        build_default_tickets_incidents_tenant_admin_activation_approval_record_store({}),
        InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    )
    assert isinstance(
        build_default_tickets_incidents_tenant_admin_activation_approval_record_store(
            {
                "SUITE_TICKETS_TENANT_APPROVAL_RECORD_BACKEND": "postgres",
                "SUITE_DATABASE_DSN": "postgresql://app:secret@postgres/collabio",
            }
        ),
        PgTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    )
    with pytest.raises(ValueError, match="requires"):
        build_default_tickets_incidents_tenant_admin_activation_approval_record_store(
            {"SUITE_TICKETS_TENANT_APPROVAL_RECORD_BACKEND": "postgres"}
        )


def test_tickets_incidents_approval_record_blocks_non_tenant_admin_without_persistence() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    response = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.approval_record_created is False
    assert response.record_status == "blocked"
    assert "tenant_admin_role_required" in response.blocking_reasons
    with pytest.raises(ValueError, match="blocked"):
        InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore().append(response)


def test_tickets_incidents_tenant_approval_record_is_persistent_and_tenant_scoped() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = os.environ.get("SUITE_DATABASE_DSN")
    if not migration_dsn or not app_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)

    module_registry = default_module_registry()
    user_context = UserContext(
        tenant_id="tenant-tickets-approval-persistence",
        user_id="tenant-admin-1",
        role_ids={"tenant-admin"},
    )
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    record = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    store = PgTicketsIncidentsTenantAdminActivationApprovalRecordStore(database_dsn=app_dsn)

    assert store.append(record) == record
    assert store.append(record) == record
    assert (
        store.latest_for_gate(
            tenant_id=user_context.tenant_id,
            approval_gate_evidence_hash=approval_gate.evidence_hash,
        )
        == record
    )
    assert (
        store.latest_for_gate(
            tenant_id="tenant-other",
            approval_gate_evidence_hash=approval_gate.evidence_hash,
        )
        is None
    )
