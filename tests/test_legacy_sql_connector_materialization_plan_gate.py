from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_execution_readiness_review_gate import (
    LegacySqlConnectorExecutionReadinessReviewGateStatus,
    build_legacy_sql_connector_execution_readiness_review_gate_hash,
)
from suite.platform.legacy_sql_connector_materialization_plan_gate import (
    LegacySqlConnectorMaterializationKillSwitchSnapshot,
    LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    LegacySqlConnectorMaterializationPlanGateCommand,
    LegacySqlConnectorMaterializationPlanGateEvidence,
    LegacySqlConnectorMaterializationPlanGateStatus,
    LegacySqlConnectorMaterializationProviderProfileSnapshot,
    build_legacy_sql_connector_materialization_kill_switch_snapshot,
    build_legacy_sql_connector_materialization_kill_switch_snapshot_hash,
    build_legacy_sql_connector_materialization_operator_mfa_snapshot,
    build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash,
    build_legacy_sql_connector_materialization_plan_gate,
    build_legacy_sql_connector_materialization_plan_gate_command,
    build_legacy_sql_connector_materialization_plan_gate_hash,
    build_legacy_sql_connector_materialization_plan_gate_smoke_report_hash,
    build_legacy_sql_connector_materialization_provider_profile_snapshot,
    exit_code_for_report,
    run_legacy_sql_connector_materialization_plan_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
    review_gate_fixture,
)

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class MaterializationPlanFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    review_gate_evidence_hash: str
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot
    command: LegacySqlConnectorMaterializationPlanGateCommand
    gate: LegacySqlConnectorMaterializationPlanGateEvidence


