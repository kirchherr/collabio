from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_connection_preflight_gate import (
    LegacySqlConnectorConnectionPreflightEvidence,
    LegacySqlConnectorOperatorContext,
    build_legacy_sql_connector_connection_preflight_command,
    build_legacy_sql_connector_connection_preflight_gate,
    build_legacy_sql_connector_operator_context,
)
from suite.platform.legacy_sql_connector_provider_attestation_adapter import (
    LegacySqlConnectorProviderAttestationAdapter,
    LegacySqlConnectorProviderAttestationAdapterEvidence,
    build_legacy_sql_connector_audit_deployment_profile,
    build_legacy_sql_connector_network_deployment_profile,
    build_legacy_sql_connector_provider_attestation_adapter_command,
    build_legacy_sql_connector_secret_resolver_deployment_profile,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    InMemoryLegacySqlConnectorRealConnectionExecutorPolicyStore,
    JsonlLegacySqlConnectorRealConnectionExecutorPolicyStore,
    LegacySqlConnectorRealConnectionExecutorStatus,
    build_legacy_sql_connector_real_connection_audit_plan,
    build_legacy_sql_connector_real_connection_audit_plan_hash,
    build_legacy_sql_connector_real_connection_executor_command,
    build_legacy_sql_connector_real_connection_executor_contract,
    build_legacy_sql_connector_real_connection_executor_contract_hash,
    build_legacy_sql_connector_real_connection_executor_policy_bundle,
    build_legacy_sql_connector_real_connection_executor_policy_bundle_hash,
    build_legacy_sql_connector_real_connection_executor_policy_store_smoke_report_hash,
    build_legacy_sql_connector_real_connection_executor_smoke_report_hash,
    build_legacy_sql_connector_real_connection_kill_switch_policy,
    build_legacy_sql_connector_real_connection_kill_switch_policy_hash,
    build_legacy_sql_connector_real_connection_timeout_retry_policy,
    build_legacy_sql_connector_real_connection_timeout_retry_policy_hash,
    exit_code_for_report,
    run_legacy_sql_connector_real_connection_executor_policy_store_smoke_from_env,
    run_legacy_sql_connector_real_connection_executor_smoke_from_env,
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
    migration_resource: str
    worker_resource: str


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
    migration_resource = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    worker_resource = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_resource)
    return LiveDatabase(migration_resource=migration_resource, worker_resource=worker_resource)


