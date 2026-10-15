from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.crm_erp_legacy_mapping import (
    CrmErpLegacyImportReadinessEvidence,
    CrmErpLegacyImportReadinessStatus,
    CrmErpLegacyMappingAction,
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingOverride,
    build_crm_erp_legacy_import_readiness_evidence,
)
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind, LegacySqlDiscoveryRequest
from suite.platform.legacy_sql_evidence_ledger import (
    LegacySqlEvidenceType,
    build_default_legacy_sql_evidence_ledger_store,
    build_legacy_sql_evidence_ledger_entry,
)
from suite.platform.legacy_sql_server_metadata import (
    DEFAULT_CONNECTOR_POLICY_PATH,
    LegacySqlMetadataQuery,
    LegacySqlServerMetadataDiscoveryCommand,
    LegacySqlServerMetadataWorker,
    LegacySqlServerNetworkMode,
    build_legacy_sql_connector_policy_hash,
    load_legacy_sql_connector_policy,
)

LEGACY_SQL_READINESS_CONTINUITY_DOMAIN = "crm_erp_business_records"
LEGACY_SQL_READINESS_SMOKE_SCHEMA_VERSION = "legacy_sql_readiness_smoke_report.v1"
FORBIDDEN_REPORT_FRAGMENTS = (
    "dbo.Kunden",
    "dbo.FreieTabelle",
    "KundenId",
    "Email",
    "sample_value",
    "connection_secret_ref",
    "secret:legacy-sql-smoke",
)


class LegacySqlReadinessSmokeScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    mapping_manifest_hash: str
    readiness_evidence_hash: str
    readiness_status: CrmErpLegacyImportReadinessStatus
    dry_run_allowed: bool
    import_write_allowed: bool = False
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    target_mapping_count: int = Field(ge=0)
    quarantine_table_count: int = Field(ge=0)
    legacy_row_table_count: int = Field(ge=0)
    blocking_reasons: tuple[str, ...]


class LegacySqlReadinessSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_READINESS_SMOKE_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    continuity_domain: str = LEGACY_SQL_READINESS_CONTINUITY_DOMAIN
    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    connector_policy_ref: str
    policy_snapshot_hash: str
    metadata_worker_network_mode: LegacySqlServerNetworkMode
    executed_query_names: tuple[str, ...]
    audit_event_types: tuple[str, ...]
    table_count: int = Field(ge=1)
    column_count: int = Field(ge=1)
    discovery_manifest_hash: str
    import_evidence_plan_hash: str
    scenarios: tuple[LegacySqlReadinessSmokeScenario, ...]
    metadata_only_ok: bool
    real_connection_used: bool = False
    dry_run_executed: bool = False
    import_write_executed: bool = False
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    recommended_actions: tuple[str, ...]
    smoke_passed: bool
    evidence_hash: str


@dataclass
class FixtureLegacySqlMetadataExecutor:
    rows_by_query: dict[str, list[dict[str, Any]]]
    calls: list[LegacySqlMetadataQuery] = field(default_factory=list)
    connection_secret_refs: list[str] = field(default_factory=list)

    def fetch_all(
        self,
        *,
        connection_secret_ref: str,
        query: LegacySqlMetadataQuery,
    ) -> list[dict[str, Any]]:
        self.connection_secret_refs.append(connection_secret_ref)
        self.calls.append(query)
        return self.rows_by_query.get(query.name, [])


@dataclass
class CapturingLegacySqlSmokeAuditSink:
    event_types: list[str] = field(default_factory=list)

    def record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, Any],
    ) -> str:
        del tenant_id, source_system_ref, metadata
        self.event_types.append(event_type)
        return f"audit:legacy-sql-readiness-smoke-{len(self.event_types)}"


