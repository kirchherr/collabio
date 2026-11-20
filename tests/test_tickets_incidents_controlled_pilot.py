import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.persistence.migrator import apply_migrations
from suite.platform.modules import ModuleLifecycleError, ModuleStatus, default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_approval_record import (
    InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
    PgTicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
    TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
)
from suite.platform.tickets_incidents_controlled_pilot import (
    ADMISSION_CONFIRMATION_STATEMENT,
    ENABLEMENT_CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsControlledPilotReceiptStore,
    PgTicketsIncidentsControlledPilotReceiptStore,
    TicketsIncidentsControlledPilotAdmissionCommand,
    TicketsIncidentsControlledPilotEnablementCommand,
    TicketsIncidentsControlledPilotService,
    TicketsIncidentsPilotReceiptType,
    controlled_pilot_disabled_features,
    controlled_pilot_enabled_features,
)
from suite.platform.tickets_incidents_module import (
    TICKETS_AI_ASSIST_FEATURE_ID,
    TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID,
    TICKETS_INCIDENTS_MODULE_ID,
    TICKETS_RAG_INDEXING_FEATURE_ID,
    build_default_tickets_incidents_subfeature_registry,
)
from suite.platform.tickets_incidents_service import InMemoryTicketRepository, TicketService

BOUNDARY_HASH = "sha256:" + ("a" * 64)
APPROVAL_HASH = "sha256:" + ("b" * 64)
RESTORE_HASH = "sha256:" + ("c" * 64)
POLICY_HASH = "sha256:" + ("d" * 64)


def approval_record() -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
    return TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse(
        tenant_id="tenant-demo",
        approval_boundary_evidence_hash=BOUNDARY_HASH,
        tenant_admin_approval_record_hash="sha256:" + ("e" * 64),
        tickets_restore_drill_evidence_hash=RESTORE_HASH,
        command_hash="sha256:" + ("f" * 64),
        idempotency_key_hash="sha256:" + ("1" * 64),
        confirmation_statement_hash="sha256:" + ("2" * 64),
        approval_record_ref="tickets-approval:pilot",
        approval_ticket_ref="ticket:pilot",
        human_confirmation_reference="confirmation:pilot",
        change_request_ref="change:pilot",
        audit_chain_ref="audit:pilot-approval",
        approved_by="tenant-admin-1",
        approved_at_utc=datetime(2026, 7, 29, 9, 0, tzinfo=UTC),
        approval_record_created=True,
        explicit_human_execution_approval_present=True,
        blocking_reasons=(),
        evidence_hash=APPROVAL_HASH,
        next_action="exercise_tickets_incidents_productive_vertical_slice_in_controlled_pilot",
    )


def approval_store() -> InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore:
    return InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore([approval_record()])


def admission_command() -> TicketsIncidentsControlledPilotAdmissionCommand:
    return TicketsIncidentsControlledPilotAdmissionCommand(
        approval_boundary_evidence_hash=BOUNDARY_HASH,
        approval_record_evidence_hash=APPROVAL_HASH,
        tickets_restore_drill_evidence_hash=RESTORE_HASH,
        policy_snapshot_hash=POLICY_HASH,
        feature_manifest_hash=build_default_tickets_incidents_subfeature_registry().manifest_hash,
        idempotency_key_ref="idempotency:tickets-pilot-admission",
        change_request_ref="change:tickets-pilot-admission",
        human_confirmation_reference="confirmation:tickets-pilot-admission",
        human_confirmation_statement=ADMISSION_CONFIRMATION_STATEMENT,
        audit_chain_ref="audit:tickets-pilot-admission",
        changed_at_utc=datetime(2026, 7, 29, 9, 5, tzinfo=UTC),
    )


