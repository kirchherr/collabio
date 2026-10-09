from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_execution_boundary import (
    TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    TicketsIncidentsActivationExecutionBoundaryCommand,
    build_tickets_incidents_activation_execution_boundary_response,
)
from suite.platform.tickets_incidents_activation_executor_skeleton import (
    TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_ENDPOINT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_PREPARATION_STATEMENT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_RESULT_CONTRACT,
    TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_SCHEMA_VERSION,
    TicketsIncidentsActivationExecutorSkeletonCommand,
    build_tickets_incidents_activation_executor_skeleton_hash,
    build_tickets_incidents_activation_executor_skeleton_response,
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


def _boundary_command(
    *,
    approval_gate_hash: str,
    approval_record_hash: str,
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
    )


def _skeleton_command(
    *,
    activation_execution_boundary_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    activation_execution_requested: bool = False,
) -> TicketsIncidentsActivationExecutorSkeletonCommand:
    return TicketsIncidentsActivationExecutorSkeletonCommand(
        activation_execution_boundary_evidence_hash=activation_execution_boundary_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        activation_executor_skeleton_ref="tickets-activation-executor-skeleton:demo",
        change_request_ref="change:tickets-activation-executor-skeleton-demo",
        idempotency_key_ref="idempotency:tickets-activation-executor-skeleton-demo",
        prepared_at_utc=datetime(2026, 7, 9, 8, 10, tzinfo=UTC),
        audit_chain_ref="audit:tickets-activation-executor-skeleton-demo",
        activation_executor_skeleton_preparation_statement=(
            TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_PREPARATION_STATEMENT
        ),
        activation_execution_requested=activation_execution_requested,
    )


def test_tickets_incidents_activation_executor_skeleton_is_metadata_only_after_boundary_review() -> None:
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
    boundary = build_tickets_incidents_activation_execution_boundary_response(
        command=_boundary_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    response = build_tickets_incidents_activation_executor_skeleton_response(
        command=_skeleton_command(
            activation_execution_boundary_hash=boundary.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_ACTIVATION_EXECUTOR_SKELETON_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.human_approval_ready is True
    assert response.activation_execution_boundary_evidence_hash == boundary.evidence_hash
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_record.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.activation_executor_skeleton_preparation_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.activation_executor_skeleton_prepared is True
    assert response.activation_executor_implementation_required is True
    assert response.activation_dry_run_required is True
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
    assert "bind_activation_execution_boundary_hash" in response.skeleton_steps
    assert "defer_tickets_business_api_activation" in response.skeleton_steps
    assert "future_activation_dry_run_required" in response.required_executor_skeleton_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_activation_executor_skeleton_hash(response)
    assert response.next_action == "prepare_tickets_incidents_activation_dry_run_plan_without_tenant_activation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_activation_executor_skeleton_blocks_without_admin_or_record() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_tickets_incidents_activation_executor_skeleton_response(
        command=_skeleton_command(
            activation_execution_boundary_hash=(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            approval_gate_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            approval_record_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            activation_execution_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore(),
    )

    assert response.activation_executor_skeleton_prepared is False
    assert "tickets_incidents_activation_execution_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_tenant_admin_activation_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "activation_execution_request_forbidden" in response.blocking_reasons
    assert response.activation_execution_allowed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == "prepare_tickets_incidents_activation_executor_without_business_api_activation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None
