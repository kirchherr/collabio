from pathlib import Path

from suite.platform.legacy_sql_discovery_intake import LegacySqlDiscoveryIntakeStatus
from suite.platform.legacy_sql_discovery_intake_operations import (
    LEGACY_SQL_DISCOVERY_INTAKE_CONTINUITY_DOMAIN,
    build_legacy_sql_discovery_intake_operations_report_hash,
    exit_code_for_report,
    run_legacy_sql_discovery_intake_operations_from_env,
)
from suite.platform.legacy_sql_evidence_ledger import (
    JsonlLegacySqlEvidenceLedgerStore,
    LegacySqlEvidenceType,
)


def test_legacy_sql_discovery_intake_operations_report_redacts_command_secret() -> None:
    report = run_legacy_sql_discovery_intake_operations_from_env({})

    assert report.schema_version == "legacy_sql_discovery_intake_operations_report.v1"
    assert report.continuity_domain == LEGACY_SQL_DISCOVERY_INTAKE_CONTINUITY_DOMAIN
    assert report.tenant_id == "tenant-demo"
    assert report.module_id == "crm_erp"
    assert report.source_system_ref == "legacy-sql:intake-drill-sqlserver"
    assert report.connector_kind == "sqlserver"
    assert report.intake_status == LegacySqlDiscoveryIntakeStatus.READY_FOR_METADATA_WORKER
    assert report.metadata_worker_command_ready
    assert report.metadata_discovery_allowed
    assert report.metadata_worker_command_hash is not None
    assert report.metadata_worker_command_hash.startswith("sha256:")
    assert report.metadata_worker_command_view is not None
    assert report.metadata_worker_command_view.secret_reference_available
    assert report.metadata_worker_command_view.connector_policy_ref == "policy:legacy-sql-connector"
    assert report.intake_evidence_hash.startswith("sha256:")
    assert not report.real_connection_used
    assert not report.dry_run_executed
    assert not report.import_write_executed
    assert not report.raw_data_import_allowed
    assert not report.destructive_actions_allowed
    assert report.blocking_reasons == ()
    assert report.report_passed
    assert exit_code_for_report(report) == 0
    assert report.evidence_hash == build_legacy_sql_discovery_intake_operations_report_hash(report)

    report_json = report.model_dump_json()
    assert "secret:legacy-sql-intake-drill" not in report_json
    assert "connection_secret_ref" not in report_json
    assert "sqlserver://" not in report_json
    assert "password" not in report_json.lower()
    assert "dsn" not in report_json.lower()


def test_legacy_sql_discovery_intake_operations_report_blocks_policy_mismatch() -> None:
    report = run_legacy_sql_discovery_intake_operations_from_env(
        {"SUITE_LEGACY_SQL_INTAKE_FORCE_POLICY_MISMATCH": "true"}
    )

    assert report.intake_status == LegacySqlDiscoveryIntakeStatus.BLOCKED
    assert not report.metadata_worker_command_ready
    assert not report.metadata_discovery_allowed
    assert report.metadata_worker_command_hash is None
    assert report.metadata_worker_command_view is None
    assert report.blocking_reasons == ("connector_policy_hash_mismatch",)
    assert not report.report_passed
    assert exit_code_for_report(report) == 1


def test_legacy_sql_discovery_intake_operations_writes_optional_ledger_entry(tmp_path: Path) -> None:
    ledger_path = tmp_path / "legacy-sql-evidence-ledger.jsonl"
    restore_hash = "sha256:" + "1" * 64

    report = run_legacy_sql_discovery_intake_operations_from_env(
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
    assert entry.evidence_type == LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT
    assert entry.evidence_ref == f"legacy-sql-intake-ops:{report.evidence_hash}"
    assert entry.evidence_hash == report.evidence_hash
    assert entry.evidence_status == report.intake_status.value
    assert entry.restore_evidence_hash == restore_hash
    assert entry.captured_by == report.checked_by
    assert report.intake_evidence_hash in entry.related_evidence_hashes
    assert report.metadata_worker_command_hash in entry.related_evidence_hashes
    assert not entry.raw_payload_included
    assert not entry.import_write_executed
    assert not entry.destructive_actions_executed
