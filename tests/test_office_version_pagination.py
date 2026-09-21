from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError
from suite.platform.office_documents import (
    OfficeDocumentHistoryRequestError,
    OfficeDocumentListRequestError,
    OfficeDocumentNotFoundError,
    OfficeDocumentRecord,
    OfficeDocumentService,
    OfficeDocumentVersion,
)
from test_office_documents import office as office


def seed_version_history(
    repository: InMemoryOfficeDocumentRepository, user: UserContext, count: int = 225, *, document_index: int = 1,
) -> tuple[str, list[str]]:
    """Metadata-only fixture with identical timestamps and deliberately contrary ID order."""
    object_id = f"office-doc-{document_index:032x}"
    ids = [f"office-version-{document_index * 1000 + count - index:032x}" for index in range(count)]
    timestamp = "2026-09-21T08:00:00Z"
    repository.documents[(user.tenant_id, object_id)] = OfficeDocumentRecord(
        tenant_id=user.tenant_id, object_id=object_id, title="Private history title",
        current_version_id=ids[-1], owner_principal_id=user.user_id, created_by=user.user_id,
        created_at_utc=timestamp, updated_at_utc=timestamp, audit_chain_ref="audit:history-fixture",
    )
    for index, version_id in enumerate(ids):
        repository.saved_versions[(user.tenant_id, object_id, version_id)] = OfficeDocumentVersion(
            tenant_id=user.tenant_id, object_id=object_id, version_id=version_id,
            previous_version_id=ids[index - 1] if index else None, title=f"Private history title {index}",
            created_at_utc=timestamp, created_by=user.user_id, content_hash=f"sha256:{index:064x}",
            source_manifest_hash="sha256:" + "a" * 64, source_write_receipt_hash=f"sha256:{index:064x}",
            content_byte_length=10, acl_hash="sha256:" + "b" * 64, acl_version=1,
            mutation_reference=f"history-{document_index}-{index}", command_hash="sha256:" + "c" * 64,
            audit_chain_ref="audit:history-fixture",
        )
    repository.grants[(user.tenant_id, object_id, user.user_id)] = "read"
    user.readable_object_ids.add(object_id)
    return object_id, ids


def test_history_pagination_reaches_all_versions_by_links_without_source_bytes(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    object_id, ids = seed_version_history(repository, user)
    source_read = Mock(side_effect=AssertionError("history must not read source content"))
    monkeypatch.setattr(repository.source_repository, "get", source_read)
    first = service.history(user_context=user, object_id=object_id)
    assert first.page_size == 200 and len(first.versions) == 200 and first.has_more and first.next_cursor
    assert first.history_head_version_id == first.current_version_id == ids[-1]
    last = service.history(user_context=user, object_id=object_id, cursor=first.next_cursor)
    assert [version.version_id for version in first.versions + last.versions] == list(reversed(ids))
    assert len(last.versions) == 25 and last.versions[-1].previous_version_id is None
    assert not last.has_more and last.next_cursor is None
    assert first.versions[-1].previous_version_id == last.versions[0].version_id
    assert [version.version_id for version in repository.versions(user_context=user, object_id=object_id)] == list(reversed(ids))[:200]
    audit = canonical_json([event.model_dump() for event in service.audit.events])
    assert "Private history title" not in audit and first.next_cursor not in audit
    source_read.assert_not_called()


def test_history_keeps_original_head_while_current_head_advances(office: Any) -> None:
    service, repository, user = office
    object_id, ids = seed_version_history(repository, user, 7)
    first = service.history(user_context=user, object_id=object_id, page_size=3)
    newest_id = "office-version-" + "f" * 32
    previous = repository.saved_versions[(user.tenant_id, object_id, ids[-1])]
    repository.saved_versions[(user.tenant_id, object_id, newest_id)] = previous.model_copy(update={
        "version_id": newest_id, "previous_version_id": ids[-1],
    })
    key = (user.tenant_id, object_id)
    repository.documents[key] = repository.documents[key].model_copy(update={"current_version_id": newest_id})
    page = service.history(user_context=user, object_id=object_id, page_size=3, cursor=first.next_cursor)
    assert page.history_head_version_id == ids[-1] and page.current_version_id == newest_id
    assert [version.version_id for version in page.versions] == list(reversed(ids))[3:6]
    last = service.history(user_context=user, object_id=object_id, page_size=3, cursor=page.next_cursor)
    assert [version.version_id for version in last.versions] == ids[:1] and not last.has_more
    refreshed = service.history(user_context=user, object_id=object_id, page_size=3)
    assert refreshed.history_head_version_id == newest_id and refreshed.versions[0].version_id == newest_id


@pytest.mark.parametrize("page_size", [1, 2, 7, 50, 200])
def test_history_page_boundaries_and_lookahead_agree(office: Any, page_size: int) -> None:
    service, repository, user = office
    object_id, ids = seed_version_history(repository, user, 7)
    versions: list[str] = []
    cursor = None
    while True:
        result = service.history(user_context=user, object_id=object_id, page_size=page_size, cursor=cursor)
        assert 0 < len(result.versions) <= page_size
        assert result.has_more == (result.next_cursor is not None) == (result.versions[-1].previous_version_id is not None)
        versions.extend(version.version_id for version in result.versions)
        if not result.has_more:
            break
        assert result.next_cursor != cursor
        cursor = result.next_cursor
    assert versions == list(reversed(ids))


@pytest.mark.parametrize("change", ["tenant", "actor", "roles", "document", "page_size", "restart", "tamper"])
def test_history_cursor_context_is_checked_before_repository(office: Any, monkeypatch: Any, change: str) -> None:
    service, repository, user = office
    object_id, _ = seed_version_history(repository, user, 3)
    token = service.history(user_context=user, object_id=object_id, page_size=1).next_cursor
    assert token
    page_size = 1
    if change == "tenant":
        user = user.model_copy(update={"tenant_id": "foreign-tenant"})
    elif change == "actor":
        user = user.model_copy(update={"user_id": "another-actor"})
    elif change == "roles":
        user = user.model_copy(update={"role_ids": {"office-reader"}})
    elif change == "document":
        object_id = "office-doc-" + "f" * 32
    elif change == "page_size":
        page_size = 2
    elif change == "restart":
        service = OfficeDocumentService(repository=repository, source_repository=repository.source_repository, audit=service.audit)
    else:
        token += "tampered"
    read = Mock(side_effect=AssertionError("invalid cursor must precede repository"))
    monkeypatch.setattr(repository, "history_page", read)
    with pytest.raises(OfficeDocumentHistoryRequestError, match=r"^Invalid version history request$"):
        service.history(user_context=user, object_id=object_id, page_size=page_size, cursor=token)
    read.assert_not_called()


def test_history_cursor_is_domain_separated_from_discovery_and_never_authorizes(office: Any) -> None:
    service, repository, user = office
    object_id, _ = seed_version_history(repository, user, 3)
    seed_version_history(repository, user, 2, document_index=2)
    history = service.history(user_context=user, object_id=object_id, page_size=1)
    discovery = service.list_documents(user_context=user, page_size=1)
    assert history.next_cursor and discovery.next_cursor
    with pytest.raises(OfficeDocumentHistoryRequestError):
        service.history(user_context=user, object_id=object_id, page_size=1, cursor=discovery.next_cursor)
    with pytest.raises(OfficeDocumentListRequestError):
        service.list_documents(user_context=user, page_size=1, cursor=history.next_cursor)
    del repository.grants[(user.tenant_id, object_id, user.user_id)]
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=user, object_id=object_id, page_size=1, cursor=history.next_cursor)


