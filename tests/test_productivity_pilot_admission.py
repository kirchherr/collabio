from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import build_app
from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import (
    PilotTenantEvidence,
    ProductivityPilotPreflightGate,
    build_productivity_pilot_preflight_gate_hash,
    persist_productivity_pilot_preflight_gate,
)
from suite.persistence.migration_catalog import get_migration
from suite.persistence.migrator import apply_migrations
from suite.platform.productivity_pilot_admission import (
    PRODUCTIVITY_PILOT_ADMISSION_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotAdmissionRecordStore,
    InMemoryProductivityPilotPreflightStore,
    PgProductivityPilotAdmissionRecordStore,
    PgProductivityPilotPreflightStore,
    ProductivityPilotAdmissionCommand,
    ProductivityPilotAdmissionConflict,
    ProductivityPilotAdmissionService,
    ProductivityPilotPreflightNotFound,
    build_productivity_pilot_admission_record_hash,
)


def _gate(*, tenant_ids: tuple[str, ...] = ("tenant-demo",)) -> ProductivityPilotPreflightGate:
    draft = ProductivityPilotPreflightGate(
        checked_at_utc="2026-07-30T15:00:00Z",
        runtime_environment=f"test-{uuid4().hex}",
        policy_id="controlled-productivity-pilot",
        policy_hash="sha256:" + "1" * 64,
        business_backend_release_gate_hash="sha256:" + "2" * 64,
        business_backend_release_ready=True,
        candidate_tenant_ids=tenant_ids,
        candidate_tenant_count=len(tenant_ids),
        maximum_candidate_tenant_count=10,
        tenant_module_state_manifest_hash="sha256:" + "3" * 64,
        tenants=tuple(
            PilotTenantEvidence(
                tenant_id=tenant_id,
                slices=(),
                ready_slice_count=3,
                ready=True,
            )
            for tenant_id in tenant_ids
        ),
        ready_tenant_count=len(tenant_ids),
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
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_productivity_pilot_preflight_gate_hash(draft)})


def _command(gate: ProductivityPilotPreflightGate, *, suffix: str = "one") -> ProductivityPilotAdmissionCommand:
    return ProductivityPilotAdmissionCommand(
        admission_id=f"pilot-admission-{suffix}",
        preflight_gate_hash=gate.gate_hash,
        policy_hash=gate.policy_hash,
        business_backend_release_gate_hash=gate.business_backend_release_gate_hash,
        tenant_module_state_manifest_hash=gate.tenant_module_state_manifest_hash,
        idempotency_key_ref=f"request:pilot-admission-{suffix}",
        change_request_ref=f"change:pilot-admission-{suffix}",
        human_confirmation_reference=f"approval:pilot-admission-{suffix}",
        human_confirmation_statement=PRODUCTIVITY_PILOT_ADMISSION_CONFIRMATION_STATEMENT,
        monitoring_owner_ref="principal:pilot-monitoring-owner",
        rollback_owner_ref="principal:pilot-rollback-owner",
        audit_chain_ref=f"audit:pilot-admission-{suffix}",
        admitted_at_utc=datetime(2026, 7, 30, 15, tzinfo=UTC),
    )


def _admin(tenant_id: str = "tenant-demo") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id="pilot-admin", role_ids={"tenant-admin"})


def test_admission_is_idempotent_metadata_only_and_non_executing() -> None:
    gate = _gate()
    service = ProductivityPilotAdmissionService(
        preflight_store=InMemoryProductivityPilotPreflightStore((gate,)),
        record_store=InMemoryProductivityPilotAdmissionRecordStore(),
    )
    command = _command(gate)

    record = service.admit(user_context=_admin(), command=command)
    replay = service.admit(user_context=_admin(), command=command)

    assert record.admission_recorded is True
    assert record.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.evidence_hash == record.evidence_hash
    assert record.evidence_hash == build_productivity_pilot_admission_record_hash(record)
    assert record.pilot_start_allowed is False
    assert record.traffic_scope_enforced is False
    assert record.tenant_state_changed is False
    assert record.module_activation_executed is False
    assert record.business_write_executed is False
    assert record.content_included is False
    assert "human_confirmation_statement" not in record.model_dump()


