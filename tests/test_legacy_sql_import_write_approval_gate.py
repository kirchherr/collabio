from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_import_dry_run_worker import (
    JsonlLegacySqlImportDryRunResultStore,
    LegacySqlImportDryRunResult,
    LegacySqlImportDryRunWorkerReport,
    run_legacy_sql_import_dry_run_worker_from_env,
)
from suite.platform.legacy_sql_import_write_approval_gate import (
    JsonlLegacySqlImportWriteApprovalGateStore,
    LegacySqlImportWriteApprovalGateEvidence,
    LegacySqlImportWriteApprovalGateStatus,
    LegacySqlImportWriteApprovalRecordPersistencePlanCommand,
    LegacySqlImportWriteApprovalRecordPersistencePlanStatus,
    LegacySqlImportWriteApprovalRequestBoundaryResponse,
    LegacySqlImportWriteApprovalRequestBoundaryStatus,
    LegacySqlImportWriteApprovalRequestCommand,
    LegacySqlImportWriteApprovalReview,
    LegacySqlImportWriteChangeControl,
    LegacySqlImportWriteRestoreDrill,
    PgLegacySqlImportWriteApprovalGateStore,
    build_legacy_sql_import_write_approval_gate,
    build_legacy_sql_import_write_approval_gate_command,
    build_legacy_sql_import_write_approval_gate_hash,
    build_legacy_sql_import_write_approval_gate_smoke_report_hash,
    build_legacy_sql_import_write_approval_record_persistence_plan,
    build_legacy_sql_import_write_approval_record_persistence_plan_command_hash,
    build_legacy_sql_import_write_approval_record_persistence_plan_hash,
    build_legacy_sql_import_write_approval_request_boundary,
    build_legacy_sql_import_write_approval_request_boundary_hash,
    build_legacy_sql_import_write_approval_request_hash,
    build_legacy_sql_import_write_approval_review,
    build_legacy_sql_import_write_change_control,
    build_legacy_sql_import_write_restore_drill,
    run_legacy_sql_import_write_approval_gate_smoke_from_env,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    worker_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, worker_dsn=worker_dsn)


def test_legacy_sql_import_write_approval_gate_allows_only_human_record(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)

    assert gate.schema_version == "legacy_sql_import_write_approval_gate.v1"
    assert gate.gate_status == LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD
    assert gate.evidence_hash == build_legacy_sql_import_write_approval_gate_hash(gate)
    assert gate.human_approval_record_allowed
    assert gate.future_import_write_execution_gate_required
    assert not gate.import_write_execution_allowed
    assert not gate.raw_data_access_allowed
    assert not gate.import_write_payload_allowed
    assert not gate.destructive_actions_allowed
    assert not gate.external_side_effect_allowed
    assert gate.blocking_reasons == ()


def test_legacy_sql_import_write_approval_gate_blocks_missing_human_review(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    review, change_control, restore_drill = approval_artifacts(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        human_review_completed=False,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by="approval-test",
    )

    gate = build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by="approval-test",
        checked_at_utc=fixed_time(),
    )

    assert gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
    assert "human_review_incomplete" in gate.blocking_reasons
    assert not gate.human_approval_record_allowed
    assert not gate.import_write_execution_allowed


def test_legacy_sql_import_write_approval_gate_blocks_unsafe_write_request(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    review, change_control, restore_drill = approval_artifacts(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by="approval-test",
        import_write_requested=True,
        raw_data_access_requested=True,
    )

    gate = build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by="approval-test",
        checked_at_utc=fixed_time(),
    )

    assert gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
    assert "import_write_request_requires_future_execution_gate" in gate.blocking_reasons
    assert "raw_data_access_request_forbidden" in gate.blocking_reasons
    assert gate.import_write_requested
    assert not gate.human_approval_record_allowed
    assert not gate.import_write_execution_allowed
    assert not gate.raw_data_access_allowed


def test_legacy_sql_import_write_approval_gate_blocks_change_and_restore_gaps(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    review, change_control, restore_drill = approval_artifacts(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        rollback_plan_verified=False,
        restore_drill_passed=False,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by="approval-test",
    )

    gate = build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by="approval-test",
        checked_at_utc=fixed_time(),
    )

    assert gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
    assert "rollback_plan_not_verified" in gate.blocking_reasons
    assert "restore_drill_not_passed" in gate.blocking_reasons
    assert not gate.human_approval_record_allowed