@pytest.mark.parametrize("page_size,cursor", [(0, None), (201, None), (True, None), (1.0, None), (1, ""), (1, "x" * 1025), (1, "private-invalid")])
def test_history_invalid_parameters_fail_before_repository(office: Any, monkeypatch: Any, page_size: Any, cursor: Any) -> None:
    service, repository, user = office
    read = Mock(side_effect=AssertionError("invalid request must not access history"))
    monkeypatch.setattr(repository, "history_page", read)
    with pytest.raises(OfficeDocumentHistoryRequestError):
        service.history(user_context=user, object_id="unreadable", page_size=page_size, cursor=cursor)
    read.assert_not_called()


@pytest.mark.parametrize("corruption", ["missing_head", "missing_predecessor", "cycle", "lookahead_cycle", "foreign_link"])
def test_history_integrity_failures_never_return_partial_metadata(office: Any, corruption: str) -> None:
    service, repository, user = office
    object_id, ids = seed_version_history(repository, user, 3)
    if corruption == "missing_head":
        del repository.saved_versions[(user.tenant_id, object_id, ids[-1])]
    elif corruption == "missing_predecessor":
        del repository.saved_versions[(user.tenant_id, object_id, ids[-2])]
    else:
        key = (user.tenant_id, object_id, ids[0] if corruption == "lookahead_cycle" else ids[-2])
        repository.saved_versions[key] = repository.saved_versions[key].model_copy(update={
            "previous_version_id": ids[-1] if corruption != "foreign_link" else "office-version-" + "f" * 32,
        })
    with pytest.raises(OfficeDocumentInvalidContentError):
        service.history(user_context=user, object_id=object_id, page_size=2)


@pytest.mark.parametrize("field,value", [("head", "wrong"), ("next", "wrong"), ("next", 1)])
def test_history_even_signed_cursor_positions_are_strictly_validated(office: Any, field: str, value: Any) -> None:
    service, repository, user = office
    object_id, ids = seed_version_history(repository, user, 3)
    fields = {"head": ids[-1], "next": ids[-2]}
    fields[field] = value
    cursor = service._write_history_cursor(fields["head"], fields["next"], service._history_binding(user, object_id, 1))
    with pytest.raises(OfficeDocumentHistoryRequestError):
        service.history(user_context=user, object_id=object_id, page_size=1, cursor=cursor)
