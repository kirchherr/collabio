from datetime import UTC, datetime

from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_approval_record import (
    CONFIRMATION_STATEMENT as EXECUTION_APPROVAL_CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
    TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand,
    build_tickets_incidents_activation_dry_run_execution_approval_record_response,
)
from suite.platform.tickets_incidents_controlled_pilot import (
    ADMISSION_CONFIRMATION_STATEMENT,
    ENABLEMENT_CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsControlledPilotReceiptStore,
    TicketsIncidentsControlledPilotAdmissionCommand,
    TicketsIncidentsControlledPilotEnablementCommand,
    TicketsIncidentsControlledPilotService,
    TicketsIncidentsControlledPilotStage,
    build_tickets_incidents_controlled_pilot_status_response,
)
from suite.platform.tickets_incidents_module import build_default_tickets_incidents_subfeature_registry
from suite.platform.tickets_incidents_tenant_admin_activation_approval_gate import (
    build_tickets_incidents_tenant_admin_activation_approval_gate_response,
)
from suite.platform.tickets_incidents_tenant_admin_activation_approval_record import (
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
    build_tickets_incidents_tenant_admin_activation_approval_record_response,
)

TENANT_ID = "tenant-tickets-pilot-status"
RESTORE_POLICY_HASH = "sha256:" + ("d" * 64)


