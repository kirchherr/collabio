from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_activation_boundary import (
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_ENDPOINT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_RESULT_CONTRACT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_SCHEMA_VERSION,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_STATEMENT,
    TicketsIncidentsActivationDryRunExecutionActivationBoundaryCommand,
    build_tickets_incidents_activation_dry_run_execution_activation_boundary_hash,
    build_tickets_incidents_activation_dry_run_execution_activation_boundary_response,
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

ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def _fake_hash(seed: str) -> str:
    return "sha256:" + seed * 64


def _approval_command(
    approval_gate_evidence_hash: str,
) -> TicketsIncidentsTenantAdminActivationApprovalRecordCommand:
    return TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
        approval_gate_evidence_hash=approval_gate_evidence_hash,
        approval_record_ref="tickets-approval:dry-run-execution-activation-boundary-demo",
        approval_ticket_ref="ticket:tickets-dry-run-execution-activation-boundary-demo",
        human_confirmation_reference="confirmation:tickets-dry-run-execution-activation-boundary-demo",
        human_confirmation_statement=TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
        change_request_ref="change:tickets-dry-run-execution-activation-boundary-demo",
        idempotency_key_ref="idempotency:tickets-dry-run-execution-activation-boundary-demo",
        approved_at_utc=datetime(2026, 7, 9, 9, 10, tzinfo=UTC),
        audit_chain_ref="audit:tickets-dry-run-execution-activation-boundary-demo",
    )


