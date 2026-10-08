from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import (
    MAX_DOCUMENT_BYTES,
    OFFICE_DOCUMENT_MIME_TYPE,
    OFFICE_DOCUMENT_SCHEMA_VERSION,
    OfficeDocumentInvalidContentError,
    office_document_reference_counts,
    office_document_references,
    validate_office_document,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectMetadataRepository,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteGuard,
    build_source_object_manifest_hash,
    sha256_bytes,
    source_object_content_bytes,
)

OFFICE_DOCUMENTS_MODULE_ID = "office_documents"
OFFICE_DOCUMENTS_READ_FEATURE_ID = "office_documents.documents.read"
OFFICE_DOCUMENTS_WRITE_FEATURE_ID = "office_documents.documents.write"
OFFICE_DOCUMENT_OBJECT_TYPE = "office.document"
OFFICE_DOCUMENT_SOURCE_SYSTEM = "collabio_office_native"
OFFICE_BACKLINK_PAGE_MAX = 50
OFFICE_BACKLINK_SCAN_LIMIT = 50
OfficeInformationClassification = Literal["public", "internal", "confidential", "restricted"]
OfficeSharePermission = Literal["read", "write"]
OFFICE_INFORMATION_CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


class OfficeDocumentNotFoundError(KeyError):
    pass


class OfficeDocumentPermissionError(PermissionError):
    pass


class OfficeDocumentConflictError(ValueError):
    pass


class OfficeDocumentListRequestError(ValueError):
    pass


class OfficeDocumentHistoryRequestError(ValueError):
    pass


class OfficeDocumentShareRequestError(ValueError):
    pass


class OfficeDocumentSharePrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    display_name: str
    email: str | None = None


class OfficeDocumentShareEntry(OfficeDocumentSharePrincipal):
    permission: Literal["read", "write", "admin"]
    is_owner: bool = False
    expires_at_utc: str | None = None


class OfficeDocumentShareState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    acl_version: int = Field(ge=1)
    entries: list[OfficeDocumentShareEntry]
    available_principals: list[OfficeDocumentSharePrincipal]
    audit_event_id: str = ""


class OfficeDocumentShareCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]*$")
    permission: OfficeSharePermission
    expires_at_utc: datetime | None = None
    expected_acl_version: int = Field(ge=1)
    mutation_reference: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    human_confirmation: bool = Field(strict=True)

    @field_validator("expires_at_utc")
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Document share expiration requires a timezone")
        value = value.astimezone(UTC)
        now = datetime.now(UTC)
        if value <= now or value > now + timedelta(days=366):
            raise ValueError("Document share expiration must be within 366 days")
        return value

    @model_validator(mode="after")
    def require_confirmation(self) -> OfficeDocumentShareCommand:
        if not self.human_confirmation:
            raise ValueError("Changing a document share requires explicit confirmation")
        return self


class OfficeDocumentUnshareCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]*$")
    expected_acl_version: int = Field(ge=1)
    mutation_reference: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    human_confirmation: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_confirmation(self) -> OfficeDocumentUnshareCommand:
        if not self.human_confirmation:
            raise ValueError("Revoking a document share requires explicit confirmation")
        return self


def validate_office_document_query(query: str) -> str:
    if (
        not isinstance(query, str)
        or len(query) > 200
        or any(
            ord(character) < 32 or 0x7F <= ord(character) <= 0x9F or 0xD800 <= ord(character) <= 0xDFFF
            for character in query
        )
    ):
        raise OfficeDocumentListRequestError("Invalid document list request")
    return query.strip()


class OfficeDocumentCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    document: dict[str, Any]
    information_classification: OfficeInformationClassification = "internal"
    mutation_reference: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    human_confirmation: bool = Field(strict=True)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("Document title is invalid")
        return value

    @field_validator("document")
    @classmethod
    def validate_document(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_office_document(value)

    @model_validator(mode="after")
    def require_confirmation(self) -> OfficeDocumentCreateCommand:
        if not self.human_confirmation:
            raise ValueError("Saving a document requires explicit confirmation")
        return self


class OfficeDocumentSaveCommand(OfficeDocumentCreateCommand):
    expected_current_version_id: str = Field(min_length=1, max_length=128)


class OfficeDocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    title: str
    information_classification: OfficeInformationClassification = "internal"
    current_version_id: str
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    audit_chain_ref: str


class OfficeDocumentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    version_id: str
    previous_version_id: str | None
    title: str
    information_classification: OfficeInformationClassification = "internal"
    created_at_utc: str
    created_by: str
    content_hash: str
    source_manifest_hash: str
    source_write_receipt_hash: str
    content_byte_length: int
    acl_hash: str
    acl_version: int
    mutation_reference: str
    command_hash: str
    audit_chain_ref: str


class OfficeDocumentView(BaseModel):
    object_id: str
    title: str
    information_classification: OfficeInformationClassification
    current_version_id: str
    created_at_utc: str
    updated_at_utc: str
    can_write: bool
    can_share: bool = False


class OfficeDocumentVersionView(BaseModel):
    version_id: str
    previous_version_id: str | None
    title: str
    information_classification: OfficeInformationClassification
    created_at_utc: str
    created_by: str
    content_hash: str
    source_write_receipt_hash: str


class OfficeDocumentListResponse(BaseModel):
    tenant_id: str
    documents: list[OfficeDocumentView]
    can_create: bool
    audit_event_id: str
    next_cursor: str | None = None
    has_more: bool = False
    page_size: int = 200


class OfficeDocumentContentResponse(BaseModel):
    tenant_id: str
    document: OfficeDocumentView
    version: OfficeDocumentVersionView
    content: dict[str, Any]
    is_current_version: bool
    can_write: bool
    audit_event_id: str
    replayed: bool = False
    schema_version: str = OFFICE_DOCUMENT_SCHEMA_VERSION
    rag_indexing_allowed: bool = False
    search_indexing_allowed: bool = False


class OfficeDocumentOutboundReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_object_id: str
    target_version_id: str
    status: Literal["resolved", "unavailable"]
    title: str | None = None
    is_current_version: bool | None = None


class OfficeDocumentOutboundReferencesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    references: list[OfficeDocumentOutboundReference]
    audit_event_id: str
    content_included: bool = False


class OfficeDocumentBacklink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str
    source_version_id: str
    title: str
    reference_count: int = Field(ge=1, le=100)


class OfficeDocumentBacklinksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    target_object_id: str
    target_version_id: str
    backlinks: list[OfficeDocumentBacklink]
    audit_event_id: str
    next_cursor: str | None = None
    has_more: bool = False
    page_size: int = OFFICE_BACKLINK_PAGE_MAX
    content_included: bool = False


class OfficeDocumentHistoryResponse(BaseModel):
    tenant_id: str
    object_id: str
    versions: list[OfficeDocumentVersionView]
    audit_event_id: str
    history_head_version_id: str
    current_version_id: str
    next_cursor: str | None = None
    has_more: bool = False
    page_size: int = 200


class OfficeDocumentHistoryPage(BaseModel):
    history_head_version_id: str
    current_version_id: str
    versions: tuple[OfficeDocumentVersion, ...]


class OfficeDocumentCommit(BaseModel):
    document: OfficeDocumentRecord
    version: OfficeDocumentVersion
    replayed: bool = False
    content: dict[str, Any] | None = None


class OfficeDocumentRepository(Protocol):
    def list_documents(
        self,
        *,
        user_context: UserContext,
        query: str = "",
        after: tuple[str, str] | None = None,
        limit: int = 200,
    ) -> tuple[OfficeDocumentRecord, ...]: ...

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord: ...

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool: ...

    def can_admin(self, *, user_context: UserContext, object_id: str) -> bool: ...

    def share_state(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentShareState: ...

    def set_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentShareCommand
    ) -> OfficeDocumentShareState: ...

    def revoke_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentUnshareCommand
    ) -> OfficeDocumentShareState: ...

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]: ...

    def history_page(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        history_head_version_id: str | None = None,
        next_version_id: str | None = None,
        limit: int = 201,
    ) -> OfficeDocumentHistoryPage: ...

    def get_version(self, *, user_context: UserContext, object_id: str, version_id: str) -> OfficeDocumentVersion: ...

    def commit(
        self, *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand
    ) -> OfficeDocumentCommit: ...


