from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_api import build_office_suggestion_service
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import (
    OfficeSuggestionService,
    SuggestionCreateCommand,
    SuggestionDecisionCommand,
    replace_suggestion_text,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import InMemorySourceObjectRepository, SourceObjectRecord


def text_document(text: str = "A😀 café PRIVATE") -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def paragraph_text(document: dict[str, Any]) -> str:
    return "".join(node["text"] for node in document["content"][0]["content"])


@dataclass
class SuggestionHarness:
    service: OfficeSuggestionService
    documents: OfficeDocumentService
    sources: InMemorySourceObjectRepository
    user: UserContext
    object_id: str
    version_id: str

    def command(self, reference: str = "suggest-create", replacement: str = "REPLACEMENT") -> SuggestionCreateCommand:
        return SuggestionCreateCommand.model_validate(
            {
                "anchor_version_id": self.version_id,
                "expected_current_version_id": self.version_id,
                "anchor": {"from": 5, "to": 9},
                "replacement_text": replacement,
                "mutation_reference": reference,
                "human_confirmation": True,
            }
        )

    def create(self, reference: str = "suggest-create", replacement: str = "REPLACEMENT") -> Any:
        return self.service.mutate(
            user_context=self.user,
            object_id=self.object_id,
            command=self.command(reference, replacement),
            write_enabled=True,
        )

    def decide(self, suggestion_id: str, operation: str = "accept", reference: str = "decide") -> Any:
        return self.service.mutate(
            user_context=self.user,
            object_id=self.object_id,
            suggestion_id=suggestion_id,
            write_enabled=True,
            command=decision_command(operation, self.version_id, reference),
        )


def decision_command(operation: str, version_id: str, reference: str = "decide") -> SuggestionDecisionCommand:
    return SuggestionDecisionCommand.model_validate(
        {
            "operation": operation,
            "expected_revision": 1,
            "expected_current_version_id": version_id if operation == "accept" else None,
            "mutation_reference": reference,
            "human_confirmation": True,
        }
    )


@pytest.fixture
def suggestions() -> SuggestionHarness:
    sources = InMemorySourceObjectRepository()
    documents = OfficeDocumentService(
        repository=InMemoryOfficeDocumentRepository(source_repository=sources),
        source_repository=sources,
        audit=InMemoryAuditLogger(),
    )
    user = UserContext(tenant_id="tenant-suggestions", user_id="editor", role_ids={"office-editor"})
    saved = documents.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Private title",
            document=text_document(),
            mutation_reference="initial",
            human_confirmation=True,
        ),
    )
    user.readable_object_ids.add(saved.document.object_id)
    service = build_office_suggestion_service(document_service=documents, audit=InMemoryAuditLogger())
    return SuggestionHarness(service, documents, sources, user, saved.document.object_id, saved.version.version_id)


def test_suggestion_accept_saves_exact_new_version_and_terminal_decision(suggestions: SuggestionHarness) -> None:
    created = suggestions.create()
    assert created.quote == "café" and created.applied_revision == 1
    assert (
        len(suggestions.documents.history(user_context=suggestions.user, object_id=suggestions.object_id).versions) == 1
    )
    accepted = suggestions.decide(created.suggestion.suggestion_id)
    assert accepted.suggestion.status == "accepted" and accepted.applied_revision == 2
    assert accepted.document_result.version.previous_version_id == suggestions.version_id
    assert accepted.suggestion.result_version_id == accepted.document_result.version.version_id
    assert paragraph_text(accepted.document_result.content) == "A😀 REPLACEMENT PRIVATE"
    historical = suggestions.documents.read_content(
        user_context=suggestions.user, object_id=suggestions.object_id, version_id=suggestions.version_id
    )
    assert historical.content == text_document()
    detail = suggestions.service.detail(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        suggestion_id=created.suggestion.suggestion_id,
        write_enabled=True,
    )
    assert detail.quote == "café" and detail.replacement_text == "REPLACEMENT"
    assert not detail.suggestion.can_accept and not detail.suggestion.can_reject
    assert suggestions.decide(created.suggestion.suggestion_id).replayed
    assert (
        len(suggestions.documents.history(user_context=suggestions.user, object_id=suggestions.object_id).versions) == 2
    )
    with pytest.raises(OfficeDocumentConflictError):
        suggestions.decide(created.suggestion.suggestion_id, "reject", "different")


