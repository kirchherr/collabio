from suite.platform.legacy_sql_discovery_intake import LegacySqlDiscoveryIntakeStatus
from suite.platform.legacy_sql_discovery_intake_operations import (
    LEGACY_SQL_DISCOVERY_INTAKE_CONTINUITY_DOMAIN,
    build_legacy_sql_discovery_intake_operations_report_hash,
    exit_code_for_report,
    run_legacy_sql_discovery_intake_operations_from_env,
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