def _dry_run_execution_activation_boundary_command(
    *,
    approval_gate_hash: str,
    approval_record_hash: str,
    activation_dry_run_plan_hash: str = _fake_hash("1"),
    activation_dry_run_execution_boundary_hash: str = _fake_hash("2"),
    activation_dry_run_execution_skeleton_hash: str = _fake_hash("3"),
    activation_dry_run_executor_implementation_review_hash: str = _fake_hash("4"),
    activation_dry_run_result_contract_hash: str = _fake_hash("5"),
    activation_dry_run_execution_gate_hash: str = _fake_hash("6"),
    activation_dry_run_execution_request_boundary_hash: str = _fake_hash("7"),
    activation_dry_run_executor_runtime_boundary_hash: str = _fake_hash("8"),
    activation_dry_run_execution_preflight_hash: str = _fake_hash("9"),
    activation_dry_run_execution_receipt_boundary_hash: str = _fake_hash("a"),
    activation_dry_run_result_persistence_boundary_hash: str = _fake_hash("b"),
    activation_execution_boundary_hash: str = _fake_hash("c"),
    activation_executor_skeleton_hash: str = _fake_hash("d"),
    activation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> TicketsIncidentsActivationDryRunExecutionActivationBoundaryCommand:
    return TicketsIncidentsActivationDryRunExecutionActivationBoundaryCommand(
        activation_dry_run_plan_evidence_hash=activation_dry_run_plan_hash,
        activation_dry_run_execution_boundary_evidence_hash=activation_dry_run_execution_boundary_hash,
        activation_dry_run_execution_skeleton_evidence_hash=activation_dry_run_execution_skeleton_hash,
        activation_dry_run_executor_implementation_review_evidence_hash=(
            activation_dry_run_executor_implementation_review_hash
        ),
        activation_dry_run_result_contract_evidence_hash=activation_dry_run_result_contract_hash,
        activation_dry_run_execution_gate_evidence_hash=activation_dry_run_execution_gate_hash,
        activation_dry_run_execution_request_boundary_evidence_hash=activation_dry_run_execution_request_boundary_hash,
        activation_dry_run_executor_runtime_boundary_evidence_hash=activation_dry_run_executor_runtime_boundary_hash,
        activation_dry_run_execution_preflight_evidence_hash=activation_dry_run_execution_preflight_hash,
        activation_dry_run_execution_receipt_boundary_evidence_hash=(
            activation_dry_run_execution_receipt_boundary_hash
        ),
        activation_dry_run_result_persistence_boundary_evidence_hash=(
            activation_dry_run_result_persistence_boundary_hash
        ),
        activation_execution_boundary_evidence_hash=activation_execution_boundary_hash,
        activation_executor_skeleton_evidence_hash=activation_executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        activation_dry_run_execution_activation_boundary_ref=(
            "tickets-activation-dry-run-execution-activation-boundary:demo"
        ),
        change_request_ref="change:tickets-activation-dry-run-execution-activation-boundary-demo",
        idempotency_key_ref="idempotency:tickets-activation-dry-run-execution-activation-boundary-demo",
        prepared_at_utc=datetime(2026, 7, 9, 9, 15, tzinfo=UTC),
        audit_chain_ref="audit:tickets-activation-dry-run-execution-activation-boundary-demo",
        activation_dry_run_execution_activation_boundary_statement=(
            TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_STATEMENT
        ),
        activation_dry_run_execution_requested=activation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def test_tickets_incidents_activation_dry_run_execution_activation_boundary_is_metadata_only() -> None:
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

    response = build_tickets_incidents_activation_dry_run_execution_activation_boundary_response(
        command=_dry_run_execution_activation_boundary_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_ENDPOINT
    assert (
        response.result_contract == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_ACTIVATION_BOUNDARY_RESULT_CONTRACT
    )
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.human_approval_ready is True
    assert response.activation_dry_run_execution_receipt_boundary_evidence_hash == _fake_hash("a")
    assert response.activation_dry_run_result_persistence_boundary_evidence_hash == _fake_hash("b")
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_record.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.activation_dry_run_execution_activation_boundary_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.activation_dry_run_execution_activation_boundary_requested is True
    assert response.activation_dry_run_execution_activation_boundary_ready is True
    assert response.future_activation_dry_run_execution_start_boundary_required is True
    assert response.activation_dry_run_execution_allowed is False
    assert response.activation_dry_run_executed is False
    assert response.activation_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.tickets_business_api_allowed is False
    assert response.worker_activation_allowed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "bind_tickets_activation_dry_run_result_persistence_boundary_hash" in (
        response.activation_dry_run_execution_activation_boundary_steps
    )
    assert "define_execution_start_boundary_required_before_any_dry_run_execution" in (
        response.activation_dry_run_execution_activation_boundary_steps
    )
    assert "future_activation_dry_run_execution_start_boundary_required" in (
        response.required_activation_dry_run_execution_activation_boundary_evidence
    )
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_activation_dry_run_execution_activation_boundary_hash(
        response
    )
    assert (
        response.next_action
        == "prepare_tickets_incidents_activation_dry_run_execution_start_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_activation_dry_run_execution_activation_boundary_blocks_execution_request() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_tickets_incidents_activation_dry_run_execution_activation_boundary_response(
        command=_dry_run_execution_activation_boundary_command(
            activation_dry_run_plan_hash=ZERO_SHA256,
            activation_dry_run_execution_boundary_hash=ZERO_SHA256,
            activation_dry_run_execution_skeleton_hash=ZERO_SHA256,
            activation_dry_run_executor_implementation_review_hash=ZERO_SHA256,
            activation_dry_run_result_contract_hash=ZERO_SHA256,
            activation_dry_run_execution_gate_hash=ZERO_SHA256,
            activation_dry_run_execution_request_boundary_hash=ZERO_SHA256,
            activation_dry_run_executor_runtime_boundary_hash=ZERO_SHA256,
            activation_dry_run_execution_preflight_hash=ZERO_SHA256,
            activation_dry_run_execution_receipt_boundary_hash=ZERO_SHA256,
            activation_dry_run_result_persistence_boundary_hash=ZERO_SHA256,
            activation_execution_boundary_hash=ZERO_SHA256,
            activation_executor_skeleton_hash=ZERO_SHA256,
            approval_gate_hash=_fake_hash("e"),
            approval_record_hash=_fake_hash("f"),
            activation_dry_run_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore(),
    )

    assert response.activation_dry_run_execution_activation_boundary_ready is False
    assert "tickets_incidents_activation_dry_run_plan_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_skeleton_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_executor_implementation_review_hash_missing" in (
        response.blocking_reasons
    )
    assert "tickets_incidents_activation_dry_run_result_contract_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_gate_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_request_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_executor_runtime_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_preflight_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_receipt_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_result_persistence_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_execution_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_executor_skeleton_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_tenant_admin_activation_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "activation_dry_run_execution_request_forbidden" in response.blocking_reasons
    assert "dry_run_result_persistence_request_forbidden" in response.blocking_reasons
    assert response.activation_dry_run_execution_allowed is False
    assert response.activation_dry_run_executed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == (
        "prepare_tickets_incidents_activation_dry_run_execution_activation_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None
