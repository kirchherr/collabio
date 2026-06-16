from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, Self

import psycopg
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import KmsKeyReference, KmsKeyReferenceError
from suite.rag.models import SourceDocument
from suite.rag.source_indexing import ResolvedSource
from suite.storage.content_hash import ContentHashVerificationError, compute_content_hash, verify_content_hash

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ManifestValue = str | int | None
SOURCE_OBJECT_WRITE_RECEIPT_SCHEMA_VERSION = "source_object_write_receipt.v1"
ZERO_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class SourceObjectWriteDeniedError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return compute_content_hash(value)


def source_object_content_bytes(record: SourceObjectRecord) -> bytes:
    return record.content_bytes if record.content_bytes is not None else record.text.encode("utf-8")


def source_object_manifest_payload(metadata: SourceObjectMetadata) -> dict[str, ManifestValue]:
    return {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "object_type": metadata.object_type.value,
        "version_id": metadata.version_id,
        "title": metadata.title,
        "owner_principal_id": metadata.owner_principal_id,
        "created_by": metadata.created_by,
        "created_at_utc": metadata.created_at_utc,
        "updated_at_utc": metadata.updated_at_utc,
        "classification": metadata.classification.value,
        "retention_policy_id": metadata.retention_policy_id,
        "legal_hold_state": metadata.legal_hold_state.value,
        "kms_key_ref": metadata.kms_key_ref,
        "audit_chain_ref": metadata.audit_chain_ref,
        "source_system": metadata.source_system,
        "schema_version": metadata.schema_version,
        "mime_type": metadata.mime_type,
        "acl_hash": metadata.acl_hash,
        "acl_version": metadata.acl_version,
        "content_hash": metadata.content_hash,
        "content_byte_length": metadata.content_byte_length,
        "lifecycle_state": metadata.lifecycle_state.value,
        "parent_object_id": metadata.parent_object_id,
        "thread_id": metadata.thread_id,
        "parser_profile_id": metadata.parser_profile_id,
    }


def build_source_object_manifest_hash(metadata: SourceObjectMetadata) -> str:
    payload = source_object_manifest_payload(metadata)
    manifest_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(manifest_bytes)


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


class SourceObjectWriteReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    receipt_reference: str
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
    legal_hold_state: LegalHoldState
    kms_key_ref: str
    manifest_hash: str
    audit_chain_ref: str
    source_system: str
    source_schema_version: str
    mime_type: str
    acl_hash: str
    acl_version: int = Field(ge=1)
    content_hash: str
    content_byte_length: int = Field(ge=0)
    lifecycle_state: SourceLifecycleState
    parent_object_id: str | None = None
    thread_id: str | None = None
    parser_profile_id: str | None = None
    captured_at_utc: str
    receipt_hash: str
    receipt_schema_version: str = SOURCE_OBJECT_WRITE_RECEIPT_SCHEMA_VERSION

    @field_validator(
        "tenant_id",
        "object_id",
        "version_id",
        "title",
        "owner_principal_id",
        "created_by",
        "retention_policy_id",
        "source_system",
        "source_schema_version",
        "mime_type",
        "receipt_schema_version",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("created_at_utc", "updated_at_utc", "captured_at_utc")
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

    @field_validator("receipt_reference", "kms_key_ref", "audit_chain_ref", "acl_hash", "content_hash")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("manifest_hash", "receipt_hash")
    @classmethod
    def require_sha256_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not SHA256_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a sha256 reference")
        return normalized


def source_object_write_receipt_payload(receipt: SourceObjectWriteReceipt) -> dict[str, Any]:
    return receipt.model_dump(mode="json", exclude={"receipt_hash"})


def build_source_object_write_receipt_hash(receipt: SourceObjectWriteReceipt) -> str:
    receipt_bytes = json.dumps(
        source_object_write_receipt_payload(receipt),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(receipt_bytes)


def build_source_object_write_receipt(
    *,
    record: SourceObjectRecord,
    receipt_reference: str,
    audit_chain_ref: str,
    captured_at_utc: str | None = None,
) -> SourceObjectWriteReceipt:
    metadata = record.metadata
    captured = captured_at_utc or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    draft = SourceObjectWriteReceipt(
        tenant_id=metadata.tenant_id,
        receipt_reference=receipt_reference,
        object_id=metadata.object_id,
        object_type=metadata.object_type,
        version_id=metadata.version_id,
        title=metadata.title,
        owner_principal_id=metadata.owner_principal_id,
        created_by=metadata.created_by,
        created_at_utc=metadata.created_at_utc,
        updated_at_utc=metadata.updated_at_utc,
        classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state,
        kms_key_ref=metadata.kms_key_ref,
        manifest_hash=metadata.manifest_hash,
        audit_chain_ref=audit_chain_ref,
        source_system=metadata.source_system,
        source_schema_version=metadata.schema_version,
        mime_type=metadata.mime_type,
        acl_hash=metadata.acl_hash,
        acl_version=metadata.acl_version,
        content_hash=metadata.content_hash,
        content_byte_length=metadata.content_byte_length,
        lifecycle_state=metadata.lifecycle_state,
        parent_object_id=metadata.parent_object_id,
        thread_id=metadata.thread_id,
        parser_profile_id=metadata.parser_profile_id,
        captured_at_utc=captured,
        receipt_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"receipt_hash": build_source_object_write_receipt_hash(draft)})


class SourceObjectWriteReceiptStore(Protocol):
    def append(self, receipt: SourceObjectWriteReceipt) -> SourceObjectWriteReceipt: ...

    def get(self, *, tenant_id: str, receipt_hash: str) -> SourceObjectWriteReceipt: ...

    def list_receipts(self, *, tenant_id: str) -> tuple[SourceObjectWriteReceipt, ...]: ...


class InMemorySourceObjectWriteReceiptStore:
    def __init__(self, receipts: tuple[SourceObjectWriteReceipt, ...] = ()) -> None:
        self._receipts: dict[tuple[str, str], SourceObjectWriteReceipt] = {}
        self._object_versions: set[tuple[str, str, str]] = set()
        for receipt in receipts:
            self.append(receipt)

    def append(self, receipt: SourceObjectWriteReceipt) -> SourceObjectWriteReceipt:
        expected_hash = build_source_object_write_receipt_hash(receipt)
        if receipt.receipt_hash != expected_hash:
            raise ValueError("source object write receipt hash is invalid")
        key = (receipt.tenant_id, receipt.receipt_hash)
        object_version_key = (receipt.tenant_id, receipt.object_id, receipt.version_id)
        if key in self._receipts or object_version_key in self._object_versions:
            raise ValueError("source object write receipt already exists")
        self._receipts[key] = receipt
        self._object_versions.add(object_version_key)
        return receipt

    def get(self, *, tenant_id: str, receipt_hash: str) -> SourceObjectWriteReceipt:
        try:
            return self._receipts[(tenant_id, receipt_hash)]
        except KeyError as exc:
            raise KeyError("source object write receipt not found") from exc

    def list_receipts(self, *, tenant_id: str) -> tuple[SourceObjectWriteReceipt, ...]:
        return tuple(
            receipt
            for (stored_tenant_id, _), receipt in sorted(self._receipts.items(), key=lambda item: item[0])
            if stored_tenant_id == tenant_id
        )


class PgSourceObjectWriteReceiptStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, receipt: SourceObjectWriteReceipt) -> SourceObjectWriteReceipt:
        self._require_valid_receipt(receipt)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, receipt.tenant_id)
                self._insert_receipt(connection, receipt)
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source object write receipt already exists") from exc
        return receipt

    def append_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        receipt: SourceObjectWriteReceipt,
    ) -> SourceObjectWriteReceipt:
        self._require_valid_receipt(receipt)
        try:
            self._insert_receipt(connection, receipt)
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source object write receipt already exists") from exc
        return receipt

    def get(self, *, tenant_id: str, receipt_hash: str) -> SourceObjectWriteReceipt:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT
                    tenant_id,
                    receipt_reference,
                    object_id,
                    object_type,
                    version_id,
                    title,
                    owner_principal_id,
                    created_by,
                    created_at_utc,
                    updated_at_utc,
                    classification,
                    retention_policy_id,
                    legal_hold_state,
                    kms_key_ref,
                    manifest_hash,
                    audit_chain_ref,
                    source_system,
                    source_schema_version,
                    mime_type,
                    acl_hash,
                    acl_version,
                    content_hash,
                    content_byte_length,
                    lifecycle_state,
                    parent_object_id,
                    thread_id,
                    parser_profile_id,
                    captured_at_utc,
                    receipt_hash,
                    receipt_schema_version
                FROM collabio.source_object_write_receipts
                WHERE tenant_id = %s
                  AND receipt_hash = %s
                """,
                (tenant_id, receipt_hash),
            ).fetchone()
        if row is None:
            raise KeyError("source object write receipt not found")
        return self._receipt_from_row(row)

    def list_receipts(self, *, tenant_id: str) -> tuple[SourceObjectWriteReceipt, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT
                    tenant_id,
                    receipt_reference,
                    object_id,
                    object_type,
                    version_id,
                    title,
                    owner_principal_id,
                    created_by,
                    created_at_utc,
                    updated_at_utc,
                    classification,
                    retention_policy_id,
                    legal_hold_state,
                    kms_key_ref,
                    manifest_hash,
                    audit_chain_ref,
                    source_system,
                    source_schema_version,
                    mime_type,
                    acl_hash,
                    acl_version,
                    content_hash,
                    content_byte_length,
                    lifecycle_state,
                    parent_object_id,
                    thread_id,
                    parser_profile_id,
                    captured_at_utc,
                    receipt_hash,
                    receipt_schema_version
                FROM collabio.source_object_write_receipts
                WHERE tenant_id = %s
                ORDER BY captured_at_utc, receipt_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    def _require_valid_receipt(self, receipt: SourceObjectWriteReceipt) -> None:
        expected_hash = build_source_object_write_receipt_hash(receipt)
        if receipt.receipt_hash != expected_hash:
            raise ValueError("source object write receipt hash is invalid")

    def _insert_receipt(
        self,
        connection: psycopg.Connection[Any],
        receipt: SourceObjectWriteReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO collabio.source_object_write_receipts (
                tenant_id,
                receipt_reference,
                object_id,
                object_type,
                version_id,
                title,
                owner_principal_id,
                created_by,
                created_at_utc,
                updated_at_utc,
                classification,
                retention_policy_id,
                legal_hold_state,
                kms_key_ref,
                manifest_hash,
                audit_chain_ref,
                source_system,
                source_schema_version,
                mime_type,
                acl_hash,
                acl_version,
                content_hash,
                content_byte_length,
                lifecycle_state,
                parent_object_id,
                thread_id,
                parser_profile_id,
                captured_at_utc,
                receipt_hash,
                receipt_schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            self._receipt_values(receipt),
        )

    def _receipt_values(self, receipt: SourceObjectWriteReceipt) -> tuple[Any, ...]:
        return (
            receipt.tenant_id,
            receipt.receipt_reference,
            receipt.object_id,
            receipt.object_type.value,
            receipt.version_id,
            receipt.title,
            receipt.owner_principal_id,
            receipt.created_by,
            receipt.created_at_utc,
            receipt.updated_at_utc,
            receipt.classification.value,
            receipt.retention_policy_id,
            receipt.legal_hold_state.value,
            receipt.kms_key_ref,
            receipt.manifest_hash,
            receipt.audit_chain_ref,
            receipt.source_system,
            receipt.source_schema_version,
            receipt.mime_type,
            receipt.acl_hash,
            receipt.acl_version,
            receipt.content_hash,
            receipt.content_byte_length,
            receipt.lifecycle_state.value,
            receipt.parent_object_id,
            receipt.thread_id,
            receipt.parser_profile_id,
            receipt.captured_at_utc,
            receipt.receipt_hash,
            receipt.receipt_schema_version,
        )

    def _receipt_from_row(self, row: tuple[Any, ...]) -> SourceObjectWriteReceipt:
        return SourceObjectWriteReceipt(
            tenant_id=str(row[0]),
            receipt_reference=str(row[1]),
            object_id=str(row[2]),
            object_type=SourceObjectType(str(row[3])),
            version_id=str(row[4]),
            title=str(row[5]),
            owner_principal_id=str(row[6]),
            created_by=str(row[7]),
            created_at_utc=self._utc_timestamp(row[8]),
            updated_at_utc=self._utc_timestamp(row[9]),
            classification=DataClass(str(row[10])),
            retention_policy_id=str(row[11]),
            legal_hold_state=LegalHoldState(str(row[12])),
            kms_key_ref=str(row[13]),
            manifest_hash=str(row[14]),
            audit_chain_ref=str(row[15]),
            source_system=str(row[16]),
            source_schema_version=str(row[17]),
            mime_type=str(row[18]),
            acl_hash=str(row[19]),
            acl_version=int(row[20]),
            content_hash=str(row[21]),
            content_byte_length=int(row[22]),
            lifecycle_state=SourceLifecycleState(str(row[23])),
            parent_object_id=str(row[24]) if row[24] is not None else None,
            thread_id=str(row[25]) if row[25] is not None else None,
            parser_profile_id=str(row[26]) if row[26] is not None else None,
            captured_at_utc=self._utc_timestamp(row[27]),
            receipt_hash=str(row[28]),
            receipt_schema_version=str(row[29]),
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))

    def _utc_timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return str(value)


def build_default_source_object_write_receipt_store() -> SourceObjectWriteReceiptStore:
    backend = os.getenv("SUITE_SOURCE_OBJECT_WRITE_RECEIPT_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemorySourceObjectWriteReceiptStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = os.getenv("SUITE_SOURCE_OBJECT_WRITE_RECEIPT_DSN") or os.getenv("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL source object write receipt store requires "
                "SUITE_SOURCE_OBJECT_WRITE_RECEIPT_DSN or SUITE_DATABASE_DSN"
            )
        return PgSourceObjectWriteReceiptStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_SOURCE_OBJECT_WRITE_RECEIPT_BACKEND: {backend}")


class SourceObjectRepository(Protocol):
    def add(self, record: SourceObjectRecord) -> None: ...

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord: ...

    def latest(self, *, tenant_id: str, object_id: str) -> SourceObjectRecord: ...


class SourceObjectWriteGuard:
    required_metadata_fields: tuple[str, ...] = (
        "tenant_id",
        "classification",
        "retention_policy_id",
        "kms_key_ref",
        "manifest_hash",
        "content_hash",
    )

    def validate_before_write(self, record: SourceObjectRecord) -> None:
        metadata = record.metadata
        self._require_write_metadata(metadata)
        self._require_kms_reference(metadata)
        self._require_content_hash_match(record)
        self._require_manifest_hash_match(metadata)

    def _require_write_metadata(self, metadata: SourceObjectMetadata) -> None:
        for field_name in self.required_metadata_fields:
            value = getattr(metadata, field_name)
            if value is None:
                raise SourceObjectWriteDeniedError(f"{field_name} is required for storage write")
            if isinstance(value, str) and not value.strip():
                raise SourceObjectWriteDeniedError(f"{field_name} is required for storage write")

    def _require_kms_reference(self, metadata: SourceObjectMetadata) -> None:
        try:
            key_ref = KmsKeyReference.parse(metadata.kms_key_ref)
        except KmsKeyReferenceError as exc:
            raise SourceObjectWriteDeniedError(f"kms_key_ref invalid: {exc}") from exc
        if key_ref.tenant_id != metadata.tenant_id:
            raise SourceObjectWriteDeniedError("kms_key_ref tenant_id does not match source object")
        if key_ref.data_class != metadata.classification:
            raise SourceObjectWriteDeniedError("kms_key_ref data_class does not match source object")

    def _require_content_hash_match(self, record: SourceObjectRecord) -> None:
        try:
            verify_content_hash(
                content=source_object_content_bytes(record),
                expected_hash=record.metadata.content_hash,
                verification_context="source_object_write",
            )
        except ContentHashVerificationError as exc:
            raise SourceObjectWriteDeniedError(f"content_hash verification failed: {exc}") from exc

    def _require_manifest_hash_match(self, metadata: SourceObjectMetadata) -> None:
        expected_hash = build_source_object_manifest_hash(metadata)
        if metadata.manifest_hash != expected_hash:
            raise SourceObjectWriteDeniedError("manifest_hash does not match source object metadata")


class InMemorySourceObjectRepository:
    def __init__(
        self,
        records: tuple[SourceObjectRecord, ...] = (),
        *,
        write_guard: SourceObjectWriteGuard | None = None,
    ) -> None:
        self._records: dict[tuple[str, str, str], SourceObjectRecord] = {}
        self._latest_keys: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.write_guard = write_guard or SourceObjectWriteGuard()
        for record in records:
            self.add(record)

    def add(self, record: SourceObjectRecord) -> None:
        metadata = record.metadata
        self.write_guard.validate_before_write(record)
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
