from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from test_office_documents_pg import (
    Database,
    command,
    editor,
    grant,
    service_for,
    set_tenant,
)
from test_office_documents_pg import (
    database as database,
)


def titled_command(index: int, title: str) -> OfficeDocumentCreateCommand:
    return OfficeDocumentCreateCommand(**{**command(f"discovery-{index}").model_dump(), "title": title})


def test_pg_office_discovery_reaches_older_than_200_and_does_not_read_source_content(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    ids: list[str] = []
    for index in range(205):
        saved = service.create(
            user_context=user, command=titled_command(index, f"Discovery {index:03d}"), write_enabled=True
        )
        ids.append(saved.document.object_id)
        user.readable_object_ids.add(saved.document.object_id)
    monkeypatch.setattr(
        service.source_repository, "get", Mock(side_effect=AssertionError("list must not read source bytes"))
    )
    first = service.list_documents(user_context=user)
    assert len(first.documents) == 200 and first.has_more and first.next_cursor
    second = service.list_documents(user_context=user, cursor=first.next_cursor)
    assert [entry.object_id for entry in first.documents + second.documents] == list(reversed(ids))
    assert len(second.documents) == 5 and not second.has_more and second.next_cursor is None
    oldest = service.list_documents(user_context=user, query="discovery 000", page_size=1)
    assert [entry.object_id for entry in oldest.documents] == [ids[0]] and not oldest.has_more


def test_pg_office_discovery_filters_authoritative_typed_acl_before_limit_and_lookahead(database: Database) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    owner = editor()
    viewer = UserContext(tenant_id=owner.tenant_id, user_id="discovery-viewer", role_ids={"office-reader"})
    ids: list[str] = []
    for index in range(5):
        saved = service.create(user_context=owner, command=titled_command(index, "Café %_\\ [a.*]"), write_enabled=True)
        ids.append(saved.document.object_id)
        viewer.readable_object_ids.add(saved.document.object_id)
    grant(database, owner, ids[0], viewer.user_id, "read")
    grant(database, owner, ids[1], viewer.user_id, "read")
    # Even a forged resolved readable-ID set cannot turn another object's ACL type into Office access.
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, owner.tenant_id)
        connection.execute(
            "INSERT INTO collabio.object_acl_entries "
            "(tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, "
            "permission, acl_version, status, audit_chain_ref) "
            "VALUES (%s, %s, 'kb.article', 'user', %s, 'read', 1, 'active', 'audit:wrong-type')",
            (owner.tenant_id, ids[4], viewer.user_id),
        )
    first = service.list_documents(user_context=viewer, query="CAFÉ %_\\", page_size=1)
    assert [entry.object_id for entry in first.documents] == [ids[1]] and first.has_more
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, owner.tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
            "WHERE tenant_id = %s AND object_id = %s AND acl_subject_id = %s",
            (owner.tenant_id, ids[0], viewer.user_id),
        )
    final = service.list_documents(user_context=viewer, query="CAFÉ %_\\", page_size=1, cursor=first.next_cursor)
    assert final.documents == [] and not final.has_more
    assert not service.list_documents(user_context=viewer, query="%_\\", page_size=1).has_more
    assert service.list_documents(user_context=viewer, query="[a.*]", page_size=1).documents[0].object_id == ids[1]
    assert service.list_documents(user_context=viewer.model_copy(update={"tenant_id": "foreign"})).documents == []


def test_pg_office_discovery_immutable_order_survives_saves_and_new_rows(database: Database) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    records: list[Any] = []
    for index in range(4):
        saved = service.create(
            user_context=user, command=titled_command(index, f"Original {index}"), write_enabled=True
        )
        records.append(saved)
        user.readable_object_ids.add(saved.document.object_id)
    first = service.list_documents(user_context=user, page_size=2)
    assert first.next_cursor
    changed = service.save(
        user_context=user,
        object_id=records[0].document.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **{**command("discovery-save").model_dump(), "title": "Renamed older document"},
            expected_current_version_id=records[0].version.version_id,
        ),
    )
    newest = service.create(user_context=user, command=titled_command(8, "Added later"), write_enabled=True)
    user.readable_object_ids.add(newest.document.object_id)
    second = service.list_documents(user_context=user, page_size=2, cursor=first.next_cursor)
    assert [entry.object_id for entry in second.documents] == [
        records[1].document.object_id,
        changed.document.object_id,
    ]
    assert second.documents[-1].title == "Renamed older document" and not second.has_more
    assert service.list_documents(user_context=user).documents[0].object_id == newest.document.object_id
