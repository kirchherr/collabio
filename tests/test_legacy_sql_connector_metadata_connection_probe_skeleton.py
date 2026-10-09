from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_metadata_connection_probe_skeleton import (
    CapturingMetadataProbeAuditSink,
    FixtureMetadataOnlyProbeProviderAdapter,
    InMemoryMetadataProbeSecretBroker,
    LegacySqlConnectorMetadataConnectionProbeSkeletonStatus,
    build_legacy_sql_connector_metadata_connection_probe_execution_evidence_hash,
    build_legacy_sql_connector_metadata_connection_probe_execution_plan,
    build_legacy_sql_connector_metadata_connection_probe_execution_plan_hash,
    build_legacy_sql_connector_metadata_connection_probe_skeleton_command,
    build_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report_hash,
    execute_legacy_sql_connector_metadata_connection_probe_skeleton,
    exit_code_for_report,
    run_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_from_env,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_metadata_connection_probe_gate import metadata_connection_probe_fixture

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


def test_legacy_sql_metadata_connection_probe_skeleton_blocks_default_off_without_touching_adapter(
    tmp_path: Path,
) -> None:
    fixture = metadata_connection_probe_fixture(tmp_path)
    checked_at = datetime(2026, 6, 21, 8, tzinfo=UTC)
    command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=fixture.gate,
        requested_by="metadata-connection-probe-skeleton-test",
    )
    broker = InMemoryMetadataProbeSecretBroker()
    adapter = FixtureMetadataOnlyProbeProviderAdapter()
    audit_sink = CapturingMetadataProbeAuditSink()

    evidence = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=command,
        metadata_connection_probe_gate=fixture.gate,
        provider_adapter=adapter,
        secret_broker=broker,
        audit_sink=audit_sink,
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at,
    )

    assert evidence.schema_version == "legacy_sql_connector_metadata_connection_probe_execution_evidence.v1"
    assert evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED
    assert "metadata_probe_runtime_default_off" in evidence.blocking_reasons
    assert not evidence.metadata_connection_probe_executed
    assert not evidence.provider_driver_adapter_invoked
    assert not evidence.secret_broker_handle_metadata_read
    assert not evidence.network_socket_opened
    assert not evidence.real_connection_opened
    assert not evidence.raw_data_access_allowed
    assert broker.calls == []
    assert adapter.calls == []
    assert tuple(audit_sink.event_types) == (
        "legacy_sql.metadata_connection_probe.requested",
        "legacy_sql.metadata_connection_probe.blocked",
    )
    assert evidence.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_execution_evidence_hash(
        evidence
    )


def test_legacy_sql_metadata_connection_probe_skeleton_executes_only_metadata_fixture_when_enabled(
    tmp_path: Path,
) -> None:
    fixture = metadata_connection_probe_fixture(tmp_path)
    checked_at = datetime(2026, 6, 21, 8, 10, tzinfo=UTC)
    command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=fixture.gate,
        requested_by="metadata-connection-probe-skeleton-test",
        metadata_probe_runtime_enabled=True,
    )
    plan = build_legacy_sql_connector_metadata_connection_probe_execution_plan(
        command=command,
        metadata_connection_probe_gate=fixture.gate,
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at,
    )
    broker = InMemoryMetadataProbeSecretBroker()
    adapter = FixtureMetadataOnlyProbeProviderAdapter()
    audit_sink = CapturingMetadataProbeAuditSink()

    evidence = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=command,
        metadata_connection_probe_gate=fixture.gate,
        provider_adapter=adapter,
        secret_broker=broker,
        audit_sink=audit_sink,
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )

    assert plan.plan_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.READY
    assert plan.execution_plan_ready
    assert plan.metadata_connection_probe_gate_hash_valid
    assert plan.metadata_connection_probe_gate_ready
    assert plan.metadata_connection_probe_gate_bound
    assert plan.provider_driver_adapter_invocation_allowed
    assert plan.secret_broker_handle_metadata_read_allowed
    assert plan.metadata_query_execution_allowed
    assert plan.socket_runtime_execution_allowed
    assert plan.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_execution_plan_hash(plan)
    assert evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.EXECUTED
    assert evidence.metadata_connection_probe_executed
    assert evidence.provider_driver_adapter_invoked
    assert evidence.secret_broker_handle_metadata_read
    assert evidence.metadata_query_execution_allowed
    assert evidence.socket_runtime_execution_allowed
    assert evidence.executed_query_names == ("tables", "columns", "primary_keys")
    assert len(evidence.metadata_result_set_hashes) == 3
    assert evidence.metadata_relation_count == 2
    assert evidence.metadata_column_count == 7
    assert not evidence.provider_driver_loaded_by_adapter
    assert not evidence.secret_material_resolved
    assert not evidence.network_socket_opened
    assert not evidence.network_connection_opened
    assert not evidence.real_connection_opened
    assert not evidence.raw_data_access_allowed
    assert not evidence.raw_rows_returned
    assert not evidence.sample_values_returned
    assert not evidence.import_dry_run_allowed
    assert not evidence.import_write_allowed
    assert not evidence.destructive_actions_allowed
    assert broker.calls == ["sealed-handle:legacy-sql-metadata-probe"]
    assert adapter.calls == [("tables", "columns", "primary_keys")]
    assert tuple(audit_sink.event_types) == (
        "legacy_sql.metadata_connection_probe.requested",
        "legacy_sql.metadata_connection_probe.started",
        "legacy_sql.metadata_connection_probe.completed",
    )
    assert evidence.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_execution_evidence_hash(
        evidence
    )
    payload = evidence.model_dump_json().lower()
    assert "secret:legacy-sql" not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload
    assert "email" not in payload


