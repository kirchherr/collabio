from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import LegacySqlApprovedHostProfile
from suite.platform.legacy_sql_evidence_ledger import LegacySqlEvidenceType
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LegacySqlEvidenceLedgerBackend,
    LegacySqlEvidenceLedgerBackendDrillResult,
    LegacySqlEvidenceLedgerOperationsReport,
    LegacySqlEvidenceLedgerOperationsRunbookEvidence,
    build_legacy_sql_evidence_ledger_operations_report_hash,
)
from suite.platform.legacy_sql_host_profile_adapter import (
    LegacySqlHostProfileAdapter,
    LegacySqlHostProfileAdapterScheduleRequest,
    build_legacy_sql_host_profile_adapter_schedule_hash,
    build_legacy_sql_host_profile_adapter_smoke_report_hash,
    exit_code_for_report,
    legacy_sql_host_profile_adapter_schedule_ref,
    run_legacy_sql_host_profile_adapter_smoke_from_env,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    InMemoryLegacySqlHostProfileReleaseGateEvidenceStore,
    LegacySqlHostProfileReleaseGateCommand,
    LegacySqlHostProfileReleaseGateEvidence,
    PgLegacySqlHostProfileReleaseGateEvidenceStore,
    build_legacy_sql_host_profile_release_gate,
    legacy_sql_connection_secret_ref_hash,
    legacy_sql_host_profile_release_gate_ref,
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


def test_legacy_sql_host_profile_adapter_schedules_metadata_worker_from_ready_gate() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id="tenant-host-adapter-ready",
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    adapter = LegacySqlHostProfileAdapter(gate_store=InMemoryLegacySqlHostProfileReleaseGateEvidenceStore((gate,)))

    schedule = adapter.prepare_metadata_worker_schedule(
        request=schedule_request(
            tenant_id=gate.tenant_id,
            policy_hash=policy_hash,
            release_gate_evidence_hash=gate.evidence_hash,
        ),
        checked_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )

    assert schedule.schema_version == "legacy_sql_host_profile_adapter_schedule.v1"
    assert schedule.tenant_id == gate.tenant_id
    assert schedule.release_gate_ref == legacy_sql_host_profile_release_gate_ref(gate)
    assert schedule.connection_secret_ref_hash == legacy_sql_connection_secret_ref_hash(
        "secret:legacy-sql-production-metadata"
    )
    assert schedule.approved_egress_ref == "egress:legacy-sql-production-metadata"
    assert schedule.metadata_worker_command_hash.startswith("sha256:")
    assert schedule.metadata_worker_command_view.secret_reference_available
    assert schedule.metadata_worker_scheduling_allowed
    assert schedule.host_profile_adapter_ready
    assert not schedule.default_compose_legacy_network_enabled
    assert not schedule.network_connection_opened
    assert not schedule.real_connection_opened
    assert not schedule.raw_data_access_allowed
    assert not schedule.import_dry_run_allowed
    assert not schedule.import_write_allowed
    assert not schedule.destructive_actions_allowed
    assert schedule.evidence_hash == build_legacy_sql_host_profile_adapter_schedule_hash(schedule)
    assert legacy_sql_host_profile_adapter_schedule_ref(schedule) == (
        f"legacy-sql-host-profile-adapter-schedule:{schedule.evidence_hash}"
    )

    schedule_json = schedule.model_dump_json().lower()
    assert '"connection_secret_ref":' not in schedule_json
    assert "secret:legacy-sql-production-metadata" not in schedule_json
    assert "sqlserver://" not in schedule_json


def test_legacy_sql_host_profile_adapter_rejects_blocked_gate() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id="tenant-host-adapter-blocked",
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
        human_confirmation=False,
    )
    adapter = LegacySqlHostProfileAdapter(gate_store=InMemoryLegacySqlHostProfileReleaseGateEvidenceStore((gate,)))

    with pytest.raises(ValueError, match="explicit_human_confirmation_missing"):
        adapter.prepare_metadata_worker_schedule(
            request=schedule_request(
                tenant_id=gate.tenant_id,
                policy_hash=policy_hash,
                release_gate_evidence_hash=gate.evidence_hash,
            )
        )


def test_legacy_sql_host_profile_adapter_rejects_unbound_secret_or_unsafe_request() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id="tenant-host-adapter-secret",
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    adapter = LegacySqlHostProfileAdapter(gate_store=InMemoryLegacySqlHostProfileReleaseGateEvidenceStore((gate,)))

    with pytest.raises(ValueError, match="connection_secret_ref_hash"):
        adapter.prepare_metadata_worker_schedule(
            request=schedule_request(
                tenant_id=gate.tenant_id,
                policy_hash=policy_hash,
                release_gate_evidence_hash=gate.evidence_hash,
                connection_secret_ref="secret:other-legacy-sql",
            )
        )

    with pytest.raises(ValueError, match="not DSN"):
        schedule_request(
            tenant_id=gate.tenant_id,
            policy_hash=policy_hash,
            release_gate_evidence_hash=gate.evidence_hash,
            dsn="sqlserver://example.invalid",
        )


