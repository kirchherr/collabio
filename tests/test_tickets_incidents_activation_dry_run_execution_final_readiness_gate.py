from datetime import UTC, datetime
from typing import Any

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_final_readiness_gate import (
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_ENDPOINT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_RESULT_CONTRACT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_SCHEMA_VERSION,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_STATEMENT,
    TicketsIncidentsActivationDryRunExecutionFinalReadinessGateCommand,
    build_tickets_incidents_activation_dry_run_execution_final_readiness_gate_hash,
    build_tickets_incidents_activation_dry_run_execution_final_readiness_gate_response,
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
NONZERO_DISPATCH_SHA256 = "sha256:" + "d" * 64
NONZERO_WORKER_BOUNDARY_SHA256 = "sha256:" + "e" * 64


def _fake_hash(seed: str) -> str:
    return "sha256:" + seed * 64


def _approval_command(
    approval_gate_evidence_hash: str,
) -> TicketsIncidentsTenantAdminActivationApprovalRecordCommand:
    return TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
        approval_gate_evidence_hash=approval_gate_evidence_hash,
        approval_record_ref="tickets-approval:dry-run-execution-final-readiness-gate-demo",
        approval_ticket_ref="ticket:tickets-dry-run-execution-final-readiness-gate-demo",
        human_confirmation_reference="confirmation:tickets-dry-run-execution-final-readiness-gate-demo",
        human_confirmation_statement=TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
        change_request_ref="change:tickets-dry-run-execution-final-readiness-gate-demo",
        idempotency_key_ref="idempotency:tickets-dry-run-execution-final-readiness-gate-demo",
        approved_at_utc=datetime(2026, 7, 9, 9, 40, tzinfo=UTC),
        audit_chain_ref="audit:tickets-dry-run-execution-final-readiness-gate-demo",
    )


def _dry_run_execution_final_readiness_gate_command(
    *,
    approval_gate_hash: str,
    approval_record_hash: str,
    **overrides: Any,
) -> TicketsIncidentsActivationDryRunExecutionFinalReadinessGateCommand:
    values: dict[str, Any] = {
        "activation_dry_run_plan_evidence_hash": _fake_hash("1"),
        "activation_dry_run_execution_boundary_evidence_hash": _fake_hash("2"),
        "activation_dry_run_execution_skeleton_evidence_hash": _fake_hash("3"),
        "activation_dry_run_executor_implementation_review_evidence_hash": _fake_hash("4"),
        "activation_dry_run_result_contract_evidence_hash": _fake_hash("5"),
        "activation_dry_run_execution_gate_evidence_hash": _fake_hash("6"),
        "activation_dry_run_execution_request_boundary_evidence_hash": _fake_hash("7"),
        "activation_dry_run_executor_runtime_boundary_evidence_hash": _fake_hash("8"),
        "activation_dry_run_execution_preflight_evidence_hash": _fake_hash("9"),
        "activation_dry_run_execution_receipt_boundary_evidence_hash": _fake_hash("a"),
        "activation_dry_run_result_persistence_boundary_evidence_hash": _fake_hash("b"),
        "activation_dry_run_execution_activation_boundary_evidence_hash": _fake_hash("c"),
        "activation_dry_run_execution_start_boundary_evidence_hash": _fake_hash("d"),
        "activation_dry_run_execution_dispatch_boundary_evidence_hash": NONZERO_DISPATCH_SHA256,
        "activation_dry_run_execution_worker_boundary_evidence_hash": NONZERO_WORKER_BOUNDARY_SHA256,
        "activation_execution_boundary_evidence_hash": _fake_hash("e"),
        "activation_executor_skeleton_evidence_hash": _fake_hash("f"),
        "tenant_admin_approval_gate_hash": approval_gate_hash,
        "tenant_admin_approval_record_hash": approval_record_hash,
        "activation_dry_run_execution_final_readiness_gate_ref": (
            "tickets-activation-dry-run-execution-final-readiness-gate:demo"
        ),
        "change_request_ref": "change:tickets-activation-dry-run-execution-final-readiness-gate-demo",
        "idempotency_key_ref": "idempotency:tickets-activation-dry-run-execution-final-readiness-gate-demo",
        "prepared_at_utc": datetime(2026, 7, 9, 9, 45, tzinfo=UTC),
        "audit_chain_ref": "audit:tickets-activation-dry-run-execution-final-readiness-gate-demo",
        "activation_dry_run_execution_final_readiness_gate_statement": (
            TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_STATEMENT
        ),
    }
    values.update(overrides)
    return TicketsIncidentsActivationDryRunExecutionFinalReadinessGateCommand(**values)


