from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash

MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_@$#.-]*$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class LegacySqlDiscoveryError(ValueError):
    pass


class LegacySqlConnectorKind(StrEnum):
    SQLSERVER = "sqlserver"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    ORACLE = "oracle"
    SQLITE = "sqlite"
    UNKNOWN = "unknown"


class LegacySqlRelationKind(StrEnum):
    TABLE = "table"
    VIEW = "view"


class LegacySqlConstraintKind(StrEnum):
    CHECK = "check"
    UNIQUE = "unique"
    DEFAULT = "default"
    OTHER = "other"


class LegacySqlCandidateConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class LegacySqlDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    include_row_counts: bool = True

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "approval_reference", "audit_chain_ref")
    @classmethod
    def validate_namespaced_ref(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("reference must be namespaced")
        return value


class LegacySqlColumnMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ordinal_position: int = Field(ge=1)
    data_type: str
    nullable: bool
    max_length: int | None = Field(default=None, ge=0)
    numeric_precision: int | None = Field(default=None, ge=0)
    numeric_scale: int | None = Field(default=None, ge=0)
    is_identity: bool = False
    default_present: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("column name must be metadata identifier only")
        return value

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("data_type must not be empty")
        if any(marker in value.lower() for marker in ("select ", "insert ", "update ", "delete ", " from ")):
            raise ValueError("data_type must not contain SQL statements")
        return value


class LegacySqlForeignKeyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    columns: tuple[str, ...]
    referenced_schema: str
    referenced_table: str
    referenced_columns: tuple[str, ...]

    @field_validator("name", "referenced_schema", "referenced_table")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("foreign key metadata must use identifiers only")
        return value

    @field_validator("columns", "referenced_columns")
    @classmethod
    def validate_column_list(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("foreign key columns must not be empty")
        for column in value:
            if not IDENTIFIER_PATTERN.fullmatch(column):
                raise ValueError("foreign key columns must be identifiers only")
        return value


class LegacySqlIndexMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    columns: tuple[str, ...]
    unique: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("index name must be metadata identifier only")
        return value

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("index columns must not be empty")
        for column in value:
            if not IDENTIFIER_PATTERN.fullmatch(column):
                raise ValueError("index columns must be identifiers only")
        return value


class LegacySqlConstraintMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: LegacySqlConstraintKind
    columns: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("constraint name must be metadata identifier only")
        return value

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for column in value:
            if not IDENTIFIER_PATTERN.fullmatch(column):
                raise ValueError("constraint columns must be identifiers only")
        return value


class LegacySqlTableMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    table_name: str
    relation_kind: LegacySqlRelationKind = LegacySqlRelationKind.TABLE
    row_count_estimate: int | None = Field(default=None, ge=0)
    columns: tuple[LegacySqlColumnMetadata, ...]
    primary_key_columns: tuple[str, ...] = Field(default_factory=tuple)
    foreign_keys: tuple[LegacySqlForeignKeyMetadata, ...] = Field(default_factory=tuple)
    indexes: tuple[LegacySqlIndexMetadata, ...] = Field(default_factory=tuple)
    constraints: tuple[LegacySqlConstraintMetadata, ...] = Field(default_factory=tuple)

    @field_validator("schema_name", "table_name")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("table metadata must use identifiers only")
        return value

    @field_validator("columns")
    @classmethod
    def require_columns(cls, value: tuple[LegacySqlColumnMetadata, ...]) -> tuple[LegacySqlColumnMetadata, ...]:
        if not value:
            raise ValueError("table metadata requires at least one column")
        ordinals = [column.ordinal_position for column in value]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("column ordinal positions must be unique")
        names = [column.name.lower() for column in value]
        if len(set(names)) != len(names):
            raise ValueError("column names must be unique per table")
        return value

    @field_validator("primary_key_columns")
    @classmethod
    def validate_primary_key_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for column in value:
            if not IDENTIFIER_PATTERN.fullmatch(column):
                raise ValueError("primary key columns must be identifiers only")
        return value

    @model_validator(mode="after")
    def require_referenced_columns_exist(self) -> LegacySqlTableMetadata:
        column_names = {column.name for column in self.columns}
        missing_primary_key_columns = set(self.primary_key_columns) - column_names
        if missing_primary_key_columns:
            raise ValueError("primary key columns must exist in table columns")
        for foreign_key in self.foreign_keys:
            if set(foreign_key.columns) - column_names:
                raise ValueError("foreign key columns must exist in table columns")
        for index in self.indexes:
            if set(index.columns) - column_names:
                raise ValueError("index columns must exist in table columns")
        for constraint in self.constraints:
            if set(constraint.columns) - column_names:
                raise ValueError("constraint columns must exist in table columns")
        return self

    @property
    def table_ref(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


class LegacySqlSchemaSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_fingerprint_hash: str
    inspected_at_utc: datetime = Field(default_factory=utc_now)
    tables: tuple[LegacySqlTableMetadata, ...]

    @field_validator("connection_fingerprint_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("connection_fingerprint_hash must be namespaced")
        return value

    @field_validator("tables")
    @classmethod
    def require_unique_tables(cls, value: tuple[LegacySqlTableMetadata, ...]) -> tuple[LegacySqlTableMetadata, ...]:
        if not value:
            raise ValueError("schema snapshot requires at least one table")
        refs = [table.table_ref.lower() for table in value]
        if len(set(refs)) != len(refs):
            raise ValueError("table refs must be unique")
        return value


class LegacySqlObjectCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_table_ref: str
    candidate_object_type: str
    confidence: LegacySqlCandidateConfidence
    reasons: tuple[str, ...]


class LegacySqlDiscoveryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    inspected_at_utc: datetime
    table_count: int = Field(ge=1)
    column_count: int = Field(ge=1)
    estimated_row_count: int | None = Field(default=None, ge=0)
    snapshot_hash: str
    object_candidates: tuple[LegacySqlObjectCandidate, ...]
    manifest_hash: str
    schema_version: str = "legacy_sql_discovery.v1"


class LegacySqlImportEvidencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    discovery_manifest_hash: str
    candidate_count: int = Field(ge=0)
    quarantine_table_refs: tuple[str, ...]
    approval_required: bool = True
    dry_run_required: bool = True
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    manifest_hash: str
    schema_version: str = "legacy_sql_import_evidence_plan.v1"


TARGET_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("crm.account", ("account", "accounts", "customer", "customers", "kunde", "kunden", "firma"), "account table name"),
    ("crm.contact", ("contact", "contacts", "kontakt", "kontakte", "person", "personen"), "contact table name"),
    ("crm.activity", ("activity", "activities", "task", "tasks", "aktivitaet", "aktivitaeten"), "activity table name"),
    ("erp.product", ("product", "products", "artikel", "item", "items", "produkt"), "product table name"),
    ("erp.supplier", ("supplier", "suppliers", "lieferant", "lieferanten", "vendor"), "supplier table name"),
    ("erp.order", ("order", "orders", "auftrag", "auftraege", "bestellung"), "order table name"),
    ("erp.invoice", ("invoice", "invoices", "rechnung", "rechnungen"), "invoice table name"),
)


def _hash_model(model: BaseModel, *, exclude_manifest_hash: bool = False) -> str:
    if exclude_manifest_hash:
        payload = model.model_dump(mode="json", exclude={"manifest_hash"})
    else:
        payload = model.model_dump(mode="json")
    return stable_hash(canonical_json(payload))


def _candidate_for_table(table: LegacySqlTableMetadata) -> LegacySqlObjectCandidate:
    searchable_name = f"{table.schema_name}.{table.table_name}".lower()
    column_names = {column.name.lower() for column in table.columns}
    reasons: list[str] = []

    for candidate_object_type, patterns, reason in TARGET_PATTERNS:
        if any(pattern in searchable_name for pattern in patterns):
            reasons.append(reason)
            if candidate_object_type == "crm.contact" and {"email", "mail", "emailaddress"} & column_names:
                reasons.append("contact-like email column present")
                return LegacySqlObjectCandidate(
                    source_table_ref=table.table_ref,
                    candidate_object_type=candidate_object_type,
                    confidence=LegacySqlCandidateConfidence.HIGH,
                    reasons=tuple(reasons),
                )
            confidence = (
                LegacySqlCandidateConfidence.MEDIUM if table.primary_key_columns else LegacySqlCandidateConfidence.LOW
            )
            return LegacySqlObjectCandidate(
                source_table_ref=table.table_ref,
                candidate_object_type=candidate_object_type,
                confidence=confidence,
                reasons=tuple(reasons),
            )

    return LegacySqlObjectCandidate(
        source_table_ref=table.table_ref,
        candidate_object_type="legacy.row",
        confidence=LegacySqlCandidateConfidence.UNKNOWN,
        reasons=("no safe target object inference from metadata",),
    )


def _assert_no_raw_payload(value: Any, *, path: str = "") -> None:
    forbidden_fragments = ("sample", "preview", "row_values", "rows", "record_values", "data_values")
    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in forbidden_fragments):
                raise LegacySqlDiscoveryError(f"raw legacy SQL payload is forbidden at {path or key_text}")
            _assert_no_raw_payload(nested_value, path=f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            _assert_no_raw_payload(nested_value, path=f"{path}[{index}]")


class LegacySqlDiscoveryService:
    def build_discovery_manifest(
        self,
        *,
        request: LegacySqlDiscoveryRequest,
        snapshot: LegacySqlSchemaSnapshot,
    ) -> LegacySqlDiscoveryManifest:
        _assert_no_raw_payload(snapshot.model_dump(mode="json"))
        object_candidates = tuple(_candidate_for_table(table) for table in snapshot.tables)
        estimated_row_count = (
            sum(table.row_count_estimate for table in snapshot.tables if table.row_count_estimate is not None)
            if request.include_row_counts
            else None
        )
        snapshot_payload = snapshot.model_copy(
            update={
                "tables": tuple(
                    table.model_copy(
                        update={
                            "row_count_estimate": table.row_count_estimate if request.include_row_counts else None,
                        }
                    )
                    for table in snapshot.tables
                )
            }
        )
        snapshot_hash = _hash_model(snapshot_payload)
        draft = LegacySqlDiscoveryManifest(
            tenant_id=request.tenant_id,
            module_id=request.module_id,
            source_system_ref=request.source_system_ref,
            connector_kind=request.connector_kind,
            requested_by=request.requested_by,
            approval_reference=request.approval_reference,
            audit_chain_ref=request.audit_chain_ref,
            inspected_at_utc=snapshot.inspected_at_utc,
            table_count=len(snapshot.tables),
            column_count=sum(len(table.columns) for table in snapshot.tables),
            estimated_row_count=estimated_row_count,
            snapshot_hash=snapshot_hash,
            object_candidates=object_candidates,
            manifest_hash="sha256:pending",
        )
        return draft.model_copy(update={"manifest_hash": _hash_model(draft, exclude_manifest_hash=True)})

    def build_import_evidence_plan(
        self,
        *,
        manifest: LegacySqlDiscoveryManifest,
    ) -> LegacySqlImportEvidencePlan:
        quarantine_table_refs = tuple(
            sorted(
                candidate.source_table_ref
                for candidate in manifest.object_candidates
                if candidate.candidate_object_type == "legacy.row"
                or candidate.confidence in {LegacySqlCandidateConfidence.LOW, LegacySqlCandidateConfidence.UNKNOWN}
            )
        )
        draft = LegacySqlImportEvidencePlan(
            tenant_id=manifest.tenant_id,
            module_id=manifest.module_id,
            source_system_ref=manifest.source_system_ref,
            discovery_manifest_hash=manifest.manifest_hash,
            candidate_count=len(manifest.object_candidates),
            quarantine_table_refs=quarantine_table_refs,
            manifest_hash="sha256:pending",
        )
        return draft.model_copy(update={"manifest_hash": _hash_model(draft, exclude_manifest_hash=True)})
