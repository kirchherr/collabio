from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import build_app
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import get_migration
from suite.platform.productivity_pilot_closure_report import (
    PRODUCTIVITY_PILOT_CLOSURE_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotClosureReportStore,
    InMemoryProductivityPilotDomainReceiptStore,
    ProductivityPilotClosureCommand,
    ProductivityPilotClosureConflict,
    ProductivityPilotClosureService,
    ProductivityPilotDomainReceipt,
    ProductivityPilotRecoveryEvidence,
    build_productivity_pilot_closure_report_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    InMemoryProductivityPilotRuntimeWindowStore,
    ProductivityPilotRuntimeObservation,
    ProductivityPilotRuntimeWindow,
    build_productivity_pilot_designated_principal_manifest_hash,
    build_productivity_pilot_principal_observation_hash,
    build_productivity_pilot_runtime_observation_hash,
    build_productivity_pilot_runtime_window_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    InMemoryProductivityPilotStartAuthorizationStore,
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_start_authorization_hash,
)

NOW = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
TENANT_ID = "tenant-demo"
DESIGNATED_PRINCIPAL = "pilot-designated-user"
OPERATIONS = (
    "POST /v1/crm/account-onboardings",
    "POST /v1/tasks/items",
    "GET /v1/tasks/items",
    "GET /v1/tasks/activities",
    "POST /v1/time-tracking/entries",
    "GET /v1/time-tracking/entries",
    "GET /v1/time-tracking/approvals",
)


def _hash(value: int) -> str:
    return f"sha256:{value:064x}"


def _start() -> ProductivityPilotStartAuthorization:
    draft = ProductivityPilotStartAuthorization(
        tenant_id=TENANT_ID,
        authorization_id="pilot-start-closure",
        enforcement_id="pilot-scope-closure",
        traffic_scope_evidence_hash=_hash(1),
        route_scope_hash=_hash(2),
        admission_evidence_hash=_hash(3),
        preflight_gate_hash=_hash(4),
        policy_hash=_hash(5),
        allowed_api_operations=OPERATIONS,
        monitoring_evidence=(),
        rollback_evidence=(),
        monitoring_evidence_manifest_hash=_hash(6),
        rollback_evidence_manifest_hash=_hash(7),
        command_hash=_hash(8),
        idempotency_key_hash=_hash(9),
        human_confirmation_statement_hash=_hash(10),
        change_request_ref="change:pilot-start-closure",
        human_confirmation_reference="approval:pilot-start-closure",
        security_approval_ref="security:pilot-start-closure",
        audit_chain_ref="audit:pilot-start-closure",
        authorized_by="pilot-start-security-admin",
        authorized_at_utc=NOW - timedelta(minutes=5),
        effective_at_utc=NOW,
        expires_at_utc=NOW + timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_start_authorization_hash(draft)})


def _window(start: ProductivityPilotStartAuthorization) -> ProductivityPilotRuntimeWindow:
    draft = ProductivityPilotRuntimeWindow(
        tenant_id=TENANT_ID,
        window_id="pilot-runtime-window-closure",
        authorization_id=start.authorization_id,
        start_authorization_evidence_hash=start.evidence_hash,
        designated_principal_ids=(DESIGNATED_PRINCIPAL,),
        designated_principal_manifest_hash=build_productivity_pilot_designated_principal_manifest_hash(
            tenant_id=TENANT_ID,
            designated_principal_ids=(DESIGNATED_PRINCIPAL,),
        ),
        allowed_api_operations=OPERATIONS,
        route_scope_hash=start.route_scope_hash,
        command_hash=_hash(11),
        idempotency_key_hash=_hash(12),
        human_confirmation_statement_hash=_hash(13),
        change_request_ref="change:pilot-runtime-closure",
        human_confirmation_reference="approval:pilot-runtime-closure",
        operations_owner_ref="principal:pilot-operations-owner",
        audit_chain_ref="audit:pilot-runtime-closure",
        activated_by="pilot-runtime-admin",
        activated_at_utc=NOW,
        effective_at_utc=NOW,
        expires_at_utc=NOW + timedelta(hours=1),
        evidence_hash=_hash(0),
    )
    return draft.model_copy(update={"evidence_hash": build_productivity_pilot_runtime_window_hash(draft)})


