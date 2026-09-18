from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_api import build_office_review_service
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
from suite.platform.office_review_repository import InMemoryOfficeReviewRepository
from suite.platform.office_reviews import (
    OfficeReviewService,
    ReviewAnchor,
    ReviewCreateCommand,
    ReviewEventCommand,
    derive_review_quote,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import InMemorySourceObjectRepository, SourceObjectRecord


def text_document(text: str = "A😀 café SECRET") -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


@dataclass
class ReviewHarness:
    service: OfficeReviewService
    documents: OfficeDocumentService
    repository: InMemoryOfficeReviewRepository
    sources: InMemorySourceObjectRepository
    user: UserContext
    object_id: str
    version_id: str

    def command(
        self, reference: str = "review-create", body: str = "PRIVATE COMMENT", anchor: dict[str, int] | None = None
    ) -> ReviewCreateCommand:
        return ReviewCreateCommand.model_validate(
            {
                "anchor_version_id": self.version_id,
                "expected_current_version_id": self.version_id,
                "anchor": anchor,
                "body": body,
                "mutation_reference": reference,
                "human_confirmation": True,
            }
        )

    def create(self, reference: str = "review-create", anchor: dict[str, int] | None = None) -> Any:
        return self.service.mutate(
            user_context=self.user,
            object_id=self.object_id,
            command=self.command(reference, anchor=anchor),
            write_enabled=True,
        )


@pytest.fixture
def reviews() -> ReviewHarness:
    source = InMemorySourceObjectRepository()
    docs = OfficeDocumentService(
        repository=InMemoryOfficeDocumentRepository(source_repository=source),
        source_repository=source,
        audit=InMemoryAuditLogger(),
    )
    user = UserContext(tenant_id="tenant-review", user_id="editor", role_ids={"office-editor"})
    saved = docs.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Private title",
            document=text_document(),
            mutation_reference="document-create",
            human_confirmation=True,
        ),
    )
    user.readable_object_ids.add(saved.document.object_id)
    service = build_office_review_service(document_service=docs, audit=InMemoryAuditLogger())
    assert isinstance(service.repository, InMemoryOfficeReviewRepository)
    return ReviewHarness(
        service, docs, service.repository, source, user, saved.document.object_id, saved.version.version_id
    )


def event_command(operation: str, revision: int, reference: str, body: str | None = None) -> ReviewEventCommand:
    return ReviewEventCommand.model_validate(
        {
            "operation": operation,
            "expected_revision": revision,
            "body": body,
            "mutation_reference": reference,
            "human_confirmation": True,
        }
    )


def test_review_lifecycle_is_durable_source_backed_without_document_versions(reviews: ReviewHarness) -> None:
    created = reviews.create(anchor={"from": 2, "to": 4})
    assert created.quote == "😀" and created.applied_revision == 1
    thread_id = created.thread.thread_id
    for revision, operation in enumerate(("reply", "resolve", "reopen"), start=1):
        changed = reviews.service.mutate(
            user_context=reviews.user,
            object_id=reviews.object_id,
            thread_id=thread_id,
            command=event_command(
                operation, revision, operation, "Reply <script>literal</script>" if operation == "reply" else None
            ),
            write_enabled=True,
        )
        assert changed.applied_revision == revision + 1
    detail = reviews.service.detail(
        user_context=reviews.user, object_id=reviews.object_id, thread_id=thread_id, write_enabled=True
    )
    assert [event.operation for event in detail.events] == ["create", "reply", "resolve", "reopen"]
    assert detail.thread.status == "open" and detail.quote == "😀" and detail.can_comment
    assert len(reviews.documents.history(user_context=reviews.user, object_id=reviews.object_id).versions) == 1
    assert len(reviews.repository.documents.receipt_store.list_receipts(tenant_id=reviews.user.tenant_id)) == 5
    audit = canonical_json([event.model_dump(mode="json") for event in reviews.service.audit.events])
    assert "PRIVATE COMMENT" not in audit and "Reply <script>" not in audit and "😀" not in audit
    assert all(event.metadata["surface"] == "api" for event in reviews.service.audit.events)


