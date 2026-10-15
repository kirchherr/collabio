from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
from suite.platform.legacy_sql_metadata_worker_lease_consumer import (
    LegacySqlMetadataWorkerLeaseConsumer,
    LegacySqlMetadataWorkerLeaseConsumerValidationStatus,
    build_legacy_sql_lease_consumer_activation_hash,
    build_legacy_sql_lease_consumer_smoke_report_hash,
    exit_code_for_report,
    run_legacy_sql_metadata_worker_lease_consumer_smoke_from_env,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    InMemoryLegacySqlMetadataWorkerQueueStore,
    LegacySqlMetadataWorkerQueueJob,
    build_legacy_sql_metadata_worker_queue_job,
    build_legacy_sql_metadata_worker_queue_job_hash,
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


def test_legacy_sql_metadata_worker_lease_consumer_validates_only_leased_offline_job() -> None:
    leased = leased_queue_job()
    evidence = LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by="lease-consumer-test",
        checked_at_utc=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )

    assert evidence.schema_version == "legacy_sql_metadata_worker_lease_consumer_activation.v1"
    assert evidence.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED
    assert evidence.queue_job_hash_valid
    assert evidence.schedule_evidence_hash_valid
    assert evidence.command_hash_verified
    assert evidence.lease_state_verified
    assert evidence.lease_not_expired
    assert evidence.egress_handle_verified
    assert evidence.secret_handle_hash_verified
    assert evidence.fingerprint_handle_verified
    assert evidence.network_mode_verified
    assert evidence.offline_runner_only
    assert not evidence.secret_material_resolved
    assert not evidence.egress_connection_materialized
    assert not evidence.network_connection_opened
    assert not evidence.real_connection_opened
    assert not evidence.raw_data_access_allowed
    assert not evidence.import_dry_run_allowed
    assert not evidence.import_write_allowed
    assert not evidence.destructive_actions_allowed
    assert evidence.evidence_hash == build_legacy_sql_lease_consumer_activation_hash(evidence)

    payload = evidence.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_metadata_worker_lease_consumer_blocks_queued_expired_or_unsafe_jobs() -> None:
    schedule = build_schedule()
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash="sha256:" + "7" * 64,
        enqueued_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )
    consumer = LegacySqlMetadataWorkerLeaseConsumer()

    queued_evidence = consumer.validate_leased_job(
        job=queued,
        checked_by="lease-consumer-test",
        checked_at_utc=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )
    assert queued_evidence.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
    assert "queue_job_not_leased" in queued_evidence.blocking_reasons

    leased = leased_queue_job()
    expired = queue_job_with_hash(
        leased.model_copy(
            update={
                "leased_until_utc": datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
                "next_attempt_after_utc": datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
                "updated_at_utc": datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
                "evidence_hash": ZERO_HASH,
            }
        )
    )
    expired_evidence = consumer.validate_leased_job(
        job=expired,
        checked_by="lease-consumer-test",
        checked_at_utc=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )
    assert expired_evidence.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
    assert "queue_job_lease_expired" in expired_evidence.blocking_reasons

    unsafe = queue_job_with_hash(
        leased.model_copy(update={"network_connection_opened": True, "evidence_hash": ZERO_HASH})
    )
    unsafe_evidence = consumer.validate_leased_job(
        job=unsafe,
        checked_by="lease-consumer-test",
        checked_at_utc=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )
    assert unsafe_evidence.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
    assert "metadata_only_boundary_broken" in unsafe_evidence.blocking_reasons


def test_pg_legacy_sql_metadata_worker_lease_consumer_smoke_keeps_handles_offline(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_consumer_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_metadata_worker_lease_consumer_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_metadata_worker_lease_consumer_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.lease_consumer_ready
    assert report.queued_job_rejected
    assert report.expired_lease_rejected
    assert report.egress_handle_verified
    assert report.secret_handle_hash_verified
    assert report.fingerprint_handle_verified
    assert report.offline_runner_only
    assert not report.default_compose_legacy_network_enabled
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_lease_consumer_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def leased_queue_job() -> LegacySqlMetadataWorkerQueueJob:
    schedule = build_schedule()
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash="sha256:" + "7" * 64,
        enqueued_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )
    store = InMemoryLegacySqlMetadataWorkerQueueStore((queued,))
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner="lease-consumer-test",
        lease_duration_seconds=60,
        now=datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    return leased


def queue_job_with_hash(job: LegacySqlMetadataWorkerQueueJob) -> LegacySqlMetadataWorkerQueueJob:
    return job.model_copy(update={"evidence_hash": build_legacy_sql_metadata_worker_queue_job_hash(job)})


def build_schedule() -> LegacySqlHostProfileAdapterScheduleEvidence:
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
            requested_by="lease-consumer-test",
            approval_reference="approval:legacy-sql-metadata-worker-lease-consumer-test",
            audit_chain_ref="audit:legacy-sql-metadata-worker-lease-consumer-test",
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
            tenant_id="tenant-legacy-sql-metadata-worker-lease-consumer-test",
            source_system_ref="legacy-sql:production-sqlserver",
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            host_profile_ref=host_profile.host_profile_ref,
            connector_policy_ref=host_profile.connector_policy_ref,
            policy_snapshot_hash=policy_hash,
            approved_egress_ref=host_profile.approved_egress_ref,
            connection_secret_ref=host_profile.connection_secret_ref,
            connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
            ledger_operations_report_hash=ledger_report.evidence_hash,
            requested_by="lease-consumer-test",
            human_confirmation_reference="human-confirmation:legacy-sql-metadata-worker-lease-consumer-test",
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
        tenant_id="tenant-legacy-sql-metadata-worker-lease-consumer-test",
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
        run_id="legacy-sql-metadata-worker-lease-consumer-test",
        checked_by="lease-consumer-test",
        checked_at_utc=checked_at,
        selected_backends=(LegacySqlEvidenceLedgerBackend.POSTGRES,),
        backend_results=(backend_result,),
        ready_count=1,
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=(),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id="legacy-sql-metadata-worker-lease-consumer-test",
            checked_by="lease-consumer-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def postgres_consumer_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "8" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "9" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }
