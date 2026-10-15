from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from suite.persistence.migration_catalog import get_migration
from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import LegacySqlApprovedHostProfile
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LegacySqlEvidenceLedgerBackend,
    LegacySqlEvidenceLedgerBackendDrillResult,
    LegacySqlEvidenceLedgerOperationsReport,
    LegacySqlEvidenceLedgerOperationsRunbookEvidence,
    build_legacy_sql_evidence_ledger_operations_report_hash,
)
from suite.platform.legacy_sql_host_profile_adapter import (
    LegacySqlHostProfileAdapter,
    LegacySqlHostProfileAdapterScheduleEvidence,
    LegacySqlHostProfileAdapterScheduleRequest,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    InMemoryLegacySqlHostProfileReleaseGateEvidenceStore,
    LegacySqlHostProfileReleaseGateCommand,
    LegacySqlHostProfileReleaseGateEvidence,
    build_legacy_sql_host_profile_release_gate,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    InMemoryLegacySqlMetadataWorkerQueueStore,
    JsonlLegacySqlMetadataWorkerQueueStore,
    LegacySqlMetadataWorkerQueueStatus,
    PgLegacySqlMetadataWorkerQueueStore,
    build_legacy_sql_metadata_worker_queue_job,
    build_legacy_sql_metadata_worker_queue_job_hash,
    build_legacy_sql_metadata_worker_queue_operations_report_hash,
    exit_code_for_report,
    run_legacy_sql_metadata_worker_queue_operations_from_env,
)
from suite.platform.legacy_sql_server_metadata import (
    DEFAULT_CONNECTOR_POLICY_PATH,
    LegacySqlServerConnectorPolicy,
    build_legacy_sql_connector_policy_hash,
    load_legacy_sql_connector_policy,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    worker_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, worker_dsn=worker_dsn)


