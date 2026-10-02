from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery_intake_operations import (
    run_legacy_sql_discovery_intake_operations_from_env,
)
from suite.platform.legacy_sql_evidence_ledger import (
    LegacySqlEvidenceLedgerEntry,
    LegacySqlEvidenceLedgerStore,
    LegacySqlEvidenceType,
    build_default_legacy_sql_evidence_ledger_store,
)
from suite.platform.legacy_sql_readiness_smoke import run_legacy_sql_readiness_smoke_from_env

LEGACY_SQL_EVIDENCE_LEDGER_OPERATIONS_SCHEMA_VERSION = "legacy_sql_evidence_ledger_operations_report.v1"
LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN = "crm_erp_business_records"
LEGACY_SQL_EVIDENCE_LEDGER_DRILL_COMMAND_REF = "docker-compose:legacy-sql-evidence-ledger-drill"
REQUIRED_LEDGER_EVIDENCE_TYPES = (
    LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT,
    LegacySqlEvidenceType.READINESS_SMOKE_REPORT,
)
FORBIDDEN_LEDGER_DRILL_FRAGMENTS = (
    "secret:legacy-sql",
    "connection_secret_ref",
    "sqlserver://",
    "password",
    "dsn",
    "dbo.kunden",
    "dbo.freietabelle",
    "kundenid",
    "email",
)


class LegacySqlEvidenceLedgerBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlEvidenceLedgerBackendDrillResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: LegacySqlEvidenceLedgerBackend
    tenant_id: str
    ledger_entry_count: int = Field(ge=0)
    ledger_entry_hashes: tuple[str, ...]
    evidence_types: tuple[LegacySqlEvidenceType, ...]
    restore_evidence_hashes: tuple[str, ...]
    intake_report_hash: str | None
    readiness_smoke_report_hash: str | None
    write_path_ok: bool
    restore_hash_bound: bool
    related_evidence_hashes_recovered: bool
    tenant_isolation_ok: bool
    duplicate_append_rejected: bool
    metadata_only_ok: bool
    host_profile_release_precondition_ok: bool
    blocking_reasons: tuple[str, ...]
    last_error: str | None = None


class LegacySqlEvidenceLedgerOperationsRunbookEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    checked_by: str
    checked_at_utc: datetime
    command_ref: str = LEGACY_SQL_EVIDENCE_LEDGER_DRILL_COMMAND_REF
    continuity_domain: str = LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN
    required_backup_evidence_artifacts: tuple[str, ...] = (
        "legacy SQL evidence ledger entries",
        "legacy SQL evidence ledger restore evidence hashes",
        "legacy SQL discovery intake operations report hash",
        "legacy SQL readiness smoke report hash",
        "legacy SQL evidence ledger operations report hash",
    )


class LegacySqlEvidenceLedgerOperationsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_EVIDENCE_LEDGER_OPERATIONS_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    continuity_domain: str = LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN
    selected_backends: tuple[LegacySqlEvidenceLedgerBackend, ...]
    backend_results: tuple[LegacySqlEvidenceLedgerBackendDrillResult, ...]
    ready_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    alert_required: bool
    legacy_host_profile_release_gate_passed: bool
    real_connection_used: bool = False
    import_dry_run_executed: bool = False
    import_write_executed: bool = False
    destructive_actions_executed: bool = False
    recommended_actions: tuple[str, ...]
    runbook_evidence: LegacySqlEvidenceLedgerOperationsRunbookEvidence
    evidence_hash: str


def build_legacy_sql_evidence_ledger_operations_report_hash(
    report: LegacySqlEvidenceLedgerOperationsReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_evidence_ledger_operations_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlEvidenceLedgerOperationsReport:
    env = os.environ if environ is None else environ
    checked_by = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_CHECKED_BY", "legacy-sql-evidence-ledger-drill")
    checked_at = datetime.now(UTC)
    run_id = f"legacy-sql-evidence-ledger-drill-{uuid4().hex}"
    selected_backends = _selected_backends(env)
    backend_results = tuple(
        _run_backend_drill(
            backend=backend,
            env=env,
            checked_by=checked_by,
            run_id=run_id,
        )
        for backend in selected_backends
    )
    ready_count = sum(1 for result in backend_results if result.host_profile_release_precondition_ok)
    failed_count = len(backend_results) - ready_count
    alert_required = failed_count > 0
    draft = LegacySqlEvidenceLedgerOperationsReport(
        run_id=run_id,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        selected_backends=selected_backends,
        backend_results=backend_results,
        ready_count=ready_count,
        failed_count=failed_count,
        alert_required=alert_required,
        legacy_host_profile_release_gate_passed=not alert_required and bool(backend_results),
        recommended_actions=_recommended_actions(backend_results),
        runbook_evidence=LegacySqlEvidenceLedgerOperationsRunbookEvidence(
            run_id=run_id,
            checked_by=checked_by,
            checked_at_utc=checked_at,
        ),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_evidence_ledger_operations_report_hash(draft)})


def exit_code_for_report(report: LegacySqlEvidenceLedgerOperationsReport) -> int:
    return 1 if report.alert_required or not report.legacy_host_profile_release_gate_passed else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL evidence ledger backend/restore drill.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only drill and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only run report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_evidence_ledger_operations_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _run_backend_drill(
    *,
    backend: LegacySqlEvidenceLedgerBackend,
    env: Mapping[str, str],
    checked_by: str,
    run_id: str,
) -> LegacySqlEvidenceLedgerBackendDrillResult:
    tenant_id = _tenant_id_for_backend(backend=backend, env=env, run_id=run_id)
    restore_hash = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH", "sha256:" + "3" * 64)
    child_env = _backend_env(
        backend=backend,
        env=env,
        checked_by=checked_by,
        tenant_id=tenant_id,
        restore_hash=restore_hash,
        run_id=run_id,
    )
    try:
        intake_report = run_legacy_sql_discovery_intake_operations_from_env(child_env)
        readiness_report = run_legacy_sql_readiness_smoke_from_env(child_env)
        store = build_default_legacy_sql_evidence_ledger_store(environ=child_env)
        entries = tuple(store.list_entries(tenant_id=tenant_id))
        return _backend_result_from_entries(
            backend=backend,
            tenant_id=tenant_id,
            restore_hash=restore_hash,
            store=store,
            entries=entries,
            intake_report_hash=intake_report.evidence_hash,
            readiness_smoke_report_hash=readiness_report.evidence_hash,
            required_related_hashes=(
                intake_report.intake_evidence_hash,
                intake_report.metadata_worker_command_hash,
                readiness_report.discovery_manifest_hash,
                readiness_report.import_evidence_plan_hash,
                *(scenario.mapping_manifest_hash for scenario in readiness_report.scenarios),
                *(scenario.readiness_evidence_hash for scenario in readiness_report.scenarios),
            ),
        )
    except Exception as exc:  # pragma: no cover - exercised through operational failure reports.
        return LegacySqlEvidenceLedgerBackendDrillResult(
            backend=backend,
            tenant_id=tenant_id,
            ledger_entry_count=0,
            ledger_entry_hashes=(),
            evidence_types=(),
            restore_evidence_hashes=(),
            intake_report_hash=None,
            readiness_smoke_report_hash=None,
            write_path_ok=False,
            restore_hash_bound=False,
            related_evidence_hashes_recovered=False,
            tenant_isolation_ok=False,
            duplicate_append_rejected=False,
            metadata_only_ok=False,
            host_profile_release_precondition_ok=False,
            blocking_reasons=("legacy_sql_evidence_ledger_backend_drill_failed",),
            last_error=type(exc).__name__,
        )


def _backend_result_from_entries(
    *,
    backend: LegacySqlEvidenceLedgerBackend,
    tenant_id: str,
    restore_hash: str,
    store: LegacySqlEvidenceLedgerStore,
    entries: tuple[LegacySqlEvidenceLedgerEntry, ...],
    intake_report_hash: str,
    readiness_smoke_report_hash: str,
    required_related_hashes: Sequence[str | None],
) -> LegacySqlEvidenceLedgerBackendDrillResult:
    entries_by_evidence_hash = {entry.evidence_hash: entry for entry in entries}
    ledger_entry_hashes = tuple(entry.ledger_entry_hash for entry in entries)
    evidence_types = tuple(sorted({entry.evidence_type for entry in entries}, key=lambda item: item.value))
    restore_evidence_hashes = tuple(sorted({entry.restore_evidence_hash for entry in entries}))
    expected_report_hashes = {intake_report_hash, readiness_smoke_report_hash}
    related_hashes = {evidence_hash for entry in entries for evidence_hash in entry.related_evidence_hashes}
    required_hashes = {value for value in required_related_hashes if value is not None}

    write_path_ok = expected_report_hashes <= set(entries_by_evidence_hash)
    restore_hash_bound = restore_evidence_hashes == (restore_hash,)
    related_evidence_hashes_recovered = required_hashes <= related_hashes
    tenant_isolation_ok = _tenant_isolation_ok(
        store=store,
        tenant_id=tenant_id,
        ledger_entry_hashes=ledger_entry_hashes,
    )
    duplicate_append_rejected = _duplicate_append_rejected(store=store, entries=entries)
    metadata_only_ok = _metadata_only_ok(entries)
    host_profile_release_precondition_ok = all(
        (
            len(entries) == 2,
            set(evidence_types) == set(REQUIRED_LEDGER_EVIDENCE_TYPES),
            write_path_ok,
            restore_hash_bound,
            related_evidence_hashes_recovered,
            tenant_isolation_ok,
            duplicate_append_rejected,
            metadata_only_ok,
        )
    )
    return LegacySqlEvidenceLedgerBackendDrillResult(
        backend=backend,
        tenant_id=tenant_id,
        ledger_entry_count=len(entries),
        ledger_entry_hashes=ledger_entry_hashes,
        evidence_types=evidence_types,
        restore_evidence_hashes=restore_evidence_hashes,
        intake_report_hash=intake_report_hash,
        readiness_smoke_report_hash=readiness_smoke_report_hash,
        write_path_ok=write_path_ok,
        restore_hash_bound=restore_hash_bound,
        related_evidence_hashes_recovered=related_evidence_hashes_recovered,
        tenant_isolation_ok=tenant_isolation_ok,
        duplicate_append_rejected=duplicate_append_rejected,
        metadata_only_ok=metadata_only_ok,
        host_profile_release_precondition_ok=host_profile_release_precondition_ok,
        blocking_reasons=_blocking_reasons(
            entry_count=len(entries),
            evidence_types=evidence_types,
            write_path_ok=write_path_ok,
            restore_hash_bound=restore_hash_bound,
            related_evidence_hashes_recovered=related_evidence_hashes_recovered,
            tenant_isolation_ok=tenant_isolation_ok,
            duplicate_append_rejected=duplicate_append_rejected,
            metadata_only_ok=metadata_only_ok,
        ),
    )


def _selected_backends(env: Mapping[str, str]) -> tuple[LegacySqlEvidenceLedgerBackend, ...]:
    raw = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_BACKENDS", "jsonl")
    values = tuple(value.strip().lower() for value in raw.split(",") if value.strip())
    backends = tuple(LegacySqlEvidenceLedgerBackend(value) for value in values)
    return tuple(dict.fromkeys(backends))


def _tenant_id_for_backend(
    *,
    backend: LegacySqlEvidenceLedgerBackend,
    env: Mapping[str, str],
    run_id: str,
) -> str:
    prefix = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_TENANT_PREFIX", "tenant-legacy-sql-ledger-drill")
    return f"{prefix}-{backend.value}-{run_id.rsplit('-', maxsplit=1)[-1][:12]}"


def _backend_env(
    *,
    backend: LegacySqlEvidenceLedgerBackend,
    env: Mapping[str, str],
    checked_by: str,
    tenant_id: str,
    restore_hash: str,
    run_id: str,
) -> dict[str, str]:
    child_env = dict(env)
    child_env.update(
        {
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE": "true",
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_BACKEND": backend.value,
            "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH": restore_hash,
            "SUITE_LEGACY_SQL_INTAKE_TENANT_ID": tenant_id,
            "SUITE_LEGACY_SQL_READINESS_SMOKE_TENANT_ID": tenant_id,
            "SUITE_LEGACY_SQL_INTAKE_CHECKED_BY": checked_by,
            "SUITE_LEGACY_SQL_READINESS_SMOKE_CHECKED_BY": checked_by,
        }
    )
    if backend == LegacySqlEvidenceLedgerBackend.JSONL:
        jsonl_path = child_env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DRILL_JSONL_PATH")
        if jsonl_path is None:
            data_dir = Path(child_env.get("SUITE_DATA_DIR", "data"))
            jsonl_path = str(data_dir / f"{run_id}-{backend.value}.jsonl")
        child_env["SUITE_LEGACY_SQL_EVIDENCE_LEDGER_PATH"] = jsonl_path
    return child_env


def _tenant_isolation_ok(
    *,
    store: LegacySqlEvidenceLedgerStore,
    tenant_id: str,
    ledger_entry_hashes: tuple[str, ...],
) -> bool:
    probe_tenant = f"{tenant_id}-isolation-probe"
    if store.list_entries(tenant_id=probe_tenant):
        return False
    if not ledger_entry_hashes:
        return False
    try:
        store.get(tenant_id=probe_tenant, ledger_entry_hash=ledger_entry_hashes[0])
    except KeyError:
        return True
    return False


def _duplicate_append_rejected(
    *,
    store: LegacySqlEvidenceLedgerStore,
    entries: tuple[LegacySqlEvidenceLedgerEntry, ...],
) -> bool:
    if not entries:
        return False
    try:
        store.append(entries[0])
    except ValueError:
        return True
    return False


def _metadata_only_ok(entries: tuple[LegacySqlEvidenceLedgerEntry, ...]) -> bool:
    for entry in entries:
        if entry.raw_payload_included or entry.import_write_executed or entry.destructive_actions_executed:
            return False
        payload = entry.model_dump_json().lower()
        if any(fragment in payload for fragment in FORBIDDEN_LEDGER_DRILL_FRAGMENTS):
            return False
    return True


def _blocking_reasons(
    *,
    entry_count: int,
    evidence_types: tuple[LegacySqlEvidenceType, ...],
    write_path_ok: bool,
    restore_hash_bound: bool,
    related_evidence_hashes_recovered: bool,
    tenant_isolation_ok: bool,
    duplicate_append_rejected: bool,
    metadata_only_ok: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if entry_count != 2:
        reasons.append("legacy_sql_evidence_ledger_entry_count_mismatch")
    if set(evidence_types) != set(REQUIRED_LEDGER_EVIDENCE_TYPES):
        reasons.append("legacy_sql_evidence_ledger_evidence_types_mismatch")
    if not write_path_ok:
        reasons.append("legacy_sql_evidence_ledger_write_path_failed")
    if not restore_hash_bound:
        reasons.append("legacy_sql_evidence_ledger_restore_hash_not_bound")
    if not related_evidence_hashes_recovered:
        reasons.append("legacy_sql_evidence_ledger_related_hashes_missing")
    if not tenant_isolation_ok:
        reasons.append("legacy_sql_evidence_ledger_tenant_isolation_failed")
    if not duplicate_append_rejected:
        reasons.append("legacy_sql_evidence_ledger_append_only_check_failed")
    if not metadata_only_ok:
        reasons.append("legacy_sql_evidence_ledger_metadata_boundary_failed")
    return tuple(reasons)


def _recommended_actions(
    backend_results: tuple[LegacySqlEvidenceLedgerBackendDrillResult, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    for result in backend_results:
        if result.host_profile_release_precondition_ok:
            continue
        reasons = ",".join(result.blocking_reasons)
        actions.append(f"{result.backend.value}: repair legacy SQL evidence ledger drill ({reasons})")
    if not actions:
        actions.append("legacy SQL evidence ledger JSONL/Postgres write paths and restore-hash binding are ready")
    return tuple(actions)


if __name__ == "__main__":
    main()
