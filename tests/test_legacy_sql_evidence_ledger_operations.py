from __future__ import annotations

import os
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_evidence_ledger import LegacySqlEvidenceType
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN,
    build_legacy_sql_evidence_ledger_operations_report_hash,
    exit_code_for_report,
    run_legacy_sql_evidence_ledger_operations_from_env,
)


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


def test_legacy_sql_evidence_ledger_operations_drill_proves_jsonl_backend(tmp_path: Path) -> None:
    report = run_legacy_sql_evidence_ledger_operations_from_env(
        {
            "SUITE_DATA_DIR": str(tmp_path),
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "4" * 64,
        }
    )

    assert report.schema_version == "legacy_sql_evidence_ledger_operations_report.v1"
    assert report.continuity_domain == LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN
    assert report.selected_backends == ("jsonl",)
    assert report.ready_count == 1
    assert report.failed_count == 0
    assert not report.alert_required
    assert report.legacy_host_profile_release_gate_passed
    assert not report.real_connection_used
    assert not report.import_dry_run_executed
    assert not report.import_write_executed
    assert not report.destructive_actions_executed
    assert exit_code_for_report(report) == 0
    assert report.evidence_hash == build_legacy_sql_evidence_ledger_operations_report_hash(report)

    result = report.backend_results[0]
    assert result.backend == "jsonl"
    assert result.ledger_entry_count == 2
    assert result.evidence_types == (
        LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT,
        LegacySqlEvidenceType.READINESS_SMOKE_REPORT,
    )
    assert result.restore_evidence_hashes == ("sha256:" + "4" * 64,)
    assert result.write_path_ok
    assert result.restore_hash_bound
    assert result.related_evidence_hashes_recovered
    assert result.tenant_isolation_ok
    assert result.duplicate_append_rejected
    assert result.metadata_only_ok
    assert result.host_profile_release_precondition_ok
    assert result.blocking_reasons == ()


def test_legacy_sql_evidence_ledger_operations_drill_proves_postgres_backend() -> None:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)

    report = run_legacy_sql_evidence_ledger_operations_from_env(
        {
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "postgres",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_BACKEND": "postgres",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": app_dsn,
            "SUITE_DATABASE_DSN": app_dsn,
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "5" * 64,
        }
    )

    assert report.selected_backends == ("postgres",)
    assert report.ready_count == 1
    assert report.failed_count == 0
    assert not report.alert_required
    assert report.legacy_host_profile_release_gate_passed
    assert exit_code_for_report(report) == 0

    result = report.backend_results[0]
    assert result.backend == "postgres"
    assert result.ledger_entry_count == 2
    assert result.restore_evidence_hashes == ("sha256:" + "5" * 64,)
    assert result.write_path_ok
    assert result.restore_hash_bound
    assert result.tenant_isolation_ok
    assert result.duplicate_append_rejected
    assert result.metadata_only_ok
    assert result.host_profile_release_precondition_ok
