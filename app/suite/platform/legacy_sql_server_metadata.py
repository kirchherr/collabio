from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import (
    LegacySqlColumnMetadata,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryManifest,
    LegacySqlDiscoveryRequest,
    LegacySqlDiscoveryService,
    LegacySqlForeignKeyMetadata,
    LegacySqlImportEvidencePlan,
    LegacySqlIndexMetadata,
    LegacySqlRelationKind,
    LegacySqlSchemaSnapshot,
    LegacySqlTableMetadata,
)
from suite.platform.modules import NAMESPACED_REF_PATTERN

DEFAULT_CONNECTOR_POLICY_PATH = Path("docs") / "legacy_sql_connector_policy.json"
QUERY_SOURCE_PATTERN = re.compile(r"\b(?:from|join)\s+([a-z0-9_.\[\]]+)", re.IGNORECASE)


class LegacySqlConnectorPolicyError(ValueError):
    pass


class LegacySqlServerMetadataWorkerError(ValueError):
    pass


class LegacySqlServerNetworkMode(StrEnum):
    NONE = "none"
    APPROVED_LEGACY_HOST_ONLY = "approved_legacy_host_only"


class LegacySqlMetadataQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    statement: str
    includes_row_count_estimates: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not re.fullmatch(r"^[a-z][a-z0-9_]*$", value):
            raise ValueError("metadata query name must be lowercase snake_case")
        return value

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        if not re.match(r"^\s*select\b", value, flags=re.IGNORECASE):
            raise ValueError("metadata query must be a SELECT statement")
        if ";" in value:
            raise ValueError("metadata query must contain exactly one statement")
        return value


class LegacySqlServerConnectorPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "legacy_sql_server_connector_policy.v1"
    owner: str
    connector_kind: LegacySqlConnectorKind = LegacySqlConnectorKind.SQLSERVER
    required_worker_network_mode: LegacySqlServerNetworkMode = LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
    isolated_worker_required: bool = True
    unrestricted_network_forbidden: bool = True
    secret_reference_required: bool = True
    parameterized_queries_required: bool = True
    raw_row_reads_allowed: bool = False
    sample_values_allowed: bool = False
    stored_procedure_body_reads_allowed: bool = False
    row_count_estimates_allowed: bool = True
    allowed_query_names: tuple[str, ...] = Field(min_length=1)
    required_query_names: tuple[str, ...] = Field(min_length=1)
    allowed_metadata_sources: tuple[str, ...] = Field(min_length=1)
    forbidden_statement_fragments: tuple[str, ...] = Field(min_length=1)
    forbidden_result_field_fragments: tuple[str, ...] = Field(min_length=1)
    required_audit_events: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_secure_connector_policy(self) -> Self:
        if self.connector_kind not in {LegacySqlConnectorKind.SQLSERVER, LegacySqlConnectorKind.POSTGRES}:
            raise ValueError("legacy SQL metadata connector policy must use connector_kind=sqlserver or postgres")
        if self.required_worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
            raise ValueError("SQL Server metadata worker must only egress to approved legacy hosts")
        if not self.isolated_worker_required:
            raise ValueError("SQL Server metadata connector requires an isolated worker")
        if not self.unrestricted_network_forbidden:
            raise ValueError("SQL Server metadata connector must forbid unrestricted network")
        if not self.secret_reference_required:
            raise ValueError("SQL Server metadata connector must require secret references")
        if not self.parameterized_queries_required:
            raise ValueError("SQL Server metadata connector must require parameterized queries")
        if self.raw_row_reads_allowed or self.sample_values_allowed or self.stored_procedure_body_reads_allowed:
            raise ValueError("SQL Server metadata connector must not allow raw data or procedure body reads")

        allowed_query_names = set(self.allowed_query_names)
        missing_query_names = sorted(set(self.required_query_names) - allowed_query_names)
        if missing_query_names:
            raise ValueError(f"required query names are not allowed: {', '.join(missing_query_names)}")

        required_audit_events = {
            "legacy_sql.metadata_discovery.started",
            "legacy_sql.metadata_discovery.completed",
            "legacy_sql.metadata_discovery.failed",
        }
        missing_audit_events = sorted(required_audit_events - set(self.required_audit_events))
        if missing_audit_events:
            raise ValueError(f"connector policy is missing audit events: {', '.join(missing_audit_events)}")

        required_forbidden_fragments = {
            "select *",
            "insert ",
            "update ",
            "delete ",
            "merge ",
            "drop ",
            "alter ",
            "create ",
            "exec ",
            "execute ",
            "openrowset",
            "xp_",
        }
        missing_fragments = sorted(required_forbidden_fragments - set(self.forbidden_statement_fragments))
        if missing_fragments:
            raise ValueError(f"connector policy is missing forbidden fragments: {', '.join(missing_fragments)}")

        required_forbidden_fields = {"sample", "preview", "row_values", "record_values", "cell", "payload", "secret"}
        missing_fields = sorted(required_forbidden_fields - set(self.forbidden_result_field_fragments))
        if missing_fields:
            raise ValueError(f"connector policy is missing forbidden result fields: {', '.join(missing_fields)}")
        return self

    def assert_query_allowed(self, query: LegacySqlMetadataQuery) -> None:
        if query.name not in self.allowed_query_names:
            raise LegacySqlConnectorPolicyError(f"metadata query is not allowed by connector policy: {query.name}")
        if query.includes_row_count_estimates and not self.row_count_estimates_allowed:
            raise LegacySqlConnectorPolicyError("row count estimates are disabled by connector policy")

        normalized_statement = _normalize_sql(query.statement)
        for fragment in self.forbidden_statement_fragments:
            if fragment in normalized_statement:
                raise LegacySqlConnectorPolicyError(f"metadata query contains forbidden fragment: {fragment.strip()}")

        sources = _metadata_sources(query.statement)
        if not sources:
            raise LegacySqlConnectorPolicyError(f"metadata query has no metadata source: {query.name}")
        disallowed_sources = sorted(set(sources) - set(self.allowed_metadata_sources))
        if disallowed_sources:
            raise LegacySqlConnectorPolicyError(
                f"metadata query uses disallowed sources: {', '.join(disallowed_sources)}"
            )

    def assert_result_fields_allowed(self, query_name: str, rows: Sequence[Mapping[str, Any]]) -> None:
        if query_name not in self.allowed_query_names:
            raise LegacySqlConnectorPolicyError(f"metadata query result is not allowed: {query_name}")
        for row in rows:
            for field_name in row:
                normalized_field = str(field_name).lower()
                for fragment in self.forbidden_result_field_fragments:
                    if fragment in normalized_field:
                        raise LegacySqlConnectorPolicyError(
                            f"metadata result field is forbidden by connector policy: {field_name}"
                        )


class LegacySqlServerMetadataDiscoveryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: LegacySqlDiscoveryRequest
    connection_secret_ref: str
    connection_fingerprint_hash: str
    connector_policy_ref: str
    policy_snapshot_hash: str

    @field_validator(
        "connection_secret_ref",
        "connection_fingerprint_hash",
        "connector_policy_ref",
        "policy_snapshot_hash",
    )
    @classmethod
    def validate_namespaced_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL worker references must be namespaced")
        return value

    @model_validator(mode="after")
    def require_sqlserver_discovery(self) -> Self:
        if self.request.connector_kind != LegacySqlConnectorKind.SQLSERVER:
            raise ValueError("SQL Server metadata worker only accepts sqlserver discovery requests")
        return self


class LegacySqlServerMetadataDiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: LegacySqlDiscoveryManifest
    import_evidence_plan: LegacySqlImportEvidencePlan
    executed_query_names: tuple[str, ...]
    connector_policy_ref: str
    policy_snapshot_hash: str
    worker_network_mode: LegacySqlServerNetworkMode
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class LegacySqlMetadataQueryExecutor(Protocol):
    def fetch_all(
        self,
        *,
        connection_secret_ref: str,
        query: LegacySqlMetadataQuery,
    ) -> Sequence[Mapping[str, Any]]: ...