def office_document_command_hash(
    *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand
) -> str:
    return stable_hash(
        canonical_json(
            {
                "tenant_id": user_context.tenant_id,
                "actor": user_context.user_id,
                "object_id": object_id,
                "command": command.model_dump(mode="json"),
                "schema_version": OFFICE_DOCUMENT_SCHEMA_VERSION,
            }
        )
    )


def can_create_office_document(user_context: UserContext) -> bool:
    return bool(user_context.role_ids & {"tenant-admin", "office-editor"})


def validate_office_classification_change(
    *,
    user_context: UserContext,
    current: OfficeInformationClassification | None,
    target: OfficeInformationClassification,
) -> None:
    """Keep protective upgrades easy while reserving publication and downgrades for tenant admins."""
    if "tenant-admin" in user_context.role_ids:
        return
    if current is None:
        if target == "public":
            raise OfficeDocumentPermissionError("Public document classification requires tenant administration")
        return
    if target == current:
        return
    if (
        target == "public"
        or OFFICE_INFORMATION_CLASSIFICATION_RANK[target] < OFFICE_INFORMATION_CLASSIFICATION_RANK[current]
    ):
        raise OfficeDocumentPermissionError("Lowering document classification requires tenant administration")


class OfficeDocumentService:
    def __init__(
        self,
        *,
        repository: OfficeDocumentRepository,
        source_repository: SourceObjectRepository,
        audit: InMemoryAuditLogger,
        writes_available: bool = True,
        list_cursor_key: bytes | None = None,
    ) -> None:
        self.repository = repository
        self.source_repository = source_repository
        self.audit = audit
        self.writes_available = writes_available
        # Navigation only: restarts invalidate cursors, and each page checks current ACLs.
        self._list_cursor_key = list_cursor_key if list_cursor_key is not None else secrets.token_bytes(32)
        if len(self._list_cursor_key) < 32:
            raise ValueError("Office list cursor key must contain at least 32 bytes")

    def _list_binding(self, user: UserContext, query: str, page_size: int) -> str:
        payload = canonical_json(
            {
                "tenant": user.tenant_id,
                "actor": user.user_id,
                "roles": sorted(user.role_ids),
                "query": query,
                "page_size": page_size,
            }
        ).encode("utf-8")
        return hmac.new(self._list_cursor_key, payload, sha256).hexdigest()

    def _read_list_cursor(self, cursor: str, binding: str) -> tuple[str, str]:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
                raise ValueError
            encoded, signature = cursor.split(".")
            payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") != encoded:
                raise ValueError
            expected = hmac.new(self._list_cursor_key, payload, sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {"binding", "created_at", "object_id"}:
                raise ValueError
            if not isinstance(value["binding"], str) or not hmac.compare_digest(value["binding"], binding):
                raise ValueError
            created_at, object_id = value["created_at"], value["object_id"]
            if not isinstance(created_at, str) or len(created_at) > 32 or not isinstance(object_id, str):
                raise ValueError
            if re.fullmatch(r"office-doc-[a-f0-9]{32}", object_id) is None:
                raise ValueError
            timestamp = datetime.fromisoformat(created_at)
            if timestamp.tzinfo is None or timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z") != created_at:
                raise ValueError
            return created_at, object_id
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise OfficeDocumentListRequestError("Invalid document list request") from exc

    def _write_list_cursor(self, record: OfficeDocumentRecord, binding: str) -> str:
        payload = canonical_json(
            {
                "binding": binding,
                "created_at": record.created_at_utc,
                "object_id": record.object_id,
            }
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return f"{encoded}.{hmac.new(self._list_cursor_key, payload, sha256).hexdigest()}"

    def list_documents(
        self,
        *,
        user_context: UserContext,
        write_enabled: bool = False,
        query: str = "",
        page_size: int = 200,
        cursor: str | None = None,
    ) -> OfficeDocumentListResponse:
        query = validate_office_document_query(query)
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise OfficeDocumentListRequestError("Invalid document list request")
        binding = self._list_binding(user_context, query, page_size)
        after = self._read_list_cursor(cursor, binding) if cursor is not None else None
        candidates = self.repository.list_documents(
            user_context=user_context, query=query, after=after, limit=page_size + 1
        )
        records = candidates[:page_size]
        has_more = len(candidates) > page_size
        event_id = self._audit(user_context, "office.documents.list", count=len(records), has_more=has_more)
        return OfficeDocumentListResponse(
            tenant_id=user_context.tenant_id,
            documents=[
                self._view(
                    record,
                    self.writes_available
                    and write_enabled
                    and self.repository.can_write(user_context=user_context, object_id=record.object_id),
                    self.writes_available
                    and write_enabled
                    and self.repository.can_admin(user_context=user_context, object_id=record.object_id),
                )
                for record in records
            ],
            can_create=self.writes_available and write_enabled and can_create_office_document(user_context),
            audit_event_id=event_id,
            next_cursor=self._write_list_cursor(records[-1], binding) if has_more else None,
            has_more=has_more,
            page_size=page_size,
        )

    def read_content(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        version_id: str | None = None,
        write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        document = self.repository.get_document(user_context=user_context, object_id=object_id)
        version = self.repository.get_version(
            user_context=user_context, object_id=object_id, version_id=version_id or document.current_version_id
        )
        content = self._read_content(document, version)
        can_write = (
            self.writes_available
            and write_enabled
            and self.repository.can_write(user_context=user_context, object_id=object_id)
        )
        can_share = (
            self.writes_available
            and write_enabled
            and self.repository.can_admin(user_context=user_context, object_id=object_id)
        )
        event_id = self._audit(
            user_context,
            "office.documents.read",
            object_id=object_id,
            version_id=version.version_id,
            content_hash=version.content_hash,
        )
        return self._content_response(document, version, content, can_write, event_id, can_share=can_share)

    def outbound_references(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        version_id: str | None = None,
    ) -> OfficeDocumentOutboundReferencesResponse:
        source = self.repository.get_document(user_context=user_context, object_id=object_id)
        source_version = self.repository.get_version(
            user_context=user_context, object_id=object_id, version_id=version_id or source.current_version_id
        )
        content = self._read_content(source, source_version)
        references: list[OfficeDocumentOutboundReference] = []
        for target_object_id, target_version_id in office_document_references(content):
            try:
                target = self.repository.get_document(user_context=user_context, object_id=target_object_id)
                target_version = self.repository.get_version(
                    user_context=user_context,
                    object_id=target_object_id,
                    version_id=target_version_id,
                )
            except (OfficeDocumentNotFoundError, OfficeDocumentPermissionError):
                references.append(
                    OfficeDocumentOutboundReference(
                        target_object_id=target_object_id,
                        target_version_id=target_version_id,
                        status="unavailable",
                    )
                )
            else:
                references.append(
                    OfficeDocumentOutboundReference(
                        target_object_id=target_object_id,
                        target_version_id=target_version_id,
                        status="resolved",
                        title=target_version.title,
                        is_current_version=target.current_version_id == target_version.version_id,
                    )
                )
        event_id = self._audit(
            user_context,
            "office.documents.outbound_references",
            object_id=object_id,
            version_id=source_version.version_id,
            reference_count=len(references),
            resolved_count=sum(reference.status == "resolved" for reference in references),
        )
        return OfficeDocumentOutboundReferencesResponse(
            tenant_id=user_context.tenant_id,
            source_object_id=object_id,
            source_version_id=source_version.version_id,
            references=references,
            audit_event_id=event_id,
        )

    def _backlink_binding(
        self,
        user: UserContext,
        target_object_id: str,
        target_version_id: str,
        page_size: int,
    ) -> str:
        payload = canonical_json(
            {
                "tenant": user.tenant_id,
                "actor": user.user_id,
                "roles": sorted(user.role_ids),
                "target_object_id": target_object_id,
                "target_version_id": target_version_id,
                "page_size": page_size,
            }
        ).encode("utf-8")
        return hmac.new(self._list_cursor_key, b"office-backlinks.v1:binding\0" + payload, sha256).hexdigest()

    def _read_backlink_cursor(self, cursor: str, binding: str) -> tuple[str, str]:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
                raise ValueError
            encoded, signature = cursor.split(".")
            payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") != encoded:
                raise ValueError
            expected = hmac.new(self._list_cursor_key, b"office-backlinks.v1:cursor\0" + payload, sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {"binding", "created_at", "object_id"}:
                raise ValueError
            if not isinstance(value["binding"], str) or not hmac.compare_digest(value["binding"], binding):
                raise ValueError
            created_at, object_id = value["created_at"], value["object_id"]
            if not isinstance(created_at, str) or len(created_at) > 32 or not isinstance(object_id, str):
                raise ValueError
            if re.fullmatch(r"office-doc-[a-f0-9]{32}", object_id) is None:
                raise ValueError
            timestamp = datetime.fromisoformat(created_at)
            if timestamp.tzinfo is None or timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z") != created_at:
                raise ValueError
            return created_at, object_id
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise OfficeDocumentListRequestError("Invalid document list request") from exc

    def _write_backlink_cursor(self, after: tuple[str, str], binding: str) -> str:
        payload = canonical_json({"binding": binding, "created_at": after[0], "object_id": after[1]}).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(self._list_cursor_key, b"office-backlinks.v1:cursor\0" + payload, sha256).hexdigest()
        return f"{encoded}.{signature}"

    def backlinks(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        version_id: str | None = None,
        page_size: int = OFFICE_BACKLINK_PAGE_MAX,
        cursor: str | None = None,
    ) -> OfficeDocumentBacklinksResponse:
        if type(page_size) is not int or not 1 <= page_size <= OFFICE_BACKLINK_PAGE_MAX:
            raise OfficeDocumentListRequestError("Invalid document list request")
        target = self.repository.get_document(user_context=user_context, object_id=object_id)
        target_version = self.repository.get_version(
            user_context=user_context,
            object_id=object_id,
            version_id=version_id or target.current_version_id,
        )
        binding = self._backlink_binding(user_context, object_id, target_version.version_id, page_size)
        after = self._read_backlink_cursor(cursor, binding) if cursor is not None else None
        candidates = self.repository.list_documents(
            user_context=user_context,
            query="",
            after=after,
            limit=OFFICE_BACKLINK_SCAN_LIMIT + 1,
        )
        scanned = candidates[:OFFICE_BACKLINK_SCAN_LIMIT]
        backlinks: list[OfficeDocumentBacklink] = []
        result_boundaries: list[tuple[str, str]] = []
        for candidate in scanned:
            if candidate.object_id == object_id:
                continue
            try:
                source = self.repository.get_document(
                    user_context=user_context,
                    object_id=candidate.object_id,
                )
                source_version = self.repository.get_version(
                    user_context=user_context,
                    object_id=source.object_id,
                    version_id=source.current_version_id,
                )
                content = self._read_content(source, source_version)
            except (OfficeDocumentNotFoundError, OfficeDocumentPermissionError):
                continue
            count = next(
                (
                    reference_count
                    for target_object_id, target_version_id, reference_count in office_document_reference_counts(
                        content
                    )
                    if target_object_id == object_id and target_version_id == target_version.version_id
                ),
                0,
            )
            if not count:
                continue
            backlinks.append(
                OfficeDocumentBacklink(
                    source_object_id=source.object_id,
                    source_version_id=source_version.version_id,
                    title=source_version.title,
                    reference_count=count,
                )
            )
            result_boundaries.append((candidate.created_at_utc, candidate.object_id))
            if len(backlinks) > page_size:
                break

        has_more = len(backlinks) > page_size or (
            len(scanned) == OFFICE_BACKLINK_SCAN_LIMIT and len(candidates) > OFFICE_BACKLINK_SCAN_LIMIT
        )
        if len(backlinks) > page_size:
            next_after = result_boundaries[page_size - 1]
        elif has_more and scanned:
            next_after = (scanned[-1].created_at_utc, scanned[-1].object_id)
        else:
            next_after = None
        backlinks = backlinks[:page_size]
        event_id = self._audit(
            user_context,
            "office.documents.backlinks",
            object_id=object_id,
            version_id=target_version.version_id,
            scanned_count=len(scanned),
            result_count=len(backlinks),
            has_more=has_more,
        )
        return OfficeDocumentBacklinksResponse(
            tenant_id=user_context.tenant_id,
            target_object_id=object_id,
            target_version_id=target_version.version_id,
            backlinks=backlinks,
            audit_event_id=event_id,
            next_cursor=self._write_backlink_cursor(next_after, binding) if next_after is not None else None,
            has_more=has_more,
            page_size=page_size,
        )

    def _history_binding(self, user: UserContext, object_id: str, page_size: int) -> str:
        payload = canonical_json(
            {
                "tenant": user.tenant_id,
                "actor": user.user_id,
                "roles": sorted(user.role_ids),
                "object_id": object_id,
                "page_size": page_size,
            }
        ).encode("utf-8")
        return hmac.new(self._list_cursor_key, b"office-history.v1:binding\0" + payload, sha256).hexdigest()

    def _read_history_cursor(self, cursor: str, binding: str) -> tuple[str, str]:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
                raise ValueError
            encoded, signature = cursor.split(".")
            payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") != encoded:
                raise ValueError
            expected = hmac.new(self._list_cursor_key, b"office-history.v1:cursor\0" + payload, sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {"binding", "head", "next"}:
                raise ValueError
            if not isinstance(value["binding"], str) or not hmac.compare_digest(value["binding"], binding):
                raise ValueError
            head, next_version = value["head"], value["next"]
            if (
                any(
                    not isinstance(item, str) or re.fullmatch(r"office-version-[a-f0-9]{32}", item) is None
                    for item in (head, next_version)
                )
                or head == next_version
            ):
                raise ValueError
            return head, next_version
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise OfficeDocumentHistoryRequestError("Invalid version history request") from exc

    def _write_history_cursor(self, head: str, next_version: str, binding: str) -> str:
        payload = canonical_json({"binding": binding, "head": head, "next": next_version}).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(self._list_cursor_key, b"office-history.v1:cursor\0" + payload, sha256).hexdigest()
        return f"{encoded}.{signature}"

    def history(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        page_size: int = 200,
        cursor: str | None = None,
    ) -> OfficeDocumentHistoryResponse:
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise OfficeDocumentHistoryRequestError("Invalid version history request")
        binding = self._history_binding(user_context, object_id, page_size)
        head, next_version = self._read_history_cursor(cursor, binding) if cursor is not None else (None, None)
        page = self.repository.history_page(
            user_context=user_context,
            object_id=object_id,
            history_head_version_id=head,
            next_version_id=next_version,
            limit=page_size + 1,
        )
        versions = page.versions[:page_size]
        has_more = len(page.versions) > page_size
        event_id = self._audit(
            user_context,
            "office.documents.history",
            object_id=object_id,
            count=len(versions),
            has_more=has_more,
        )
        return OfficeDocumentHistoryResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            versions=[self._version_view(version) for version in versions],
            audit_event_id=event_id,
            history_head_version_id=page.history_head_version_id,
            current_version_id=page.current_version_id,
            page_size=page_size,
            has_more=has_more,
            next_cursor=self._write_history_cursor(
                page.history_head_version_id,
                page.versions[page_size].version_id,
                binding,
            )
            if has_more
            else None,
        )

    def create(
        self,
        *,
        user_context: UserContext,
        command: OfficeDocumentCreateCommand,
        write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        if not self.writes_available or not write_enabled or not can_create_office_document(user_context):
            raise OfficeDocumentPermissionError("Document creation is not permitted")
        return self._save(user_context=user_context, object_id=None, command=command)

    def save(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: OfficeDocumentSaveCommand,
        write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        if not self.writes_available or not write_enabled:
            raise OfficeDocumentPermissionError("Document saving is not permitted")
        return self._save(user_context=user_context, object_id=object_id, command=command)

    def share_state(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentShareState:
        state = self.repository.share_state(user_context=user_context, object_id=object_id)
        return state.model_copy(
            update={
                "audit_event_id": self._audit(
                    user_context,
                    "office.documents.shares.read",
                    object_id=object_id,
                    acl_version=state.acl_version,
                    share_count=len(state.entries),
                )
            }
        )

    def set_share(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: OfficeDocumentShareCommand,
        write_enabled: bool = False,
    ) -> OfficeDocumentShareState:
        if not self.writes_available or not write_enabled:
            raise OfficeDocumentPermissionError("Document sharing is not permitted")
        command = OfficeDocumentShareCommand.model_validate(command.model_dump(mode="python"))
        state = self.repository.set_share(user_context=user_context, object_id=object_id, command=command)
        return state.model_copy(
            update={
                "audit_event_id": self._audit(
                    user_context,
                    "office.documents.shares.changed",
                    object_id=object_id,
                    principal_id=command.principal_id,
                    permission=command.permission,
                    expires_at_utc=command.expires_at_utc.isoformat() if command.expires_at_utc else None,
                    acl_version=state.acl_version,
                    mutation_reference=command.mutation_reference,
                )
            }
        )

    def revoke_share(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: OfficeDocumentUnshareCommand,
        write_enabled: bool = False,
    ) -> OfficeDocumentShareState:
        if not self.writes_available or not write_enabled:
            raise OfficeDocumentPermissionError("Document sharing is not permitted")
        command = OfficeDocumentUnshareCommand.model_validate(command.model_dump(mode="python"))
        state = self.repository.revoke_share(user_context=user_context, object_id=object_id, command=command)
        return state.model_copy(
            update={
                "audit_event_id": self._audit(
                    user_context,
                    "office.documents.shares.revoked",
                    object_id=object_id,
                    principal_id=command.principal_id,
                    acl_version=state.acl_version,
                    mutation_reference=command.mutation_reference,
                )
            }
        )

    def _save(
        self,
        *,
        user_context: UserContext,
        object_id: str | None,
        command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentContentResponse:
        # Revalidate even commands constructed internally without Pydantic validation.
        command = type(command).model_validate(command.model_dump(mode="python"))
        result = self.repository.commit(user_context=user_context, object_id=object_id, command=command)
        previous_classification = None
        if result.version.previous_version_id is not None:
            previous_classification = self.repository.get_version(
                user_context=user_context,
                object_id=result.document.object_id,
                version_id=result.version.previous_version_id,
            ).information_classification
        event_id = self._audit(
            user_context,
            "office.documents.saved",
            object_id=result.document.object_id,
            version_id=result.version.version_id,
            content_hash=result.version.content_hash,
            source_write_receipt_hash=result.version.source_write_receipt_hash,
            command_hash=result.version.command_hash,
            replayed=result.replayed,
            information_classification=result.version.information_classification,
            previous_information_classification=previous_classification,
            classification_changed=previous_classification is not None
            and previous_classification != result.version.information_classification,
        )
        # Return the committed transaction snapshot: a later save cannot invalidate this success.
        return self._content_response(
            result.document,
            result.version,
            result.content or command.document,
            True,
            event_id,
            replayed=result.replayed,
            can_share=(
                result.document.owner_principal_id == user_context.user_id
                or self.repository.can_admin(user_context=user_context, object_id=result.document.object_id)
            ),
        )

    def _read_content(self, document: OfficeDocumentRecord, version: OfficeDocumentVersion) -> dict[str, Any]:
        if version.tenant_id != document.tenant_id or version.object_id != document.object_id:
            raise OfficeDocumentInvalidContentError("Document source is invalid")
        try:
            if not isinstance(self.source_repository, SourceObjectMetadataRepository):
                raise OfficeDocumentInvalidContentError("Document metadata verification is unavailable")
            metadata = self.source_repository.get_metadata(
                tenant_id=document.tenant_id, object_id=document.object_id, version_id=version.version_id
            )
            self._validate_source(metadata, document, version)
            record = self.source_repository.get(
                tenant_id=document.tenant_id, object_id=document.object_id, version_id=version.version_id
            )
            self._validate_source(record.metadata, document, version)
            if record.metadata != metadata:
                raise OfficeDocumentInvalidContentError("Document source is invalid")
            SourceObjectWriteGuard().validate_before_write(record)
            content = source_object_content_bytes(record)
            if len(content) != version.content_byte_length or sha256_bytes(content) != version.content_hash:
                raise OfficeDocumentInvalidContentError("Document source is invalid")
            value = json.loads(content.decode("utf-8"))
            if not isinstance(value, dict):
                raise OfficeDocumentInvalidContentError("Document source is invalid")
            validate_office_document(value)
            from suite.platform.office_image_schema import image_references
            from suite.platform.office_images import read_image

            for attrs in image_references(value):
                read_image(self.source_repository, document, attrs, load=False)
            if canonical_json(value).encode("utf-8") != content:
                raise OfficeDocumentInvalidContentError("Document source is invalid")
            return value
        except SourceObjectStorageError:
            raise
        except KeyError as exc:
            raise OfficeDocumentNotFoundError("Document not found") from exc
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise OfficeDocumentInvalidContentError("Document source is invalid") from exc

    @staticmethod
    def _validate_source(
        metadata: SourceObjectMetadata, document: OfficeDocumentRecord, version: OfficeDocumentVersion
    ) -> None:
        if (
            metadata.tenant_id != document.tenant_id
            or metadata.object_id != document.object_id
            or metadata.version_id != version.version_id
            or metadata.object_type != SourceObjectType.DOCUMENT
            or metadata.mime_type != OFFICE_DOCUMENT_MIME_TYPE
            or metadata.source_system != OFFICE_DOCUMENT_SOURCE_SYSTEM
            or metadata.schema_version != OFFICE_DOCUMENT_SCHEMA_VERSION
            or metadata.lifecycle_state != SourceLifecycleState.SAVED_VERSION
            or metadata.classification.value != "internal"
            or metadata.retention_policy_id != "rp-standard"
            or metadata.legal_hold_state.value != "none"
            or metadata.parent_object_id is not None
            or metadata.thread_id is not None
            or metadata.parser_profile_id is not None
            or metadata.owner_principal_id != document.owner_principal_id
            or metadata.created_by != version.created_by
            or metadata.title != version.title
            or metadata.created_at_utc != version.created_at_utc
            or metadata.updated_at_utc != version.created_at_utc
            or metadata.audit_chain_ref != version.audit_chain_ref
            or metadata.kms_key_ref != f"kms://{document.tenant_id}/internal/v1"
            or metadata.content_hash != version.content_hash
            or metadata.manifest_hash != version.source_manifest_hash
            or metadata.acl_hash != version.acl_hash
            or metadata.acl_version != version.acl_version
            or metadata.content_byte_length != version.content_byte_length
            or not 0 < metadata.content_byte_length <= MAX_DOCUMENT_BYTES
            or build_source_object_manifest_hash(metadata) != metadata.manifest_hash
        ):
            raise OfficeDocumentInvalidContentError("Document source is invalid")

    @staticmethod
    def _view(record: OfficeDocumentRecord, can_write: bool, can_share: bool = False) -> OfficeDocumentView:
        return OfficeDocumentView(
            **record.model_dump(
                include={
                    "object_id",
                    "title",
                    "information_classification",
                    "current_version_id",
                    "created_at_utc",
                    "updated_at_utc",
                }
            ),
            can_write=can_write,
            can_share=can_share,
        )

    @staticmethod
    def _version_view(version: OfficeDocumentVersion) -> OfficeDocumentVersionView:
        return OfficeDocumentVersionView(**version.model_dump(include=set(OfficeDocumentVersionView.model_fields)))

    def _content_response(
        self,
        document: OfficeDocumentRecord,
        version: OfficeDocumentVersion,
        content: dict[str, Any],
        can_write: bool,
        event_id: str,
        *,
        replayed: bool = False,
        can_share: bool | None = None,
    ) -> OfficeDocumentContentResponse:
        return OfficeDocumentContentResponse(
            tenant_id=document.tenant_id,
            document=self._view(document, can_write, can_write if can_share is None else can_share),
            version=self._version_view(version),
            content=content,
            is_current_version=document.current_version_id == version.version_id,
            can_write=can_write,
            audit_event_id=event_id,
            replayed=replayed,
        )

    def _audit(self, user: UserContext, event_type: str, **metadata: Any) -> str:
        object_id = metadata.get("object_id")
        return self.audit.record(
            user_context=user,
            event_type=event_type,
            source_object_ids=[object_id] if isinstance(object_id, str) else [],
            metadata={
                "module_id": OFFICE_DOCUMENTS_MODULE_ID,
                "surface": "api",
                **metadata,
                "rag_indexing_allowed": False,
                "search_indexing_allowed": False,
            },
        ).event_id