def test_review_replay_is_actor_bound_and_requires_current_acl_and_confirmation(reviews: ReviewHarness) -> None:
    created = reviews.create()
    reviews.service.mutate(
        user_context=reviews.user,
        object_id=reviews.object_id,
        thread_id=created.thread.thread_id,
        command=event_command("resolve", 1, "resolve"),
        write_enabled=True,
    )
    replay = reviews.create()
    assert replay.replayed and replay.applied_revision == 1 and replay.thread.revision == 1
    assert replay.event.event_id == created.event.event_id
    with pytest.raises(OfficeDocumentConflictError):
        reviews.service.mutate(
            user_context=reviews.user,
            object_id=reviews.object_id,
            command=reviews.command(body="different"),
            write_enabled=True,
        )
    with pytest.raises(ValidationError):
        reviews.service.mutate(
            user_context=reviews.user,
            object_id=reviews.object_id,
            command=reviews.command().model_copy(update={"human_confirmation": False}),
            write_enabled=True,
        )
    reviews.repository.documents.grants[(reviews.user.tenant_id, reviews.object_id, reviews.user.user_id)] = "read"
    with pytest.raises(OfficeDocumentPermissionError):
        reviews.create()
    reviews.repository.documents.grants.clear()
    with pytest.raises(OfficeDocumentNotFoundError):
        reviews.create()


def test_review_historical_discussion_survives_new_document_save(reviews: ReviewHarness) -> None:
    thread = reviews.create().thread
    reviews.documents.save(
        user_context=reviews.user,
        object_id=reviews.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="New title",
            document=text_document("New contents"),
            mutation_reference="document-save",
            human_confirmation=True,
            expected_current_version_id=reviews.version_id,
        ),
    )
    listed = reviews.service.list_threads(
        user_context=reviews.user, object_id=reviews.object_id, anchor_version_id=reviews.version_id, write_enabled=True
    )
    assert not listed.can_create and listed.can_comment and listed.threads[0].anchor_version_id == reviews.version_id
    changed = reviews.service.mutate(
        user_context=reviews.user,
        object_id=reviews.object_id,
        thread_id=thread.thread_id,
        command=event_command("reply", 1, "old-version-reply", "Still relevant"),
        write_enabled=True,
    )
    assert changed.thread.anchor_version_id == reviews.version_id
    with pytest.raises(OfficeDocumentConflictError):
        reviews.create("stale-new-thread")
    with pytest.raises(OfficeDocumentNotFoundError):
        reviews.service.list_threads(
            user_context=reviews.user, object_id=reviews.object_id, anchor_version_id="missing"
        )


def test_review_denies_before_reading_storage_and_read_does_not_grant_write(
    reviews: ReviewHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = reviews.create().thread
    read = Mock(wraps=reviews.sources.get)
    monkeypatch.setattr(reviews.sources, "get", read)
    foreign = reviews.user.model_copy(update={"tenant_id": "tenant-foreign"})
    with pytest.raises(OfficeDocumentNotFoundError):
        reviews.service.detail(user_context=foreign, object_id=reviews.object_id, thread_id=thread.thread_id)
    read.assert_not_called()
    reviews.repository.documents.grants[(reviews.user.tenant_id, reviews.object_id, reviews.user.user_id)] = "read"
    detail = reviews.service.detail(
        user_context=reviews.user, object_id=reviews.object_id, thread_id=thread.thread_id, write_enabled=True
    )
    assert not detail.can_comment and not detail.can_resolve and detail.events[0].body == "PRIVATE COMMENT"
    with pytest.raises(OfficeDocumentPermissionError):
        reviews.service.mutate(
            user_context=reviews.user,
            object_id=reviews.object_id,
            thread_id=thread.thread_id,
            command=event_command("resolve", 1, "denied-resolve"),
            write_enabled=True,
        )


def test_review_pagination_is_complete_and_state_cas_is_independent(reviews: ReviewHarness) -> None:
    thread = reviews.create().thread
    reviews.create("second-thread")
    first = reviews.service.list_threads(user_context=reviews.user, object_id=reviews.object_id, limit=1)
    second = reviews.service.list_threads(
        user_context=reviews.user, object_id=reviews.object_id, limit=1, after=first.next_cursor
    )
    assert first.next_cursor and not second.next_cursor and first.threads[0].thread_id != second.threads[0].thread_id
    reviews.service.mutate(
        user_context=reviews.user,
        object_id=reviews.object_id,
        thread_id=thread.thread_id,
        command=event_command("reply", 1, "reply", "another"),
        write_enabled=True,
    )
    with pytest.raises(OfficeDocumentConflictError):
        reviews.service.mutate(
            user_context=reviews.user,
            object_id=reviews.object_id,
            thread_id=thread.thread_id,
            command=event_command("resolve", 1, "stale"),
            write_enabled=True,
        )
    page = reviews.service.detail(
        user_context=reviews.user, object_id=reviews.object_id, thread_id=thread.thread_id, limit=1
    )
    assert page.next_after_revision == 1
    last = reviews.service.detail(
        user_context=reviews.user, object_id=reviews.object_id, thread_id=thread.thread_id, after_revision=1, limit=1
    )
    assert last.next_after_revision is None and last.events[0].revision == 2


@pytest.mark.parametrize("anchor", [{"from": 2, "to": 3}, {"from": 3, "to": 4}, {"from": 1, "to": 99}])
def test_anchor_rejects_split_surrogate_or_outside_saved_content(
    anchor: dict[str, int], reviews: ReviewHarness
) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        reviews.create(anchor=anchor)
    assert not reviews.repository.events


def test_anchor_spans_marks_but_never_hard_break_or_paragraphs() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Ca", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": "fé"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "other"},
                ],
            },
            text_document("last")["content"][0],
        ],
    }
    assert derive_review_quote(doc, ReviewAnchor.model_validate({"from": 1, "to": 5})) == "Café"
    for start, end in ((1, 7), (6, 14)):
        with pytest.raises(OfficeDocumentInvalidContentError):
            derive_review_quote(doc, ReviewAnchor.model_validate({"from": start, "to": end}))


