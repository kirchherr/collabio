from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_connection_preflight_gate import (
    LegacySqlConnectorConnectionPreflightStatus,
    LegacySqlConnectorOperatorContext,
    build_legacy_sql_connector_connection_preflight_command,
    build_legacy_sql_connector_connection_preflight_gate,
    build_legacy_sql_connector_connection_preflight_hash,
    build_legacy_sql_connector_connection_preflight_smoke_report_hash,
    build_legacy_sql_connector_operator_context,
    build_legacy_sql_connector_operator_context_hash,
    exit_code_for_report,
    run_legacy_sql_connector_connection_preflight_smoke_from_env,
)
from suite.platform.legacy_sql_connector_provider_attestation_adapter import (
    LegacySqlConnectorProviderAttestationAdapter,
    LegacySqlConnectorProviderAttestationAdapterEvidence,
    build_legacy_sql_connector_audit_deployment_profile,
    build_legacy_sql_connector_network_deployment_profile,
    build_legacy_sql_connector_provider_attestation_adapter_command,
    build_legacy_sql_connector_secret_resolver_deployment_profile,
)
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    LegacySqlConnectorSandboxEnablementGateEvidence,
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


@dataclass(frozen=True)
class PreflightFixture:
    profile: LegacySqlConnectorSandboxProfileEvidence
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence
    operator_context: LegacySqlConnectorOperatorContext


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


def test_legacy_sql_connector_connection_preflight_gate_binds_final_no_socket_chain() -> None:
    fixture = preflight_fixture()
    command = build_legacy_sql_connector_connection_preflight_command(
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        restore_evidence_hash="sha256:" + "9" * 64,
        requested_by="connection-preflight-test",
    )

    preflight = build_legacy_sql_connector_connection_preflight_gate(
        command=command,
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 0, 1, tzinfo=UTC),
    )

    assert preflight.schema_version == "legacy_sql_connector_connection_attempt_preflight_gate.v1"
    assert preflight.gate_status == LegacySqlConnectorConnectionPreflightStatus.READY
    assert preflight.sandbox_profile_hash_valid
    assert preflight.sandbox_profile_default_off
    assert preflight.sandbox_profile_visible
    assert preflight.enablement_gate_hash_valid
    assert preflight.enablement_gate_ready
    assert preflight.enablement_gate_bound
    assert preflight.provider_adapter_hash_valid
    assert preflight.provider_adapter_ready
    assert preflight.provider_adapter_bound
    assert preflight.operator_context_hash_valid
    assert preflight.operator_context_bound
    assert preflight.operator_authorized_for_legacy_sql
    assert preflight.operator_mfa_verified
    assert preflight.compliance_window_active
    assert not preflight.break_glass_requested
    assert preflight.restore_evidence_hash_valid
    assert preflight.evidence_chain_bound
    assert preflight.connection_attempt_preflight_ready
    assert preflight.future_real_connection_executor_required
    assert not preflight.network_socket_opened
    assert not preflight.network_connection_opened
    assert not preflight.real_connection_opened
    assert not preflight.secret_material_resolved
    assert not preflight.raw_data_access_allowed
    assert not preflight.import_dry_run_allowed
    assert not preflight.import_write_allowed
    assert not preflight.destructive_actions_allowed
    assert fixture.operator_context.evidence_hash == build_legacy_sql_connector_operator_context_hash(
        fixture.operator_context
    )
    assert preflight.evidence_hash == build_legacy_sql_connector_connection_preflight_hash(preflight)

    payload = preflight.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_connector_connection_preflight_gate_blocks_operator_secret_and_tamper() -> None:
    fixture = preflight_fixture()
    command = build_legacy_sql_connector_connection_preflight_command(
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        restore_evidence_hash="sha256:" + "9" * 64,
        requested_by="connection-preflight-test",
    )

    operator_without_mfa = fixture.operator_context.model_copy(
        update={"operator_mfa_verified": False, "evidence_hash": ZERO_HASH}
    )
    operator_without_mfa = operator_without_mfa.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_operator_context_hash(operator_without_mfa)}
    )
    missing_mfa = build_legacy_sql_connector_connection_preflight_gate(
        command=command.model_copy(update={"operator_context_evidence_hash": operator_without_mfa.evidence_hash}),
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=operator_without_mfa,
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 0, 2, tzinfo=UTC),
    )
    assert missing_mfa.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
    assert "operator_mfa_not_verified" in missing_mfa.blocking_reasons
    assert not missing_mfa.connection_attempt_preflight_ready

    secret_request = build_legacy_sql_connector_connection_preflight_gate(
        command=command.model_copy(update={"secret_material_resolution_requested": True}),
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 0, 3, tzinfo=UTC),
    )
    assert secret_request.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
    assert "secret_material_resolution_request_requires_future_executor" in secret_request.blocking_reasons
    assert not secret_request.secret_material_resolved

    socket_request = build_legacy_sql_connector_connection_preflight_gate(
        command=command.model_copy(update={"network_socket_open_requested": True}),
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 0, 4, tzinfo=UTC),
    )
    assert socket_request.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
    assert "network_socket_request_requires_future_executor" in socket_request.blocking_reasons
    assert not socket_request.network_socket_opened

    tampered_gate = fixture.enablement_gate.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    tampered = build_legacy_sql_connector_connection_preflight_gate(
        command=command,
        profile=fixture.profile,
        enablement_gate=tampered_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 0, 5, tzinfo=UTC),
    )
    assert tampered.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
    assert "enablement_gate_hash_invalid" in tampered.blocking_reasons