def test_legacy_sql_real_connection_executor_contract_stays_non_executing() -> None:
    preflight = ready_preflight()
    checked_at = datetime(2026, 6, 18, 14, tzinfo=UTC)
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at,
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash="sha256:" + "a" * 64,
        requested_by="real-connection-executor-test",
    )

    contract = build_legacy_sql_connector_real_connection_executor_contract(
        command=command,
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )

    assert contract.schema_version == "legacy_sql_connector_real_connection_executor_contract.v1"
    assert contract.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.READY
    assert contract.executor_contract_ready
    assert contract.preflight_hash_valid
    assert contract.preflight_ready
    assert contract.preflight_bound
    assert contract.timeout_retry_policy_hash_valid
    assert contract.timeout_retry_policy_bound
    assert contract.timeout_retry_policy_ready
    assert contract.audit_plan_hash_valid
    assert contract.audit_plan_bound
    assert contract.audit_plan_metadata_only
    assert contract.audit_plan_required_event_types_present
    assert contract.kill_switch_policy_hash_valid
    assert contract.kill_switch_policy_bound
    assert contract.kill_switch_armed
    assert contract.kill_switch_policy_ready
    assert contract.executor_restore_evidence_hash_valid
    assert contract.future_socket_materialization_gate_required
    assert contract.future_secret_materialization_gate_required
    assert contract.future_execution_implementation_required
    assert not contract.socket_materialization_allowed
    assert not contract.network_socket_opened
    assert not contract.network_connection_opened
    assert not contract.real_connection_opened
    assert not contract.secret_material_resolved
    assert not contract.raw_data_access_allowed
    assert not contract.import_dry_run_allowed
    assert not contract.import_write_allowed
    assert not contract.destructive_actions_allowed
    assert timeout_retry_policy.evidence_hash == build_legacy_sql_connector_real_connection_timeout_retry_policy_hash(
        timeout_retry_policy
    )
    assert audit_plan.evidence_hash == build_legacy_sql_connector_real_connection_audit_plan_hash(audit_plan)
    assert kill_switch_policy.evidence_hash == build_legacy_sql_connector_real_connection_kill_switch_policy_hash(
        kill_switch_policy
    )
    assert contract.evidence_hash == build_legacy_sql_connector_real_connection_executor_contract_hash(contract)

    payload = contract.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_real_connection_executor_contract_blocks_materialization_kill_switch_and_tamper() -> None:
    preflight = ready_preflight()
    checked_at = datetime(2026, 6, 18, 14, 10, tzinfo=UTC)
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at,
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash="sha256:" + "a" * 64,
        requested_by="real-connection-executor-test",
    )

    materialization_request = build_legacy_sql_connector_real_connection_executor_contract(
        command=command.model_copy(
            update={"socket_materialization_requested": True, "secret_materialization_requested": True}
        ),
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert materialization_request.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
    assert "socket_materialization_requires_future_execution_gate" in materialization_request.blocking_reasons
    assert "secret_materialization_requires_future_execution_gate" in materialization_request.blocking_reasons
    assert not materialization_request.socket_materialization_allowed
    assert not materialization_request.network_socket_opened
    assert not materialization_request.secret_material_resolved

    disabled_kill_switch = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
        tenant_connection_disabled=True,
    )
    disabled_command = command.model_copy(update={"kill_switch_policy_hash": disabled_kill_switch.evidence_hash})
    kill_switch_blocked = build_legacy_sql_connector_real_connection_executor_contract(
        command=disabled_command,
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=disabled_kill_switch,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    assert kill_switch_blocked.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
    assert "tenant_connection_kill_switch_disabled" in kill_switch_blocked.blocking_reasons
    assert not kill_switch_blocked.real_connection_opened

    tampered_preflight = preflight.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    tampered = build_legacy_sql_connector_real_connection_executor_contract(
        command=command,
        preflight=tampered_preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    assert tampered.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
    assert "preflight_hash_invalid" in tampered.blocking_reasons


def test_legacy_sql_real_connection_executor_policy_store_roundtrips_tenant_safely(tmp_path: Path) -> None:
    preflight = ready_preflight()
    checked_at = datetime(2026, 6, 18, 14, 20, tzinfo=UTC)
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at,
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash="sha256:" + "a" * 64,
        requested_by="real-connection-executor-test",
    )
    contract = build_legacy_sql_connector_real_connection_executor_contract(
        command=command,
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    bundle = build_legacy_sql_connector_real_connection_executor_policy_bundle(
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=contract,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )

    assert bundle.schema_version == "legacy_sql_connector_real_connection_executor_policy_bundle.v1"
    assert bundle.bundle_status == LegacySqlConnectorRealConnectionExecutorStatus.READY
    assert bundle.store_persistence_allowed
    assert bundle.policy_chain_bound
    assert bundle.tenant_scope_verified
    assert bundle.restore_evidence_hash_valid
    assert bundle.evidence_hash == build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(bundle)
    assert not bundle.network_socket_opened
    assert not bundle.secret_material_resolved
    assert not bundle.real_connection_opened

    memory_store = InMemoryLegacySqlConnectorRealConnectionExecutorPolicyStore()
    assert memory_store.append(bundle).evidence_hash == bundle.evidence_hash
    assert memory_store.append(bundle).evidence_hash == bundle.evidence_hash
    assert len(memory_store.list_bundles(tenant_id=bundle.tenant_id)) == 1
    assert (
        memory_store.get(
            tenant_id=bundle.tenant_id,
            executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        ).evidence_hash
        == bundle.evidence_hash
    )
    with pytest.raises(KeyError):
        memory_store.get(
            tenant_id=f"{bundle.tenant_id}-other",
            executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        )

    jsonl_path = tmp_path / "executor_policy_store.jsonl"
    jsonl_store = JsonlLegacySqlConnectorRealConnectionExecutorPolicyStore(path=jsonl_path)
    jsonl_store.append(bundle)
    assert jsonl_store.append(bundle).evidence_hash == bundle.evidence_hash
    reloaded = JsonlLegacySqlConnectorRealConnectionExecutorPolicyStore(path=jsonl_path)
    assert len(reloaded.list_bundles(tenant_id=bundle.tenant_id)) == 1
    assert (
        reloaded.get(
            tenant_id=bundle.tenant_id,
            executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        ).evidence_hash
        == bundle.evidence_hash
    )


def test_pg_legacy_sql_real_connection_executor_smoke_keeps_contract_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_executor_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_real_connection_executor_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_real_connection_executor_smoke_report.v1"
    assert report.queue_backend == "postgres"
    assert report.executor_contract_ready
    assert report.preflight_required
    assert report.timeout_retry_policy_required
    assert report.audit_plan_required
    assert report.kill_switch_policy_required
    assert report.materialization_request_blocked
    assert report.kill_switch_disabled_blocked
    assert report.tampered_preflight_blocked
    assert report.future_socket_materialization_gate_required
    assert report.future_secret_materialization_gate_required
    assert report.future_execution_implementation_required
    assert not report.socket_materialization_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_real_connection_executor_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def test_pg_legacy_sql_real_connection_executor_policy_store_smoke_persists_bundle(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_policy_store_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_real_connection_executor_policy_store_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_real_connection_executor_policy_store_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.bundle_ready
    assert report.persistence_roundtrip_ok
    assert report.duplicate_append_idempotent
    assert report.tenant_isolation_ok
    assert report.restore_evidence_required
    assert report.policy_store_operational
    assert report.future_socket_materialization_gate_required
    assert report.future_secret_materialization_gate_required
    assert report.future_execution_implementation_required
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_real_connection_executor_policy_store_smoke_report_hash(
        report
    )
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "secret:legacy-sql-production-metadata" not in payload
    assert "sqlserver://" not in payload


def ready_preflight() -> LegacySqlConnectorConnectionPreflightEvidence:
    fixture = preflight_fixture()
    command = build_legacy_sql_connector_connection_preflight_command(
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        restore_evidence_hash="sha256:" + "9" * 64,
        requested_by="real-connection-executor-test",
    )
    return build_legacy_sql_connector_connection_preflight_gate(
        command=command,
        profile=fixture.profile,
        enablement_gate=fixture.enablement_gate,
        provider_adapter_evidence=fixture.provider_adapter_evidence,
        operator_context=fixture.operator_context,
        checked_by="real-connection-executor-test",
        checked_at_utc=datetime(2026, 6, 18, 13, 30, tzinfo=UTC),
    )


def preflight_fixture() -> PreflightFixture:
    profile = sandbox_profile()
    checked_at = datetime(2026, 6, 18, 13, tzinfo=UTC)
    network_profile = build_legacy_sql_connector_network_deployment_profile(
        profile=profile,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at,
    )
    secret_resolver_profile = build_legacy_sql_connector_secret_resolver_deployment_profile(
        profile=profile,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    audit_profile = build_legacy_sql_connector_audit_deployment_profile(
        profile=profile,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    provider_command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by="real-connection-executor-test",
    )
    provider_result = LegacySqlConnectorProviderAttestationAdapter().validate_provider_profiles(
        command=provider_command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    enablement_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        restore_evidence_hash="sha256:" + "8" * 64,
        requested_by="real-connection-executor-test",
        human_confirmation_reference="human-confirmation:legacy-sql-real-connection-executor-test",
    )
    enablement_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=enablement_command,
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    operator_context = build_legacy_sql_connector_operator_context(
        profile=profile,
        operator_principal_ref="principal:legacy-sql-operator",
        change_request_ref="change-request:legacy-sql-real-connection-executor-test",
        maintenance_window_ref="maintenance-window:legacy-sql-real-connection-executor-test",
        approval_reference="approval:legacy-sql-real-connection-executor-test",
        audit_chain_ref="audit:legacy-sql-real-connection-executor-test",
        checked_by="real-connection-executor-test",
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
        checked_by="real-connection-executor-test",
        checked_at_utc=datetime(2026, 6, 18, 10, tzinfo=UTC),
    )


def validated_activation() -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
    checked_at = datetime(2026, 6, 18, 9, tzinfo=UTC)
    draft = LegacySqlMetadataWorkerLeaseConsumerActivationEvidence(
        tenant_id="tenant-legacy-sql-real-connection-executor-test",
        module_id="crm_erp",
        source_system_ref="legacy-sql:production-sqlserver",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        host_profile_ref="legacy-host:sqlserver-production-metadata",
        worker_queue_ref="worker-queue:legacy-sql-metadata-discovery",
        worker_job_ref="legacy-sql-metadata-worker-job:real-connection-executor-test",
        worker_idempotency_key_hash="sha256:" + "1" * 64,
        queue_job_evidence_hash="sha256:" + "2" * 64,
        schedule_evidence_hash="sha256:" + "3" * 64,
        schedule_evidence_ref="legacy-sql-host-profile-adapter-schedule:real-connection-executor-test",
        release_gate_evidence_hash="sha256:" + "4" * 64,
        metadata_worker_command_hash="sha256:" + "5" * 64,
        metadata_worker_command_view_hash="sha256:" + "6" * 64,
        metadata_worker_profile_ref="worker-profile:legacy-sql-metadata-only",
        approved_egress_ref="egress:legacy-sql-production-metadata",
        connection_secret_ref_hash="sha256:" + "7" * 64,
        connection_fingerprint_hash="fingerprint:legacy-sql-production",
        worker_network_mode=LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY,
        lease_id="lease:real-connection-executor-test",
        lease_owner="real-connection-executor-test",
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
        checked_by="real-connection-executor-test",
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(draft)})


def postgres_executor_env(*, tmp_path: Path, worker_resource: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "c" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_resource,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_resource,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_resource,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "d" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_ENABLEMENT_RESTORE_HASH": "sha256:" + "e" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_PREFLIGHT_RESTORE_HASH": "sha256:" + "f" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_RESTORE_HASH": "sha256:" + "a" * 64,
        "SUITE_DATABASE_DSN": worker_resource,
    }


def postgres_policy_store_env(*, tmp_path: Path, worker_resource: str) -> dict[str, str]:
    return {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "c" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": worker_resource,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": worker_resource,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN": worker_resource,
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH": "sha256:" + "d" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_DSN": worker_resource,
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_ENABLEMENT_RESTORE_HASH": (
            "sha256:" + "e" * 64
        ),
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_PREFLIGHT_RESTORE_HASH": (
            "sha256:" + "f" * 64
        ),
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_RESTORE_HASH": "sha256:" + "a" * 64,
        "SUITE_DATABASE_DSN": worker_resource,
    }
