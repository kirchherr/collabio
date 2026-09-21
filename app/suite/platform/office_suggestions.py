"""Exact-version text suggestions and terminal decisions for native Office."""

from __future__ import annotations

import copy
import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import validate_office_document
from suite.platform.office_documents import (
    OFFICE_DOCUMENTS_MODULE_ID,
    OfficeDocumentContentResponse,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
    OfficeDocumentService,
    OfficeDocumentVersion,
)
from suite.platform.office_reviews import ReviewAnchor, ReviewMutation, derive_review_quote
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import (
    SourceObjectMetadataRepository,
    SourceObjectRepository,
    SourceObjectWriteGuard,
    build_source_object_manifest_hash,
    sha256_bytes,
    source_object_content_bytes,
)

SUGGESTION_SCHEMA = "collabio_office_suggestion_event.v1"
SUGGESTION_MIME = "application/vnd.collabio.suggestion-event+json"
SUGGESTION_SOURCE_SYSTEM = "collabio_office_native_suggestion"
MAX_SUGGESTION_BYTES = 80000


def validate_replacement(value: str) -> str:
    if len(value) > 4000 or any(
        (ord(char) < 32 and char not in "\n\t") or 0xD800 <= ord(char) <= 0xDFFF for char in value
    ):
        raise OfficeDocumentInvalidContentError("Suggestion text is invalid")
    return value


class SuggestionCreateCommand(ReviewMutation):
    anchor_version_id: str = Field(min_length=1, max_length=128)
    expected_current_version_id: str = Field(min_length=1, max_length=128)
    anchor: ReviewAnchor
    replacement_text: str = Field(max_length=4000)

    @field_validator("replacement_text")
    @classmethod
    def valid_replacement(cls, value: str) -> str:
        return validate_replacement(value)


