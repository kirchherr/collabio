from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_execution_boundary import (
    TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_ENDPOINT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RESULT_CONTRACT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_SCHEMA_VERSION,
    TicketsIncidentsActivationExecutionBoundaryCommand,
    build_tickets_incidents_activation_execution_boundary_hash,
    build_tickets_incidents_activation_execution_boundary_response,
)
from suite.platform.tickets_incidents_tenant_admin_activation_approval_gate import (
    build_tickets_incidents_tenant_admin_activation_approval_gate_response,
)
from suite.platform.tickets_incidents_tenant_admin_activation_approval_record import (
    TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore,
    TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
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


def _execution_boundary_command(
    *,
    approval_gate_hash: str,
    approval_record_hash: str,
    activation_execution_requested: bool = False,
) -> TicketsIncidentsActivationExecutionBoundaryCommand:
    return TicketsIncidentsActivationExecutionBoundaryCommand(
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        activation_execution_boundary_ref="tickets-activation-boundary:review-demo",
        change_request_ref="change:tickets-activation-execution-demo",
        idempotency_key_ref="idempotency:tickets-activation-execution-demo",
        reviewed_at_utc=datetime(2026, 7, 9, 8, 5, tzinfo=UTC),
        audit_chain_ref="audit:tickets-activation-execution-demo",
        activation_execution_boundary_review_statement=(
            TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT
        ),
        activation_execution_requested=activation_execution_requested,
    )


def test_tickets_incidents_activation_execution_boundary_is_metadata_only_after_approval() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    migration_manifest = load_migration_manifest()
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record_store = InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore(records=(approval_record,))

    response = build_tickets_incidents_activation_execution_boundary_response(
        command=_execution_boundary_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.human_approval_ready is True
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_record.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.activation_execution_boundary_review_statement_hash.startswith("sha256:")
    assert response.approver_role_allowed is True
    assert response.activation_execution_boundary_review_requested is True
    assert response.activation_execution_boundary_review_ready is True
    assert response.tickets_incidents_activation_execution_boundary_ready is True
    assert response.future_activation_executor_required is True
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
    assert "tenant_admin_activation_approval_record_hash" in response.required_execution_boundary_evidence
    assert "future_activation_executor_required" in response.required_execution_boundary_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_activation_execution_boundary_hash(response)
    assert response.next_action == "prepare_tickets_incidents_activation_executor_without_business_api_activation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_activation_execution_boundary_blocks_without_admin_or_record() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )

    response = build_tickets_incidents_activation_execution_boundary_response(
        command=_execution_boundary_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            activation_execution_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore(),
    )

    assert response.activation_execution_boundary_review_ready is False
    assert response.tickets_incidents_activation_execution_boundary_ready is False
    assert "tickets_incidents_tenant_admin_activation_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "activation_execution_request_forbidden" in response.blocking_reasons
    assert response.activation_execution_allowed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == "review_tickets_incidents_activation_execution_boundary"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None
