from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_connector_execution_readiness_review_gate import (
    LegacySqlConnectorExecutionReadinessChangeControl,
    LegacySqlConnectorExecutionReadinessHumanReview,
    LegacySqlConnectorExecutionReadinessRestoreDrill,
    LegacySqlConnectorExecutionReadinessReviewGateCommand,
    LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    LegacySqlConnectorExecutionReadinessReviewGateStatus,
    build_legacy_sql_connector_execution_readiness_change_control,
    build_legacy_sql_connector_execution_readiness_human_review,
    build_legacy_sql_connector_execution_readiness_restore_drill,
    build_legacy_sql_connector_execution_readiness_review_gate,
    build_legacy_sql_connector_execution_readiness_review_gate_command,
    build_legacy_sql_connector_execution_readiness_review_gate_hash,
    build_legacy_sql_connector_execution_readiness_review_gate_smoke_report_hash,
    exit_code_for_report,
    run_legacy_sql_connector_execution_readiness_review_gate_smoke_from_env,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    build_legacy_sql_connector_real_connection_audit_plan,
    build_legacy_sql_connector_real_connection_executor_command,
    build_legacy_sql_connector_real_connection_executor_contract,
    build_legacy_sql_connector_real_connection_executor_policy_bundle,
    build_legacy_sql_connector_real_connection_kill_switch_policy,
    build_legacy_sql_connector_real_connection_timeout_retry_policy,
)
from test_legacy_sql_connector_real_connection_executor import ready_preflight

ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class LiveDatabase:
    migration_resource: str
    worker_resource: str


@dataclass(frozen=True)
class ReviewGateFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    human_review: LegacySqlConnectorExecutionReadinessHumanReview
    change_control: LegacySqlConnectorExecutionReadinessChangeControl
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand
    gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence


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


def test_legacy_sql_execution_readiness_review_gate_requires_review_control_and_stays_non_executing(
    tmp_path: Path,
) -> None:
    fixture = review_gate_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_execution_readiness_review_gate.v1"
    assert gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.READY
    assert gate.execution_readiness_review_passed
    assert gate.policy_bundle_hash_valid
    assert gate.policy_bundle_ready
    assert gate.policy_bundle_bound
    assert gate.human_review_hash_valid
    assert gate.human_review_bound
    assert gate.human_review_completed
    assert gate.reviewer_independent
    assert gate.reviewer_mfa_verified
    assert gate.change_control_hash_valid
    assert gate.change_control_bound
    assert gate.change_approved
    assert gate.maintenance_window_active
    assert gate.rollback_plan_verified
    assert gate.risk_acceptance_signed
    assert gate.restore_drill_hash_valid
    assert gate.restore_drill_bound
    assert gate.restore_drill_passed
    assert gate.policy_store_restored
    assert gate.tenant_isolation_reverified
    assert gate.kill_switch_armed
    assert not gate.tenant_connection_disabled
    assert not gate.global_connection_disabled
    assert not gate.manual_abort_requested
    assert gate.future_materialization_plan_gate_required
    assert not gate.socket_materialization_planning_allowed
    assert not gate.secret_materialization_planning_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_execution_readiness_review_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_execution_readiness_review_gate_blocks_missing_review_change_kill_switch_and_planning(
    tmp_path: Path,
) -> None:
    fixture = review_gate_fixture(tmp_path)
    checked_at = datetime(2026, 6, 19, 11, tzinfo=UTC)

    missing_review = build_legacy_sql_connector_execution_readiness_human_review(
        bundle=fixture.bundle,
        reviewer_principal_ref="principal:legacy-sql-execution-reviewer",
        review_ticket_ref="review-ticket:legacy-sql-execution-readiness",
        approval_reference="approval:legacy-sql-execution-readiness",
        human_review_completed=False,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at,
    )
    missing_review_command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=fixture.bundle,
        human_review=missing_review,
        change_control=fixture.change_control,
        restore_drill=fixture.restore_drill,
        requested_by="execution-readiness-review-gate-test",
    )
    missing_review_gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=missing_review_command,
        bundle=fixture.bundle,
        human_review=missing_review,
        change_control=fixture.change_control,
        restore_drill=fixture.restore_drill,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert missing_review_gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
    assert "human_review_not_completed" in missing_review_gate.blocking_reasons
    assert not missing_review_gate.execution_readiness_review_passed

    incomplete_change = build_legacy_sql_connector_execution_readiness_change_control(
        bundle=fixture.bundle,
        change_request_ref="change-request:legacy-sql-execution-readiness",
        maintenance_window_ref="maintenance-window:legacy-sql-execution-readiness",
        rollback_plan_ref="rollback-plan:legacy-sql-execution-readiness",
        risk_acceptance_ref="risk-acceptance:legacy-sql-execution-readiness",
        rollback_plan_verified=False,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    incomplete_change_command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=fixture.bundle,
        human_review=fixture.human_review,
        change_control=incomplete_change,
        restore_drill=fixture.restore_drill,
        requested_by="execution-readiness-review-gate-test",
    )
    incomplete_change_gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=incomplete_change_command,
        bundle=fixture.bundle,
        human_review=fixture.human_review,
        change_control=incomplete_change,
        restore_drill=fixture.restore_drill,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert incomplete_change_gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
    assert "rollback_plan_not_verified" in incomplete_change_gate.blocking_reasons

    disabled_policy = fixture.bundle.kill_switch_policy.model_copy(update={"tenant_connection_disabled": True})
    disabled_bundle = fixture.bundle.model_copy(update={"kill_switch_policy": disabled_policy})
    disabled_gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=fixture.command,
        bundle=disabled_bundle,
        human_review=fixture.human_review,
        change_control=fixture.change_control,
        restore_drill=fixture.restore_drill,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    assert disabled_gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
    assert "tenant_connection_kill_switch_disabled" in disabled_gate.blocking_reasons
    assert not disabled_gate.real_connection_opened

    planning_command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=fixture.bundle,
        human_review=fixture.human_review,
        change_control=fixture.change_control,
        restore_drill=fixture.restore_drill,
        requested_by="execution-readiness-review-gate-test",
        socket_materialization_planning_requested=True,
        secret_materialization_planning_requested=True,
    )
    planning_gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=planning_command,
        bundle=fixture.bundle,
        human_review=fixture.human_review,
        change_control=fixture.change_control,
        restore_drill=fixture.restore_drill,
        checked_by="execution-readiness-review-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    assert planning_gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
    assert "socket_materialization_planning_requires_future_gate" in planning_gate.blocking_reasons
    assert "secret_materialization_planning_requires_future_gate" in planning_gate.blocking_reasons
    assert not planning_gate.socket_materialization_planning_allowed
    assert not planning_gate.secret_materialization_planning_allowed
    assert not planning_gate.network_socket_opened
    assert not planning_gate.secret_material_resolved