def _observations(window: ProductivityPilotRuntimeWindow) -> tuple[ProductivityPilotRuntimeObservation, ...]:
    principal_hash = build_productivity_pilot_principal_observation_hash(
        tenant_id=TENANT_ID,
        principal_id=DESIGNATED_PRINCIPAL,
    )
    records: list[ProductivityPilotRuntimeObservation] = []
    for index, operation in enumerate(OPERATIONS, start=1):
        draft = ProductivityPilotRuntimeObservation(
            tenant_id=TENANT_ID,
            observation_id=f"pilot-observation-closure-{index}",
            window_id=window.window_id,
            authorization_id=window.authorization_id,
            start_authorization_evidence_hash=window.start_authorization_evidence_hash,
            window_evidence_hash=window.evidence_hash,
            principal_id_hash=principal_hash,
            operation=operation,
            observed_at_utc=NOW + timedelta(minutes=index),
            evidence_hash=_hash(0),
        )
        records.append(
            draft.model_copy(update={"evidence_hash": build_productivity_pilot_runtime_observation_hash(draft)})
        )
    return tuple(records)


def _command(window: ProductivityPilotRuntimeWindow) -> ProductivityPilotClosureCommand:
    return ProductivityPilotClosureCommand(
        closure_id="pilot-closure-one",
        window_id=window.window_id,
        runtime_window_evidence_hash=window.evidence_hash,
        recovery_evidence=ProductivityPilotRecoveryEvidence(
            backup_sha256=_hash(21),
            postgres_restore_drill_report_hash=_hash(22),
            backend_foundation_gate_hash=_hash(23),
            business_backend_release_gate_hash=_hash(24),
            observed_at_utc=NOW + timedelta(minutes=11),
            restored_runtime_window_count=1,
            restored_observation_count=7,
            restored_domain_receipt_count=3,
        ),
        idempotency_key_ref="request:pilot-closure-one",
        change_request_ref="change:pilot-closure-one",
        human_confirmation_reference="approval:pilot-closure-one",
        operations_owner_ref="principal:pilot-operations-owner",
        recovery_owner_ref="principal:pilot-recovery-owner",
        audit_chain_ref="audit:pilot-closure-one",
        human_confirmation_statement=PRODUCTIVITY_PILOT_CLOSURE_CONFIRMATION_STATEMENT,
        closed_at_utc=NOW + timedelta(minutes=10),
    )


def _service(
    *,
    observations: tuple[ProductivityPilotRuntimeObservation, ...] | None = None,
    receipt_actor: str = DESIGNATED_PRINCIPAL,
    runtime_enabled: bool = False,
) -> tuple[ProductivityPilotClosureService, ProductivityPilotRuntimeWindow]:
    start = _start()
    window = _window(start)
    runtime_store = InMemoryProductivityPilotRuntimeWindowStore(
        (window,),
        _observations(window) if observations is None else observations,
    )
    receipts = tuple(
        ProductivityPilotDomainReceipt(
            operation=operation,
            receipt_hash=_hash(30 + index),
            created_by=receipt_actor,
            committed_at_utc=NOW + timedelta(minutes=index),
        )
        for index, operation in enumerate((item for item in OPERATIONS if item.startswith("POST ")), start=1)
    )
    service = ProductivityPilotClosureService(
        start_authorization_store=InMemoryProductivityPilotStartAuthorizationStore((start,)),
        runtime_window_store=runtime_store,
        domain_receipt_store=InMemoryProductivityPilotDomainReceiptStore(receipts),
        closure_report_store=InMemoryProductivityPilotClosureReportStore(),
        runtime_enabled=runtime_enabled,
    )
    return service, window


def _closure_actor() -> UserContext:
    return UserContext(
        tenant_id=TENANT_ID,
        user_id="pilot-closure-security-admin",
        role_ids={"security-admin"},
    )


def test_closure_report_binds_authoritative_observations_receipts_and_recovery() -> None:
    service, window = _service()
    command = _command(window)

    report = service.close(user_context=_closure_actor(), command=command)
    replay = service.close(user_context=_closure_actor(), command=command)

    assert report.evidence_hash == build_productivity_pilot_closure_report_hash(report)
    assert report.observation_count == 7
    assert report.distinct_principal_hash_count == 1
    assert len(report.operation_summaries) == 7
    assert len(report.domain_receipts) == 3
    assert report.runtime_switch_closed is True
    assert report.records_preserved is True
    assert report.content_included is False
    assert replay.idempotent_replay is True
    assert replay.evidence_hash == report.evidence_hash
    assert "human_confirmation_statement" not in report.model_dump()
    assert DESIGNATED_PRINCIPAL not in report.model_dump_json()


