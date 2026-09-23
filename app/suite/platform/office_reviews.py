"""Version-bound native Office discussions; content never enters audit metadata."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import (
    OFFICE_DOCUMENTS_MODULE_ID,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectMetadataRepository,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteGuard,
    build_source_object_manifest_hash,
    sha256_bytes,
    source_object_content_bytes,
)

REVIEW_SCHEMA = "collabio_office_review_event.v1"
REVIEW_MIME = "application/vnd.collabio.review-event+json"
REVIEW_SOURCE_SYSTEM = "collabio_office_native_review"
MAX_REVIEW_BYTES = 80000
ReviewOperation = Literal["create", "reply", "resolve", "reopen"]
ReviewStatus = Literal["open", "resolved"]


class ReviewAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_: int = Field(alias="from", strict=True, ge=1, le=220000)
    to: int = Field(strict=True, ge=2, le=220000)

    @model_validator(mode="after")
    def ordered(self) -> ReviewAnchor:
        if self.to <= self.from_:
            raise ValueError("Review anchor is invalid")
        return self


def _review_text(value: str) -> str:
    if (
        not value.strip()
        or len(value) > 4000
        or any(
            (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        )
    ):
        raise ValueError("Review text is invalid")
    return value


class ReviewMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutation_reference: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    human_confirmation: bool = Field(strict=True)

    @model_validator(mode="after")
    def confirmed(self) -> ReviewMutation:
        if not self.human_confirmation:
            raise ValueError("Review changes require explicit confirmation")
        return self


class ReviewCreateCommand(ReviewMutation):
    anchor_version_id: str = Field(min_length=1, max_length=128)
    expected_current_version_id: str = Field(min_length=1, max_length=128)
    anchor: ReviewAnchor | None = None
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def valid_body(cls, value: str) -> str:
        return _review_text(value)


class ReviewEventCommand(ReviewMutation):
    operation: Literal["reply", "resolve", "reopen"]
    expected_revision: int = Field(strict=True, ge=1, le=2147483646)
    body: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def body_matches_operation(self) -> ReviewEventCommand:
        if self.operation == "reply":
            if self.body is None:
                raise ValueError("Reply text is required")
            _review_text(self.body)
        elif self.body is not None:
            raise ValueError("Status changes do not accept text")
        return self


class ReviewThreadRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    object_id: str
    thread_id: str
    anchor_version_id: str
    anchor_content_hash: str
    anchor_from: int | None
    anchor_to: int | None
    revision: int
    current_event_id: str
    status: ReviewStatus
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    audit_chain_ref: str

    def anchor(self) -> ReviewAnchor | None:
        return (
            ReviewAnchor.model_validate({"from": self.anchor_from, "to": self.anchor_to})
            if self.anchor_from is not None
            else None
        )


class ReviewEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    object_id: str
    thread_id: str
    event_id: str
    revision: int
    previous_event_id: str | None
    operation: ReviewOperation
    status_after: ReviewStatus
    created_by: str
    created_at_utc: str
    content_hash: str
    source_manifest_hash: str
    source_write_receipt_hash: str
    content_byte_length: int
    acl_hash: str
    acl_version: int
    mutation_reference: str
    command_hash: str
    audit_chain_ref: str


class ReviewThreadView(BaseModel):
    thread_id: str
    anchor_version_id: str
    anchor: ReviewAnchor | None
    revision: int
    status: ReviewStatus
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    can_comment: bool
    can_resolve: bool


class ReviewEventView(BaseModel):
    event_id: str
    revision: int
    operation: ReviewOperation
    body: str | None
    created_by: str
    created_at_utc: str


class ReviewResponse(BaseModel):
    tenant_id: str
    object_id: str
    audit_event_id: str
    rag_indexing_allowed: bool = False
    search_indexing_allowed: bool = False


class ReviewListResponse(ReviewResponse):
    current_version_id: str
    threads: list[ReviewThreadView]
    can_create: bool
    can_comment: bool
    can_resolve: bool
    next_cursor: str | None


class ReviewDetailResponse(ReviewResponse):
    current_version_id: str
    thread: ReviewThreadView
    quote: str | None
    events: list[ReviewEventView]
    next_after_revision: int | None
    can_comment: bool
    can_resolve: bool


class ReviewMutationResponse(ReviewResponse):
    thread: ReviewThreadView
    event: ReviewEventView
    quote: str | None
    applied_revision: int
    replayed: bool


class ReviewListSnapshot(BaseModel):
    document: OfficeDocumentRecord
    threads: tuple[ReviewThreadRecord, ...]
    can_write: bool
    has_more: bool


class ReviewDetailSnapshot(BaseModel):
    document: OfficeDocumentRecord
    thread: ReviewThreadRecord
    events: tuple[ReviewEventRecord, ...]
    latest: ReviewEventRecord
    can_write: bool
    has_more: bool


class ReviewCommit(BaseModel):
    document: OfficeDocumentRecord
    thread: ReviewThreadRecord
    event: ReviewEventRecord
    payload: dict[str, Any]
    replayed: bool = False


class OfficeReviewRepository(Protocol):
    def list_threads(
        self, *, user: UserContext, object_id: str, after: str | None, limit: int, anchor_version_id: str | None
    ) -> ReviewListSnapshot: ...
    def detail(
        self, *, user: UserContext, object_id: str, thread_id: str, after_revision: int, limit: int
    ) -> ReviewDetailSnapshot: ...
    def commit(
        self,
        *,
        user: UserContext,
        object_id: str,
        thread_id: str | None,
        command: ReviewCreateCommand | ReviewEventCommand,
    ) -> ReviewCommit: ...


def review_command_hash(user: UserContext, object_id: str, thread_id: str | None, command: ReviewMutation) -> str:
    return stable_hash(
        canonical_json(
            {
                "tenant_id": user.tenant_id,
                "actor": user.user_id,
                "object_id": object_id,
                "thread_id": thread_id,
                "command": command.model_dump(mode="json", by_alias=True),
                "schema_version": REVIEW_SCHEMA,
            }
        )
    )


def derive_review_quote(document: dict[str, Any], anchor: ReviewAnchor | None) -> str | None:
    """Project native positions without case folding or splitting a UTF-16 pair."""
    if anchor is None:
        return None
    runs: list[tuple[int, str]] = []

    def visit(node: dict[str, Any], position: int) -> int:
        kind = node["type"]
        if kind == "text":
            return len(node["text"].encode("utf-16-le")) // 2
        children = node.get("content", [])
        if not children:
            return 1 if kind in {"hardBreak", "horizontalRule", "image"} else 2
        offset = position + (0 if kind == "doc" else 1)
        if kind in {"paragraph", "heading", "codeBlock"}:
            start = offset
            parts: list[str] = []
            for child in children:
                if child["type"] == "text":
                    parts.append(child["text"])
                else:
                    if parts:
                        runs.append((start, "".join(parts)))
                    parts = []
                    start = offset + 1
                offset += visit(child, offset)
            if parts:
                runs.append((start, "".join(parts)))
        else:
            for child in children:
                offset += visit(child, offset)
        return offset - position + (0 if kind == "doc" else 1)

    visit(document, 0)
    for start, text in runs:
        encoded = text.encode("utf-16-le")
        if start <= anchor.from_ < anchor.to <= start + len(encoded) // 2:
            try:
                quote = encoded[2 * (anchor.from_ - start) : 2 * (anchor.to - start)].decode("utf-16-le")
            except UnicodeError as exc:
                raise OfficeDocumentInvalidContentError("Review anchor is invalid") from exc
            if not quote or len(quote) > 2000:
                raise OfficeDocumentInvalidContentError("Review anchor is invalid")
            return quote
    raise OfficeDocumentInvalidContentError("Review anchor is invalid")


def read_review_payload(
    source_repository: SourceObjectRepository,
    document: OfficeDocumentRecord,
    thread: ReviewThreadRecord,
    event: ReviewEventRecord,
) -> dict[str, Any]:
    if not isinstance(source_repository, SourceObjectMetadataRepository):
        raise OfficeDocumentInvalidContentError("Review metadata is unavailable")
    try:
        metadata = source_repository.get_metadata(
            tenant_id=thread.tenant_id, object_id=thread.thread_id, version_id=event.event_id
        )
        if (
            event.tenant_id != thread.tenant_id
            or event.object_id != thread.object_id
            or event.thread_id != thread.thread_id
            or document.tenant_id != thread.tenant_id
            or document.object_id != thread.object_id
            or metadata.tenant_id != thread.tenant_id
            or metadata.object_id != thread.thread_id
            or metadata.version_id != event.event_id
            or metadata.object_type != SourceObjectType.COMMENT
            or metadata.parent_object_id != thread.object_id
            or metadata.thread_id != thread.thread_id
            or metadata.source_system != REVIEW_SOURCE_SYSTEM
            or metadata.schema_version != REVIEW_SCHEMA
            or metadata.mime_type != REVIEW_MIME
            or metadata.lifecycle_state != SourceLifecycleState.SAVED_VERSION
            or metadata.classification.value != "internal"
            or metadata.retention_policy_id != "rp-standard"
            or metadata.legal_hold_state.value != "none"
            or metadata.kms_key_ref != f"kms://{thread.tenant_id}/internal/v1"
            or metadata.parser_profile_id is not None
            or metadata.owner_principal_id != document.owner_principal_id
            or metadata.created_by != event.created_by
            or metadata.title != "Office review event"
            or metadata.created_at_utc != event.created_at_utc
            or metadata.updated_at_utc != event.created_at_utc
            or metadata.audit_chain_ref != event.audit_chain_ref
            or metadata.content_hash != event.content_hash
            or metadata.manifest_hash != event.source_manifest_hash
            or metadata.content_byte_length != event.content_byte_length
            or not 0 < event.content_byte_length <= MAX_REVIEW_BYTES
            or metadata.acl_hash != event.acl_hash
            or metadata.acl_version != event.acl_version
            or build_source_object_manifest_hash(metadata) != event.source_manifest_hash
        ):
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        record = source_repository.get(
            tenant_id=thread.tenant_id, object_id=thread.thread_id, version_id=event.event_id
        )
        if record.metadata != metadata:
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        SourceObjectWriteGuard().validate_before_write(record)
        content = source_object_content_bytes(record)
        if len(content) != event.content_byte_length or sha256_bytes(content) != event.content_hash:
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        payload = json.loads(content.decode("utf-8"))
        anchor = thread.anchor()
        expected = {
            "schema_version": REVIEW_SCHEMA,
            "thread_id": thread.thread_id,
            "document_id": thread.object_id,
            "anchor_version_id": thread.anchor_version_id,
            "anchor_content_hash": thread.anchor_content_hash,
            "anchor": anchor.model_dump(by_alias=True) if anchor else None,
            "operation": event.operation,
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != set(expected) | {"body", "quote"}
            or any(payload[key] != value for key, value in expected.items())
        ):
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        quote = payload["quote"]
        if (anchor is None and quote is not None) or (
            anchor is not None and (not isinstance(quote, str) or not quote or len(quote) > 2000)
        ):
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        if event.operation in {"create", "reply"}:
            _review_text(payload["body"])
        elif payload["body"] is not None:
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        if canonical_json(payload).encode("utf-8") != content:
            raise OfficeDocumentInvalidContentError("Review source is invalid")
        return payload
    except SourceObjectStorageError:
        raise
    except KeyError as exc:
        raise OfficeDocumentNotFoundError("Document not found") from exc
    except (UnicodeError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise OfficeDocumentInvalidContentError("Review source is invalid") from exc


class OfficeReviewService:
    def __init__(
        self,
        *,
        repository: OfficeReviewRepository,
        source_repository: SourceObjectRepository,
        audit: InMemoryAuditLogger,
        writes_available: bool = True,
    ) -> None:
        self.repository, self.source_repository, self.audit = repository, source_repository, audit
        self.writes_available = writes_available

    def _audit(self, user: UserContext, action: str, object_id: str, **metadata: Any) -> str:
        return self.audit.record(
            user_context=user,
            event_type=f"office.reviews.{action}",
            source_object_ids=[object_id],
            metadata={
                "module_id": OFFICE_DOCUMENTS_MODULE_ID,
                "surface": "api",
                **metadata,
                "rag_indexing_allowed": False,
                "search_indexing_allowed": False,
            },
        ).event_id

    @staticmethod
    def _thread(thread: ReviewThreadRecord, writable: bool) -> ReviewThreadView:
        return ReviewThreadView(
            **thread.model_dump(
                include={
                    "thread_id",
                    "anchor_version_id",
                    "revision",
                    "status",
                    "created_by",
                    "created_at_utc",
                    "updated_at_utc",
                }
            ),
            anchor=thread.anchor(),
            can_comment=writable and thread.status == "open",
            can_resolve=writable,
        )

    @staticmethod
    def _event(event: ReviewEventRecord, payload: dict[str, Any]) -> ReviewEventView:
        return ReviewEventView(
            **event.model_dump(include={"event_id", "revision", "operation", "created_by", "created_at_utc"}),
            body=payload["body"],
        )

    def list_threads(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        after: str | None = None,
        limit: int = 20,
        anchor_version_id: str | None = None,
        write_enabled: bool = False,
    ) -> ReviewListResponse:
        if not 1 <= limit <= 50:
            raise OfficeDocumentInvalidContentError("Review page is invalid")
        result = self.repository.list_threads(
            user=user_context, object_id=object_id, after=after, limit=limit, anchor_version_id=anchor_version_id
        )
        writable = self.writes_available and write_enabled and result.can_write
        return ReviewListResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            current_version_id=result.document.current_version_id,
            threads=[self._thread(thread, writable) for thread in result.threads],
            can_create=writable
            and (anchor_version_id is None or anchor_version_id == result.document.current_version_id),
            can_comment=writable,
            can_resolve=writable,
            next_cursor=result.threads[-1].thread_id if result.has_more else None,
            audit_event_id=self._audit(user_context, "list", object_id, count=len(result.threads)),
        )

    def detail(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        thread_id: str,
        after_revision: int = 0,
        limit: int = 20,
        write_enabled: bool = False,
    ) -> ReviewDetailResponse:
        if not 1 <= limit <= 50 or after_revision < 0:
            raise OfficeDocumentInvalidContentError("Review page is invalid")
        result = self.repository.detail(
            user=user_context, object_id=object_id, thread_id=thread_id, after_revision=after_revision, limit=limit
        )
        writable = self.writes_available and write_enabled and result.can_write
        payloads = {
            event.event_id: read_review_payload(self.source_repository, result.document, result.thread, event)
            for event in (*result.events, result.latest)
        }
        return ReviewDetailResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            current_version_id=result.document.current_version_id,
            thread=self._thread(result.thread, writable),
            quote=payloads[result.latest.event_id]["quote"],
            events=[self._event(event, payloads[event.event_id]) for event in result.events],
            next_after_revision=result.events[-1].revision if result.has_more else None,
            can_comment=writable and result.thread.status == "open",
            can_resolve=writable,
            audit_event_id=self._audit(
                user_context,
                "read",
                object_id,
                thread_id=thread_id,
                revision=result.thread.revision,
                count=len(result.events),
            ),
        )

    def mutate(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: ReviewCreateCommand | ReviewEventCommand,
        thread_id: str | None = None,
        write_enabled: bool = False,
    ) -> ReviewMutationResponse:
        if not self.writes_available or not write_enabled:
            raise OfficeDocumentPermissionError("Review writing is not permitted")
        command = type(command).model_validate(command.model_dump(mode="python", by_alias=True))
        result = self.repository.commit(user=user_context, object_id=object_id, thread_id=thread_id, command=command)
        return ReviewMutationResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            thread=self._thread(result.thread, True),
            event=self._event(result.event, result.payload),
            quote=result.payload["quote"],
            applied_revision=result.event.revision,
            replayed=result.replayed,
            audit_event_id=self._audit(
                user_context,
                "changed",
                object_id,
                thread_id=result.thread.thread_id,
                revision=result.event.revision,
                operation=result.event.operation,
                command_hash=result.event.command_hash,
                source_write_receipt_hash=result.event.source_write_receipt_hash,
                replayed=result.replayed,
            ),
        )
