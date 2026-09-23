from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_connector_runtime_merge_gate import (
    LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    LegacySqlConnectorRuntimeMergeGateCommand,
    LegacySqlConnectorRuntimeMergeGateEvidence,
    LegacySqlConnectorRuntimeMergeGateStatus,
    build_legacy_sql_connector_runtime_merge_branch_protection_snapshot,
    build_legacy_sql_connector_runtime_merge_container_provenance_snapshot,
    build_legacy_sql_connector_runtime_merge_gate,
    build_legacy_sql_connector_runtime_merge_gate_command,
    build_legacy_sql_connector_runtime_merge_gate_hash,
    build_legacy_sql_connector_runtime_merge_gate_smoke_report_hash,
    build_legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot,
    build_legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot,
    build_legacy_sql_connector_runtime_merge_security_scan_snapshot,
    build_legacy_sql_connector_runtime_merge_snapshot_hash,
    exit_code_for_report,
    run_legacy_sql_connector_runtime_merge_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_runtime_pr_gate import (
    LegacySqlConnectorRuntimePrGateEvidence,
    LegacySqlConnectorRuntimePrGateStatus,
    build_legacy_sql_connector_runtime_pr_gate_hash,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_runtime_pr_gate import runtime_pr_fixture

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class RuntimeMergeFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence
    branch_protection_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot
    security_scan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot
    container_provenance_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot
    secret_rotation_plan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot
    kill_switch_drill_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot
    command: LegacySqlConnectorRuntimeMergeGateCommand
    gate: LegacySqlConnectorRuntimeMergeGateEvidence


def test_legacy_sql_runtime_merge_gate_binds_pr_branch_scan_provenance_rotation_and_drill_without_runtime(
    tmp_path: Path,
) -> None:
    fixture = runtime_merge_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_runtime_merge_gate.v1"
    assert gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.READY
    assert gate.runtime_merge_gate_ready
    assert gate.runtime_pr_gate_hash_valid
    assert gate.runtime_pr_gate_ready
    assert gate.runtime_pr_gate_bound
    assert gate.branch_protection_snapshot_hash_valid
    assert gate.branch_protection_snapshot_bound
    assert gate.branch_protection_passed
    assert gate.security_scan_snapshot_hash_valid
    assert gate.security_scan_snapshot_bound
    assert gate.security_scan_passed
    assert gate.container_provenance_snapshot_hash_valid
    assert gate.container_provenance_snapshot_bound
    assert gate.container_provenance_passed
    assert gate.secret_rotation_plan_snapshot_hash_valid
    assert gate.secret_rotation_plan_snapshot_bound
    assert gate.secret_rotation_plan_passed
    assert gate.kill_switch_drill_snapshot_hash_valid
    assert gate.kill_switch_drill_snapshot_bound
    assert gate.kill_switch_drill_passed
    assert gate.future_runtime_activation_gate_required
    assert gate.future_live_connection_gate_required
    assert gate.future_import_dry_run_gate_required
    assert not gate.merge_allowed
    assert not gate.runtime_code_merge_allowed
    assert not gate.activatable_runtime_allowed
    assert not gate.socket_runtime_execution_allowed
    assert not gate.secret_materialization_allowed
    assert not gate.live_secret_rotation_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_runtime_merge_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_runtime_merge_gate_blocks_missing_inputs_and_activation_requests(tmp_path: Path) -> None:
    fixture = runtime_merge_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 14, tzinfo=UTC)

    blocked_pr = fixture.runtime_pr_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimePrGateStatus.BLOCKED,
            "runtime_pr_gate_ready": False,
            "blocking_reasons": ("runtime_merge_test_pr_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_pr = blocked_pr.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_pr_gate_hash(blocked_pr)}
    )
    blocked_pr_gate = build_legacy_sql_connector_runtime_merge_gate(
        command=fixture.command.model_copy(update={"runtime_pr_gate_evidence_hash": blocked_pr.evidence_hash}),
        bundle=fixture.bundle,
        runtime_pr_gate=blocked_pr,
        branch_protection_snapshot=fixture.branch_protection_snapshot,
        security_scan_snapshot=fixture.security_scan_snapshot,
        container_provenance_snapshot=fixture.container_provenance_snapshot,
        secret_rotation_plan_snapshot=fixture.secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=fixture.kill_switch_drill_snapshot,
        checked_by="runtime-merge-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_pr_gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
    assert "runtime_pr_gate_not_ready" in blocked_pr_gate.blocking_reasons

    for field_name, snapshot, failed_control, expected_reason in (
        (
            "branch_protection_snapshot_hash",
            fixture.branch_protection_snapshot,
            "branch_protection_enabled",
            "branch_protection_snapshot_failed",
        ),
        ("security_scan_snapshot_hash", fixture.security_scan_snapshot, "sast_passed", "security_scan_snapshot_failed"),
        (
            "container_provenance_snapshot_hash",
            fixture.container_provenance_snapshot,
            "slsa_provenance_present",
            "container_provenance_snapshot_failed",
        ),
        (
            "secret_rotation_plan_snapshot_hash",
            fixture.secret_rotation_plan_snapshot,
            "rotation_plan_reviewed",
            "secret_rotation_plan_snapshot_failed",
        ),
        (
            "kill_switch_drill_snapshot_hash",
            fixture.kill_switch_drill_snapshot,
            "kill_switch_drill_passed",
            "kill_switch_drill_snapshot_failed",
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
            update={"evidence_hash": build_legacy_sql_connector_runtime_merge_snapshot_hash(blocked_snapshot)}
        )
        snapshots = {
            "branch_protection_snapshot": fixture.branch_protection_snapshot,
            "security_scan_snapshot": fixture.security_scan_snapshot,
            "container_provenance_snapshot": fixture.container_provenance_snapshot,
            "secret_rotation_plan_snapshot": fixture.secret_rotation_plan_snapshot,
            "kill_switch_drill_snapshot": fixture.kill_switch_drill_snapshot,
        }
        snapshots[field_name.removesuffix("_hash")] = blocked_snapshot
        blocked_gate = build_legacy_sql_connector_runtime_merge_gate(
            command=fixture.command.model_copy(update={field_name: blocked_snapshot.evidence_hash}),
            bundle=fixture.bundle,
            runtime_pr_gate=fixture.runtime_pr_gate,
            checked_by="runtime-merge-gate-test",
            checked_at_utc=checked_at + timedelta(seconds=2),
            **snapshots,
        )
        assert blocked_gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
        assert expected_reason in blocked_gate.blocking_reasons
        assert not blocked_gate.runtime_merge_gate_ready

    runtime_command = build_legacy_sql_connector_runtime_merge_gate_command(
        runtime_pr_gate=fixture.runtime_pr_gate,
        branch_protection_snapshot=fixture.branch_protection_snapshot,
        security_scan_snapshot=fixture.security_scan_snapshot,
        container_provenance_snapshot=fixture.container_provenance_snapshot,
        secret_rotation_plan_snapshot=fixture.secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=fixture.kill_switch_drill_snapshot,
        requested_by="runtime-merge-gate-test",
        merge_requested=True,
        runtime_code_merge_requested=True,
        activatable_runtime_requested=True,
        socket_runtime_execution_requested=True,
        secret_materialization_requested=True,
        live_secret_rotation_requested=True,
        raw_data_access_requested=True,
    )
    runtime_gate = build_legacy_sql_connector_runtime_merge_gate(
        command=runtime_command,
        bundle=fixture.bundle,
        runtime_pr_gate=fixture.runtime_pr_gate,
        branch_protection_snapshot=fixture.branch_protection_snapshot,
        security_scan_snapshot=fixture.security_scan_snapshot,
        container_provenance_snapshot=fixture.container_provenance_snapshot,
        secret_rotation_plan_snapshot=fixture.secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=fixture.kill_switch_drill_snapshot,
        checked_by="runtime-merge-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert runtime_gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
    assert "merge_requires_future_activation_gate" in runtime_gate.blocking_reasons
    assert "runtime_code_merge_requires_future_activation_gate" in runtime_gate.blocking_reasons
    assert "activatable_runtime_requires_future_activation_gate" in runtime_gate.blocking_reasons
    assert "socket_runtime_execution_requires_future_live_connection_gate" in runtime_gate.blocking_reasons
    assert "secret_materialization_requires_future_secret_gate" in runtime_gate.blocking_reasons
    assert "live_secret_rotation_requires_future_rotation_gate" in runtime_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in runtime_gate.blocking_reasons
    assert not runtime_gate.merge_allowed
    assert not runtime_gate.activatable_runtime_allowed
    assert not runtime_gate.real_connection_opened


def test_pg_legacy_sql_runtime_merge_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_runtime_merge_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_runtime_merge_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.runtime_merge_gate_ready
    assert report.runtime_pr_gate_required
    assert report.branch_protection_snapshot_required
    assert report.security_scan_snapshot_required
    assert report.container_provenance_snapshot_required
    assert report.secret_rotation_plan_snapshot_required
    assert report.kill_switch_drill_snapshot_required
    assert report.runtime_pr_gate_missing_blocked
    assert report.branch_protection_missing_blocked
    assert report.security_scan_missing_blocked
    assert report.container_provenance_missing_blocked
    assert report.secret_rotation_plan_missing_blocked
    assert report.kill_switch_drill_missing_blocked
    assert report.activation_request_blocked
    assert report.future_runtime_activation_gate_required
    assert report.future_live_connection_gate_required
    assert report.future_import_dry_run_gate_required
    assert not report.merge_allowed
    assert not report.runtime_code_merge_allowed
    assert not report.activatable_runtime_allowed
    assert not report.socket_runtime_execution_allowed
    assert not report.secret_materialization_allowed
    assert not report.live_secret_rotation_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_runtime_merge_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def runtime_merge_fixture(tmp_path: Path) -> RuntimeMergeFixture:
    checked_at = datetime(2026, 6, 20, 13, tzinfo=UTC)
    checked_by = "runtime-merge-gate-test"
    pr_fixture = runtime_pr_fixture(tmp_path)
    branch_protection_snapshot = build_legacy_sql_connector_runtime_merge_branch_protection_snapshot(
        runtime_pr_gate=pr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    security_scan_snapshot = build_legacy_sql_connector_runtime_merge_security_scan_snapshot(
        runtime_pr_gate=pr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    container_provenance_snapshot = build_legacy_sql_connector_runtime_merge_container_provenance_snapshot(
        runtime_pr_gate=pr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    secret_rotation_plan_snapshot = build_legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot(
        runtime_pr_gate=pr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    kill_switch_drill_snapshot = build_legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot(
        runtime_pr_gate=pr_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    command = build_legacy_sql_connector_runtime_merge_gate_command(
        runtime_pr_gate=pr_fixture.gate,
        branch_protection_snapshot=branch_protection_snapshot,
        security_scan_snapshot=security_scan_snapshot,
        container_provenance_snapshot=container_provenance_snapshot,
        secret_rotation_plan_snapshot=secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=kill_switch_drill_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_runtime_merge_gate(
        command=command,
        bundle=pr_fixture.bundle,
        runtime_pr_gate=pr_fixture.gate,
        branch_protection_snapshot=branch_protection_snapshot,
        security_scan_snapshot=security_scan_snapshot,
        container_provenance_snapshot=container_provenance_snapshot,
        secret_rotation_plan_snapshot=secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=kill_switch_drill_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    return RuntimeMergeFixture(
        bundle=pr_fixture.bundle,
        runtime_pr_gate=pr_fixture.gate,
        branch_protection_snapshot=branch_protection_snapshot,
        security_scan_snapshot=security_scan_snapshot,
        container_provenance_snapshot=container_provenance_snapshot,
        secret_rotation_plan_snapshot=secret_rotation_plan_snapshot,
        kill_switch_drill_snapshot=kill_switch_drill_snapshot,
        command=command,
        gate=gate,
    )
