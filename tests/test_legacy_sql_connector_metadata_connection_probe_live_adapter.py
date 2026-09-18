from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_metadata_connection_probe_gate import (
    LegacySqlConnectorMetadataConnectionProbeGateEvidence,
)
from suite.platform.legacy_sql_connector_metadata_connection_probe_live_adapter import (
    LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus,
    LivePostgresMetadataProbeSecretBroker,
    build_legacy_sql_connector_metadata_connection_probe_live_adapter_command,
    build_legacy_sql_connector_metadata_connection_probe_live_adapter_evidence_hash,
    build_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report_hash,
    execute_legacy_sql_connector_metadata_connection_probe_live_adapter,
    exit_code_for_report,
    run_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_from_env,
)
from suite.platform.legacy_sql_connector_metadata_connection_probe_skeleton import (
    _build_ready_metadata_connection_probe_gate,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)

_ = live_database


def postgres_metadata_probe_gate(
    tmp_path: Path,
    worker_resource: str,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorMetadataConnectionProbeGateEvidence]:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=worker_resource)
    env["SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_CONNECTOR_KIND"] = "postgres"
    env["SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SOURCE_REF"] = "legacy-sql:production-postgres"
    env["SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_HOST_PROFILE_REF"] = "legacy-host:postgres-production-metadata"
    return _build_ready_metadata_connection_probe_gate(
        env=env,
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at=datetime(2026, 6, 21, 9, tzinfo=UTC),
    )


def test_legacy_sql_metadata_connection_probe_live_adapter_blocks_before_secret_or_network(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    _bundle, gate = postgres_metadata_probe_gate(tmp_path, live_database.worker_resource)
    command = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by="metadata-connection-probe-live-adapter-test",
    )
    broker = LivePostgresMetadataProbeSecretBroker(dsn=live_database.worker_resource)

    evidence = execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=command,
        metadata_connection_probe_gate=gate,
        secret_broker=broker,
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at_utc=datetime(2026, 6, 21, 9, 1, tzinfo=UTC),
    )

    assert gate.connector_kind == LegacySqlConnectorKind.POSTGRES
    assert evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.BLOCKED
    assert "live_adapter_runtime_default_off" in evidence.blocking_reasons
    assert "secret_materialization_not_enabled" in evidence.blocking_reasons
    assert "network_route_not_allowed" in evidence.blocking_reasons
    assert not evidence.secret_materialized_inside_worker
    assert not evidence.network_socket_opened
    assert not evidence.real_connection_opened
    assert broker.calls == []
    assert evidence.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_live_adapter_evidence_hash(
        evidence
    )


def test_legacy_sql_metadata_connection_probe_live_adapter_blocks_missing_route_secret_and_emergency_stop(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    _bundle, gate = postgres_metadata_probe_gate(tmp_path, live_database.worker_resource)
    checked_at = datetime(2026, 6, 21, 9, 10, tzinfo=UTC)
    no_secret = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by="metadata-connection-probe-live-adapter-test",
        live_adapter_runtime_enabled=True,
        network_route_allowed=True,
    )
    no_route = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by="metadata-connection-probe-live-adapter-test",
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
    )
    emergency_stop = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by="metadata-connection-probe-live-adapter-test",
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
        network_route_allowed=True,
        emergency_stop_active=True,
    )

    no_secret_evidence = execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=no_secret,
        metadata_connection_probe_gate=gate,
        secret_broker=LivePostgresMetadataProbeSecretBroker(dsn=live_database.worker_resource),
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at_utc=checked_at,
    )
    no_route_evidence = execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=no_route,
        metadata_connection_probe_gate=gate,
        secret_broker=LivePostgresMetadataProbeSecretBroker(dsn=live_database.worker_resource),
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    emergency_evidence = execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=emergency_stop,
        metadata_connection_probe_gate=gate,
        secret_broker=LivePostgresMetadataProbeSecretBroker(dsn=live_database.worker_resource),
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )

    assert "secret_materialization_not_enabled" in no_secret_evidence.blocking_reasons
    assert "network_route_not_allowed" in no_route_evidence.blocking_reasons
    assert "emergency_stop_active" in emergency_evidence.blocking_reasons
    for evidence in (no_secret_evidence, no_route_evidence, emergency_evidence):
        assert evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.BLOCKED
        assert not evidence.secret_materialized_inside_worker
        assert not evidence.network_socket_opened
        assert not evidence.real_connection_opened


