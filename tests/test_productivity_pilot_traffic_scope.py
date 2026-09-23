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
from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import (
    PilotTenantEvidence,
    ProductivityPilotPolicy,
    ProductivityPilotPreflightGate,
    build_productivity_pilot_policy_hash,
    build_productivity_pilot_preflight_gate_hash,
    load_productivity_pilot_policy,
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
    ProductivityPilotAdmissionRecord,
    ProductivityPilotAdmissionService,
)
from suite.platform.productivity_pilot_traffic_scope import (
    PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotTrafficScopeStore,
    PgProductivityPilotTrafficScopeStore,
    ProductivityPilotTrafficScopeCommand,
    ProductivityPilotTrafficScopeConflict,
    ProductivityPilotTrafficScopeService,
    build_productivity_pilot_traffic_scope_hash,
)


def _policy() -> ProductivityPilotPolicy:
    return load_productivity_pilot_policy(Path("docs/operations/productivity_pilot_policy.json"))


def _gate(policy: ProductivityPilotPolicy, *, tenant_id: str = "tenant-demo") -> ProductivityPilotPreflightGate:
    draft = ProductivityPilotPreflightGate(
        checked_at_utc="2026-07-30T15:30:00Z",
        runtime_environment=f"test-{uuid4().hex}",
        policy_id=policy.policy_id,
        policy_hash=build_productivity_pilot_policy_hash(policy),
        business_backend_release_gate_hash="sha256:" + "2" * 64,
        business_backend_release_ready=True,
        candidate_tenant_ids=(tenant_id,),
        candidate_tenant_count=1,
        maximum_candidate_tenant_count=policy.max_candidate_tenants,
        tenant_module_state_manifest_hash="sha256:" + "3" * 64,
        tenants=(
            PilotTenantEvidence(
                tenant_id=tenant_id,
                slices=(),
                ready_slice_count=3,
                ready=True,
            ),
        ),
        ready_tenant_count=1,
        productive_slice_count=3,
        route_scope_contract_verified=True,
        monitoring_contract_verified=True,
        monitoring_control_count=len(policy.monitoring_controls),
        rollback_contract_verified=True,
        rollback_control_count=len(policy.rollback_controls),
        human_admission_required=True,
        traffic_scope_enforcement_required=True,
        preflight_ready=True,
        next_action="record_explicit_human_pilot_admission_and_enforce_traffic_scope",
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_productivity_pilot_preflight_gate_hash(draft)})


def _admin(tenant_id: str = "tenant-demo") -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id="pilot-admin", role_ids={"tenant-admin"})


def _admit(
    gate: ProductivityPilotPreflightGate,
    *,
    preflight_store: InMemoryProductivityPilotPreflightStore,
    admission_store: InMemoryProductivityPilotAdmissionRecordStore,
    suffix: str = "one",
) -> ProductivityPilotAdmissionRecord:
    service = ProductivityPilotAdmissionService(preflight_store=preflight_store, record_store=admission_store)
    return service.admit(
        user_context=_admin(),
        command=ProductivityPilotAdmissionCommand(
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
            admitted_at_utc=datetime(2026, 7, 30, 15, 30, tzinfo=UTC),
        ),
    )


def _command(
    *,
    gate: ProductivityPilotPreflightGate,
    admission: ProductivityPilotAdmissionRecord,
    policy: ProductivityPilotPolicy,
    suffix: str = "one",
) -> ProductivityPilotTrafficScopeCommand:
    return ProductivityPilotTrafficScopeCommand(
        enforcement_id=f"pilot-traffic-scope-{suffix}",
        admission_id=admission.admission_id,
        admission_evidence_hash=admission.evidence_hash,
        preflight_gate_hash=gate.gate_hash,
        policy_hash=gate.policy_hash,
        allowed_api_operations=policy.allowed_api_operations,
        idempotency_key_ref=f"request:pilot-traffic-scope-{suffix}",
        change_request_ref=f"change:pilot-traffic-scope-{suffix}",
        ingress_policy_ref=f"ingress:pilot-traffic-scope-{suffix}",
        human_confirmation_reference=f"approval:pilot-traffic-scope-{suffix}",
        human_confirmation_statement=PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_CONFIRMATION_STATEMENT,
        audit_chain_ref=f"audit:pilot-traffic-scope-{suffix}",
        enforced_at_utc=datetime(2026, 7, 30, 15, 45, tzinfo=UTC),
    )