def test_closure_report_fails_closed_for_open_switch_incomplete_ledger_and_wrong_actor() -> None:
    open_service, window = _service(runtime_enabled=True)
    with pytest.raises(ProductivityPilotClosureConflict, match="kill switch"):
        open_service.close(user_context=_closure_actor(), command=_command(window))

    start = _start()
    incomplete_window = _window(start)
    incomplete_service, _ = _service(observations=_observations(incomplete_window)[:-1])
    with pytest.raises(ProductivityPilotClosureConflict, match="exactly one observation"):
        incomplete_service.close(user_context=_closure_actor(), command=_command(incomplete_window))

    actor_service, actor_window = _service(receipt_actor="unobserved-principal")
    with pytest.raises(ProductivityPilotClosureConflict, match="receipt actor"):
        actor_service.close(user_context=_closure_actor(), command=_command(actor_window))


def test_closure_report_requires_four_eyes_and_exact_restore_counts() -> None:
    service, window = _service()
    command = _command(window)
    with pytest.raises(ProductivityPilotClosureConflict, match="four-eyes"):
        service.close(
            user_context=UserContext(
                tenant_id=TENANT_ID,
                user_id="pilot-runtime-admin",
                role_ids={"security-admin"},
            ),
            command=command,
        )

    mismatched = command.model_copy(
        update={
            "recovery_evidence": command.recovery_evidence.model_copy(
                update={"restored_observation_count": 8}
            )
        }
    )
    with pytest.raises(ProductivityPilotClosureConflict, match="recovery evidence counts"):
        service.close(user_context=_closure_actor(), command=mismatched)


def test_closure_report_api_is_security_admin_only_and_audits_metadata() -> None:
    service, window = _service()
    test_app = build_app()
    test_app.state.productivity_pilot_closure_service = service
    client = TestClient(test_app)
    command = _command(window)

    denied = client.post(
        "/v1/platform/productivity-pilot/closure-reports",
        headers={
            "X-Tenant-Id": TENANT_ID,
            "X-User-Id": "pilot-reader",
            "X-Role-Ids": "knowledge-worker",
        },
        json=command.model_dump(mode="json"),
    )
    response = client.post(
        "/v1/platform/productivity-pilot/closure-reports",
        headers={
            "X-Tenant-Id": TENANT_ID,
            "X-User-Id": "pilot-closure-security-admin",
            "X-Role-Ids": "security-admin",
        },
        json=command.model_dump(mode="json"),
    )
    current = client.get(
        "/v1/platform/productivity-pilot/closure-reports/current",
        headers={
            "X-Tenant-Id": TENANT_ID,
            "X-User-Id": "pilot-closure-security-admin",
            "X-Role-Ids": "security-admin",
        },
    )

    assert denied.status_code == 403
    assert response.status_code == 201
    assert current.status_code == 200
    assert current.json()["evidence_hash"] == response.json()["evidence_hash"]
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.closed"
    assert "human_confirmation_statement" not in event.metadata
    assert event.metadata["observation_count"] == 7
    assert event.metadata["domain_receipt_count"] == 3


def test_closure_report_migration_is_append_only_tenant_scoped_and_metadata_only() -> None:
    sql = " ".join(get_migration("0065").sql().lower().split())

    assert "create table if not exists collabio.productivity_pilot_closure_reports" in sql
    assert "alter table collabio.productivity_pilot_closure_reports force row level security" in sql
    assert "productivity_pilot_closure_reports_no_update" in sql
    assert "productivity_pilot_closure_reports_no_hard_delete" in sql
    assert "productivity_pilot_closure_reports_append_only" in sql
    assert "grant select, insert on table collabio.productivity_pilot_closure_reports" in sql
    assert "not (closure_record ? 'human_confirmation_statement')" in sql
    assert "position('\"principal_id\"' in lower(closure_record::text)) = 0" in sql
