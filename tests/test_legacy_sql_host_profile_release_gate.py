from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from suite.persistence.migration_catalog import get_migration
from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import LegacySqlApprovedHostProfile
from suite.platform.legacy_sql_evidence_ledger import LegacySqlEvidenceType
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN,
    LegacySqlEvidenceLedgerBackend,
    LegacySqlEvidenceLedgerBackendDrillResult,
    LegacySqlEvidenceLedgerOperationsReport,
    LegacySqlEvidenceLedgerOperationsRunbookEvidence,
    build_legacy_sql_evidence_ledger_operations_report_hash,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    InMemoryLegacySqlHostProfileReleaseGateEvidenceStore,
    JsonlLegacySqlHostProfileReleaseGateEvidenceStore,
    LegacySqlHostProfileReleaseGateCommand,
    LegacySqlHostProfileReleaseGateEvidence,
    LegacySqlHostProfileReleaseGateStatus,
    PgLegacySqlHostProfileReleaseGateEvidenceStore,
    build_legacy_sql_host_profile_release_gate,
    build_legacy_sql_host_profile_release_gate_hash,
    legacy_sql_host_profile_release_gate_ref,
    require_legacy_sql_host_profile_release_gate_for_wiring,
    require_legacy_sql_host_profile_release_gate_ready,
)
from suite.platform.legacy_sql_server_metadata import (
    DEFAULT_CONNECTOR_POLICY_PATH,
    LegacySqlServerConnectorPolicy,
    build_legacy_sql_connector_policy_hash,
    load_legacy_sql_connector_policy,
)

ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_legacy_sql_host_profile_release_gate_allows_only_confirmed_metadata_profile() -> None:
    checked_at = datetime(2026, 6, 18, 8, tzinfo=UTC)
    evaluated_at = checked_at + timedelta(hours=1)
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    ledger_report = ready_ledger_operations_report(tenant_id="tenant-host-gate-ready", checked_at=checked_at)
    host_profile = approved_host_profile(policy_hash=policy_hash)
    command = release_command(
        tenant_id="tenant-host-gate-ready",
        policy_hash=policy_hash,
        ledger_report_hash=ledger_report.evidence_hash,
    )

    gate = build_legacy_sql_host_profile_release_gate(
        command=command,
        host_profile=host_profile,
        connector_policy=policy,
        ledger_operations_report=ledger_report,
        evaluated_at_utc=evaluated_at,
    )

    assert gate.schema_version == "legacy_sql_host_profile_release_gate.v1"
    assert gate.continuity_domain == LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN
    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.READY
    assert gate.host_profile_activation_allowed
    assert gate.metadata_worker_scheduling_allowed
    assert not gate.real_connection_used
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.ledger_operations_report_hash_valid
    assert gate.ledger_operations_report_fresh
    assert gate.ledger_operations_gate_passed
    assert gate.postgres_ledger_backend_ready
    assert gate.connector_policy_hash_valid
    assert gate.host_profile_policy_bound
    assert gate.host_profile_egress_bound
    assert gate.host_profile_secret_bound
    assert gate.host_profile_fingerprint_bound
    assert gate.host_profile_metadata_only
    assert gate.human_confirmation_verified
    assert gate.metadata_only_boundary_verified
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_host_profile_release_gate_hash(gate)
    assert require_legacy_sql_host_profile_release_gate_ready(gate) == gate
    assert (
        require_legacy_sql_host_profile_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-host-gate-ready",
            host_profile_ref=host_profile.host_profile_ref,
            evidence_hash=gate.evidence_hash,
        )
        == gate
    )
    assert legacy_sql_host_profile_release_gate_ref(gate) == (
        f"legacy-sql-host-profile-release-gate:{gate.evidence_hash}"
    )
    assert host_profile.connection_secret_ref not in gate.model_dump_json()