def build_legacy_sql_readiness_smoke_report_hash(report: LegacySqlReadinessSmokeReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_readiness_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlReadinessSmokeReport:
    env = os.environ if environ is None else environ
    policy_path = Path(env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_PATH", str(DEFAULT_CONNECTOR_POLICY_PATH)))
    policy = load_legacy_sql_connector_policy(policy_path)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    tenant_id = env.get("SUITE_LEGACY_SQL_READINESS_SMOKE_TENANT_ID", "tenant-demo")
    source_system_ref = env.get("SUITE_LEGACY_SQL_READINESS_SMOKE_SOURCE_REF", "legacy-sql:smoke-sqlserver")
    connector_policy_ref = env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_REF", "policy:legacy-sql-connector")

    command = LegacySqlServerMetadataDiscoveryCommand(
        request=LegacySqlDiscoveryRequest(
            tenant_id=tenant_id,
            module_id="crm_erp",
            source_system_ref=source_system_ref,
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            requested_by=env.get("SUITE_LEGACY_SQL_READINESS_SMOKE_CHECKED_BY", "legacy-sql-readiness-smoke"),
            approval_reference="approval:legacy-sql-readiness-smoke",
            audit_chain_ref="audit:legacy-sql-readiness-smoke",
            include_row_counts=True,
        ),
        connection_secret_ref="secret:legacy-sql-smoke",
        connection_fingerprint_hash="sha256:legacy-sql-smoke-fingerprint",
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=policy_hash,
    )
    executor = FixtureLegacySqlMetadataExecutor(_fixture_metadata_rows())
    audit_sink = CapturingLegacySqlSmokeAuditSink()
    worker = LegacySqlServerMetadataWorker(policy=policy, executor=executor, audit_sink=audit_sink)
    metadata_result = worker.discover(command)

    mapping_service = CrmErpLegacyMappingEvidenceService()
    manual_mapping = mapping_service.build_mapping_manifest(
        discovery_manifest=metadata_result.manifest,
        import_evidence_plan=metadata_result.import_evidence_plan,
    )
    manual_readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=metadata_result.manifest,
        import_evidence_plan=metadata_result.import_evidence_plan,
        mapping_manifest=manual_mapping,
    )
    override_mapping = mapping_service.build_mapping_manifest(
        discovery_manifest=metadata_result.manifest,
        import_evidence_plan=metadata_result.import_evidence_plan,
        overrides=(
            CrmErpLegacyMappingOverride(
                source_table_ref="dbo.FreieTabelle",
                action=CrmErpLegacyMappingAction.MAP_TO_TARGET,
                target_object_type="crm.contact",
                mapping_reason="metadata smoke fixture maps free-form table after manual approval",
                approval_reference="approval:legacy-sql-readiness-smoke-override",
            ),
        ),
    )
    override_readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=metadata_result.manifest,
        import_evidence_plan=metadata_result.import_evidence_plan,
        mapping_manifest=override_mapping,
    )

    scenarios = (
        _scenario_from_readiness(
            scenario_id="manual_mapping_blocks_dry_run",
            mapping_manifest_hash=manual_mapping.manifest_hash,
            readiness=manual_readiness,
        ),
        _scenario_from_readiness(
            scenario_id="approved_override_allows_metadata_dry_run",
            mapping_manifest_hash=override_mapping.manifest_hash,
            readiness=override_readiness,
        ),
    )
    smoke_passed = _smoke_passed(
        scenarios=scenarios,
        audit_event_types=tuple(audit_sink.event_types),
        executor=executor,
    )
    draft = LegacySqlReadinessSmokeReport(
        run_id=f"legacy-sql-readiness-smoke-{uuid4().hex}",
        checked_by=env.get("SUITE_LEGACY_SQL_READINESS_SMOKE_CHECKED_BY", "legacy-sql-readiness-smoke"),
        checked_at_utc=datetime.now(UTC),
        tenant_id=metadata_result.manifest.tenant_id,
        module_id=metadata_result.manifest.module_id,
        source_system_ref=metadata_result.manifest.source_system_ref,
        connector_kind=metadata_result.manifest.connector_kind,
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=policy_hash,
        metadata_worker_network_mode=metadata_result.worker_network_mode,
        executed_query_names=metadata_result.executed_query_names,
        audit_event_types=tuple(audit_sink.event_types),
        table_count=metadata_result.manifest.table_count,
        column_count=metadata_result.manifest.column_count,
        discovery_manifest_hash=metadata_result.manifest.manifest_hash,
        import_evidence_plan_hash=metadata_result.import_evidence_plan.manifest_hash,
        scenarios=scenarios,
        metadata_only_ok=True,
        recommended_actions=_recommended_actions(smoke_passed=smoke_passed),
        smoke_passed=smoke_passed,
        evidence_hash="sha256:" + "0" * 64,
    )
    _assert_smoke_report_has_no_raw_or_table_metadata(draft)
    report = draft.model_copy(update={"evidence_hash": build_legacy_sql_readiness_smoke_report_hash(draft)})
    _append_readiness_smoke_report_to_ledger_if_enabled(report=report, env=env)
    return report


