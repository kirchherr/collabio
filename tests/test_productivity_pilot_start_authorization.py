from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

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
from suite.platform.productivity_pilot_start_authorization import (
    PRODUCTIVITY_PILOT_START_AUTHORIZATION_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotStartAuthorizationStore,
    PgProductivityPilotStartAuthorizationStore,
    ProductivityPilotControlEvidence,
    ProductivityPilotStartAuthorizationCommand,
    ProductivityPilotStartAuthorizationConflict,
    ProductivityPilotStartAuthorizationService,
    build_productivity_pilot_start_authorization_hash,
)
from suite.platform.productivity_pilot_traffic_scope import (
    PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_CONFIRMATION_STATEMENT,
    InMemoryProductivityPilotTrafficScopeStore,
    PgProductivityPilotTrafficScopeStore,
    ProductivityPilotTrafficScopeCommand,
    ProductivityPilotTrafficScopeEnforcement,
    ProductivityPilotTrafficScopeService,
)
from suite.platform.tasks_activities_module import (
    TASKS_ACTIVITY_READ_FEATURE_ID,
    TASKS_ITEMS_READ_FEATURE_ID,
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
)

NOW = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)


def _policy() -> ProductivityPilotPolicy:
    return load_productivity_pilot_policy(Path("docs/operations/productivity_pilot_policy.json"))


def _gate(policy: ProductivityPilotPolicy, *, tenant_id: str = "tenant-demo") -> ProductivityPilotPreflightGate:
    draft = ProductivityPilotPreflightGate(
        checked_at_utc=(NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        runtime_environment=f"start-authorization-test-{uuid4().hex}",
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


def _user(*, tenant_id: str = "tenant-demo", user_id: str, role: str) -> UserContext:
    return UserContext(tenant_id=tenant_id, user_id=user_id, role_ids={role})


def _admit(
    gate: ProductivityPilotPreflightGate,
    *,
    preflight_store: InMemoryProductivityPilotPreflightStore | PgProductivityPilotPreflightStore,
    admission_store: InMemoryProductivityPilotAdmissionRecordStore | PgProductivityPilotAdmissionRecordStore,
    tenant_id: str = "tenant-demo",
    suffix: str = "one",
) -> ProductivityPilotAdmissionRecord:
    return ProductivityPilotAdmissionService(
        preflight_store=preflight_store,
        record_store=admission_store,
    ).admit(
        user_context=_user(tenant_id=tenant_id, user_id="pilot-admission-admin", role="tenant-admin"),
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
            admitted_at_utc=NOW - timedelta(minutes=30),
        ),
    )


def _enforce(
    *,
    policy: ProductivityPilotPolicy,
    gate: ProductivityPilotPreflightGate,
    admission: ProductivityPilotAdmissionRecord,
    preflight_store: InMemoryProductivityPilotPreflightStore | PgProductivityPilotPreflightStore,
    admission_store: InMemoryProductivityPilotAdmissionRecordStore | PgProductivityPilotAdmissionRecordStore,
    traffic_store: InMemoryProductivityPilotTrafficScopeStore | PgProductivityPilotTrafficScopeStore,
    tenant_id: str = "tenant-demo",
    suffix: str = "one",
) -> ProductivityPilotTrafficScopeEnforcement:
    return ProductivityPilotTrafficScopeService(
        policy=policy,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_scope_store=traffic_store,
    ).enforce(
        user_context=_user(tenant_id=tenant_id, user_id="pilot-traffic-admin", role="tenant-admin"),
        command=ProductivityPilotTrafficScopeCommand(
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
            enforced_at_utc=NOW - timedelta(minutes=15),
        ),
    )


def _control_evidence(
    policy: ProductivityPilotPolicy,
    *,
    authorized_at: datetime,
    expires_at: datetime,
) -> tuple[tuple[ProductivityPilotControlEvidence, ...], tuple[ProductivityPilotControlEvidence, ...]]:
    monitoring = tuple(
        ProductivityPilotControlEvidence(
            control_id=control.control_id,
            evidence_hash=f"sha256:{index:064x}",
            observed_at_utc=authorized_at - timedelta(minutes=5),
            valid_until_utc=expires_at + timedelta(minutes=5),
        )
        for index, control in enumerate(policy.monitoring_controls, start=1)
    )
    rollback = tuple(
        ProductivityPilotControlEvidence(
            control_id=control.control_id,
            evidence_hash=f"sha256:{index:064x}",
            observed_at_utc=authorized_at - timedelta(minutes=5),
            valid_until_utc=expires_at + timedelta(minutes=5),
        )
        for index, control in enumerate(policy.rollback_controls, start=101)
    )
    return monitoring, rollback


def _command(
    *,
    policy: ProductivityPilotPolicy,
    gate: ProductivityPilotPreflightGate,
    admission: ProductivityPilotAdmissionRecord,
    traffic: ProductivityPilotTrafficScopeEnforcement,
    suffix: str = "one",
    authorized_at: datetime = NOW,
    effective_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> ProductivityPilotStartAuthorizationCommand:
    monitoring, rollback = _control_evidence(
        policy,
        authorized_at=authorized_at,
        expires_at=expires_at,
    )
    return ProductivityPilotStartAuthorizationCommand(
        authorization_id=f"pilot-start-{suffix}",
        enforcement_id=traffic.enforcement_id,
        traffic_scope_evidence_hash=traffic.evidence_hash,
        route_scope_hash=traffic.route_scope_hash,
        admission_evidence_hash=admission.evidence_hash,
        preflight_gate_hash=gate.gate_hash,
        policy_hash=gate.policy_hash,
        allowed_api_operations=policy.allowed_api_operations,
        monitoring_evidence=monitoring,
        rollback_evidence=rollback,
        idempotency_key_ref=f"request:pilot-start-{suffix}",
        change_request_ref=f"change:pilot-start-{suffix}",
        human_confirmation_reference=f"approval:pilot-start-{suffix}",
        security_approval_ref=f"security:pilot-start-{suffix}",
        audit_chain_ref=f"audit:pilot-start-{suffix}",
        human_confirmation_statement=PRODUCTIVITY_PILOT_START_AUTHORIZATION_CONFIRMATION_STATEMENT,
        authorized_at_utc=authorized_at,
        effective_at_utc=effective_at,
        expires_at_utc=expires_at,
    )


def _memory_service(
    *,
    runtime_enabled: bool = True,
    now: datetime = NOW,
) -> tuple[
    ProductivityPilotStartAuthorizationService,
    ProductivityPilotPolicy,
    ProductivityPilotPreflightGate,
    ProductivityPilotAdmissionRecord,
    ProductivityPilotTrafficScopeEnforcement,
]:
    policy = _policy()
    gate = _gate(policy)
    preflight_store = InMemoryProductivityPilotPreflightStore((gate,))
    admission_store = InMemoryProductivityPilotAdmissionRecordStore()
    admission = _admit(gate, preflight_store=preflight_store, admission_store=admission_store)
    traffic_store = InMemoryProductivityPilotTrafficScopeStore()
    traffic = _enforce(
        policy=policy,
        gate=gate,
        admission=admission,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_store=traffic_store,
    )
    service = ProductivityPilotStartAuthorizationService(
        policy=policy,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_scope_store=traffic_store,
        start_authorization_store=InMemoryProductivityPilotStartAuthorizationStore(),
        runtime_enabled=runtime_enabled,
        clock=lambda: now,
    )
    return service, policy, gate, admission, traffic


def test_start_authorization_is_idempotent_bounded_metadata_only_and_four_eyes() -> None:
    service, policy, gate, admission, traffic = _memory_service()
    command = _command(policy=policy, gate=gate, admission=admission, traffic=traffic)
    security_admin = _user(user_id="pilot-security-admin", role="security-admin")

    record = service.authorize(user_context=security_admin, command=command)
    replay = service.authorize(user_context=security_admin, command=command)

    assert record.evidence_hash == build_productivity_pilot_start_authorization_hash(record)
    assert replay.idempotent_replay is True
    assert replay.evidence_hash == record.evidence_hash
    assert record.authorized_by not in {admission.admitted_by, traffic.enforced_by}
    assert len(record.monitoring_evidence) == len(policy.monitoring_controls) == 5
    assert len(record.rollback_evidence) == len(policy.rollback_controls) == 4
    assert record.expires_at_utc - record.effective_at_utc == timedelta(hours=1)
    assert record.pilot_start_authorized is True
    assert record.pilot_business_traffic_allowed is True
    assert record.business_write_executed is False
    assert record.tenant_state_changed is False
    assert record.module_activation_executed is False
    assert record.destructive_action_executed is False
    assert record.external_side_effect_executed is False
    assert record.content_included is False
    assert "human_confirmation_statement" not in record.model_dump()


def test_start_authorization_fails_closed_for_role_four_eyes_kill_switch_and_bindings() -> None:
    service, policy, gate, admission, traffic = _memory_service()
    command = _command(policy=policy, gate=gate, admission=admission, traffic=traffic)

    with pytest.raises(PermissionError, match="security admin"):
        service.authorize(
            user_context=_user(user_id="reader", role="knowledge-worker"),
            command=command,
        )
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="four-eyes"):
        service.authorize(
            user_context=_user(user_id=admission.admitted_by, role="security-admin"),
            command=command,
        )
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="traffic_scope_evidence_hash"):
        service.authorize(
            user_context=_user(user_id="pilot-security-admin", role="security-admin"),
            command=command.model_copy(update={"traffic_scope_evidence_hash": "sha256:" + "9" * 64}),
        )

    closed, policy, gate, admission, traffic = _memory_service(runtime_enabled=False)
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="kill switch"):
        closed.authorize(
            user_context=_user(user_id="pilot-security-admin", role="security-admin"),
            command=_command(policy=policy, gate=gate, admission=admission, traffic=traffic),
        )