class LegacySqlMetadataWorkerAuditSink(Protocol):
    def record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, Any],
    ) -> str: ...


class LegacySqlServerMetadataWorker:
    def __init__(
        self,
        *,
        policy: LegacySqlServerConnectorPolicy,
        executor: LegacySqlMetadataQueryExecutor,
        discovery_service: LegacySqlDiscoveryService | None = None,
        audit_sink: LegacySqlMetadataWorkerAuditSink | None = None,
    ) -> None:
        self.policy = policy
        self.executor = executor
        self.discovery_service = discovery_service or LegacySqlDiscoveryService()
        self.audit_sink = audit_sink

    def discover(self, command: LegacySqlServerMetadataDiscoveryCommand) -> LegacySqlServerMetadataDiscoveryResult:
        self._validate_command(command)
        query_plan = build_sql_server_metadata_query_plan(include_row_counts=command.request.include_row_counts)
        self._record_worker_event(
            tenant_id=command.request.tenant_id,
            event_type="legacy_sql.metadata_discovery.started",
            source_system_ref=command.request.source_system_ref,
            metadata={
                "connector_kind": command.request.connector_kind.value,
                "connector_policy_ref": command.connector_policy_ref,
                "policy_snapshot_hash": command.policy_snapshot_hash,
                "planned_query_names": [query.name for query in query_plan],
            },
        )

        try:
            rows_by_query = self._execute_query_plan(command=command, query_plan=query_plan)
            snapshot = self._build_snapshot(
                connection_fingerprint_hash=command.connection_fingerprint_hash,
                rows_by_query=rows_by_query,
            )
            manifest = self.discovery_service.build_discovery_manifest(request=command.request, snapshot=snapshot)
            import_evidence_plan = self.discovery_service.build_import_evidence_plan(manifest=manifest)
        except Exception as exc:
            self._record_worker_event(
                tenant_id=command.request.tenant_id,
                event_type="legacy_sql.metadata_discovery.failed",
                source_system_ref=command.request.source_system_ref,
                metadata={
                    "connector_kind": command.request.connector_kind.value,
                    "connector_policy_ref": command.connector_policy_ref,
                    "policy_snapshot_hash": command.policy_snapshot_hash,
                    "error_type": type(exc).__name__,
                },
            )
            raise

        result = LegacySqlServerMetadataDiscoveryResult(
            manifest=manifest,
            import_evidence_plan=import_evidence_plan,
            executed_query_names=tuple(query.name for query in query_plan),
            connector_policy_ref=command.connector_policy_ref,
            policy_snapshot_hash=command.policy_snapshot_hash,
            worker_network_mode=self.policy.required_worker_network_mode,
            warnings=(),
        )
        self._record_worker_event(
            tenant_id=command.request.tenant_id,
            event_type="legacy_sql.metadata_discovery.completed",
            source_system_ref=command.request.source_system_ref,
            metadata={
                "connector_kind": command.request.connector_kind.value,
                "connector_policy_ref": command.connector_policy_ref,
                "policy_snapshot_hash": command.policy_snapshot_hash,
                "executed_query_names": list(result.executed_query_names),
                "table_count": manifest.table_count,
                "column_count": manifest.column_count,
                "estimated_row_count_present": manifest.estimated_row_count is not None,
                "snapshot_hash": manifest.snapshot_hash,
                "manifest_hash": manifest.manifest_hash,
                "import_evidence_plan_hash": import_evidence_plan.manifest_hash,
                "quarantine_table_count": len(import_evidence_plan.quarantine_table_refs),
            },
        )
        return result

    def _validate_command(self, command: LegacySqlServerMetadataDiscoveryCommand) -> None:
        expected_policy_hash = build_legacy_sql_connector_policy_hash(self.policy)
        if command.policy_snapshot_hash != expected_policy_hash:
            raise LegacySqlServerMetadataWorkerError("policy_snapshot_hash does not match connector policy")
        if command.request.include_row_counts and not self.policy.row_count_estimates_allowed:
            raise LegacySqlServerMetadataWorkerError("row count estimates are disabled by connector policy")

    def _execute_query_plan(
        self,
        *,
        command: LegacySqlServerMetadataDiscoveryCommand,
        query_plan: tuple[LegacySqlMetadataQuery, ...],
    ) -> dict[str, Sequence[Mapping[str, Any]]]:
        rows_by_query: dict[str, Sequence[Mapping[str, Any]]] = {}
        for query in query_plan:
            self.policy.assert_query_allowed(query)
            rows = self.executor.fetch_all(connection_secret_ref=command.connection_secret_ref, query=query)
            self.policy.assert_result_fields_allowed(query.name, rows)
            rows_by_query[query.name] = rows
        return rows_by_query

    def _build_snapshot(
        self,
        *,
        connection_fingerprint_hash: str,
        rows_by_query: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> LegacySqlSchemaSnapshot:
        table_kinds = _table_kinds(rows_by_query["tables"])
        columns_by_table = _columns_by_table(rows_by_query["columns"])
        primary_keys_by_table = _primary_keys_by_table(rows_by_query.get("primary_keys", ()))
        foreign_keys_by_table = _foreign_keys_by_table(rows_by_query.get("foreign_keys", ()))
        indexes_by_table = _indexes_by_table(rows_by_query.get("indexes", ()))
        row_counts_by_table = _row_counts_by_table(rows_by_query.get("row_counts", ()))

        tables: list[LegacySqlTableMetadata] = []
        for table_ref, relation_kind in sorted(table_kinds.items()):
            columns = columns_by_table.get(table_ref, ())
            if not columns:
                raise LegacySqlServerMetadataWorkerError(f"metadata query returned table without columns: {table_ref}")
            schema_name, table_name = table_ref.split(".", 1)
            tables.append(
                LegacySqlTableMetadata(
                    schema_name=schema_name,
                    table_name=table_name,
                    relation_kind=relation_kind,
                    row_count_estimate=row_counts_by_table.get(table_ref),
                    columns=columns,
                    primary_key_columns=primary_keys_by_table.get(table_ref, ()),
                    foreign_keys=foreign_keys_by_table.get(table_ref, ()),
                    indexes=indexes_by_table.get(table_ref, ()),
                )
            )
        return LegacySqlSchemaSnapshot(connection_fingerprint_hash=connection_fingerprint_hash, tables=tuple(tables))

    def _record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, Any],
    ) -> str | None:
        if self.audit_sink is None:
            return None
        _assert_safe_legacy_sql_worker_audit_metadata(metadata)
        return self.audit_sink.record_worker_event(
            tenant_id=tenant_id,
            event_type=event_type,
            source_system_ref=source_system_ref,
            metadata=metadata,
        )


