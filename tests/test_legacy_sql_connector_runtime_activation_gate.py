from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_connector_runtime_activation_gate import (
    LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    LegacySqlConnectorRuntimeActivationGateCommand,
    LegacySqlConnectorRuntimeActivationGateEvidence,
    LegacySqlConnectorRuntimeActivationGateStatus,
    build_legacy_sql_connector_runtime_activation_feature_flag_snapshot,
    build_legacy_sql_connector_runtime_activation_gate,
    build_legacy_sql_connector_runtime_activation_gate_command,
    build_legacy_sql_connector_runtime_activation_gate_hash,
    build_legacy_sql_connector_runtime_activation_gate_smoke_report_hash,
    build_legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot,
    build_legacy_sql_connector_runtime_activation_network_authorization_snapshot,
    build_legacy_sql_connector_runtime_activation_rollback_freeze_snapshot,
    build_legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot,
    build_legacy_sql_connector_runtime_activation_snapshot_hash,
    build_legacy_sql_connector_runtime_activation_tenant_approval_snapshot,
    exit_code_for_report,
    run_legacy_sql_connector_runtime_activation_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_runtime_merge_gate import (
    LegacySqlConnectorRuntimeMergeGateEvidence,
    LegacySqlConnectorRuntimeMergeGateStatus,
    build_legacy_sql_connector_runtime_merge_gate_hash,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_runtime_merge_gate import runtime_merge_fixture

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class RuntimeActivationFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence
    tenant_approval_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    feature_flag_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    secret_rotation_confirmation_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    network_authorization_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    rollback_freeze_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    kill_switch_arming_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot
    command: LegacySqlConnectorRuntimeActivationGateCommand
    gate: LegacySqlConnectorRuntimeActivationGateEvidence


def test_legacy_sql_runtime_activation_gate_binds_required_evidence_without_connection(
    tmp_path: Path,
) -> None:
    fixture = runtime_activation_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_runtime_activation_gate.v1"
    assert gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.READY
    assert gate.runtime_activation_gate_ready
    assert gate.runtime_merge_gate_hash_valid
    assert gate.runtime_merge_gate_ready
    assert gate.runtime_merge_gate_bound
    assert gate.tenant_approval_snapshot_hash_valid
    assert gate.tenant_approval_snapshot_bound
    assert gate.tenant_approval_passed
    assert gate.feature_flag_snapshot_hash_valid
    assert gate.feature_flag_snapshot_bound
    assert gate.feature_flag_passed
    assert gate.secret_rotation_confirmation_snapshot_hash_valid
    assert gate.secret_rotation_confirmation_snapshot_bound
    assert gate.secret_rotation_confirmation_passed
    assert gate.network_authorization_snapshot_hash_valid
    assert gate.network_authorization_snapshot_bound
    assert gate.network_authorization_passed
    assert gate.rollback_freeze_snapshot_hash_valid
    assert gate.rollback_freeze_snapshot_bound
    assert gate.rollback_freeze_passed
    assert gate.kill_switch_arming_snapshot_hash_valid
    assert gate.kill_switch_arming_snapshot_bound
    assert gate.kill_switch_arming_passed
    assert gate.future_live_connection_gate_required
    assert gate.future_secret_materialization_gate_required
    assert gate.future_import_dry_run_gate_required
    assert not gate.runtime_activation_allowed
    assert not gate.runtime_feature_flag_enabled
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
    assert gate.evidence_hash == build_legacy_sql_connector_runtime_activation_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_runtime_activation_gate_blocks_missing_inputs_and_direct_connection_requests(
    tmp_path: Path,
) -> None:
    fixture = runtime_activation_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 16, tzinfo=UTC)

    blocked_merge = fixture.runtime_merge_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED,
            "runtime_merge_gate_ready": False,
            "blocking_reasons": ("runtime_activation_test_merge_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_merge = blocked_merge.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_merge_gate_hash(blocked_merge)}
    )
    blocked_merge_gate = build_legacy_sql_connector_runtime_activation_gate(
        command=fixture.command.model_copy(update={"runtime_merge_gate_evidence_hash": blocked_merge.evidence_hash}),
        bundle=fixture.bundle,
        runtime_merge_gate=blocked_merge,
        tenant_approval_snapshot=fixture.tenant_approval_snapshot,
        feature_flag_snapshot=fixture.feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=fixture.secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=fixture.network_authorization_snapshot,
        rollback_freeze_snapshot=fixture.rollback_freeze_snapshot,
        kill_switch_arming_snapshot=fixture.kill_switch_arming_snapshot,
        checked_by="runtime-activation-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_merge_gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
    assert "runtime_merge_gate_not_ready" in blocked_merge_gate.blocking_reasons

    for field_name, snapshot, failed_control, expected_reason in (
        (
            "tenant_approval_snapshot_hash",
            fixture.tenant_approval_snapshot,
            "tenant_owner_activation_approval_recorded",
            "tenant_approval_snapshot_failed",
        ),
        (
            "feature_flag_snapshot_hash",
            fixture.feature_flag_snapshot,
            "runtime_feature_flag_default_off",
            "feature_flag_snapshot_failed",
        ),
        (
            "secret_rotation_confirmation_snapshot_hash",
            fixture.secret_rotation_confirmation_snapshot,
            "rotation_window_confirmed",
            "secret_rotation_confirmation_snapshot_failed",
        ),
        (
            "network_authorization_snapshot_hash",
            fixture.network_authorization_snapshot,
            "egress_policy_approved",
            "network_authorization_snapshot_failed",
        ),
        (
            "rollback_freeze_snapshot_hash",
            fixture.rollback_freeze_snapshot,
            "deployment_freeze_window_confirmed",
            "rollback_freeze_snapshot_failed",
        ),
        (
            "kill_switch_arming_snapshot_hash",
            fixture.kill_switch_arming_snapshot,
            "tenant_kill_switch_armed",
            "kill_switch_arming_snapshot_failed",
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
            update={"evidence_hash": build_legacy_sql_connector_runtime_activation_snapshot_hash(blocked_snapshot)}
        )
        snapshots = {
            "tenant_approval_snapshot": fixture.tenant_approval_snapshot,
            "feature_flag_snapshot": fixture.feature_flag_snapshot,
            "secret_rotation_confirmation_snapshot": fixture.secret_rotation_confirmation_snapshot,
            "network_authorization_snapshot": fixture.network_authorization_snapshot,
            "rollback_freeze_snapshot": fixture.rollback_freeze_snapshot,
            "kill_switch_arming_snapshot": fixture.kill_switch_arming_snapshot,
        }
        snapshots[field_name.removesuffix("_hash")] = blocked_snapshot
        blocked_gate = build_legacy_sql_connector_runtime_activation_gate(
            command=fixture.command.model_copy(update={field_name: blocked_snapshot.evidence_hash}),
            bundle=fixture.bundle,
            runtime_merge_gate=fixture.runtime_merge_gate,
            checked_by="runtime-activation-gate-test",
            checked_at_utc=checked_at + timedelta(seconds=2),
            **snapshots,
        )
        assert blocked_gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
        assert expected_reason in blocked_gate.blocking_reasons
        assert not blocked_gate.runtime_activation_gate_ready

    connection_command = build_legacy_sql_connector_runtime_activation_gate_command(
        runtime_merge_gate=fixture.runtime_merge_gate,
        tenant_approval_snapshot=fixture.tenant_approval_snapshot,
        feature_flag_snapshot=fixture.feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=fixture.secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=fixture.network_authorization_snapshot,
        rollback_freeze_snapshot=fixture.rollback_freeze_snapshot,
        kill_switch_arming_snapshot=fixture.kill_switch_arming_snapshot,
        requested_by="runtime-activation-gate-test",
        runtime_activation_requested=True,
        runtime_feature_flag_enable_requested=True,
        activatable_runtime_requested=True,
        socket_runtime_execution_requested=True,
        secret_materialization_requested=True,
        live_secret_rotation_requested=True,
        raw_data_access_requested=True,
    )
    connection_gate = build_legacy_sql_connector_runtime_activation_gate(
        command=connection_command,
        bundle=fixture.bundle,
        runtime_merge_gate=fixture.runtime_merge_gate,
        tenant_approval_snapshot=fixture.tenant_approval_snapshot,
        feature_flag_snapshot=fixture.feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=fixture.secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=fixture.network_authorization_snapshot,
        rollback_freeze_snapshot=fixture.rollback_freeze_snapshot,
        kill_switch_arming_snapshot=fixture.kill_switch_arming_snapshot,
        checked_by="runtime-activation-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert connection_gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
    assert "runtime_activation_requires_future_live_connection_gate" in connection_gate.blocking_reasons
    assert "runtime_feature_flag_enable_requires_future_live_connection_gate" in connection_gate.blocking_reasons
    assert "activatable_runtime_requires_future_live_connection_gate" in connection_gate.blocking_reasons
    assert "socket_runtime_execution_requires_future_live_connection_gate" in connection_gate.blocking_reasons
    assert "secret_materialization_requires_future_secret_gate" in connection_gate.blocking_reasons
    assert "live_secret_rotation_requires_future_rotation_gate" in connection_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in connection_gate.blocking_reasons
    assert not connection_gate.runtime_activation_allowed
    assert not connection_gate.runtime_feature_flag_enabled
    assert not connection_gate.activatable_runtime_allowed
    assert not connection_gate.real_connection_opened


def test_pg_legacy_sql_runtime_activation_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_runtime_activation_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_runtime_activation_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.runtime_activation_gate_ready
    assert report.runtime_merge_gate_required
    assert report.tenant_approval_snapshot_required
    assert report.feature_flag_snapshot_required
    assert report.secret_rotation_confirmation_snapshot_required
    assert report.network_authorization_snapshot_required
    assert report.rollback_freeze_snapshot_required
    assert report.kill_switch_arming_snapshot_required
    assert report.runtime_merge_gate_missing_blocked
    assert report.tenant_approval_missing_blocked
    assert report.feature_flag_missing_blocked
    assert report.secret_rotation_confirmation_missing_blocked
    assert report.network_authorization_missing_blocked
    assert report.rollback_freeze_missing_blocked
    assert report.kill_switch_arming_missing_blocked
    assert report.direct_connection_request_blocked
    assert report.future_live_connection_gate_required
    assert report.future_secret_materialization_gate_required
    assert report.future_import_dry_run_gate_required
    assert not report.runtime_activation_allowed
    assert not report.runtime_feature_flag_enabled
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
    assert report.evidence_hash == build_legacy_sql_connector_runtime_activation_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def runtime_activation_fixture(tmp_path: Path) -> RuntimeActivationFixture:
    checked_at = datetime(2026, 6, 20, 15, tzinfo=UTC)
    checked_by = "runtime-activation-gate-test"
    merge_fixture = runtime_merge_fixture(tmp_path)
    tenant_approval_snapshot = build_legacy_sql_connector_runtime_activation_tenant_approval_snapshot(
        runtime_merge_gate=merge_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    feature_flag_snapshot = build_legacy_sql_connector_runtime_activation_feature_flag_snapshot(
        runtime_merge_gate=merge_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    secret_rotation_confirmation_snapshot = (
        build_legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot(
            runtime_merge_gate=merge_fixture.gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=3),
        )
    )
    network_authorization_snapshot = build_legacy_sql_connector_runtime_activation_network_authorization_snapshot(
        runtime_merge_gate=merge_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    rollback_freeze_snapshot = build_legacy_sql_connector_runtime_activation_rollback_freeze_snapshot(
        runtime_merge_gate=merge_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    kill_switch_arming_snapshot = build_legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot(
        runtime_merge_gate=merge_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    command = build_legacy_sql_connector_runtime_activation_gate_command(
        runtime_merge_gate=merge_fixture.gate,
        tenant_approval_snapshot=tenant_approval_snapshot,
        feature_flag_snapshot=feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=network_authorization_snapshot,
        rollback_freeze_snapshot=rollback_freeze_snapshot,
        kill_switch_arming_snapshot=kill_switch_arming_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_runtime_activation_gate(
        command=command,
        bundle=merge_fixture.bundle,
        runtime_merge_gate=merge_fixture.gate,
        tenant_approval_snapshot=tenant_approval_snapshot,
        feature_flag_snapshot=feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=network_authorization_snapshot,
        rollback_freeze_snapshot=rollback_freeze_snapshot,
        kill_switch_arming_snapshot=kill_switch_arming_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    return RuntimeActivationFixture(
        bundle=merge_fixture.bundle,
        runtime_merge_gate=merge_fixture.gate,
        tenant_approval_snapshot=tenant_approval_snapshot,
        feature_flag_snapshot=feature_flag_snapshot,
        secret_rotation_confirmation_snapshot=secret_rotation_confirmation_snapshot,
        network_authorization_snapshot=network_authorization_snapshot,
        rollback_freeze_snapshot=rollback_freeze_snapshot,
        kill_switch_arming_snapshot=kill_switch_arming_snapshot,
        command=command,
        gate=gate,
    )