def test_pg_legacy_sql_host_profile_adapter_loads_gate_with_tenant_scope(
    live_database: LiveDatabase,
) -> None:
    suffix = os.urandom(4).hex()
    tenant_id = f"tenant-host-adapter-pg-{suffix}"
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(
        tenant_id=tenant_id,
        policy=policy,
        policy_hash=policy_hash,
        checked_at=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )
    store = PgLegacySqlHostProfileReleaseGateEvidenceStore(database_dsn=live_database.app_dsn)
    store.append(gate)
    adapter = LegacySqlHostProfileAdapter(gate_store=store)

    schedule = adapter.prepare_metadata_worker_schedule(
        request=schedule_request(
            tenant_id=tenant_id,
            policy_hash=policy_hash,
            release_gate_evidence_hash=gate.evidence_hash,
        )
    )

    assert schedule.tenant_id == tenant_id
    assert schedule.release_gate_evidence_hash == gate.evidence_hash
    with pytest.raises(KeyError, match="not found"):
        adapter.prepare_metadata_worker_schedule(
            request=schedule_request(
                tenant_id=f"tenant-other-{suffix}",
                policy_hash=policy_hash,
                release_gate_evidence_hash=gate.evidence_hash,
            )
        )


def test_legacy_sql_host_profile_adapter_smoke_builds_schedule_without_secret_leak(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "8" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": live_database.app_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": live_database.app_dsn,
        "SUITE_DATABASE_DSN": live_database.app_dsn,
    }

    report = run_legacy_sql_host_profile_adapter_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_host_profile_adapter_smoke_report.v1"
    assert report.host_profile_adapter_ready
    assert report.blocked_gate_rejected
    assert report.schedule_evidence_hash.startswith("sha256:")
    assert report.metadata_worker_command_hash.startswith("sha256:")
    assert not report.default_compose_legacy_network_enabled
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_host_profile_adapter_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    report_json = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in report_json
    assert "secret:legacy-sql-production-metadata" not in report_json
    assert "sqlserver://" not in report_json


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
        requested_by="legacy-sql-host-profile-adapter-test",
        human_confirmation_reference="human-confirmation:legacy-sql-host-profile-adapter",
        human_confirmation=human_confirmation,
    )


def ready_gate(
    *,
    tenant_id: str,
    policy: LegacySqlServerConnectorPolicy,
    policy_hash: str,
    checked_at: datetime,
    human_confirmation: bool = True,
) -> LegacySqlHostProfileReleaseGateEvidence:
    ledger_report = ready_ledger_operations_report(tenant_id=tenant_id, checked_at=checked_at)
    return build_legacy_sql_host_profile_release_gate(
        command=release_command(
            tenant_id=tenant_id,
            policy_hash=policy_hash,
            ledger_report_hash=ledger_report.evidence_hash,
            human_confirmation=human_confirmation,
        ),
        host_profile=approved_host_profile(policy_hash=policy_hash),
        connector_policy=policy,
        ledger_operations_report=ledger_report,
        evaluated_at_utc=checked_at + timedelta(hours=1),
    )


def schedule_request(
    *,
    tenant_id: str,
    policy_hash: str,
    release_gate_evidence_hash: str,
    connection_secret_ref: str = "secret:legacy-sql-production-metadata",
    dsn: str | None = None,
) -> LegacySqlHostProfileAdapterScheduleRequest:
    return LegacySqlHostProfileAdapterScheduleRequest(
        tenant_id=tenant_id,
        source_system_ref="legacy-sql:production-sqlserver",
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        connector_policy_ref="policy:legacy-sql-connector",
        policy_snapshot_hash=policy_hash,
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref=connection_secret_ref,
        connection_fingerprint_hash="sha256:legacy-sql-production-fingerprint",
        release_gate_evidence_hash=release_gate_evidence_hash,
        requested_by="legacy-sql-host-profile-adapter-test",
        approval_reference="approval:legacy-sql-host-profile-adapter",
        audit_chain_ref="audit:legacy-sql-host-profile-adapter",
        dsn=dsn,
    )


def ready_ledger_operations_report(
    *,
    tenant_id: str,
    checked_at: datetime,
) -> LegacySqlEvidenceLedgerOperationsReport:
    backend_results = (
        ready_backend_result(tenant_id=tenant_id, backend=LegacySqlEvidenceLedgerBackend.JSONL),
        ready_backend_result(tenant_id=tenant_id, backend=LegacySqlEvidenceLedgerBackend.POSTGRES),
    )
    draft = LegacySqlEvidenceLedgerOperationsReport(
        run_id=f"legacy-sql-evidence-ledger-drill-{tenant_id}",
        checked_by="legacy-sql-host-profile-adapter-test",
        checked_at_utc=checked_at,
        selected_backends=(
            LegacySqlEvidenceLedgerBackend.JSONL,
            LegacySqlEvidenceLedgerBackend.POSTGRES,
        ),
        backend_results=backend_results,
        ready_count=len(backend_results),
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=("legacy SQL evidence ledger backends are ready",),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id=f"legacy-sql-evidence-ledger-drill-{tenant_id}",
            checked_by="legacy-sql-host-profile-adapter-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


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
