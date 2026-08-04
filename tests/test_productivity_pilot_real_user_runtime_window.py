from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from main import build_app, require_productivity_pilot_traffic_scope
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import get_migration
from suite.platform.productivity_pilot_real_user_admission import (
    InMemoryProductivityPilotParticipantDirectory,
    InMemoryProductivityPilotRealUserAdmissionStore,
    ProductivityPilotParticipantEvidence,
    ProductivityPilotPrincipalSnapshot,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_real_user_runtime_window import (
    PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotRealUserRuntimeWindowStore,
    ProductivityPilotRealUserRuntimeWindowCommand,
    ProductivityPilotRealUserRuntimeWindowConflict,
    ProductivityPilotRealUserRuntimeWindowService,
    build_productivity_pilot_real_user_runtime_observation_hash,
    build_productivity_pilot_real_user_runtime_window_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    PRODUCTIVITY_PILOT_RUNTIME_WINDOW_CONFIRMATION_STATEMENT,
    ProductivityPilotRuntimeWindowCommand,
    build_productivity_pilot_principal_observation_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    InMemoryProductivityPilotStartAuthorizationStore,
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_start_authorization_hash,
)
from suite.platform.productivity_pilot_traffic_scope import ProductivityPilotTrafficDecision

NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
TENANT_ID = "tenant-demo"
PARTICIPANT_ID = "real-pilot-user"
OPERATION = "GET /v1/tasks/items"


def _hash(value: int) -> str:
    return f"sha256:{value:064x}"


def _participant_hash() -> str:
    return build_productivity_pilot_principal_observation_hash(
        tenant_id=TENANT_ID,
        principal_id=PARTICIPANT_ID,
    )


def _nomination() -> ProductivityPilotRealUserNomination:
    participant = ProductivityPilotParticipantEvidence(
        principal_id_hash=_participant_hash(),
        authoritative_role_ids=("knowledge-worker",),
        role_manifest_hash=_hash(1),
        participation_notice_evidence_hash=_hash(2),
        training_evidence_hash=_hash(3),
    )
    draft = ProductivityPilotRealUserNomination(
        tenant_id=TENANT_ID,
        nomination_id="real-pilot-nomination-runtime",
        baseline_closure_id="pilot-closure-development",
        baseline_closure_evidence_hash=_hash(4),
        purpose_code="validate_productivity_workflows",
        purpose_ref="purpose:real-pilot-runtime",
        lawful_basis_ref="lawful-basis:tenant-assessment",
        privacy_risk_assessment_ref="privacy-risk:real-pilot-runtime",
        retention_policy_id="rp-audit-3650d",
        data_classification="internal",
        participants=(participant,),
        participant_manifest_hash=_hash(5),
        participant_count=1,
        scheduled_start_at_utc=NOW - timedelta(minutes=5),
        scheduled_end_at_utc=NOW + timedelta(hours=2),
        dpia_required=False,
        dpia_ref=None,
        works_council_review_required=False,
        works_council_approval_ref=None,
        command_hash=_hash(6),
        idempotency_key_hash=_hash(7),
        human_confirmation_statement_hash=_hash(8),
        change_request_ref="change:real-pilot-runtime",
        human_confirmation_reference="approval:real-pilot-runtime-nomination",
        audit_chain_ref="audit:real-pilot-runtime-nomination",
        nominated_by_principal_hash=build_productivity_pilot_principal_observation_hash(
            tenant_id=TENANT_ID,
            principal_id="real-pilot-nominator",
        ),
        nominated_at_utc=NOW - timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_nomination_hash(draft)})


