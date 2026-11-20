from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from suite.platform.legacy_sql_connector_materialization_plan_gate import (
    LegacySqlConnectorMaterializationPlanGateStatus,
    build_legacy_sql_connector_materialization_plan_gate_hash,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
)
from suite.platform.legacy_sql_connector_socket_secret_implementation_adr_gate import (
    LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    LegacySqlConnectorSocketSecretImplementationAdrGateStatus,
    LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_command,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report_hash,
    build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot,
    build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash,
    build_legacy_sql_connector_socket_secret_network_route_snapshot,
    build_legacy_sql_connector_socket_secret_network_route_snapshot_hash,
    build_legacy_sql_connector_socket_secret_provider_limits_snapshot,
    build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash,
    build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot,
    build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash,
    build_legacy_sql_connector_socket_secret_secret_manager_snapshot,
    build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash,
    exit_code_for_report,
    run_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_from_env,
)
from test_legacy_sql_connector_execution_readiness_review_gate import (
    LiveDatabase,
    live_database,
    postgres_review_gate_env,
)
from test_legacy_sql_connector_materialization_plan_gate import (
    materialization_plan_fixture,
)

_ = live_database
ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class SocketSecretAdrFixture:
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand
    gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence


def test_legacy_sql_socket_secret_implementation_adr_gate_binds_required_evidence_without_runtime(
    tmp_path: Path,
) -> None:
    fixture = socket_secret_adr_fixture(tmp_path)
    gate = fixture.gate

    assert gate.schema_version == "legacy_sql_connector_socket_secret_implementation_adr_gate.v1"
    assert gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.READY
    assert gate.implementation_adr_ready
    assert gate.materialization_plan_gate_hash_valid
    assert gate.materialization_plan_gate_ready
    assert gate.materialization_plan_gate_bound
    assert gate.provider_limits_snapshot_hash_valid
    assert gate.provider_limits_snapshot_bound
    assert gate.provider_limits_attested
    assert gate.network_route_snapshot_hash_valid
    assert gate.network_route_snapshot_bound
    assert gate.network_route_approved
    assert gate.tenant_route_isolated
    assert gate.egress_allowlist_reviewed
    assert gate.inbound_access_forbidden
    assert gate.secret_manager_snapshot_hash_valid
    assert gate.secret_manager_snapshot_bound
    assert gate.secret_manager_ready
    assert gate.tenant_kms_required
    assert gate.no_plaintext_secret_reviewed
    assert gate.rollback_runbook_snapshot_hash_valid
    assert gate.rollback_runbook_snapshot_bound
    assert gate.rollback_runbook_tested
    assert gate.recover_without_import_writes
    assert gate.destructive_rollback_forbidden
    assert gate.kill_switch_runbook_snapshot_hash_valid
    assert gate.kill_switch_runbook_snapshot_bound
    assert gate.kill_switch_armed
    assert gate.kill_switch_runbook_tested
    assert not gate.tenant_connection_disabled
    assert not gate.global_connection_disabled
    assert not gate.manual_abort_requested
    assert not gate.break_glass_allowed
    assert gate.future_socket_secret_runtime_pr_required
    assert gate.future_secret_manager_runtime_binding_required
    assert gate.future_network_route_runtime_binding_required
    assert not gate.socket_implementation_allowed
    assert not gate.secret_materialization_allowed
    assert not gate.executor_code_allowed
    assert not gate.network_socket_opened
    assert not gate.network_connection_opened
    assert not gate.real_connection_opened
    assert not gate.secret_material_resolved
    assert not gate.raw_data_access_allowed
    assert not gate.import_dry_run_allowed
    assert not gate.import_write_allowed
    assert not gate.destructive_actions_allowed
    assert gate.blocking_reasons == ()
    assert gate.evidence_hash == build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(gate)

    payload = gate.model_dump_json().lower()
    assert '"connection_secret_ref":' not in payload
    assert "sqlserver://" not in payload
    assert "password" not in payload


