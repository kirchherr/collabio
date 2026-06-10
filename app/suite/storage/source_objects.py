from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.rag.models import SourceDocument
from suite.rag.source_indexing import ResolvedSource

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


class SourceObjectType(StrEnum):
    DOCUMENT = "document"
    MAIL = "mail"
    ATTACHMENT = "attachment"
    COMMENT = "comment"
    WIKI = "wiki"
    PROCEDURE_DOC = "procedure_doc"


class LegalHoldState(StrEnum):
    NONE = "none"
    ACTIVE = "active"


class SourceLifecycleState(StrEnum):
    WORKING = "working"
    SAVED_VERSION = "saved_version"
    BUSINESS_RECORD = "business_record"
    WORM_EVIDENCE = "worm_evidence"
    RESTRICTED = "restricted"
    DELETED = "deleted"
    CRYPTOSHREDDED = "cryptoshredded"


class SourceObjectMetadata(BaseModel):
    tenant_id: str
    object_id: str
    object_type: SourceObjectType
    version_id: str
    title: str
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: LegalHoldState = LegalHoldState.NONE
    kms_key_ref: str
    manifest_hash: str
    audit_chain_ref: str
    source_system: str
    schema_version: str = "source_object.v1"
    mime_type: str = "text/plain"
    acl_hash: str
    acl_version: int = Field(ge=1)
    content_hash: str
    content_byte_length: int = Field(ge=0)
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING
    parent_object_id: str | None = None
    thread_id: str | None = None
    parser_profile_id: str | None = None

    @field_validator(
        "tenant_id",
        "object_id",
        "version_id",
        "title",
        "owner_principal_id",
        "created_by",
        "retention_policy_id",
        "source_system",
        "schema_version",
        "mime_type",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("created_at_utc", "updated_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("timestamp must not be empty")
        candidate = normalized.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError("timestamp must be UTC")
        return normalized

    @field_validator("kms_key_ref", "manifest_hash", "audit_chain_ref", "acl_hash", "content_hash")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @model_validator(mode="after")
    def enforce_source_object_rules(self) -> Self:
        if self.object_type in {SourceObjectType.ATTACHMENT, SourceObjectType.COMMENT} and not self.parent_object_id:
            raise ValueError("attachments and comments require parent_object_id")
        if self.object_type == SourceObjectType.MAIL and self.mime_type != "message/rfc822":
            raise ValueError("mail source objects require message/rfc822 mime_type")
        if self.legal_hold_state == LegalHoldState.ACTIVE and self.lifecycle_state in {
            SourceLifecycleState.DELETED,
            SourceLifecycleState.CRYPTOSHREDDED,
        }:
            raise ValueError("legal hold blocks deletion and cryptoshredding")
        if self.lifecycle_state == SourceLifecycleState.WORM_EVIDENCE and self.audit_chain_ref == "audit:none":
            raise ValueError("WORM evidence requires an audit chain reference")
        return self


class SourceObjectRecord(BaseModel):
    metadata: SourceObjectMetadata
    text: str = ""
    content_bytes: bytes | None = None

    @model_validator(mode="after")
    def require_content_and_length_match(self) -> Self:
        if self.content_bytes is None:
            content_length = len(self.text.encode("utf-8"))
            if content_length == 0:
                raise ValueError("source object requires text or content_bytes")
        else:
            content_length = len(self.content_bytes)
            if content_length == 0:
                raise ValueError("content_bytes must not be empty")

        if self.metadata.content_byte_length != content_length:
            raise ValueError("content_byte_length must match stored content bytes")
        return self

    def to_source_document(self) -> SourceDocument:
        return SourceDocument(
            object_id=self.metadata.object_id,
            version_id=self.metadata.version_id,
            title=self.metadata.title,
            text=self.text,
            classification=self.metadata.classification,
            mime_type=self.metadata.mime_type,
            content_bytes=self.content_bytes,
        )


class SourceObjectRepository(Protocol):
    def add(self, record: SourceObjectRecord) -> None: ...

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord: ...

    def latest(self, *, tenant_id: str, object_id: str) -> SourceObjectRecord: ...


class InMemorySourceObjectRepository:
    def __init__(self, records: tuple[SourceObjectRecord, ...] = ()) -> None:
        self._records: dict[tuple[str, str, str], SourceObjectRecord] = {}
        self._latest_keys: dict[tuple[str, str], tuple[str, str, str]] = {}
        for record in records:
            self.add(record)

    def add(self, record: SourceObjectRecord) -> None:
        metadata = record.metadata
        key = (metadata.tenant_id, metadata.object_id, metadata.version_id)
        if key in self._records:
            raise ValueError("source object version already exists")
        self._records[key] = record
        self._latest_keys[(metadata.tenant_id, metadata.object_id)] = key

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord:
        return self._records[(tenant_id, object_id, version_id)]

    def latest(self, *, tenant_id: str, object_id: str) -> SourceObjectRecord:
        return self._records[self._latest_keys[(tenant_id, object_id)]]


class SourceObjectResolver:
    def __init__(self, repository: SourceObjectRepository) -> None:
        self.repository = repository

    def resolve_source(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
    ) -> ResolvedSource:
        record = self.repository.get(
            tenant_id=tenant_id,
            object_id=source_object_id,
            version_id=source_version_id,
        )
        metadata = record.metadata
        if metadata.tenant_id != tenant_id:
            raise ValueError("resolved source tenant_id does not match index command")
        if metadata.object_id != source_object_id:
            raise ValueError("resolved source object_id does not match index command")
        if metadata.version_id != source_version_id:
            raise ValueError("resolved source version_id does not match index command")

        return ResolvedSource(
            tenant_id=metadata.tenant_id,
            object_id=metadata.object_id,
            version_id=metadata.version_id,
            title=metadata.title,
            text=record.text,
            classification=metadata.classification,
            source_object_type=metadata.object_type.value,
            retention_policy_id=metadata.retention_policy_id,
            legal_hold_state=metadata.legal_hold_state.value,
            acl_hash=metadata.acl_hash,
            acl_version=metadata.acl_version,
            created_at_utc=metadata.created_at_utc,
            mime_type=metadata.mime_type,
            content_bytes=record.content_bytes,
        )