class SuggestionDecisionCommand(ReviewMutation):
    operation: Literal["accept", "reject"]
    expected_revision: Literal[1]
    expected_current_version_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("expected_revision", mode="before")
    @classmethod
    def strict_revision(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("Suggestion revision is invalid")
        return value

    @model_validator(mode="after")
    def head_matches_operation(self) -> SuggestionDecisionCommand:
        if type(self.expected_revision) is not int or (
            (self.operation == "accept") != (self.expected_current_version_id is not None)
        ):
            raise ValueError("Suggestion decision is invalid")
        return self


class SuggestionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    object_id: str
    suggestion_id: str
    source_version_id: str
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


class TextSuggestionRecord(SuggestionEvidence):
    anchor_version_id: str
    anchor_content_hash: str
    anchor_from: int
    anchor_to: int

    def anchor(self) -> ReviewAnchor:
        return ReviewAnchor.model_validate({"from": self.anchor_from, "to": self.anchor_to})


class SuggestionDecisionRecord(SuggestionEvidence):
    decision_id: str
    operation: Literal["accept", "reject"]
    result_version_id: str | None
    result_content_hash: str | None


class SuggestionView(BaseModel):
    suggestion_id: str
    anchor_version_id: str
    anchor: ReviewAnchor
    revision: Literal[1, 2]
    status: Literal["open", "accepted", "rejected"]
    created_by: str
    created_at_utc: str
    can_accept: bool
    can_reject: bool
    result_version_id: str | None


class SuggestionDecisionView(BaseModel):
    decision_id: str
    operation: Literal["accept", "reject"]
    created_by: str
    created_at_utc: str
    result_version_id: str | None


class SuggestionResponse(BaseModel):
    tenant_id: str
    object_id: str
    current_version_id: str
    audit_event_id: str
    rag_indexing_allowed: bool = False
    search_indexing_allowed: bool = False


class SuggestionListResponse(SuggestionResponse):
    suggestions: list[SuggestionView]
    can_create: bool
    next_cursor: str | None


class SuggestionDetailResponse(SuggestionResponse):
    suggestion: SuggestionView
    quote: str
    replacement_text: str
    decision: SuggestionDecisionView | None


class SuggestionMutationResponse(SuggestionDetailResponse):
    applied_revision: Literal[1, 2]
    replayed: bool
    document_result: OfficeDocumentContentResponse | None


class SuggestionSnapshot(BaseModel):
    document: OfficeDocumentRecord
    suggestion: TextSuggestionRecord
    decision: SuggestionDecisionRecord | None = None
    can_write: bool = False
    payload: dict[str, Any] | None = None
    result_version: OfficeDocumentVersion | None = None
    result_content: dict[str, Any] | None = None
    replayed: bool = False


class SuggestionListSnapshot(BaseModel):
    document: OfficeDocumentRecord
    entries: tuple[SuggestionSnapshot, ...]
    can_write: bool
    has_more: bool


class OfficeSuggestionRepository(Protocol):
    def list_suggestions(
        self, *, user: UserContext, object_id: str, after: str | None, limit: int, anchor_version_id: str | None
    ) -> SuggestionListSnapshot: ...

    def detail(self, *, user: UserContext, object_id: str, suggestion_id: str) -> SuggestionSnapshot: ...

    def commit(
        self, *, user: UserContext, object_id: str, suggestion_id: str | None,
        command: SuggestionCreateCommand | SuggestionDecisionCommand,
    ) -> SuggestionSnapshot: ...


def suggestion_command_hash(
    user: UserContext, object_id: str, suggestion_id: str | None,
    command: SuggestionCreateCommand | SuggestionDecisionCommand,
) -> str:
    return stable_hash(canonical_json({
        "tenant_id": user.tenant_id, "actor": user.user_id, "object_id": object_id,
        "suggestion_id": suggestion_id, "command": command.model_dump(mode="json", by_alias=True),
        "schema_version": SUGGESTION_SCHEMA,
    }))


def replace_suggestion_text(document: dict[str, Any], anchor: ReviewAnchor, replacement: str) -> dict[str, Any]:
    """Replace one validated inline run, retaining untouched nodes and start marks."""
    validate_replacement(replacement)
    quote = derive_review_quote(document, anchor)
    if quote == replacement:
        raise OfficeDocumentInvalidContentError("Suggestion must change the selected text")
    result = copy.deepcopy(document)
    inserted = False

    def visit(node: dict[str, Any], position: int) -> int:
        nonlocal inserted
        kind = node["type"]
        if kind == "text":
            return len(node["text"].encode("utf-16-le")) // 2
        children = node.get("content", [])
        if not children:
            return 1 if kind in {"hardBreak", "horizontalRule"} else 2
        offset = position + (0 if kind == "doc" else 1)
        updated: list[dict[str, Any]] = []
        for child in children:
            size = visit(child, offset)
            if child["type"] == "text" and offset < anchor.to and offset + size > anchor.from_:
                encoded = child["text"].encode("utf-16-le")
                start, end = max(0, anchor.from_ - offset), min(size, anchor.to - offset)
                before, after = encoded[:start * 2].decode("utf-16-le"), encoded[end * 2:].decode("utf-16-le")
                if before:
                    updated.append({**child, "text": before})
                if not inserted:
                    if replacement:
                        updated.append({**child, "text": replacement})
                    inserted = True
                if after:
                    updated.append({**child, "text": after})
            else:
                updated.append(child)
            offset += size
        node["content"] = updated
        return offset - position + (0 if kind == "doc" else 1)

    visit(result, 0)
    if not inserted:
        raise OfficeDocumentInvalidContentError("Suggestion anchor is invalid")
    return validate_office_document(result)


def read_suggestion_payload(
    sources: SourceObjectRepository, document: OfficeDocumentRecord,
    suggestion: TextSuggestionRecord, evidence: SuggestionEvidence,
) -> dict[str, Any]:
    if not isinstance(sources, SourceObjectMetadataRepository):
        raise OfficeDocumentInvalidContentError("Suggestion metadata unavailable")
    try:
        metadata = sources.get_metadata(
            tenant_id=suggestion.tenant_id, object_id=suggestion.suggestion_id, version_id=evidence.source_version_id
        )
        expected = {
            "tenant_id": document.tenant_id, "object_id": suggestion.suggestion_id,
            "version_id": evidence.source_version_id, "object_type": "comment",
            "parent_object_id": document.object_id, "thread_id": suggestion.suggestion_id,
            "source_system": SUGGESTION_SOURCE_SYSTEM, "schema_version": SUGGESTION_SCHEMA,
            "mime_type": SUGGESTION_MIME, "lifecycle_state": "saved_version", "classification": "internal",
            "retention_policy_id": "rp-standard", "legal_hold_state": "none",
            "kms_key_ref": f"kms://{document.tenant_id}/internal/v1", "parser_profile_id": None,
            "owner_principal_id": document.owner_principal_id, "created_by": evidence.created_by,
            "title": "Office text suggestion", "created_at_utc": evidence.created_at_utc,
            "updated_at_utc": evidence.created_at_utc, "audit_chain_ref": evidence.audit_chain_ref,
            "content_hash": evidence.content_hash, "manifest_hash": evidence.source_manifest_hash,
            "content_byte_length": evidence.content_byte_length, "acl_hash": evidence.acl_hash,
            "acl_version": evidence.acl_version,
        }
        values = metadata.model_dump(mode="json")
        if (
            suggestion.tenant_id != document.tenant_id or suggestion.object_id != document.object_id
            or evidence.tenant_id != suggestion.tenant_id or evidence.object_id != suggestion.object_id
            or evidence.suggestion_id != suggestion.suggestion_id
            or not 0 < evidence.content_byte_length <= MAX_SUGGESTION_BYTES
            or any(values[key] != value for key, value in expected.items())
            or build_source_object_manifest_hash(metadata) != evidence.source_manifest_hash
        ):
            raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        source = sources.get(
            tenant_id=suggestion.tenant_id, object_id=suggestion.suggestion_id, version_id=evidence.source_version_id
        )
        if source.metadata != metadata:
            raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        SourceObjectWriteGuard().validate_before_write(source)
        content = source_object_content_bytes(source)
        if len(content) != evidence.content_byte_length or sha256_bytes(content) != evidence.content_hash:
            raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        payload = json.loads(content.decode("utf-8"))
        decision = evidence if isinstance(evidence, SuggestionDecisionRecord) else None
        bindings = {
            "schema_version": SUGGESTION_SCHEMA, "suggestion_id": suggestion.suggestion_id,
            "document_id": document.object_id, "anchor_version_id": suggestion.anchor_version_id,
            "anchor_content_hash": suggestion.anchor_content_hash, "anchor": suggestion.anchor().model_dump(by_alias=True),
            "operation": decision.operation if decision else "create",
            "result_version_id": decision.result_version_id if decision else None,
            "result_content_hash": decision.result_content_hash if decision else None,
        }
        if (
            not isinstance(payload, dict) or set(payload) != set(bindings) | {"quote", "replacement_text"}
            or any(payload[key] != value for key, value in bindings.items())
            or not isinstance(payload["quote"], str) or not 0 < len(payload["quote"]) <= 2000
            or not isinstance(payload["replacement_text"], str)
            or payload["quote"] == payload["replacement_text"]
        ):
            raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        validate_replacement(payload["replacement_text"])
        if canonical_json(payload).encode("utf-8") != content:
            raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        return payload
    except SourceObjectStorageError:
        raise
    except KeyError as exc:
        raise OfficeDocumentNotFoundError("Document not found") from exc
    except (UnicodeError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise OfficeDocumentInvalidContentError("Suggestion source is invalid") from exc


class OfficeSuggestionService:
    def __init__(
        self, *, repository: OfficeSuggestionRepository, document_service: OfficeDocumentService,
        audit: InMemoryAuditLogger,
    ) -> None:
        self.repository, self.documents, self.audit = repository, document_service, audit

    def _audit(self, user: UserContext, action: str, object_id: str, **metadata: Any) -> str:
        return self.audit.record(
            user_context=user, event_type=f"office.suggestions.{action}", source_object_ids=[object_id],
            metadata={"module_id": OFFICE_DOCUMENTS_MODULE_ID, "surface": "api", **metadata,
                      "rag_indexing_allowed": False, "search_indexing_allowed": False},
        ).event_id

    @staticmethod
    def _view(snapshot: SuggestionSnapshot, enabled: bool) -> SuggestionView:
        suggestion, decision = snapshot.suggestion, snapshot.decision
        writable = enabled and snapshot.can_write and decision is None
        return SuggestionView(
            suggestion_id=suggestion.suggestion_id, anchor_version_id=suggestion.anchor_version_id,
            anchor=suggestion.anchor(), revision=2 if decision else 1,
            status="accepted" if decision and decision.operation == "accept" else "rejected" if decision else "open",
            created_by=suggestion.created_by, created_at_utc=suggestion.created_at_utc,
            can_accept=writable and snapshot.document.current_version_id == suggestion.anchor_version_id,
            can_reject=writable, result_version_id=decision.result_version_id if decision else None,
        )

    def list_suggestions(
        self, *, user_context: UserContext, object_id: str, after: str | None = None, limit: int = 20,
        anchor_version_id: str | None = None, write_enabled: bool = False,
    ) -> SuggestionListResponse:
        if not 1 <= limit <= 50:
            raise OfficeDocumentInvalidContentError("Suggestion page is invalid")
        result = self.repository.list_suggestions(
            user=user_context, object_id=object_id, after=after, limit=limit, anchor_version_id=anchor_version_id
        )
        enabled = write_enabled and self.documents.writes_available
        return SuggestionListResponse(
            tenant_id=user_context.tenant_id, object_id=object_id,
            current_version_id=result.document.current_version_id,
            suggestions=[self._view(entry, enabled) for entry in result.entries],
            can_create=enabled and result.can_write and (
                anchor_version_id is None or anchor_version_id == result.document.current_version_id
            ),
            next_cursor=result.entries[-1].suggestion.suggestion_id if result.has_more else None,
            audit_event_id=self._audit(user_context, "list", object_id, count=len(result.entries)),
        )

    def _detail_response(
        self, snapshot: SuggestionSnapshot, enabled: bool, audit_event_id: str,
    ) -> SuggestionDetailResponse:
        payload = snapshot.payload or read_suggestion_payload(
            self.documents.source_repository, snapshot.document, snapshot.suggestion, snapshot.suggestion
        )
        if snapshot.decision:
            decision_payload = read_suggestion_payload(
                self.documents.source_repository, snapshot.document, snapshot.suggestion, snapshot.decision
            ) if snapshot.payload is None else snapshot.payload
            if any(decision_payload[key] != payload[key] for key in ("quote", "replacement_text")):
                raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
        return SuggestionDetailResponse(
            tenant_id=snapshot.document.tenant_id, object_id=snapshot.document.object_id,
            current_version_id=snapshot.document.current_version_id, suggestion=self._view(snapshot, enabled),
            quote=payload["quote"], replacement_text=payload["replacement_text"],
            decision=SuggestionDecisionView.model_validate(snapshot.decision.model_dump()) if snapshot.decision else None,
            audit_event_id=audit_event_id,
        )

    def detail(
        self, *, user_context: UserContext, object_id: str, suggestion_id: str, write_enabled: bool = False,
    ) -> SuggestionDetailResponse:
        snapshot = self.repository.detail(user=user_context, object_id=object_id, suggestion_id=suggestion_id)
        return self._detail_response(
            snapshot, write_enabled and self.documents.writes_available,
            self._audit(user_context, "read", object_id, suggestion_id=suggestion_id),
        )

    def mutate(
        self, *, user_context: UserContext, object_id: str,
        command: SuggestionCreateCommand | SuggestionDecisionCommand,
        suggestion_id: str | None = None, write_enabled: bool = False,
    ) -> SuggestionMutationResponse:
        if not write_enabled or not self.documents.writes_available:
            raise OfficeDocumentPermissionError("Suggestion writes are unavailable")
        command = type(command).model_validate(command.model_dump(mode="python", by_alias=True))
        result = self.repository.commit(
            user=user_context, object_id=object_id, suggestion_id=suggestion_id, command=command
        )
        event_id = self._audit(
            user_context, "changed", object_id, suggestion_id=result.suggestion.suggestion_id,
            decision_id=result.decision.decision_id if result.decision else None,
            result_version_id=result.result_version.version_id if result.result_version else None,
            replayed=result.replayed,
        )
        response = self._detail_response(result, True, event_id)
        saved = self.documents._content_response(
            result.document, result.result_version, result.result_content, True, event_id, replayed=result.replayed
        ) if result.result_version is not None and result.result_content is not None else None
        return SuggestionMutationResponse(
            **response.model_dump(), applied_revision=2 if result.decision else 1,
            replayed=result.replayed, document_result=saved,
        )
