from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import (
    MAX_DOCUMENT_BYTES,
    OFFICE_DOCUMENT_MIME_TYPE,
    OFFICE_DOCUMENT_SCHEMA_VERSION,
    OfficeDocumentInvalidContentError,
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


class OfficeDocumentNotFoundError(KeyError):
    pass


class OfficeDocumentPermissionError(PermissionError):
    pass


class OfficeDocumentConflictError(ValueError):
    pass


class OfficeDocumentCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    document: dict[str, Any]
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
    current_version_id: str
    created_at_utc: str
    updated_at_utc: str
    can_write: bool


class OfficeDocumentVersionView(BaseModel):
    version_id: str
    previous_version_id: str | None
    title: str
    created_at_utc: str
    created_by: str
    content_hash: str
    source_write_receipt_hash: str


class OfficeDocumentListResponse(BaseModel):
    tenant_id: str
    documents: list[OfficeDocumentView]
    can_create: bool
    audit_event_id: str


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


class OfficeDocumentHistoryResponse(BaseModel):
    tenant_id: str
    object_id: str
    versions: list[OfficeDocumentVersionView]
    audit_event_id: str


class OfficeDocumentCommit(BaseModel):
    document: OfficeDocumentRecord
    version: OfficeDocumentVersion
    replayed: bool = False


class OfficeDocumentRepository(Protocol):
    def list_documents(self, *, user_context: UserContext) -> tuple[OfficeDocumentRecord, ...]: ...

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord: ...

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool: ...

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]: ...

    def get_version(self, *, user_context: UserContext, object_id: str, version_id: str) -> OfficeDocumentVersion: ...

    def commit(
        self, *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand
    ) -> OfficeDocumentCommit: ...


def office_document_command_hash(
    *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand
) -> str:
    return stable_hash(canonical_json({
        "tenant_id": user_context.tenant_id,
        "actor": user_context.user_id,
        "object_id": object_id,
        "command": command.model_dump(mode="json"),
        "schema_version": OFFICE_DOCUMENT_SCHEMA_VERSION,
    }))


def can_create_office_document(user_context: UserContext) -> bool:
    return bool(user_context.role_ids & {"tenant-admin", "office-editor"})


