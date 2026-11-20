from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import build_app
from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import (
    PilotTenantEvidence,
    ProductivityPilotPreflightGate,
    build_productivity_pilot_preflight_gate_hash,
)
from suite.persistence.migration_catalog import get_migration
from suite.platform.productivity_pilot_admission import InMemoryProductivityPilotPreflightStore
from suite.platform.productivity_pilot_closure_report import (
    InMemoryProductivityPilotClosureReportStore,
    ProductivityPilotClosureReport,
    ProductivityPilotDomainReceiptEvidence,
    ProductivityPilotOperationObservationSummary,
    ProductivityPilotRecoveryEvidence,
    build_productivity_pilot_closure_report_hash,
)
from suite.platform.productivity_pilot_real_user_admission import (
    PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_CONFIRMATION_STATEMENT,
    PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotParticipantDirectory,
    InMemoryProductivityPilotRealUserAdmissionStore,
    ProductivityPilotParticipantIdentity,
    ProductivityPilotPrincipalSnapshot,
    ProductivityPilotRealUserAdmissionCommand,
    ProductivityPilotRealUserAdmissionConflict,
    ProductivityPilotRealUserAdmissionService,
    ProductivityPilotRealUserNominationCommand,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
TENANT_ID = "tenant-demo"
PARTICIPANT_ID = "real-pilot-user"


def _hash(value: int) -> str:
    return f"sha256:{value:064x}"


def _closure() -> ProductivityPilotClosureReport:
    draft = ProductivityPilotClosureReport(
        tenant_id=TENANT_ID,
        closure_id="pilot-closure-development",
        window_id="pilot-window-development",
        authorization_id="pilot-start-development",
        runtime_window_evidence_hash=_hash(1),
        start_authorization_evidence_hash=_hash(2),
        route_scope_hash=_hash(3),
        observation_manifest_hash=_hash(4),
        observation_count=1,
        distinct_principal_hash_count=1,
        operation_summaries=(
            ProductivityPilotOperationObservationSummary(
                operation="GET /v1/tasks/items",
                observation_count=1,
            ),
        ),
        domain_receipt_manifest_hash=_hash(5),
        domain_receipts=(
            ProductivityPilotDomainReceiptEvidence(
                operation="POST /v1/tasks/items",
                receipt_hash=_hash(6),
                principal_id_hash=_hash(7),
                committed_at_utc=NOW - timedelta(days=1),
            ),
        ),
        recovery_evidence=ProductivityPilotRecoveryEvidence(
            backup_sha256=_hash(8),
            postgres_restore_drill_report_hash=_hash(9),
            backend_foundation_gate_hash=_hash(10),
            business_backend_release_gate_hash=_hash(11),
            observed_at_utc=NOW - timedelta(days=1),
            restored_runtime_window_count=1,
            restored_observation_count=1,
            restored_domain_receipt_count=1,
        ),
        command_hash=_hash(12),
        idempotency_key_hash=_hash(13),
        human_confirmation_statement_hash=_hash(14),
        change_request_ref="change:closed-development-pilot",
        human_confirmation_reference="approval:closed-development-pilot",
        operations_owner_ref="principal:operations-owner",
        recovery_owner_ref="principal:recovery-owner",
        audit_chain_ref="audit:closed-development-pilot",
        closed_by="security-admin-development",
        closed_at_utc=NOW - timedelta(days=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_closure_report_hash(draft)})


def _gate(*, checked_at: datetime = NOW + timedelta(minutes=2)) -> ProductivityPilotPreflightGate:
    draft = ProductivityPilotPreflightGate(
        checked_at_utc=checked_at.isoformat(),
        runtime_environment="test",
        policy_id="controlled-productivity-pilot",
        policy_hash=_hash(21),
        business_backend_release_gate_hash=_hash(22),
        business_backend_release_ready=True,
        candidate_tenant_ids=(TENANT_ID,),
        candidate_tenant_count=1,
        maximum_candidate_tenant_count=10,
        tenant_module_state_manifest_hash=_hash(23),
        tenants=(
            PilotTenantEvidence(
                tenant_id=TENANT_ID,
                slices=(),
                ready_slice_count=3,
                ready=True,
            ),
        ),
        ready_tenant_count=1,
        productive_slice_count=3,
        route_scope_contract_verified=True,
        monitoring_contract_verified=True,
        monitoring_control_count=5,
        rollback_contract_verified=True,
        rollback_control_count=4,
        human_admission_required=True,
        traffic_scope_enforcement_required=True,
        preflight_ready=True,
        next_action="record_explicit_human_pilot_admission_and_enforce_traffic_scope",
        gate_hash=_hash(0),
    )
    return draft.model_copy(update={"gate_hash": build_productivity_pilot_preflight_gate_hash(draft)})


def _participant(*, roles: tuple[str, ...] = ("knowledge-worker",)) -> ProductivityPilotParticipantIdentity:
    return ProductivityPilotParticipantIdentity(
        principal_id=PARTICIPANT_ID,
        required_role_ids=roles,
        participation_notice_ref="notice:real-pilot-user-v1",
        training_evidence_ref="training:real-pilot-user-v1",
    )


def _directory() -> InMemoryProductivityPilotParticipantDirectory:
    return InMemoryProductivityPilotParticipantDirectory(
        {
            (TENANT_ID, PARTICIPANT_ID): ProductivityPilotPrincipalSnapshot(
                principal_id=PARTICIPANT_ID,
                role_ids=("knowledge-worker",),
            )
        }
    )


def _nomination_command(closure: ProductivityPilotClosureReport) -> ProductivityPilotRealUserNominationCommand:
    return ProductivityPilotRealUserNominationCommand(
        nomination_id="real-pilot-nomination-one",
        baseline_closure_evidence_hash=closure.evidence_hash,
        purpose_code="validate_productivity_workflows",
        purpose_ref="purpose:real-pilot-v1",
        lawful_basis_ref="lawful-basis:tenant-assessment-v1",
        privacy_risk_assessment_ref="privacy-risk:real-pilot-v1",
        retention_policy_id="rp-audit-3650d",
        data_classification="internal",
        participants=(_participant(),),
        scheduled_start_at_utc=NOW + timedelta(hours=1),
        scheduled_end_at_utc=NOW + timedelta(hours=3),
        dpia_required=False,
        works_council_review_required=False,
        idempotency_key_ref="request:real-pilot-nomination-one",
        change_request_ref="change:real-pilot-one",
        human_confirmation_reference="approval:tenant-real-pilot-one",
        human_confirmation_statement=(PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_CONFIRMATION_STATEMENT),
        audit_chain_ref="audit:real-pilot-nomination-one",
        nominated_at_utc=NOW,
    )


def _admission_command(
    *,
    nomination_hash: str,
    gate: ProductivityPilotPreflightGate,
) -> ProductivityPilotRealUserAdmissionCommand:
    return ProductivityPilotRealUserAdmissionCommand(
        admission_id="real-pilot-admission-one",
        nomination_id="real-pilot-nomination-one",
        nomination_evidence_hash=nomination_hash,
        participants=(_participant(),),
        preflight_gate_hash=gate.gate_hash,
        policy_hash=gate.policy_hash,
        business_backend_release_gate_hash=gate.business_backend_release_gate_hash,
        tenant_module_state_manifest_hash=gate.tenant_module_state_manifest_hash,
        backup_sha256=_hash(31),
        postgres_restore_drill_report_hash=_hash(32),
        backend_foundation_gate_hash=_hash(33),
        control_evidence_observed_at_utc=NOW + timedelta(minutes=3),
        security_review_ref="security-review:real-pilot-one",
        privacy_approval_ref="privacy-approval:real-pilot-one",
        idempotency_key_ref="request:real-pilot-admission-one",
        change_request_ref="change:real-pilot-one",
        human_confirmation_reference="approval:security-real-pilot-one",
        human_confirmation_statement=(PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_CONFIRMATION_STATEMENT),
        audit_chain_ref="audit:real-pilot-admission-one",
        approved_at_utc=NOW + timedelta(minutes=5),
    )


def _service(
    *,
    closure: ProductivityPilotClosureReport,
    gate: ProductivityPilotPreflightGate,
    store: InMemoryProductivityPilotRealUserAdmissionStore,
    now: datetime = NOW,
) -> ProductivityPilotRealUserAdmissionService:
    return ProductivityPilotRealUserAdmissionService(
        participant_directory=_directory(),
        closure_store=InMemoryProductivityPilotClosureReportStore((closure,)),
        preflight_store=InMemoryProductivityPilotPreflightStore((gate,)),
        record_store=store,
        clock=lambda: now,
    )


def test_real_user_nomination_and_admission_are_pseudonymized_append_only_and_non_executing() -> None:
    closure = _closure()
    gate = _gate()
    store = InMemoryProductivityPilotRealUserAdmissionStore()
    service = _service(closure=closure, gate=gate, store=store)
    nomination_command = _nomination_command(closure)

    nomination = service.nominate(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="tenant-nominator",
            role_ids={"tenant-admin"},
        ),
        command=nomination_command,
    )
    nomination_replay = service.nominate(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="tenant-nominator",
            role_ids={"tenant-admin"},
        ),
        command=nomination_command,
    )

    assert nomination.evidence_hash == build_productivity_pilot_real_user_nomination_hash(nomination)
    assert nomination_replay.idempotent_replay is True
    assert nomination.participant_count == 1
    assert PARTICIPANT_ID not in nomination.model_dump_json()
    assert nomination.runtime_activation_allowed is False
    assert nomination.traffic_authorization_allowed is False

    service.clock = lambda: NOW + timedelta(minutes=5)
    admission_command = _admission_command(
        nomination_hash=nomination.evidence_hash,
        gate=gate,
    )
    admission = service.approve(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="independent-security-approver",
            role_ids={"security-admin"},
        ),
        command=admission_command,
    )
    replay = service.approve(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="independent-security-approver",
            role_ids={"security-admin"},
        ),
        command=admission_command,
    )

    assert admission.evidence_hash == build_productivity_pilot_real_user_admission_hash(admission)
    assert replay.idempotent_replay is True
    assert PARTICIPANT_ID not in admission.model_dump_json()
    assert admission.four_eyes_verified is True
    assert admission.fresh_control_evidence_verified is True
    assert admission.runtime_activation_allowed is False
    assert admission.traffic_authorization_allowed is False
    assert admission.business_write_executed is False


