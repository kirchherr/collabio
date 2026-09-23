from __future__ import annotations

from datetime import UTC, datetime

import pytest

from suite.platform.legacy_sql_migration_api_plan import (
    LegacySqlMigrationApiEndpointKind,
    LegacySqlMigrationApiPlanCommand,
    LegacySqlMigrationApiPlanStatus,
    build_legacy_sql_migration_api_plan,
    build_legacy_sql_migration_api_plan_hash,
)


def test_legacy_sql_migration_api_plan_covers_run_report_and_approval_surfaces() -> None:
    command = migration_api_plan_command()

    plan = build_legacy_sql_migration_api_plan(
        command=command,
        tenant_id="tenant-demo",
        planned_by="migration-api-plan-test",
        planned_at_utc=fixed_time(),
    )

    assert plan.schema_version == "legacy_sql_migration_api_plan.v1"
    assert plan.plan_status == LegacySqlMigrationApiPlanStatus.READY_FOR_RUN_REGISTRY_DESIGN
    assert plan.evidence_hash == build_legacy_sql_migration_api_plan_hash(plan)
    assert plan.migration_api_plan_accepted
    assert plan.run_creation_planned
    assert plan.run_listing_planned
    assert plan.report_retrieval_planned
    assert plan.approval_request_planned
    assert plan.approval_grant_planned
    assert plan.future_import_write_execution_gate_required
    assert not plan.run_creation_enabled
    assert not plan.report_retrieval_enabled
    assert not plan.approval_grant_enabled
    assert not plan.import_write_execution_allowed
    assert not plan.raw_data_access_allowed
    assert not plan.import_write_payload_allowed
    assert not plan.destructive_actions_allowed
    assert not plan.external_side_effect_allowed

    endpoint_kinds = {endpoint.endpoint_kind for endpoint in plan.planned_endpoints}
    assert endpoint_kinds == set(LegacySqlMigrationApiEndpointKind)
    assert all(not endpoint.implemented_now for endpoint in plan.planned_endpoints)
    assert all(not endpoint.import_write_execution_allowed for endpoint in plan.planned_endpoints)
    assert all(not endpoint.raw_data_access_allowed for endpoint in plan.planned_endpoints)
    assert all(not endpoint.destructive_actions_allowed for endpoint in plan.planned_endpoints)
    assert all(not endpoint.external_side_effect_allowed for endpoint in plan.planned_endpoints)

    payload = plan.model_dump_json().lower()
    assert "dbo.kunden" not in payload
    assert "kundenid" not in payload
    assert "email" not in payload
    assert "connection_secret_ref" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_migration_api_plan_blocks_execution_and_raw_data_requests() -> None:
    command = migration_api_plan_command(
        import_write_execution_requested=True,
        raw_data_access_requested=True,
        import_write_payload_requested=True,
        destructive_actions_requested=True,
        external_side_effect_requested=True,
    )

    plan = build_legacy_sql_migration_api_plan(
        command=command,
        tenant_id="tenant-demo",
        planned_by="migration-api-plan-test",
        planned_at_utc=fixed_time(),
    )

    assert plan.plan_status == LegacySqlMigrationApiPlanStatus.BLOCKED
    assert not plan.migration_api_plan_accepted
    assert "import_write_execution_requires_future_gate" in plan.blocking_reasons
    assert "raw_data_access_request_forbidden" in plan.blocking_reasons
    assert "import_write_payload_request_forbidden" in plan.blocking_reasons
    assert "destructive_action_request_forbidden" in plan.blocking_reasons
    assert "external_side_effect_request_forbidden" in plan.blocking_reasons
    assert not plan.import_write_execution_allowed
    assert not plan.raw_data_access_allowed


def test_legacy_sql_migration_api_plan_rejects_non_namespaced_refs() -> None:
    with pytest.raises(ValueError, match="references must be namespaced"):
        migration_api_plan_command(source_system_ref="sqlserver")


def migration_api_plan_command(**updates: object) -> LegacySqlMigrationApiPlanCommand:
    values: dict[str, object] = {
        "source_system_ref": "legacy-sql:sqlserver-demo",
        "approval_record_store_ref": "store:crm-erp-legacy-import-write-approval-records",
        "migration_run_registry_ref": "store:crm-erp-legacy-migration-runs",
        "migration_report_store_ref": "store:crm-erp-legacy-migration-reports",
        "approval_reference": "approval:legacy-sql-migration-api-plan",
        "change_control_ref": "change:legacy-sql-migration-api-plan",
        "restore_drill_ref": "restore:legacy-sql-migration-api-plan",
        "reason": "plan migration APIs for runs, reports and approvals without enabling import writes",
    }
    values.update(updates)
    return LegacySqlMigrationApiPlanCommand.model_validate(values)


def fixed_time() -> datetime:
    return datetime(2026, 6, 23, 9, tzinfo=UTC)
