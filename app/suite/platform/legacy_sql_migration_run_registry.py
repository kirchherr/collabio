from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.crm_erp_legacy_mapping import CRM_ERP_MODULE_ID
from suite.platform.legacy_sql_discovery import NAMESPACED_REF_PATTERN
from suite.platform.legacy_sql_import_write_approval_gate import (
    LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN,
    SHA256_REF_PATTERN,
    ZERO_HASH,
)
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_MIGRATION_RUN_REGISTRY_ENTRY_SCHEMA_VERSION = "legacy_sql_migration_run_registry_entry.v1"
LEGACY_SQL_MIGRATION_REPORT_METADATA_SCHEMA_VERSION = "legacy_sql_migration_report_metadata.v1"
LEGACY_SQL_MIGRATION_RUN_REGISTRY_COMMAND_REF = "store:legacy-sql-migration-run-registry"
LEGACY_SQL_MIGRATION_REPORT_METADATA_COMMAND_REF = "store:legacy-sql-migration-report-metadata"
LEGACY_SQL_MIGRATION_RUN_REGISTRY_IDEMPOTENCY_SCHEMA_VERSION = "legacy_sql_migration_run_registry_idempotency_key.v1"
LEGACY_SQL_MIGRATION_REPORT_METADATA_IDEMPOTENCY_SCHEMA_VERSION = (
    "legacy_sql_migration_report_metadata_idempotency_key.v1"
)
FORBIDDEN_MIGRATION_REGISTRY_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:",
    "sqlserver://",
    "password",
    "dsn",
    "plain_secret",
    "connection_string",
    '"raw_payload":',
    '"sample_values":',
    '"import_write_payload":',
    "dbo.kunden",
    "dbo.freietabelle",
    "kundenid",
    "email",
)


class LegacySqlMigrationRunRegistryStoreBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlMigrationRunStatus(StrEnum):
    PLANNED_METADATA_ONLY = "planned_metadata_only"
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_GRANTED = "approval_granted"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class LegacySqlMigrationReportStatus(StrEnum):
    PLANNED_METADATA_ONLY = "planned_metadata_only"
    READY_FOR_REVIEW = "ready_for_review"
    BLOCKED = "blocked"


class LegacySqlMigrationRunRegistryEntryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system_ref: str
    migration_run_ref: str
    approval_record_hash: str
    approval_gate_evidence_hash: str
    dry_run_result_hash: str
    idempotency_key_ref: str
    restore_evidence_hash: str
    audit_event_id: str
    audit_chain_ref: str
    requested_by: str
    run_status: LegacySqlMigrationRunStatus = LegacySqlMigrationRunStatus.PLANNED_METADATA_ONLY
    run_registry_entry_requested: bool = True
    run_creation_requested: bool = False
    run_execution_requested: bool = False
    import_write_execution_requested: bool = False
    raw_data_access_requested: bool = False
    import_write_payload_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("audit_event_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration run registry command text fields must not be empty")
        return value

    @field_validator("source_system_ref", "migration_run_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration run registry command references must be namespaced")
        return value

    @field_validator(
        "approval_record_hash",
        "approval_gate_evidence_hash",
        "dry_run_result_hash",
        "restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration run registry command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_request(self) -> Self:
        if not self.run_registry_entry_requested:
            raise ValueError("legacy SQL migration run registry entry must be explicitly requested")
        if (
            self.run_creation_requested
            or self.run_execution_requested
            or self.import_write_execution_requested
            or self.raw_data_access_requested
            or self.import_write_payload_requested
            or self.destructive_actions_requested
            or self.external_side_effect_requested
        ):
            raise ValueError("legacy SQL migration run registry command must not request execution or side effects")
        _assert_migration_registry_safe(self)
        return self


class LegacySqlMigrationReportMetadataCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system_ref: str
    migration_run_hash: str
    migration_report_ref: str
    idempotency_key_ref: str
    report_status: LegacySqlMigrationReportStatus = LegacySqlMigrationReportStatus.PLANNED_METADATA_ONLY
    planned_table_count: int = Field(default=0, ge=0)
    table_result_count: int = Field(default=0, ge=0)
    row_count_manifest_hash: str
    checksum_manifest_hash: str
    restore_evidence_hash: str
    audit_event_id: str
    audit_chain_ref: str
    report_metadata_requested: bool = True
    report_retrieval_requested: bool = False
    run_execution_completed_requested: bool = False
    import_write_execution_requested: bool = False
    raw_data_access_requested: bool = False
    import_write_payload_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("audit_event_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration report command text fields must not be empty")
        return value

    @field_validator("source_system_ref", "migration_report_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration report command references must be namespaced")
        return value

    @field_validator(
        "migration_run_hash",
        "row_count_manifest_hash",
        "checksum_manifest_hash",
        "restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration report command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_request(self) -> Self:
        if not self.report_metadata_requested:
            raise ValueError("legacy SQL migration report metadata must be explicitly requested")
        if (
            self.report_retrieval_requested
            or self.run_execution_completed_requested
            or self.import_write_execution_requested
            or self.raw_data_access_requested
            or self.import_write_payload_requested
            or self.destructive_actions_requested
            or self.external_side_effect_requested
        ):
            raise ValueError("legacy SQL migration report command must not request execution or side effects")
        _assert_migration_registry_safe(self)
        return self


class LegacySqlMigrationRunRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_MIGRATION_RUN_REGISTRY_ENTRY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_MIGRATION_RUN_REGISTRY_COMMAND_REF
    migration_run_ref: str
    approval_record_hash: str
    approval_gate_evidence_hash: str
    dry_run_result_hash: str
    idempotency_key_hash: str
    requested_by: str
    requested_at_utc: datetime
    run_status: LegacySqlMigrationRunStatus = LegacySqlMigrationRunStatus.PLANNED_METADATA_ONLY
    future_import_write_execution_gate_required: bool = True
    run_creation_enabled: bool = False
    run_execution_allowed: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    metadata_only_report_required: bool = True
    restore_evidence_hash: str
    audit_event_id: str
    audit_chain_ref: str
    evidence_hash: str

    @field_validator("tenant_id", "requested_by", "audit_event_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration run registry entry text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL migration run registry entry only applies to module crm_erp")
        return value

    @field_validator("source_system_ref", "migration_run_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration run registry entry references must be namespaced")
        return value

    @field_validator(
        "approval_record_hash",
        "approval_gate_evidence_hash",
        "dry_run_result_hash",
        "idempotency_key_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration run registry entry hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_entry(self) -> Self:
        if self.schema_version != LEGACY_SQL_MIGRATION_RUN_REGISTRY_ENTRY_SCHEMA_VERSION:
            raise ValueError("legacy SQL migration run registry entry schema version is invalid")
        if (
            not self.future_import_write_execution_gate_required
            or self.run_creation_enabled
            or self.run_execution_allowed
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
            or not self.metadata_only_report_required
        ):
            raise ValueError("legacy SQL migration run registry entry must remain metadata-only and non-executing")
        _assert_migration_registry_safe(self)
        return self


class LegacySqlMigrationReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_MIGRATION_REPORT_METADATA_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_MIGRATION_REPORT_METADATA_COMMAND_REF
    migration_run_hash: str
    migration_report_ref: str
    idempotency_key_hash: str
    report_status: LegacySqlMigrationReportStatus = LegacySqlMigrationReportStatus.PLANNED_METADATA_ONLY
    planned_table_count: int = Field(default=0, ge=0)
    table_result_count: int = Field(default=0, ge=0)
    row_count_manifest_hash: str
    checksum_manifest_hash: str
    restore_evidence_hash: str
    audit_event_id: str
    audit_chain_ref: str
    metadata_only_ok: bool = True
    future_import_write_execution_gate_required: bool = True
    report_retrieval_enabled: bool = False
    run_execution_completed: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    evidence_hash: str

    @field_validator("tenant_id", "audit_event_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration report metadata text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL migration report metadata only applies to module crm_erp")
        return value

    @field_validator("source_system_ref", "migration_report_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration report metadata references must be namespaced")
        return value

    @field_validator(
        "migration_run_hash",
        "idempotency_key_hash",
        "row_count_manifest_hash",
        "checksum_manifest_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration report metadata hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_report(self) -> Self:
        if self.schema_version != LEGACY_SQL_MIGRATION_REPORT_METADATA_SCHEMA_VERSION:
            raise ValueError("legacy SQL migration report metadata schema version is invalid")
        if (
            not self.metadata_only_ok
            or not self.future_import_write_execution_gate_required
            or self.report_retrieval_enabled
            or self.run_execution_completed
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL migration report metadata must remain metadata-only and non-executing")
        _assert_migration_registry_safe(self)
        return self


class LegacySqlMigrationRunRegistryStore(Protocol):
    def append_run(self, entry: LegacySqlMigrationRunRegistryEntry) -> LegacySqlMigrationRunRegistryEntry:
        raise NotImplementedError

    def append_report(self, report: LegacySqlMigrationReportMetadata) -> LegacySqlMigrationReportMetadata:
        raise NotImplementedError

    def get_run(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationRunRegistryEntry:
        raise NotImplementedError

    def get_run_by_ref(self, *, tenant_id: str, migration_run_ref: str) -> LegacySqlMigrationRunRegistryEntry:
        raise NotImplementedError

    def get_run_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationRunRegistryEntry:
        raise NotImplementedError

    def list_runs(self, *, tenant_id: str) -> tuple[LegacySqlMigrationRunRegistryEntry, ...]:
        raise NotImplementedError

    def get_report(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationReportMetadata:
        raise NotImplementedError

    def get_report_by_ref(self, *, tenant_id: str, migration_report_ref: str) -> LegacySqlMigrationReportMetadata:
        raise NotImplementedError

    def get_report_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationReportMetadata:
        raise NotImplementedError

    def list_reports(self, *, tenant_id: str) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        raise NotImplementedError

    def list_reports_for_run(
        self,
        *,
        tenant_id: str,
        migration_run_hash: str,
    ) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        raise NotImplementedError


class InMemoryLegacySqlMigrationRunRegistryStore:
    def __init__(
        self,
        runs: Sequence[LegacySqlMigrationRunRegistryEntry] = (),
        reports: Sequence[LegacySqlMigrationReportMetadata] = (),
    ) -> None:
        self._runs: dict[tuple[str, str], LegacySqlMigrationRunRegistryEntry] = {}
        self._runs_by_ref: dict[tuple[str, str], LegacySqlMigrationRunRegistryEntry] = {}
        self._runs_by_idempotency: dict[tuple[str, str], LegacySqlMigrationRunRegistryEntry] = {}
        self._reports: dict[tuple[str, str], LegacySqlMigrationReportMetadata] = {}
        self._reports_by_ref: dict[tuple[str, str], LegacySqlMigrationReportMetadata] = {}
        self._reports_by_idempotency: dict[tuple[str, str], LegacySqlMigrationReportMetadata] = {}
        for entry in runs:
            self._append_run_to_indexes(entry)
        for report in reports:
            self._append_report_to_indexes(report)

    def append_run(self, entry: LegacySqlMigrationRunRegistryEntry) -> LegacySqlMigrationRunRegistryEntry:
        return self._append_run_to_indexes(entry)

    def append_report(self, report: LegacySqlMigrationReportMetadata) -> LegacySqlMigrationReportMetadata:
        return self._append_report_to_indexes(report)

    def get_run(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationRunRegistryEntry:
        try:
            return self._runs[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration run registry entry not found") from exc

    def get_run_by_ref(self, *, tenant_id: str, migration_run_ref: str) -> LegacySqlMigrationRunRegistryEntry:
        try:
            return self._runs_by_ref[(tenant_id, migration_run_ref)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration run registry entry not found") from exc

    def get_run_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationRunRegistryEntry:
        try:
            return self._runs_by_idempotency[(tenant_id, idempotency_key_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration run registry entry not found") from exc

    def list_runs(self, *, tenant_id: str) -> tuple[LegacySqlMigrationRunRegistryEntry, ...]:
        return tuple(entry for (stored_tenant_id, _), entry in self._runs.items() if stored_tenant_id == tenant_id)

    def get_report(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationReportMetadata:
        try:
            return self._reports[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration report metadata not found") from exc

    def get_report_by_ref(self, *, tenant_id: str, migration_report_ref: str) -> LegacySqlMigrationReportMetadata:
        try:
            return self._reports_by_ref[(tenant_id, migration_report_ref)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration report metadata not found") from exc

    def get_report_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationReportMetadata:
        try:
            return self._reports_by_idempotency[(tenant_id, idempotency_key_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL migration report metadata not found") from exc

    def list_reports(self, *, tenant_id: str) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        return tuple(report for (stored_tenant_id, _), report in self._reports.items() if stored_tenant_id == tenant_id)

    def list_reports_for_run(
        self,
        *,
        tenant_id: str,
        migration_run_hash: str,
    ) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        return tuple(
            report
            for (stored_tenant_id, _), report in self._reports.items()
            if stored_tenant_id == tenant_id and report.migration_run_hash == migration_run_hash
        )

    def _append_run_to_indexes(
        self,
        entry: LegacySqlMigrationRunRegistryEntry,
    ) -> LegacySqlMigrationRunRegistryEntry:
        _require_valid_run_registry_entry_hash(entry)
        key = (entry.tenant_id, entry.evidence_hash)
        existing_by_hash = self._runs.get(key)
        if existing_by_hash is not None:
            if existing_by_hash == entry:
                return existing_by_hash
            raise ValueError("legacy SQL migration run registry evidence hash already exists")
        ref_key = (entry.tenant_id, entry.migration_run_ref)
        existing_by_ref = self._runs_by_ref.get(ref_key)
        if existing_by_ref is not None:
            if existing_by_ref == entry:
                return existing_by_ref
            raise ValueError("legacy SQL migration run registry ref already exists")
        idempotency_key = (entry.tenant_id, entry.idempotency_key_hash)
        existing_by_idempotency = self._runs_by_idempotency.get(idempotency_key)
        if existing_by_idempotency is not None:
            if existing_by_idempotency == entry:
                return existing_by_idempotency
            raise ValueError("legacy SQL migration run registry idempotency key already used")
        self._runs[key] = entry
        self._runs_by_ref[ref_key] = entry
        self._runs_by_idempotency[idempotency_key] = entry
        return entry

    def _append_report_to_indexes(self, report: LegacySqlMigrationReportMetadata) -> LegacySqlMigrationReportMetadata:
        _require_valid_migration_report_metadata_hash(report)
        key = (report.tenant_id, report.evidence_hash)
        existing_by_hash = self._reports.get(key)
        if existing_by_hash is not None:
            if existing_by_hash == report:
                return existing_by_hash
            raise ValueError("legacy SQL migration report metadata evidence hash already exists")
        ref_key = (report.tenant_id, report.migration_report_ref)
        existing_by_ref = self._reports_by_ref.get(ref_key)
        if existing_by_ref is not None:
            if existing_by_ref == report:
                return existing_by_ref
            raise ValueError("legacy SQL migration report metadata ref already exists")
        idempotency_key = (report.tenant_id, report.idempotency_key_hash)
        existing_by_idempotency = self._reports_by_idempotency.get(idempotency_key)
        if existing_by_idempotency is not None:
            if existing_by_idempotency == report:
                return existing_by_idempotency
            raise ValueError("legacy SQL migration report metadata idempotency key already used")
        self._reports[key] = report
        self._reports_by_ref[ref_key] = report
        self._reports_by_idempotency[idempotency_key] = report
        return report


class JsonlLegacySqlMigrationRunRegistryStore(InMemoryLegacySqlMigrationRunRegistryStore):
    def __init__(self, *, run_path: Path, report_path: Path) -> None:
        self.run_path = run_path
        self.report_path = report_path
        runs = self._load_runs(run_path)
        reports = self._load_reports(report_path)
        super().__init__(runs=runs, reports=reports)

    def append_run(self, entry: LegacySqlMigrationRunRegistryEntry) -> LegacySqlMigrationRunRegistryEntry:
        existing = self._existing_run_for_append(entry)
        if existing is not None:
            return existing
        appended = super().append_run(entry)
        self.run_path.parent.mkdir(parents=True, exist_ok=True)
        with self.run_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(appended.model_dump(mode="json"), sort_keys=True) + "\n")
        return appended

    def append_report(self, report: LegacySqlMigrationReportMetadata) -> LegacySqlMigrationReportMetadata:
        existing = self._existing_report_for_append(report)
        if existing is not None:
            return existing
        appended = super().append_report(report)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        with self.report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(appended.model_dump(mode="json"), sort_keys=True) + "\n")
        return appended

    def _existing_run_for_append(
        self,
        entry: LegacySqlMigrationRunRegistryEntry,
    ) -> LegacySqlMigrationRunRegistryEntry | None:
        try:
            existing = self.get_run_by_idempotency_key_hash(
                tenant_id=entry.tenant_id,
                idempotency_key_hash=entry.idempotency_key_hash,
            )
        except KeyError:
            return None
        if existing == entry:
            return existing
        raise ValueError("legacy SQL migration run registry idempotency key already used")

    def _existing_report_for_append(
        self,
        report: LegacySqlMigrationReportMetadata,
    ) -> LegacySqlMigrationReportMetadata | None:
        try:
            existing = self.get_report_by_idempotency_key_hash(
                tenant_id=report.tenant_id,
                idempotency_key_hash=report.idempotency_key_hash,
            )
        except KeyError:
            return None
        if existing == report:
            return existing
        raise ValueError("legacy SQL migration report metadata idempotency key already used")

    def _load_runs(self, path: Path) -> tuple[LegacySqlMigrationRunRegistryEntry, ...]:
        if not path.exists():
            return ()
        return tuple(
            LegacySqlMigrationRunRegistryEntry.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def _load_reports(self, path: Path) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        if not path.exists():
            return ()
        return tuple(
            LegacySqlMigrationReportMetadata.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )


class PgLegacySqlMigrationRunRegistryStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append_run(self, entry: LegacySqlMigrationRunRegistryEntry) -> LegacySqlMigrationRunRegistryEntry:
        _require_valid_run_registry_entry_hash(entry)
        try:
            existing = self.get_run_by_idempotency_key_hash(
                tenant_id=entry.tenant_id,
                idempotency_key_hash=entry.idempotency_key_hash,
            )
        except KeyError:
            existing = None
        if existing is not None:
            if existing == entry:
                return existing
            raise ValueError("legacy SQL migration run registry idempotency key already used")
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, entry.tenant_id)
                connection.execute(
                    """
                    INSERT INTO crm_erp_legacy.migration_runs (
                        tenant_id,
                        module_id,
                        source_system_ref,
                        migration_run_ref,
                        approval_record_hash,
                        approval_gate_evidence_hash,
                        dry_run_result_hash,
                        idempotency_key_hash,
                        requested_by,
                        requested_at_utc,
                        run_status,
                        future_import_write_execution_gate_required,
                        run_creation_enabled,
                        run_execution_allowed,
                        import_write_execution_allowed,
                        raw_data_access_allowed,
                        import_write_payload_allowed,
                        destructive_actions_allowed,
                        external_side_effect_allowed,
                        metadata_only_report_required,
                        restore_evidence_hash,
                        audit_event_id,
                        audit_chain_ref,
                        migration_run,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._run_values(entry),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("legacy SQL migration run registry entry already exists") from exc
        return entry

    def append_report(self, report: LegacySqlMigrationReportMetadata) -> LegacySqlMigrationReportMetadata:
        _require_valid_migration_report_metadata_hash(report)
        try:
            existing = self.get_report_by_idempotency_key_hash(
                tenant_id=report.tenant_id,
                idempotency_key_hash=report.idempotency_key_hash,
            )
        except KeyError:
            existing = None
        if existing is not None:
            if existing == report:
                return existing
            raise ValueError("legacy SQL migration report metadata idempotency key already used")
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, report.tenant_id)
                connection.execute(
                    """
                    INSERT INTO crm_erp_legacy.migration_reports (
                        tenant_id,
                        module_id,
                        source_system_ref,
                        migration_run_hash,
                        migration_report_ref,
                        idempotency_key_hash,
                        report_status,
                        planned_table_count,
                        table_result_count,
                        row_count_manifest_hash,
                        checksum_manifest_hash,
                        restore_evidence_hash,
                        audit_event_id,
                        audit_chain_ref,
                        metadata_only_ok,
                        future_import_write_execution_gate_required,
                        report_retrieval_enabled,
                        run_execution_completed,
                        import_write_execution_allowed,
                        raw_data_access_allowed,
                        import_write_payload_allowed,
                        destructive_actions_allowed,
                        external_side_effect_allowed,
                        migration_report,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._report_values(report),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("legacy SQL migration report metadata already exists") from exc
        return report

    def get_run(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationRunRegistryEntry:
        return self._fetch_run(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND evidence_hash = %s",
            params=(tenant_id, evidence_hash),
        )

    def get_run_by_ref(self, *, tenant_id: str, migration_run_ref: str) -> LegacySqlMigrationRunRegistryEntry:
        return self._fetch_run(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND migration_run_ref = %s",
            params=(tenant_id, migration_run_ref),
        )

    def get_run_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationRunRegistryEntry:
        return self._fetch_run(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND idempotency_key_hash = %s",
            params=(tenant_id, idempotency_key_hash),
        )

    def list_runs(self, *, tenant_id: str) -> tuple[LegacySqlMigrationRunRegistryEntry, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT migration_run
                FROM crm_erp_legacy.migration_runs
                WHERE tenant_id = %s
                ORDER BY requested_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def get_report(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlMigrationReportMetadata:
        return self._fetch_report(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND evidence_hash = %s",
            params=(tenant_id, evidence_hash),
        )

    def get_report_by_ref(self, *, tenant_id: str, migration_report_ref: str) -> LegacySqlMigrationReportMetadata:
        return self._fetch_report(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND migration_report_ref = %s",
            params=(tenant_id, migration_report_ref),
        )

    def get_report_by_idempotency_key_hash(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> LegacySqlMigrationReportMetadata:
        return self._fetch_report(
            tenant_id=tenant_id,
            where_sql="tenant_id = %s AND idempotency_key_hash = %s",
            params=(tenant_id, idempotency_key_hash),
        )

    def list_reports(self, *, tenant_id: str) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT migration_report
                FROM crm_erp_legacy.migration_reports
                WHERE tenant_id = %s
                ORDER BY created_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._report_from_row(row) for row in rows)

    def list_reports_for_run(
        self,
        *,
        tenant_id: str,
        migration_run_hash: str,
    ) -> tuple[LegacySqlMigrationReportMetadata, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT migration_report
                FROM crm_erp_legacy.migration_reports
                WHERE tenant_id = %s
                  AND migration_run_hash = %s
                ORDER BY created_at_utc, evidence_hash
                """,
                (tenant_id, migration_run_hash),
            ).fetchall()
        return tuple(self._report_from_row(row) for row in rows)

    def _fetch_run(
        self,
        *,
        tenant_id: str,
        where_sql: str,
        params: tuple[str, str],
    ) -> LegacySqlMigrationRunRegistryEntry:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT migration_run
                FROM crm_erp_legacy.migration_runs
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL migration run registry entry not found")
        return self._run_from_row(row)

    def _fetch_report(
        self,
        *,
        tenant_id: str,
        where_sql: str,
        params: tuple[str, str],
    ) -> LegacySqlMigrationReportMetadata:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT migration_report
                FROM crm_erp_legacy.migration_reports
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL migration report metadata not found")
        return self._report_from_row(row)

    def _run_values(self, entry: LegacySqlMigrationRunRegistryEntry) -> tuple[object, ...]:
        return (
            entry.tenant_id,
            entry.module_id,
            entry.source_system_ref,
            entry.migration_run_ref,
            entry.approval_record_hash,
            entry.approval_gate_evidence_hash,
            entry.dry_run_result_hash,
            entry.idempotency_key_hash,
            entry.requested_by,
            entry.requested_at_utc,
            entry.run_status.value,
            entry.future_import_write_execution_gate_required,
            entry.run_creation_enabled,
            entry.run_execution_allowed,
            entry.import_write_execution_allowed,
            entry.raw_data_access_allowed,
            entry.import_write_payload_allowed,
            entry.destructive_actions_allowed,
            entry.external_side_effect_allowed,
            entry.metadata_only_report_required,
            entry.restore_evidence_hash,
            entry.audit_event_id,
            entry.audit_chain_ref,
            Jsonb(entry.model_dump(mode="json")),
            entry.evidence_hash,
            entry.schema_version,
        )

    def _report_values(self, report: LegacySqlMigrationReportMetadata) -> tuple[object, ...]:
        return (
            report.tenant_id,
            report.module_id,
            report.source_system_ref,
            report.migration_run_hash,
            report.migration_report_ref,
            report.idempotency_key_hash,
            report.report_status.value,
            report.planned_table_count,
            report.table_result_count,
            report.row_count_manifest_hash,
            report.checksum_manifest_hash,
            report.restore_evidence_hash,
            report.audit_event_id,
            report.audit_chain_ref,
            report.metadata_only_ok,
            report.future_import_write_execution_gate_required,
            report.report_retrieval_enabled,
            report.run_execution_completed,
            report.import_write_execution_allowed,
            report.raw_data_access_allowed,
            report.import_write_payload_allowed,
            report.destructive_actions_allowed,
            report.external_side_effect_allowed,
            Jsonb(report.model_dump(mode="json")),
            report.evidence_hash,
            report.schema_version,
        )

    def _run_from_row(self, row: tuple[Any, ...]) -> LegacySqlMigrationRunRegistryEntry:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        entry = LegacySqlMigrationRunRegistryEntry.model_validate(parsed)
        _require_valid_run_registry_entry_hash(entry)
        return entry

    def _report_from_row(self, row: tuple[Any, ...]) -> LegacySqlMigrationReportMetadata:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        report = LegacySqlMigrationReportMetadata.model_validate(parsed)
        _require_valid_migration_report_metadata_hash(report)
        return report

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_legacy_sql_migration_run_registry_idempotency_key_hash(
    *,
    command: LegacySqlMigrationRunRegistryEntryCommand,
    tenant_id: str,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "schema_version": LEGACY_SQL_MIGRATION_RUN_REGISTRY_IDEMPOTENCY_SCHEMA_VERSION,
                "tenant_id": tenant_id,
                "source_system_ref": command.source_system_ref,
                "approval_record_hash": command.approval_record_hash,
                "dry_run_result_hash": command.dry_run_result_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )


def build_legacy_sql_migration_report_metadata_idempotency_key_hash(
    *,
    command: LegacySqlMigrationReportMetadataCommand,
    tenant_id: str,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "schema_version": LEGACY_SQL_MIGRATION_REPORT_METADATA_IDEMPOTENCY_SCHEMA_VERSION,
                "tenant_id": tenant_id,
                "source_system_ref": command.source_system_ref,
                "migration_run_hash": command.migration_run_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )


def build_legacy_sql_migration_run_registry_entry_hash(entry: LegacySqlMigrationRunRegistryEntry) -> str:
    return stable_hash(canonical_json(entry.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_migration_report_metadata_hash(report: LegacySqlMigrationReportMetadata) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_migration_run_registry_entry(
    *,
    command: LegacySqlMigrationRunRegistryEntryCommand,
    tenant_id: str,
    requested_at_utc: datetime | None = None,
) -> LegacySqlMigrationRunRegistryEntry:
    requested_at = requested_at_utc or datetime.now(UTC)
    draft = LegacySqlMigrationRunRegistryEntry(
        tenant_id=tenant_id,
        source_system_ref=command.source_system_ref,
        migration_run_ref=command.migration_run_ref,
        approval_record_hash=command.approval_record_hash,
        approval_gate_evidence_hash=command.approval_gate_evidence_hash,
        dry_run_result_hash=command.dry_run_result_hash,
        idempotency_key_hash=build_legacy_sql_migration_run_registry_idempotency_key_hash(
            command=command,
            tenant_id=tenant_id,
        ),
        requested_by=command.requested_by,
        requested_at_utc=requested_at,
        run_status=command.run_status,
        restore_evidence_hash=command.restore_evidence_hash,
        audit_event_id=command.audit_event_id,
        audit_chain_ref=command.audit_chain_ref,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_migration_run_registry_entry_hash(draft)})


def build_legacy_sql_migration_report_metadata(
    *,
    command: LegacySqlMigrationReportMetadataCommand,
    tenant_id: str,
) -> LegacySqlMigrationReportMetadata:
    draft = LegacySqlMigrationReportMetadata(
        tenant_id=tenant_id,
        source_system_ref=command.source_system_ref,
        migration_run_hash=command.migration_run_hash,
        migration_report_ref=command.migration_report_ref,
        idempotency_key_hash=build_legacy_sql_migration_report_metadata_idempotency_key_hash(
            command=command,
            tenant_id=tenant_id,
        ),
        report_status=command.report_status,
        planned_table_count=command.planned_table_count,
        table_result_count=command.table_result_count,
        row_count_manifest_hash=command.row_count_manifest_hash,
        checksum_manifest_hash=command.checksum_manifest_hash,
        restore_evidence_hash=command.restore_evidence_hash,
        audit_event_id=command.audit_event_id,
        audit_chain_ref=command.audit_chain_ref,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_migration_report_metadata_hash(draft)})


def build_default_legacy_sql_migration_run_registry_store(
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LegacySqlMigrationRunRegistryStore:
    env = os.environ if environ is None else environ
    backend = _registry_store_backend(env)
    if backend == LegacySqlMigrationRunRegistryStoreBackend.JSONL:
        base_dir = data_dir or suite_data_dir()
        run_path_value = env.get("SUITE_LEGACY_SQL_MIGRATION_RUN_REGISTRY_PATH")
        report_path_value = env.get("SUITE_LEGACY_SQL_MIGRATION_REPORT_METADATA_PATH")
        run_path = Path(run_path_value) if run_path_value else base_dir / "legacy_sql_migration_runs.jsonl"
        report_path = Path(report_path_value) if report_path_value else base_dir / "legacy_sql_migration_reports.jsonl"
        return JsonlLegacySqlMigrationRunRegistryStore(run_path=run_path, report_path=report_path)
    if backend == LegacySqlMigrationRunRegistryStoreBackend.POSTGRES:
        database_dsn = env.get("SUITE_LEGACY_SQL_MIGRATION_RUN_REGISTRY_DSN") or env.get("SUITE_DATABASE_DSN")
        if database_dsn is None:
            raise ValueError("Postgres legacy SQL migration run registry store requires a database DSN")
        return PgLegacySqlMigrationRunRegistryStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported legacy SQL migration run registry store backend: {backend}")


def _registry_store_backend(env: Mapping[str, str]) -> LegacySqlMigrationRunRegistryStoreBackend:
    value = env.get("SUITE_LEGACY_SQL_MIGRATION_RUN_REGISTRY_BACKEND", "jsonl").strip().lower()
    if value == "jsonl":
        return LegacySqlMigrationRunRegistryStoreBackend.JSONL
    if value == "postgres":
        return LegacySqlMigrationRunRegistryStoreBackend.POSTGRES
    raise ValueError(f"Unsupported legacy SQL migration run registry store backend: {value}")


def _require_valid_run_registry_entry_hash(entry: LegacySqlMigrationRunRegistryEntry) -> None:
    if entry.evidence_hash != build_legacy_sql_migration_run_registry_entry_hash(entry):
        raise ValueError("legacy SQL migration run registry entry evidence hash is invalid")


def _require_valid_migration_report_metadata_hash(report: LegacySqlMigrationReportMetadata) -> None:
    if report.evidence_hash != build_legacy_sql_migration_report_metadata_hash(report):
        raise ValueError("legacy SQL migration report metadata evidence hash is invalid")


def _assert_migration_registry_safe(value: BaseModel) -> None:
    payload = canonical_json(value.model_dump(mode="json")).lower()
    for fragment in FORBIDDEN_MIGRATION_REGISTRY_FRAGMENTS:
        if fragment.lower() in payload:
            raise ValueError("legacy SQL migration registry metadata must not contain raw data or secrets")