def exit_code_for_report(report: LegacySqlReadinessSmokeReport) -> int:
    return 0 if report.smoke_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the metadata-only Legacy SQL readiness smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only smoke report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_readiness_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _scenario_from_readiness(
    *,
    scenario_id: str,
    mapping_manifest_hash: str,
    readiness: CrmErpLegacyImportReadinessEvidence,
) -> LegacySqlReadinessSmokeScenario:
    return LegacySqlReadinessSmokeScenario(
        scenario_id=scenario_id,
        mapping_manifest_hash=mapping_manifest_hash,
        readiness_evidence_hash=readiness.evidence_hash,
        readiness_status=readiness.status,
        dry_run_allowed=readiness.dry_run_allowed,
        import_write_allowed=readiness.import_write_allowed,
        raw_data_import_allowed=readiness.raw_data_import_allowed,
        destructive_actions_allowed=readiness.destructive_actions_allowed,
        target_mapping_count=readiness.target_mapping_count,
        quarantine_table_count=readiness.quarantine_table_count,
        legacy_row_table_count=readiness.legacy_row_table_count,
        blocking_reasons=readiness.blocking_reasons,
    )


def _smoke_passed(
    *,
    scenarios: tuple[LegacySqlReadinessSmokeScenario, ...],
    audit_event_types: tuple[str, ...],
    executor: FixtureLegacySqlMetadataExecutor,
) -> bool:
    scenarios_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    manual = scenarios_by_id.get("manual_mapping_blocks_dry_run")
    override = scenarios_by_id.get("approved_override_allows_metadata_dry_run")
    if manual is None or override is None:
        return False
    return (
        audit_event_types
        == (
            "legacy_sql.metadata_discovery.started",
            "legacy_sql.metadata_discovery.completed",
        )
        and tuple(query.name for query in executor.calls)
        == ("tables", "columns", "primary_keys", "foreign_keys", "indexes", "row_counts")
        and manual.readiness_status == CrmErpLegacyImportReadinessStatus.MANUAL_MAPPING_REQUIRED
        and not manual.dry_run_allowed
        and manual.quarantine_table_count == 1
        and manual.legacy_row_table_count == 1
        and override.readiness_status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN
        and override.dry_run_allowed
        and override.quarantine_table_count == 0
        and override.legacy_row_table_count == 0
        and not any(scenario.import_write_allowed for scenario in scenarios)
        and not any(scenario.raw_data_import_allowed for scenario in scenarios)
        and not any(scenario.destructive_actions_allowed for scenario in scenarios)
    )


def _recommended_actions(*, smoke_passed: bool) -> tuple[str, ...]:
    if smoke_passed:
        return (
            "retain legacy SQL readiness smoke report hash with CRM/ERP release evidence",
            "require ready_for_dry_run readiness before any real import dry-run",
            "keep import writes disabled until dry-run report and human approval exist",
        )
    return ("repair metadata-only legacy SQL readiness smoke before connecting real legacy SQL",)