def test_legacy_sql_materialization_plan_gate_binds_review_provider_mfa_and_kill_switch_without_execution(
    tmp_path: Path,
) -> None:
    fixture = materialization_plan_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_materialization_plan_gate.v1"
    assert gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.READY
    assert gate.materialization_plan_ready
    assert gate.review_gate_hash_valid
    assert gate.review_gate_ready
    assert gate.review_gate_bound
    assert gate.provider_profile_snapshot_hash_valid
    assert gate.provider_profile_snapshot_bound
    assert gate.provider_profiles_current
    assert gate.provider_metadata_only_boundary_attested
    assert gate.operator_mfa_snapshot_hash_valid
    assert gate.operator_mfa_snapshot_bound
    assert gate.operator_authorized_for_legacy_sql
    assert gate.operator_mfa_verified
    assert gate.compliance_window_active
    assert not gate.break_glass_requested
    assert gate.kill_switch_snapshot_hash_valid
    assert gate.kill_switch_snapshot_bound
    assert gate.kill_switch_armed
    assert not gate.tenant_connection_disabled
    assert not gate.global_connection_disabled
    assert not gate.manual_abort_requested
    assert gate.future_socket_materialization_implementation_gate_required
    assert gate.future_secret_materialization_implementation_gate_required
    assert gate.future_execution_implementation_required
    assert not gate.socket_materialization_allowed
    assert not gate.secret_materialization_allowed
    assert not gate.execution_implementation_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_materialization_plan_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_materialization_plan_gate_blocks_review_mfa_kill_switch_and_execution_requests(
    tmp_path: Path,
) -> None:
    fixture = materialization_plan_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 11, tzinfo=UTC)
    review_fixture = review_gate_fixture(tmp_path)

    blocked_review_gate = review_fixture.gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED,
            "execution_readiness_review_passed": False,
            "blocking_reasons": ("human_review_not_completed",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_review_gate = blocked_review_gate.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_review_gate_hash(blocked_review_gate)}
    )
    blocked_review = build_legacy_sql_connector_materialization_plan_gate(
        command=fixture.command.model_copy(update={"review_gate_evidence_hash": blocked_review_gate.evidence_hash}),
        bundle=fixture.bundle,
        review_gate=blocked_review_gate,
        provider_profile_snapshot=fixture.provider_profile_snapshot,
        operator_mfa_snapshot=fixture.operator_mfa_snapshot,
        kill_switch_snapshot=fixture.kill_switch_snapshot,
        checked_by="materialization-plan-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_review.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
    assert "review_gate_not_ready" in blocked_review.blocking_reasons
    assert not blocked_review.materialization_plan_ready

    blocked_operator = fixture.operator_mfa_snapshot.model_copy(
        update={"operator_mfa_verified": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_operator = blocked_operator.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash(blocked_operator)
        }
    )
    blocked_operator_gate = build_legacy_sql_connector_materialization_plan_gate(
        command=fixture.command.model_copy(update={"operator_mfa_snapshot_hash": blocked_operator.evidence_hash}),
        bundle=fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=fixture.provider_profile_snapshot,
        operator_mfa_snapshot=blocked_operator,
        kill_switch_snapshot=fixture.kill_switch_snapshot,
        checked_by="materialization-plan-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    assert blocked_operator_gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
    assert "operator_mfa_not_verified" in blocked_operator_gate.blocking_reasons

    blocked_kill_switch = fixture.kill_switch_snapshot.model_copy(
        update={"tenant_connection_disabled": True, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_kill_switch = blocked_kill_switch.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_materialization_kill_switch_snapshot_hash(blocked_kill_switch)
        }
    )
    blocked_kill_switch_gate = build_legacy_sql_connector_materialization_plan_gate(
        command=fixture.command.model_copy(update={"kill_switch_snapshot_hash": blocked_kill_switch.evidence_hash}),
        bundle=fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=fixture.provider_profile_snapshot,
        operator_mfa_snapshot=fixture.operator_mfa_snapshot,
        kill_switch_snapshot=blocked_kill_switch,
        checked_by="materialization-plan-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert blocked_kill_switch_gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
    assert "tenant_connection_kill_switch_disabled" in blocked_kill_switch_gate.blocking_reasons

    execution_command = build_legacy_sql_connector_materialization_plan_gate_command(
        bundle=fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=fixture.provider_profile_snapshot,
        operator_mfa_snapshot=fixture.operator_mfa_snapshot,
        kill_switch_snapshot=fixture.kill_switch_snapshot,
        requested_by="materialization-plan-gate-test",
        socket_materialization_requested=True,
        secret_materialization_requested=True,
        execution_implementation_requested=True,
    )
    execution_gate = build_legacy_sql_connector_materialization_plan_gate(
        command=execution_command,
        bundle=fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=fixture.provider_profile_snapshot,
        operator_mfa_snapshot=fixture.operator_mfa_snapshot,
        kill_switch_snapshot=fixture.kill_switch_snapshot,
        checked_by="materialization-plan-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    assert execution_gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
    assert "socket_materialization_requires_future_implementation_gate" in execution_gate.blocking_reasons
    assert "secret_materialization_requires_future_implementation_gate" in execution_gate.blocking_reasons
    assert "execution_implementation_requires_future_gate" in execution_gate.blocking_reasons
    assert not execution_gate.socket_materialization_allowed
    assert not execution_gate.secret_materialization_allowed
    assert not execution_gate.execution_implementation_allowed
    assert not execution_gate.real_connection_opened


def test_pg_legacy_sql_materialization_plan_gate_smoke_requires_plan_gate_and_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_materialization_plan_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_materialization_plan_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.materialization_plan_ready
    assert report.review_gate_required
    assert report.provider_profile_snapshot_required
    assert report.operator_mfa_snapshot_required
    assert report.kill_switch_snapshot_required
    assert report.review_gate_missing_blocked
    assert report.operator_mfa_missing_blocked
    assert report.kill_switch_disabled_blocked
    assert report.materialization_request_blocked
    assert report.future_socket_materialization_implementation_gate_required
    assert report.future_secret_materialization_implementation_gate_required
    assert report.future_execution_implementation_required
    assert not report.socket_materialization_allowed
    assert not report.secret_materialization_allowed
    assert not report.execution_implementation_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_materialization_plan_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0


def materialization_plan_fixture(tmp_path: Path) -> MaterializationPlanFixture:
    checked_at = datetime(2026, 6, 20, 10, tzinfo=UTC)
    checked_by = "materialization-plan-gate-test"
    review_fixture = review_gate_fixture(tmp_path)
    provider_profile_snapshot = build_legacy_sql_connector_materialization_provider_profile_snapshot(
        bundle=review_fixture.bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    operator_mfa_snapshot = build_legacy_sql_connector_materialization_operator_mfa_snapshot(
        bundle=review_fixture.bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    kill_switch_snapshot = build_legacy_sql_connector_materialization_kill_switch_snapshot(
        bundle=review_fixture.bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    command = build_legacy_sql_connector_materialization_plan_gate_command(
        bundle=review_fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_materialization_plan_gate(
        command=command,
        bundle=review_fixture.bundle,
        review_gate=review_fixture.gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    return MaterializationPlanFixture(
        bundle=review_fixture.bundle,
        review_gate_evidence_hash=review_fixture.gate.evidence_hash,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        command=command,
        gate=gate,
    )