def test_suggestion_stale_accept_denied_but_reject_is_durable(suggestions: SuggestionHarness) -> None:
    created = suggestions.create()
    suggestions.documents.save(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Later",
            document=text_document("Other content"),
            expected_current_version_id=suggestions.version_id,
            mutation_reference="later",
            human_confirmation=True,
        ),
    )
    with pytest.raises(OfficeDocumentConflictError):
        suggestions.decide(created.suggestion.suggestion_id)
    rejected = suggestions.decide(created.suggestion.suggestion_id, "reject")
    assert rejected.suggestion.status == "rejected" and rejected.document_result is None
    assert suggestions.decide(created.suggestion.suggestion_id, "reject").replayed
    assert (
        len(suggestions.documents.history(user_context=suggestions.user, object_id=suggestions.object_id).versions) == 2
    )


def test_suggestion_exact_retry_is_actor_bound_and_rechecks_acl(suggestions: SuggestionHarness) -> None:
    created = suggestions.create()
    assert suggestions.create().replayed
    with pytest.raises(OfficeDocumentConflictError):
        suggestions.create(replacement="DIFFERENT")
    accepted = suggestions.decide(created.suggestion.suggestion_id)
    suggestions.documents.save(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Later",
            document=text_document("Later content"),
            expected_current_version_id=accepted.suggestion.result_version_id,
            mutation_reference="later",
            human_confirmation=True,
        ),
    )
    replayed = suggestions.decide(created.suggestion.suggestion_id)
    assert replayed.document_result.version.version_id == accepted.document_result.version.version_id
    assert not replayed.document_result.is_current_version
    assert replayed.document_result.content == accepted.document_result.content
    repository = suggestions.documents.repository
    assert isinstance(repository, InMemoryOfficeDocumentRepository)
    repository.grants[(suggestions.user.tenant_id, suggestions.object_id, suggestions.user.user_id)] = "read"
    with pytest.raises(OfficeDocumentPermissionError):
        suggestions.decide(created.suggestion.suggestion_id)


