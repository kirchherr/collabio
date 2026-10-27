from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import build_app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import get_migration
from suite.persistence.migrator import apply_migrations
from suite.platform.mvp_pilot_decisions import (
    MVP_PILOT_DECISION_CONFIRMATION_STATEMENT,
    MVP_PILOT_DECISION_SUBMIT_CONTRACT_ID,
    InMemoryMvpPilotDecisionStore,
    MvpPilotDecisionCommand,
    MvpPilotDecisionConflict,
    MvpPilotDecisionContext,
    MvpPilotDecisionService,
    MvpPilotDecisionValue,
    PgMvpPilotDecisionStore,
    build_mvp_pilot_decision_context_hash,
    build_mvp_pilot_decision_record_hash,
)

ADMIN_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "pilot-reviewer",
    "X-Role-Ids": "tenant-admin",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}


def _context(
    *,
    tenant_id: str = "tenant-demo",
    checked_by: str = "pilot-reviewer",
    go: bool = True,
) -> MvpPilotDecisionContext:
    draft = MvpPilotDecisionContext(
        tenant_id=tenant_id,
        checked_by=checked_by,
        mvp_readiness_decision="metadata_only_mvp_ready_with_deferred_content_release" if go else "blocked",
        metadata_only_productive_path=go,
        role_gate_status="role_gated_actions_visible",
        audit_gate_status="audit_visible" if go else "audit_blocked",
        backup_failover_gate_status="metadata_only_no_state_change",
        module_gate_status="module_activation_required",
        content_gate_status="deferred_metadata_only_ready",
        foundation_gap_status="foundation_gaps_visible",
        active_foundation_gap_ids=("human_confirmation_required",),
        ready_foundation_gap_ids=(),
        deferred_foundation_gap_ids=("human_confirmation_required",),
        next_foundation_action="human_confirmation_required",
        required_roles=("tenant-admin", "security-admin"),
        module_count=2,
        source_object_flow_count=2,
        work_item_count=1,
        module_manifest_hash="sha256:" + "1" * 64,
        source_object_flow_manifest_hash="sha256:" + "2" * 64,
        work_item_manifest_hash="sha256:" + "3" * 64,
        foundation_gap_manifest_hash="sha256:" + "4" * 64,
        go_decision_allowed=go,
        context_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"context_hash": build_mvp_pilot_decision_context_hash(draft)})


def _command(
    context: MvpPilotDecisionContext,
    *,
    suffix: str = "one",
    decision: MvpPilotDecisionValue = MvpPilotDecisionValue.GO,
) -> MvpPilotDecisionCommand:
    return MvpPilotDecisionCommand(
        tenant_id=context.tenant_id,
        decision_id=f"mvp-pilot-decision-{suffix}",
        decision_capture_submit_contract_id=MVP_PILOT_DECISION_SUBMIT_CONTRACT_ID,
        decision_context_hash=context.context_hash,
        go_no_go_decision=decision,
        decision_reason="The reviewed metadata-only scope is acceptable for the next controlled boundary.",
        human_confirmation_statement=MVP_PILOT_DECISION_CONFIRMATION_STATEMENT,
        human_confirmation_reference=f"approval:mvp-pilot-decision-{suffix}",
        change_request_ref=f"change:mvp-pilot-decision-{suffix}",
        confirmed_by=context.checked_by,
        confirmed_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        confirmation_role_ids=("tenant-admin",),
        idempotency_key=f"request:mvp-pilot-decision-{suffix}",
    )


def _admin(*, tenant_id: str = "tenant-demo", user_id: str = "pilot-reviewer") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user_id, role_ids={"tenant-admin"})


def test_decision_capture_is_append_only_idempotent_and_non_executing() -> None:
    audit_logger = InMemoryAuditLogger()
    service = MvpPilotDecisionService(store=InMemoryMvpPilotDecisionStore(), audit_logger=audit_logger)
    context = _context()
    command = _command(context)

    record = service.capture(user_context=_admin(), command=command, decision_context=context)
    replay = service.capture(user_context=_admin(), command=command, decision_context=context)

    assert record.go_no_go_decision is MvpPilotDecisionValue.GO
    assert record.evidence_hash == build_mvp_pilot_decision_record_hash(record)
    assert replay.idempotent_replay is True
    assert replay.evidence_hash == record.evidence_hash
    assert record.pilot_admission_allowed is False
    assert record.pilot_start_allowed is False
    assert record.module_activation_executed is False
    assert record.traffic_authorized is False
    assert record.external_side_effect_executed is False
    assert record.content_included is False
    serialized = record.model_dump()
    assert "decision_reason" not in serialized
    assert "human_confirmation_statement" not in serialized
    assert audit_logger.events[0].metadata["decision_reason_hash"] == record.decision_reason_hash
    assert "decision_reason" not in audit_logger.events[0].metadata


