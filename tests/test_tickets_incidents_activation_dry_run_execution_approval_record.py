from datetime import UTC, datetime

import pytest

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_activation_dry_run_execution_approval_record import (
    CONFIRMATION_STATEMENT,
    InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
    TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand,
    build_tickets_incidents_activation_dry_run_execution_approval_record_response,
    build_tickets_incidents_controlled_pilot_approval_boundary_hash,
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

BOUNDARY_HASH = "sha256:" + ("a" * 64)


def expected_boundary_hash(
    *,
    user_context: UserContext,
    store: InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore,
) -> str:
    gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
    )
    tenant_approval = store.latest_for_gate(
        tenant_id=user_context.tenant_id,
        approval_gate_evidence_hash=gate.evidence_hash,
    )
    assert tenant_approval is not None
    assert gate.tickets_restore_drill_evidence_hash is not None
    return build_tickets_incidents_controlled_pilot_approval_boundary_hash(
        tenant_id=user_context.tenant_id,
        tenant_admin_approval_record_hash=tenant_approval.evidence_hash,
        tickets_restore_drill_evidence_hash=gate.tickets_restore_drill_evidence_hash,
        feature_manifest_hash=build_default_tickets_incidents_subfeature_registry().manifest_hash,
    )


def build_tenant_approval_store(
    user_context: UserContext,
) -> InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore:
    module_registry = default_module_registry()
    manifest = load_migration_manifest()
    gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )
    tenant_record = build_tickets_incidents_tenant_admin_activation_approval_record_response(
        command=TicketsIncidentsTenantAdminActivationApprovalRecordCommand(
            approval_gate_evidence_hash=gate.evidence_hash,
            approval_record_ref="tickets-approval:tenant-record",
            approval_ticket_ref="ticket:tenant-activation",
            human_confirmation_reference="confirmation:tenant-activation",
            human_confirmation_statement=(
                TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
            ),
            change_request_ref="change:tenant-activation",
            idempotency_key_ref="idempotency:tenant-activation",
            approved_at_utc=datetime(2026, 7, 29, 7, 30, tzinfo=UTC),
            audit_chain_ref="audit:tenant-activation",
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=manifest,
    )
    store = InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore()
    store.append(tenant_record)
    return store


def execution_approval_command(
    **changes: object,
) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand:
    values: dict[str, object] = {
        "approval_boundary_evidence_hash": BOUNDARY_HASH,
        "approval_record_ref": "tickets-dry-run-approval:record-1",
        "approval_ticket_ref": "ticket:dry-run-approval",
        "human_confirmation_reference": "confirmation:dry-run-approval",
        "human_confirmation_statement": CONFIRMATION_STATEMENT,
        "change_request_ref": "change:dry-run-approval",
        "idempotency_key_ref": "idempotency:dry-run-approval",
        "approved_at_utc": datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
        "audit_chain_ref": "audit:dry-run-approval",
    }
    values.update(changes)
    return TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand.model_validate(values)


def test_execution_approval_record_is_explicit_append_only_and_non_executing() -> None:
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-1",
        role_ids={"tenant-admin"},
    )
    store = build_tenant_approval_store(user_context)
    boundary_hash = expected_boundary_hash(user_context=user_context, store=store)

    response = build_tickets_incidents_activation_dry_run_execution_approval_record_response(
        command=execution_approval_command(approval_boundary_evidence_hash=boundary_hash),
        user_context=user_context,
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
        tenant_approval_record_store=store,
    )
    approval_store = InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore()

    assert response.approval_record_created is True
    assert response.explicit_human_execution_approval_present is True
    assert response.worker_execution_allowed is False
    assert response.activation_dry_run_execution_allowed is False
    assert response.tickets_business_api_allowed is False
    assert response.tenant_module_state_created is False
    assert response.content_included is False
    assert response.blocking_reasons == ()
    assert "human_confirmation_statement" not in response.model_dump()
    assert approval_store.append(response) == response
    assert approval_store.append(response) == response
    assert (
        approval_store.latest_for_boundary(
            tenant_id="tenant-demo",
            approval_boundary_evidence_hash=boundary_hash,
        )
        == response
    )


def test_execution_approval_record_rejects_side_effect_requests() -> None:
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-1",
        role_ids={"tenant-admin"},
    )
    store = build_tenant_approval_store(user_context)
    boundary_hash = expected_boundary_hash(user_context=user_context, store=store)
    response = build_tickets_incidents_activation_dry_run_execution_approval_record_response(
        command=execution_approval_command(
            approval_boundary_evidence_hash=boundary_hash,
            worker_execution_requested=True,
        ),
        user_context=user_context,
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
        tenant_approval_record_store=store,
    )

    assert response.approval_record_created is False
    assert "worker_execution_request_forbidden" in response.blocking_reasons
    with pytest.raises(ValueError, match="blocked"):
        InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore().append(response)


def test_execution_approval_rejects_untrusted_boundary_hash() -> None:
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-1",
        role_ids={"tenant-admin"},
    )
    response = build_tickets_incidents_activation_dry_run_execution_approval_record_response(
        command=execution_approval_command(),
        user_context=user_context,
        module_registry=default_module_registry(),
        migration_manifest_entries=load_migration_manifest(),
        tenant_approval_record_store=build_tenant_approval_store(user_context),
    )

    assert response.approval_record_created is False
    assert "activation_dry_run_execution_approval_boundary_hash_mismatch" in response.blocking_reasons


def test_execution_approval_command_requires_exact_human_confirmation() -> None:
    with pytest.raises(ValueError, match="exact Tickets"):
        execution_approval_command(human_confirmation_statement="approve")