def build_sql_server_metadata_query_plan(*, include_row_counts: bool = True) -> tuple[LegacySqlMetadataQuery, ...]:
    queries = [
        LegacySqlMetadataQuery(
            name="tables",
            statement="""
SELECT
  t.TABLE_SCHEMA AS schema_name,
  t.TABLE_NAME AS table_name,
  CASE WHEN t.TABLE_TYPE = 'VIEW' THEN 'view' ELSE 'table' END AS relation_kind
FROM INFORMATION_SCHEMA.TABLES t
WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
""".strip(),
        ),
        LegacySqlMetadataQuery(
            name="columns",
            statement="""
SELECT
  c.TABLE_SCHEMA AS schema_name,
  c.TABLE_NAME AS table_name,
  c.COLUMN_NAME AS column_name,
  c.ORDINAL_POSITION AS ordinal_position,
  c.DATA_TYPE AS data_type,
  c.IS_NULLABLE AS is_nullable,
  c.CHARACTER_MAXIMUM_LENGTH AS max_length,
  c.NUMERIC_PRECISION AS numeric_precision,
  c.NUMERIC_SCALE AS numeric_scale,
  CAST(
    COLUMNPROPERTY(OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)), c.COLUMN_NAME, 'IsIdentity')
    AS bit
  ) AS is_identity,
  CASE WHEN c.COLUMN_DEFAULT IS NULL THEN CAST(0 AS bit) ELSE CAST(1 AS bit) END AS default_present
FROM INFORMATION_SCHEMA.COLUMNS c
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
""".strip(),
        ),
        LegacySqlMetadataQuery(
            name="primary_keys",
            statement="""
SELECT
  tc.TABLE_SCHEMA AS schema_name,
  tc.TABLE_NAME AS table_name,
  kcu.COLUMN_NAME AS column_name,
  kcu.ORDINAL_POSITION AS ordinal_position
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON tc.CONSTRAINT_CATALOG = kcu.CONSTRAINT_CATALOG
  AND tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
  AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, kcu.ORDINAL_POSITION
""".strip(),
        ),
        LegacySqlMetadataQuery(
            name="foreign_keys",
            statement="""
SELECT
  sch.name AS schema_name,
  parent_table.name AS table_name,
  fk.name AS foreign_key_name,
  parent_column.name AS column_name,
  referenced_schema.name AS referenced_schema,
  referenced_table.name AS referenced_table,
  referenced_column.name AS referenced_column,
  fkc.constraint_column_id AS ordinal_position
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc
  ON fk.object_id = fkc.constraint_object_id
JOIN sys.tables parent_table
  ON fk.parent_object_id = parent_table.object_id
JOIN sys.schemas sch
  ON parent_table.schema_id = sch.schema_id
JOIN sys.columns parent_column
  ON fkc.parent_object_id = parent_column.object_id
  AND fkc.parent_column_id = parent_column.column_id
JOIN sys.tables referenced_table
  ON fk.referenced_object_id = referenced_table.object_id
JOIN sys.schemas referenced_schema
  ON referenced_table.schema_id = referenced_schema.schema_id
JOIN sys.columns referenced_column
  ON fkc.referenced_object_id = referenced_column.object_id
  AND fkc.referenced_column_id = referenced_column.column_id
ORDER BY sch.name, parent_table.name, fk.name, fkc.constraint_column_id
""".strip(),
        ),
        LegacySqlMetadataQuery(
            name="indexes",
            statement="""
SELECT
  sch.name AS schema_name,
  table_object.name AS table_name,
  index_object.name AS index_name,
  column_object.name AS column_name,
  index_column.key_ordinal AS ordinal_position,
  index_object.is_unique AS is_unique
FROM sys.indexes index_object
JOIN sys.tables table_object
  ON index_object.object_id = table_object.object_id
JOIN sys.schemas sch
  ON table_object.schema_id = sch.schema_id
JOIN sys.index_columns index_column
  ON index_object.object_id = index_column.object_id
  AND index_object.index_id = index_column.index_id
JOIN sys.columns column_object
  ON index_column.object_id = column_object.object_id
  AND index_column.column_id = column_object.column_id
WHERE index_object.name IS NOT NULL
  AND index_object.type <> 0
  AND index_object.is_hypothetical = 0
  AND index_object.is_primary_key = 0
  AND index_column.key_ordinal > 0
ORDER BY sch.name, table_object.name, index_object.name, index_column.key_ordinal
""".strip(),
        ),
    ]
    if include_row_counts:
        queries.append(
            LegacySqlMetadataQuery(
                name="row_counts",
                includes_row_count_estimates=True,
                statement="""
SELECT
  sch.name AS schema_name,
  table_object.name AS table_name,
  SUM(partition_stats.row_count) AS row_count_estimate
FROM sys.dm_db_partition_stats partition_stats
JOIN sys.tables table_object
  ON partition_stats.object_id = table_object.object_id
JOIN sys.schemas sch
  ON table_object.schema_id = sch.schema_id
WHERE partition_stats.index_id IN (0, 1)
GROUP BY sch.name, table_object.name
ORDER BY sch.name, table_object.name
""".strip(),
            )
        )
    return tuple(queries)