def enablement_command() -> TicketsIncidentsControlledPilotEnablementCommand:
    return TicketsIncidentsControlledPilotEnablementCommand(
        approval_boundary_evidence_hash=BOUNDARY_HASH,
        approval_record_evidence_hash=APPROVAL_HASH,
        tickets_restore_drill_evidence_hash=RESTORE_HASH,
        policy_snapshot_hash=POLICY_HASH,
        feature_manifest_hash=build_default_tickets_incidents_subfeature_registry().manifest_hash,
        idempotency_key_ref="idempotency:tickets-pilot-enablement",
        change_request_ref="change:tickets-pilot-enablement",
        human_confirmation_reference="confirmation:tickets-pilot-enablement",
        human_confirmation_statement=ENABLEMENT_CONFIRMATION_STATEMENT,
        audit_chain_ref="audit:tickets-pilot-enablement",
        changed_at_utc=datetime(2026, 7, 29, 9, 10, tzinfo=UTC),
    )


def test_controlled_pilot_is_two_step_idempotent_and_opens_exactly_four_features() -> None:
    registry = default_module_registry()
    receipts = InMemoryTicketsIncidentsControlledPilotReceiptStore()
    service = TicketsIncidentsControlledPilotService(
        module_registry=registry,
        migration_manifest_entries=load_migration_manifest(),
        approval_record_store=approval_store(),
        receipt_store=receipts,
    )
    user = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})

    admission = service.admit(user_context=user, command=admission_command())
    state = registry.get_tenant_module("tenant-demo", TICKETS_INCIDENTS_MODULE_ID)

    assert registry.get_catalog_entry(TICKETS_INCIDENTS_MODULE_ID).status == ModuleStatus.INSTALLED
    assert admission.receipt_type == TicketsIncidentsPilotReceiptType.ADMISSION
    assert admission.module_status == ModuleStatus.DISABLED
    assert admission.tickets_business_api_allowed is False
    assert state.enabled_features == controlled_pilot_disabled_features()
    assert service.admit(user_context=user, command=admission_command()) == admission
    with pytest.raises(ModuleLifecycleError, match="not enabled"):
        registry.require_normal_use(tenant_id="tenant-demo", module_id=TICKETS_INCIDENTS_MODULE_ID)

    completed = service.enable(user_context=user, command=enablement_command())
    state = registry.get_tenant_module("tenant-demo", TICKETS_INCIDENTS_MODULE_ID)
    authorization = receipts.latest_for_type(
        tenant_id="tenant-demo",
        receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_AUTHORIZATION,
    )

    assert authorization is not None
    assert authorization.module_status == ModuleStatus.DISABLED
    assert completed.receipt_type == TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED
    assert completed.authorization_receipt_evidence_hash == authorization.evidence_hash
    assert completed.tickets_business_api_allowed is True
    assert completed.worker_activation_allowed is False
    assert completed.ai_or_rag_allowed is False
    assert completed.compliance_feature_allowed is False
    assert state.status == ModuleStatus.ENABLED
    assert state.enabled_features == controlled_pilot_enabled_features()
    assert sum(state.enabled_features.values()) == 4
    assert state.enabled_features[TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID] is False
    assert state.enabled_features[TICKETS_RAG_INDEXING_FEATURE_ID] is False
    assert state.enabled_features[TICKETS_AI_ASSIST_FEATURE_ID] is False
    assert service.enable(user_context=user, command=enablement_command()) == completed


def test_controlled_pilot_rejects_enablement_without_admission_and_non_admin() -> None:
    service = TicketsIncidentsControlledPilotService(
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
        approval_record_store=approval_store(),
        receipt_store=InMemoryTicketsIncidentsControlledPilotReceiptStore(),
    )
    admin = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    member = UserContext(tenant_id="tenant-demo", user_id="member-1", role_ids={"member"})

    with pytest.raises(ValueError, match="admission"):
        service.enable(user_context=admin, command=enablement_command())
    with pytest.raises(PermissionError, match="tenant_admin"):
        service.admit(user_context=member, command=admission_command())


