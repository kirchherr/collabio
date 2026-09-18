from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_approval_boundary import (
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION,
    TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT,
    TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand,
    build_tickets_incidents_activation_dry_run_execution_approval_boundary_hash,
    build_tickets_incidents_activation_dry_run_execution_approval_boundary_response,
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
FINAL_READINESS_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SCHEDULER_BOUNDARY_HASH = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
WORKER_IMAGE_BOUNDARY_HASH = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def _approval_command(
    approval_gate_evidence_hash: str,
) -> TicketsIncidentsTenantAdminActivationApprovalRecordCommand:
    return TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
        approval_gate_evidence_hash=approval_gate_evidence_hash,
        approval_record_ref="tickets-approval:dry-run-execution-approval-boundary-demo",
        approval_ticket_ref="ticket:tickets-dry-run-execution-approval-boundary-demo",
        human_confirmation_reference="confirmation:tickets-dry-run-execution-approval-boundary-demo",
        human_confirmation_statement=TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
        change_request_ref="change:tickets-dry-run-execution-approval-boundary-demo",
        idempotency_key_ref="idempotency:tickets-dry-run-execution-approval-boundary-demo",
        approved_at_utc=datetime(2026, 7, 9, 9, 50, tzinfo=UTC),
        audit_chain_ref="audit:tickets-dry-run-execution-approval-boundary-demo",
    )


def _approval_boundary_command(
    *,
    final_readiness_hash: str = FINAL_READINESS_HASH,
    scheduler_boundary_hash: str = ZERO_SHA256,
    worker_image_boundary_hash: str = ZERO_SHA256,
    activation_dry_run_execution_approval_boundary_requested: bool = True,
    explicit_human_execution_approval_requested: bool = False,
    scheduler_activation_requested: bool = False,
    scheduler_job_creation_requested: bool = False,
    worker_image_resolution_requested: bool = False,
    worker_image_pull_requested: bool = False,
    worker_image_digest_lookup_requested: bool = False,
    worker_dispatch_requested: bool = False,
    worker_queue_enqueue_requested: bool = False,
    worker_execution_requested: bool = False,
    activation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
    activation_execution_requested: bool = False,
    tenant_provisioning_requested: bool = False,
    tenant_module_state_creation_requested: bool = False,
    migration_execution_requested: bool = False,
    tickets_business_api_activation_requested: bool = False,
    worker_activation_requested: bool = False,
    persistent_task_creation_requested: bool = False,
    content_payload_included: bool = False,
    destructive_actions_requested: bool = False,
    external_side_effect_requested: bool = False,
) -> TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand:
    return TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand(
        activation_dry_run_execution_final_readiness_gate_evidence_hash=final_readiness_hash,
        activation_dry_run_execution_scheduler_boundary_evidence_hash=scheduler_boundary_hash,
        activation_dry_run_execution_worker_image_boundary_evidence_hash=worker_image_boundary_hash,
        activation_dry_run_execution_approval_boundary_ref=(
            "tickets-activation-dry-run-execution-approval-boundary:demo"
        ),
        change_request_ref="change:tickets-activation-dry-run-execution-approval-boundary-demo",
        idempotency_key_ref="idempotency:tickets-activation-dry-run-execution-approval-boundary-demo",
        prepared_at_utc=datetime(2026, 7, 9, 9, 55, tzinfo=UTC),
        audit_chain_ref="audit:tickets-activation-dry-run-execution-approval-boundary-demo",
        activation_dry_run_execution_approval_boundary_statement=(
            TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT
        ),
        activation_dry_run_execution_approval_boundary_requested=(
            activation_dry_run_execution_approval_boundary_requested
        ),
        explicit_human_execution_approval_requested=explicit_human_execution_approval_requested,
        scheduler_activation_requested=scheduler_activation_requested,
        scheduler_job_creation_requested=scheduler_job_creation_requested,
        worker_image_resolution_requested=worker_image_resolution_requested,
        worker_image_pull_requested=worker_image_pull_requested,
        worker_image_digest_lookup_requested=worker_image_digest_lookup_requested,
        worker_dispatch_requested=worker_dispatch_requested,
        worker_queue_enqueue_requested=worker_queue_enqueue_requested,
        worker_execution_requested=worker_execution_requested,
        activation_dry_run_execution_requested=activation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
        activation_execution_requested=activation_execution_requested,
        tenant_provisioning_requested=tenant_provisioning_requested,
        tenant_module_state_creation_requested=tenant_module_state_creation_requested,
        migration_execution_requested=migration_execution_requested,
        tickets_business_api_activation_requested=tickets_business_api_activation_requested,
        worker_activation_requested=worker_activation_requested,
        persistent_task_creation_requested=persistent_task_creation_requested,
        content_payload_included=content_payload_included,
        destructive_actions_requested=destructive_actions_requested,
        external_side_effect_requested=external_side_effect_requested,
    )