def _append_readiness_smoke_report_to_ledger_if_enabled(
    *,
    report: LegacySqlReadinessSmokeReport,
    env: Mapping[str, str],
) -> None:
    if not _env_bool(env, "SUITE_LEGACY_SQL_EVIDENCE_LEDGER_WRITE", default=False):
        return
    restore_evidence_hash = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH")
    if restore_evidence_hash is None or not restore_evidence_hash.strip():
        raise ValueError("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_RESTORE_HASH is required when ledger writes are enabled")

    related_hashes = _unique_evidence_hashes(
        report.discovery_manifest_hash,
        report.import_evidence_plan_hash,
        *(scenario.mapping_manifest_hash for scenario in report.scenarios),
        *(scenario.readiness_evidence_hash for scenario in report.scenarios),
    )
    entry = build_legacy_sql_evidence_ledger_entry(
        tenant_id=report.tenant_id,
        module_id=report.module_id,
        source_system_ref=report.source_system_ref,
        evidence_type=LegacySqlEvidenceType.READINESS_SMOKE_REPORT,
        evidence_ref=f"legacy-sql-readiness-smoke:{report.evidence_hash}",
        evidence_hash=report.evidence_hash,
        evidence_status="smoke_passed" if report.smoke_passed else "smoke_failed",
        related_evidence_hashes=related_hashes,
        restore_evidence_hash=restore_evidence_hash,
        captured_by=report.checked_by,
        metadata={
            "scenario_count": str(len(report.scenarios)),
            "schema_version": report.schema_version,
            "smoke_passed": str(report.smoke_passed).lower(),
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


def _assert_smoke_report_has_no_raw_or_table_metadata(report: LegacySqlReadinessSmokeReport) -> None:
    payload = report.model_dump_json()
    for fragment in FORBIDDEN_REPORT_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL readiness smoke report leaked forbidden fragment: {fragment}")


def _fixture_metadata_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "tables": [
            {"schema_name": "dbo", "table_name": "Kunden", "relation_kind": "table"},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "relation_kind": "table"},
        ],
        "columns": [
            _column_row("dbo", "Kunden", "KundenId", 1, "int", "NO"),
            _column_row("dbo", "Kunden", "Name", 2, "nvarchar", "YES", max_length=255),
            _column_row("dbo", "Kunden", "Email", 3, "nvarchar", "YES", max_length=255),
            _column_row("dbo", "FreieTabelle", "Id", 1, "int", "NO"),
            _column_row("dbo", "FreieTabelle", "Text", 2, "nvarchar", "YES", max_length=255),
        ],
        "primary_keys": [
            {"schema_name": "dbo", "table_name": "Kunden", "column_name": "KundenId", "ordinal_position": 1},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "column_name": "Id", "ordinal_position": 1},
        ],
        "foreign_keys": [],
        "indexes": [
            {
                "schema_name": "dbo",
                "table_name": "Kunden",
                "index_name": "IX_Kunden_Email",
                "column_name": "Email",
                "ordinal_position": 1,
                "is_unique": False,
            }
        ],
        "row_counts": [
            {"schema_name": "dbo", "table_name": "Kunden", "row_count_estimate": 12},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "row_count_estimate": 3},
        ],
    }


def _column_row(
    schema_name: str,
    table_name: str,
    column_name: str,
    ordinal_position: int,
    data_type: str,
    is_nullable: str,
    *,
    max_length: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": schema_name,
        "table_name": table_name,
        "column_name": column_name,
        "ordinal_position": ordinal_position,
        "data_type": data_type,
        "is_nullable": is_nullable,
        "max_length": max_length,
        "numeric_precision": None,
        "numeric_scale": None,
        "is_identity": ordinal_position == 1,
        "default_present": False,
    }


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
