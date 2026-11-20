from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.crm_erp_legacy_mapping import (
    CRM_ERP_MODULE_ID,
    CrmErpLegacyChecksumStrategy,
    CrmErpLegacyImportDryRunPlan,
    CrmErpLegacyImportDryRunStatus,
    CrmErpLegacyImportDryRunTablePlan,
    CrmErpLegacyMappingAction,
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingOverride,
    CrmErpLegacyRowCountStrategy,
    build_crm_erp_legacy_import_dry_run_plan,
    build_crm_erp_legacy_import_readiness_evidence,
    build_crm_erp_legacy_staging_metadata_plan,
    validate_table_ref,
)
from suite.platform.legacy_sql_discovery import (
    NAMESPACED_REF_PATTERN,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryRequest,
    LegacySqlImportEvidencePlan,
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
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_IMPORT_DRY_RUN_RESULT_SCHEMA_VERSION = "legacy_sql_import_dry_run_result.v1"
LEGACY_SQL_IMPORT_DRY_RUN_WORKER_REPORT_SCHEMA_VERSION = "legacy_sql_import_dry_run_worker_report.v1"
LEGACY_SQL_IMPORT_DRY_RUN_RESULT_REF_PREFIX = "legacy-sql-import-dry-run-result"
LEGACY_SQL_IMPORT_DRY_RUN_CONTINUITY_DOMAIN = "crm_erp_business_records"
LEGACY_SQL_IMPORT_DRY_RUN_COMMAND_REF = "docker-compose:legacy-sql-import-dry-run-worker"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
FORBIDDEN_WORKER_REPORT_FRAGMENTS = (
    "dbo.Kunden",
    "dbo.FreieTabelle",
    "KundenId",
    "Email",
    "sample_value",
    "connection_secret_ref",
    "secret:legacy-sql-dry-run",
    "sqlserver://",
)
FORBIDDEN_RESULT_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:",
    "sqlserver://",
    "password",
    "sample_value",
    "raw_payload",
    "import_write_payload",
    "kundenid",
    "email",
)


class LegacySqlImportDryRunResultBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlImportDryRunResultStatus(StrEnum):
    COMPLETED_METADATA_ONLY = "completed_metadata_only"
    BLOCKED_BY_PLAN = "blocked_by_plan"


class LegacySqlImportDryRunTableResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_system_ref: str
    source_table_ref: str
    target_object_type: str
    staging_profile_object_id: str
    row_count_strategy: CrmErpLegacyRowCountStrategy = CrmErpLegacyRowCountStrategy.EXACT_READ_ONLY_COUNT_QUERY
    row_count_checked: bool = True
    observed_row_count: int = Field(ge=0)
    checksum_strategy: CrmErpLegacyChecksumStrategy = CrmErpLegacyChecksumStrategy.SHA256_CANONICAL_ROW_HASH_MANIFEST
    checksum_manifest_built: bool = True
    checksum_manifest_hash: str
    manifest_hash_required: bool = True
    audit_event_type: str = "legacy_sql.import_dry_run.table_validated"
    table_result_hash: str

    @field_validator("tenant_id")
    @classmethod
    def require_tenant_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import dry-run table result tenant_id must not be empty")
        return value

    @field_validator("source_system_ref", "staging_profile_object_id")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import dry-run table result references must be namespaced")
        return value

    @field_validator("source_table_ref")
    @classmethod
    def validate_source_table_ref(cls, value: str) -> str:
        validate_table_ref(value)
        return value

    @field_validator("checksum_manifest_hash", "table_result_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import dry-run table result hashes must be sha256 references")
        return value

    @field_validator("audit_event_type")
    @classmethod
    def require_table_audit_event(cls, value: str) -> str:
        if value != "legacy_sql.import_dry_run.table_validated":
            raise ValueError("legacy SQL import dry-run table audit event is fixed")
        return value

    @model_validator(mode="after")
    def require_metadata_only_table_result(self) -> Self:
        if not self.row_count_checked:
            raise ValueError("legacy SQL import dry-run table result requires row-count check")
        if not self.checksum_manifest_built:
            raise ValueError("legacy SQL import dry-run table result requires checksum manifest")
        if not self.manifest_hash_required:
            raise ValueError("legacy SQL import dry-run table result requires manifest hashes")
        return self


class LegacySqlImportDryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_DRY_RUN_RESULT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    dry_run_plan_hash: str
    discovery_manifest_hash: str
    mapping_manifest_hash: str
    readiness_evidence_hash: str
    staging_metadata_plan_hash: str
    status: LegacySqlImportDryRunResultStatus
    table_result_count: int = Field(ge=0)
    expected_table_count: int = Field(ge=1)
    table_results: tuple[LegacySqlImportDryRunTableResult, ...]
    blocking_reasons: tuple[str, ...]
    row_count_strategy: CrmErpLegacyRowCountStrategy = CrmErpLegacyRowCountStrategy.EXACT_READ_ONLY_COUNT_QUERY
    checksum_strategy: CrmErpLegacyChecksumStrategy = CrmErpLegacyChecksumStrategy.SHA256_CANONICAL_ROW_HASH_MANIFEST
    audit_event_types: tuple[str, ...]
    metadata_only_ok: bool = True
    dry_run_execution_attempted: bool
    dry_run_execution_completed: bool
    real_connection_used: bool = False
    raw_data_import_allowed: bool = False
    import_write_executed: bool = False
    destructive_actions_executed: bool = False
    executed_by: str
    executed_at_utc: datetime
    result_hash: str

    @field_validator("tenant_id", "executed_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import dry-run result text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import dry-run result only applies to module crm_erp")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_ref(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import dry-run result references must be namespaced")
        return value

    @field_validator(
        "dry_run_plan_hash",
        "discovery_manifest_hash",
        "mapping_manifest_hash",
        "readiness_evidence_hash",
        "staging_metadata_plan_hash",
        "result_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import dry-run result hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons", "audit_event_types")
    @classmethod
    def validate_unique_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL import dry-run result lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL import dry-run result lists must not contain empty entries")
        return value

    @model_validator(mode="after")
    def require_metadata_only_result(self) -> Self:
        if (
            not self.metadata_only_ok
            or self.real_connection_used
            or self.raw_data_import_allowed
            or self.import_write_executed
            or self.destructive_actions_executed
        ):
            raise ValueError("legacy SQL import dry-run result must remain metadata-only")
        if self.table_result_count != len(self.table_results):
            raise ValueError("legacy SQL import dry-run table_result_count must match table_results")
        table_refs = [table.source_table_ref.lower() for table in self.table_results]
        if len(set(table_refs)) != len(table_refs):
            raise ValueError("legacy SQL import dry-run table results must be unique per source table")
        for table_result in self.table_results:
            if table_result.tenant_id != self.tenant_id:
                raise ValueError("legacy SQL import dry-run table result tenant mismatch")
            if table_result.source_system_ref != self.source_system_ref:
                raise ValueError("legacy SQL import dry-run table result source-system mismatch")
            if table_result.row_count_strategy != self.row_count_strategy:
                raise ValueError("legacy SQL import dry-run table result row-count strategy mismatch")
            if table_result.checksum_strategy != self.checksum_strategy:
                raise ValueError("legacy SQL import dry-run table result checksum strategy mismatch")
            if build_legacy_sql_import_dry_run_table_result_hash(table_result) != table_result.table_result_hash:
                raise ValueError("legacy SQL import dry-run table result hash invalid")
        if self.status == LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY:
            if not self.dry_run_execution_attempted or not self.dry_run_execution_completed:
                raise ValueError("completed import dry-run result requires completed execution")
            if self.blocking_reasons:
                raise ValueError("completed import dry-run result must not include blockers")
            if self.table_result_count != self.expected_table_count:
                raise ValueError("completed import dry-run result must cover every planned table")
        if self.status == LegacySqlImportDryRunResultStatus.BLOCKED_BY_PLAN:
            if self.dry_run_execution_completed:
                raise ValueError("blocked import dry-run result must not complete execution")
            if not self.blocking_reasons:
                raise ValueError("blocked import dry-run result requires blocking reasons")
        _assert_result_evidence_safe(self)
        return self


class LegacySqlImportDryRunWorkerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_DRY_RUN_WORKER_REPORT_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    continuity_domain: str = LEGACY_SQL_IMPORT_DRY_RUN_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_IMPORT_DRY_RUN_COMMAND_REF
    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    metadata_worker_network_mode: LegacySqlServerNetworkMode
    dry_run_plan_hash: str
    dry_run_result_hash: str
    result_status: LegacySqlImportDryRunResultStatus
    planned_table_count: int = Field(ge=1)
    table_result_count: int = Field(ge=0)
    metadata_only_ok: bool
    result_store_write_enabled: bool
    result_store_backend: LegacySqlImportDryRunResultBackend | None
    real_connection_used: bool = False
    raw_data_import_allowed: bool = False
    import_write_executed: bool = False
    destructive_actions_executed: bool = False
    recommended_actions: tuple[str, ...]
    worker_passed: bool
    evidence_hash: str


class LegacySqlImportDryRunResultStore(Protocol):
    def append(self, result: LegacySqlImportDryRunResult) -> LegacySqlImportDryRunResult:
        raise NotImplementedError

    def get(self, *, tenant_id: str, result_hash: str) -> LegacySqlImportDryRunResult:
        raise NotImplementedError

    def list_results(self, *, tenant_id: str) -> tuple[LegacySqlImportDryRunResult, ...]:
        raise NotImplementedError


class InMemoryLegacySqlImportDryRunResultStore:
    def __init__(self, results: Sequence[LegacySqlImportDryRunResult] = ()) -> None:
        self._results: dict[tuple[str, str], LegacySqlImportDryRunResult] = {}
        for result in results:
            self.append(result)

    def append(self, result: LegacySqlImportDryRunResult) -> LegacySqlImportDryRunResult:
        _require_valid_result_hash(result)
        key = (result.tenant_id, result.result_hash)
        if key in self._results:
            raise ValueError("legacy SQL import dry-run result already exists")
        self._results[key] = result
        return result

    def get(self, *, tenant_id: str, result_hash: str) -> LegacySqlImportDryRunResult:
        try:
            return self._results[(tenant_id, result_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL import dry-run result not found") from exc

    def list_results(self, *, tenant_id: str) -> tuple[LegacySqlImportDryRunResult, ...]:
        return tuple(result for (stored_tenant_id, _), result in self._results.items() if stored_tenant_id == tenant_id)


class JsonlLegacySqlImportDryRunResultStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._results: dict[tuple[str, str], LegacySqlImportDryRunResult] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            result = LegacySqlImportDryRunResult.model_validate_json(line)
            _require_valid_result_hash(result)
            key = (result.tenant_id, result.result_hash)
            if key in self._results:
                raise ValueError("duplicate legacy SQL import dry-run result in store")
            self._results[key] = result

    def append(self, result: LegacySqlImportDryRunResult) -> LegacySqlImportDryRunResult:
        _require_valid_result_hash(result)
        key = (result.tenant_id, result.result_hash)
        if key in self._results:
            raise ValueError("legacy SQL import dry-run result already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.model_dump(mode="json"), sort_keys=True) + "\n")
        self._results[key] = result
        return result

    def get(self, *, tenant_id: str, result_hash: str) -> LegacySqlImportDryRunResult:
        try:
            return self._results[(tenant_id, result_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL import dry-run result not found") from exc

    def list_results(self, *, tenant_id: str) -> tuple[LegacySqlImportDryRunResult, ...]:
        return tuple(result for (stored_tenant_id, _), result in self._results.items() if stored_tenant_id == tenant_id)


class PgLegacySqlImportDryRunResultStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, result: LegacySqlImportDryRunResult) -> LegacySqlImportDryRunResult:
        _require_valid_result_hash(result)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, result.tenant_id)
                connection.execute(
                    """
                    INSERT INTO crm_erp_legacy.import_dry_run_results (
                        tenant_id,
                        module_id,
                        source_system_ref,
                        dry_run_plan_hash,
                        discovery_manifest_hash,
                        mapping_manifest_hash,
                        readiness_evidence_hash,
                        staging_metadata_plan_hash,
                        status,
                        table_result_count,
                        expected_table_count,
                        table_results,
                        blocking_reasons,
                        row_count_strategy,
                        checksum_strategy,
                        audit_event_types,
                        metadata_only_ok,
                        dry_run_execution_attempted,
                        dry_run_execution_completed,
                        real_connection_used,
                        raw_data_import_allowed,
                        import_write_executed,
                        destructive_actions_executed,
                        executed_by,
                        executed_at_utc,
                        result_evidence,
                        result_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._result_values(result),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("legacy SQL import dry-run result already exists") from exc
        return result

    def get(self, *, tenant_id: str, result_hash: str) -> LegacySqlImportDryRunResult:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT result_evidence
                FROM crm_erp_legacy.import_dry_run_results
                WHERE tenant_id = %s
                  AND result_hash = %s
                """,
                (tenant_id, result_hash),
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL import dry-run result not found")
        return self._result_from_row(row)

    def list_results(self, *, tenant_id: str) -> tuple[LegacySqlImportDryRunResult, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT result_evidence
                FROM crm_erp_legacy.import_dry_run_results
                WHERE tenant_id = %s
                ORDER BY executed_at_utc, result_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._result_from_row(row) for row in rows)

    def _result_values(self, result: LegacySqlImportDryRunResult) -> tuple[object, ...]:
        return (
            result.tenant_id,
            result.module_id,
            result.source_system_ref,
            result.dry_run_plan_hash,
            result.discovery_manifest_hash,
            result.mapping_manifest_hash,
            result.readiness_evidence_hash,
            result.staging_metadata_plan_hash,
            result.status.value,
            result.table_result_count,
            result.expected_table_count,
            Jsonb([table_result.model_dump(mode="json") for table_result in result.table_results]),
            Jsonb(list(result.blocking_reasons)),
            result.row_count_strategy.value,
            result.checksum_strategy.value,
            list(result.audit_event_types),
            result.metadata_only_ok,
            result.dry_run_execution_attempted,
            result.dry_run_execution_completed,
            result.real_connection_used,
            result.raw_data_import_allowed,
            result.import_write_executed,
            result.destructive_actions_executed,
            result.executed_by,
            result.executed_at_utc,
            Jsonb(result.model_dump(mode="json")),
            result.result_hash,
            result.schema_version,
        )

    def _result_from_row(self, row: tuple[Any, ...]) -> LegacySqlImportDryRunResult:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        result = LegacySqlImportDryRunResult.model_validate(parsed)
        _require_valid_result_hash(result)
        return result

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


@dataclass
class FixtureLegacySqlImportDryRunMetadataExecutor:
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
class CapturingLegacySqlImportDryRunAuditSink:
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
        return f"audit:legacy-sql-import-dry-run-{len(self.event_types)}"


def execute_legacy_sql_import_dry_run_plan(
    *,
    dry_run_plan: CrmErpLegacyImportDryRunPlan,
    row_count_observations: Mapping[str, int],
    checksum_manifest_hashes: Mapping[str, str],
    executed_by: str,
    executed_at_utc: datetime | None = None,
) -> LegacySqlImportDryRunResult:
    checked_at = executed_at_utc or datetime.now(UTC)
    if (
        dry_run_plan.status != CrmErpLegacyImportDryRunStatus.READY_FOR_METADATA_DRY_RUN
        or not dry_run_plan.dry_run_execution_allowed
    ):
        return _blocked_result_from_plan(
            dry_run_plan=dry_run_plan,
            executed_by=executed_by,
            executed_at_utc=checked_at,
        )
    table_results = tuple(
        _execute_table_dry_run(
            table_plan=table_plan,
            row_count_observations=row_count_observations,
            checksum_manifest_hashes=checksum_manifest_hashes,
        )
        for table_plan in dry_run_plan.table_plans
    )
    draft = LegacySqlImportDryRunResult(
        tenant_id=dry_run_plan.tenant_id,
        module_id=dry_run_plan.module_id,
        source_system_ref=dry_run_plan.source_system_ref,
        dry_run_plan_hash=dry_run_plan.manifest_hash,
        discovery_manifest_hash=dry_run_plan.discovery_manifest_hash,
        mapping_manifest_hash=dry_run_plan.mapping_manifest_hash,
        readiness_evidence_hash=dry_run_plan.readiness_evidence_hash,
        staging_metadata_plan_hash=dry_run_plan.staging_metadata_plan_hash,
        status=LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY,
        table_result_count=len(table_results),
        expected_table_count=dry_run_plan.planned_table_count,
        table_results=table_results,
        blocking_reasons=(),
        row_count_strategy=dry_run_plan.row_count_strategy,
        checksum_strategy=dry_run_plan.checksum_strategy,
        audit_event_types=dry_run_plan.required_audit_event_types,
        dry_run_execution_attempted=True,
        dry_run_execution_completed=True,
        executed_by=executed_by,
        executed_at_utc=checked_at,
        result_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"result_hash": build_legacy_sql_import_dry_run_result_hash(draft)})


def run_legacy_sql_import_dry_run_worker_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlImportDryRunWorkerReport:
    env = os.environ if environ is None else environ
    checked_by = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_CHECKED_BY", "legacy-sql-import-dry-run-worker")
    checked_at = datetime.now(UTC)
    policy_path = Path(env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_PATH", str(DEFAULT_CONNECTOR_POLICY_PATH)))
    policy = load_legacy_sql_connector_policy(policy_path)
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    tenant_id = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_TENANT_ID", "tenant-demo")
    source_system_ref = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_SOURCE_REF", "legacy-sql:dry-run-sqlserver")

    command = LegacySqlServerMetadataDiscoveryCommand(
        request=LegacySqlDiscoveryRequest(
            tenant_id=tenant_id,
            module_id=CRM_ERP_MODULE_ID,
            source_system_ref=source_system_ref,
            connector_kind=LegacySqlConnectorKind.SQLSERVER,
            requested_by=checked_by,
            approval_reference="approval:legacy-sql-import-dry-run-worker",
            audit_chain_ref="audit:legacy-sql-import-dry-run-worker",
            include_row_counts=True,
        ),
        connection_secret_ref="secret:legacy-sql-dry-run",
        connection_fingerprint_hash="sha256:legacy-sql-dry-run-fingerprint",
        connector_policy_ref=env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_REF", "policy:legacy-sql-connector"),
        policy_snapshot_hash=policy_hash,
    )
    executor = FixtureLegacySqlImportDryRunMetadataExecutor(_fixture_metadata_rows())
    audit_sink = CapturingLegacySqlImportDryRunAuditSink()
    metadata_result = LegacySqlServerMetadataWorker(policy=policy, executor=executor, audit_sink=audit_sink).discover(
        command
    )
    dry_run_plan = _ready_fixture_dry_run_plan(
        import_evidence_plan=metadata_result.import_evidence_plan,
        discovery_manifest=metadata_result.manifest,
        captured_at_utc=checked_at,
    )
    result = execute_legacy_sql_import_dry_run_plan(
        dry_run_plan=dry_run_plan,
        row_count_observations={"dbo.Kunden": 12, "dbo.FreieTabelle": 3},
        checksum_manifest_hashes=_fixture_checksum_manifest_hashes(dry_run_plan),
        executed_by=checked_by,
        executed_at_utc=checked_at,
    )
    store_write_enabled = _env_bool(env, "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_WRITE", default=False)
    store_backend = _result_store_backend(env) if store_write_enabled else None
    if store_write_enabled:
        build_default_legacy_sql_import_dry_run_result_store(environ=env).append(result)
    worker_passed = (
        result.status == LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY
        and result.metadata_only_ok
        and result.table_result_count == dry_run_plan.planned_table_count
        and tuple(query.name for query in executor.calls)
        == ("tables", "columns", "primary_keys", "foreign_keys", "indexes", "row_counts")
        and audit_sink.event_types
        == [
            "legacy_sql.metadata_discovery.started",
            "legacy_sql.metadata_discovery.completed",
        ]
    )
    draft = LegacySqlImportDryRunWorkerReport(
        run_id=f"legacy-sql-import-dry-run-worker-{uuid4().hex}",
        checked_by=checked_by,
        checked_at_utc=checked_at,
        tenant_id=metadata_result.manifest.tenant_id,
        module_id=metadata_result.manifest.module_id,
        source_system_ref=metadata_result.manifest.source_system_ref,
        connector_kind=metadata_result.manifest.connector_kind,
        metadata_worker_network_mode=metadata_result.worker_network_mode,
        dry_run_plan_hash=dry_run_plan.manifest_hash,
        dry_run_result_hash=result.result_hash,
        result_status=result.status,
        planned_table_count=dry_run_plan.planned_table_count,
        table_result_count=result.table_result_count,
        metadata_only_ok=result.metadata_only_ok,
        result_store_write_enabled=store_write_enabled,
        result_store_backend=store_backend,
        recommended_actions=_recommended_actions(worker_passed=worker_passed),
        worker_passed=worker_passed,
        evidence_hash=ZERO_HASH,
    )
    _assert_worker_report_has_no_raw_or_table_metadata(draft)
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_import_dry_run_worker_report_hash(draft)})


def exit_code_for_report(report: LegacySqlImportDryRunWorkerReport) -> int:
    return 0 if report.worker_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the metadata-only Legacy SQL import dry-run worker.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only dry-run and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only worker report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_import_dry_run_worker_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def build_legacy_sql_import_dry_run_table_result_hash(result: LegacySqlImportDryRunTableResult) -> str:
    return stable_hash(canonical_json(result.model_dump(mode="json", exclude={"table_result_hash"})))


def build_legacy_sql_import_dry_run_result_hash(result: LegacySqlImportDryRunResult) -> str:
    return stable_hash(canonical_json(result.model_dump(mode="json", exclude={"result_hash"})))


def build_legacy_sql_import_dry_run_worker_report_hash(report: LegacySqlImportDryRunWorkerReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def legacy_sql_import_dry_run_result_ref(result: LegacySqlImportDryRunResult) -> str:
    return f"{LEGACY_SQL_IMPORT_DRY_RUN_RESULT_REF_PREFIX}:{result.result_hash}"


def build_default_legacy_sql_import_dry_run_result_store(
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LegacySqlImportDryRunResultStore:
    env = os.environ if environ is None else environ
    backend = _result_store_backend(env)
    if backend == LegacySqlImportDryRunResultBackend.JSONL:
        path_value = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_PATH")
        path = (
            Path(path_value)
            if path_value
            else (data_dir or suite_data_dir()) / "legacy_sql_import_dry_run_results.jsonl"
        )
        return JsonlLegacySqlImportDryRunResultStore(path=path)
    if backend == LegacySqlImportDryRunResultBackend.POSTGRES:
        database_dsn = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if database_dsn is None:
            raise ValueError("Postgres legacy SQL import dry-run result store requires a database DSN")
        return PgLegacySqlImportDryRunResultStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported legacy SQL import dry-run result store backend: {backend}")


def _result_store_backend(env: Mapping[str, str]) -> LegacySqlImportDryRunResultBackend:
    backend = env.get("SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_BACKEND", "jsonl").strip().lower()
    if backend in {"jsonl", "json"}:
        return LegacySqlImportDryRunResultBackend.JSONL
    if backend in {"postgres", "pg"}:
        return LegacySqlImportDryRunResultBackend.POSTGRES
    raise ValueError(f"Unsupported legacy SQL import dry-run result store backend: {backend}")


def _execute_table_dry_run(
    *,
    table_plan: CrmErpLegacyImportDryRunTablePlan,
    row_count_observations: Mapping[str, int],
    checksum_manifest_hashes: Mapping[str, str],
) -> LegacySqlImportDryRunTableResult:
    try:
        observed_row_count = row_count_observations[table_plan.source_table_ref]
    except KeyError as exc:
        raise ValueError(f"missing row-count observation for {table_plan.source_table_ref}") from exc
    if observed_row_count < 0:
        raise ValueError("legacy SQL import dry-run row-count observations must not be negative")
    try:
        checksum_manifest_hash = checksum_manifest_hashes[table_plan.source_table_ref]
    except KeyError as exc:
        raise ValueError(f"missing checksum manifest hash for {table_plan.source_table_ref}") from exc
    draft = LegacySqlImportDryRunTableResult(
        tenant_id=table_plan.tenant_id,
        source_system_ref=table_plan.source_system_ref,
        source_table_ref=table_plan.source_table_ref,
        target_object_type=table_plan.target_object_type,
        staging_profile_object_id=table_plan.staging_profile_object_id,
        row_count_strategy=table_plan.row_count_strategy,
        observed_row_count=observed_row_count,
        checksum_strategy=table_plan.checksum_strategy,
        checksum_manifest_hash=checksum_manifest_hash,
        manifest_hash_required=table_plan.manifest_hash_required,
        table_result_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"table_result_hash": build_legacy_sql_import_dry_run_table_result_hash(draft)})


def _blocked_result_from_plan(
    *,
    dry_run_plan: CrmErpLegacyImportDryRunPlan,
    executed_by: str,
    executed_at_utc: datetime,
) -> LegacySqlImportDryRunResult:
    blocking_reasons = dry_run_plan.blocking_reasons or (f"dry_run_plan_status:{dry_run_plan.status.value}",)
    draft = LegacySqlImportDryRunResult(
        tenant_id=dry_run_plan.tenant_id,
        module_id=dry_run_plan.module_id,
        source_system_ref=dry_run_plan.source_system_ref,
        dry_run_plan_hash=dry_run_plan.manifest_hash,
        discovery_manifest_hash=dry_run_plan.discovery_manifest_hash,
        mapping_manifest_hash=dry_run_plan.mapping_manifest_hash,
        readiness_evidence_hash=dry_run_plan.readiness_evidence_hash,
        staging_metadata_plan_hash=dry_run_plan.staging_metadata_plan_hash,
        status=LegacySqlImportDryRunResultStatus.BLOCKED_BY_PLAN,
        table_result_count=0,
        expected_table_count=dry_run_plan.planned_table_count,
        table_results=(),
        blocking_reasons=tuple(sorted(set(blocking_reasons))),
        row_count_strategy=dry_run_plan.row_count_strategy,
        checksum_strategy=dry_run_plan.checksum_strategy,
        audit_event_types=("legacy_sql.import_dry_run.blocked",),
        dry_run_execution_attempted=False,
        dry_run_execution_completed=False,
        executed_by=executed_by,
        executed_at_utc=executed_at_utc,
        result_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"result_hash": build_legacy_sql_import_dry_run_result_hash(draft)})


def _ready_fixture_dry_run_plan(
    *,
    discovery_manifest: Any,
    import_evidence_plan: LegacySqlImportEvidencePlan,
    captured_at_utc: datetime,
) -> CrmErpLegacyImportDryRunPlan:
    mapping_service = CrmErpLegacyMappingEvidenceService()
    mapping = mapping_service.build_mapping_manifest(
        discovery_manifest=discovery_manifest,
        import_evidence_plan=import_evidence_plan,
        overrides=(
            CrmErpLegacyMappingOverride(
                source_table_ref="dbo.FreieTabelle",
                action=CrmErpLegacyMappingAction.MAP_TO_TARGET,
                target_object_type="crm.contact",
                mapping_reason="metadata-only dry-run worker fixture maps free-form table after manual approval",
                approval_reference="approval:legacy-sql-import-dry-run-worker-override",
            ),
        ),
    )
    readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=discovery_manifest,
        import_evidence_plan=import_evidence_plan,
        mapping_manifest=mapping,
    )
    staging_plan = build_crm_erp_legacy_staging_metadata_plan(
        discovery_manifest=discovery_manifest,
        mapping_manifest=mapping,
        captured_at_utc=captured_at_utc,
    )
    return build_crm_erp_legacy_import_dry_run_plan(
        discovery_manifest=discovery_manifest,
        mapping_manifest=mapping,
        readiness_evidence=readiness,
        staging_metadata_plan=staging_plan,
    )


def _fixture_checksum_manifest_hashes(dry_run_plan: CrmErpLegacyImportDryRunPlan) -> dict[str, str]:
    counts = {"dbo.Kunden": 12, "dbo.FreieTabelle": 3}
    return {
        table_plan.source_table_ref: stable_hash(
            canonical_json(
                {
                    "dry_run_plan_hash": dry_run_plan.manifest_hash,
                    "observed_row_count": counts[table_plan.source_table_ref],
                    "source_system_ref": dry_run_plan.source_system_ref,
                    "source_table_ref": table_plan.source_table_ref,
                }
            )
        )
        for table_plan in dry_run_plan.table_plans
    }


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


def _recommended_actions(*, worker_passed: bool) -> tuple[str, ...]:
    if worker_passed:
        return (
            "persist legacy SQL import dry-run result hash with CRM/ERP restore evidence",
            "require human approval before any import write path is implemented",
            "keep real legacy SQL import writes disabled until dry-run result review is accepted",
        )
    return ("repair metadata-only legacy SQL import dry-run worker before enabling real dry-run execution",)


def _require_valid_result_hash(result: LegacySqlImportDryRunResult) -> None:
    if build_legacy_sql_import_dry_run_result_hash(result) != result.result_hash:
        raise ValueError("legacy SQL import dry-run result hash is invalid")


def _assert_result_evidence_safe(result: LegacySqlImportDryRunResult) -> None:
    payload = result.model_dump_json().lower()
    for fragment in FORBIDDEN_RESULT_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL import dry-run result leaked forbidden fragment: {fragment}")


def _assert_worker_report_has_no_raw_or_table_metadata(report: LegacySqlImportDryRunWorkerReport) -> None:
    payload = report.model_dump_json()
    for fragment in FORBIDDEN_WORKER_REPORT_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL import dry-run worker report leaked forbidden fragment: {fragment}")


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
