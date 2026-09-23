from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import build_app
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import get_migration
from suite.platform.productivity_pilot_closure_report import (
    InMemoryProductivityPilotDomainReceiptStore,
    ProductivityPilotDomainReceipt,
)
from suite.platform.productivity_pilot_real_user_admission import (
    InMemoryProductivityPilotRealUserAdmissionStore,
    ProductivityPilotParticipantEvidence,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_real_user_closure_report import (
    PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotRealUserClosureReportStore,
    ProductivityPilotRealUserClosureCommand,
    ProductivityPilotRealUserClosureConflict,
    ProductivityPilotRealUserClosureService,
    ProductivityPilotRealUserRecoveryEvidence,
    build_productivity_pilot_real_user_closure_report_hash,
)
from suite.platform.productivity_pilot_real_user_runtime_window import (
    InMemoryProductivityPilotRealUserRuntimeWindowStore,
    ProductivityPilotRealUserRuntimeObservation,
    ProductivityPilotRealUserRuntimeWindow,
    build_productivity_pilot_real_user_designated_principal_manifest_hash,
    build_productivity_pilot_real_user_runtime_observation_hash,
    build_productivity_pilot_real_user_runtime_window_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    build_productivity_pilot_principal_observation_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    InMemoryProductivityPilotStartAuthorizationStore,
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_start_authorization_hash,
)

TENANT_ID = "tenant-demo"
PARTICIPANT_ID = "real-user-closure-participant"
OPERATION = "POST /v1/tasks/items"
NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)


def _hash(index: int) -> str:
    return f"sha256:{index:064x}"


def _principal_hash(principal_id: str = PARTICIPANT_ID) -> str:
    return build_productivity_pilot_principal_observation_hash(
        tenant_id=TENANT_ID,
        principal_id=principal_id,
    )


def _nomination() -> ProductivityPilotRealUserNomination:
    participant = ProductivityPilotParticipantEvidence(
        principal_id_hash=_principal_hash(),
        authoritative_role_ids=("knowledge-worker",),
        role_manifest_hash=_hash(1),
        participation_notice_evidence_hash=_hash(2),
        training_evidence_hash=_hash(3),
    )
    draft = ProductivityPilotRealUserNomination(
        tenant_id=TENANT_ID,
        nomination_id="real-user-closure-nomination",
        baseline_closure_id="development-closure",
        baseline_closure_evidence_hash=_hash(4),
        purpose_code="validate_productivity_workflows",
        purpose_ref="purpose:real-user-closure",
        lawful_basis_ref="lawful-basis:tenant-assessment",
        privacy_risk_assessment_ref="privacy-risk:real-user-closure",
        retention_policy_id="rp-audit-3650d",
        data_classification="internal",
        participants=(participant,),
        participant_manifest_hash=_hash(5),
        participant_count=1,
        scheduled_start_at_utc=NOW - timedelta(hours=1),
        scheduled_end_at_utc=NOW + timedelta(hours=1),
        dpia_required=False,
        dpia_ref=None,
        works_council_review_required=False,
        works_council_approval_ref=None,
        command_hash=_hash(6),
        idempotency_key_hash=_hash(7),
        human_confirmation_statement_hash=_hash(8),
        change_request_ref="change:real-user-closure",
        human_confirmation_reference="approval:real-user-closure-nomination",
        audit_chain_ref="audit:real-user-closure-nomination",
        nominated_by_principal_hash=_principal_hash("real-user-nominator"),
        nominated_at_utc=NOW - timedelta(hours=2),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_nomination_hash(draft)})


