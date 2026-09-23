"""Document-owned immutable renditions in the existing versioned source store.

The authoritative parent ACL is the asset ACL: assets cannot be shared independently.
Only normalized pixels are persisted; an upload never changes a document head.
"""

from __future__ import annotations

import copy
import struct
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import psycopg

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError
from suite.platform.office_documents import OfficeDocumentNotFoundError, OfficeDocumentPermissionError, OfficeDocumentRecord
from suite.platform.office_image_codec import MAX_IMAGE_OUTPUT, image_dimensions
from suite.platform.office_image_schema import image_references
from suite.storage.source_objects import (
    LegalHoldState, SourceLifecycleState, SourceObjectMetadata, SourceObjectMetadataRepository,
    SourceObjectRecord, SourceObjectRepository, SourceObjectType, SourceObjectWriteGuard,
    build_source_object_manifest_hash, build_source_object_write_receipt, sha256_bytes, source_object_content_bytes,
)

if TYPE_CHECKING:
    from suite.platform.office_document_repository import PgOfficeDocumentRepository

IMAGE_SOURCE_SYSTEM = "collabio_office_image"
IMAGE_SCHEMA = "collabio_office_image.v1"


def read_image(
    repository: SourceObjectRepository, document: OfficeDocumentRecord, attrs: dict[str, Any], *, load: bool = True,
) -> tuple[SourceObjectMetadata, bytes]:
    if attrs["documentId"] != document.object_id or not isinstance(repository, SourceObjectMetadataRepository):
        raise OfficeDocumentNotFoundError("Document not found")
    try:
        metadata = repository.get_metadata(
            tenant_id=document.tenant_id, object_id=attrs["assetId"], version_id=attrs["versionId"],
        )
        if metadata.parent_object_id != document.object_id:
            raise OfficeDocumentNotFoundError("Document not found")
        if (
            metadata.tenant_id != document.tenant_id or metadata.object_id != attrs["assetId"]
            or metadata.version_id != attrs["versionId"] or metadata.parent_object_id != document.object_id
            or metadata.source_system != IMAGE_SOURCE_SYSTEM or metadata.schema_version != IMAGE_SCHEMA
            or metadata.object_type != SourceObjectType.ATTACHMENT or metadata.mime_type != "image/png"
            or metadata.owner_principal_id != document.owner_principal_id or metadata.classification != DataClass.INTERNAL
            or metadata.retention_policy_id != "rp-standard" or metadata.legal_hold_state != LegalHoldState.NONE
            or metadata.kms_key_ref != f"kms://{document.tenant_id}/internal/v1"
            or metadata.lifecycle_state != SourceLifecycleState.SAVED_VERSION
            or metadata.thread_id is not None or metadata.parser_profile_id is not None
            or not 1 <= metadata.content_byte_length <= MAX_IMAGE_OUTPUT
            or metadata.manifest_hash != build_source_object_manifest_hash(metadata)
            or ("contentHash" in attrs and attrs["contentHash"] != metadata.content_hash)
            or ("manifestHash" in attrs and attrs["manifestHash"] != metadata.manifest_hash)
        ):
            raise OfficeDocumentInvalidContentError("Image reference validation failed")
        if not load:
            return metadata, b""
        source = repository.get(tenant_id=document.tenant_id, object_id=metadata.object_id, version_id=metadata.version_id)
        if source.metadata != metadata:
            raise OfficeDocumentInvalidContentError("Image source changed")
        SourceObjectWriteGuard().validate_before_write(source)
        content = source_object_content_bytes(source)
        if len(content) != metadata.content_byte_length or sha256_bytes(content) != metadata.content_hash:
            raise OfficeDocumentInvalidContentError("Image source integrity failed")
        if not content.startswith(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"):
            raise OfficeDocumentInvalidContentError("Image source is invalid")
        width, height = struct.unpack(">II", content[16:24])
        image_dimensions(width, height)
        if "pixelWidth" in attrs and (width, height) != (attrs["pixelWidth"], attrs["pixelHeight"]):
            raise OfficeDocumentInvalidContentError("Image source dimensions differ")
        return metadata, content
    except KeyError as exc:
        raise OfficeDocumentNotFoundError("Document not found") from exc


def persist_image(
    repository: PgOfficeDocumentRepository, connection: psycopg.Connection[Any], user: UserContext,
    document: OfficeDocumentRecord, content: bytes, width: int, height: int,
) -> dict[str, Any]:
    acl_rows = repository._acl_rows(connection, user.tenant_id, document.object_id)
    if not acl_rows:
        raise OfficeDocumentPermissionError("Document image writing is not permitted")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    audit_ref = f"audit:office-image-{uuid4().hex}"
    metadata = SourceObjectMetadata(
        tenant_id=user.tenant_id, object_id=f"office-image-{uuid4().hex}", version_id=f"office-image-version-{uuid4().hex}",
        object_type=SourceObjectType.ATTACHMENT, parent_object_id=document.object_id, title="Document image",
        owner_principal_id=document.owner_principal_id, created_by=user.user_id, created_at_utc=now, updated_at_utc=now,
        classification=DataClass.INTERNAL, retention_policy_id="rp-standard", legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{user.tenant_id}/internal/v1", manifest_hash="sha256:" + "0" * 64, audit_chain_ref=audit_ref,
        source_system=IMAGE_SOURCE_SYSTEM, schema_version=IMAGE_SCHEMA, mime_type="image/png",
        acl_hash=stable_hash(canonical_json(acl_rows)), acl_version=max(int(row[3]) for row in acl_rows),
        content_hash=sha256_bytes(content), content_byte_length=len(content), lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    record = SourceObjectRecord(metadata=metadata, content_bytes=content)
    receipt = build_source_object_write_receipt(
        record=record, receipt_reference=f"office-image-write:{uuid4().hex}", audit_chain_ref=audit_ref, captured_at_utc=now,
    )
    repository.receipt_store.append_in_transaction(connection, receipt)
    repository.source_repository.add_with_receipt_in_transaction(
        connection, record=record, source_object_write_receipt_hash=receipt.receipt_hash,
    )
    display_width = min(width, 640)
    display_height = max(1, round(height * display_width / width))
    if display_height > 1600:
        display_width = max(1, round(display_width * 1600 / display_height))
        display_height = 1600
    return {
        "documentId": document.object_id, "assetId": metadata.object_id, "versionId": metadata.version_id,
        "contentHash": metadata.content_hash, "manifestHash": metadata.manifest_hash,
        "pixelWidth": width, "pixelHeight": height, "width": display_width, "height": display_height,
        "align": "left", "alt": "", "caption": "", "decorative": True, "lockAspect": True,
    }


def prepare_image_references(
    repository: PgOfficeDocumentRepository, connection: psycopg.Connection[Any], user: UserContext,
    document: OfficeDocumentRecord, content: dict[str, Any], *, creating: bool,
) -> dict[str, Any]:
    references = image_references(content)
    if not references:
        return content
    result = copy.deepcopy(content)
    copies: dict[tuple[str, str], dict[str, Any]] = {}
    for attrs in image_references(result):
        owner = attrs["documentId"]
        if owner == document.object_id:
            read_image(repository.source_repository, document, attrs)
            continue
        if not creating:
            raise OfficeDocumentInvalidContentError("Image belongs to another document")
        # Explicit Create/reuse obtains independent ownership; never inherit sharing.
        source_document = repository._authorized_document(connection, user, owner)
        _, pixels = read_image(repository.source_repository, source_document, attrs)
        key = (attrs["assetId"], attrs["versionId"])
        if key not in copies:
            copies[key] = persist_image(
                repository, connection, user, document, pixels, attrs["pixelWidth"], attrs["pixelHeight"],
            )
        for name in ("documentId", "assetId", "versionId", "contentHash", "manifestHash"):
            attrs[name] = copies[key][name]
    return result


def store_uploaded_image(
    repository: PgOfficeDocumentRepository, user: UserContext, object_id: str, content: bytes, width: int, height: int,
) -> dict[str, Any]:
    with psycopg.connect(repository.database_dsn) as connection, connection.transaction():
        repository._set_tenant(connection, user.tenant_id)
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"office-document-write:{user.tenant_id}",))
        document = repository._authorized_document(connection, user, object_id, write=True)
        # Draft removal never deletes historical assets. Bound retained uploads until a
        # separately confirmed, retention-aware cleanup workflow is introduced.
        count = connection.execute(
            "SELECT count(*) FROM collabio.source_object_metadata WHERE tenant_id = %s AND parent_object_id = %s "
            "AND source_system = %s", (user.tenant_id, object_id, IMAGE_SOURCE_SYSTEM),
        ).fetchone()
        if count is None or count[0] >= 200:
            raise OfficeDocumentInvalidContentError("Document image storage limit reached")
        return persist_image(repository, connection, user, document, content, width, height)