def test_controlled_pilot_status_drives_the_authoritative_four_stage_flow() -> None:
    user = UserContext(tenant_id=TENANT_ID, user_id="tenant-admin-1", role_ids={"tenant-admin"})
    registry = default_module_registry()
    manifest = load_migration_manifest()
    tenant_approvals = InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore()
    execution_approvals = InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore()
    receipts = InMemoryTicketsIncidentsControlledPilotReceiptStore()

    def status_response():
        return build_tickets_incidents_controlled_pilot_status_response(
            user_context=user,
            module_registry=registry,
            migration_manifest_entries=manifest,
            tenant_approval_record_store=tenant_approvals,
            execution_approval_record_store=execution_approvals,
            receipt_store=receipts,
        )

    initial = status_response()
    assert initial.stage == TicketsIncidentsControlledPilotStage.TENANT_APPROVAL_REQUIRED
    assert initial.required_confirmation_statement == (
        TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
    )
    assert initial.tickets_business_api_allowed is False

    gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user,
        module_registry=registry,
        migration_manifest_entries=manifest,
    )
    tenant_approval = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
            approval_gate_evidence_hash=gate.evidence_hash,
            approval_record_ref="tickets-approval:pilot-status",
            approval_ticket_ref="ticket:pilot-status",
            human_confirmation_reference="confirmation:pilot-status-tenant",
            human_confirmation_statement=(
                TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
            ),
            change_request_ref="change:pilot-status",
            idempotency_key_ref="idempotency:pilot-status-tenant",
            approved_at_utc=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            audit_chain_ref="audit:pilot-status-tenant",
        ),
        user_context=user,
        module_registry=registry,
        migration_manifest_entries=manifest,
    )
    tenant_approvals.append(tenant_approval)

    approval_pending = status_response()
    assert approval_pending.stage == TicketsIncidentsControlledPilotStage.EXECUTION_APPROVAL_REQUIRED
    assert approval_pending.expected_execution_approval_boundary_hash != "sha256:" + ("0" * 64)
    assert approval_pending.required_confirmation_statement == EXECUTION_APPROVAL_CONFIRMATION_STATEMENT

    execution_approval = build_tickets_incidents_activation_dry_run_execution_approval_record_response(
        command=TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand(
            approval_boundary_evidence_hash=approval_pending.expected_execution_approval_boundary_hash,
            approval_record_ref="tickets-execution-approval:pilot-status",
            approval_ticket_ref="ticket:pilot-status",
            human_confirmation_reference="confirmation:pilot-status-execution",
            human_confirmation_statement=EXECUTION_APPROVAL_CONFIRMATION_STATEMENT,
            change_request_ref="change:pilot-status",
            idempotency_key_ref="idempotency:pilot-status-execution",
            approved_at_utc=datetime(2026, 8, 14, 10, 5, tzinfo=UTC),
            audit_chain_ref="audit:pilot-status-execution",
        ),
        user_context=user,
        module_registry=registry,
        migration_manifest_entries=manifest,
        tenant_approval_record_store=tenant_approvals,
    )
    execution_approvals.append(execution_approval)

    admission_pending = status_response()
    assert admission_pending.stage == TicketsIncidentsControlledPilotStage.ADMISSION_REQUIRED
    assert admission_pending.execution_approval_boundary_trusted is True
    assert admission_pending.required_confirmation_statement == ADMISSION_CONFIRMATION_STATEMENT

    service = TicketsIncidentsControlledPilotService(
        module_registry=registry,
        migration_manifest_entries=manifest,
        approval_record_store=execution_approvals,
        receipt_store=receipts,
    )
    common_command = {
        "approval_boundary_evidence_hash": execution_approval.approval_boundary_evidence_hash,
        "approval_record_evidence_hash": execution_approval.evidence_hash,
        "tickets_restore_drill_evidence_hash": execution_approval.tickets_restore_drill_evidence_hash,
        "policy_snapshot_hash": RESTORE_POLICY_HASH,
        "feature_manifest_hash": build_default_tickets_incidents_subfeature_registry().manifest_hash,
        "change_request_ref": "change:pilot-status",
    }
    service.admit(
        user_context=user,
        command=TicketsIncidentsControlledPilotAdmissionCommand(
            **common_command,
            idempotency_key_ref="idempotency:pilot-status-admission",
            human_confirmation_reference="confirmation:pilot-status-admission",
            human_confirmation_statement=ADMISSION_CONFIRMATION_STATEMENT,
            audit_chain_ref="audit:pilot-status",
            changed_at_utc=datetime(2026, 8, 14, 10, 10, tzinfo=UTC),
        ),
    )

    enablement_pending = status_response()
    assert enablement_pending.stage == TicketsIncidentsControlledPilotStage.ENABLEMENT_REQUIRED
    assert enablement_pending.required_confirmation_statement == ENABLEMENT_CONFIRMATION_STATEMENT
    assert enablement_pending.tenant_module_status == "disabled"

    service.enable(
        user_context=user,
        command=TicketsIncidentsControlledPilotEnablementCommand(
            **common_command,
            idempotency_key_ref="idempotency:pilot-status-enablement",
            human_confirmation_reference="confirmation:pilot-status-enablement",
            human_confirmation_statement=ENABLEMENT_CONFIRMATION_STATEMENT,
            audit_chain_ref="audit:pilot-status",
            changed_at_utc=datetime(2026, 8, 14, 10, 15, tzinfo=UTC),
        ),
    )

    enabled = status_response()
    assert enabled.stage == TicketsIncidentsControlledPilotStage.VERTICAL_SLICE_VALIDATION_REQUIRED
    assert enabled.pilot_state_consistent is True
    assert enabled.tickets_business_api_allowed is True
    assert sum(enabled.enabled_features.values()) == 4
    assert enabled.required_confirmation_statement is None


def test_controlled_pilot_status_api_is_admin_only_and_does_not_activate() -> None:
    client = TestClient(app)
    admin_headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "tenant-admin-1",
        "X-Role-Ids": "tenant-admin",
    }
    member_headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "member-1",
        "X-Role-Ids": "knowledge-worker",
    }

    response = client.get(
        "/v1/platform/modules/families/tickets-incidents/controlled-pilot/status",
        headers=admin_headers,
    )
    forbidden = client.get(
        "/v1/platform/modules/families/tickets-incidents/controlled-pilot/status",
        headers=member_headers,
    )

    assert response.status_code == 200
    assert response.json()["stage"] == "tenant_approval_required"
    assert response.json()["tickets_business_api_allowed"] is False
    assert response.json()["content_included"] is False
    assert forbidden.status_code == 403