def _admission(nomination: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserAdmission:
    draft = ProductivityPilotRealUserAdmission(
        tenant_id=TENANT_ID,
        admission_id="real-pilot-admission-runtime",
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        baseline_closure_evidence_hash=nomination.baseline_closure_evidence_hash,
        participant_manifest_hash=nomination.participant_manifest_hash,
        participant_count=1,
        approved_principal_hashes=(_participant_hash(),),
        preflight_gate_hash=_hash(11),
        policy_hash=_hash(12),
        business_backend_release_gate_hash=_hash(13),
        tenant_module_state_manifest_hash=_hash(14),
        backup_sha256=_hash(15),
        postgres_restore_drill_report_hash=_hash(16),
        backend_foundation_gate_hash=_hash(17),
        control_evidence_observed_at_utc=NOW - timedelta(minutes=30),
        scheduled_start_at_utc=nomination.scheduled_start_at_utc,
        scheduled_end_at_utc=nomination.scheduled_end_at_utc,
        security_review_ref="security-review:real-pilot-runtime",
        privacy_approval_ref="privacy-approval:real-pilot-runtime",
        command_hash=_hash(18),
        idempotency_key_hash=_hash(19),
        human_confirmation_statement_hash=_hash(20),
        change_request_ref="change:real-pilot-runtime",
        human_confirmation_reference="approval:real-pilot-runtime-security",
        audit_chain_ref="audit:real-pilot-runtime-admission",
        approved_by_principal_hash=build_productivity_pilot_principal_observation_hash(
            tenant_id=TENANT_ID,
            principal_id="real-pilot-security-approver",
        ),
        approved_at_utc=NOW - timedelta(minutes=25),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_admission_hash(draft)})


def _start(admission: ProductivityPilotRealUserAdmission) -> ProductivityPilotStartAuthorization:
    draft = ProductivityPilotStartAuthorization(
        tenant_id=TENANT_ID,
        authorization_id="real-pilot-start-runtime",
        enforcement_id="real-pilot-traffic-runtime",
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
        change_request_ref="change:real-pilot-runtime",
        human_confirmation_reference="approval:real-pilot-start",
        security_approval_ref="security:real-pilot-start",
        audit_chain_ref="audit:real-pilot-start",
        authorized_by="real-pilot-start-authorizer",
        authorized_at_utc=NOW - timedelta(minutes=15),
        effective_at_utc=NOW - timedelta(minutes=5),
        expires_at_utc=NOW + timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_start_authorization_hash(draft)})


def _directory(*, roles: tuple[str, ...] = ("knowledge-worker",)) -> InMemoryProductivityPilotParticipantDirectory:
    return InMemoryProductivityPilotParticipantDirectory(
        {
            (TENANT_ID, PARTICIPANT_ID): ProductivityPilotPrincipalSnapshot(
                principal_id=PARTICIPANT_ID,
                role_ids=roles,
            )
        }
    )


def _chain() -> tuple[
    ProductivityPilotRealUserNomination,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotStartAuthorization,
]:
    nomination = _nomination()
    admission = _admission(nomination)
    return nomination, admission, _start(admission)


def _command(
    *,
    admission: ProductivityPilotRealUserAdmission,
    nomination: ProductivityPilotRealUserNomination,
    start: ProductivityPilotStartAuthorization,
) -> ProductivityPilotRealUserRuntimeWindowCommand:
    return ProductivityPilotRealUserRuntimeWindowCommand(
        window_id="real-pilot-runtime-window-one",
        admission_id=admission.admission_id,
        real_user_admission_evidence_hash=admission.evidence_hash,
        nomination_id=nomination.nomination_id,
        nomination_evidence_hash=nomination.evidence_hash,
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        designated_principal_ids=(PARTICIPANT_ID,),
        idempotency_key_ref="request:real-pilot-runtime-one",
        change_request_ref="change:real-pilot-runtime",
        human_confirmation_reference="approval:real-pilot-runtime",
        operations_owner_ref="control-owner:real-pilot-operations",
        audit_chain_ref="audit:real-pilot-runtime",
        human_confirmation_statement=PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_CONFIRMATION_STATEMENT,
        activated_at_utc=NOW,
        effective_at_utc=NOW,
        expires_at_utc=NOW + timedelta(minutes=45),
    )