def _memory_service() -> tuple[
    ProductivityPilotTrafficScopeService,
    ProductivityPilotPreflightGate,
    ProductivityPilotAdmissionRecord,
    ProductivityPilotPolicy,
]:
    policy = _policy()
    gate = _gate(policy)
    preflight_store = InMemoryProductivityPilotPreflightStore((gate,))
    admission_store = InMemoryProductivityPilotAdmissionRecordStore()
    admission = _admit(gate, preflight_store=preflight_store, admission_store=admission_store)
    service = ProductivityPilotTrafficScopeService(
        policy=policy,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_scope_store=InMemoryProductivityPilotTrafficScopeStore(),
    )
    return service, gate, admission, policy


def test_traffic_scope_is_idempotent_metadata_only_and_prestart() -> None:
    service, gate, admission, policy = _memory_service()
    command = _command(gate=gate, admission=admission, policy=policy)

    record = service.enforce(user_context=_admin(), command=command)
    replay = service.enforce(user_context=_admin(), command=command)

    assert record.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.evidence_hash == record.evidence_hash
    assert record.evidence_hash == build_productivity_pilot_traffic_scope_hash(record)
    assert record.allowed_api_operations == policy.allowed_api_operations
    assert len(record.allowed_api_operations) == 7
    assert record.tenant_scope_enforced is True
    assert record.route_scope_enforced is True
    assert record.default_deny_enabled is True
    assert record.pilot_start_authorized is False
    assert record.pilot_business_traffic_allowed is False
    assert record.business_write_executed is False
    assert record.content_included is False
    assert "human_confirmation_statement" not in record.model_dump()


def test_traffic_scope_fails_closed_for_role_hash_and_route_scope_mismatch() -> None:
    service, gate, admission, policy = _memory_service()
    command = _command(gate=gate, admission=admission, policy=policy)

    with pytest.raises(PermissionError, match="tenant admin"):
        service.enforce(
            user_context=UserContext(
                tenant_id="tenant-demo",
                user_id="reader",
                role_ids={"knowledge-worker"},
            ),
            command=command,
        )
    with pytest.raises(ProductivityPilotTrafficScopeConflict, match="admission_evidence_hash"):
        service.enforce(
            user_context=_admin(),
            command=command.model_copy(update={"admission_evidence_hash": "sha256:" + "9" * 64}),
        )
    with pytest.raises(ProductivityPilotTrafficScopeConflict, match="allowed_api_operations"):
        service.enforce(
            user_context=_admin(),
            command=command.model_copy(update={"allowed_api_operations": policy.allowed_api_operations[:-1]}),
        )


def test_traffic_scope_decision_defaults_to_pass_and_denies_managed_prestart_traffic() -> None:
    service, gate, admission, policy = _memory_service()

    unmanaged = service.authorize_operation(tenant_id="tenant-other", operation="GET /v1/tasks/items")
    assert unmanaged.authorization_allowed is True
    assert unmanaged.pilot_traffic_managed is False

    record = service.enforce(
        user_context=_admin(),
        command=_command(gate=gate, admission=admission, policy=policy),
    )
    allowed_route = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/tasks/items")
    outside_route = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/crm/accounts")

    assert allowed_route.authorization_allowed is False
    assert allowed_route.operation_in_scope is True
    assert allowed_route.http_status_code == 423
    assert allowed_route.blocking_reason == "productivity_pilot_start_authorization_required"
    assert allowed_route.enforcement_evidence_hash == record.evidence_hash
    assert outside_route.authorization_allowed is False
    assert outside_route.operation_in_scope is False
    assert outside_route.http_status_code == 403
    assert outside_route.blocking_reason == "operation_outside_productivity_pilot_route_scope"


def test_traffic_scope_requires_exact_confirmation_and_rejects_start_flags() -> None:
    _, gate, admission, policy = _memory_service()
    payload = _command(gate=gate, admission=admission, policy=policy).model_dump()

    with pytest.raises(ValidationError, match="exact productivity pilot traffic scope confirmation"):
        ProductivityPilotTrafficScopeCommand.model_validate({**payload, "human_confirmation_statement": "enforce"})
    with pytest.raises(ValidationError, match="must remain pre-start"):
        ProductivityPilotTrafficScopeCommand.model_validate({**payload, "pilot_start_requested": True})


def test_traffic_scope_api_enforces_real_route_dependencies_and_audits_hashes_only() -> None:
    policy = _policy()
    gate = _gate(policy)
    test_app = build_app()
    assert isinstance(test_app.state.productivity_pilot_preflight_store, InMemoryProductivityPilotPreflightStore)
    assert isinstance(
        test_app.state.productivity_pilot_admission_record_store, InMemoryProductivityPilotAdmissionRecordStore
    )
    test_app.state.productivity_pilot_preflight_store.add(gate)
    admission = _admit(
        gate,
        preflight_store=test_app.state.productivity_pilot_preflight_store,
        admission_store=test_app.state.productivity_pilot_admission_record_store,
        suffix="api",
    )
    client = TestClient(test_app)
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "pilot-api-admin",
        "X-Role-Ids": "tenant-admin",
    }
    payload = _command(gate=gate, admission=admission, policy=policy, suffix="api").model_dump(mode="json")

    response = client.post(
        "/v1/platform/productivity-pilot/traffic-scope-enforcements",
        headers=headers,
        json=payload,
    )
    replay = client.post(
        "/v1/platform/productivity-pilot/traffic-scope-enforcements",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 201
    assert replay.status_code == 201
    assert response.json()["pilot_start_authorized"] is False
    assert response.json()["pilot_business_traffic_allowed"] is False
    assert replay.json()["idempotent_replay"] is True
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.traffic_scope_enforced"
    assert "human_confirmation_statement" not in event.metadata

    allowed_route = client.get("/v1/tasks/items", headers=headers)
    assert allowed_route.status_code == 423
    assert allowed_route.json()["detail"] == "productivity_pilot_start_authorization_required"
    assert test_app.state.audit_logger.events[-1].event_type == "platform.productivity_pilot.traffic_denied"
    assert "human_confirmation_statement" not in test_app.state.audit_logger.events[-1].metadata

    outside_route = client.get("/v1/crm/accounts", headers=headers)
    assert outside_route.status_code == 403
    assert outside_route.json()["detail"] == "operation_outside_productivity_pilot_route_scope"


def test_productivity_pilot_traffic_scope_migration_is_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0062")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_traffic_scope_enforcements" in sql
    assert "force row level security" in sql
    assert "productivity_pilot_traffic_scope_tenant_select" in sql
    assert "productivity_pilot_traffic_scope_tenant_insert" in sql
    assert "productivity_pilot_traffic_scope_append_only" in sql
    assert "grant select, insert on table collabio.productivity_pilot_traffic_scope_enforcements" in sql
    assert "default deny remains in force until separate pilot start authorization" in sql


def test_postgres_traffic_scope_persists_authoritative_evidence_with_rls() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    authz_dsn = os.environ.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    if not migration_dsn or not authz_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)
    policy = _policy()
    tenant_id = f"tenant-pilot-{uuid4().hex}"
    gate = _gate(policy, tenant_id=tenant_id)
    persist_productivity_pilot_preflight_gate(database_dsn=migration_dsn, gate=gate)
    preflight_store = PgProductivityPilotPreflightStore(database_dsn=authz_dsn)
    admission_store = PgProductivityPilotAdmissionRecordStore(database_dsn=authz_dsn)
    suffix = uuid4().hex
    admission_service = ProductivityPilotAdmissionService(
        preflight_store=preflight_store,
        record_store=admission_store,
    )
    admission = admission_service.admit(
        user_context=_admin(tenant_id),
        command=ProductivityPilotAdmissionCommand(
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
            admitted_at_utc=datetime(2026, 7, 30, 15, 30, tzinfo=UTC),
        ),
    )
    traffic_store = PgProductivityPilotTrafficScopeStore(database_dsn=authz_dsn)
    service = ProductivityPilotTrafficScopeService(
        policy=policy,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_scope_store=traffic_store,
    )

    record = service.enforce(
        user_context=_admin(tenant_id),
        command=_command(gate=gate, admission=admission, policy=policy, suffix=suffix),
    )

    assert traffic_store.current(tenant_id=tenant_id) == record
    assert traffic_store.current(tenant_id="tenant-other") is None
    with psycopg.connect(authz_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        with pytest.raises(psycopg.Error):
            connection.execute(
                """
                UPDATE collabio.productivity_pilot_traffic_scope_enforcements
                SET enforced_by = 'tampered'
                WHERE tenant_id = %s AND enforcement_id = %s
                """,
                (tenant_id, record.enforcement_id),
            )
