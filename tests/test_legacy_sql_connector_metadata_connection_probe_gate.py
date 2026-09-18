from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_live_connection_gate import (
    LegacySqlConnectorLiveConnectionGateEvidence,
    LegacySqlConnectorLiveConnectionGateStatus,
    build_legacy_sql_connector_live_connection_gate_hash,
)
from suite.platform.legacy_sql_connector_metadata_connection_probe_gate import (
    LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    LegacySqlConnectorMetadataConnectionProbeGateCommand,
    LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    LegacySqlConnectorMetadataConnectionProbeGateStatus,
    build_legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot,
    build_legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot,
    build_legacy_sql_connector_metadata_connection_probe_gate,
    build_legacy_sql_connector_metadata_connection_probe_gate_command,
    build_legacy_sql_connector_metadata_connection_probe_gate_hash,
    build_legacy_sql_connector_metadata_connection_probe_gate_smoke_report_hash,
    build_legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot,
    build_legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot,
    build_legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot,
    build_legacy_sql_connector_metadata_connection_probe_snapshot_hash,
    build_legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot,
    exit_code_for_report,
    run_legacy_sql_connector_metadata_connection_probe_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_live_connection_gate import live_connection_fixture

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class MetadataConnectionProbeFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence
    provider_driver_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    secret_broker_read_path_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    metadata_query_allowlist_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    timeout_circuit_breaker_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    audit_sink_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    emergency_disable_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence


def test_legacy_sql_metadata_connection_probe_gate_binds_required_evidence_without_probe(tmp_path: Path) -> None:
    fixture = metadata_connection_probe_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_metadata_connection_probe_gate.v1"
    assert gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
    assert gate.metadata_connection_probe_gate_ready
    assert gate.live_connection_gate_hash_valid
    assert gate.live_connection_gate_ready
    assert gate.live_connection_gate_bound
    assert gate.provider_driver_snapshot_hash_valid
    assert gate.provider_driver_snapshot_bound
    assert gate.provider_driver_passed
    assert gate.secret_broker_read_path_snapshot_hash_valid
    assert gate.secret_broker_read_path_snapshot_bound
    assert gate.secret_broker_read_path_passed
    assert gate.metadata_query_allowlist_snapshot_hash_valid
    assert gate.metadata_query_allowlist_snapshot_bound
    assert gate.metadata_query_allowlist_passed
    assert gate.timeout_circuit_breaker_execution_snapshot_hash_valid
    assert gate.timeout_circuit_breaker_execution_snapshot_bound
    assert gate.timeout_circuit_breaker_execution_passed
    assert gate.audit_sink_execution_snapshot_hash_valid
    assert gate.audit_sink_execution_snapshot_bound
    assert gate.audit_sink_execution_passed
    assert gate.emergency_disable_execution_snapshot_hash_valid
    assert gate.emergency_disable_execution_snapshot_bound
    assert gate.emergency_disable_execution_passed
    assert gate.future_metadata_probe_implementation_required
    assert gate.future_secret_materialization_gate_required
    assert gate.future_import_dry_run_gate_required
    assert not gate.provider_driver_load_allowed
    assert not gate.secret_broker_read_allowed
    assert not gate.metadata_connection_probe_allowed
    assert not gate.metadata_connection_probe_executed
    assert not gate.metadata_query_execution_allowed
    assert not gate.socket_runtime_execution_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_metadata_connection_probe_gate_blocks_missing_inputs_and_direct_probe_requests(
    tmp_path: Path,
) -> None:
    fixture = metadata_connection_probe_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 20, tzinfo=UTC)

    blocked_live = fixture.live_connection_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorLiveConnectionGateStatus.BLOCKED,
            "live_connection_gate_ready": False,
            "blocking_reasons": ("metadata_probe_test_live_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_live = blocked_live.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_live_connection_gate_hash(blocked_live)}
    )
    blocked_live_gate = build_legacy_sql_connector_metadata_connection_probe_gate(
        command=fixture.command.model_copy(update={"live_connection_gate_evidence_hash": blocked_live.evidence_hash}),
        bundle=fixture.bundle,
        live_connection_gate=blocked_live,
        provider_driver_snapshot=fixture.provider_driver_snapshot,
        secret_broker_read_path_snapshot=fixture.secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=fixture.metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=fixture.timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=fixture.audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=fixture.emergency_disable_execution_snapshot,
        checked_by="metadata-connection-probe-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_live_gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
    assert "live_connection_gate_not_ready" in blocked_live_gate.blocking_reasons

    for field_name, snapshot, failed_control, expected_reason in (
        (
            "provider_driver_snapshot_hash",
            fixture.provider_driver_snapshot,
            "provider_driver_package_pinned",
            "provider_driver_snapshot_failed",
        ),
        (
            "secret_broker_read_path_snapshot_hash",
            fixture.secret_broker_read_path_snapshot,
            "secret_broker_read_path_bound",
            "secret_broker_read_path_snapshot_failed",
        ),
        (
            "metadata_query_allowlist_snapshot_hash",
            fixture.metadata_query_allowlist_snapshot,
            "metadata_catalog_queries_allowlisted",
            "metadata_query_allowlist_snapshot_failed",
        ),
        (
            "timeout_circuit_breaker_execution_snapshot_hash",
            fixture.timeout_circuit_breaker_execution_snapshot,
            "connect_timeout_execution_bound",
            "timeout_circuit_breaker_execution_snapshot_failed",
        ),
        (
            "audit_sink_execution_snapshot_hash",
            fixture.audit_sink_execution_snapshot,
            "probe_attempt_audit_event_bound",
            "audit_sink_execution_snapshot_failed",
        ),
        (
            "emergency_disable_execution_snapshot_hash",
            fixture.emergency_disable_execution_snapshot,
            "tenant_emergency_disable_execution_bound",
            "emergency_disable_execution_snapshot_failed",
        ),
    ):
        failed_controls = tuple(dict.fromkeys((*snapshot.failed_controls, failed_control)))
        blocked_snapshot = snapshot.model_copy(
            update={
                "passed_controls": tuple(
                    control for control in snapshot.required_controls if control not in failed_controls
                ),
                "failed_controls": failed_controls,
                "checked_at_utc": checked_at,
                "evidence_hash": ZERO_HASH,
            }
        )
        blocked_snapshot = blocked_snapshot.model_copy(
            update={
                "evidence_hash": build_legacy_sql_connector_metadata_connection_probe_snapshot_hash(blocked_snapshot)
            }
        )
        snapshots = {
            "provider_driver_snapshot": fixture.provider_driver_snapshot,
            "secret_broker_read_path_snapshot": fixture.secret_broker_read_path_snapshot,
            "metadata_query_allowlist_snapshot": fixture.metadata_query_allowlist_snapshot,
            "timeout_circuit_breaker_execution_snapshot": fixture.timeout_circuit_breaker_execution_snapshot,
            "audit_sink_execution_snapshot": fixture.audit_sink_execution_snapshot,
            "emergency_disable_execution_snapshot": fixture.emergency_disable_execution_snapshot,
        }
        snapshots[field_name.removesuffix("_hash")] = blocked_snapshot
        blocked_gate = build_legacy_sql_connector_metadata_connection_probe_gate(
            command=fixture.command.model_copy(update={field_name: blocked_snapshot.evidence_hash}),
            bundle=fixture.bundle,
            live_connection_gate=fixture.live_connection_gate,
            checked_by="metadata-connection-probe-gate-test",
            checked_at_utc=checked_at + timedelta(seconds=2),
            **snapshots,
        )
        assert blocked_gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
        assert expected_reason in blocked_gate.blocking_reasons
        assert not blocked_gate.metadata_connection_probe_gate_ready

    probe_command = build_legacy_sql_connector_metadata_connection_probe_gate_command(
        live_connection_gate=fixture.live_connection_gate,
        provider_driver_snapshot=fixture.provider_driver_snapshot,
        secret_broker_read_path_snapshot=fixture.secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=fixture.metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=fixture.timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=fixture.audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=fixture.emergency_disable_execution_snapshot,
        requested_by="metadata-connection-probe-gate-test",
        provider_driver_load_requested=True,
        secret_broker_read_requested=True,
        metadata_connection_probe_requested=True,
        metadata_query_execution_requested=True,
        socket_runtime_execution_requested=True,
        raw_data_access_requested=True,
    )
    probe_gate = build_legacy_sql_connector_metadata_connection_probe_gate(
        command=probe_command,
        bundle=fixture.bundle,
        live_connection_gate=fixture.live_connection_gate,
        provider_driver_snapshot=fixture.provider_driver_snapshot,
        secret_broker_read_path_snapshot=fixture.secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=fixture.metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=fixture.timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=fixture.audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=fixture.emergency_disable_execution_snapshot,
        checked_by="metadata-connection-probe-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert probe_gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
    assert "provider_driver_load_requires_future_probe_implementation" in probe_gate.blocking_reasons
    assert "secret_broker_read_requires_future_secret_gate" in probe_gate.blocking_reasons
    assert "metadata_connection_probe_requires_future_probe_implementation" in probe_gate.blocking_reasons
    assert "metadata_query_execution_requires_future_probe_implementation" in probe_gate.blocking_reasons
    assert "socket_runtime_execution_requires_future_probe_implementation" in probe_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in probe_gate.blocking_reasons
    assert not probe_gate.provider_driver_load_allowed
    assert not probe_gate.secret_broker_read_allowed
    assert not probe_gate.metadata_connection_probe_executed
    assert not probe_gate.real_connection_opened


def test_pg_legacy_sql_metadata_connection_probe_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_metadata_connection_probe_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_metadata_connection_probe_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.metadata_connection_probe_gate_ready
    assert report.live_connection_gate_required
    assert report.provider_driver_snapshot_required
    assert report.secret_broker_read_path_snapshot_required
    assert report.metadata_query_allowlist_snapshot_required
    assert report.timeout_circuit_breaker_execution_snapshot_required
    assert report.audit_sink_execution_snapshot_required
    assert report.emergency_disable_execution_snapshot_required
    assert report.live_connection_gate_missing_blocked
    assert report.provider_driver_missing_blocked
    assert report.secret_broker_read_path_missing_blocked
    assert report.metadata_query_allowlist_missing_blocked
    assert report.timeout_circuit_breaker_execution_missing_blocked
    assert report.audit_sink_execution_missing_blocked
    assert report.emergency_disable_execution_missing_blocked
    assert report.direct_probe_request_blocked
    assert report.future_metadata_probe_implementation_required
    assert report.future_secret_materialization_gate_required
    assert report.future_import_dry_run_gate_required
    assert not report.provider_driver_load_allowed
    assert not report.secret_broker_read_allowed
    assert not report.metadata_connection_probe_allowed
    assert not report.metadata_connection_probe_executed
    assert not report.metadata_query_execution_allowed
    assert not report.socket_runtime_execution_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_metadata_connection_probe_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def metadata_connection_probe_fixture(tmp_path: Path) -> MetadataConnectionProbeFixture:
    checked_at = datetime(2026, 6, 20, 19, tzinfo=UTC)
    checked_by = "metadata-connection-probe-gate-test"
    live_fixture = live_connection_fixture(tmp_path)
    provider_driver_snapshot = build_legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot(
        live_connection_gate=live_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    secret_broker_read_path_snapshot = (
        build_legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot(
            live_connection_gate=live_fixture.gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=2),
        )
    )
    metadata_query_allowlist_snapshot = build_legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot(
        live_connection_gate=live_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    timeout_circuit_breaker_execution_snapshot = (
        build_legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot(
            live_connection_gate=live_fixture.gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=4),
        )
    )
    audit_sink_execution_snapshot = build_legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot(
        live_connection_gate=live_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    emergency_disable_execution_snapshot = (
        build_legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot(
            live_connection_gate=live_fixture.gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=6),
        )
    )
    command = build_legacy_sql_connector_metadata_connection_probe_gate_command(
        live_connection_gate=live_fixture.gate,
        provider_driver_snapshot=provider_driver_snapshot,
        secret_broker_read_path_snapshot=secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=emergency_disable_execution_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_metadata_connection_probe_gate(
        command=command,
        bundle=live_fixture.bundle,
        live_connection_gate=live_fixture.gate,
        provider_driver_snapshot=provider_driver_snapshot,
        secret_broker_read_path_snapshot=secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=emergency_disable_execution_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    return MetadataConnectionProbeFixture(
        bundle=live_fixture.bundle,
        live_connection_gate=live_fixture.gate,
        provider_driver_snapshot=provider_driver_snapshot,
        secret_broker_read_path_snapshot=secret_broker_read_path_snapshot,
        metadata_query_allowlist_snapshot=metadata_query_allowlist_snapshot,
        timeout_circuit_breaker_execution_snapshot=timeout_circuit_breaker_execution_snapshot,
        audit_sink_execution_snapshot=audit_sink_execution_snapshot,
        emergency_disable_execution_snapshot=emergency_disable_execution_snapshot,
        command=command,
        gate=gate,
    )