def load_legacy_sql_connector_policy(path: Path) -> LegacySqlServerConnectorPolicy:
    return LegacySqlServerConnectorPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_legacy_sql_connector_policy_hash(policy: LegacySqlServerConnectorPolicy) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json")))


def legacy_sql_connector_policy_summary(policy: LegacySqlServerConnectorPolicy) -> dict[str, object]:
    return {
        "schema_version": policy.schema_version,
        "owner": policy.owner,
        "connector_kind": policy.connector_kind.value,
        "allowed_query_count": len(policy.allowed_query_names),
        "isolated_worker_required": policy.isolated_worker_required,
        "required_worker_network_mode": policy.required_worker_network_mode.value,
        "raw_row_reads_allowed": policy.raw_row_reads_allowed,
        "row_count_estimates_allowed": policy.row_count_estimates_allowed,
        "policy_hash": build_legacy_sql_connector_policy_hash(policy),
    }


def _normalize_sql(statement: str) -> str:
    return re.sub(r"\s+", " ", statement.lower()).strip()


def _metadata_sources(statement: str) -> tuple[str, ...]:
    sources: list[str] = []
    for match in QUERY_SOURCE_PATTERN.finditer(statement):
        source = match.group(1).replace("[", "").replace("]", "").lower()
        sources.append(source)
    return tuple(sources)


