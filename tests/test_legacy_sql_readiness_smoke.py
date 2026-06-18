from pathlib import Path

from suite.platform.crm_erp_legacy_mapping import CrmErpLegacyImportReadinessStatus
from suite.platform.legacy_sql_evidence_ledger import (
    JsonlLegacySqlEvidenceLedgerStore,
    LegacySqlEvidenceType,
)
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


def test_legacy_sql_readiness_smoke_writes_optional_ledger_entry(tmp_path: Path) -> None:
    ledger_path = tmp_path / "legacy-sql-evidence-ledger.jsonl"
    restore_hash = "sha256:" + "2" * 64

    report = run_legacy_sql_readiness_smoke_from_env(
        {
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE": "true",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_BACKEND": "jsonl",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_PATH": str(ledger_path),
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": restore_hash,
        }
    )

    store = JsonlLegacySqlEvidenceLedgerStore(path=ledger_path)
    entries = store.list_entries(tenant_id=report.tenant_id)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.tenant_id == report.tenant_id
    assert entry.module_id == report.module_id
    assert entry.source_system_ref == report.source_system_ref
    assert entry.evidence_type == LegacySqlEvidenceType.READINESS_SMOKE_REPORT
    assert entry.evidence_ref == f"legacy-sql-readiness-smoke:{report.evidence_hash}"
    assert entry.evidence_hash == report.evidence_hash
    assert entry.evidence_status == "smoke_passed"
    assert entry.restore_evidence_hash == restore_hash
    assert entry.captured_by == report.checked_by
    assert report.discovery_manifest_hash in entry.related_evidence_hashes
    assert report.import_evidence_plan_hash in entry.related_evidence_hashes
    for scenario in report.scenarios:
        assert scenario.mapping_manifest_hash in entry.related_evidence_hashes
        assert scenario.readiness_evidence_hash in entry.related_evidence_hashes
    assert not entry.raw_payload_included
    assert not entry.import_write_executed
    assert not entry.destructive_actions_executed
