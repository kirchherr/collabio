from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

import suite.platform.office_document_repository as document_repository
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentNotFoundError, OfficeDocumentSaveCommand
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from test_office_documents_pg import Database, command, editor, grant, service_for, set_tenant
from test_office_documents_pg import database as database


def test_pg_history_follows_205_real_same_timestamp_versions_and_reads_old_content(
    database: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare = document_repository._prepare_version
    fixed = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)

    def same_timestamp(**values: Any) -> Any:
        # Freeze only preparation; psycopg timestamp conversion continues using the real datetime type.
        with monkeypatch.context() as clock:
            clock.setattr(document_repository, "datetime", Mock(now=Mock(return_value=fixed)))
            return prepare(**values)

    monkeypatch.setattr(document_repository, "_prepare_version", same_timestamp)
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    saved = service.create(user_context=user, command=command("history-create", "Oldest exact content"), write_enabled=True)
    object_id = saved.document.object_id
    user.readable_object_ids.add(object_id)
    ids = [saved.version.version_id]
    for index in range(1, 205):
        saved = service.save(
            user_context=user, object_id=object_id, write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **command(f"history-save-{index}", f"Saved text {index}").model_dump(),
                expected_current_version_id=ids[-1],
            ),
        )
        ids.append(saved.version.version_id)
    assert len(set(ids)) == 205
    with monkeypatch.context() as read_guard:
        source_read = Mock(side_effect=AssertionError("metadata pagination must not read bytes"))
        read_guard.setattr(service.source_repository, "get", source_read)
        first = service.history(user_context=user, object_id=object_id)
        assert first.page_size == 200 and len(first.versions) == 200 and first.has_more
        last = service.history(user_context=user, object_id=object_id, cursor=first.next_cursor)
        assert [version.version_id for version in first.versions + last.versions] == list(reversed(ids))
        assert len({version.created_at_utc for version in first.versions + last.versions}) == 1
        assert last.versions[-1].previous_version_id is None and not last.has_more and last.next_cursor is None
        source_read.assert_not_called()
    oldest = service.read_content(user_context=user, object_id=object_id, version_id=ids[0])
    assert oldest.content == command(text="Oldest exact content").document and not oldest.is_current_version


def test_pg_history_cursor_continuation_is_immutable_across_confirmed_new_saves(database: Database) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    saved = service.create(user_context=user, command=command("history-create"), write_enabled=True)
    object_id = saved.document.object_id
    user.readable_object_ids.add(object_id)
    ids = [saved.version.version_id]
    for index in range(1, 4):
        saved = service.save(
            user_context=user, object_id=object_id, write_enabled=True,
            command=OfficeDocumentSaveCommand(**command(f"history-save-{index}").model_dump(), expected_current_version_id=ids[-1]),
        )
        ids.append(saved.version.version_id)
    first = service.history(user_context=user, object_id=object_id, page_size=2)
    newest = service.save(
        user_context=user, object_id=object_id, write_enabled=True,
        command=OfficeDocumentSaveCommand(**command("history-after-page").model_dump(), expected_current_version_id=ids[-1]),
    )
    final = service.history(user_context=user, object_id=object_id, page_size=2, cursor=first.next_cursor)
    assert final.history_head_version_id == first.history_head_version_id == ids[-1]
    assert final.current_version_id == newest.version.version_id
    assert [version.version_id for version in first.versions + final.versions] == list(reversed(ids))
    assert not final.has_more
    refreshed = service.history(user_context=user, object_id=object_id, page_size=2)
    assert refreshed.history_head_version_id == refreshed.current_version_id == newest.version.version_id


def test_pg_history_rechecks_typed_parent_acl_before_cursor_page_metadata(
    database: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    owner = editor()
    created = service.create(user_context=owner, command=command("history-create"), write_enabled=True)
    object_id = created.document.object_id
    owner.readable_object_ids.add(object_id)
    service.save(
        user_context=owner, object_id=object_id, write_enabled=True,
        command=OfficeDocumentSaveCommand(**command("history-save").model_dump(), expected_current_version_id=created.version.version_id),
    )
    viewer = UserContext(tenant_id=owner.tenant_id, user_id="history-reader", role_ids={"office-reader"}, readable_object_ids={object_id})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=viewer, object_id=object_id)
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, owner.tenant_id)
        connection.execute(
            "INSERT INTO collabio.object_acl_entries "
            "(tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, "
            "permission, acl_version, status, audit_chain_ref) "
            "VALUES (%s, %s, 'kb.article', 'user', %s, 'read', 1, 'active', 'audit:wrong-type')",
            (owner.tenant_id, object_id, viewer.user_id),
        )
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=viewer, object_id=object_id)
    grant(database, owner, object_id, viewer.user_id, "read")
    first = service.history(user_context=viewer, object_id=object_id, page_size=1)
    assert first.has_more and first.next_cursor
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, owner.tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
            "WHERE tenant_id = %s AND object_id = %s AND acl_subject_id = %s AND object_type = 'office.document'",
            (owner.tenant_id, object_id, viewer.user_id),
        )
    metadata = Mock(side_effect=AssertionError("revoked cursor must not load its head metadata"))
    monkeypatch.setattr(service.repository, "_version", metadata)
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=viewer, object_id=object_id, page_size=1, cursor=first.next_cursor)
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=viewer.model_copy(update={"tenant_id": "foreign"}), object_id=object_id)
    metadata.assert_not_called()