def test_admission_fails_closed_for_role_tenant_and_authoritative_hash_mismatch() -> None:
    gate = _gate()
    service = ProductivityPilotAdmissionService(
        preflight_store=InMemoryProductivityPilotPreflightStore((gate,)),
        record_store=InMemoryProductivityPilotAdmissionRecordStore(),
    )
    command = _command(gate)

    with pytest.raises(PermissionError, match="tenant admin"):
        service.admit(
            user_context=UserContext(
                tenant_id="tenant-demo",
                user_id="reader",
                role_ids={"knowledge-worker"},
            ),
            command=command,
        )
    with pytest.raises(ProductivityPilotPreflightNotFound):
        service.admit(user_context=_admin("tenant-other"), command=command)
    with pytest.raises(ProductivityPilotAdmissionConflict, match="policy_hash"):
        service.admit(
            user_context=_admin(),
            command=command.model_copy(update={"policy_hash": "sha256:" + "9" * 64}),
        )


def test_admission_requires_exact_confirmation_and_rejects_execution_flags() -> None:
    gate = _gate()
    payload = _command(gate).model_dump()

    with pytest.raises(ValidationError, match="exact productivity pilot admission confirmation"):
        ProductivityPilotAdmissionCommand.model_validate({**payload, "human_confirmation_statement": "approve"})
    with pytest.raises(ValidationError, match="must remain non-executing"):
        ProductivityPilotAdmissionCommand.model_validate({**payload, "pilot_start_requested": True})


def test_admission_api_requires_tenant_admin_and_audits_hashes_only() -> None:
    gate = _gate()
    test_app = build_app()
    assert isinstance(test_app.state.productivity_pilot_preflight_store, InMemoryProductivityPilotPreflightStore)
    test_app.state.productivity_pilot_preflight_store.add(gate)
    client = TestClient(test_app)
    payload = _command(gate, suffix="api").model_dump(mode="json")
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "pilot-api-admin",
        "X-Role-Ids": "tenant-admin",
    }

    response = client.post(
        "/v1/platform/productivity-pilot/admissions",
        headers=headers,
        json=payload,
    )
    replay = client.post(
        "/v1/platform/productivity-pilot/admissions",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 201
    assert replay.status_code == 201
    assert response.json()["admission_recorded"] is True
    assert response.json()["pilot_start_allowed"] is False
    assert replay.json()["idempotent_replay"] is True
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.admission_recorded"
    assert "human_confirmation_statement" not in event.metadata
    denied = client.post(
        "/v1/platform/productivity-pilot/admissions",
        headers={**headers, "X-Role-Ids": "knowledge-worker"},
        json=payload,
    )
    assert denied.status_code == 403


def test_productivity_pilot_admission_migration_is_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0061")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_preflight_reports" in sql
    assert "create table if not exists collabio.productivity_pilot_admission_records" in sql
    assert "force row level security" in sql
    assert "productivity_pilot_preflight_reports_tenant_select" in sql
    assert "productivity_pilot_admission_records_tenant_insert" in sql
    assert "productivity_pilot_admission_records_append_only" in sql
    assert (
        "grant select, insert on table collabio.productivity_pilot_admission_records to collabio_authz_admin"
    ) in sql
    assert "does not activate modules, enforce traffic or execute business writes" in sql


def test_postgres_admission_persists_authoritative_evidence_with_rls() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    authz_dsn = os.environ.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    if not migration_dsn or not authz_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)
    gate = _gate()
    persist_productivity_pilot_preflight_gate(database_dsn=migration_dsn, gate=gate)
    service = ProductivityPilotAdmissionService(
        preflight_store=PgProductivityPilotPreflightStore(database_dsn=authz_dsn),
        record_store=PgProductivityPilotAdmissionRecordStore(database_dsn=authz_dsn),
    )

    record = service.admit(
        user_context=_admin(),
        command=_command(gate, suffix=uuid4().hex),
    )

    assert record.admission_recorded is True
    with pytest.raises(ProductivityPilotPreflightNotFound):
        service.preflight_store.get(tenant_id="tenant-other", gate_hash=gate.gate_hash)
    with psycopg.connect(authz_dsn) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", ("tenant-other",))
        row = connection.execute(
            """
            SELECT admission_record
            FROM collabio.productivity_pilot_admission_records
            WHERE tenant_id = %s AND admission_id = %s
            """,
            ("tenant-demo", record.admission_id),
        ).fetchone()
    assert row is None
    with psycopg.connect(authz_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", ("tenant-demo",))
        with pytest.raises(psycopg.Error):
            connection.execute(
                """
                UPDATE collabio.productivity_pilot_admission_records
                SET admitted_by = 'tampered'
                WHERE tenant_id = %s AND admission_id = %s
                """,
                ("tenant-demo", record.admission_id),
            )