def test_legacy_sql_import_write_approval_gate_blocks_tampered_result_hash(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    review, change_control, restore_drill = approval_artifacts(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by="approval-test",
    ).model_copy(update={"dry_run_result_hash": "sha256:" + "0" * 64})

    gate = build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by="approval-test",
        checked_at_utc=fixed_time(),
    )

    assert gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
    assert "dry_run_result_hash_invalid" in gate.blocking_reasons
    assert not gate.human_approval_record_allowed


def test_legacy_sql_import_write_approval_request_boundary_accepts_only_request(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    command = approval_request_command(gate)

    response = build_legacy_sql_import_write_approval_request_boundary(
        command=command,
        gate_evidence=gate,
        tenant_id=gate.tenant_id,
        checked_by="approval-request-test",
        checked_at_utc=fixed_time(),
    )

    assert response.schema_version == "legacy_sql_import_write_approval_request_boundary.v1"
    assert (
        response.boundary_status == LegacySqlImportWriteApprovalRequestBoundaryStatus.READY_FOR_APPROVAL_RECORD_REQUEST
    )
    assert response.approval_request_hash == build_legacy_sql_import_write_approval_request_hash(command)
    assert response.evidence_hash == build_legacy_sql_import_write_approval_request_boundary_hash(response)
    assert response.approval_request_accepted
    assert response.human_approval_record_allowed_by_gate
    assert response.future_import_write_execution_gate_required
    assert not response.approval_record_persistence_allowed
    assert not response.approval_record_persisted
    assert not response.import_write_execution_allowed
    assert not response.raw_data_access_allowed
    assert not response.import_write_payload_allowed
    assert not response.destructive_actions_allowed
    assert not response.external_side_effect_allowed


def test_legacy_sql_import_write_approval_request_boundary_blocks_unsafe_request(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    command = approval_request_command(
        gate,
        import_write_requested=True,
        approval_record_persistence_requested=True,
        import_write_payload_requested=True,
    )

    response = build_legacy_sql_import_write_approval_request_boundary(
        command=command,
        gate_evidence=gate,
        tenant_id=gate.tenant_id,
        checked_by="approval-request-test",
        checked_at_utc=fixed_time(),
    )

    assert response.boundary_status == LegacySqlImportWriteApprovalRequestBoundaryStatus.BLOCKED
    assert "import_write_request_requires_future_execution_gate" in response.blocking_reasons
    assert "approval_record_persistence_not_enabled" in response.blocking_reasons
    assert "import_write_payload_request_forbidden" in response.blocking_reasons
    assert not response.approval_request_accepted
    assert not response.approval_record_persistence_allowed
    assert not response.import_write_execution_allowed


def test_legacy_sql_import_write_approval_record_persistence_plan_is_store_only(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    request_boundary = approval_request_boundary(gate)
    command = approval_record_persistence_plan_command(request_boundary)

    plan = build_legacy_sql_import_write_approval_record_persistence_plan(
        command=command,
        request_boundary=request_boundary,
        gate_evidence=gate,
        tenant_id=gate.tenant_id,
        planned_by="approval-record-plan-test",
        planned_at_utc=fixed_time(),
    )

    assert plan.schema_version == "legacy_sql_import_write_approval_record_persistence_plan.v1"
    assert plan.plan_status == LegacySqlImportWriteApprovalRecordPersistencePlanStatus.READY_FOR_STORE_IMPLEMENTATION
    assert plan.persistence_plan_command_hash == (
        build_legacy_sql_import_write_approval_record_persistence_plan_command_hash(command)
    )
    assert plan.evidence_hash == build_legacy_sql_import_write_approval_record_persistence_plan_hash(plan)
    assert plan.approval_request_boundary_hash_valid
    assert plan.approval_request_boundary_bound
    assert plan.approval_request_boundary_ready
    assert plan.approval_gate_hash_valid
    assert plan.approval_gate_ready_for_human_record
    assert plan.human_approval_record_allowed_by_boundary
    assert plan.approval_record_store_required
    assert plan.tenant_scoped_rls_required
    assert plan.append_only_store_required
    assert plan.idempotency_required
    assert plan.restore_evidence_required
    assert plan.approval_record_persistence_plan_accepted
    assert plan.future_import_write_execution_gate_required
    assert not plan.approval_record_persistence_allowed
    assert not plan.approval_record_persisted
    assert not plan.import_write_execution_allowed
    assert not plan.raw_data_access_allowed
    assert not plan.import_write_payload_allowed
    assert not plan.destructive_actions_allowed
    assert not plan.external_side_effect_allowed


def test_legacy_sql_import_write_approval_record_persistence_plan_blocks_direct_writes(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    request_boundary = approval_request_boundary(gate)
    command = approval_record_persistence_plan_command(
        request_boundary,
        approval_record_persistence_requested=True,
        import_write_requested=True,
        raw_data_access_requested=True,
        external_side_effect_requested=True,
    )

    plan = build_legacy_sql_import_write_approval_record_persistence_plan(
        command=command,
        request_boundary=request_boundary,
        gate_evidence=gate,
        tenant_id=gate.tenant_id,
        planned_by="approval-record-plan-test",
        planned_at_utc=fixed_time(),
    )

    assert plan.plan_status == LegacySqlImportWriteApprovalRecordPersistencePlanStatus.BLOCKED
    assert "approval_record_persistence_not_enabled" in plan.blocking_reasons
    assert "import_write_request_requires_future_execution_gate" in plan.blocking_reasons
    assert "raw_data_access_request_forbidden" in plan.blocking_reasons
    assert "external_side_effect_request_forbidden" in plan.blocking_reasons
    assert not plan.approval_record_persistence_plan_accepted
    assert not plan.approval_record_persistence_allowed
    assert not plan.approval_record_persisted
    assert not plan.import_write_execution_allowed


def test_legacy_sql_import_write_approval_gate_store_replays_jsonl(tmp_path: Path) -> None:
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path)
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    store_path = tmp_path / "approval-gates.jsonl"
    store = JsonlLegacySqlImportWriteApprovalGateStore(path=store_path)

    store.append(gate)
    reloaded = JsonlLegacySqlImportWriteApprovalGateStore(path=store_path)

    assert reloaded.get(tenant_id=gate.tenant_id, evidence_hash=gate.evidence_hash) == gate
    assert reloaded.list_gates(tenant_id=gate.tenant_id) == (gate,)
    with pytest.raises(ValueError, match="already exists"):
        reloaded.append(gate)


def test_pg_legacy_sql_import_write_approval_gate_store_persists_with_tenant_isolation(
    tmp_path: Path,
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    dry_run_result, dry_run_worker_report = dry_run_fixture_pair(tmp_path, tenant_id=f"tenant-approval-{suffix}")
    gate = ready_gate(dry_run_result=dry_run_result, dry_run_worker_report=dry_run_worker_report)
    store = PgLegacySqlImportWriteApprovalGateStore(database_dsn=live_database.worker_dsn)

    store.append(gate)

    assert store.get(tenant_id=gate.tenant_id, evidence_hash=gate.evidence_hash) == gate
    assert store.list_gates(tenant_id=gate.tenant_id) == (gate,)
    with pytest.raises(KeyError, match="not found"):
        store.get(tenant_id=f"{gate.tenant_id}-other", evidence_hash=gate.evidence_hash)


def test_legacy_sql_import_write_approval_gate_smoke_is_metadata_only_and_hashable(tmp_path: Path) -> None:
    store_path = tmp_path / "approval-gates.jsonl"
    report = run_legacy_sql_import_write_approval_gate_smoke_from_env(
        {
            "SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_WRITE": "true",
            "SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_BACKEND": "jsonl",
            "SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_PATH": str(store_path),
        }
    )

    assert report.schema_version == "legacy_sql_import_write_approval_gate_smoke_report.v1"
    assert report.smoke_passed
    assert report.approval_gate_ready_for_human_record
    assert report.human_approval_record_allowed
    assert report.future_import_write_execution_gate_required
    assert report.missing_human_review_blocked
    assert report.rollback_plan_missing_blocked
    assert report.restore_drill_missing_blocked
    assert report.import_write_request_blocked
    assert report.tampered_dry_run_result_blocked
    assert report.evidence_hash == build_legacy_sql_import_write_approval_gate_smoke_report_hash(report)
    assert store_path.exists()
    assert not report.import_write_execution_allowed
    assert not report.raw_data_access_allowed
    assert not report.import_write_payload_allowed

    payload = report.model_dump_json().lower()
    assert "dbo.kunden" not in payload
    assert "kundenid" not in payload
    assert "email" not in payload
    assert "connection_secret_ref" not in payload
    assert "sqlserver://" not in payload


def dry_run_fixture_pair(
    tmp_path: Path,
    *,
    tenant_id: str = "tenant-demo",
) -> tuple[LegacySqlImportDryRunResult, LegacySqlImportDryRunWorkerReport]:
    result_store_path = tmp_path / f"dry-run-results-{uuid4().hex}.jsonl"
    report = run_legacy_sql_import_dry_run_worker_from_env(
        {
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_TENANT_ID": tenant_id,
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_WRITE": "true",
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_BACKEND": "jsonl",
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_PATH": str(result_store_path),
        }
    )
    result = JsonlLegacySqlImportDryRunResultStore(path=result_store_path).get(
        tenant_id=report.tenant_id,
        result_hash=report.dry_run_result_hash,
    )
    return result, report


def approval_artifacts(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    human_review_completed: bool = True,
    rollback_plan_verified: bool = True,
    restore_drill_passed: bool = True,
) -> tuple[
    LegacySqlImportWriteApprovalReview,
    LegacySqlImportWriteChangeControl,
    LegacySqlImportWriteRestoreDrill,
]:
    checked_at = fixed_time()
    review = build_legacy_sql_import_write_approval_review(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        reviewer_principal_ref="principal:approval-reviewer",
        review_ticket_ref="ticket:approval-review",
        approval_reference="approval:import-write-record",
        checked_by="approval-test",
        checked_at_utc=checked_at,
        human_review_completed=human_review_completed,
    )
    change_control = build_legacy_sql_import_write_change_control(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        change_request_ref="change:import-write-record",
        maintenance_window_ref="window:import-write-record",
        rollback_plan_ref="rollback:import-write-record",
        risk_acceptance_ref="risk:import-write-record",
        checked_by="approval-test",
        checked_at_utc=checked_at,
        rollback_plan_verified=rollback_plan_verified,
    )
    restore_drill = build_legacy_sql_import_write_restore_drill(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        restore_drill_report_hash=fixture_hash("restore-drill", dry_run_result.result_hash),
        backup_verification_hash=fixture_hash("backup-verification", dry_run_worker_report.evidence_hash),
        dry_run_result_store_roundtrip_hash=dry_run_result.result_hash,
        checked_by="approval-test",
        checked_at_utc=checked_at,
        restore_drill_passed=restore_drill_passed,
    )
    return review, change_control, restore_drill


def ready_gate(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
) -> LegacySqlImportWriteApprovalGateEvidence:
    review, change_control, restore_drill = approval_artifacts(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by="approval-test",
    )
    return build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by="approval-test",
        checked_at_utc=fixed_time(),
    )


def fixture_hash(kind: str, seed: str) -> str:
    return stable_hash(canonical_json({"kind": kind, "seed": seed}))


def approval_request_command(
    gate: LegacySqlImportWriteApprovalGateEvidence,
    **updates: object,
) -> LegacySqlImportWriteApprovalRequestCommand:
    values: dict[str, object] = {
        "source_system_ref": gate.source_system_ref,
        "dry_run_result_hash": gate.dry_run_result_hash,
        "approval_gate_evidence_hash": gate.evidence_hash,
        "approval_reference": "approval:legacy-sql-import-write-request",
        "approval_ticket_ref": "ticket:legacy-sql-import-write-request",
        "human_confirmation_reference": "human-confirmation:legacy-sql-import-write-request",
        "reason": "request a non-executing legacy sql import write approval record boundary",
    }
    values.update(updates)
    return LegacySqlImportWriteApprovalRequestCommand.model_validate(values)


def approval_request_boundary(
    gate: LegacySqlImportWriteApprovalGateEvidence,
) -> LegacySqlImportWriteApprovalRequestBoundaryResponse:
    command = approval_request_command(gate)
    return build_legacy_sql_import_write_approval_request_boundary(
        command=command,
        gate_evidence=gate,
        tenant_id=gate.tenant_id,
        checked_by="approval-request-test",
        checked_at_utc=fixed_time(),
    )


def approval_record_persistence_plan_command(
    request_boundary: LegacySqlImportWriteApprovalRequestBoundaryResponse,
    **updates: object,
) -> LegacySqlImportWriteApprovalRecordPersistencePlanCommand:
    values: dict[str, object] = {
        "approval_request_boundary_evidence_hash": request_boundary.evidence_hash,
        "approval_record_store_ref": "store:crm-erp-legacy-import-write-approval-records",
        "approval_record_schema_ref": "schema:legacy-sql-import-write-approval-record-v1",
        "approval_record_retention_policy_ref": "retention:crm-erp-legacy-import-write-approval-record",
        "approval_record_legal_hold_policy_ref": "legal-hold:crm-erp-business-records",
        "idempotency_key_ref": "idempotency:legacy-sql-import-write-approval-record",
        "operator_mfa_ref": "mfa:legacy-sql-import-write-approval-record",
        "change_control_ref": "change:legacy-sql-import-write-approval-record-store-plan",
        "reason": "plan a tenant-scoped append-only approval record store without executing import writes",
    }
    values.update(updates)
    return LegacySqlImportWriteApprovalRecordPersistencePlanCommand.model_validate(values)


def fixed_time() -> datetime:
    return datetime(2026, 6, 22, 9, tzinfo=UTC)
