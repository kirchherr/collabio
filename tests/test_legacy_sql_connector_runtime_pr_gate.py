from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_connector_runtime_pr_gate import (
    LegacySqlConnectorRuntimePrEvidenceSnapshot,
    LegacySqlConnectorRuntimePrGateCommand,
    LegacySqlConnectorRuntimePrGateEvidence,
    LegacySqlConnectorRuntimePrGateStatus,
    build_legacy_sql_connector_runtime_pr_code_review_snapshot,
    build_legacy_sql_connector_runtime_pr_gate,
    build_legacy_sql_connector_runtime_pr_gate_command,
    build_legacy_sql_connector_runtime_pr_gate_hash,
    build_legacy_sql_connector_runtime_pr_gate_smoke_report_hash,
    build_legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot,
    build_legacy_sql_connector_runtime_pr_network_binding_snapshot,
    build_legacy_sql_connector_runtime_pr_rollback_probe_snapshot,
    build_legacy_sql_connector_runtime_pr_secret_binding_snapshot,
    build_legacy_sql_connector_runtime_pr_snapshot_hash,
    build_legacy_sql_connector_runtime_pr_test_container_snapshot,
    exit_code_for_report,
    run_legacy_sql_connector_runtime_pr_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_socket_secret_implementation_adr_gate import (
    LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    LegacySqlConnectorSocketSecretImplementationAdrGateStatus,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_socket_secret_implementation_adr_gate import (
    socket_secret_adr_fixture,
)

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class RuntimePrFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence
    code_review_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    test_container_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    secret_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    network_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    rollback_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    kill_switch_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot
    command: LegacySqlConnectorRuntimePrGateCommand
    gate: LegacySqlConnectorRuntimePrGateEvidence


def test_legacy_sql_runtime_pr_gate_binds_adr_review_container_secret_route_and_probes_without_runtime(
    tmp_path: Path,
) -> None:
    fixture = runtime_pr_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_runtime_pr_gate.v1"
    assert gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.READY
    assert gate.runtime_pr_gate_ready
    assert gate.adr_gate_hash_valid
    assert gate.adr_gate_ready
    assert gate.adr_gate_bound
    assert gate.code_review_snapshot_hash_valid
    assert gate.code_review_snapshot_bound
    assert gate.code_review_passed
    assert gate.test_container_snapshot_hash_valid
    assert gate.test_container_snapshot_bound
    assert gate.test_container_passed
    assert gate.secret_binding_snapshot_hash_valid
    assert gate.secret_binding_snapshot_bound
    assert gate.secret_binding_passed
    assert gate.network_binding_snapshot_hash_valid
    assert gate.network_binding_snapshot_bound
    assert gate.network_binding_passed
    assert gate.rollback_probe_snapshot_hash_valid
    assert gate.rollback_probe_snapshot_bound
    assert gate.rollback_probe_passed
    assert gate.kill_switch_probe_snapshot_hash_valid
    assert gate.kill_switch_probe_snapshot_bound
    assert gate.kill_switch_probe_passed
    assert gate.future_runtime_merge_gate_required
    assert gate.future_live_secret_rotation_gate_required
    assert gate.future_import_dry_run_gate_required
    assert not gate.merge_allowed
    assert not gate.runtime_code_merge_allowed
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
    assert gate.evidence_hash == build_legacy_sql_connector_runtime_pr_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_runtime_pr_gate_blocks_missing_inputs_and_merge_requests(tmp_path: Path) -> None:
    fixture = runtime_pr_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 13, tzinfo=UTC)

    blocked_adr = fixture.adr_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED,
            "implementation_adr_ready": False,
            "blocking_reasons": ("runtime_pr_test_adr_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_adr = blocked_adr.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(blocked_adr)}
    )
    blocked_adr_gate = build_legacy_sql_connector_runtime_pr_gate(
        command=fixture.command.model_copy(update={"adr_gate_evidence_hash": blocked_adr.evidence_hash}),
        bundle=fixture.bundle,
        adr_gate=blocked_adr,
        code_review_snapshot=fixture.code_review_snapshot,
        test_container_snapshot=fixture.test_container_snapshot,
        secret_binding_snapshot=fixture.secret_binding_snapshot,
        network_binding_snapshot=fixture.network_binding_snapshot,
        rollback_probe_snapshot=fixture.rollback_probe_snapshot,
        kill_switch_probe_snapshot=fixture.kill_switch_probe_snapshot,
        checked_by="runtime-pr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_adr_gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
    assert "adr_gate_not_ready" in blocked_adr_gate.blocking_reasons

    for field_name, snapshot, failed_control, expected_reason in (
        ("code_review_snapshot_hash", fixture.code_review_snapshot, "code_owner_review", "code_review_snapshot_failed"),
        (
            "test_container_snapshot_hash",
            fixture.test_container_snapshot,
            "runtime_tests_passed",
            "test_container_snapshot_failed",
        ),
        (
            "secret_binding_snapshot_hash",
            fixture.secret_binding_snapshot,
            "runtime_secret_binding_reviewed",
            "secret_binding_snapshot_failed",
        ),
        (
            "network_binding_snapshot_hash",
            fixture.network_binding_snapshot,
            "runtime_route_binding_reviewed",
            "network_binding_snapshot_failed",
        ),
        (
            "rollback_probe_snapshot_hash",
            fixture.rollback_probe_snapshot,
            "rollback_probe_passed",
            "rollback_probe_snapshot_failed",
        ),
        (
            "kill_switch_probe_snapshot_hash",
            fixture.kill_switch_probe_snapshot,
            "kill_switch_probe_passed",
            "kill_switch_probe_snapshot_failed",
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
            update={"evidence_hash": build_legacy_sql_connector_runtime_pr_snapshot_hash(blocked_snapshot)}
        )
        snapshots = {
            "code_review_snapshot": fixture.code_review_snapshot,
            "test_container_snapshot": fixture.test_container_snapshot,
            "secret_binding_snapshot": fixture.secret_binding_snapshot,
            "network_binding_snapshot": fixture.network_binding_snapshot,
            "rollback_probe_snapshot": fixture.rollback_probe_snapshot,
            "kill_switch_probe_snapshot": fixture.kill_switch_probe_snapshot,
        }
        snapshots[field_name.removesuffix("_hash")] = blocked_snapshot
        blocked_gate = build_legacy_sql_connector_runtime_pr_gate(
            command=fixture.command.model_copy(update={field_name: blocked_snapshot.evidence_hash}),
            bundle=fixture.bundle,
            adr_gate=fixture.adr_gate,
            checked_by="runtime-pr-gate-test",
            checked_at_utc=checked_at + timedelta(seconds=2),
            **snapshots,
        )
        assert blocked_gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
        assert expected_reason in blocked_gate.blocking_reasons
        assert not blocked_gate.runtime_pr_gate_ready

    runtime_command = build_legacy_sql_connector_runtime_pr_gate_command(
        adr_gate=fixture.adr_gate,
        code_review_snapshot=fixture.code_review_snapshot,
        test_container_snapshot=fixture.test_container_snapshot,
        secret_binding_snapshot=fixture.secret_binding_snapshot,
        network_binding_snapshot=fixture.network_binding_snapshot,
        rollback_probe_snapshot=fixture.rollback_probe_snapshot,
        kill_switch_probe_snapshot=fixture.kill_switch_probe_snapshot,
        requested_by="runtime-pr-gate-test",
        merge_requested=True,
        runtime_code_merge_requested=True,
        socket_runtime_execution_requested=True,
        secret_materialization_requested=True,
        raw_data_access_requested=True,
    )
    runtime_gate = build_legacy_sql_connector_runtime_pr_gate(
        command=runtime_command,
        bundle=fixture.bundle,
        adr_gate=fixture.adr_gate,
        code_review_snapshot=fixture.code_review_snapshot,
        test_container_snapshot=fixture.test_container_snapshot,
        secret_binding_snapshot=fixture.secret_binding_snapshot,
        network_binding_snapshot=fixture.network_binding_snapshot,
        rollback_probe_snapshot=fixture.rollback_probe_snapshot,
        kill_switch_probe_snapshot=fixture.kill_switch_probe_snapshot,
        checked_by="runtime-pr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert runtime_gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
    assert "merge_requires_future_runtime_merge_gate" in runtime_gate.blocking_reasons
    assert "runtime_code_merge_requires_future_runtime_merge_gate" in runtime_gate.blocking_reasons
    assert "socket_runtime_execution_requires_future_execution_gate" in runtime_gate.blocking_reasons
    assert "secret_materialization_requires_future_secret_gate" in runtime_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in runtime_gate.blocking_reasons
    assert not runtime_gate.merge_allowed
    assert not runtime_gate.runtime_code_merge_allowed
    assert not runtime_gate.real_connection_opened


def test_pg_legacy_sql_runtime_pr_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_runtime_pr_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_runtime_pr_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.runtime_pr_gate_ready
    assert report.adr_gate_required
    assert report.code_review_snapshot_required
    assert report.test_container_snapshot_required
    assert report.secret_binding_snapshot_required
    assert report.network_binding_snapshot_required
    assert report.rollback_probe_snapshot_required
    assert report.kill_switch_probe_snapshot_required
    assert report.adr_gate_missing_blocked
    assert report.code_review_missing_blocked
    assert report.test_container_missing_blocked
    assert report.secret_binding_missing_blocked
    assert report.network_binding_missing_blocked
    assert report.rollback_probe_missing_blocked
    assert report.kill_switch_probe_missing_blocked
    assert report.merge_request_blocked
    assert report.future_runtime_merge_gate_required
    assert report.future_live_secret_rotation_gate_required
    assert report.future_import_dry_run_gate_required
    assert not report.merge_allowed
    assert not report.runtime_code_merge_allowed
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
    assert report.evidence_hash == build_legacy_sql_connector_runtime_pr_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def runtime_pr_fixture(tmp_path: Path) -> RuntimePrFixture:
    checked_at = datetime(2026, 6, 20, 12, tzinfo=UTC)
    checked_by = "runtime-pr-gate-test"
    adr_fixture = socket_secret_adr_fixture(tmp_path)
    code_review_snapshot = build_legacy_sql_connector_runtime_pr_code_review_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    test_container_snapshot = build_legacy_sql_connector_runtime_pr_test_container_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    secret_binding_snapshot = build_legacy_sql_connector_runtime_pr_secret_binding_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    network_binding_snapshot = build_legacy_sql_connector_runtime_pr_network_binding_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    rollback_probe_snapshot = build_legacy_sql_connector_runtime_pr_rollback_probe_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    kill_switch_probe_snapshot = build_legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot(
        adr_gate=adr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    command = build_legacy_sql_connector_runtime_pr_gate_command(
        adr_gate=adr_fixture.gate,
        code_review_snapshot=code_review_snapshot,
        test_container_snapshot=test_container_snapshot,
        secret_binding_snapshot=secret_binding_snapshot,
        network_binding_snapshot=network_binding_snapshot,
        rollback_probe_snapshot=rollback_probe_snapshot,
        kill_switch_probe_snapshot=kill_switch_probe_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_runtime_pr_gate(
        command=command,
        bundle=adr_fixture.bundle,
        adr_gate=adr_fixture.gate,
        code_review_snapshot=code_review_snapshot,
        test_container_snapshot=test_container_snapshot,
        secret_binding_snapshot=secret_binding_snapshot,
        network_binding_snapshot=network_binding_snapshot,
        rollback_probe_snapshot=rollback_probe_snapshot,
        kill_switch_probe_snapshot=kill_switch_probe_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    return RuntimePrFixture(
        bundle=adr_fixture.bundle,
        adr_gate=adr_fixture.gate,
        code_review_snapshot=code_review_snapshot,
        test_container_snapshot=test_container_snapshot,
        secret_binding_snapshot=secret_binding_snapshot,
        network_binding_snapshot=network_binding_snapshot,
        rollback_probe_snapshot=rollback_probe_snapshot,
        kill_switch_probe_snapshot=kill_switch_probe_snapshot,
        command=command,
        gate=gate,
    )
