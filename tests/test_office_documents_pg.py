import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.source_object_storage import (
    InMemorySourceObjectContentStore,
    PgSourceObjectRepository,
    SourceObjectStorageError,
    StoredSourceObjectContent,
)
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore, SourceObjectRecord

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Database:
    admin_dsn: str
    app_dsn: str


@pytest.fixture(scope="module")
def database() -> Database:
    admin = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    app = os.environ.get("SUITE_DATABASE_DSN")
    if not admin or not app:
        pytest.skip("PostgreSQL integration environment is not configured")
    apply_migrations(admin)
    return Database(admin_dsn=admin, app_dsn=app)


def source_repository(database: Database, store: InMemorySourceObjectContentStore) -> PgSourceObjectRepository:
    return PgSourceObjectRepository(
        database_dsn=database.app_dsn,
        content_store=store,
        retention_policy=load_retention_manifest_policy(ROOT / "docs" / "retention_manifest_policy.json"),
        storage_policy=load_storage_adapter_policy(ROOT / "docs" / "storage_adapter_policy.json"),
    )


def service_for(database: Database, store: InMemorySourceObjectContentStore) -> OfficeDocumentService:
    source = source_repository(database, store)
    return OfficeDocumentService(
        repository=PgOfficeDocumentRepository(
            database_dsn=database.app_dsn,
            source_repository=source,
            receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=database.app_dsn),
        ),
        source_repository=source,
        audit=InMemoryAuditLogger(),
    )


def editor() -> UserContext:
    return UserContext(tenant_id=f"tenant-office-{uuid4().hex}", user_id="native-editor", role_ids={"office-editor"})


def command(reference: str = "create", text: str = "Private native content") -> OfficeDocumentCreateCommand:
    return OfficeDocumentCreateCommand(
        title="Native document",
        mutation_reference=reference,
        human_confirmation=True,
        document={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
    )


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))


def counts(database: Database, user: UserContext) -> tuple[int, ...]:
    tables = (
        "office.documents",
        "office.document_versions",
        "collabio.source_object_metadata",
        "collabio.source_object_write_receipts",
        "collabio.object_acl_entries",
    )
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        result = []
        for table in tables:
            row = connection.execute(f"SELECT count(*) FROM {table} WHERE tenant_id = %s", (user.tenant_id,)).fetchone()
            assert row is not None
            result.append(int(row[0]))
        return tuple(result)


def grant(database: Database, user: UserContext, object_id: str, principal: str, permission: str) -> None:
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute(
            "INSERT INTO collabio.object_acl_entries "
            "(tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, "
            "permission, acl_version, status, audit_chain_ref) "
            "VALUES (%s, %s, 'office.document', 'user', %s, %s, 1, 'active', 'audit:office-test-grant')",
            (user.tenant_id, object_id, principal, permission),
        )


def test_pg_create_save_read_history_receipts_and_creator_acl_are_atomic(database: Database) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    assert counts(database, user) == (1, 1, 1, 1, 1)
    assert service.read_content(user_context=user, object_id=object_id, write_enabled=True).can_write
    second_actor = user.model_copy(update={"user_id": "second-editor"})
    grant(database, user, object_id, second_actor.user_id, "write")
    saved = service.save(
        user_context=second_actor,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **command("save", "Updated text").model_dump(),
            expected_current_version_id=created.version.version_id,
        ),
    )
    assert saved.version.created_by == "second-editor"
    original = service.read_content(user_context=user, object_id=object_id, version_id=created.version.version_id)
    assert original.content == command().document
    current = service.read_content(user_context=user, object_id=object_id)
    assert current.content == command(text="Updated text").document
    assert len(service.history(user_context=user, object_id=object_id).versions) == 2
    assert counts(database, user) == (1, 2, 2, 2, 2)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 2
    receipt = PgSourceObjectWriteReceiptStore(database_dsn=database.app_dsn).get(
        tenant_id=user.tenant_id,
        receipt_hash=saved.version.source_write_receipt_hash,
    )
    assert receipt.created_by == second_actor.user_id and receipt.owner_principal_id == user.user_id
    assert receipt.content_hash == saved.version.content_hash


def test_pg_explicit_read_acl_never_grants_write_and_revocation_blocks_history(database: Database) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    object_id = created.document.object_id
    reader = user.model_copy(update={"user_id": "reader", "role_ids": set(), "readable_object_ids": {object_id}})
    grant(database, user, object_id, reader.user_id, "read")
    assert service.read_content(user_context=reader, object_id=object_id).content == command().document
    assert service.read_content(user_context=reader, object_id=object_id, write_enabled=True).can_write is False
    with pytest.raises(OfficeDocumentPermissionError):
        service.save(
            user_context=reader,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **command("denied").model_dump(),
                expected_current_version_id=created.version.version_id,
            ),
        )
    forged = reader.model_copy(update={"user_id": "forged", "role_ids": {"office-editor"}})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=forged, object_id=object_id)
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
            "WHERE tenant_id = %s AND object_id = %s AND acl_subject_id = %s",
            (user.tenant_id, object_id, reader.user_id),
        )
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=reader, object_id=object_id)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 1
    assert counts(database, user) == (1, 1, 1, 1, 2)


