from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import stable_hash
from suite.platform.crm_accounts import (
    CrmAccountRecord,
    CrmAccountRepository,
    InMemoryCrmAccountRepository,
)
from suite.platform.crm_activities import (
    CrmActivityRecord,
    CrmActivityRepository,
    CrmNoteRecord,
    CrmNoteRepository,
    InMemoryCrmActivityRepository,
    InMemoryCrmNoteRepository,
)
from suite.platform.crm_contacts import (
    CrmContactRecord,
    CrmContactRepository,
    InMemoryCrmContactRepository,
)

CRM_RUNTIME_BOOTSTRAP_SCHEMA_VERSION = "crm_runtime_bootstrap_report.v1"

_COMMON_COLUMNS = (
    "tenant_id",
    "object_id",
    "object_type",
    "owner_principal_id",
    "created_by",
    "created_at_utc",
    "updated_at_utc",
    "data_classification",
    "retention_policy_id",
    "legal_hold_state",
    "lifecycle_state",
    "kms_key_ref",
    "audit_chain_ref",
    "source_system",
    "schema_version",
)
_ACCOUNT_COLUMNS = (*_COMMON_COLUMNS, "account_number", "display_name", "account_kind", "status")
_CONTACT_COLUMNS = (
    *_COMMON_COLUMNS,
    "account_object_id",
    "contact_number",
    "display_name",
    "given_name",
    "family_name",
    "primary_email",
    "primary_phone",
    "role_label",
    "status",
)
_ACTIVITY_COLUMNS = (
    *_COMMON_COLUMNS,
    "account_object_id",
    "contact_object_id",
    "activity_number",
    "activity_type",
    "subject",
    "due_at_utc",
    "completed_at_utc",
    "status",
)
_NOTE_COLUMNS = (
    *_COMMON_COLUMNS,
    "account_object_id",
    "contact_object_id",
    "activity_object_id",
    "note_number",
    "title",
    "status",
)

RecordT = TypeVar("RecordT", bound=BaseModel)
CrmRecord = CrmAccountRecord | CrmContactRecord | CrmActivityRecord | CrmNoteRecord


@dataclass(frozen=True)
class CrmRepositories:
    account_repository: CrmAccountRepository
    contact_repository: CrmContactRepository
    activity_repository: CrmActivityRepository
    note_repository: CrmNoteRepository


class CrmRuntimeBootstrapReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_RUNTIME_BOOTSTRAP_SCHEMA_VERSION
    backend: str = "postgres"
    tenant_ids: tuple[str, ...]
    attempted_record_count: int
    inserted_record_count: int
    visible_record_count: int
    table_record_counts: dict[str, int]
    content_included: bool = False
    evidence_hash: str

    @field_validator("tenant_ids")
    @classmethod
    def require_tenants(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not tenant_id.strip() for tenant_id in value):
            raise ValueError("CRM runtime bootstrap requires tenant IDs")
        return value

    @model_validator(mode="after")
    def require_metadata_only_consistency(self) -> CrmRuntimeBootstrapReport:
        if self.content_included:
            raise ValueError("CRM runtime bootstrap report must remain metadata-only")
        if self.attempted_record_count < self.inserted_record_count:
            raise ValueError("inserted CRM records cannot exceed attempted records")
        if self.visible_record_count != sum(self.table_record_counts.values()):
            raise ValueError("CRM runtime bootstrap visible count must match table counts")
        if self.evidence_hash != _bootstrap_report_hash(self):
            raise ValueError("CRM runtime bootstrap evidence hash is invalid")
        return self


