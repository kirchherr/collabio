from __future__ import annotations

import os
import re
from dataclasses import dataclass
from uuid import uuid4

import pytest
from pydantic import ValidationError

from suite.persistence.migration_catalog import get_migration
from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_evidence_ledger import (
    InMemoryLegacySqlEvidenceLedgerStore,
    LegacySqlEvidenceLedgerEntry,
    LegacySqlEvidenceType,
    PgLegacySqlEvidenceLedgerStore,
    build_legacy_sql_evidence_ledger_entry,
    build_legacy_sql_evidence_ledger_entry_hash,
    legacy_sql_evidence_ledger_ref,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
RESTORE_HASH = "sha256:" + "d" * 64


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


def ledger_entry(
    *,
    tenant_id: str = "tenant-1",
    source_system_ref: str = "legacy-sql:sqlserver-prod",
    evidence_type: LegacySqlEvidenceType = LegacySqlEvidenceType.DISCOVERY_INTAKE_OPERATIONS_REPORT,
    evidence_hash: str = HASH_A,
    evidence_status: str = "ready_for_metadata_worker",
    related_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlEvidenceLedgerEntry:
    return build_legacy_sql_evidence_ledger_entry(
        tenant_id=tenant_id,
        source_system_ref=source_system_ref,
        evidence_type=evidence_type,
        evidence_ref=f"legacy-sql:{evidence_type.value}",
        evidence_hash=evidence_hash,
        evidence_status=evidence_status,
        related_evidence_hashes=related_evidence_hashes,
        restore_evidence_hash=RESTORE_HASH,
        captured_by="legacy-sql-ledger-test",
        metadata={"report_schema": "metadata-only"},
    )


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_legacy_sql_evidence_ledger_entry_is_hashable_metadata_only() -> None:
    entry = ledger_entry(related_evidence_hashes=(HASH_B, HASH_C))
    store = InMemoryLegacySqlEvidenceLedgerStore()

    persisted = store.append(entry)

    assert persisted.ledger_entry_hash == build_legacy_sql_evidence_ledger_entry_hash(entry)
    assert legacy_sql_evidence_ledger_ref(persisted) == f"legacy-sql-evidence:{entry.ledger_entry_hash}"
    assert store.get(tenant_id="tenant-1", ledger_entry_hash=entry.ledger_entry_hash) == entry
    assert store.list_entries(tenant_id="tenant-1") == (entry,)
    assert not entry.raw_payload_included
    assert not entry.import_write_executed
    assert not entry.destructive_actions_executed
    assert entry.restore_evidence_hash == RESTORE_HASH

    entry_json = entry.model_dump_json()
    assert "sqlserver://user" not in entry_json
    assert "password" not in entry_json.lower()
    assert "sample_value" not in entry_json

    with pytest.raises(ValueError, match="already exists"):
        store.append(entry)


def test_legacy_sql_evidence_ledger_rejects_sensitive_metadata_or_write_actions() -> None:
    sensitive_payload = ledger_entry().model_dump(mode="json")
    sensitive_payload["metadata"] = {"dsn": "sqlserver://example.invalid"}
    with pytest.raises(ValidationError, match="sensitive payload markers"):
        LegacySqlEvidenceLedgerEntry.model_validate(sensitive_payload)

    payload = ledger_entry().model_dump(mode="json")
    payload["import_write_executed"] = True
    with pytest.raises(ValidationError, match="write actions"):
        LegacySqlEvidenceLedgerEntry.model_validate(payload)


def test_pg_legacy_sql_evidence_ledger_store_persists_entries_with_tenant_isolation(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-legacy-ledger-a-{suffix}"
    tenant_b = f"tenant-legacy-ledger-b-{suffix}"
    store = PgLegacySqlEvidenceLedgerStore(database_dsn=live_database.app_dsn)
    entry_a = ledger_entry(tenant_id=tenant_a, evidence_hash=HASH_A)
    entry_b = ledger_entry(
        tenant_id=tenant_b,
        evidence_type=LegacySqlEvidenceType.READINESS_SMOKE_REPORT,
        evidence_hash=HASH_B,
        evidence_status="smoke_passed",
        related_evidence_hashes=(entry_a.evidence_hash,),
    )

    store.append(entry_a)
    store.append(entry_b)

    assert store.get(tenant_id=tenant_a, ledger_entry_hash=entry_a.ledger_entry_hash) == entry_a
    assert store.list_entries(tenant_id=tenant_a) == (entry_a,)
    assert store.list_entries(tenant_id=tenant_b) == (entry_b,)
    with pytest.raises(KeyError):
        store.get(tenant_id=tenant_a, ledger_entry_hash=entry_b.ledger_entry_hash)


def test_legacy_sql_evidence_ledger_migration_declares_rls_append_only_and_restore_binding() -> None:
    migration = get_migration("0034")
    sql = normalized(migration.sql())

    assert migration.module_id == "crm_erp"
    assert "create table if not exists collabio.legacy_sql_evidence_ledger" in sql
    for column in [
        "tenant_id",
        "module_id",
        "source_system_ref",
        "evidence_type",
        "evidence_ref",
        "evidence_hash",
        "related_evidence_hashes",
        "restore_evidence_hash",
        "ledger_entry_hash",
    ]:
        assert column in sql
    assert "raw_payload_included boolean not null default false check (raw_payload_included = false)" in sql
    assert "import_write_executed boolean not null default false check (import_write_executed = false)" in sql
    assert "destructive_actions_executed boolean not null default false check" in sql
    assert "alter table collabio.legacy_sql_evidence_ledger enable row level security" in sql
    assert "alter table collabio.legacy_sql_evidence_ledger force row level security" in sql
    assert "create policy legacy_sql_evidence_ledger_tenant_select" in sql
    assert "create policy legacy_sql_evidence_ledger_tenant_insert" in sql
    assert "create policy legacy_sql_evidence_ledger_no_update" in sql
    assert "create policy legacy_sql_evidence_ledger_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "grant select, insert on table collabio.legacy_sql_evidence_ledger to collabio_app" in sql
    assert "grant select, insert on table collabio.legacy_sql_evidence_ledger to collabio_worker" in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