def _table_ref(row: Mapping[str, Any]) -> str:
    return f"{_text(row, 'schema_name')}.{_text(row, 'table_name')}"


def _table_kinds(rows: Sequence[Mapping[str, Any]]) -> dict[str, LegacySqlRelationKind]:
    table_kinds: dict[str, LegacySqlRelationKind] = {}
    for row in rows:
        relation_kind = _text(row, "relation_kind", default="table").lower()
        table_kinds[_table_ref(row)] = (
            LegacySqlRelationKind.VIEW if relation_kind == "view" else LegacySqlRelationKind.TABLE
        )
    return table_kinds


def _columns_by_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[LegacySqlColumnMetadata, ...]]:
    columns_by_table: dict[str, list[LegacySqlColumnMetadata]] = {}
    for row in rows:
        table_ref = _table_ref(row)
        columns_by_table.setdefault(table_ref, []).append(
            LegacySqlColumnMetadata(
                name=_text(row, "column_name"),
                ordinal_position=_int(row, "ordinal_position"),
                data_type=_text(row, "data_type"),
                nullable=_bool(row, "is_nullable"),
                max_length=_optional_int(row, "max_length"),
                numeric_precision=_optional_int(row, "numeric_precision"),
                numeric_scale=_optional_int(row, "numeric_scale"),
                is_identity=_bool(row, "is_identity", default=False),
                default_present=_bool(row, "default_present", default=False),
            )
        )
    return {
        table_ref: tuple(sorted(columns, key=lambda column: column.ordinal_position))
        for table_ref, columns in columns_by_table.items()
    }


def _primary_keys_by_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    primary_keys_by_table: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        primary_keys_by_table.setdefault(_table_ref(row), []).append(
            (_int(row, "ordinal_position"), _text(row, "column_name"))
        )
    return {
        table_ref: tuple(column_name for _, column_name in sorted(columns))
        for table_ref, columns in primary_keys_by_table.items()
    }