def test_legacy_sql_metadata_connection_probe_live_adapter_executes_postgres_metadata_only(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    _bundle, gate = postgres_metadata_probe_gate(tmp_path, live_database.worker_resource)
    command = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by="metadata-connection-probe-live-adapter-test",
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
        network_route_allowed=True,
    )
    broker = LivePostgresMetadataProbeSecretBroker(dsn=live_database.worker_resource)

    evidence = execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=command,
        metadata_connection_probe_gate=gate,
        secret_broker=broker,
        checked_by="metadata-connection-probe-live-adapter-test",
        checked_at_utc=datetime(2026, 6, 21, 9, 20, tzinfo=UTC),
    )

    assert evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.EXECUTED
    assert evidence.skeleton_execution_status
    assert evidence.executed_query_names == ("tables", "columns", "primary_keys")
    assert evidence.metadata_relation_count > 0
    assert evidence.metadata_column_count > 0
    assert evidence.metadata_primary_key_count >= 0
    assert evidence.secret_materialized_inside_worker
    assert not evidence.secret_material_exposed_to_evidence
    assert evidence.provider_driver_loaded_by_adapter
    assert evidence.network_route_allowed
    assert evidence.network_socket_opened
    assert evidence.network_connection_opened
    assert evidence.real_connection_opened
    assert evidence.read_only_transaction_verified
    assert evidence.redaction_boundary_passed
    assert not evidence.raw_data_access_allowed
    assert not evidence.raw_rows_returned
    assert not evidence.sample_values_returned
    assert not evidence.import_dry_run_allowed
    assert not evidence.import_write_allowed
    assert not evidence.destructive_actions_allowed
    assert broker.calls == ["read_handle_metadata", "materialize_for_worker"]
    payload = evidence.model_dump_json().lower()
    assert live_database.worker_resource.lower() not in payload
    assert "postgresql://" not in payload
    assert "password" not in payload
    assert "row_values" not in payload
    assert evidence.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_live_adapter_evidence_hash(
        evidence
    )


def test_pg_legacy_sql_metadata_connection_probe_live_adapter_smoke(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)
    env["SUITE_LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_LIVE_ADAPTER_SECRET_DSN"] = live_database.worker_resource

    report = run_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report.v1"
    assert report.metadata_connection_probe_gate_ready
    assert report.default_off_blocked
    assert report.no_secret_materialization_blocked
    assert report.no_network_route_blocked
    assert report.emergency_stop_blocked
    assert report.live_postgres_probe_completed
    assert report.live_adapter_runtime_enabled
    assert report.secret_materialized_inside_worker
    assert not report.secret_material_exposed_to_evidence
    assert report.network_route_allowed
    assert report.provider_driver_loaded_by_adapter
    assert report.network_socket_opened
    assert report.network_connection_opened
    assert report.real_connection_opened
    assert report.read_only_transaction_verified
    assert report.redaction_boundary_passed
    assert report.audit_sink_bound
    assert report.timeout_circuit_breaker_bound
    assert report.emergency_stop_bound
    assert report.isolated_worker_bound
    assert not report.raw_data_access_allowed
    assert not report.raw_rows_returned
    assert not report.sample_values_returned
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.metadata_relation_count > 0
    assert report.metadata_column_count > 0
    assert report.smoke_passed
    assert report.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report_hash(
        report
    )
    assert exit_code_for_report(report) == 0
    payload = report.model_dump_json().lower()
    assert live_database.worker_resource.lower() not in payload
    assert "postgresql://" not in payload
    assert "password" not in payload
