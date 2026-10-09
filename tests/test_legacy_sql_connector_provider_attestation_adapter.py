from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_provider_attestation_adapter import (
    LegacySqlConnectorProviderAttestationAdapter,
    LegacySqlConnectorProviderAttestationAdapterStatus,
    build_legacy_sql_connector_audit_deployment_profile,
    build_legacy_sql_connector_audit_deployment_profile_hash,
    build_legacy_sql_connector_network_deployment_profile,
    build_legacy_sql_connector_network_deployment_profile_hash,
    build_legacy_sql_connector_provider_attestation_adapter_command,
    build_legacy_sql_connector_provider_attestation_adapter_hash,
    build_legacy_sql_connector_provider_attestation_adapter_smoke_report_hash,
    build_legacy_sql_connector_secret_resolver_deployment_profile,
    build_legacy_sql_connector_secret_resolver_deployment_profile_hash,
    exit_code_for_report,
    run_legacy_sql_connector_provider_attestation_adapter_smoke_from_env,
)
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    LegacySqlConnectorSandboxEnablementGateStatus,
    build_legacy_sql_connector_sandbox_enablement_command,
    build_legacy_sql_connector_sandbox_enablement_gate,
)
from suite.platform.legacy_sql_connector_sandbox_profile import (
    LegacySqlConnectorSandboxProfileEvidence,
    build_legacy_sql_connector_sandbox_profile,
)
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_lease_consumer import (
    LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    LegacySqlMetadataWorkerLeaseConsumerValidationStatus,
    build_legacy_sql_lease_consumer_activation_hash,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

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


def test_legacy_sql_connector_provider_attestation_adapter_validates_deployment_profiles() -> None:
    profile = sandbox_profile()
    checked_at = datetime(2026, 6, 18, 12, tzinfo=UTC)
    network_profile = build_legacy_sql_connector_network_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at,
    )
    secret_resolver_profile = build_legacy_sql_connector_secret_resolver_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    audit_profile = build_legacy_sql_connector_audit_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by="provider-attestation-test",
    )

    result = LegacySqlConnectorProviderAttestationAdapter().validate_provider_profiles(
        command=command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )

    evidence = result.adapter_evidence
    assert evidence.schema_version == "legacy_sql_connector_provider_attestation_adapter.v1"
    assert evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.READY
    assert evidence.sandbox_profile_hash_valid
    assert evidence.sandbox_profile_default_off
    assert evidence.sandbox_profile_visible
    assert evidence.network_profile_hash_valid
    assert evidence.secret_resolver_profile_hash_valid
    assert evidence.audit_profile_hash_valid
    assert evidence.network_profile_bound
    assert evidence.secret_resolver_profile_bound
    assert evidence.audit_profile_bound
    assert evidence.provider_metadata_only_boundary_attested
    assert evidence.provider_attestation_ready
    assert not evidence.network_connection_opened
    assert not evidence.real_connection_opened
    assert not evidence.secret_material_resolved
    assert not evidence.raw_data_access_allowed
    assert not evidence.import_dry_run_allowed
    assert not evidence.import_write_allowed
    assert not evidence.destructive_actions_allowed
    assert network_profile.evidence_hash == build_legacy_sql_connector_network_deployment_profile_hash(network_profile)
    assert secret_resolver_profile.evidence_hash == build_legacy_sql_connector_secret_resolver_deployment_profile_hash(
        secret_resolver_profile
    )
    assert audit_profile.evidence_hash == build_legacy_sql_connector_audit_deployment_profile_hash(audit_profile)
    assert evidence.evidence_hash == build_legacy_sql_connector_provider_attestation_adapter_hash(evidence)

    enablement_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=result.provider_attestation,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="provider-attestation-test",
        human_confirmation_reference="human-confirmation:legacy-sql-provider-attestation-test",
    )
    enablement_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=enablement_command,
        profile=profile,
        provider_attestation=result.provider_attestation,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    assert enablement_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.READY
    assert enablement_gate.provider_attestation_hash_valid
    assert enablement_gate.connection_attempt_preparation_allowed
    assert not enablement_gate.connection_materialization_allowed
    assert not enablement_gate.secret_material_resolution_allowed

    payload = evidence.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_connector_provider_attestation_adapter_blocks_mismatch_and_secret_request() -> None:
    profile = sandbox_profile()
    checked_at = datetime(2026, 6, 18, 12, tzinfo=UTC)
    network_profile = build_legacy_sql_connector_network_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at,
    )
    secret_resolver_profile = build_legacy_sql_connector_secret_resolver_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    audit_profile = build_legacy_sql_connector_audit_deployment_profile(
        profile=profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by="provider-attestation-test",
    )
    adapter = LegacySqlConnectorProviderAttestationAdapter()

    mismatched_network = network_profile.model_copy(
        update={"connector_network_profile_ref": "network-profile:legacy-sql-wrong", "evidence_hash": ZERO_HASH}
    )
    mismatched_network = mismatched_network.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_network_deployment_profile_hash(mismatched_network)}
    )
    network_mismatch = adapter.validate_provider_profiles(
        command=command.model_copy(update={"network_profile_evidence_hash": mismatched_network.evidence_hash}),
        profile=profile,
        network_profile=mismatched_network,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert (
        network_mismatch.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
    )
    assert "network_profile_not_bound" in network_mismatch.adapter_evidence.blocking_reasons
    assert not network_mismatch.adapter_evidence.provider_attestation_ready

    secret_request = adapter.validate_provider_profiles(
        command=command.model_copy(update={"secret_material_resolution_requested": True}),
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    assert secret_request.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
    assert "secret_material_resolution_request_requires_real_connection_gate" in (
        secret_request.adapter_evidence.blocking_reasons
    )
    assert not secret_request.adapter_evidence.secret_material_resolved

    tampered_profile = profile.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    tampered = adapter.validate_provider_profiles(
        command=command,
        profile=tampered_profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    assert tampered.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
    assert "sandbox_profile_hash_invalid" in tampered.adapter_evidence.blocking_reasons


def test_pg_legacy_sql_connector_provider_attestation_adapter_smoke_keeps_providers_metadata_only(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_provider_adapter_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_connector_provider_attestation_adapter_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_provider_attestation_adapter_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.adapter_ready
    assert report.downstream_enablement_gate_ready
    assert report.network_profile_mismatch_blocked
    assert report.secret_material_request_blocked
    assert report.tampered_sandbox_profile_blocked
    assert report.provider_metadata_only_boundary_attested
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_provider_attestation_adapter_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def sandbox_profile() -> LegacySqlConnectorSandboxProfileEvidence:
    return build_legacy_sql_connector_sandbox_profile(
        activation=validated_activation(),
        checked_by="provider-attestation-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )


def validated_activation() -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
    checked_at = datetime(2026, 6, 18, 9, tzinfo=UTC)
    draft = LegacySqlMetadataWorkerLeaseConsumerActivationEvidence(
        tenant_id="tenant-legacy-sql-provider-attestation-test",
        module_id="crm_erp",
        source_system_ref="legacy-sql:production-sqlserver",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        worker_queue_ref="worker-queue:legacy-sql-metadata-discovery",
        worker_job_ref="legacy-sql-metadata-worker-job:provider-attestation-test",
        worker_idempotency_key_hash="sha256:" + "1" * 64,
        queue_job_evidence_hash="sha256:" + "2" * 64,
        schedule_evidence_hash="sha256:" + "3" * 64,
        schedule_evidence_ref="legacy-sql-host-profile-adapter-schedule:provider-attestation-test",
        release_gate_evidence_hash="sha256:" + "4" * 64,
        metadata_worker_command_hash="sha256:" + "5" * 64,
        metadata_worker_command_view_hash="sha256:" + "6" * 64,
        metadata_worker_profile_ref="worker-profile:legacy-sql-metadata-only",
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref_hash="sha256:" + "7" * 64,
        connection_fingerprint_hash="fingerprint:legacy-sql-production",
        worker_network_mode=LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY,
        lease_id="lease:provider-attestation-test",
        lease_owner="provider-attestation-test",
        leased_until_utc=checked_at + timedelta(minutes=5),
        restore_evidence_hash="sha256:" + "8" * 64,
        queue_job_hash_valid=True,
        schedule_evidence_hash_valid=True,
        command_hash_verified=True,
        lease_state_verified=True,
        lease_not_expired=True,
        egress_handle_verified=True,
        secret_handle_hash_verified=True,
        fingerprint_handle_verified=True,
        network_mode_verified=True,
        validation_status=LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED,
        blocking_reasons=(),
        checked_by="provider-attestation-test",
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(draft)})


def postgres_provider_adapter_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
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
        "SUITE_LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_RESTORE_HASH": "sha256:" + "e" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }
