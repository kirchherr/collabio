from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_sandbox_profile import (
    LegacySqlConnectorSandboxProfileStatus,
    build_legacy_sql_connector_sandbox_profile,
    build_legacy_sql_connector_sandbox_profile_hash,
    build_legacy_sql_connector_sandbox_profile_smoke_report_hash,
    exit_code_for_report,
    run_legacy_sql_connector_sandbox_profile_smoke_from_env,
)
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
    LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    LegacySqlMetadataWorkerLeaseConsumerValidationStatus,
    build_legacy_sql_lease_consumer_activation_hash,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    InMemoryLegacySqlMetadataWorkerQueueStore,
    build_legacy_sql_metadata_worker_queue_job,
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


def test_legacy_sql_connector_sandbox_profile_is_visible_but_default_off() -> None:
    activation = validated_activation()

    profile = build_legacy_sql_connector_sandbox_profile(
        activation=activation,
        checked_by="sandbox-profile-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )

    assert profile.schema_version == "legacy_sql_connector_sandbox_profile.v1"
    assert profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
    assert profile.consumer_activation_validated
    assert profile.sandbox_profile_visible
    assert not profile.sandbox_profile_enabled
    assert not profile.connection_materialization_allowed
    assert not profile.secret_material_resolution_allowed
    assert not profile.egress_connection_materialized
    assert not profile.default_compose_legacy_network_enabled
    assert not profile.network_connection_opened
    assert not profile.real_connection_opened
    assert not profile.raw_data_access_allowed
    assert not profile.import_dry_run_allowed
    assert not profile.import_write_allowed
    assert not profile.destructive_actions_allowed
    assert profile.connector_network_profile_ref == "network-profile:legacy-sql-approved-host-default-off"
    assert profile.secret_resolver_profile_ref == "secret-resolver:legacy-sql-handle-only-default-off"
    assert profile.evidence_hash == build_legacy_sql_connector_sandbox_profile_hash(profile)

    payload = profile.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_connector_sandbox_profile_blocks_invalid_activation_or_direct_enablement() -> None:
    activation = validated_activation()
    blocked_activation = activation.model_copy(
        update={
            "validation_status": LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED,
            "lease_not_expired": False,
            "blocking_reasons": ("queue_job_lease_expired",),
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_activation = blocked_activation.model_copy(
        update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(blocked_activation)}
    )

    blocked_profile = build_legacy_sql_connector_sandbox_profile(
        activation=blocked_activation,
        checked_by="sandbox-profile-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )
    assert blocked_profile.profile_status == LegacySqlConnectorSandboxProfileStatus.BLOCKED
    assert "consumer_activation_not_validated" in blocked_profile.blocking_reasons

    with pytest.raises(ValueError, match="default-off"):
        build_legacy_sql_connector_sandbox_profile(
            activation=activation,
            checked_by="sandbox-profile-test",
            checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
            sandbox_profile_enabled=True,
        )


def test_pg_legacy_sql_connector_sandbox_profile_smoke_keeps_connector_default_off(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_profile_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_connector_sandbox_profile_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_sandbox_profile_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.sandbox_profile_ready
    assert report.default_off_profile_created
    assert report.blocked_activation_rejected
    assert report.unsafe_enablement_rejected
    assert report.sandbox_profile_visible
    assert not report.sandbox_profile_enabled
    assert not report.connection_materialization_allowed
    assert not report.secret_material_resolution_allowed
    assert not report.egress_connection_materialized
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_sandbox_profile_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def validated_activation() -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
    schedule = build_schedule()
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash="sha256:" + "7" * 64,
        enqueued_at_utc=datetime(2026, 6, 18, 9, tzinfo=UTC),
    )
    store = InMemoryLegacySqlMetadataWorkerQueueStore((queued,))
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner="sandbox-profile-test",
        lease_duration_seconds=60,
        now=datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    return LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by="sandbox-profile-test",
        checked_at_utc=datetime(2026, 6, 18, 9, 0, 2, tzinfo=UTC),
    )


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
            requested_by="sandbox-profile-test",
            approval_reference="approval:legacy-sql-connector-sandbox-profile-test",
            audit_chain_ref="audit:legacy-sql-connector-sandbox-profile-test",
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
            tenant_id="tenant-legacy-sql-connector-sandbox-profile-test",
            source_system_ref="legacy-sql:production-sqlserver",
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            host_profile_ref=host_profile.host_profile_ref,
            connector_policy_ref=host_profile.connector_policy_ref,
            policy_snapshot_hash=policy_hash,
            approved_egress_ref=host_profile.approved_egress_ref,
            connection_secret_ref=host_profile.connection_secret_ref,
            connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
            ledger_operations_report_hash=ledger_report.evidence_hash,
            requested_by="sandbox-profile-test",
            human_confirmation_reference="human-confirmation:legacy-sql-connector-sandbox-profile-test",
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
        tenant_id="tenant-legacy-sql-connector-sandbox-profile-test",
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
        run_id="legacy-sql-connector-sandbox-profile-test",
        checked_by="sandbox-profile-test",
        checked_at_utc=checked_at,
        selected_backends=(LegacySqlEvidenceLedgerBackend.POSTGRES,),
        backend_results=(backend_result,),
        ready_count=1,
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=(),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id="legacy-sql-connector-sandbox-profile-test",
            checked_by="sandbox-profile-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def postgres_profile_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "a" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "b" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }
