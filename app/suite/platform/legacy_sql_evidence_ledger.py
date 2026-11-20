from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_EVIDENCE_LEDGER_SCHEMA_VERSION = "legacy_sql_evidence_ledger_entry.v1"
LEGACY_SQL_EVIDENCE_LEDGER_REF_PREFIX = "legacy-sql-evidence"
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_HASH = "sha256:" + "0" * 64
FORBIDDEN_METADATA_FRAGMENTS = (
    "dsn",
    "password",
    "secret",
    "sample",
    "preview",
    "row_values",
    "record_values",
    "cell",
    "payload",
)


class LegacySqlEvidenceType(StrEnum):
    DISCOVERY_INTAKE = "discovery_intake"
    DISCOVERY_INTAKE_OPERATIONS_REPORT = "discovery_intake_operations_report"
    METADATA_DISCOVERY_MANIFEST = "metadata_discovery_manifest"
    IMPORT_EVIDENCE_PLAN = "import_evidence_plan"
    CRM_ERP_MAPPING_MANIFEST = "crm_erp_mapping_manifest"
    IMPORT_READINESS = "import_readiness"
    READINESS_SMOKE_REPORT = "readiness_smoke_report"


class LegacySqlEvidenceLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    evidence_type: LegacySqlEvidenceType
    evidence_ref: str
    evidence_hash: str
    evidence_status: str
    related_evidence_hashes: tuple[str, ...] = Field(default_factory=tuple)
    restore_evidence_hash: str
    captured_by: str
    captured_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_payload_included: bool = False
    real_connection_used: bool = False
    import_dry_run_executed: bool = False
    import_write_executed: bool = False
    destructive_actions_executed: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    ledger_entry_hash: str
    schema_version: str = LEGACY_SQL_EVIDENCE_LEDGER_SCHEMA_VERSION

    @field_validator("tenant_id", "captured_by", "evidence_status")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL evidence ledger text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL evidence ledger module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "evidence_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL evidence ledger references must be namespaced")
        return value

    @field_validator("evidence_hash", "restore_evidence_hash", "ledger_entry_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL evidence ledger hashes must be sha256 references")
        return value

    @field_validator("related_evidence_hashes")
    @classmethod
    def validate_related_evidence_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL related evidence hashes must be unique")
        for evidence_hash in value:
            if not SHA256_REF_PATTERN.fullmatch(evidence_hash):
                raise ValueError("legacy SQL related evidence hashes must be sha256 references")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata_is_safe(cls, value: dict[str, str]) -> dict[str, str]:
        for key, metadata_value in value.items():
            _assert_safe_metadata_text(key)
            _assert_safe_metadata_text(metadata_value)
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def require_metadata_only_ledger_entry(self) -> LegacySqlEvidenceLedgerEntry:
        if self.raw_payload_included or self.import_write_executed or self.destructive_actions_executed:
            raise ValueError("legacy SQL evidence ledger entries must not include raw payloads or write actions")
        return self


class LegacySqlEvidenceLedgerStore(Protocol):
    def append(self, entry: LegacySqlEvidenceLedgerEntry) -> LegacySqlEvidenceLedgerEntry:
        raise NotImplementedError

    def get(self, *, tenant_id: str, ledger_entry_hash: str) -> LegacySqlEvidenceLedgerEntry:
        raise NotImplementedError

    def list_entries(self, *, tenant_id: str) -> Sequence[LegacySqlEvidenceLedgerEntry]:
        raise NotImplementedError


class InMemoryLegacySqlEvidenceLedgerStore:
    def __init__(self, entries: Sequence[LegacySqlEvidenceLedgerEntry] = ()) -> None:
        self._entries: dict[tuple[str, str], LegacySqlEvidenceLedgerEntry] = {}
        for entry in entries:
            self.append(entry)

    def append(self, entry: LegacySqlEvidenceLedgerEntry) -> LegacySqlEvidenceLedgerEntry:
        _require_valid_ledger_entry_hash(entry)
        key = (entry.tenant_id, entry.ledger_entry_hash)
        if key in self._entries:
            raise ValueError("legacy SQL evidence ledger entry already exists")
        self._entries[key] = entry
        return entry

    def get(self, *, tenant_id: str, ledger_entry_hash: str) -> LegacySqlEvidenceLedgerEntry:
        try:
            return self._entries[(tenant_id, ledger_entry_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL evidence ledger entry not found") from exc

    def list_entries(self, *, tenant_id: str) -> Sequence[LegacySqlEvidenceLedgerEntry]:
        return tuple(entry for (stored_tenant_id, _), entry in self._entries.items() if stored_tenant_id == tenant_id)


class JsonlLegacySqlEvidenceLedgerStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._entries: dict[tuple[str, str], LegacySqlEvidenceLedgerEntry] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = LegacySqlEvidenceLedgerEntry.model_validate_json(line)
            _require_valid_ledger_entry_hash(entry)
            key = (entry.tenant_id, entry.ledger_entry_hash)
            if key in self._entries:
                raise ValueError("duplicate legacy SQL evidence ledger entry in store")
            self._entries[key] = entry

    def append(self, entry: LegacySqlEvidenceLedgerEntry) -> LegacySqlEvidenceLedgerEntry:
        _require_valid_ledger_entry_hash(entry)
        key = (entry.tenant_id, entry.ledger_entry_hash)
        if key in self._entries:
            raise ValueError("legacy SQL evidence ledger entry already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
        self._entries[key] = entry
        return entry

    def get(self, *, tenant_id: str, ledger_entry_hash: str) -> LegacySqlEvidenceLedgerEntry:
        try:
            return self._entries[(tenant_id, ledger_entry_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL evidence ledger entry not found") from exc

    def list_entries(self, *, tenant_id: str) -> Sequence[LegacySqlEvidenceLedgerEntry]:
        return tuple(entry for (stored_tenant_id, _), entry in self._entries.items() if stored_tenant_id == tenant_id)


class PgLegacySqlEvidenceLedgerStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, entry: LegacySqlEvidenceLedgerEntry) -> LegacySqlEvidenceLedgerEntry:
        _require_valid_ledger_entry_hash(entry)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, entry.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.legacy_sql_evidence_ledger (
                        tenant_id,
                        module_id,
                        source_system_ref,
                        evidence_type,
                        evidence_ref,
                        evidence_hash,
                        evidence_status,
                        related_evidence_hashes,
                        restore_evidence_hash,
                        captured_by,
                        captured_at_utc,
                        raw_payload_included,
                        real_connection_used,
                        import_dry_run_executed,
                        import_write_executed,
                        destructive_actions_executed,
                        metadata,
                        ledger_entry,
                        ledger_entry_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._entry_values(entry),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("legacy SQL evidence ledger entry already exists") from exc
        return entry

    def get(self, *, tenant_id: str, ledger_entry_hash: str) -> LegacySqlEvidenceLedgerEntry:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT ledger_entry
                FROM collabio.legacy_sql_evidence_ledger
                WHERE tenant_id = %s
                  AND ledger_entry_hash = %s
                """,
                (tenant_id, ledger_entry_hash),
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL evidence ledger entry not found")
        return self._entry_from_row(row)

    def list_entries(self, *, tenant_id: str) -> Sequence[LegacySqlEvidenceLedgerEntry]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT ledger_entry
                FROM collabio.legacy_sql_evidence_ledger
                WHERE tenant_id = %s
                ORDER BY captured_at_utc, ledger_entry_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._entry_from_row(row) for row in rows)

    def _entry_values(self, entry: LegacySqlEvidenceLedgerEntry) -> tuple[object, ...]:
        return (
            entry.tenant_id,
            entry.module_id,
            entry.source_system_ref,
            entry.evidence_type.value,
            entry.evidence_ref,
            entry.evidence_hash,
            entry.evidence_status,
            Jsonb(list(entry.related_evidence_hashes)),
            entry.restore_evidence_hash,
            entry.captured_by,
            entry.captured_at_utc,
            entry.raw_payload_included,
            entry.real_connection_used,
            entry.import_dry_run_executed,
            entry.import_write_executed,
            entry.destructive_actions_executed,
            Jsonb(entry.metadata),
            Jsonb(entry.model_dump(mode="json")),
            entry.ledger_entry_hash,
            entry.schema_version,
        )

    def _entry_from_row(self, row: tuple[Any, ...]) -> LegacySqlEvidenceLedgerEntry:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        entry = LegacySqlEvidenceLedgerEntry.model_validate(parsed)
        _require_valid_ledger_entry_hash(entry)
        return entry

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_legacy_sql_evidence_ledger_entry(
    *,
    tenant_id: str,
    source_system_ref: str,
    evidence_type: LegacySqlEvidenceType,
    evidence_ref: str,
    evidence_hash: str,
    evidence_status: str,
    restore_evidence_hash: str,
    captured_by: str,
    module_id: str = "crm_erp",
    related_evidence_hashes: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    captured_at_utc: datetime | None = None,
) -> LegacySqlEvidenceLedgerEntry:
    draft = LegacySqlEvidenceLedgerEntry(
        tenant_id=tenant_id,
        module_id=module_id,
        source_system_ref=source_system_ref,
        evidence_type=evidence_type,
        evidence_ref=evidence_ref,
        evidence_hash=evidence_hash,
        evidence_status=evidence_status,
        related_evidence_hashes=tuple(related_evidence_hashes),
        restore_evidence_hash=restore_evidence_hash,
        captured_by=captured_by,
        captured_at_utc=captured_at_utc or datetime.now(UTC),
        metadata=dict(metadata or {}),
        ledger_entry_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"ledger_entry_hash": build_legacy_sql_evidence_ledger_entry_hash(draft)})


def build_legacy_sql_evidence_ledger_entry_hash(entry: LegacySqlEvidenceLedgerEntry) -> str:
    return stable_hash(canonical_json(entry.model_dump(mode="json", exclude={"ledger_entry_hash"})))


def legacy_sql_evidence_ledger_ref(entry: LegacySqlEvidenceLedgerEntry) -> str:
    return f"{LEGACY_SQL_EVIDENCE_LEDGER_REF_PREFIX}:{entry.ledger_entry_hash}"


def build_default_legacy_sql_evidence_ledger_store(
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LegacySqlEvidenceLedgerStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_BACKEND", "jsonl").strip().lower()
    if backend in {"memory", "in_memory"}:
        return InMemoryLegacySqlEvidenceLedgerStore()
    if backend == "jsonl":
        path_value = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_PATH")
        path = Path(path_value) if path_value else (data_dir or suite_data_dir()) / "legacy_sql_evidence_ledger.jsonl"
        return JsonlLegacySqlEvidenceLedgerStore(path=path)
    if backend in {"postgres", "pg"}:
        database_dsn = env.get("SUITE_LEGACY_SQL_EVIDENCE_LEDGER_DSN") or env.get("SUITE_DATABASE_DSN")
        if database_dsn is None:
            raise ValueError("Postgres legacy SQL evidence ledger requires a database DSN")
        return PgLegacySqlEvidenceLedgerStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported legacy SQL evidence ledger backend: {backend}")


def _require_valid_ledger_entry_hash(entry: LegacySqlEvidenceLedgerEntry) -> None:
    if build_legacy_sql_evidence_ledger_entry_hash(entry) != entry.ledger_entry_hash:
        raise ValueError("legacy SQL evidence ledger entry hash is invalid")


def _assert_safe_metadata_text(value: str) -> None:
    lowered = value.lower()
    if any(fragment in lowered for fragment in FORBIDDEN_METADATA_FRAGMENTS):
        raise ValueError("legacy SQL evidence ledger metadata must not contain sensitive payload markers")