def _admission(nomination: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserAdmission:
    draft = ProductivityPilotRealUserAdmission(
        tenant_id=TENANT_ID,
        admission_id="real-user-closure-admission",
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        baseline_closure_evidence_hash=nomination.baseline_closure_evidence_hash,
        participant_manifest_hash=nomination.participant_manifest_hash,
        participant_count=1,
        approved_principal_hashes=(_principal_hash(),),
        preflight_gate_hash=_hash(11),
        policy_hash=_hash(12),
        business_backend_release_gate_hash=_hash(13),
        tenant_module_state_manifest_hash=_hash(14),
        backup_sha256=_hash(15),
        postgres_restore_drill_report_hash=_hash(16),
        backend_foundation_gate_hash=_hash(17),
        control_evidence_observed_at_utc=NOW - timedelta(minutes=50),
        scheduled_start_at_utc=nomination.scheduled_start_at_utc,
        scheduled_end_at_utc=nomination.scheduled_end_at_utc,
        security_review_ref="security-review:real-user-closure",
        privacy_approval_ref="privacy-approval:real-user-closure",
        command_hash=_hash(18),
        idempotency_key_hash=_hash(19),
        human_confirmation_statement_hash=_hash(20),
        change_request_ref="change:real-user-closure",
        human_confirmation_reference="approval:real-user-closure-admission",
        audit_chain_ref="audit:real-user-closure-admission",
        approved_by_principal_hash=_principal_hash("real-user-security-approver"),
        approved_at_utc=NOW - timedelta(minutes=45),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_admission_hash(draft)})


def _start(admission: ProductivityPilotRealUserAdmission) -> ProductivityPilotStartAuthorization:
    draft = ProductivityPilotStartAuthorization(
        tenant_id=TENANT_ID,
        authorization_id="real-user-closure-start",
        enforcement_id="real-user-closure-traffic",
        traffic_scope_evidence_hash=_hash(21),
        route_scope_hash=_hash(22),
        admission_evidence_hash=_hash(23),
        preflight_gate_hash=admission.preflight_gate_hash,
        policy_hash=admission.policy_hash,
        allowed_api_operations=(OPERATION,),
        monitoring_evidence=(),
        rollback_evidence=(),
        monitoring_evidence_manifest_hash=_hash(24),
        rollback_evidence_manifest_hash=_hash(25),
        command_hash=_hash(26),
        idempotency_key_hash=_hash(27),
        human_confirmation_statement_hash=_hash(28),
        change_request_ref="change:real-user-closure",
        human_confirmation_reference="approval:real-user-closure-start",
        security_approval_ref="security:real-user-closure-start",
        audit_chain_ref="audit:real-user-closure-start",
        authorized_by="real-user-start-authorizer",
        authorized_at_utc=NOW - timedelta(minutes=40),
        effective_at_utc=NOW - timedelta(minutes=30),
        expires_at_utc=NOW + timedelta(minutes=30),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_start_authorization_hash(draft)})


def _window(
    nomination: ProductivityPilotRealUserNomination,
    admission: ProductivityPilotRealUserAdmission,
    start: ProductivityPilotStartAuthorization,
) -> ProductivityPilotRealUserRuntimeWindow:
    principal_hashes = (_principal_hash(),)
    draft = ProductivityPilotRealUserRuntimeWindow(
        tenant_id=TENANT_ID,
        window_id="real-user-closure-window",
        admission_id=admission.admission_id,
        real_user_admission_evidence_hash=admission.evidence_hash,
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        designated_principal_hashes=principal_hashes,
        designated_principal_manifest_hash=(
            build_productivity_pilot_real_user_designated_principal_manifest_hash(
                tenant_id=TENANT_ID,
                designated_principal_hashes=principal_hashes,
            )
        ),
        participant_role_snapshot_hash=_hash(31),
        allowed_api_operations=(OPERATION,),
        route_scope_hash=start.route_scope_hash,
        command_hash=_hash(32),
        idempotency_key_hash=_hash(33),
        human_confirmation_statement_hash=_hash(34),
        change_request_ref="change:real-user-closure",
        human_confirmation_reference="approval:real-user-runtime",
        operations_owner_ref="control-owner:real-user-runtime",
        audit_chain_ref="audit:real-user-runtime",
        activated_by_principal_hash=_principal_hash("real-user-runtime-operator"),
        activated_at_utc=NOW - timedelta(minutes=30),
        effective_at_utc=NOW - timedelta(minutes=30),
        expires_at_utc=NOW + timedelta(minutes=30),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_runtime_window_hash(draft)})