def _service(
    *,
    runtime_enabled: bool = True,
    directory: InMemoryProductivityPilotParticipantDirectory | None = None,
    runtime_store: InMemoryProductivityPilotRealUserRuntimeWindowStore | None = None,
) -> tuple[
    ProductivityPilotRealUserRuntimeWindowService,
    ProductivityPilotRealUserNomination,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotStartAuthorization,
    InMemoryProductivityPilotRealUserRuntimeWindowStore,
]:
    nomination, admission, start = _chain()
    admission_store = InMemoryProductivityPilotRealUserAdmissionStore(
        nominations=(nomination,),
        admissions=(admission,),
    )
    start_store = InMemoryProductivityPilotStartAuthorizationStore((start,))
    store = runtime_store or InMemoryProductivityPilotRealUserRuntimeWindowStore()
    service = ProductivityPilotRealUserRuntimeWindowService(
        start_authorization_store=start_store,
        real_user_admission_store=admission_store,
        participant_directory=directory or _directory(),
        runtime_window_store=store,
        runtime_enabled=runtime_enabled,
        clock=lambda: NOW,
    )
    return service, nomination, admission, start, store


def _activate(
    service: ProductivityPilotRealUserRuntimeWindowService,
    nomination: ProductivityPilotRealUserNomination,
    admission: ProductivityPilotRealUserAdmission,
    start: ProductivityPilotStartAuthorization,
) -> None:
    service.activate(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="real-pilot-runtime-operator",
            role_ids={"tenant-admin"},
        ),
        command=_command(admission=admission, nomination=nomination, start=start),
    )


def test_real_user_runtime_rejects_raw_principal_owner_reference() -> None:
    _, nomination, admission, start, _ = _service()
    payload = _command(admission=admission, nomination=nomination, start=start).model_dump(mode="python")
    payload["operations_owner_ref"] = "principal:real-pilot-operations-owner"

    with pytest.raises(ValueError, match="raw principal identifier"):
        ProductivityPilotRealUserRuntimeWindowCommand.model_validate(payload)


def test_real_user_runtime_persists_only_hashes_and_observes_current_authorized_principal() -> None:
    service, nomination, admission, start, store = _service()

    window = service.activate(
        user_context=UserContext(
            tenant_id=TENANT_ID,
            user_id="real-pilot-runtime-operator",
            role_ids={"tenant-admin"},
        ),
        command=_command(admission=admission, nomination=nomination, start=start),
    )
    decision = service.authorize_operation(
        tenant_id=TENANT_ID,
        principal_id=PARTICIPANT_ID,
        operation=OPERATION,
        start_authorization_evidence_hash=start.evidence_hash,
    )

    assert window.evidence_hash == build_productivity_pilot_real_user_runtime_window_hash(window)
    assert window.designated_principal_hashes == (_participant_hash(),)
    assert decision.authorization_allowed is True
    assert decision.current_roles_verified is True
    assert len(store.observations) == 1
    assert store.observations[0].evidence_hash == build_productivity_pilot_real_user_runtime_observation_hash(
        store.observations[0]
    )
    serialized = json.dumps(window.model_dump(mode="json"), sort_keys=True)
    assert PARTICIPANT_ID not in serialized
    assert "real-pilot-runtime-operator" not in serialized
    assert "designated_principal_ids" not in serialized