def test_decision_capture_fails_closed_for_stale_context_roles_and_blocked_go() -> None:
    service = MvpPilotDecisionService(
        store=InMemoryMvpPilotDecisionStore(),
        audit_logger=InMemoryAuditLogger(),
    )
    ready_context = _context()
    command = _command(ready_context)

    with pytest.raises(PermissionError, match="tenant admin"):
        service.capture(
            user_context=UserContext(
                tenant_id="tenant-demo",
                user_id="pilot-reviewer",
                role_ids={"knowledge-worker"},
            ),
            command=command,
            decision_context=ready_context,
        )
    with pytest.raises(MvpPilotDecisionConflict, match="context changed"):
        service.capture(
            user_context=_admin(),
            command=command.model_copy(update={"decision_context_hash": "sha256:" + "9" * 64}),
            decision_context=ready_context,
        )

    blocked_context = _context(go=False)
    with pytest.raises(MvpPilotDecisionConflict, match="GO is blocked"):
        service.capture(
            user_context=_admin(),
            command=_command(blocked_context, suffix="blocked"),
            decision_context=blocked_context,
        )
    no_go = service.capture(
        user_context=_admin(),
        command=_command(blocked_context, suffix="no-go", decision=MvpPilotDecisionValue.NO_GO),
        decision_context=blocked_context,
    )
    assert no_go.go_no_go_decision is MvpPilotDecisionValue.NO_GO


def test_decision_command_requires_exact_confirmation_and_non_executing_flags() -> None:
    command = _command(_context())
    payload = command.model_dump()

    with pytest.raises(ValidationError, match="exact MVP pilot decision confirmation"):
        MvpPilotDecisionCommand.model_validate({**payload, "human_confirmation_statement": "approve"})
    with pytest.raises(ValidationError, match="must remain non-executing"):
        MvpPilotDecisionCommand.model_validate({**payload, "pilot_start_requested": True})


def test_decision_api_exposes_stable_context_and_records_hash_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUITE_DATA_DIR", str(tmp_path))
    test_app = build_app()
    client = TestClient(test_app)

    first_context = client.get(
        "/v1/platform/cockpit/mvp-pilot-decision-context",
        headers=ADMIN_HEADERS,
    )
    second_context = client.get(
        "/v1/platform/cockpit/mvp-pilot-decision-context",
        headers=ADMIN_HEADERS,
    )

    assert first_context.status_code == 200
    assert second_context.status_code == 200
    context_body = first_context.json()
    assert context_body["context_hash"] == second_context.json()["context_hash"]
    assert context_body["go_decision_allowed"] is True
    assert context_body["pilot_start_allowed"] is False
    assert context_body["content_included"] is False

    command = _command(
        MvpPilotDecisionContext.model_validate(context_body),
        suffix=uuid4().hex,
    )
    response = client.post(
        "/v1/platform/cockpit/mvp-pilot-decision-capture-submit",
        headers=ADMIN_HEADERS,
        json=command.model_dump(mode="json"),
    )
    replay = client.post(
        "/v1/platform/cockpit/mvp-pilot-decision-capture-submit",
        headers=ADMIN_HEADERS,
        json=command.model_dump(mode="json"),
    )
    current = client.get(
        "/v1/platform/cockpit/mvp-pilot-decisions/current",
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True
    assert current.status_code == 200
    assert current.json()["evidence_hash"] == response.json()["evidence_hash"]
    assert response.json()["pilot_start_allowed"] is False
    assert response.json()["module_activation_executed"] is False
    assert response.json()["external_side_effect_executed"] is False
    assert "decision_reason" not in response.json()
    latest_event = test_app.state.audit_logger.events[-1]
    assert latest_event.event_type == "platform.mvp_pilot_decision.recorded"
    assert "decision_reason" not in latest_event.metadata
    assert "human_confirmation_statement" not in latest_event.metadata

    denied = client.get(
        "/v1/platform/cockpit/mvp-pilot-decision-context",
        headers={**ADMIN_HEADERS, "X-Role-Ids": "knowledge-worker"},
    )
    assert denied.status_code == 403


def test_mvp_pilot_decision_migration_is_tenant_scoped_append_only_and_restore_bound() -> None:
    migration = get_migration("0076")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.mvp_pilot_decision_records" in sql
    assert "force row level security" in sql
    assert "mvp_pilot_decision_records_tenant_insert" in sql
    assert "mvp_pilot_decision_records_append_only" in sql
    assert "grant select, insert on table collabio.mvp_pilot_decision_records to collabio_authz_admin" in sql
    assert "no admission, activation, traffic authorization, pilot start" in sql


def test_postgres_decision_store_enforces_rls_and_append_only_records() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    authz_dsn = os.environ.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    if not migration_dsn or not authz_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)
    service = MvpPilotDecisionService(
        store=PgMvpPilotDecisionStore(database_dsn=authz_dsn),
        audit_logger=InMemoryAuditLogger(),
    )
    context = _context()
    record = service.capture(
        user_context=_admin(),
        command=_command(context, suffix=uuid4().hex),
        decision_context=context,
    )

    assert service.latest(tenant_id="tenant-demo") is not None
    assert service.latest(tenant_id="tenant-other") is None
    with psycopg.connect(authz_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", ("tenant-demo",))
        with pytest.raises(psycopg.Error):
            connection.execute(
                """
                UPDATE collabio.mvp_pilot_decision_records
                SET decided_by = 'tampered'
                WHERE tenant_id = %s AND decision_id = %s
                """,
                ("tenant-demo", record.decision_id),
            )