def _foreign_keys_by_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[LegacySqlForeignKeyMetadata, ...]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((_table_ref(row), _text(row, "foreign_key_name")), []).append(row)

    foreign_keys_by_table: dict[str, list[LegacySqlForeignKeyMetadata]] = {}
    for (table_ref, foreign_key_name), foreign_key_rows in grouped.items():
        ordered_rows = sorted(foreign_key_rows, key=lambda row: _int(row, "ordinal_position"))
        first_row = ordered_rows[0]
        foreign_keys_by_table.setdefault(table_ref, []).append(
            LegacySqlForeignKeyMetadata(
                name=foreign_key_name,
                columns=tuple(_text(row, "column_name") for row in ordered_rows),
                referenced_schema=_text(first_row, "referenced_schema"),
                referenced_table=_text(first_row, "referenced_table"),
                referenced_columns=tuple(_text(row, "referenced_column") for row in ordered_rows),
            )
        )
    return {table_ref: tuple(foreign_keys) for table_ref, foreign_keys in foreign_keys_by_table.items()}


def _indexes_by_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, tuple[LegacySqlIndexMetadata, ...]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((_table_ref(row), _text(row, "index_name")), []).append(row)

    indexes_by_table: dict[str, list[LegacySqlIndexMetadata]] = {}
    for (table_ref, index_name), index_rows in grouped.items():
        ordered_rows = sorted(index_rows, key=lambda row: _int(row, "ordinal_position"))
        indexes_by_table.setdefault(table_ref, []).append(
            LegacySqlIndexMetadata(
                name=index_name,
                columns=tuple(_text(row, "column_name") for row in ordered_rows),
                unique=_bool(ordered_rows[0], "is_unique", default=False),
            )
        )
    return {table_ref: tuple(indexes) for table_ref, indexes in indexes_by_table.items()}


def _row_counts_by_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {_table_ref(row): _int(row, "row_count_estimate") for row in rows}


def _text(row: Mapping[str, Any], key: str, *, default: str | None = None) -> str:
    value = row.get(key, default)
    if value is None:
        raise LegacySqlServerMetadataWorkerError(f"metadata row is missing required field: {key}")
    text = str(value).strip()
    if not text:
        raise LegacySqlServerMetadataWorkerError(f"metadata row field must not be empty: {key}")
    return text


def _int(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if value is None:
        raise LegacySqlServerMetadataWorkerError(f"metadata row is missing required integer field: {key}")
    return int(value)


def _optional_int(row: Mapping[str, Any], key: str) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed >= 0 else None


def _bool(row: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = row.get(key, default)
    if value is None:
        raise LegacySqlServerMetadataWorkerError(f"metadata row is missing required boolean field: {key}")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    raise LegacySqlServerMetadataWorkerError(f"metadata row boolean field is invalid: {key}")


def _assert_safe_legacy_sql_worker_audit_metadata(metadata: Mapping[str, Any]) -> None:
    unsafe_key = _find_unsafe_legacy_sql_worker_audit_metadata_key(metadata)
    if unsafe_key is not None:
        raise LegacySqlServerMetadataWorkerError(f"legacy SQL worker audit metadata has raw field: {unsafe_key}")


def _find_unsafe_legacy_sql_worker_audit_metadata_key(value: Any, *, path: str = "") -> str | None:
    forbidden_fragments = ("sample", "preview", "row_values", "record_values", "cell", "payload", "secret", "dsn")
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            key_text = str(key)
            normalized_key = key_text.lower()
            key_path = f"{path}.{key_text}" if path else key_text
            if any(fragment in normalized_key for fragment in forbidden_fragments):
                return key_path
            nested_unsafe_key = _find_unsafe_legacy_sql_worker_audit_metadata_key(nested_value, path=key_path)
            if nested_unsafe_key is not None:
                return nested_unsafe_key
    if isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            nested_unsafe_key = _find_unsafe_legacy_sql_worker_audit_metadata_key(nested_value, path=f"{path}[{index}]")
            if nested_unsafe_key is not None:
                return nested_unsafe_key
    return None


def main() -> None:
    policy = load_legacy_sql_connector_policy(DEFAULT_CONNECTOR_POLICY_PATH)
    print(json.dumps(legacy_sql_connector_policy_summary(policy), sort_keys=True))


if __name__ == "__main__":
    main()