class OfficeDocumentService:
    def __init__(
        self, *, repository: OfficeDocumentRepository, source_repository: SourceObjectRepository,
        audit: InMemoryAuditLogger, writes_available: bool = True,
    ) -> None:
        self.repository = repository
        self.source_repository = source_repository
        self.audit = audit
        self.writes_available = writes_available

    def list_documents(self, *, user_context: UserContext, write_enabled: bool = False) -> OfficeDocumentListResponse:
        records = self.repository.list_documents(user_context=user_context)
        event_id = self._audit(user_context, "office.documents.list", count=len(records))
        return OfficeDocumentListResponse(
            tenant_id=user_context.tenant_id,
            documents=[self._view(record, self.writes_available and write_enabled and self.repository.can_write(
                user_context=user_context, object_id=record.object_id
            )) for record in records],
            can_create=self.writes_available and write_enabled and can_create_office_document(user_context),
            audit_event_id=event_id,
        )

    def read_content(
        self, *, user_context: UserContext, object_id: str, version_id: str | None = None,
        write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        document = self.repository.get_document(user_context=user_context, object_id=object_id)
        version = self.repository.get_version(
            user_context=user_context, object_id=object_id, version_id=version_id or document.current_version_id
        )
        content = self._read_content(document, version)
        can_write = self.writes_available and write_enabled and self.repository.can_write(user_context=user_context, object_id=object_id)
        event_id = self._audit(user_context, "office.documents.read", object_id=object_id,
                               version_id=version.version_id, content_hash=version.content_hash)
        return self._content_response(document, version, content, can_write, event_id)

    def history(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentHistoryResponse:
        versions = self.repository.versions(user_context=user_context, object_id=object_id)
        event_id = self._audit(user_context, "office.documents.history", object_id=object_id, count=len(versions))
        return OfficeDocumentHistoryResponse(
            tenant_id=user_context.tenant_id, object_id=object_id,
            versions=[self._version_view(version) for version in versions], audit_event_id=event_id,
        )

    def create(
        self, *, user_context: UserContext, command: OfficeDocumentCreateCommand, write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        if not self.writes_available or not write_enabled or not can_create_office_document(user_context):
            raise OfficeDocumentPermissionError("Document creation is not permitted")
        return self._save(user_context=user_context, object_id=None, command=command)

    def save(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentSaveCommand,
        write_enabled: bool = False,
    ) -> OfficeDocumentContentResponse:
        if not self.writes_available or not write_enabled:
            raise OfficeDocumentPermissionError("Document saving is not permitted")
        return self._save(user_context=user_context, object_id=object_id, command=command)

    def _save(
        self, *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentContentResponse:
        # Revalidate even commands constructed internally without Pydantic validation.
        command = type(command).model_validate(command.model_dump(mode="python"))
        result = self.repository.commit(user_context=user_context, object_id=object_id, command=command)
        event_id = self._audit(
            user_context, "office.documents.saved", object_id=result.document.object_id,
            version_id=result.version.version_id, content_hash=result.version.content_hash,
            source_write_receipt_hash=result.version.source_write_receipt_hash,
            command_hash=result.version.command_hash, replayed=result.replayed,
        )
        # Return the committed transaction snapshot: a later save cannot invalidate this success.
        return self._content_response(
            result.document, result.version, command.document, True, event_id, replayed=result.replayed
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
    def _validate_source(metadata: SourceObjectMetadata, document: OfficeDocumentRecord, version: OfficeDocumentVersion) -> None:
        if (
            metadata.tenant_id != document.tenant_id or metadata.object_id != document.object_id
            or metadata.version_id != version.version_id or metadata.object_type != SourceObjectType.DOCUMENT
            or metadata.mime_type != OFFICE_DOCUMENT_MIME_TYPE or metadata.source_system != OFFICE_DOCUMENT_SOURCE_SYSTEM
            or metadata.schema_version != OFFICE_DOCUMENT_SCHEMA_VERSION
            or metadata.lifecycle_state != SourceLifecycleState.SAVED_VERSION
            or metadata.classification.value != "internal" or metadata.retention_policy_id != "rp-standard"
            or metadata.legal_hold_state.value != "none" or metadata.parent_object_id is not None
            or metadata.thread_id is not None or metadata.parser_profile_id is not None
            or metadata.owner_principal_id != document.owner_principal_id or metadata.created_by != version.created_by
            or metadata.title != version.title or metadata.created_at_utc != version.created_at_utc
            or metadata.updated_at_utc != version.created_at_utc or metadata.audit_chain_ref != version.audit_chain_ref
            or metadata.kms_key_ref != f"kms://{document.tenant_id}/internal/v1"
            or metadata.content_hash != version.content_hash or metadata.manifest_hash != version.source_manifest_hash
            or metadata.acl_hash != version.acl_hash or metadata.acl_version != version.acl_version
            or metadata.content_byte_length != version.content_byte_length
            or not 0 < metadata.content_byte_length <= MAX_DOCUMENT_BYTES
            or build_source_object_manifest_hash(metadata) != metadata.manifest_hash
        ):
            raise OfficeDocumentInvalidContentError("Document source is invalid")

    @staticmethod
    def _view(record: OfficeDocumentRecord, can_write: bool) -> OfficeDocumentView:
        return OfficeDocumentView(**record.model_dump(include={
            "object_id", "title", "current_version_id", "created_at_utc", "updated_at_utc"
        }), can_write=can_write)

    @staticmethod
    def _version_view(version: OfficeDocumentVersion) -> OfficeDocumentVersionView:
        return OfficeDocumentVersionView(**version.model_dump(include=set(OfficeDocumentVersionView.model_fields)))

    def _content_response(
        self, document: OfficeDocumentRecord, version: OfficeDocumentVersion, content: dict[str, Any],
        can_write: bool, event_id: str, *, replayed: bool = False,
    ) -> OfficeDocumentContentResponse:
        return OfficeDocumentContentResponse(
            tenant_id=document.tenant_id, document=self._view(document, can_write),
            version=self._version_view(version), content=content,
            is_current_version=document.current_version_id == version.version_id,
            can_write=can_write, audit_event_id=event_id, replayed=replayed,
        )

    def _audit(self, user: UserContext, event_type: str, **metadata: Any) -> str:
        object_id = metadata.get("object_id")
        return self.audit.record(
            user_context=user, event_type=event_type,
            source_object_ids=[object_id] if isinstance(object_id, str) else [],
            metadata={"module_id": OFFICE_DOCUMENTS_MODULE_ID, "surface": "api", **metadata,
                      "rag_indexing_allowed": False, "search_indexing_allowed": False},
        ).event_id