@pytest.mark.parametrize("change", ("read-only", "foreign", "missing", "no-readable"))
def test_suggestion_access_fails_before_source_reads(
    suggestions: SuggestionHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    created = suggestions.create()
    user = suggestions.user
    repository = suggestions.documents.repository
    assert isinstance(repository, InMemoryOfficeDocumentRepository)
    if change == "read-only":
        repository.grants[(user.tenant_id, suggestions.object_id, user.user_id)] = "read"
    elif change == "foreign":
        user = user.model_copy(update={"tenant_id": "foreign"})
    elif change == "missing":
        repository.grants.clear()
    else:
        user = user.model_copy(update={"readable_object_ids": set()})
    read = Mock(side_effect=AssertionError("must not read content"))
    monkeypatch.setattr(suggestions.sources, "get", read)
    with pytest.raises((OfficeDocumentPermissionError, OfficeDocumentNotFoundError)):
        suggestions.service.mutate(
            user_context=user,
            object_id=suggestions.object_id,
            suggestion_id=created.suggestion.suggestion_id,
            command=decision_command("accept", suggestions.version_id),
            write_enabled=True,
        )
    read.assert_not_called()


@pytest.mark.parametrize("available,enabled", ((False, True), (True, False)))
def test_suggestion_writes_require_feature_and_durable_service(
    suggestions: SuggestionHarness, available: bool, enabled: bool
) -> None:
    suggestions.documents.writes_available = available
    assert not suggestions.service.list_suggestions(
        user_context=suggestions.user, object_id=suggestions.object_id, write_enabled=enabled
    ).can_create
    with pytest.raises(OfficeDocumentPermissionError):
        suggestions.service.mutate(
            user_context=suggestions.user,
            object_id=suggestions.object_id,
            command=suggestions.command(),
            write_enabled=enabled,
        )


def test_suggestion_pagination_is_complete_and_historical_filter_validated(suggestions: SuggestionHarness) -> None:
    for index in range(7):
        suggestions.create(f"create-{index}")
    after, seen = None, set()
    while True:
        page = suggestions.service.list_suggestions(
            user_context=suggestions.user, object_id=suggestions.object_id, after=after, limit=3
        )
        seen.update(item.suggestion_id for item in page.suggestions)
        after = page.next_cursor
        if after is None:
            break
    assert len(seen) == 7
    with pytest.raises(OfficeDocumentNotFoundError):
        suggestions.service.list_suggestions(
            user_context=suggestions.user, object_id=suggestions.object_id, anchor_version_id="missing"
        )


@pytest.mark.parametrize("replacement", ("", "<script>$&</script>", "😀" * 4000))
def test_suggestion_literal_deletion_and_max_unicode(suggestions: SuggestionHarness, replacement: str) -> None:
    created = suggestions.create(replacement=replacement)
    result = suggestions.decide(created.suggestion.suggestion_id)
    assert paragraph_text(result.document_result.content) == f"A😀 {replacement} PRIVATE"


def test_suggestion_replacement_preserves_cross_mark_structure_and_following_positions() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "ab", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": "cd", "marks": [{"type": "italic"}]},
                    {"type": "text", "text": "ef"},
                ],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "tail"}]},
        ],
    }
    result = replace_suggestion_text(document, ReviewAnchor.model_validate({"from": 2, "to": 5}), "XYZ")
    assert result["content"][0]["content"] == [
        {"type": "text", "text": "a", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "XYZ", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "ef"},
    ]
    assert result["content"][1] == document["content"][1]
    assert derive_review_quote(result, ReviewAnchor.model_validate({"from": 9, "to": 13})) == "tail"


@pytest.mark.parametrize("anchor", ({"from": 2, "to": 3}, {"from": 1, "to": 99}))
def test_suggestion_rejects_split_surrogate_and_outside_anchor(anchor: dict[str, int]) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        replace_suggestion_text(text_document(), ReviewAnchor.model_validate(anchor), "change")


def test_suggestion_rejects_noop_cross_break_and_output_limits() -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        replace_suggestion_text(text_document("same"), ReviewAnchor.model_validate({"from": 1, "to": 5}), "same")
    broken = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "ab"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "cd"},
                ],
            }
        ],
    }
    with pytest.raises(OfficeDocumentInvalidContentError):
        replace_suggestion_text(broken, ReviewAnchor.model_validate({"from": 2, "to": 5}), "new")
    with pytest.raises(OfficeDocumentInvalidContentError):
        replace_suggestion_text(text_document("a" * 100000), ReviewAnchor.model_validate({"from": 1, "to": 2}), "xx")


def test_suggestion_corruption_and_outage_fail_closed(
    suggestions: SuggestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = suggestions.create()
    original = suggestions.sources.get

    def corrupt(**kwargs: Any) -> SourceObjectRecord:
        record = original(**kwargs)
        return record.model_copy(update={"content_bytes": b"corrupt"})

    monkeypatch.setattr(suggestions.sources, "get", corrupt)
    with pytest.raises(OfficeDocumentInvalidContentError):
        suggestions.decide(created.suggestion.suggestion_id)
    monkeypatch.setattr(suggestions.sources, "get", Mock(side_effect=SourceObjectStorageError("PRIVATE")))
    with pytest.raises(SourceObjectStorageError):
        suggestions.decide(created.suggestion.suggestion_id)


@pytest.mark.parametrize(
    "overrides", ({"human_confirmation": False}, {"expected_revision": True}, {"expected_revision": 2})
)
def test_suggestion_decisions_require_exact_confirmation_and_revision(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SuggestionDecisionCommand.model_validate(
            {
                "operation": "reject",
                "expected_revision": 1,
                "mutation_reference": "x",
                "human_confirmation": True,
                **overrides,
            }
        )