def test_real_user_workflow_fails_closed_for_roles_identity_and_stale_controls() -> None:
    closure = _closure()
    gate = _gate()
    store = InMemoryProductivityPilotRealUserAdmissionStore()
    service = _service(closure=closure, gate=gate, store=store)
    command = _nomination_command(closure)

    with pytest.raises(PermissionError, match="tenant admin"):
        service.nominate(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id="reader",
                role_ids={"knowledge-worker"},
            ),
            command=command,
        )
    with pytest.raises(ProductivityPilotRealUserAdmissionConflict, match="required authoritative role"):
        service.nominate(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id="tenant-nominator",
                role_ids={"tenant-admin"},
            ),
            command=command.model_copy(update={"participants": (_participant(roles=("records-admin",)),)}),
        )

    nomination = service.nominate(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="tenant-nominator",
            role_ids={"tenant-admin"},
        ),
        command=command,
    )
    stale_gate = _gate(checked_at=NOW - timedelta(minutes=1))
    stale_service = _service(
        closure=closure,
        gate=stale_gate,
        store=store,
        now=NOW + timedelta(minutes=5),
    )
    with pytest.raises(ProductivityPilotRealUserAdmissionConflict, match="fresh authoritative"):
        stale_service.approve(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id="independent-security-approver",
                role_ids={"security-admin"},
            ),
            command=_admission_command(
                nomination_hash=nomination.evidence_hash,
                gate=stale_gate,
            ),
        )