def test_controlled_pilot_api_keeps_tickets_closed_until_separate_enablement() -> None:
    client = TestClient(app)
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "tenant-admin-1",
        "X-Role-Ids": "tenant-admin",
    }
    original_registry = app.state.module_registry
    original_approval_store = app.state.tickets_incidents_dry_run_execution_approval_record_store
    original_receipt_store = app.state.tickets_incidents_controlled_pilot_receipt_store
    original_ticket_service = app.state.ticket_service
    try:
        app.state.module_registry = default_module_registry()
        app.state.tickets_incidents_dry_run_execution_approval_record_store = approval_store()
        app.state.tickets_incidents_controlled_pilot_receipt_store = (
            InMemoryTicketsIncidentsControlledPilotReceiptStore()
        )
        app.state.ticket_service = TicketService(
            repository=InMemoryTicketRepository(),
            audit_logger=app.state.audit_logger,
        )

        admission = client.post(
            "/v1/platform/modules/families/tickets-incidents/controlled-pilot/admission",
            headers=headers,
            json=admission_command().model_dump(mode="json"),
        )
        still_closed = client.get("/v1/tickets", headers=headers)
        enablement = client.post(
            "/v1/platform/modules/families/tickets-incidents/controlled-pilot/enablement",
            headers=headers,
            json=enablement_command().model_dump(mode="json"),
        )
        created = client.post(
            "/v1/tickets",
            headers=headers,
            json={
                "ticket_id": "ticket-pilot-1",
                "ticket_number": "PILOT-1",
                "subject_redacted": "Controlled pilot proof",
                "kms_key_ref": "kms:tenant-demo:tickets",
                "audit_chain_ref": "audit:ticket-pilot-1:create",
                "created_event_id": "event:ticket-pilot-1:create",
                "created_event_summary_redacted": "Ticket created in controlled pilot",
                "occurred_at_utc": "2026-07-29T09:15:00Z",
            },
        )

        assert admission.status_code == 200
        assert admission.json()["module_status"] == "disabled"
        assert still_closed.status_code == 403
        assert enablement.status_code == 200
        assert enablement.json()["module_status"] == "enabled"
        assert sum(enablement.json()["enabled_features"].values()) == 4
        assert created.status_code == 201
        assert created.json()["ticket"]["ticket_id"] == "ticket-pilot-1"
    finally:
        app.state.module_registry = original_registry
        app.state.tickets_incidents_dry_run_execution_approval_record_store = original_approval_store
        app.state.tickets_incidents_controlled_pilot_receipt_store = original_receipt_store
        app.state.ticket_service = original_ticket_service


def test_postgres_controlled_pilot_evidence_is_persistent_and_tenant_scoped() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = os.environ.get("SUITE_DATABASE_DSN")
    if not migration_dsn or not app_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)

    persistent_approvals = PgTicketsIncidentsActivationDryRunExecutionApprovalRecordStore(database_dsn=app_dsn)
    persisted_approval = persistent_approvals.append(approval_record())
    assert persisted_approval == approval_record()
    assert (
        persistent_approvals.latest_for_boundary(
            tenant_id="tenant-demo",
            approval_boundary_evidence_hash=BOUNDARY_HASH,
        )
        == approval_record()
    )
    assert (
        persistent_approvals.latest_for_boundary(
            tenant_id="tenant-other",
            approval_boundary_evidence_hash=BOUNDARY_HASH,
        )
        is None
    )

    memory_receipts = InMemoryTicketsIncidentsControlledPilotReceiptStore()
    service = TicketsIncidentsControlledPilotService(
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
        approval_record_store=approval_store(),
        receipt_store=memory_receipts,
    )
    user = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    admission = service.admit(user_context=user, command=admission_command())
    completed = service.enable(user_context=user, command=enablement_command())
    authorization = memory_receipts.latest_for_type(
        tenant_id="tenant-demo",
        receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_AUTHORIZATION,
    )
    assert authorization is not None

    persistent_receipts = PgTicketsIncidentsControlledPilotReceiptStore(database_dsn=app_dsn)
    assert persistent_receipts.append(admission) == admission
    assert persistent_receipts.append(authorization) == authorization
    assert persistent_receipts.append(completed) == completed
    assert (
        persistent_receipts.latest_for_type(
            tenant_id="tenant-demo",
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
        )
        == completed
    )
    assert (
        persistent_receipts.latest_for_type(
            tenant_id="tenant-other",
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
        )
        is None
    )
