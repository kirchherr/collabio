from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_live_connection_gate import (
    LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    LegacySqlConnectorLiveConnectionGateCommand,
    LegacySqlConnectorLiveConnectionGateEvidence,
    LegacySqlConnectorLiveConnectionGateStatus,
    build_legacy_sql_connector_live_connection_audit_sink_snapshot,
    build_legacy_sql_connector_live_connection_emergency_disable_snapshot,
    build_legacy_sql_connector_live_connection_gate,
    build_legacy_sql_connector_live_connection_gate_command,
    build_legacy_sql_connector_live_connection_gate_hash,
    build_legacy_sql_connector_live_connection_gate_smoke_report_hash,
    build_legacy_sql_connector_live_connection_least_privilege_db_role_snapshot,
    build_legacy_sql_connector_live_connection_network_egress_policy_snapshot,
    build_legacy_sql_connector_live_connection_secret_broker_binding_snapshot,
    build_legacy_sql_connector_live_connection_snapshot_hash,
    build_legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot,
    exit_code_for_report,
    run_legacy_sql_connector_live_connection_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_connector_runtime_activation_gate import (
    LegacySqlConnectorRuntimeActivationGateEvidence,
    LegacySqlConnectorRuntimeActivationGateStatus,
    build_legacy_sql_connector_runtime_activation_gate_hash,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_runtime_activation_gate import runtime_activation_fixture

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class LiveConnectionFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence
    secret_broker_binding_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    network_egress_policy_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    least_privilege_db_role_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    timeout_circuit_breaker_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    audit_sink_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    emergency_disable_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot
    command: LegacySqlConnectorLiveConnectionGateCommand
    gate: LegacySqlConnectorLiveConnectionGateEvidence


def test_legacy_sql_live_connection_gate_binds_required_evidence_without_probe(tmp_path: Path) -> None:
    fixture = live_connection_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_live_connection_gate.v1"
    assert gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.READY
    assert gate.live_connection_gate_ready
    assert gate.runtime_activation_gate_hash_valid
    assert gate.runtime_activation_gate_ready
    assert gate.runtime_activation_gate_bound
    assert gate.secret_broker_binding_snapshot_hash_valid
    assert gate.secret_broker_binding_snapshot_bound
    assert gate.secret_broker_binding_passed
    assert gate.network_egress_policy_snapshot_hash_valid
    assert gate.network_egress_policy_snapshot_bound
    assert gate.network_egress_policy_passed
    assert gate.least_privilege_db_role_snapshot_hash_valid
    assert gate.least_privilege_db_role_snapshot_bound
    assert gate.least_privilege_db_role_passed
    assert gate.timeout_circuit_breaker_snapshot_hash_valid
    assert gate.timeout_circuit_breaker_snapshot_bound
    assert gate.timeout_circuit_breaker_passed
    assert gate.audit_sink_snapshot_hash_valid
    assert gate.audit_sink_snapshot_bound
    assert gate.audit_sink_passed
    assert gate.emergency_disable_snapshot_hash_valid
    assert gate.emergency_disable_snapshot_bound
    assert gate.emergency_disable_passed
    assert gate.future_metadata_connection_probe_gate_required
    assert gate.future_secret_materialization_gate_required
    assert gate.future_import_dry_run_gate_required
    assert not gate.metadata_connection_probe_allowed
    assert not gate.live_connection_probe_allowed
    assert not gate.secret_broker_resolution_allowed
    assert not gate.socket_runtime_execution_allowed
    assert not gate.secret_materialization_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_live_connection_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_live_connection_gate_blocks_missing_inputs_and_direct_probe_requests(tmp_path: Path) -> None:
    fixture = live_connection_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 18, tzinfo=UTC)

    blocked_activation = fixture.runtime_activation_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED,
            "runtime_activation_gate_ready": False,
            "blocking_reasons": ("live_connection_test_activation_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_activation = blocked_activation.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_activation_gate_hash(blocked_activation)}
    )
    blocked_activation_gate = build_legacy_sql_connector_live_connection_gate(
        command=fixture.command.model_copy(
            update={"runtime_activation_gate_evidence_hash": blocked_activation.evidence_hash}
        ),
        bundle=fixture.bundle,
        runtime_activation_gate=blocked_activation,
        secret_broker_binding_snapshot=fixture.secret_broker_binding_snapshot,
        network_egress_policy_snapshot=fixture.network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=fixture.least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=fixture.timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=fixture.audit_sink_snapshot,
        emergency_disable_snapshot=fixture.emergency_disable_snapshot,
        checked_by="live-connection-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_activation_gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
    assert "runtime_activation_gate_not_ready" in blocked_activation_gate.blocking_reasons

    for field_name, snapshot, failed_control, expected_reason in (
        (
            "secret_broker_binding_snapshot_hash",
            fixture.secret_broker_binding_snapshot,
            "secret_broker_binding_metadata_ready",
            "secret_broker_binding_snapshot_failed",
        ),
        (
            "network_egress_policy_snapshot_hash",
            fixture.network_egress_policy_snapshot,
            "egress_policy_bound",
            "network_egress_policy_snapshot_failed",
        ),
        (
            "least_privilege_db_role_snapshot_hash",
            fixture.least_privilege_db_role_snapshot,
            "least_privilege_db_role_defined",
            "least_privilege_db_role_snapshot_failed",
        ),
        (
            "timeout_circuit_breaker_snapshot_hash",
            fixture.timeout_circuit_breaker_snapshot,
            "connect_timeout_defined",
            "timeout_circuit_breaker_snapshot_failed",
        ),
        ("audit_sink_snapshot_hash", fixture.audit_sink_snapshot, "audit_sink_bound", "audit_sink_snapshot_failed"),
        (
            "emergency_disable_snapshot_hash",
            fixture.emergency_disable_snapshot,
            "tenant_emergency_disable_armed",
            "emergency_disable_snapshot_failed",
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
            update={"evidence_hash": build_legacy_sql_connector_live_connection_snapshot_hash(blocked_snapshot)}
        )
        snapshots = {
            "secret_broker_binding_snapshot": fixture.secret_broker_binding_snapshot,
            "network_egress_policy_snapshot": fixture.network_egress_policy_snapshot,
            "least_privilege_db_role_snapshot": fixture.least_privilege_db_role_snapshot,
            "timeout_circuit_breaker_snapshot": fixture.timeout_circuit_breaker_snapshot,
            "audit_sink_snapshot": fixture.audit_sink_snapshot,
            "emergency_disable_snapshot": fixture.emergency_disable_snapshot,
        }
        snapshots[field_name.removesuffix("_hash")] = blocked_snapshot
        blocked_gate = build_legacy_sql_connector_live_connection_gate(
            command=fixture.command.model_copy(update={field_name: blocked_snapshot.evidence_hash}),
            bundle=fixture.bundle,
            runtime_activation_gate=fixture.runtime_activation_gate,
            checked_by="live-connection-gate-test",
            checked_at_utc=checked_at + timedelta(seconds=2),
            **snapshots,
        )
        assert blocked_gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
        assert expected_reason in blocked_gate.blocking_reasons
        assert not blocked_gate.live_connection_gate_ready

    probe_command = build_legacy_sql_connector_live_connection_gate_command(
        runtime_activation_gate=fixture.runtime_activation_gate,
        secret_broker_binding_snapshot=fixture.secret_broker_binding_snapshot,
        network_egress_policy_snapshot=fixture.network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=fixture.least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=fixture.timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=fixture.audit_sink_snapshot,
        emergency_disable_snapshot=fixture.emergency_disable_snapshot,
        requested_by="live-connection-gate-test",
        metadata_connection_probe_requested=True,
        live_connection_probe_requested=True,
        secret_broker_resolution_requested=True,
        socket_runtime_execution_requested=True,
        secret_materialization_requested=True,
        raw_data_access_requested=True,
    )
    probe_gate = build_legacy_sql_connector_live_connection_gate(
        command=probe_command,
        bundle=fixture.bundle,
        runtime_activation_gate=fixture.runtime_activation_gate,
        secret_broker_binding_snapshot=fixture.secret_broker_binding_snapshot,
        network_egress_policy_snapshot=fixture.network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=fixture.least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=fixture.timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=fixture.audit_sink_snapshot,
        emergency_disable_snapshot=fixture.emergency_disable_snapshot,
        checked_by="live-connection-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert probe_gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
    assert "metadata_connection_probe_requires_future_probe_execution_gate" in probe_gate.blocking_reasons
    assert "live_connection_probe_requires_future_probe_execution_gate" in probe_gate.blocking_reasons
    assert "secret_broker_resolution_requires_future_secret_gate" in probe_gate.blocking_reasons
    assert "socket_runtime_execution_requires_future_probe_execution_gate" in probe_gate.blocking_reasons
    assert "secret_materialization_requires_future_secret_gate" in probe_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in probe_gate.blocking_reasons
    assert not probe_gate.metadata_connection_probe_allowed
    assert not probe_gate.secret_broker_resolution_allowed
    assert not probe_gate.real_connection_opened


def test_pg_legacy_sql_live_connection_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_live_connection_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_live_connection_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.live_connection_gate_ready
    assert report.runtime_activation_gate_required
    assert report.secret_broker_binding_snapshot_required
    assert report.network_egress_policy_snapshot_required
    assert report.least_privilege_db_role_snapshot_required
    assert report.timeout_circuit_breaker_snapshot_required
    assert report.audit_sink_snapshot_required
    assert report.emergency_disable_snapshot_required
    assert report.runtime_activation_gate_missing_blocked
    assert report.secret_broker_binding_missing_blocked
    assert report.network_egress_policy_missing_blocked
    assert report.least_privilege_db_role_missing_blocked
    assert report.timeout_circuit_breaker_missing_blocked
    assert report.audit_sink_missing_blocked
    assert report.emergency_disable_missing_blocked
    assert report.metadata_probe_request_blocked
    assert report.future_metadata_connection_probe_gate_required
    assert report.future_secret_materialization_gate_required
    assert report.future_import_dry_run_gate_required
    assert not report.metadata_connection_probe_allowed
    assert not report.live_connection_probe_allowed
    assert not report.secret_broker_resolution_allowed
    assert not report.socket_runtime_execution_allowed
    assert not report.secret_materialization_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_live_connection_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def live_connection_fixture(tmp_path: Path) -> LiveConnectionFixture:
    checked_at = datetime(2026, 6, 20, 17, tzinfo=UTC)
    checked_by = "live-connection-gate-test"
    activation_fixture = runtime_activation_fixture(tmp_path)
    secret_broker_binding_snapshot = build_legacy_sql_connector_live_connection_secret_broker_binding_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    network_egress_policy_snapshot = build_legacy_sql_connector_live_connection_network_egress_policy_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    least_privilege_db_role_snapshot = build_legacy_sql_connector_live_connection_least_privilege_db_role_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    timeout_circuit_breaker_snapshot = build_legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    audit_sink_snapshot = build_legacy_sql_connector_live_connection_audit_sink_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    emergency_disable_snapshot = build_legacy_sql_connector_live_connection_emergency_disable_snapshot(
        runtime_activation_gate=activation_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    command = build_legacy_sql_connector_live_connection_gate_command(
        runtime_activation_gate=activation_fixture.gate,
        secret_broker_binding_snapshot=secret_broker_binding_snapshot,
        network_egress_policy_snapshot=network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=audit_sink_snapshot,
        emergency_disable_snapshot=emergency_disable_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_live_connection_gate(
        command=command,
        bundle=activation_fixture.bundle,
        runtime_activation_gate=activation_fixture.gate,
        secret_broker_binding_snapshot=secret_broker_binding_snapshot,
        network_egress_policy_snapshot=network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=audit_sink_snapshot,
        emergency_disable_snapshot=emergency_disable_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    return LiveConnectionFixture(
        bundle=activation_fixture.bundle,
        runtime_activation_gate=activation_fixture.gate,
        secret_broker_binding_snapshot=secret_broker_binding_snapshot,
        network_egress_policy_snapshot=network_egress_policy_snapshot,
        least_privilege_db_role_snapshot=least_privilege_db_role_snapshot,
        timeout_circuit_breaker_snapshot=timeout_circuit_breaker_snapshot,
        audit_sink_snapshot=audit_sink_snapshot,
        emergency_disable_snapshot=emergency_disable_snapshot,
        command=command,
        gate=gate,
    )