def test_real_user_api_audits_hashes_without_principal_ids_and_remains_non_executing() -> None:
    closure = _closure()
    gate = _gate()
    store = InMemoryProductivityPilotRealUserAdmissionStore()
    service = _service(closure=closure, gate=gate, store=store)
    test_app = build_app()
    test_app.state.productivity_pilot_real_user_admission_service = service
    client = TestClient(test_app)
    tenant_headers = {
        "X-Tenant-Id": TENANT_ID,
        "X-User-Id": "tenant-nominator",
        "X-Role-Ids": "tenant-admin",
    }
    security_headers = {
        "X-Tenant-Id": TENANT_ID,
        "X-User-Id": "independent-security-approver",
        "X-Role-Ids": "security-admin",
    }

    nomination_response = client.post(
        "/v1/platform/productivity-pilot/real-user-nominations",
        headers=tenant_headers,
        json=_nomination_command(closure).model_dump(mode="json"),
    )
    assert nomination_response.status_code == 201
    nomination_body = nomination_response.json()
    assert PARTICIPANT_ID not in nomination_response.text
    assert nomination_body["runtime_activation_allowed"] is False
    assert nomination_body["traffic_authorization_allowed"] is False
    nomination_event = test_app.state.audit_logger.events[-1]
    assert nomination_event.event_type == ("platform.productivity_pilot.real_user_nomination_recorded")
    assert PARTICIPANT_ID not in str(nomination_event.metadata)

    service.clock = lambda: NOW + timedelta(minutes=5)
    admission_response = client.post(
        "/v1/platform/productivity-pilot/real-user-admissions",
        headers=security_headers,
        json=_admission_command(
            nomination_hash=nomination_body["evidence_hash"],
            gate=gate,
        ).model_dump(mode="json"),
    )
    assert admission_response.status_code == 201
    assert PARTICIPANT_ID not in admission_response.text
    assert admission_response.json()["runtime_activation_allowed"] is False
    admission_event = test_app.state.audit_logger.events[-1]
    assert admission_event.event_type == ("platform.productivity_pilot.real_user_admission_recorded")
    assert PARTICIPANT_ID not in str(admission_event.metadata)
    current = client.get(
        "/v1/platform/productivity-pilot/real-user-admissions/current",
        headers=security_headers,
    )
    assert current.status_code == 200
    assert current.json()["evidence_hash"] == admission_response.json()["evidence_hash"]


def test_real_user_commands_require_conditional_privacy_evidence_and_exact_confirmation() -> None:
    payload = _nomination_command(_closure()).model_dump()
    with pytest.raises(ValidationError, match="DPIA reference"):
        ProductivityPilotRealUserNominationCommand.model_validate({**payload, "dpia_required": True})
    with pytest.raises(ValidationError, match="exact real-user pilot nomination"):
        ProductivityPilotRealUserNominationCommand.model_validate(
            {**payload, "human_confirmation_statement": "approve"}
        )


def test_real_user_admission_migration_is_pseudonymized_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0066")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_real_user_nominations" in sql
    assert "create table if not exists collabio.productivity_pilot_real_user_admissions" in sql
    assert "force row level security" in sql
    assert "productivity_pilot_real_user_nominations_append_only" in sql
    assert "productivity_pilot_real_user_admissions_append_only" in sql
    assert "nominated_by_principal_hash" in sql
    assert "approved_by_principal_hash" in sql
    assert "grant select, insert on table collabio.productivity_pilot_real_user_admissions" in sql
    assert "runtime and traffic remain disabled" in sql