class PgCrmRepository:
    """Tenant-RLS repository shared by the four CRM foundation object types."""

    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def list_accounts(self, *, tenant_id: str) -> Sequence[CrmAccountRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="crm.accounts",
            columns=_ACCOUNT_COLUMNS,
            order_by="display_name, object_id",
            record_type=CrmAccountRecord,
        )

    def list_contacts(self, *, tenant_id: str) -> Sequence[CrmContactRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="crm.contacts",
            columns=_CONTACT_COLUMNS,
            order_by="display_name, object_id",
            record_type=CrmContactRecord,
        )

    def list_activities(self, *, tenant_id: str) -> Sequence[CrmActivityRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="crm.activities",
            columns=_ACTIVITY_COLUMNS,
            order_by="due_at_utc NULLS LAST, updated_at_utc DESC, object_id",
            record_type=CrmActivityRecord,
        )

    def list_notes(self, *, tenant_id: str) -> Sequence[CrmNoteRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="crm.notes",
            columns=_NOTE_COLUMNS,
            order_by="updated_at_utc DESC, object_id",
            record_type=CrmNoteRecord,
        )

    def seed_demo_records(self) -> CrmRuntimeBootstrapReport:
        records_by_table: tuple[tuple[str, tuple[str, ...], tuple[CrmRecord, ...]], ...] = (
            ("crm.accounts", _ACCOUNT_COLUMNS, _demo_accounts()),
            ("crm.contacts", _CONTACT_COLUMNS, _demo_contacts()),
            ("crm.activities", _ACTIVITY_COLUMNS, _demo_activities()),
            ("crm.notes", _NOTE_COLUMNS, _demo_notes()),
        )
        tenant_ids = tuple(sorted({str(record.tenant_id) for _, _, records in records_by_table for record in records}))
        inserted_record_count = 0
        with psycopg.connect(self.database_dsn) as connection:
            for tenant_id in tenant_ids:
                with connection.transaction():
                    self._set_tenant(connection, tenant_id)
                    for table, columns, records in records_by_table:
                        for record in records:
                            if record.tenant_id == tenant_id:
                                inserted_record_count += self._insert_record(
                                    connection,
                                    table=table,
                                    columns=columns,
                                    record=record,
                                )

        table_record_counts = {
            "crm.accounts": sum(len(self.list_accounts(tenant_id=tenant_id)) for tenant_id in tenant_ids),
            "crm.contacts": sum(len(self.list_contacts(tenant_id=tenant_id)) for tenant_id in tenant_ids),
            "crm.activities": sum(len(self.list_activities(tenant_id=tenant_id)) for tenant_id in tenant_ids),
            "crm.notes": sum(len(self.list_notes(tenant_id=tenant_id)) for tenant_id in tenant_ids),
        }
        attempted_record_count = sum(len(records) for _, _, records in records_by_table)
        draft = CrmRuntimeBootstrapReport.model_construct(
            tenant_ids=tenant_ids,
            attempted_record_count=attempted_record_count,
            inserted_record_count=inserted_record_count,
            visible_record_count=sum(table_record_counts.values()),
            table_record_counts=table_record_counts,
            evidence_hash="sha256:pending",
        )
        return CrmRuntimeBootstrapReport.model_validate(
            {**draft.model_dump(), "evidence_hash": _bootstrap_report_hash(draft)}
        )

    def _list_records(
        self,
        *,
        tenant_id: str,
        table: str,
        columns: tuple[str, ...],
        order_by: str,
        record_type: type[RecordT],
    ) -> tuple[RecordT, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE tenant_id = %s ORDER BY {order_by}",
                (tenant_id,),
            ).fetchall()
        return tuple(record_type.model_validate(_row_values(columns, row)) for row in rows)

    @staticmethod
    def _insert_record(
        connection: psycopg.Connection[Any],
        *,
        table: str,
        columns: tuple[str, ...],
        record: BaseModel,
    ) -> int:
        values = record.model_dump(mode="json")
        cursor = connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('%s' for _ in columns)}) ON CONFLICT DO NOTHING",
            tuple(values[column] for column in columns),
        )
        return cursor.rowcount

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_default_crm_repositories(environ: Mapping[str, str] | None = None) -> CrmRepositories:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_CRM_REPOSITORY_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return CrmRepositories(
            account_repository=InMemoryCrmAccountRepository.demo(),
            contact_repository=InMemoryCrmContactRepository.demo(),
            activity_repository=InMemoryCrmActivityRepository.demo(),
            note_repository=InMemoryCrmNoteRepository.demo(),
        )
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_CRM_REPOSITORY_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError("PostgreSQL CRM repository requires SUITE_CRM_REPOSITORY_DSN or SUITE_DATABASE_DSN")
        repository = PgCrmRepository(database_dsn=database_dsn)
        return CrmRepositories(
            account_repository=repository,
            contact_repository=repository,
            activity_repository=repository,
            note_repository=repository,
        )
    raise ValueError(f"Unsupported SUITE_CRM_REPOSITORY_BACKEND: {backend}")


def bootstrap_default_crm_runtime(environ: Mapping[str, str] | None = None) -> CrmRuntimeBootstrapReport:
    env = os.environ if environ is None else environ
    repositories = build_default_crm_repositories(env)
    repository = repositories.account_repository
    if not isinstance(repository, PgCrmRepository):
        raise ValueError("CRM runtime bootstrap requires the PostgreSQL repository backend")
    if env.get("SUITE_CRM_RUNTIME_SEED_DEMO", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        raise ValueError("CRM runtime bootstrap demo seed must be explicitly enabled")
    return repository.seed_demo_records()


def _row_values(columns: tuple[str, ...], row: Sequence[Any]) -> dict[str, Any]:
    return {column: _json_value(value) for column, value in zip(columns, row, strict=True)}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC).isoformat()
        return normalized.replace("+00:00", "Z")
    return value


def _demo_accounts() -> tuple[CrmAccountRecord, ...]:
    return tuple(
        record
        for tenant_id in ("tenant-demo", "tenant-other")
        for record in InMemoryCrmAccountRepository.demo().list_accounts(tenant_id=tenant_id)
    )


def _demo_contacts() -> tuple[CrmContactRecord, ...]:
    return tuple(
        record
        for tenant_id in ("tenant-demo", "tenant-other")
        for record in InMemoryCrmContactRepository.demo().list_contacts(tenant_id=tenant_id)
    )


def _demo_activities() -> tuple[CrmActivityRecord, ...]:
    return tuple(
        record
        for tenant_id in ("tenant-demo", "tenant-other")
        for record in InMemoryCrmActivityRepository.demo().list_activities(tenant_id=tenant_id)
    )


def _demo_notes() -> tuple[CrmNoteRecord, ...]:
    return tuple(
        record
        for tenant_id in ("tenant-demo", "tenant-other")
        for record in InMemoryCrmNoteRepository.demo().list_notes(tenant_id=tenant_id)
    )


def _bootstrap_report_hash(report: CrmRuntimeBootstrapReport) -> str:
    payload = report.model_dump(mode="json", exclude={"evidence_hash"})
    return stable_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main() -> None:
    print(bootstrap_default_crm_runtime().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
