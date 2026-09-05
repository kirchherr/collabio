from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_host_profile_release_gate import (
    PgLegacySqlHostProfileReleaseGateEvidenceStore,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    build_legacy_sql_host_profile_release_gate_smoke_report_hash,
    exit_code_for_report,
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def test_legacy_sql_host_profile_release_gate_smoke_persists_ready_and_blocked_paths(
    live_database: LiveDatabase,
    tmp_path: Path,
) -> None:
    env = {
        "SUITE_DATA_DIR": str(tmp_path),
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS": "jsonl,postgres",
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": "sha256:" + "7" * 64,
        "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN": live_database.app_dsn,
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_BACKEND": "postgres",
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_STORE_DSN": live_database.app_dsn,
        "SUITE_DATABASE_DSN": live_database.app_dsn,
    }

    report = run_legacy_sql_host_profile_release_gate_smoke_from_env(env)

    assert report.schema_version == "legacy_sql_host_profile_release_gate_smoke_report.v1"
    assert report.ready_gate_status == "ready"
    assert report.ready_gate_persisted
    assert report.ready_wiring_guard_ok
    assert report.blocked_gate_status == "blocked"
    assert report.blocked_gate_persisted
    assert report.blocked_wiring_guard_ok
    assert "explicit_human_confirmation_missing" in report.blocked_gate_blocking_reasons
    assert report.host_profile_adapter_precondition_ok
    assert report.evidence_hash == build_legacy_sql_host_profile_release_gate_smoke_report_hash(report)
    assert exit_code_for_report(report) == 0

    report_json = report.model_dump_json().lower()
    assert "secret:legacy-sql-production-metadata" not in report_json
    assert "sqlserver://" not in report_json

    store = PgLegacySqlHostProfileReleaseGateEvidenceStore(database_dsn=live_database.app_dsn)
    ready_gate = store.get(tenant_id=report.tenant_id, evidence_hash=report.ready_gate_evidence_hash)
    blocked_gate = store.get(tenant_id=report.tenant_id, evidence_hash=report.blocked_gate_evidence_hash)

    assert ready_gate.host_profile_activation_allowed
    assert ready_gate.metadata_worker_scheduling_allowed
    assert not blocked_gate.host_profile_activation_allowed
    assert not blocked_gate.metadata_worker_scheduling_allowed