def test_pg_concurrent_stale_save_loser_has_no_receipt_source_or_orphan(database: Database) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    user.readable_object_ids.add(created.document.object_id)
    barrier = Barrier(2)

    def save(index: int) -> str:
        worker = service_for(database, store)
        barrier.wait(timeout=10)
        try:
            worker.save(
                user_context=user,
                object_id=created.document.object_id,
                write_enabled=True,
                command=OfficeDocumentSaveCommand(
                    **command(f"save-{index}", f"Version {index}").model_dump(),
                    expected_current_version_id=created.version.version_id,
                ),
            )
        except OfficeDocumentConflictError:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, (1, 2)))
    assert sorted(results) == ["committed", "conflict"]
    assert counts(database, user) == (1, 2, 2, 2, 1)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 2


def test_pg_exact_retry_replays_actor_bound_receipt_even_after_later_save(database: Database) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    user.readable_object_ids.add(created.document.object_id)
    service.save(
        user_context=user,
        object_id=created.document.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **command("save", "Later").model_dump(), expected_current_version_id=created.version.version_id
        ),
    )
    replay = service.create(user_context=user, command=command(), write_enabled=True)
    assert replay.replayed and not replay.is_current_version and replay.version == created.version
    with pytest.raises(OfficeDocumentConflictError):
        service.create(user_context=user, command=command(text="Different content"), write_enabled=True)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 2
    assert counts(database, user) == (1, 2, 2, 2, 1)


class FailingContentStore(InMemorySourceObjectContentStore):
    def put(self, *, record: SourceObjectRecord, bucket_id: str, object_key: str) -> StoredSourceObjectContent:
        raise SourceObjectStorageError("Synthetic pre-PUT outage")


def test_pg_storage_failure_rolls_back_document_creator_acl_and_receipt(database: Database) -> None:
    store = FailingContentStore()
    service = service_for(database, store)
    user = editor()
    with pytest.raises(SourceObjectStorageError):
        service.create(user_context=user, command=command(), write_enabled=True)
    assert counts(database, user) == (0, 0, 0, 0, 0)
    assert store.list_stored_objects(tenant_id=user.tenant_id) == ()
    assert service.audit.events == ()


def test_pg_database_failure_after_put_preserves_old_head_and_detects_orphan(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)

    def fail_version_insert(connection: psycopg.Connection[Any], version: Any) -> None:
        connection.execute("SELECT 1 / 0")

    monkeypatch.setattr(service.repository, "_insert_version", fail_version_insert)
    with pytest.raises(psycopg.errors.DivisionByZero):
        service.save(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **command("failed-save", "Uncommitted draft").model_dump(),
                expected_current_version_id=created.version.version_id,
            ),
        )
    assert counts(database, user) == (1, 1, 1, 1, 1)
    assert service.read_content(user_context=user, object_id=object_id).version == created.version
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 2
    recovery = source_repository(database, store).build_content_recovery_evidence(
        tenant_id=user.tenant_id,
        restore_drill_report_hash="sha256:" + "a" * 64,
    )
    assert recovery.orphaned_content_count == 1
    assert recovery.missing_content_count == 0
    assert recovery.source_content_recovery_required
    assert not recovery.api_wiring_allowed


def test_pg_rls_append_only_versions_and_head_cannot_rewind(database: Database) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    user.readable_object_ids.add(created.document.object_id)
    service.save(
        user_context=user,
        object_id=created.document.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **command("save", "New").model_dump(), expected_current_version_id=created.version.version_id
        ),
    )
    foreign = user.model_copy(update={"tenant_id": "tenant-other"})
    assert service.list_documents(user_context=foreign).documents == []
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=foreign, object_id=created.document.object_id)
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        for sql in (
            "UPDATE office.document_versions SET title = 'mutated' WHERE tenant_id = %s",
            "DELETE FROM office.document_versions WHERE tenant_id = %s",
            "UPDATE office.documents SET owner_principal_id = 'other' WHERE tenant_id = %s",
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(sql, (user.tenant_id,))
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "UPDATE office.documents SET current_version_id = %s WHERE tenant_id = %s AND object_id = %s",
                (created.version.version_id, user.tenant_id, created.document.object_id),
            )