def test_legacy_sql_host_profile_release_gate_blocks_missing_human_confirmation() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    ledger_report = ready_ledger_operations_report(
        tenant_id="tenant-host-gate-confirmation",
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    command = release_command(
        tenant_id="tenant-host-gate-confirmation",
        policy_hash=policy_hash,
        ledger_report_hash=ledger_report.evidence_hash,
        human_confirmation=False,
    )

    gate = build_legacy_sql_host_profile_release_gate(
        command=command,
        host_profile=approved_host_profile(policy_hash=policy_hash),
        connector_policy=policy,
        ledger_operations_report=ledger_report,
        evaluated_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )

    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.BLOCKED
    assert not gate.host_profile_activation_allowed
    assert "explicit_human_confirmation_missing" in gate.blocking_reasons
    with pytest.raises(ValueError, match="explicit_human_confirmation_missing"):
        require_legacy_sql_host_profile_release_gate_ready(gate)


def test_legacy_sql_host_profile_release_gate_blocks_stale_or_tampered_ledger_report() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    stale_report = ready_ledger_operations_report(
        tenant_id="tenant-host-gate-stale",
        checked_at=datetime(2026, 6, 15, 8, tzinfo=UTC),
    )
    tampered_report = stale_report.model_copy(update={"evidence_hash": "sha256:" + "9" * 64})

    gate = build_legacy_sql_host_profile_release_gate(
        command=release_command(
            tenant_id="tenant-host-gate-stale",
            policy_hash=policy_hash,
            ledger_report_hash=tampered_report.evidence_hash,
        ),
        host_profile=approved_host_profile(policy_hash=policy_hash),
        connector_policy=policy,
        ledger_operations_report=tampered_report,
        evaluated_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )

    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.BLOCKED
    assert "ledger_operations_report_hash_invalid" in gate.blocking_reasons
    assert "ledger_operations_report_stale" in gate.blocking_reasons


def test_legacy_sql_host_profile_release_gate_requires_postgres_ledger_backend() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    report = ready_ledger_operations_report(
        tenant_id="tenant-host-gate-jsonl-only",
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
        backends=(LegacySqlEvidenceLedgerBackend.JSONL,),
    )

    gate = build_legacy_sql_host_profile_release_gate(
        command=release_command(
            tenant_id="tenant-host-gate-jsonl-only",
            policy_hash=policy_hash,
            ledger_report_hash=report.evidence_hash,
        ),
        host_profile=approved_host_profile(policy_hash=policy_hash),
        connector_policy=policy,
        ledger_operations_report=report,
        evaluated_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )

    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.BLOCKED
    assert "postgres_ledger_backend_not_ready" in gate.blocking_reasons


def test_legacy_sql_host_profile_release_gate_blocks_policy_and_profile_mismatch() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    report = ready_ledger_operations_report(
        tenant_id="tenant-host-gate-policy",
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    host_profile = approved_host_profile(policy_hash=policy_hash).model_copy(
        update={"approved_egress_ref": "egress:other-approved-route"}
    )

    gate = build_legacy_sql_host_profile_release_gate(
        command=release_command(
            tenant_id="tenant-host-gate-policy",
            policy_hash=policy_hash,
            ledger_report_hash=report.evidence_hash,
        ),
        host_profile=host_profile,
        connector_policy=policy,
        ledger_operations_report=report,
        evaluated_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )

    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.BLOCKED
    assert "host_profile_egress_not_bound" in gate.blocking_reasons
    with pytest.raises(ValueError, match="profile does not match"):
        require_legacy_sql_host_profile_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-host-gate-policy",
            host_profile_ref="legacy-host:other",
            evidence_hash=gate.evidence_hash,
        )


def test_legacy_sql_host_profile_release_gate_rejects_dsn_or_import_requests() -> None:
    with pytest.raises(ValueError, match="not DSN"):
        release_command(
            tenant_id="tenant-host-gate-unsafe",
            policy_hash="sha256:" + "1" * 64,
            ledger_report_hash="sha256:" + "2" * 64,
            dsn="sqlserver://example.invalid",
        )

    with pytest.raises(ValueError, match="metadata discovery host profiles"):
        release_command(
            tenant_id="tenant-host-gate-unsafe",
            policy_hash="sha256:" + "1" * 64,
            ledger_report_hash="sha256:" + "2" * 64,
            import_dry_run_requested=True,
        )


def test_legacy_sql_host_profile_release_gate_jsonl_store_reloads_tenant_scoped_evidence(tmp_path: Path) -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id="tenant-host-gate-jsonl-store",
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    path = tmp_path / "legacy_sql_host_profile_gates.jsonl"
    store = JsonlLegacySqlHostProfileReleaseGateEvidenceStore(path=path)

    persisted = store.append(gate)
    reloaded = JsonlLegacySqlHostProfileReleaseGateEvidenceStore(path=path)

    assert persisted == gate
    assert reloaded.get(tenant_id=gate.tenant_id, evidence_hash=gate.evidence_hash) == gate
    assert reloaded.list_evidence(tenant_id=gate.tenant_id) == (gate,)
    assert reloaded.list_evidence(tenant_id="tenant-other") == ()
    with pytest.raises(ValueError, match="already exists"):
        reloaded.append(gate)


def test_legacy_sql_host_profile_release_gate_store_rejects_tampered_evidence() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id="tenant-host-gate-tampered",
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    ).model_copy(update={"host_profile_activation_allowed": False})
    store = InMemoryLegacySqlHostProfileReleaseGateEvidenceStore()

    with pytest.raises(ValueError, match="evidence hash is invalid"):
        store.append(gate)