def _observation(window: ProductivityPilotRealUserRuntimeWindow) -> ProductivityPilotRealUserRuntimeObservation:
    draft = ProductivityPilotRealUserRuntimeObservation(
        tenant_id=TENANT_ID,
        observation_id="real-user-closure-observation",
        window_id=window.window_id,
        admission_id=window.admission_id,
        real_user_admission_evidence_hash=window.real_user_admission_evidence_hash,
        authorization_id=window.authorization_id,
        start_authorization_evidence_hash=window.start_authorization_evidence_hash,
        window_evidence_hash=window.evidence_hash,
        principal_id_hash=_principal_hash(),
        operation=OPERATION,
        observed_at_utc=NOW - timedelta(minutes=10),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(
        update={"evidence_hash": build_productivity_pilot_real_user_runtime_observation_hash(draft)}
    )


def _command(
    window: ProductivityPilotRealUserRuntimeWindow,
    *,
    observation_count: int = 1,
    receipt_count: int = 1,
) -> ProductivityPilotRealUserClosureCommand:
    return ProductivityPilotRealUserClosureCommand(
        closure_id="real-user-closure-one",
        window_id=window.window_id,
        runtime_window_evidence_hash=window.evidence_hash,
        recovery_evidence=ProductivityPilotRealUserRecoveryEvidence(
            backup_sha256=_hash(40),
            postgres_restore_drill_report_hash=_hash(41),
            backend_foundation_gate_hash=_hash(42),
            business_backend_release_gate_hash=_hash(43),
            observed_at_utc=NOW + timedelta(minutes=2),
            restored_runtime_window_count=1,
            restored_observation_count=observation_count,
            restored_domain_receipt_count=receipt_count,
        ),
        idempotency_key_ref="request:real-user-closure-one",
        change_request_ref="change:real-user-closure",
        human_confirmation_reference="approval:real-user-closure",
        operations_owner_ref="control-owner:real-user-operations",
        recovery_owner_ref="control-owner:real-user-recovery",
        audit_chain_ref="audit:real-user-closure",
        human_confirmation_statement=PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_CONFIRMATION_STATEMENT,
        closed_at_utc=NOW,
    )


def _service(
    *,
    with_observation: bool = True,
    with_receipt: bool = True,
    runtime_enabled: bool = False,
) -> tuple[
    ProductivityPilotRealUserClosureService,
    ProductivityPilotRealUserRuntimeWindow,
    InMemoryProductivityPilotRealUserClosureReportStore,
]:
    nomination = _nomination()
    admission = _admission(nomination)
    start = _start(admission)
    window = _window(nomination, admission, start)
    runtime_store = InMemoryProductivityPilotRealUserRuntimeWindowStore(
        windows=(window,),
        observations=(_observation(window),) if with_observation else (),
    )
    receipts = (
        (
            ProductivityPilotDomainReceipt(
                operation=OPERATION,
                receipt_hash=_hash(44),
                created_by=PARTICIPANT_ID,
                committed_at_utc=NOW - timedelta(minutes=9),
            ),
        )
        if with_receipt
        else ()
    )
    closure_store = InMemoryProductivityPilotRealUserClosureReportStore()
    return (
        ProductivityPilotRealUserClosureService(
            start_authorization_store=InMemoryProductivityPilotStartAuthorizationStore((start,)),
            real_user_admission_store=InMemoryProductivityPilotRealUserAdmissionStore(
                nominations=(nomination,),
                admissions=(admission,),
            ),
            runtime_window_store=runtime_store,
            domain_receipt_store=InMemoryProductivityPilotDomainReceiptStore(receipts),
            closure_report_store=closure_store,
            runtime_enabled=runtime_enabled,
        ),
        window,
        closure_store,
    )


def _security_context(user_id: str = "real-user-independent-closer") -> UserContext:
    return UserContext(tenant_id=TENANT_ID, user_id=user_id, role_ids={"security-admin"})


def test_real_user_closure_binds_hash_only_observations_receipts_and_recovery() -> None:
    service, window, store = _service()
    command = _command(window)

    record = service.close(user_context=_security_context(), command=command)
    replay = service.close(user_context=_security_context(), command=command)

    assert record.evidence_hash == build_productivity_pilot_real_user_closure_report_hash(record)
    assert record.observation_count == 1
    assert record.observed_principal_hashes == (_principal_hash(),)
    assert len(record.domain_receipts) == 1
    assert record.pilot_activity_observed is True
    assert replay.idempotent_replay is True
    assert len(store.records) == 1
    serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    assert PARTICIPANT_ID not in serialized
    assert "real-user-independent-closer" not in serialized
    assert "closed_by" not in type(record).model_fields
    assert "human_confirmation_statement" not in record.model_dump(mode="json")


def test_real_user_closure_can_preserve_an_unused_window_without_inventing_activity() -> None:
    service, window, _ = _service(with_observation=False, with_receipt=False)

    record = service.close(
        user_context=_security_context(),
        command=_command(window, observation_count=0, receipt_count=0),
    )

    assert record.observation_count == 0
    assert record.operation_summaries == ()
    assert record.domain_receipts == ()
    assert record.pilot_activity_observed is False


def test_real_user_closure_fails_closed_for_unobserved_receipt_open_switch_and_actor_overlap() -> None:
    missing_observation_service, window, _ = _service(with_observation=False, with_receipt=True)
    with pytest.raises(ProductivityPilotRealUserClosureConflict, match="not covered"):
        missing_observation_service.close(
            user_context=_security_context(),
            command=_command(window, observation_count=0, receipt_count=1),
        )

    enabled_service, enabled_window, _ = _service(runtime_enabled=True)
    with pytest.raises(ProductivityPilotRealUserClosureConflict, match="kill switch"):
        enabled_service.close(
            user_context=_security_context(),
            command=_command(enabled_window),
        )

    separated_service, separated_window, _ = _service()
    with pytest.raises(ProductivityPilotRealUserClosureConflict, match="four-eyes"):
        separated_service.close(
            user_context=_security_context(PARTICIPANT_ID),
            command=_command(separated_window),
        )


def test_real_user_closure_rejects_raw_principal_owner_references() -> None:
    _, window, _ = _service()
    payload = _command(window).model_dump(mode="python")
    payload["operations_owner_ref"] = "principal:real-user-operations-owner"

    with pytest.raises(ValueError, match="raw principal identifiers"):
        ProductivityPilotRealUserClosureCommand.model_validate(payload)


def test_real_user_closure_api_and_audit_are_hash_only() -> None:
    service, window, _ = _service()
    test_app = build_app()
    test_app.state.productivity_pilot_real_user_closure_service = service
    client = TestClient(test_app)

    response = client.post(
        "/v1/platform/productivity-pilot/real-user-closure-reports",
        headers={
            "X-Tenant-Id": TENANT_ID,
            "X-User-Id": "real-user-independent-closer",
            "X-Role-Ids": "security-admin",
        },
        json=_command(window).model_dump(mode="json"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["schema_version"] == "productivity_pilot_real_user_closure_report.v1"
    assert "closed_by_principal_hash" in body
    assert PARTICIPANT_ID not in json.dumps(body, sort_keys=True)
    assert "real-user-independent-closer" not in json.dumps(body, sort_keys=True)
    event = next(
        item
        for item in reversed(test_app.state.audit_logger.events)
        if item.event_type == "platform.productivity_pilot.real_user_closure_recorded"
    )
    assert PARTICIPANT_ID not in json.dumps(event.metadata, sort_keys=True)
    assert "real-user-independent-closer" not in json.dumps(event.metadata, sort_keys=True)


def test_real_user_closure_migration_is_hash_only_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0069")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_real_user_closure_reports" in sql
    assert "closed_by_principal_hash" in sql
    assert "real_user_pilot_closure_append_only" in sql
    assert "force row level security" in sql
    assert "grant select, insert on table collabio.productivity_pilot_real_user_closure_reports" in sql
    assert "position('\"principal_id\"' in lower(closure_record::text)) = 0" in sql
    assert "position('\"closed_by\"' in lower(closure_record::text)) = 0" in sql

    owner_guard = " ".join(get_migration("0070").sql().lower().split())
    assert "real_user_pilot_closure_owner_refs_no_raw_principals" in owner_guard
    assert "operations_owner_ref" in owner_guard
    assert "recovery_owner_ref" in owner_guard
    assert all(
        len(name) <= 63
        for name in (
            "real_user_pilot_closure_tenant_select",
            "real_user_pilot_closure_tenant_insert",
            "real_user_pilot_closure_no_update",
            "real_user_pilot_closure_no_hard_delete",
            "real_user_pilot_closure_append_only",
        )
    )