def test_legacy_sql_socket_secret_implementation_adr_gate_blocks_missing_inputs_and_runtime_requests(
    tmp_path: Path,
) -> None:
    fixture = socket_secret_adr_fixture(tmp_path)
    materialization_fixture = materialization_plan_fixture(tmp_path)
    checked_at = datetime(2026, 6, 20, 12, tzinfo=UTC)

    blocked_plan = materialization_fixture.gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED,
            "materialization_plan_ready": False,
            "blocking_reasons": ("socket_secret_adr_test_plan_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_plan = blocked_plan.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_plan_gate_hash(blocked_plan)}
    )
    blocked_plan_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(
            update={"materialization_plan_gate_evidence_hash": blocked_plan.evidence_hash}
        ),
        bundle=fixture.bundle,
        materialization_gate=blocked_plan,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    assert blocked_plan_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "materialization_plan_gate_not_ready" in blocked_plan_gate.blocking_reasons
    assert not blocked_plan_gate.implementation_adr_ready

    blocked_limits = fixture.provider_limits_snapshot.model_copy(
        update={"provider_limits_attested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_limits = blocked_limits.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash(blocked_limits)}
    )
    blocked_limits_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(update={"provider_limits_snapshot_hash": blocked_limits.evidence_hash}),
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=blocked_limits,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    assert blocked_limits_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "provider_limits_not_attested" in blocked_limits_gate.blocking_reasons

    blocked_route = fixture.network_route_snapshot.model_copy(
        update={"approved_route_bound_to_tenant": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_route = blocked_route.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_network_route_snapshot_hash(blocked_route)}
    )
    blocked_route_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(update={"network_route_snapshot_hash": blocked_route.evidence_hash}),
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=blocked_route,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    assert blocked_route_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "network_route_not_approved" in blocked_route_gate.blocking_reasons

    blocked_secret_manager = fixture.secret_manager_snapshot.model_copy(
        update={"secret_manager_ready": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_secret_manager = blocked_secret_manager.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash(
                blocked_secret_manager
            )
        }
    )
    blocked_secret_manager_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(
            update={"secret_manager_snapshot_hash": blocked_secret_manager.evidence_hash}
        ),
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=blocked_secret_manager,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    assert blocked_secret_manager_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "secret_manager_not_ready" in blocked_secret_manager_gate.blocking_reasons

    blocked_rollback = fixture.rollback_runbook_snapshot.model_copy(
        update={"rollback_runbook_tested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_rollback = blocked_rollback.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash(blocked_rollback)
        }
    )
    blocked_rollback_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(update={"rollback_runbook_snapshot_hash": blocked_rollback.evidence_hash}),
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=blocked_rollback,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    assert blocked_rollback_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "rollback_runbook_not_tested" in blocked_rollback_gate.blocking_reasons

    blocked_kill_switch = fixture.kill_switch_runbook_snapshot.model_copy(
        update={"kill_switch_runbook_tested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_kill_switch = blocked_kill_switch.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash(
                blocked_kill_switch
            )
        }
    )
    blocked_kill_switch_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=fixture.command.model_copy(
            update={"kill_switch_runbook_snapshot_hash": blocked_kill_switch.evidence_hash}
        ),
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=blocked_kill_switch,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    assert blocked_kill_switch_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "kill_switch_runbook_not_tested" in blocked_kill_switch_gate.blocking_reasons

    runtime_command = build_legacy_sql_connector_socket_secret_implementation_adr_gate_command(
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        requested_by="socket-secret-adr-gate-test",
        socket_implementation_requested=True,
        secret_materialization_requested=True,
        executor_code_requested=True,
        raw_data_access_requested=True,
    )
    runtime_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=runtime_command,
        bundle=fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=fixture.provider_limits_snapshot,
        network_route_snapshot=fixture.network_route_snapshot,
        secret_manager_snapshot=fixture.secret_manager_snapshot,
        rollback_runbook_snapshot=fixture.rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=fixture.kill_switch_runbook_snapshot,
        checked_by="socket-secret-adr-gate-test",
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    assert runtime_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
    assert "socket_implementation_requires_future_pr_gate" in runtime_gate.blocking_reasons
    assert "secret_materialization_requires_future_pr_gate" in runtime_gate.blocking_reasons
    assert "executor_code_requires_future_pr_gate" in runtime_gate.blocking_reasons
    assert "raw_data_access_requires_future_data_gate" in runtime_gate.blocking_reasons
    assert not runtime_gate.socket_implementation_allowed
    assert not runtime_gate.secret_materialization_allowed
    assert not runtime_gate.executor_code_allowed
    assert not runtime_gate.real_connection_opened


def test_pg_legacy_sql_socket_secret_implementation_adr_gate_smoke_stays_non_executing(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = postgres_review_gate_env(tmp_path=tmp_path, worker_resource=live_database.worker_resource)

    report = run_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report.v1"
    assert report.store_backend == "postgres"
    assert report.implementation_adr_ready
    assert report.materialization_plan_gate_required
    assert report.provider_limits_snapshot_required
    assert report.network_route_snapshot_required
    assert report.secret_manager_snapshot_required
    assert report.rollback_runbook_snapshot_required
    assert report.kill_switch_runbook_snapshot_required
    assert report.materialization_plan_missing_blocked
    assert report.provider_limits_missing_blocked
    assert report.network_route_missing_blocked
    assert report.secret_manager_missing_blocked
    assert report.rollback_runbook_missing_blocked
    assert report.kill_switch_runbook_missing_blocked
    assert report.implementation_request_blocked
    assert report.future_socket_secret_runtime_pr_required
    assert report.future_secret_manager_runtime_binding_required
    assert report.future_network_route_runtime_binding_required
    assert not report.socket_implementation_allowed
    assert not report.secret_materialization_allowed
    assert not report.executor_code_allowed
    assert not report.network_socket_opened
    assert not report.network_connection_opened
    assert not report.real_connection_opened
    assert not report.secret_material_resolved
    assert not report.raw_data_access_allowed
    assert not report.import_dry_run_allowed
    assert not report.import_write_allowed
    assert not report.destructive_actions_allowed
    assert report.evidence_hash == build_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report_hash(
        report
    )
    assert exit_code_for_report(report) == 0


def socket_secret_adr_fixture(tmp_path: Path) -> SocketSecretAdrFixture:
    checked_at = datetime(2026, 6, 20, 11, tzinfo=UTC)
    checked_by = "socket-secret-adr-gate-test"
    materialization_fixture = materialization_plan_fixture(tmp_path)
    provider_limits_snapshot = build_legacy_sql_connector_socket_secret_provider_limits_snapshot(
        materialization_gate=materialization_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    network_route_snapshot = build_legacy_sql_connector_socket_secret_network_route_snapshot(
        materialization_gate=materialization_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    secret_manager_snapshot = build_legacy_sql_connector_socket_secret_secret_manager_snapshot(
        materialization_gate=materialization_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    rollback_runbook_snapshot = build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot(
        materialization_gate=materialization_fixture.gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    kill_switch_runbook_snapshot = build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot(
        materialization_gate=materialization_fixture.gate,
        kill_switch_snapshot=materialization_fixture.kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    command = build_legacy_sql_connector_socket_secret_implementation_adr_gate_command(
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command,
        bundle=materialization_fixture.bundle,
        materialization_gate=materialization_fixture.gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    return SocketSecretAdrFixture(
        bundle=materialization_fixture.bundle,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        command=command,
        gate=gate,
    )