def test_legacy_sql_metadata_connection_probe_skeleton_blocks_tamper_kill_switch_and_raw_request(
    tmp_path: Path,
) -> None:
    fixture = metadata_connection_probe_fixture(tmp_path)
    checked_at = datetime(2026, 6, 21, 8, 20, tzinfo=UTC)
    enabled_command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=fixture.gate,
        requested_by="metadata-connection-probe-skeleton-test",
        metadata_probe_runtime_enabled=True,
    )
    tampered_gate = fixture.gate.model_copy(update={"evidence_hash": ZERO_HASH})
    tampered = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=enabled_command,
        metadata_connection_probe_gate=tampered_gate,
        provider_adapter=FixtureMetadataOnlyProbeProviderAdapter(),
        secret_broker=InMemoryMetadataProbeSecretBroker(),
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at,
    )
    assert tampered.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED
    assert "metadata_connection_probe_gate_hash_invalid" in tampered.blocking_reasons
    assert "metadata_connection_probe_gate_not_bound" in tampered.blocking_reasons

    kill_switch_command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=fixture.gate,
        requested_by="metadata-connection-probe-skeleton-test",
        metadata_probe_runtime_enabled=True,
        tenant_kill_switch_disabled=True,
    )
    kill_switch = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=kill_switch_command,
        metadata_connection_probe_gate=fixture.gate,
        provider_adapter=FixtureMetadataOnlyProbeProviderAdapter(),
        secret_broker=InMemoryMetadataProbeSecretBroker(),
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert kill_switch.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED
    assert "tenant_connection_kill_switch_disabled" in kill_switch.blocking_reasons
    assert not kill_switch.metadata_connection_probe_executed

    raw_command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=fixture.gate,
        requested_by="metadata-connection-probe-skeleton-test",
        metadata_probe_runtime_enabled=True,
        raw_data_access_requested=True,
    )
    raw_request = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=raw_command,
        metadata_connection_probe_gate=fixture.gate,
        provider_adapter=FixtureMetadataOnlyProbeProviderAdapter(),
        secret_broker=InMemoryMetadataProbeSecretBroker(),
        checked_by="metadata-connection-probe-skeleton-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    assert raw_request.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED
    assert "raw_data_access_requires_future_data_gate" in raw_request.blocking_reasons
    assert not raw_request.metadata_connection_probe_executed
    assert not raw_request.raw_data_access_allowed


def test_pg_legacy_sql_metadata_connection_probe_skeleton_smoke(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.metadata_connection_probe_gate_ready
    assert report.default_off_blocked
    assert report.kill_switch_disabled_blocked
    assert report.raw_data_request_blocked
    assert report.enabled_fixture_probe_completed
    assert report.provider_driver_adapter_contract_bound
    assert report.secret_broker_read_path_bound
    assert report.metadata_query_allowlist_bound
    assert report.timeout_circuit_breaker_bound
    assert report.audit_sink_bound
    assert report.emergency_disable_bound
    assert report.offline_fixture_probe_executed
    assert not report.external_metadata_connection_probe_executed
    assert report.provider_driver_adapter_invoked
    assert not report.provider_driver_loaded_by_adapter
    assert report.secret_broker_handle_metadata_read
    assert not report.secret_material_resolved
    assert report.metadata_query_execution_allowed
    assert report.socket_runtime_execution_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.raw_data_access_allowed
    assert not report.raw_rows_returned
    assert not report.sample_values_returned
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.future_raw_data_gate_required
    assert report.future_import_dry_run_gate_required
    assert report.smoke_passed
    assert report.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report_hash(
        report
    )
    assert exit_code_for_report(report) == 0
