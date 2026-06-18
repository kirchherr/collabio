from suite.platform.crm_erp_legacy_mapping import CrmErpLegacyImportReadinessStatus
from suite.platform.legacy_sql_readiness_smoke import (
    LEGACY_SQL_READINESS_CONTINUITY_DOMAIN,
    build_legacy_sql_readiness_smoke_report_hash,
    exit_code_for_report,
    run_legacy_sql_readiness_smoke_from_env,
)


def test_legacy_sql_readiness_smoke_reports_manual_block_and_ready_override() -> None:
    report = run_legacy_sql_readiness_smoke_from_env({})

    assert report.schema_version == "legacy_sql_readiness_smoke_report.v1"
    assert report.continuity_domain == LEGACY_SQL_READINESS_CONTINUITY_DOMAIN
    assert report.tenant_id == "tenant-demo"
    assert report.module_id == "crm_erp"
    assert report.source_system_ref == "legacy-sql:smoke-sqlserver"
    assert report.connector_kind == "sqlserver"
    assert report.metadata_worker_network_mode == "approved_legacy_host_only"
    assert report.executed_query_names == (
        "tables",
        "columns",
        "primary_keys",
        "foreign_keys",
        "indexes",
        "row_counts",
    )
    assert report.audit_event_types == (
        "legacy_sql.metadata_discovery.started",
        "legacy_sql.metadata_discovery.completed",
    )
    assert report.table_count == 2
    assert report.column_count == 5
    assert report.metadata_only_ok
    assert not report.real_connection_used
    assert not report.dry_run_executed
    assert not report.import_write_executed
    assert not report.raw_data_import_allowed
    assert not report.destructive_actions_allowed
    assert report.smoke_passed
    assert exit_code_for_report(report) == 0
    assert report.evidence_hash == build_legacy_sql_readiness_smoke_report_hash(report)

    scenarios = {scenario.scenario_id: scenario for scenario in report.scenarios}
    manual = scenarios["manual_mapping_blocks_dry_run"]
    assert manual.readiness_status == CrmErpLegacyImportReadinessStatus.MANUAL_MAPPING_REQUIRED
    assert not manual.dry_run_allowed
    assert manual.quarantine_table_count == 1
    assert manual.legacy_row_table_count == 1
    assert "quarantine_tables_require_manual_mapping" in manual.blocking_reasons

    override = scenarios["approved_override_allows_metadata_dry_run"]
    assert override.readiness_status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN
    assert override.dry_run_allowed
    assert override.quarantine_table_count == 0
    assert override.legacy_row_table_count == 0
    assert not override.import_write_allowed
    assert not override.raw_data_import_allowed
    assert not override.destructive_actions_allowed

    report_json = report.model_dump_json()
    assert "dbo.Kunden" not in report_json
    assert "dbo.FreieTabelle" not in report_json
    assert "KundenId" not in report_json
    assert "Email" not in report_json
    assert "secret:legacy-sql-smoke" not in report_json
    assert "connection_secret_ref" not in report_json
