from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    LegacySqlConnectorSandboxEnablementGateStatus,
    build_legacy_sql_connector_sandbox_enablement_command,
    build_legacy_sql_connector_sandbox_enablement_gate,
    build_legacy_sql_connector_sandbox_enablement_gate_hash,
    build_legacy_sql_connector_sandbox_enablement_gate_smoke_report_hash,
    build_legacy_sql_connector_sandbox_provider_attestation,
    build_legacy_sql_connector_sandbox_provider_attestation_hash,
    exit_code_for_report,
    run_legacy_sql_connector_sandbox_enablement_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_sandbox_profile import (
    LegacySqlConnectorSandboxProfileEvidence,
    build_legacy_sql_connector_sandbox_profile,
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


def test_legacy_sql_connector_sandbox_enablement_gate_allows_only_preparation() -> None:
    profile = validated_profile()
    provider_attestation = build_legacy_sql_connector_sandbox_provider_attestation(
        profile=profile,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, tzinfo=UTC),
    )
    command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_attestation,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="sandbox-enablement-test",
        human_confirmation_reference="human-confirmation:legacy-sql-connector-sandbox-enablement-test",
    )

    gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=command,
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, 0, 1, tzinfo=UTC),
    )

    assert gate.schema_version == "legacy_sql_connector_sandbox_enablement_gate.v1"
    assert gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.READY
    assert gate.sandbox_profile_hash_valid
    assert gate.sandbox_profile_default_off
    assert gate.sandbox_profile_visible
    assert gate.sandbox_profile_enablement_allowed
    assert gate.provider_attestation_hash_valid
    assert gate.provider_attestation_bound
    assert gate.provider_metadata_only_boundary_attested
    assert gate.network_profile_attested
    assert gate.secret_resolver_attested
    assert gate.audit_profile_attested
    assert gate.restore_evidence_hash_valid
    assert gate.human_confirmation_verified
    assert gate.connection_attempt_preparation_allowed
    assert gate.future_real_connection_gate_required
    assert not gate.connection_materialization_allowed
    assert not gate.secret_material_resolution_allowed
    assert not gate.egress_connection_materialized
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert provider_attestation.evidence_hash == build_legacy_sql_connector_sandbox_provider_attestation_hash(
        provider_attestation
    )
    assert gate.evidence_hash == build_legacy_sql_connector_sandbox_enablement_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_connector_sandbox_enablement_gate_blocks_missing_human_import_and_tamper() -> None:
    profile = validated_profile()
    provider_attestation = build_legacy_sql_connector_sandbox_provider_attestation(
        profile=profile,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, tzinfo=UTC),
    )
    command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_attestation,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="sandbox-enablement-test",
        human_confirmation_reference="human-confirmation:legacy-sql-connector-sandbox-enablement-test",
    )

    missing_human = build_legacy_sql_connector_sandbox_enablement_gate(
        command=command.model_copy(update={"human_confirmation": False}),
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, 0, 1, tzinfo=UTC),
    )
    assert missing_human.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
    assert "explicit_human_confirmation_missing" in missing_human.blocking_reasons
    assert not missing_human.connection_attempt_preparation_allowed

    unsafe_import = build_legacy_sql_connector_sandbox_enablement_gate(
        command=command.model_copy(update={"import_dry_run_requested": True}),
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, 0, 2, tzinfo=UTC),
    )
    assert unsafe_import.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
    assert "import_dry_run_request_requires_separate_gate" in unsafe_import.blocking_reasons
    assert not unsafe_import.import_dry_run_allowed

    tampered_profile = profile.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    tampered_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=command,
        profile=tampered_profile,
        provider_attestation=provider_attestation,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, 0, 3, tzinfo=UTC),
    )
    assert tampered_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
    assert "sandbox_profile_hash_invalid" in tampered_gate.blocking_reasons
    assert "provider_attestation_profile_hash_mismatch" in tampered_gate.blocking_reasons

    untrusted_provider = provider_attestation.model_copy(
        update={
            "provider_metadata_only_boundary_attested": False,
            "evidence_hash": ZERO_HASH,
        }
    )
    untrusted_provider = untrusted_provider.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_sandbox_provider_attestation_hash(untrusted_provider)}
    )
    untrusted_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=untrusted_provider,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="sandbox-enablement-test",
        human_confirmation_reference="human-confirmation:legacy-sql-connector-sandbox-enablement-test",
    )
    untrusted_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=untrusted_command,
        profile=profile,
        provider_attestation=untrusted_provider,
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 11, 0, 4, tzinfo=UTC),
    )
    assert untrusted_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
    assert "provider_metadata_only_boundary_not_attested" in untrusted_gate.blocking_reasons


def test_pg_legacy_sql_connector_sandbox_enablement_gate_smoke_keeps_imports_blocked(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_enablement_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_connector_sandbox_enablement_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_sandbox_enablement_gate_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.enablement_gate_ready
    assert report.ready_gate_created
    assert report.explicit_human_confirmation_required
    assert report.provider_attestation_required
    assert report.restore_evidence_required
    assert report.sandbox_profile_hash_required
    assert report.missing_human_confirmation_blocked
    assert report.unsafe_import_request_blocked
    assert report.tampered_profile_hash_blocked
    assert report.connection_attempt_preparation_allowed
    assert report.sandbox_profile_enablement_allowed
    assert report.future_real_connection_gate_required
    assert not report.connection_materialization_allowed
    assert not report.secret_material_resolution_allowed
    assert not report.egress_connection_materialized
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_sandbox_enablement_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def validated_profile() -> LegacySqlConnectorSandboxProfileEvidence:
    return build_legacy_sql_connector_sandbox_profile(
        activation=validated_activation(),
        checked_by="sandbox-enablement-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )


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
        lease_owner="sandbox-enablement-test",
        lease_duration_seconds=60,
        now=datetime(2026, 6, 18, 9, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    return LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by="sandbox-enablement-test",
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
            requested_by="sandbox-enablement-test",
            approval_reference="approval:legacy-sql-connector-sandbox-enablement-test",
            audit_chain_ref="audit:legacy-sql-connector-sandbox-enablement-test",
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
            tenant_id="tenant-legacy-sql-connector-sandbox-enablement-test",
            source_system_ref="legacy-sql:production-sqlserver",
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            host_profile_ref=host_profile.host_profile_ref,
            connector_policy_ref=host_profile.connector_policy_ref,
            policy_snapshot_hash=policy_hash,
            approved_egress_ref=host_profile.approved_egress_ref,
            connection_secret_ref=host_profile.connection_secret_ref,
            connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
            ledger_operations_report_hash=ledger_report.evidence_hash,
            requested_by="sandbox-enablement-test",
            human_confirmation_reference="human-confirmation:legacy-sql-connector-sandbox-enablement-test",
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
        tenant_id="tenant-legacy-sql-connector-sandbox-enablement-test",
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
        run_id="legacy-sql-connector-sandbox-enablement-test",
        checked_by="sandbox-enablement-test",
        checked_at_utc=checked_at,
        selected_backends=(LegacySqlEvidenceLedgerBackend.POSTGRES,),
        backend_results=(backend_result,),
        ready_count=1,
        failed_count=0,
        alert_required=False,
        legacy_host_profile_release_gate_passed=True,
        recommended_actions=(),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id="legacy-sql-connector-sandbox-enablement-test",
            checked_by="sandbox-enablement-test",
            checked_at_utc=checked_at,
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def postgres_enablement_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "c" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_dsn,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "d" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_RESTORE_HASH": "sha256:" + "e" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }
