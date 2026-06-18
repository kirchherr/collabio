from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import (
    LegacySqlApprovedHostProfile,
    LegacySqlDiscoveryIntakeGate,
    LegacySqlDiscoveryIntakeRequest,
    LegacySqlDiscoveryIntakeStatus,
)
from suite.platform.legacy_sql_evidence_ledger import (
    LegacySqlEvidenceType,
    build_default_legacy_sql_evidence_ledger_store,
    build_legacy_sql_evidence_ledger_entry,
)
from suite.platform.legacy_sql_server_metadata import (
    DEFAULT_CONNECTOR_POLICY_PATH,
    LegacySqlServerMetadataDiscoveryCommand,
    build_legacy_sql_connector_policy_hash,
    load_legacy_sql_connector_policy,
)

LEGACY_SQL_DISCOVERY_INTAKE_CONTINUITY_DOMAIN = "crm_erp_business_records"
LEGACY_SQL_DISCOVERY_INTAKE_OPERATIONS_SCHEMA_VERSION = "legacy_sql_discovery_intake_operations_report.v1"
FORBIDDEN_INTAKE_REPORT_FRAGMENTS = (
    "connection_secret_ref",
    "secret:legacy-sql-intake-drill",
    "sqlserver://",
    "password",
    "dsn",
)


class LegacySqlMetadataWorkerCommandView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    include_row_counts: bool
    connector_policy_ref: str
    policy_snapshot_hash: str
    connection_fingerprint_hash: str
    secret_reference_available: bool


class LegacySqlDiscoveryIntakeOperationsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_DISCOVERY_INTAKE_OPERATIONS_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    continuity_domain: str = LEGACY_SQL_DISCOVERY_INTAKE_CONTINUITY_DOMAIN
    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    intake_evidence_hash: str
    intake_status: LegacySqlDiscoveryIntakeStatus
    metadata_worker_command_ready: bool
    metadata_worker_command_hash: str | None = None
    metadata_worker_command_view: LegacySqlMetadataWorkerCommandView | None = None
    metadata_discovery_allowed: bool
    real_connection_used: bool = False
    dry_run_executed: bool = False
    import_write_executed: bool = False
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    report_passed: bool
    evidence_hash: str


def build_legacy_sql_discovery_intake_operations_report_hash(
    report: LegacySqlDiscoveryIntakeOperationsReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_discovery_intake_operations_report(
    *,
    request: LegacySqlDiscoveryIntakeRequest,
    host_profile: LegacySqlApprovedHostProfile,
    checked_by: str = "legacy-sql-discovery-intake",
) -> LegacySqlDiscoveryIntakeOperationsReport:
    result = LegacySqlDiscoveryIntakeGate().evaluate(request=request, host_profile=host_profile)
    command_view = _command_view(result.command)
    command_hash = _command_hash(result.command)
    report_passed = (
        result.evidence.status == LegacySqlDiscoveryIntakeStatus.READY_FOR_METADATA_WORKER
        and result.command is not None
        and command_view is not None
        and command_hash is not None
        and result.evidence.metadata_worker_command_ready
        and result.evidence.metadata_discovery_allowed
        and not result.evidence.import_dry_run_allowed
        and not result.evidence.import_write_allowed
        and not result.evidence.raw_data_import_allowed
        and not result.evidence.destructive_actions_allowed
    )
    draft = LegacySqlDiscoveryIntakeOperationsReport(
        run_id=f"legacy-sql-discovery-intake-{uuid4().hex}",
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        tenant_id=result.evidence.tenant_id,
        module_id=result.evidence.module_id,
        source_system_ref=result.evidence.source_system_ref,
        connector_kind=result.evidence.connector_kind,
        host_profile_ref=result.evidence.host_profile_ref,
        connector_policy_ref=result.evidence.connector_policy_ref,
        policy_snapshot_hash=result.evidence.policy_snapshot_hash,
        intake_evidence_hash=result.evidence.evidence_hash,
        intake_status=result.evidence.status,
        metadata_worker_command_ready=result.evidence.metadata_worker_command_ready,
        metadata_worker_command_hash=command_hash,
        metadata_worker_command_view=command_view,
        metadata_discovery_allowed=result.evidence.metadata_discovery_allowed,
        blocking_reasons=result.evidence.blocking_reasons,
        recommended_actions=_recommended_actions(report_passed=report_passed),
        report_passed=report_passed,
        evidence_hash="sha256:" + "0" * 64,
    )
    _assert_intake_operations_report_safe(draft)
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_discovery_intake_operations_report_hash(draft)})


def run_legacy_sql_discovery_intake_operations_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlDiscoveryIntakeOperationsReport:
    env = os.environ if environ is None else environ
    policy_path = Path(env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_PATH", str(DEFAULT_CONNECTOR_POLICY_PATH)))
    policy = load_legacy_sql_connector_policy(policy_path)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    connector_policy_ref = env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_REF", "policy:legacy-sql-connector")
    host_profile_ref = env.get("SUITE_LEGACY_SQL_INTAKE_HOST_PROFILE_REF", "legacy-host:sqlserver-intake-drill")
    checked_by = env.get("SUITE_LEGACY_SQL_INTAKE_CHECKED_BY", "legacy-sql-discovery-intake")

    host_profile = LegacySqlApprovedHostProfile(
        host_profile_ref=host_profile_ref,
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=policy_hash,
        approved_egress_ref=env.get("SUITE_LEGACY_SQL_INTAKE_APPROVED_EGRESS_REF", "egress:sqlserver-intake-drill"),
        connection_secret_ref=env.get("SUITE_LEGACY_SQL_INTAKE_SECRET_REF", "secret:legacy-sql-intake-drill"),
        connection_fingerprint_hash=env.get(
            "SUITE_LEGACY_SQL_INTAKE_CONNECTION_FINGERPRINT_HASH",
            "sha256:legacy-sql-intake-fingerprint",
        ),
        row_count_estimates_allowed=_env_bool(env, "SUITE_LEGACY_SQL_INTAKE_ROW_COUNTS_ALLOWED", default=True),
    )
    request_policy_hash = (
        "sha256:intake-policy-mismatch"
        if _env_bool(env, "SUITE_LEGACY_SQL_INTAKE_FORCE_POLICY_MISMATCH", default=False)
        else policy_hash
    )
    request = LegacySqlDiscoveryIntakeRequest(
        tenant_id=env.get("SUITE_LEGACY_SQL_INTAKE_TENANT_ID", "tenant-demo"),
        module_id="crm_erp",
        source_system_ref=env.get("SUITE_LEGACY_SQL_INTAKE_SOURCE_REF", "legacy-sql:intake-drill-sqlserver"),
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        requested_by=checked_by,
        approval_reference=env.get("SUITE_LEGACY_SQL_INTAKE_APPROVAL_REF", "approval:legacy-sql-intake-drill"),
        audit_chain_ref=env.get("SUITE_LEGACY_SQL_INTAKE_AUDIT_REF", "audit:legacy-sql-intake-drill"),
        host_profile_ref=host_profile_ref,
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=request_policy_hash,
        include_row_counts=_env_bool(env, "SUITE_LEGACY_SQL_INTAKE_INCLUDE_ROW_COUNTS", default=True),
    )
    report = build_legacy_sql_discovery_intake_operations_report(
        request=request,
        host_profile=host_profile,
        checked_by=checked_by,
    )
    _append_intake_operations_report_to_ledger_if_enabled(report=report, env=env)
    return report


def exit_code_for_report(report: LegacySqlDiscoveryIntakeOperationsReport) -> int:
    return 0 if report.report_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the metadata-only Legacy SQL discovery intake drill.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only intake drill and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only intake report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_discovery_intake_operations_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _command_view(
    command: LegacySqlServerMetadataDiscoveryCommand | None,
) -> LegacySqlMetadataWorkerCommandView | None:
    if command is None:
        return None
    return LegacySqlMetadataWorkerCommandView(
        tenant_id=command.request.tenant_id,
        module_id=command.request.module_id,
        source_system_ref=command.request.source_system_ref,
        connector_kind=command.request.connector_kind,
        include_row_counts=command.request.include_row_counts,
        connector_policy_ref=command.connector_policy_ref,
        policy_snapshot_hash=command.policy_snapshot_hash,
        connection_fingerprint_hash=command.connection_fingerprint_hash,
        secret_reference_available=bool(command.connection_secret_ref.strip()),
    )


def _command_hash(command: LegacySqlServerMetadataDiscoveryCommand | None) -> str | None:
    view = _command_view(command)
    if view is None:
        return None
    return stable_hash(canonical_json(view.model_dump(mode="json")))


def _recommended_actions(*, report_passed: bool) -> tuple[str, ...]:
    if report_passed:
        return (
            "persist intake evidence before scheduling metadata worker",
            "schedule only the redacted metadata-worker command view for operator review",
            "keep real connection execution disabled until approved host-network profile exists",
        )
    return ("repair legacy SQL discovery intake blockers before creating a metadata-worker command",)


def _append_intake_operations_report_to_ledger_if_enabled(
    *,
    report: LegacySqlDiscoveryIntakeOperationsReport,
    env: Mapping[str, str],
) -> None:
    if not _env_bool(env, "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE", default=False):
        return
    restore_evidence_hash = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH")
    if restore_evidence_hash is None or not restore_evidence_hash.strip():
        raise ValueError("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH is required when ledger writes are enabled")

    related_hashes = _unique_evidence_hashes(
        report.intake_evidence_hash,
        report.metadata_worker_command_hash,
    )
    entry = build_legacy_sql_evidence_ledger_entry(
        tenant_id=report.tenant_id,
        module_id=report.module_id,
        source_system_ref=report.source_system_ref,
        evidence_type=LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT,
        evidence_ref=f"legacy-sql-intake-ops:{report.evidence_hash}",
        evidence_hash=report.evidence_hash,
        evidence_status=report.intake_status.value,
        related_evidence_hashes=related_hashes,
        restore_evidence_hash=restore_evidence_hash,
        captured_by=report.checked_by,
        metadata={
            "metadata_worker_ready": str(report.metadata_worker_command_ready).lower(),
            "report_passed": str(report.report_passed).lower(),
            "schema_version": report.schema_version,
        },
    )
    build_default_legacy_sql_evidence_ledger_store(environ=env).append(entry)


def _unique_evidence_hashes(*values: str | None) -> tuple[str, ...]:
    hashes: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value in seen:
            continue
        hashes.append(value)
        seen.add(value)
    return tuple(hashes)


def _assert_intake_operations_report_safe(report: LegacySqlDiscoveryIntakeOperationsReport) -> None:
    payload = report.model_dump_json()
    for fragment in FORBIDDEN_INTAKE_REPORT_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL intake operations report leaked forbidden fragment: {fragment}")


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