def test_tickets_incidents_final_readiness_gate_is_metadata_only_after_worker_boundary() -> None:
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

    response = build_tickets_incidents_activation_dry_run_execution_final_readiness_gate_response(
        command=_dry_run_execution_final_readiness_gate_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_ENDPOINT
    assert (
        response.result_contract == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_FINAL_READINESS_GATE_RESULT_CONTRACT
    )
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.human_approval_ready is True
    assert response.activation_dry_run_execution_dispatch_boundary_evidence_hash == NONZERO_DISPATCH_SHA256
    assert response.activation_dry_run_execution_worker_boundary_evidence_hash == NONZERO_WORKER_BOUNDARY_SHA256
    assert response.worker_image_boundary_evidence_bound is False
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_record.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.activation_dry_run_execution_final_readiness_gate_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.activation_dry_run_execution_final_readiness_gate_requested is True
    assert response.activation_dry_run_execution_final_readiness_gate_ready is True
    assert response.future_activation_dry_run_execution_approval_boundary_required is True
    assert response.explicit_human_execution_approval_present is False
    assert response.scheduler_activation_allowed is False
    assert response.scheduler_job_creation_allowed is False
    assert response.scheduler_job_created is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_image_resolved is False
    assert response.worker_image_pull_allowed is False
    assert response.worker_image_pulled is False
    assert response.worker_image_digest_lookup_allowed is False
    assert response.worker_image_digest_looked_up is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.worker_executed is False
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
    assert "bind_tickets_activation_dry_run_execution_worker_boundary_hash" in (
        response.activation_dry_run_execution_final_readiness_gate_steps
    )
    assert "define_final_readiness_gate_requires_separate_explicit_execution_approval_boundary" in (
        response.activation_dry_run_execution_final_readiness_gate_steps
    )
    assert "confirm_no_execution_approval_recorded_at_final_readiness_gate" in (
        response.activation_dry_run_execution_final_readiness_gate_steps
    )
    assert "activation_dry_run_execution_worker_boundary_hash" in (
        response.required_activation_dry_run_execution_final_readiness_gate_evidence
    )
    assert "future_activation_dry_run_execution_approval_boundary_required" in (
        response.required_activation_dry_run_execution_final_readiness_gate_evidence
    )
    assert "separate_explicit_execution_approval_boundary_required" in (
        response.required_activation_dry_run_execution_final_readiness_gate_evidence
    )
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_activation_dry_run_execution_final_readiness_gate_hash(
        response
    )
    assert (
        response.next_action
        == "prepare_tickets_incidents_activation_dry_run_execution_approval_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_final_readiness_gate_blocks_execution_approval_and_worker_activity() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_tickets_incidents_activation_dry_run_execution_final_readiness_gate_response(
        command=_dry_run_execution_final_readiness_gate_command(
            approval_gate_hash=_fake_hash("e"),
            approval_record_hash=_fake_hash("f"),
            activation_dry_run_plan_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_skeleton_evidence_hash=ZERO_SHA256,
            activation_dry_run_executor_implementation_review_evidence_hash=ZERO_SHA256,
            activation_dry_run_result_contract_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_gate_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_request_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_executor_runtime_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_preflight_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_receipt_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_result_persistence_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_activation_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_start_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_dispatch_boundary_evidence_hash=ZERO_SHA256,
            activation_dry_run_execution_worker_boundary_evidence_hash=ZERO_SHA256,
            activation_execution_boundary_evidence_hash=ZERO_SHA256,
            activation_executor_skeleton_evidence_hash=ZERO_SHA256,
            explicit_human_execution_approval_requested=True,
            scheduler_activation_requested=True,
            scheduler_job_creation_requested=True,
            worker_image_resolution_requested=True,
            worker_image_pull_requested=True,
            worker_image_digest_lookup_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            activation_dry_run_execution_requested=True,
            dry_run_result_persistence_requested=True,
            activation_execution_requested=True,
            tenant_provisioning_requested=True,
            tenant_module_state_creation_requested=True,
            migration_execution_requested=True,
            tickets_business_api_activation_requested=True,
            worker_activation_requested=True,
            persistent_task_creation_requested=True,
            content_payload_included=True,
            destructive_actions_requested=True,
            external_side_effect_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore(),
    )

    assert response.activation_dry_run_execution_final_readiness_gate_ready is False
    assert "tickets_incidents_activation_dry_run_execution_dispatch_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_activation_dry_run_execution_worker_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_tenant_admin_activation_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "explicit_human_execution_approval_requires_separate_boundary" in response.blocking_reasons
    assert "scheduler_activation_request_forbidden" in response.blocking_reasons
    assert "scheduler_job_creation_request_forbidden" in response.blocking_reasons
    assert "worker_image_resolution_request_forbidden" in response.blocking_reasons
    assert "worker_image_pull_request_forbidden" in response.blocking_reasons
    assert "worker_image_digest_lookup_request_forbidden" in response.blocking_reasons
    assert "worker_dispatch_request_forbidden" in response.blocking_reasons
    assert "worker_queue_enqueue_request_forbidden" in response.blocking_reasons
    assert "worker_execution_request_forbidden" in response.blocking_reasons
    assert "activation_dry_run_execution_request_forbidden" in response.blocking_reasons
    assert "dry_run_result_persistence_request_forbidden" in response.blocking_reasons
    assert response.future_activation_dry_run_execution_approval_boundary_required is True
    assert response.explicit_human_execution_approval_present is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.activation_dry_run_execution_allowed is False
    assert response.activation_dry_run_executed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == (
        "prepare_tickets_incidents_activation_dry_run_execution_final_readiness_gate_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None
