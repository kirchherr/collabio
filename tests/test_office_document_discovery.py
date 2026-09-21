from __future__ import annotations

import base64
import hmac
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from unittest.mock import Mock

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentListRequestError,
    OfficeDocumentRecord,
    OfficeDocumentService,
)
from test_office_documents import office as office


def seed_discovery_record(
    repository: InMemoryOfficeDocumentRepository,
    user: UserContext,
    index: int,
    *,
    title: str = "Saved document",
    permission: str | None = "read",
) -> OfficeDocumentRecord:
    created_at = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
    record = OfficeDocumentRecord(
        tenant_id=user.tenant_id, object_id=f"office-doc-{index:032x}", title=title,
        current_version_id=f"office-version-{index:032x}", owner_principal_id="source-owner", created_by="source-owner",
        created_at_utc=created_at, updated_at_utc=created_at, audit_chain_ref=f"audit:discovery-{index}",
    )
    repository.documents[(user.tenant_id, record.object_id)] = record
    if permission:
        repository.grants[(user.tenant_id, record.object_id, user.user_id)] = permission
    user.readable_object_ids.add(record.object_id)
    return record


def test_discovery_pages_beyond_200_without_bodies_counts_or_query_audit(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    for index in range(1, 218):
        seed_discovery_record(repository, user, index, title="PRIVATE discovery %_\\ Café")
    monkeypatch.setattr(repository.source_repository, "get", Mock(side_effect=AssertionError("no source reads")))
    first = service.list_documents(user_context=user, write_enabled=True)
    assert len(first.documents) == 200 and first.page_size == 200 and first.has_more and first.can_create
    assert all(not document.can_write for document in first.documents)
    second = service.list_documents(user_context=user, cursor=first.next_cursor)
    assert len(second.documents) == 17 and not second.has_more and second.next_cursor is None
    ids = [document.object_id for document in first.documents + second.documents]
    assert len(set(ids)) == 217 and ids == sorted(ids, reverse=True)
    assert "total" not in first.model_dump() and "content" not in first.model_dump()
    searched = service.list_documents(user_context=user, query="PRIVATE discovery %_\\ café", page_size=17)
    assert searched.has_more and len(searched.documents) == 17
    assert searched.next_cursor is not None
    audit = canonical_json([event.model_dump() for event in service.audit.events])
    assert "PRIVATE" not in audit and "Café" not in audit and searched.next_cursor not in audit


@pytest.mark.parametrize("query,expected", [("CAFÉ", [2]), ("%_\\", [2]), ("ss", [1]), ("straße", [3]), ("[a.*]", [1])])
def test_discovery_literal_case_insensitive_title_search(office: Any, query: str, expected: list[int]) -> None:
    service, repository, user = office
    for index, title in enumerate(["StraSSe [a.*]", "Café %_\\", "Straße"], start=1):
        seed_discovery_record(repository, user, index, title=title)
    result = service.list_documents(user_context=user, query=f"  {query}  ")
    assert [entry.object_id for entry in result.documents] == [f"office-doc-{index:032x}" for index in expected]


def test_discovery_acl_precedes_lookahead_and_revalidates_after_cursor(office: Any) -> None:
    service, repository, user = office
    for index in range(1, 8):
        seed_discovery_record(repository, user, index, permission="read" if index < 4 else None)
    first = service.list_documents(user_context=user, page_size=2)
    assert [item.object_id for item in first.documents] == [f"office-doc-{index:032x}" for index in [3, 2]]
    assert first.has_more
    del repository.grants[(user.tenant_id, f"office-doc-{1:032x}", user.user_id)]
    second = service.list_documents(user_context=user, page_size=2, cursor=first.next_cursor)
    assert second.documents == [] and not second.has_more
    assert not service.list_documents(user_context=user, page_size=2).has_more


def test_discovery_cursor_anchor_survives_revocation_and_title_or_head_changes(office: Any) -> None:
    service, repository, user = office
    for index in range(1, 5):
        seed_discovery_record(repository, user, index)
    first = service.list_documents(user_context=user, page_size=2)
    anchor_id = first.documents[-1].object_id
    del repository.grants[(user.tenant_id, anchor_id, user.user_id)]
    older = repository.documents[(user.tenant_id, f"office-doc-{1:032x}")]
    repository.documents[(user.tenant_id, older.object_id)] = older.model_copy(update={
        "title": "Renamed", "updated_at_utc": "2027-01-01T00:00:00Z", "current_version_id": "new-head",
    })
    seed_discovery_record(repository, user, 8, title="New after first page")
    second = service.list_documents(user_context=user, page_size=2, cursor=first.next_cursor)
    assert [entry.object_id for entry in second.documents] == [f"office-doc-{index:032x}" for index in [2, 1]]
    assert second.documents[-1].title == "Renamed" and not second.has_more
    assert service.list_documents(user_context=user).documents[0].object_id == f"office-doc-{8:032x}"


def test_discovery_same_timestamp_uses_immutable_object_id_tiebreaker(office: Any) -> None:
    service, repository, user = office
    for index in [1, 4, 2, 3]:
        record = seed_discovery_record(repository, user, index)
        repository.documents[(user.tenant_id, record.object_id)] = record.model_copy(
            update={"created_at_utc": "2026-01-01T00:00:00Z"}
        )
    first = service.list_documents(user_context=user, page_size=2)
    second = service.list_documents(user_context=user, page_size=2, cursor=first.next_cursor)
    assert [item.object_id for item in first.documents + second.documents] == [
        f"office-doc-{index:032x}" for index in [4, 3, 2, 1]
    ]
    assert not second.has_more


@pytest.mark.parametrize("change", ["tenant", "actor", "roles", "query", "page_size", "tamper", "restart"])
def test_discovery_cursors_reject_other_context_or_tampering_before_repository(office: Any, monkeypatch: Any, change: str) -> None:
    service, repository, user = office
    for index in [1, 2]:
        seed_discovery_record(repository, user, index)
    first = service.list_documents(user_context=user, page_size=1)
    cursor = first.next_cursor
    assert cursor
    changed_user = user.model_copy(deep=True)
    query, page_size = "", 1
    if change == "tenant":
        changed_user.tenant_id = "foreign"
    elif change == "actor":
        changed_user.user_id = "foreign-actor"
    elif change == "roles":
        changed_user.role_ids = {"office-reader"}
    elif change == "query":
        query = "different"
    elif change == "page_size":
        page_size = 2
    elif change == "tamper":
        cursor = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    else:
        service = OfficeDocumentService(repository=repository, source_repository=repository.source_repository, audit=service.audit)
    monkeypatch.setattr(repository, "list_documents", Mock(side_effect=AssertionError("cursor must fail before query")))
    with pytest.raises(OfficeDocumentListRequestError):
        service.list_documents(user_context=changed_user, query=query, page_size=page_size, cursor=cursor)


@pytest.mark.parametrize("query,page_size,cursor", [
    ("x" * 201, 20, None), ("\x00private", 20, None), ("\ud800", 20, None),
    ("private\u0085", 20, None), ("private\u009f", 20, None),
    ("", 0, None), ("", 201, None), ("", True, None), ("", 1.0, None),
    ("", 20, ""), ("", 20, "x" * 1025), ("", 20, "invalid.base64.payload"),
])
def test_discovery_invalid_navigation_is_bounded(office: Any, query: str, page_size: Any, cursor: str | None) -> None:
    service, _, user = office
    with pytest.raises(OfficeDocumentListRequestError):
        service.list_documents(user_context=user, query=query, page_size=page_size, cursor=cursor)


@pytest.mark.parametrize("key,value", [("created_at", "2026-01-01"), ("created_at", "not-a-timestamp"), ("object_id", "' OR true --")])
def test_discovery_even_signed_malformed_anchor_is_rejected_before_sql(office: Any, key: str, value: str) -> None:
    service, repository, user = office
    for index in [1, 2]:
        seed_discovery_record(repository, user, index)
    cursor = service.list_documents(user_context=user, page_size=1).next_cursor
    assert cursor
    encoded = cursor.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload[key] = value
    raw = canonical_json(payload).encode()
    changed = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(service._list_cursor_key, raw, sha256).hexdigest()
    with pytest.raises(OfficeDocumentListRequestError):
        service.list_documents(user_context=user, page_size=1, cursor=changed)