def test_pg_legacy_sql_connector_connection_preflight_smoke_stays_no_secret_no_socket(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_preflight_env(tmp_path=tmp_path, worker_dsn=live_database.worker_dsn)

    report = run_legacy_sql_connector_connection_preflight_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_connection_attempt_preflight_gate_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.preflight_ready
    assert report.enablement_gate_required
    assert report.provider_adapter_required
    assert report.operator_context_required
    assert report.restore_evidence_required
    assert report.operator_mfa_missing_blocked
    assert report.secret_material_request_blocked
    assert report.tampered_enablement_gate_blocked
    assert report.future_real_connection_executor_required
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_connection_preflight_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def preflight_fixture() -> PreflightFixture:
    profile = sandbox_profile()
    checked_at = datetime(2026, 6, 18, 13, tzinfo=UTC)
    network_profile = build_legacy_sql_connector_network_deployment_profile(
        profile=profile,
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at,
    )
    secret_resolver_profile = build_legacy_sql_connector_secret_resolver_deployment_profile(
        profile=profile,
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    audit_profile = build_legacy_sql_connector_audit_deployment_profile(
        profile=profile,
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    provider_command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by="connection-preflight-test",
    )
    provider_result = LegacySqlConnectorProviderAttestationAdapter().validate_provider_profiles(
        command=provider_command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    enablement_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="connection-preflight-test",
        human_confirmation_reference="human-confirmation:legacy-sql-connection-preflight-test",
    )
    enablement_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=enablement_command,
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    operator_context = build_legacy_sql_connector_operator_context(
        profile=profile,
        operator_principal_ref="principal:legacy-sql-operator",
        change_request_ref="change-request:legacy-sql-connection-preflight-test",
        maintenance_window_ref="maintenance-window:legacy-sql-connection-preflight-test",
        approval_reference="approval:legacy-sql-connection-preflight-test",
        audit_chain_ref="audit:legacy-sql-connection-preflight-test",
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    return PreflightFixture(
        profile=profile,
        provider_adapter_evidence=provider_result.adapter_evidence,
        enablement_gate=enablement_gate,
        operator_context=operator_context,
    )


def sandbox_profile() -> LegacySqlConnectorSandboxProfileEvidence:
    return build_legacy_sql_connector_sandbox_profile(
        activation=validated_activation(),
        checked_by="connection-preflight-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )


def validated_activation() -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
    checked_at = datetime(2026, 6, 18, 9, tzinfo=UTC)
    draft = LegacySqlMetadataWorkerLeaseConsumerActivationEvidence(
        tenant_id="tenant-legacy-sql-connection-preflight-test",
        module_id="crm_erp",
        source_system_ref="legacy-sql:production-sqlserver",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        worker_queue_ref="worker-queue:legacy-sql-metadata-discovery",
        worker_job_ref="legacy-sql-metadata-worker-job:connection-preflight-test",
        worker_idempotency_key_hash="sha256:" + "1" * 64,
        queue_job_evidence_hash="sha256:" + "2" * 64,
        schedule_evidence_hash="sha256:" + "3" * 64,
        schedule_evidence_ref="legacy-sql-host-profile-adapter-schedule:connection-preflight-test",
        release_gate_evidence_hash="sha256:" + "4" * 64,
        metadata_worker_command_hash="sha256:" + "5" * 64,
        metadata_worker_command_view_hash="sha256:" + "6" * 64,
        metadata_worker_profile_ref="worker-profile:legacy-sql-metadata-only",
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref_hash="sha256:" + "7" * 64,
        connection_fingerprint_hash="fingerprint:legacy-sql-production",
        worker_network_mode=LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY,
        lease_id="lease:connection-preflight-test",
        lease_owner="connection-preflight-test",
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
        checked_by="connection-preflight-test",
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(draft)})


def postgres_preflight_env(*, tmp_path: Path, worker_dsn: str) -> dict[str, str]:
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
        "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_ENABLEMENT_RESTORE_HASH": "sha256:" + "e" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_RESTORE_HASH": "sha256:" + "f" * 64,
        "SUITE_DATABASE_DSN": worker_dsn,
    }