def test_start_authorization_requires_current_full_window_control_evidence() -> None:
    service, policy, gate, admission, traffic = _memory_service()
    command = _command(policy=policy, gate=gate, admission=admission, traffic=traffic)
    security_admin = _user(user_id="pilot-security-admin", role="security-admin")

    incomplete_monitoring = command.monitoring_evidence[:-1]
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="monitoring evidence"):
        service.authorize(
            user_context=security_admin,
            command=command.model_copy(update={"monitoring_evidence": incomplete_monitoring}),
        )

    short_lived = command.monitoring_evidence[0].model_copy(update={"valid_until_utc": NOW + timedelta(minutes=30)})
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="full authorization window"):
        service.authorize(
            user_context=security_admin,
            command=command.model_copy(update={"monitoring_evidence": (short_lived, *command.monitoring_evidence[1:])}),
        )

    stale_command = _command(
        policy=policy,
        gate=gate,
        admission=admission,
        traffic=traffic,
        authorized_at=NOW - timedelta(minutes=6),
        effective_at=NOW - timedelta(minutes=6),
    )
    with pytest.raises(ProductivityPilotStartAuthorizationConflict, match="clock skew"):
        service.authorize(user_context=security_admin, command=stale_command)


def test_start_authorization_opens_only_exact_routes_until_expiry() -> None:
    service, policy, gate, admission, traffic = _memory_service()

    unmanaged = service.authorize_operation(tenant_id="tenant-other", operation="GET /v1/tasks/items")
    prestart = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/tasks/items")
    assert unmanaged.authorization_allowed is True
    assert unmanaged.pilot_traffic_managed is False
    assert prestart.authorization_allowed is False
    assert prestart.http_status_code == 423

    record = service.authorize(
        user_context=_user(user_id="pilot-security-admin", role="security-admin"),
        command=_command(policy=policy, gate=gate, admission=admission, traffic=traffic),
    )
    allowed = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/tasks/items")
    outside = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/crm/accounts")
    assert allowed.authorization_allowed is True
    assert allowed.start_authorization_evidence_hash == record.evidence_hash
    assert allowed.authorization_expires_at_utc == record.expires_at_utc
    assert outside.authorization_allowed is False
    assert outside.http_status_code == 403

    service.clock = lambda: NOW + timedelta(hours=1)
    expired = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/tasks/items")
    assert expired.authorization_allowed is False
    assert expired.blocking_reason == "productivity_pilot_start_authorization_expired"
    assert expired.http_status_code == 423

    service.runtime_enabled = False
    disabled = service.authorize_operation(tenant_id="tenant-demo", operation="GET /v1/tasks/items")
    assert disabled.authorization_allowed is False
    assert disabled.blocking_reason == "productivity_pilot_runtime_disabled"


def test_start_authorization_api_opens_scoped_read_route_and_audits_hashes_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "1")
    policy = _policy()
    gate = _gate(policy)
    test_app = build_app()
    test_app.state.productivity_pilot_preflight_store.add(gate)
    admission = _admit(
        gate,
        preflight_store=test_app.state.productivity_pilot_preflight_store,
        admission_store=test_app.state.productivity_pilot_admission_record_store,
        suffix="api",
    )
    traffic = _enforce(
        policy=policy,
        gate=gate,
        admission=admission,
        preflight_store=test_app.state.productivity_pilot_preflight_store,
        admission_store=test_app.state.productivity_pilot_admission_record_store,
        traffic_store=test_app.state.productivity_pilot_traffic_scope_store,
        suffix="api",
    )
    now = datetime.now(UTC)
    command = _command(
        policy=policy,
        gate=gate,
        admission=admission,
        traffic=traffic,
        suffix="api",
        authorized_at=now,
        effective_at=now,
        expires_at=now + timedelta(hours=1),
    )
    client = TestClient(test_app)
    tenant_admin_headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "pilot-module-admin",
        "X-Role-Ids": "tenant-admin",
    }
    provision = client.post(
        "/v1/admin/tenant-modules/tasks_activities/provision",
        headers=tenant_admin_headers,
        json={
            "approval_reference": "approval:pilot-tasks-provision",
            "reason": "prepare controlled productivity pilot slice",
        },
    )
    assert provision.status_code == 200
    enable = client.post(
        "/v1/admin/tenant-modules/tasks_activities/enable",
        headers=tenant_admin_headers,
        json={
            "approval_reference": "approval:pilot-tasks-enable",
            "reason": "enable controlled productivity pilot reads",
            "enabled_features": {
                TASKS_ITEMS_READ_FEATURE_ID: True,
                TASKS_ACTIVITY_READ_FEATURE_ID: True,
                TASKS_WORKFLOW_WRITE_FEATURE_ID: True,
            },
        },
    )
    assert enable.status_code == 200
    security_headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "pilot-api-security-admin",
        "X-Role-Ids": "security-admin",
    }

    response = client.post(
        "/v1/platform/productivity-pilot/start-authorizations",
        headers=security_headers,
        json=command.model_dump(mode="json"),
    )
    replay = client.post(
        "/v1/platform/productivity-pilot/start-authorizations",
        headers=security_headers,
        json=command.model_dump(mode="json"),
    )

    assert response.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True
    event = test_app.state.audit_logger.events[-1]
    assert event.event_type == "platform.productivity_pilot.start_authorized"
    assert "human_confirmation_statement" not in event.metadata
    assert event.metadata["monitoring_control_count"] == 5
    assert event.metadata["rollback_control_count"] == 4

    reader_headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "pilot-reader",
        "X-Role-Ids": "knowledge-worker",
    }
    assert client.get("/v1/tasks/items", headers=reader_headers).status_code == 200
    outside = client.get("/v1/crm/accounts", headers=reader_headers)
    assert outside.status_code == 403
    assert outside.json()["detail"] == "operation_outside_productivity_pilot_route_scope"


def test_productivity_pilot_start_authorization_migration_is_append_only_and_tenant_scoped() -> None:
    migration = get_migration("0063")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "core"
    assert "create table if not exists collabio.productivity_pilot_start_authorizations" in sql
    assert "force row level security" in sql
    assert "productivity_pilot_start_authorizations_tenant_select" in sql
    assert "productivity_pilot_start_authorizations_tenant_insert" in sql
    assert "productivity_pilot_start_authorizations_append_only" in sql
    assert "interval '8 hours'" in sql
    assert "grant select, insert on table collabio.productivity_pilot_start_authorizations" in sql
    assert "no business write is executed by this record" in sql


def test_postgres_start_authorization_persists_authoritative_evidence_with_rls() -> None:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    authz_dsn = os.environ.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    if not migration_dsn or not authz_dsn:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)
    policy = _policy()
    tenant_id = f"tenant-pilot-start-{uuid4().hex}"
    suffix = uuid4().hex
    gate = _gate(policy, tenant_id=tenant_id)
    persist_productivity_pilot_preflight_gate(database_dsn=migration_dsn, gate=gate)
    preflight_store = PgProductivityPilotPreflightStore(database_dsn=authz_dsn)
    admission_store = PgProductivityPilotAdmissionRecordStore(database_dsn=authz_dsn)
    admission = _admit(
        gate,
        preflight_store=preflight_store,
        admission_store=admission_store,
        tenant_id=tenant_id,
        suffix=suffix,
    )
    traffic_store = PgProductivityPilotTrafficScopeStore(database_dsn=authz_dsn)
    traffic = _enforce(
        policy=policy,
        gate=gate,
        admission=admission,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_store=traffic_store,
        tenant_id=tenant_id,
        suffix=suffix,
    )
    start_store = PgProductivityPilotStartAuthorizationStore(database_dsn=authz_dsn)
    service = ProductivityPilotStartAuthorizationService(
        policy=policy,
        preflight_store=preflight_store,
        admission_store=admission_store,
        traffic_scope_store=traffic_store,
        start_authorization_store=start_store,
        runtime_enabled=True,
        clock=lambda: NOW,
    )

    record = service.authorize(
        user_context=_user(
            tenant_id=tenant_id,
            user_id="pilot-security-admin",
            role="security-admin",
        ),
        command=_command(
            policy=policy,
            gate=gate,
            admission=admission,
            traffic=traffic,
            suffix=suffix,
        ),
    )

    assert start_store.current(tenant_id=tenant_id) == record
    assert start_store.current(tenant_id="tenant-other") is None
    with psycopg.connect(authz_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        with pytest.raises(psycopg.Error):
            connection.execute(
                """
                UPDATE collabio.productivity_pilot_start_authorizations
                SET authorized_by = 'tampered'
                WHERE tenant_id = %s AND authorization_id = %s
                """,
                (tenant_id, record.authorization_id),
            )