def test_tickets_incidents_activation_dry_run_execution_approval_boundary_is_metadata_only() -> None:
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

    response = build_tickets_incidents_activation_dry_run_execution_approval_boundary_response(
        command=_approval_boundary_command(
            scheduler_boundary_hash=SCHEDULER_BOUNDARY_HASH,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.approval_gate_ready is True
    assert response.human_approval_ready is True
    assert response.activation_dry_run_execution_final_readiness_gate_evidence_hash == FINAL_READINESS_HASH
    assert response.activation_dry_run_execution_scheduler_boundary_evidence_hash == SCHEDULER_BOUNDARY_HASH
    assert response.activation_dry_run_execution_worker_image_boundary_evidence_hash == WORKER_IMAGE_BOUNDARY_HASH
    assert response.worker_image_boundary_evidence_bound is True
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.tickets_restore_drill_evidence_hash == approval_record.tickets_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.activation_dry_run_execution_approval_boundary_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.activation_dry_run_execution_approval_boundary_requested is True
    assert response.activation_dry_run_execution_approval_boundary_ready is True
    assert response.future_activation_dry_run_execution_approval_record_required is True
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
    assert "define_approval_boundary_idempotency_and_hash_closure" in (
        response.activation_dry_run_execution_approval_boundary_steps
    )
    assert "confirm_no_execution_approval_recorded_at_approval_boundary" in (
        response.activation_dry_run_execution_approval_boundary_steps
    )
    assert "worker_image_boundary_chain_hashes_when_present" in (
        response.required_activation_dry_run_execution_approval_boundary_evidence
    )
    assert "future_activation_dry_run_execution_approval_record_required" in (
        response.required_activation_dry_run_execution_approval_boundary_evidence
    )
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_tickets_incidents_activation_dry_run_execution_approval_boundary_hash(
        response
    )
    assert response.next_action == (
        "record_tickets_incidents_activation_dry_run_execution_approval_with_explicit_human_confirmation"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None


def test_tickets_incidents_activation_dry_run_execution_approval_boundary_blocks_execution_requests() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_tickets_incidents_activation_dry_run_execution_approval_boundary_response(
        command=_approval_boundary_command(
            final_readiness_hash=ZERO_SHA256,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
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

    assert response.activation_dry_run_execution_approval_boundary_ready is False
    assert (
        "tickets_incidents_activation_dry_run_execution_final_readiness_gate_hash_missing" in response.blocking_reasons
    )
    assert "tickets_incidents_activation_dry_run_execution_scheduler_boundary_hash_missing" in response.blocking_reasons
    assert "tickets_incidents_tenant_admin_activation_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "explicit_human_execution_approval_requires_separate_record" in response.blocking_reasons
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
    assert "activation_execution_request_forbidden" in response.blocking_reasons
    assert "tenant_provisioning_request_forbidden" in response.blocking_reasons
    assert "tenant_module_state_creation_request_forbidden" in response.blocking_reasons
    assert "migration_execution_request_forbidden" in response.blocking_reasons
    assert "tickets_business_api_activation_request_forbidden" in response.blocking_reasons
    assert "worker_activation_request_forbidden" in response.blocking_reasons
    assert "persistent_task_creation_request_forbidden" in response.blocking_reasons
    assert "content_payload_forbidden" in response.blocking_reasons
    assert "destructive_action_request_forbidden" in response.blocking_reasons
    assert "external_side_effect_request_forbidden" in response.blocking_reasons
    assert response.explicit_human_execution_approval_present is False
    assert response.worker_image_boundary_evidence_bound is True
    assert response.scheduler_activation_allowed is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.activation_dry_run_execution_allowed is False
    assert response.activation_dry_run_executed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == (
        "prepare_tickets_incidents_activation_dry_run_execution_approval_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="tickets_incidents") is None