def test_pg_legacy_sql_host_profile_release_gate_store_is_tenant_scoped_append_only_and_metadata_only(
    live_database: LiveDatabase,
) -> None:
    suffix = os.urandom(4).hex()
    tenant_id = f"tenant-host-gate-pg-{suffix}"
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id=tenant_id,
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    store = PgLegacySqlHostProfileReleaseGateEvidenceStore(database_dsn=live_database.app_dsn)

    persisted = store.append(gate)

    assert persisted == gate
    assert store.get(tenant_id=tenant_id, evidence_hash=gate.evidence_hash) == gate
    assert store.list_evidence(tenant_id=tenant_id) == (gate,)
    assert store.list_evidence(tenant_id=f"tenant-other-{suffix}") == ()
    assert gate.host_profile_activation_allowed is True
    assert gate.metadata_worker_scheduling_allowed is True
    assert gate.gate_status == LegacySqlHostProfileReleaseGateStatus.READY
    gate_json = gate.model_dump_json()
    assert "secret:legacy-sql-production-metadata" not in gate_json
    assert "sqlserver://" not in gate_json

    with pytest.raises(KeyError, match="not found"):
        store.get(tenant_id=f"tenant-other-{suffix}", evidence_hash=gate.evidence_hash)
    with pytest.raises(ValueError, match="already exists"):
        store.append(gate)

    with psycopg.connect(live_database.app_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            connection.execute(
                """
                UPDATE collabio.legacy_sql_host_profile_release_gate_evidence
                SET host_profile_activation_allowed = false
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, gate.evidence_hash),
            )


def test_legacy_sql_host_profile_release_gate_migration_declares_rls_append_only_and_metadata_boundary() -> None:
    migration = get_migration("0035")
    sql = normalized(migration.sql())

    assert migration.module_id == "crm_erp"
    assert "create table if not exists collabio.legacy_sql_host_profile_release_gate_evidence" in sql
    assert "legacy_sql_host_profile_release_gate.v1" in sql
    assert "connection_secret_ref_hash" in sql
    assert "real_connection_used boolean not null default false check (real_connection_used = false)" in sql
    assert "raw_data_access_allowed boolean not null default false check (raw_data_access_allowed = false)" in sql
    assert "import_dry_run_allowed boolean not null default false check (import_dry_run_allowed = false)" in sql
    assert "import_write_allowed boolean not null default false check (import_write_allowed = false)" in sql
    assert "destructive_actions_allowed boolean not null default false check" in sql
    assert "alter table collabio.legacy_sql_host_profile_release_gate_evidence enable row level security" in sql
    assert "alter table collabio.legacy_sql_host_profile_release_gate_evidence force row level security" in sql
    assert "create policy legacy_sql_host_profile_release_gate_tenant_select" in sql
    assert "create policy legacy_sql_host_profile_release_gate_tenant_insert" in sql
    assert "create policy legacy_sql_host_profile_release_gate_no_update" in sql
    assert "create policy legacy_sql_host_profile_release_gate_no_hard_delete" in sql
    assert "grant select, insert on table collabio.legacy_sql_host_profile_release_gate_evidence to collabio_app" in sql
    assert (
        "grant select, insert on table collabio.legacy_sql_host_profile_release_gate_evidence to collabio_worker" in sql
    )
    assert "grant update" not in sql
    assert "grant delete" not in sql


def approved_host_profile(*, policy_hash: str) -> LegacySqlApprovedHostProfile:
    return LegacySqlApprovedHostProfile(
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        connector_policy_ref="policy:legacy-sql-connector",
        policy_snapshot_hash=policy_hash,
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref="secret:legacy-sql-production-metadata",
        connection_fingerprint_hash="sha256:legacy-sql-production-fingerprint",
        row_count_estimates_allowed=True,
    )


def release_command(
    *,
    tenant_id: str,
    policy_hash: str,
    ledger_report_hash: str,
    human_confirmation: bool = True,
    dsn: str | None = None,
    import_dry_run_requested: bool = False,
) -> LegacySqlHostProfileReleaseGateCommand:
    return LegacySqlHostProfileReleaseGateCommand(
        tenant_id=tenant_id,
        source_system_ref="legacy-sql:production-sqlserver",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        connector_policy_ref="policy:legacy-sql-connector",
        policy_snapshot_hash=policy_hash,
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref="secret:legacy-sql-production-metadata",
        connection_fingerprint_hash="sha256:legacy-sql-production-fingerprint",
        ledger_operations_report_hash=ledger_report_hash,
        requested_by="legacy-sql-host-profile-release-gate-test",
        human_confirmation_reference="human-confirmation:legacy-sql-host-profile-release",
        human_confirmation=human_confirmation,
        dsn=dsn,
        import_dry_run_requested=import_dry_run_requested,
    )


def ready_ledger_operations_report(
    *,
    tenant_id: str,
    checked_at: datetime,
    backends: tuple[LegacySqlEvidenceLedgerBackend, ...] = (
        LegacySqlEvidenceLedgerBackend.JSONL,
        LegacySqlEvidenceLedgerBackend.POSTGRES,
    ),
) -> LegacySqlEvidenceLedgerOperationsReport:
    backend_results = tuple(ready_backend_result(tenant_id=tenant_id, backend=backend) for backend in backends)
    draft = LegacySqlEvidenceLedgerOperationsReport(
        run_id=f"legacy-sql-evidence-ledger-drill-{tenant_id}",
        checked_by="legacy-sql-host-profile-release-gate-test",
        checked_at_utc=checked_at,
        selected_backends=backends,
        backend_results=backend_results,
        ready_count=len(backend_results),
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=("legacy SQL evidence ledger backends are ready",),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id=f"legacy-sql-evidence-ledger-drill-{tenant_id}",
            checked_by="legacy-sql-host-profile-release-gate-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def ready_gate(
    *,
    tenant_id: str,
    policy: LegacySqlServerConnectorPolicy,
    policy_hash: str,
    checked_at: datetime,
) -> LegacySqlHostProfileReleaseGateEvidence:
    ledger_report = ready_ledger_operations_report(tenant_id=tenant_id, checked_at=checked_at)
    return build_legacy_sql_host_profile_release_gate(
        command=release_command(
            tenant_id=tenant_id,
            policy_hash=policy_hash,
            ledger_report_hash=ledger_report.evidence_hash,
        ),
        host_profile=approved_host_profile(policy_hash=policy_hash),
        connector_policy=policy,
        ledger_operations_report=ledger_report,
        evaluated_at_utc=checked_at + timedelta(hours=1),
    )


def ready_backend_result(
    *,
    tenant_id: str,
    backend: LegacySqlEvidenceLedgerBackend,
) -> LegacySqlEvidenceLedgerBackendDrillResult:
    hash_digit = "1" if backend == LegacySqlEvidenceLedgerBackend.JSONL else "2"
    return LegacySqlEvidenceLedgerBackendDrillResult(
        backend=backend,
        tenant_id=tenant_id,
        ledger_entry_count=2,
        ledger_entry_hashes=("sha256:" + hash_digit * 64, "sha256:" + "3" * 64),
        evidence_types=(
            LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT,
            LegacySqlEvidenceType.READINESS_SMOKE_REPORT,
        ),
        restore_evidence_hashes=("sha256:" + "4" * 64,),
        intake_report_hash="sha256:" + "5" * 64,
        readiness_smoke_report_hash="sha256:" + "6" * 64,
        write_path_ok=True,
        restore_hash_bound=True,
        related_evidence_hashes_recovered=True,
        tenant_isolation_ok=True,
        duplicate_append_rejected=True,
        metadata_only_ok=True,
        host_profile_release_precondition_ok=True,
        blocking_reasons=(),
    )