def test_pg_legacy_sql_execution_readiness_review_gate_smoke_requires_review_gate_and_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_execution_readiness_review_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_execution_readiness_review_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.review_gate_ready
    assert report.stored_policy_bundle_required
    assert report.human_review_required
    assert report.change_control_required
    assert report.restore_drill_required
    assert report.kill_switch_required
    assert report.missing_human_review_blocked
    assert report.change_control_missing_blocked
    assert report.kill_switch_disabled_blocked
    assert report.materialization_planning_request_blocked
    assert report.future_materialization_plan_gate_required
    assert not report.socket_materialization_planning_allowed
    assert not report.secret_materialization_planning_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_execution_readiness_review_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    payload = report.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def review_gate_fixture(tmp_path: Path) -> ReviewGateFixture:
    checked_at = datetime(2026, 6, 19, 10, tzinfo=UTC)
    checked_by = "execution-readiness-review-gate-test"
    _ = tmp_path
    preflight = ready_preflight()
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=16),
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=17),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=18),
    )
    executor_command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash="sha256:" + "a" * 64,
        requested_by=checked_by,
    )
    executor_contract = build_legacy_sql_connector_real_connection_executor_contract(
        command=executor_command,
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=19),
    )
    bundle = build_legacy_sql_connector_real_connection_executor_policy_bundle(
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=executor_contract,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=20),
    )
    human_review = build_legacy_sql_connector_execution_readiness_human_review(
        bundle=bundle,
        reviewer_principal_ref="principal:legacy-sql-execution-reviewer",
        review_ticket_ref="review-ticket:legacy-sql-execution-readiness",
        approval_reference="approval:legacy-sql-execution-readiness",
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=21),
    )
    change_control = build_legacy_sql_connector_execution_readiness_change_control(
        bundle=bundle,
        change_request_ref="change-request:legacy-sql-execution-readiness",
        maintenance_window_ref="maintenance-window:legacy-sql-execution-readiness",
        rollback_plan_ref="rollback-plan:legacy-sql-execution-readiness",
        risk_acceptance_ref="risk-acceptance:legacy-sql-execution-readiness",
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=22),
    )
    restore_drill = build_legacy_sql_connector_execution_readiness_restore_drill(
        bundle=bundle,
        restore_drill_report_hash="sha256:" + "8" * 64,
        backup_verification_hash="sha256:" + "9" * 64,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=23),
    )
    command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command,
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=24),
    )
    return ReviewGateFixture(
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        command=command,
        gate=gate,
    )


def postgres_review_gate_env(*, tmp_path: Path, worker_resource: str) -> dict[str, str]:
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
        "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_RESTORE_DRILL_HASH": "sha256:" + "8" * 64,
        "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_BACKUP_VERIFY_HASH": "sha256:" + "9" * 64,
        "SUITE_DATABASE_DSN": worker_resource,
    }
