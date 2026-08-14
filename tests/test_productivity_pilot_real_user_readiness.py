from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import build_app
from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_real_user_admission import (
    ProductivityPilotParticipantEvidence,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_real_user_closure_report import (
    ProductivityPilotRealUserClosureReport,
    build_productivity_pilot_real_user_closure_report_hash,
)
from suite.platform.productivity_pilot_real_user_readiness import (
    ProductivityPilotRealUserReadinessConflict,
    ProductivityPilotRealUserReadinessService,
    ProductivityPilotRealUserReadinessStage,
    build_productivity_pilot_real_user_readiness_hash,
)
from suite.platform.productivity_pilot_real_user_runtime_window import (
    ProductivityPilotRealUserRuntimeObservation,
    ProductivityPilotRealUserRuntimeWindow,
    build_productivity_pilot_real_user_runtime_window_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_start_authorization_hash,
)

TENANT_ID = "tenant-demo"
PARTICIPANT_HASH = "sha256:" + "1" * 64
NOW = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


def _hash(index: int) -> str:
    return f"sha256:{index:064x}"


class _AdmissionStore:
    def __init__(
        self,
        nomination: ProductivityPilotRealUserNomination | None = None,
        admission: ProductivityPilotRealUserAdmission | None = None,
    ) -> None:
        self.nomination = nomination
        self.admission = admission

    def current_nomination(self, *, tenant_id: str) -> ProductivityPilotRealUserNomination | None:
        return self.nomination if self.nomination and self.nomination.tenant_id == tenant_id else None

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None:
        return self.admission if self.admission and self.admission.tenant_id == tenant_id else None


class _StartStore:
    def __init__(self, start: ProductivityPilotStartAuthorization | None = None) -> None:
        self.start = start

    def current(self, *, tenant_id: str) -> ProductivityPilotStartAuthorization | None:
        return self.start if self.start and self.start.tenant_id == tenant_id else None


class _RuntimeStore:
    def __init__(self, window: ProductivityPilotRealUserRuntimeWindow | None = None) -> None:
        self.window = window

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRealUserRuntimeWindow | None:
        return self.window if self.window and self.window.tenant_id == tenant_id else None

    def observations_for_window(
        self,
        *,
        tenant_id: str,
        window_id: str,
    ) -> tuple[ProductivityPilotRealUserRuntimeObservation, ...]:
        return ()


class _ClosureStore:
    def __init__(self, closure: ProductivityPilotRealUserClosureReport | None = None) -> None:
        self.closure = closure

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserClosureReport | None:
        return self.closure if self.closure and self.closure.tenant_id == tenant_id else None


def _nomination(*, nomination_id: str = "nomination-current") -> ProductivityPilotRealUserNomination:
    participant = ProductivityPilotParticipantEvidence.model_construct(principal_id_hash=PARTICIPANT_HASH)
    draft = ProductivityPilotRealUserNomination.model_construct(
        tenant_id=TENANT_ID,
        nomination_id=nomination_id,
        baseline_closure_evidence_hash=_hash(2),
        participant_manifest_hash=_hash(3),
        participant_count=1,
        participants=(participant,),
        scheduled_start_at_utc=NOW - timedelta(minutes=30),
        scheduled_end_at_utc=NOW + timedelta(hours=2),
        nominated_at_utc=NOW - timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_nomination_hash(draft)})


def _admission(nomination: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserAdmission:
    draft = ProductivityPilotRealUserAdmission.model_construct(
        tenant_id=TENANT_ID,
        admission_id="admission-current",
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        baseline_closure_evidence_hash=nomination.baseline_closure_evidence_hash,
        participant_manifest_hash=nomination.participant_manifest_hash,
        participant_count=nomination.participant_count,
        approved_principal_hashes=(PARTICIPANT_HASH,),
        preflight_gate_hash=_hash(4),
        scheduled_start_at_utc=nomination.scheduled_start_at_utc,
        scheduled_end_at_utc=nomination.scheduled_end_at_utc,
        approved_at_utc=NOW - timedelta(minutes=20),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_admission_hash(draft)})


def _start(admission: ProductivityPilotRealUserAdmission) -> ProductivityPilotStartAuthorization:
    draft = ProductivityPilotStartAuthorization.model_construct(
        tenant_id=TENANT_ID,
        authorization_id="start-current",
        preflight_gate_hash=admission.preflight_gate_hash,
        route_scope_hash=_hash(5),
        allowed_api_operations=("GET /v1/tasks/items",),
        authorized_at_utc=NOW - timedelta(minutes=10),
        effective_at_utc=NOW - timedelta(minutes=5),
        expires_at_utc=NOW + timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_start_authorization_hash(draft)})


def _window(
    nomination: ProductivityPilotRealUserNomination,
    admission: ProductivityPilotRealUserAdmission,
    start: ProductivityPilotStartAuthorization,
) -> ProductivityPilotRealUserRuntimeWindow:
    draft = ProductivityPilotRealUserRuntimeWindow.model_construct(
        tenant_id=TENANT_ID,
        window_id="window-current",
        admission_id=admission.admission_id,
        real_user_admission_evidence_hash=admission.evidence_hash,
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        route_scope_hash=start.route_scope_hash,
        allowed_api_operations=start.allowed_api_operations,
        designated_principal_manifest_hash=_hash(6),
        participant_role_snapshot_hash=_hash(7),
        activated_at_utc=NOW - timedelta(minutes=4),
        effective_at_utc=NOW - timedelta(minutes=4),
        expires_at_utc=NOW + timedelta(minutes=40),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_runtime_window_hash(draft)})