def test_anchor_nested_table_positions_and_boundaries() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [text_document("A😀")["content"][0]]},
                            {"type": "tableCell", "content": [text_document("B")["content"][0]]},
                        ],
                    }
                ],
            }
        ],
    }
    assert derive_review_quote(doc, ReviewAnchor.model_validate({"from": 5, "to": 7})) == "😀"
    with pytest.raises(OfficeDocumentInvalidContentError):
        derive_review_quote(doc, ReviewAnchor.model_validate({"from": 4, "to": 12}))


@pytest.mark.parametrize("body", [" ", "x" * 4001, "NUL\x00", "unpaired\ud800"])
def test_review_body_validation_is_bounded(body: str, reviews: ReviewHarness) -> None:
    with pytest.raises(ValidationError):
        reviews.command(body=body)


def test_maximum_unicode_body_and_quote_fit_canonical_resource_bound(reviews: ReviewHarness) -> None:
    saved = reviews.documents.save(
        user_context=reviews.user,
        object_id=reviews.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Unicode",
            document=text_document("😀" * 2000),
            mutation_reference="unicode-save",
            human_confirmation=True,
            expected_current_version_id=reviews.version_id,
        ),
    )
    reviews.version_id = saved.version.version_id
    created = reviews.service.mutate(
        user_context=reviews.user,
        object_id=reviews.object_id,
        command=reviews.command(body="😀" * 4000, anchor={"from": 1, "to": 4001}),
        write_enabled=True,
    )
    assert created.quote == "😀" * 2000 and created.event.body == "😀" * 4000
    event = reviews.repository.events[(reviews.user.tenant_id, created.event.event_id)]
    assert 72000 < event.content_byte_length <= 80000


def test_storage_outage_and_corrupt_content_fail_closed(
    reviews: ReviewHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = reviews.create()
    original_get = reviews.sources.get
    monkeypatch.setattr(reviews.sources, "get", Mock(side_effect=SourceObjectStorageError("private storage URL")))
    with pytest.raises(SourceObjectStorageError):
        reviews.service.detail(
            user_context=reviews.user, object_id=reviews.object_id, thread_id=created.thread.thread_id
        )
    record = original_get(
        tenant_id=reviews.user.tenant_id, object_id=created.thread.thread_id, version_id=created.event.event_id
    )
    bad = SourceObjectRecord.model_construct(metadata=record.metadata, content_bytes=b"wrong")
    monkeypatch.setattr(reviews.sources, "get", Mock(return_value=bad))
    with pytest.raises(OfficeDocumentInvalidContentError):
        reviews.service.detail(
            user_context=reviews.user, object_id=reviews.object_id, thread_id=created.thread.thread_id
        )


def test_write_feature_and_durable_factory_gate_precede_mutation(
    reviews: ReviewHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = Mock(wraps=reviews.repository.commit)
    monkeypatch.setattr(reviews.repository, "commit", commit)
    with pytest.raises(OfficeDocumentPermissionError):
        reviews.service.mutate(user_context=reviews.user, object_id=reviews.object_id, command=reviews.command())
    reviews.service.writes_available = False
    listing = reviews.service.list_threads(user_context=reviews.user, object_id=reviews.object_id, write_enabled=True)
    assert not listing.can_create and not listing.can_comment
    with pytest.raises(OfficeDocumentPermissionError):
        reviews.create()
    commit.assert_not_called()
