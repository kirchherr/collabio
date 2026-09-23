from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

import suite.platform.office_review_repository as review_repository
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_api import build_office_review_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
)
from suite.platform.office_reviews import ReviewCreateCommand, ReviewEventCommand
from suite.storage.source_object_storage import InMemorySourceObjectContentStore, SourceObjectStorageError
from test_office_documents_pg import Database, command, editor, grant, service_for, set_tenant
from test_office_documents_pg import database as database


def prepared(database: Database) -> tuple[Any, ...]:
    store = InMemorySourceObjectContentStore()
    docs = service_for(database, store)
    user = editor()
    saved = docs.create(user_context=user, command=command(text="Private café 😀 document"), write_enabled=True)
    user.readable_object_ids.add(saved.document.object_id)
    reviews = build_office_review_service(document_service=docs, audit=InMemoryAuditLogger())
    create = ReviewCreateCommand.model_validate(
        {
            "anchor_version_id": saved.version.version_id,
            "expected_current_version_id": saved.version.version_id,
            "anchor": {"from": 9, "to": 13},
            "body": "PRIVATE review body",
            "mutation_reference": "review-create",
            "human_confirmation": True,
        }
    )
    return store, docs, user, saved.document.object_id, reviews, create


def review_counts(database: Database, user: Any) -> tuple[int, ...]:
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        result = []
        for table in (
            "office.review_threads",
            "office.review_events",
            "collabio.source_object_metadata",
            "collabio.source_object_write_receipts",
        ):
            row = connection.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (user.tenant_id,)).fetchone()
            assert row is not None
            result.append(int(row[0]))
        return tuple(result)


def test_pg_review_complete_loop_is_reopenable_after_reconstructing_service(database: Database) -> None:
    store, _, user, object_id, reviews, create = prepared(database)
    created = reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    assert created.quote == "café"
    for revision, operation in enumerate(("reply", "resolve", "reopen"), start=1):
        reviews = build_office_review_service(
            document_service=service_for(database, store), audit=InMemoryAuditLogger()
        )
        reviews.mutate(
            user_context=user,
            object_id=object_id,
            thread_id=created.thread.thread_id,
            write_enabled=True,
            command=ReviewEventCommand.model_validate(
                {
                    "operation": operation,
                    "expected_revision": revision,
                    "mutation_reference": operation,
                    "human_confirmation": True,
                    "body": "reply content" if operation == "reply" else None,
                }
            ),
        )
    detail = reviews.detail(
        user_context=user, object_id=object_id, thread_id=created.thread.thread_id, write_enabled=True
    )
    assert detail.thread.revision == 4 and detail.thread.status == "open"
    assert [event.operation for event in detail.events] == ["create", "reply", "resolve", "reopen"]
    assert review_counts(database, user) == (1, 4, 5, 5)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 5
    replay = reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    assert replay.replayed and replay.applied_revision == 1 and replay.event.event_id == created.event.event_id


def test_pg_review_current_parent_acl_precedes_storage_and_replay(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, docs, user, object_id, reviews, create = prepared(database)
    created = reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    reader = user.model_copy(update={"user_id": "review-reader", "role_ids": set()})
    grant(database, user, object_id, reader.user_id, "read")
    assert not reviews.detail(
        user_context=reader, object_id=object_id, thread_id=created.thread.thread_id, write_enabled=True
    ).can_comment
    with pytest.raises(OfficeDocumentPermissionError):
        reviews.mutate(user_context=reader, object_id=object_id, command=create, write_enabled=True)
    read = Mock(wraps=docs.source_repository.get)
    monkeypatch.setattr(docs.source_repository, "get", read)
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status='revoked', revoked_at_utc=now() "
            "WHERE tenant_id=%s AND object_id=%s AND acl_subject_id=%s",
            (user.tenant_id, object_id, user.user_id),
        )
    with pytest.raises(OfficeDocumentNotFoundError):
        reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    with pytest.raises(OfficeDocumentNotFoundError):
        reviews.detail(user_context=user, object_id=object_id, thread_id=created.thread.thread_id)
    read.assert_not_called()


def test_pg_competing_review_revision_has_one_commit_and_no_loser_side_effect(database: Database) -> None:
    store, _, user, object_id, reviews, create = prepared(database)
    created = reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    barrier = Barrier(2)

    def save(index: int) -> str:
        worker = build_office_review_service(document_service=service_for(database, store), audit=InMemoryAuditLogger())
        barrier.wait(timeout=10)
        try:
            worker.mutate(
                user_context=user,
                object_id=object_id,
                thread_id=created.thread.thread_id,
                write_enabled=True,
                command=ReviewEventCommand(
                    operation="reply",
                    expected_revision=1,
                    body=f"Reply {index}",
                    mutation_reference=f"concurrent-{index}",
                    human_confirmation=True,
                ),
            )
        except OfficeDocumentConflictError:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, (1, 2)))
    assert sorted(results) == ["committed", "conflict"]
    assert review_counts(database, user) == (1, 2, 3, 3)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 3


def test_pg_review_pre_put_outage_rolls_back_thread_and_receipt(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, user, object_id, reviews, create = prepared(database)
    monkeypatch.setattr(store, "put", Mock(side_effect=SourceObjectStorageError("Synthetic storage outage")))
    with pytest.raises(SourceObjectStorageError):
        reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    assert review_counts(database, user) == (0, 0, 1, 1)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 1


def test_pg_review_post_put_binding_failure_rolls_back_and_exposes_orphan(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, docs, user, object_id, reviews, create = prepared(database)
    original = review_repository._prepare

    def corrupt(*args: Any, **kwargs: Any) -> Any:
        result, source, receipt = original(*args, **kwargs)
        result.event = result.event.model_copy(update={"content_hash": "sha256:" + "f" * 64})
        return result, source, receipt

    monkeypatch.setattr(review_repository, "_prepare", corrupt)
    with pytest.raises(psycopg.Error):
        reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    assert review_counts(database, user) == (0, 0, 1, 1)
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 2
    recovery = docs.source_repository.build_content_recovery_evidence(
        tenant_id=user.tenant_id, restore_drill_report_hash="sha256:" + "a" * 64
    )
    assert recovery.orphaned_content_count == 1 and not recovery.api_wiring_allowed


def test_pg_review_rls_immutable_anchor_events_and_head_cannot_rewind(database: Database) -> None:
    _, _, user, object_id, reviews, create = prepared(database)
    created = reviews.mutate(user_context=user, object_id=object_id, command=create, write_enabled=True)
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, "tenant-foreign")
        assert connection.execute("SELECT count(*) FROM office.review_threads").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM office.review_events").fetchone() == (0,)
        set_tenant(connection, user.tenant_id)
        for sql in (
            "UPDATE office.review_events SET operation='reply' WHERE tenant_id=%s",
            "DELETE FROM office.review_events WHERE tenant_id=%s",
            "UPDATE office.review_threads SET anchor_from=2 WHERE tenant_id=%s",
            "UPDATE office.review_threads SET status='resolved' WHERE tenant_id=%s",
            "DELETE FROM office.review_threads WHERE tenant_id=%s",
        ):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(sql, (user.tenant_id,))
    assert (
        reviews.detail(user_context=user, object_id=object_id, thread_id=created.thread.thread_id).thread.revision == 1
    )