def test_real_user_runtime_fails_closed_for_role_drift_outsiders_and_kill_switch() -> None:
    service, nomination, admission, start, store = _service()
    _activate(service, nomination, admission, start)

    drifted_service, _, _, _, _ = _service(
        directory=_directory(roles=("knowledge-worker", "tenant-admin")),
        runtime_store=store,
    )
    role_drift = drifted_service.authorize_operation(
        tenant_id=TENANT_ID,
        principal_id=PARTICIPANT_ID,
        operation=OPERATION,
        start_authorization_evidence_hash=start.evidence_hash,
    )
    outsider = service.authorize_operation(
        tenant_id=TENANT_ID,
        principal_id="not-admitted",
        operation=OPERATION,
        start_authorization_evidence_hash=start.evidence_hash,
    )
    disabled_service, _, _, _, _ = _service(runtime_enabled=False, runtime_store=store)
    disabled = disabled_service.authorize_operation(
        tenant_id=TENANT_ID,
        principal_id=PARTICIPANT_ID,
        operation=OPERATION,
        start_authorization_evidence_hash=start.evidence_hash,
    )

    assert role_drift.authorization_allowed is False
    assert role_drift.blocking_reason == "principal_role_drift_for_real_user_productivity_pilot"
    assert outsider.authorization_allowed is False
    assert outsider.blocking_reason == "principal_not_active_for_real_user_productivity_pilot"
    assert disabled.authorization_allowed is False
    assert disabled.blocking_reason == "productivity_pilot_runtime_disabled"
    assert store.observations == []


def test_real_user_runtime_requires_fresh_admission_bound_start_and_separated_operator() -> None:
    service, nomination, admission, start, _ = _service()
    command = _command(admission=admission, nomination=nomination, start=start)

    with pytest.raises(ProductivityPilotRealUserRuntimeWindowConflict, match="four-eyes"):
        service.activate(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id=start.authorized_by,
                role_ids={"tenant-admin"},
            ),
            command=command,
        )
    with pytest.raises(ProductivityPilotRealUserRuntimeWindowConflict, match="admission_evidence_hash"):
        service.activate(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id="real-pilot-runtime-operator",
                role_ids={"tenant-admin"},
            ),
            command=command.model_copy(update={"real_user_admission_evidence_hash": _hash(63)}),
        )


class _ManagedStartService:
    def __init__(self, start: ProductivityPilotStartAuthorization) -> None:
        self.start = start

    def authorize_operation(self, *, tenant_id: str, operation: str) -> ProductivityPilotTrafficDecision:
        return ProductivityPilotTrafficDecision(
            tenant_id=tenant_id,
            operation=operation,
            pilot_traffic_managed=True,
            operation_in_scope=True,
            tenant_scope_enforced=True,
            route_scope_enforced=True,
            default_deny_enabled=True,
            pilot_start_authorized=True,
            runtime_enablement_verified=True,
            authorization_allowed=True,
            enforcement_evidence_hash=_hash(61),
            start_authorization_evidence_hash=self.start.evidence_hash,
            authorization_expires_at_utc=self.start.expires_at_utc,
            http_status_code=200,
        )


class _CurrentAdmissionService:
    def __init__(self, admission: ProductivityPilotRealUserAdmission) -> None:
        self.admission = admission

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None:
        return self.admission if tenant_id == self.admission.tenant_id else None


class _LegacyRuntimeMustNotRun:
    def authorize_operation(self, **_: object) -> None:
        raise AssertionError("legacy runtime path must not run after real-user admission")


def test_request_gate_switches_to_hash_only_runtime_after_real_user_admission() -> None:
    service, nomination, admission, start, store = _service()
    _activate(service, nomination, admission, start)
    test_app = build_app()
    test_app.state.productivity_pilot_start_authorization_service = _ManagedStartService(start)
    test_app.state.productivity_pilot_real_user_admission_service = _CurrentAdmissionService(admission)
    test_app.state.productivity_pilot_real_user_runtime_window_service = service
    test_app.state.productivity_pilot_runtime_window_service = _LegacyRuntimeMustNotRun()
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/tasks/items",
        "raw_path": b"/v1/tasks/items",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "app": test_app,
        "route": SimpleNamespace(path="/v1/tasks/items"),
    }
    request = Request(scope)
    context = cast(
        Any,
        SimpleNamespace(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id=PARTICIPANT_ID,
                role_ids={"knowledge-worker"},
            )
        ),
    )

    decision = require_productivity_pilot_traffic_scope(request, context)

    assert decision.authorization_allowed is True
    assert len(store.observations) == 1
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.real_user_runtime_access_observed"
    assert PARTICIPANT_ID not in json.dumps(event.metadata, sort_keys=True)