def _closure(
    nomination: ProductivityPilotRealUserNomination,
    admission: ProductivityPilotRealUserAdmission,
    start: ProductivityPilotStartAuthorization,
    window: ProductivityPilotRealUserRuntimeWindow,
) -> ProductivityPilotRealUserClosureReport:
    draft = ProductivityPilotRealUserClosureReport.model_construct(
        tenant_id=TENANT_ID,
        closure_id="closure-current",
        window_id=window.window_id,
        runtime_window_evidence_hash=window.evidence_hash,
        admission_id=admission.admission_id,
        real_user_admission_evidence_hash=admission.evidence_hash,
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        designated_principal_manifest_hash=window.designated_principal_manifest_hash,
        participant_role_snapshot_hash=window.participant_role_snapshot_hash,
        route_scope_hash=window.route_scope_hash,
        domain_receipts=(),
        closed_at_utc=NOW,
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_closure_report_hash(draft)})


def _service(
    *,
    nomination: ProductivityPilotRealUserNomination | None = None,
    admission: ProductivityPilotRealUserAdmission | None = None,
    start: ProductivityPilotStartAuthorization | None = None,
    window: ProductivityPilotRealUserRuntimeWindow | None = None,
    closure: ProductivityPilotRealUserClosureReport | None = None,
    runtime_enabled: bool = False,
) -> ProductivityPilotRealUserReadinessService:
    return ProductivityPilotRealUserReadinessService(
        admission_store=_AdmissionStore(nomination, admission),
        start_authorization_store=_StartStore(start),
        runtime_window_store=_RuntimeStore(window),
        closure_report_store=_ClosureStore(closure),
        runtime_enabled=runtime_enabled,
        clock=lambda: NOW,
    )


def _context(role: str = "tenant-admin") -> UserContext:
    return UserContext(tenant_id=TENANT_ID, user_id="pilot-admin", role_ids={role})


def test_readiness_starts_with_named_nomination_and_never_authorizes_runtime() -> None:
    response = _service().current(user_context=_context())

    assert response.stage == ProductivityPilotRealUserReadinessStage.NOMINATION_REQUIRED
    assert response.available_evidence == ()
    assert response.missing_evidence == (
        "real_user_nomination",
        "real_user_admission",
        "fresh_start_authorization",
        "real_user_runtime_window",
        "real_user_closure_report",
    )
    assert response.runtime_activation_authorized is False
    assert response.persistent_state_changed is False
    assert response.content_included is False
    assert response.evidence_hash == build_productivity_pilot_real_user_readiness_hash(response)


def test_readiness_tracks_a_complete_hash_bound_cycle_without_principal_ids() -> None:
    nomination = _nomination()
    admission = _admission(nomination)
    start = _start(admission)
    window = _window(nomination, admission, start)
    closure = _closure(nomination, admission, start, window)

    response = _service(
        nomination=nomination,
        admission=admission,
        start=start,
        window=window,
        closure=closure,
    ).current(user_context=_context("security-admin"))

    assert response.stage == ProductivityPilotRealUserReadinessStage.CLOSED
    assert response.current_cycle_complete is True
    assert response.missing_evidence == ()
    assert response.participant_count == 1
    assert response.allowed_api_operation_count == 1
    assert response.observation_count == 0
    assert response.domain_receipt_count == 0
    serialized = json.dumps(response.model_dump(mode="json"), sort_keys=True)
    assert "principal_id" not in serialized
    assert "pilot-admin" not in serialized


def test_readiness_does_not_promote_previous_cycle_admission() -> None:
    previous_nomination = _nomination(nomination_id="nomination-previous")
    previous_admission = _admission(previous_nomination)
    current_nomination = _nomination()

    response = _service(
        nomination=current_nomination,
        admission=previous_admission,
    ).current(user_context=_context())

    assert response.stage == ProductivityPilotRealUserReadinessStage.ADMISSION_REQUIRED
    assert response.available_evidence == ("real_user_nomination",)
    assert "current_admission_belongs_to_previous_nomination" in response.blocking_reasons


def test_readiness_fails_closed_for_tampered_authoritative_evidence() -> None:
    nomination = _nomination().model_copy(update={"evidence_hash": _hash(99)})

    with pytest.raises(ProductivityPilotRealUserReadinessConflict, match="nomination is invalid"):
        _service(nomination=nomination).current(user_context=_context())


def test_readiness_api_is_admin_only_audited_and_metadata_only() -> None:
    test_app = build_app()
    test_app.state.productivity_pilot_real_user_readiness_service = _service()
    client = TestClient(test_app)
    headers = {
        "X-Tenant-Id": TENANT_ID,
        "X-User-Id": "pilot-admin",
        "X-Role-Ids": "tenant-admin",
    }

    response = client.get(
        "/v1/platform/productivity-pilot/real-user-readiness",
        headers=headers,
    )
    denied = client.get(
        "/v1/platform/productivity-pilot/real-user-readiness",
        headers={**headers, "X-Role-Ids": "knowledge-worker"},
    )

    assert response.status_code == 200
    assert response.json()["stage"] == "nomination_required"
    assert denied.status_code == 403
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.real_user_readiness_read"
    assert event.metadata["stage"] == "nomination_required"
    assert event.metadata["runtime_activation_authorized"] is False
    assert "pilot-admin" not in json.dumps(event.metadata, sort_keys=True)