def test_legacy_sql_metadata_worker_queue_is_idempotent_and_records_lease_retry(tmp_path: Path) -> None:
    schedule = build_schedule(tmp_path=tmp_path)
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash="sha256:" + "7" * 64,
        enqueued_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )
    store = InMemoryLegacySqlMetadataWorkerQueueStore()

    persisted = store.enqueue(queued)
    duplicate = store.enqueue(queued)
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner="queue-test",
        lease_duration_seconds=60,
        now=datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    retry = store.record_retry(
        tenant_id=schedule.tenant_id,
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id or "",
        error_type="metadata-worker-retry-test",
        next_attempt_after_utc=datetime(2026, 6, 18, 9, 5, tzinfo=UTC),
        now=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )

    assert duplicate == persisted
    assert len(store.list_jobs(tenant_id=schedule.tenant_id)) == 1
    assert persisted.queue_status == LegacySqlMetadataWorkerQueueStatus.QUEUED
    assert leased.queue_status == LegacySqlMetadataWorkerQueueStatus.LEASED
    assert leased.attempt_count == 1
    assert leased.lease_id is not None
    assert retry.queue_status == LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED
    assert retry.last_error_type == "metadata-worker-retry-test"
    assert retry.restore_evidence_hash == "sha256:" + "7" * 64
    assert retry.evidence_hash == build_legacy_sql_metadata_worker_queue_job_hash(retry)
    assert not store.list_jobs(tenant_id=f"{schedule.tenant_id}-other")

    payload = retry.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_metadata_worker_queue_jsonl_replays_latest_state(tmp_path: Path) -> None:
    schedule = build_schedule(tmp_path=tmp_path / "schedule")
    path = tmp_path / "queue.jsonl"
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash="sha256:" + "8" * 64,
        enqueued_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )
    store = JsonlLegacySqlMetadataWorkerQueueStore(path=path)
    store.enqueue(queued)
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner="jsonl-queue-test",
        now=datetime(2026, 6, 18, 10, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    retry = store.record_retry(
        tenant_id=schedule.tenant_id,
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id or "",
        error_type="jsonl-retry",
        next_attempt_after_utc=datetime(2026, 6, 18, 10, 5, tzinfo=UTC),
        now=datetime(2026, 6, 18, 10, 0, 2, tzinfo=UTC),
    )

    reloaded = JsonlLegacySqlMetadataWorkerQueueStore(path=path)
    assert (
        reloaded.get(
            tenant_id=schedule.tenant_id,
            worker_idempotency_key_hash=queued.worker_idempotency_key_hash,
        )
        == retry
    )


def test_pg_legacy_sql_metadata_worker_queue_drill_persists_tenant_safe_retry_state(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_queue_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_metadata_worker_queue_operations_from_env(env)

    assert report.schema_version == "legacy_sql_metadata_worker_queue_operations_report.v1"
    assert report.queue_backend == "postgres"
    assert report.queue_operational
    assert report.duplicate_enqueue_idempotent
    assert report.tenant_isolation_ok
    assert report.restore_hash_bound
    assert report.blocked_gate_not_enqueued
    assert report.metadata_only_ok
    assert report.queue_status_after_enqueue == LegacySqlMetadataWorkerQueueStatus.QUEUED
    assert report.queue_status_after_lease == LegacySqlMetadataWorkerQueueStatus.LEASED
    assert report.queue_status_after_retry == LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED
    assert report.evidence_hash == build_legacy_sql_metadata_worker_queue_operations_report_hash(report)
    assert exit_code_for_report(report) == 0

    store = PgLegacySqlMetadataWorkerQueueStore(database_dsn=live_database.worker_dsn)
    persisted = store.get(
        tenant_id=report.tenant_id,
        worker_idempotency_key_hash=report.worker_idempotency_key_hash,
    )
    assert persisted.queue_status == LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED
    assert persisted.restore_evidence_hash == report.restore_evidence_hash
    with pytest.raises(KeyError, match="not found"):
        store.get(
            tenant_id=f"{report.tenant_id}-other",
            worker_idempotency_key_hash=report.worker_idempotency_key_hash,
        )

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_metadata_worker_queue_migration_declares_rls_and_metadata_only_updates() -> None:
    migration = get_migration("0036")
    sql = normalized(migration.sql())

    assert migration.module_id == "crm_erp"
    assert "create table if not exists collabio.legacy_sql_metadata_worker_queue" in sql
    assert "legacy_sql_metadata_worker_queue_job.v1" in sql
    assert "legacy_sql_host_profile_adapter_schedule.v1" in sql
    assert "worker_idempotency_key_hash text not null" in sql
    assert (
        "queue_status text not null check (queue_status in ('queued', 'leased', 'retry_scheduled', 'blocked'))" in sql
    )
    assert "restore_evidence_hash text not null" in sql
    assert "not (schedule_evidence ? 'connection_secret_ref')" in sql
    assert "not (job_evidence -> 'schedule_evidence' ? 'connection_secret_ref')" in sql
    assert "network_connection_opened boolean not null default false check (network_connection_opened = false)" in sql
    assert "real_connection_opened boolean not null default false check (real_connection_opened = false)" in sql
    assert "import_write_allowed boolean not null default false check (import_write_allowed = false)" in sql
    assert "alter table collabio.legacy_sql_metadata_worker_queue enable row level security" in sql
    assert "alter table collabio.legacy_sql_metadata_worker_queue force row level security" in sql
    assert "create policy legacy_sql_metadata_worker_queue_tenant_select" in sql
    assert "create policy legacy_sql_metadata_worker_queue_tenant_insert" in sql
    assert "create policy legacy_sql_metadata_worker_queue_tenant_lease_retry_update" in sql
    assert "create policy legacy_sql_metadata_worker_queue_no_hard_delete" in sql
    assert "grant select, insert on table collabio.legacy_sql_metadata_worker_queue to collabio_worker" in sql
    assert "grant update (" in sql
    assert "job_evidence" in sql
    assert "dsns, raw sql rows, sample values, table data, secret references" in sql


def build_schedule(*, tmp_path: Path) -> LegacySqlHostProfileAdapterScheduleEvidence:
    del tmp_path
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    gate = ready_gate(policy=policy, policy_hash=policy_hash)
    adapter = LegacySqlHostProfileAdapter(gate_store=InMemoryLegacySqlHostProfileReleaseGateEvidenceStore((gate,)))
    return adapter.prepare_metadata_worker_schedule(
        request=LegacySqlHostProfileAdapterScheduleRequest(
            tenant_id=gate.tenant_id,
            source_system_ref="legacy-sql:production-sqlserver",
            host_profile_ref=gate.host_profile_ref,
            connector_policy_ref=gate.connector_policy_ref,
            policy_snapshot_hash=policy_hash,
            approved_egress_ref=gate.approved_egress_ref,
            connection_secret_ref="secret:legacy-sql-production-metadata",
            connection_fingerprint_hash=gate.connection_fingerprint_hash,
            release_gate_evidence_hash=gate.evidence_hash,
            requested_by="queue-test",
            approval_reference="approval:legacy-sql-metadata-worker-queue-test",
            audit_chain_ref="audit:legacy-sql-metadata-worker-queue-test",
        ),
        checked_at_utc=datetime(2026, 6, 18, 8, tzinfo=UTC),
    )


def ready_gate(
    *,
    policy: LegacySqlServerConnectorPolicy,
    policy_hash: str,
) -> LegacySqlHostProfileReleaseGateEvidence:
    host_profile = LegacySqlApprovedHostProfile(
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        connector_policy_ref="policy:legacy-sql-connector",
        policy_snapshot_hash=policy_hash,
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref="secret:legacy-sql-production-metadata",
        connection_fingerprint_hash="sha256:legacy-sql-production-fingerprint",
        row_count_estimates_allowed=True,
    )
    ledger_report = legacy_sql_operations_report()
    return build_legacy_sql_host_profile_release_gate(
        command=LegacySqlHostProfileReleaseGateCommand(
            tenant_id="tenant-legacy-sql-metadata-worker-queue-test",
            source_system_ref="legacy-sql:production-sqlserver",
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            host_profile_ref=host_profile.host_profile_ref,
            connector_policy_ref=host_profile.connector_policy_ref,
            policy_snapshot_hash=policy_hash,
            approved_egress_ref=host_profile.approved_egress_ref,
            connection_secret_ref=host_profile.connection_secret_ref,
            connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
            ledger_operations_report_hash=ledger_report.evidence_hash,
            requested_by="queue-test",
            human_confirmation_reference="human-confirmation:legacy-sql-metadata-worker-queue-test",
            human_confirmation=True,
        ),
        host_profile=host_profile,
        connector_policy=policy,
        ledger_operations_report=ledger_report,
        evaluated_at_utc=datetime(2026, 6, 18, 7, tzinfo=UTC),
    )


def legacy_sql_operations_report() -> LegacySqlEvidenceLedgerOperationsReport:
    checked_at = datetime(2026, 6, 18, 6, tzinfo=UTC)
    backend_result = LegacySqlEvidenceLedgerBackendDrillResult(
        backend=LegacySqlEvidenceLedgerBackend.POSTGRES,
        tenant_id="tenant-legacy-sql-metadata-worker-queue-test",
        ledger_entry_count=2,
        ledger_entry_hashes=("sha256:" + "1" * 64,),
        evidence_types=(),
        restore_evidence_hashes=("sha256:" + "2" * 64,),
        intake_report_hash="sha256:" + "3" * 64,
        readiness_smoke_report_hash="sha256:" + "4" * 64,
        write_path_ok=True,
        restore_hash_bound=True,
        related_evidence_hashes_recovered=True,
        tenant_isolation_ok=True,
        duplicate_append_rejected=True,
        metadata_only_ok=True,
        host_profile_release_precondition_ok=True,
        blocking_reasons=(),
    )
    draft = LegacySqlEvidenceLedgerOperationsReport(
        run_id="legacy-sql-metadata-worker-queue-test",
        checked_by="queue-test",
        checked_at_utc=checked_at,
        selected_backends=(LegacySqlEvidenceLedgerBackend.POSTGRES,),
        backend_results=(backend_result,),
        ready_count=1,
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=(),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id="legacy-sql-metadata-worker-queue-test",
            checked_by="queue-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def postgres_queue_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "6" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "7" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower())