def test_real_user_runtime_api_is_hash_only_and_legacy_runtime_is_blocked() -> None:
    service, nomination, admission, start, _ = _service()
    test_app = build_app()
    test_app.state.productivity_pilot_real_user_runtime_window_service = service
    test_app.state.productivity_pilot_real_user_admission_service = _CurrentAdmissionService(admission)
    client = TestClient(test_app)
    headers = {
        "X-Tenant-Id": TENANT_ID,
        "X-User-Id": "real-pilot-runtime-operator",
        "X-Role-Ids": "tenant-admin",
    }

    response = client.post(
        "/v1/platform/productivity-pilot/real-user-runtime-windows",
        headers=headers,
        json=_command(admission=admission, nomination=nomination, start=start).model_dump(mode="json"),
    )
    legacy_command = ProductivityPilotRuntimeWindowCommand(
        window_id="legacy-runtime-after-real-user-admission",
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        designated_principal_ids=(PARTICIPANT_ID,),
        idempotency_key_ref="request:legacy-runtime-after-real-user-admission",
        change_request_ref="change:real-pilot-runtime",
        human_confirmation_reference="approval:legacy-runtime",
        operations_owner_ref="principal:real-pilot-operations-owner",
        audit_chain_ref="audit:legacy-runtime",
        human_confirmation_statement=PRODUCTIVITY_PILOT_RUNTIME_WINDOW_CONFIRMATION_STATEMENT,
        activated_at_utc=NOW,
        effective_at_utc=NOW,
        expires_at_utc=NOW + timedelta(minutes=30),
    )
    legacy = client.post(
        "/v1/platform/productivity-pilot/runtime-windows",
        headers=headers,
        json=legacy_command.model_dump(mode="json"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["designated_principal_hashes"] == [_participant_hash()]
    assert "designated_principal_ids" not in body
    assert PARTICIPANT_ID not in json.dumps(body, sort_keys=True)
    assert legacy.status_code == 409
    assert "forbidden" in legacy.json()["detail"]
    event = next(
        item
        for item in reversed(test_app.state.audit_logger.events)
        if item.event_type == "platform.productivity_pilot.real_user_runtime_window_activated"
    )
    assert PARTICIPANT_ID not in json.dumps(event.metadata, sort_keys=True)


def test_real_user_runtime_migration_is_hash_only_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0067")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_real_user_runtime_windows" in sql
    assert "create table if not exists collabio.productivity_pilot_real_user_runtime_observations" in sql
    assert "designated_principal_hashes" in sql
    assert "productivity_pilot_real_user_runtime_windows_append_only" in sql
    assert "productivity_pilot_real_user_runtime_observations_append_only" in sql
    assert "force row level security" in sql
    assert "grant select, insert on table collabio.productivity_pilot_real_user_runtime_windows" in sql
    assert "position('\"designated_principal_ids\"' in lower(window_record::text)) = 0" in sql

    owner_guard_sql = " ".join(get_migration("0071").sql().lower().split())
    assert "real_user_pilot_runtime_owner_ref_no_raw_principal" in owner_guard_sql
    assert "operations_owner_ref" in owner_guard_sql

    policy_name_migration = get_migration("0068")
    policy_sql = " ".join(policy_name_migration.sql().lower().split())
    assert "alter policy productivity_pilot_real_user_runtime_observations_no_hard_delet" in policy_sql
    assert "rename to productivity_pilot_real_user_runtime_obs_no_hard_delete" in policy_sql
