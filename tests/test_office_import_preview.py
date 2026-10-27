from __future__ import annotations

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_import_preview import (
    OfficeImportPreviewCommand,
    OfficeImportPreviewDenied,
    OfficeImportPreviewInvalid,
    OfficeImportPreviewNotFound,
    OfficeImportPreviewService,
)
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, sha256_bytes
from suite.rag.rich_document_parser import DOCX_MIME_TYPE
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
)


def source_record(
    content: bytes = b"synthetic-docx-bytes",
    *,
    mime_type: str = DOCX_MIME_TYPE,
) -> SourceObjectRecord:
    draft = SourceObjectMetadata(
        tenant_id="tenant-office",
        object_id="source-docx-1",
        object_type=SourceObjectType.DOCUMENT,
        version_id="v7",
        title="Importierte Notiz",
        owner_principal_id="editor",
        created_by="editor",
        created_at_utc="2026-10-27T08:00:00Z",
        updated_at_utc="2026-10-27T08:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        kms_key_ref="kms://tenant-office/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref="audit:source-docx-1-v7",
        source_system="collabio-test",
        mime_type=mime_type,
        acl_hash="sha256:source-docx-1-acl",
        acl_version=4,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
    )
    metadata = draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)})
    return SourceObjectRecord(metadata=metadata, content_bytes=content)


def user(*, readable: bool = True, tenant_id: str = "tenant-office") -> UserContext:
    return UserContext(
        tenant_id=tenant_id,
        user_id="editor",
        role_ids={"office-editor"},
        readable_object_ids={"source-docx-1"} if readable else set(),
    )


def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
    return ParsedTextArtifact(
        text="Erster Absatz\nZweiter Absatz",
        parser_name="rich-document-parser-worker",
        parser_version="1",
        source_object_type=request.source_object_type,
        mime_type=DOCX_MIME_TYPE,
        input_hash=sha256_bytes(request.content),
        text_hash=sha256_bytes(b"Erster Absatz\nZweiter Absatz"),
        text_byte_length=len(b"Erster Absatz\nZweiter Absatz"),
        warnings=("non-executable security markers require review",),
    )


def command() -> OfficeImportPreviewCommand:
    return OfficeImportPreviewCommand(source_object_id="source-docx-1", source_version_id="v7")


def test_import_preview_is_acl_checked_non_persisting_and_provenance_bound() -> None:
    record = source_record()
    audit = InMemoryAuditLogger()
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((record,)),
        audit=audit,
        parser_dispatch=parser,
    )

    response = service.preview(user_context=user(), command=command())

    assert response.content_persisted is False
    assert response.save_requires_explicit_confirmation is True
    assert response.fidelity_preserved is False
    assert response.information_classification == "internal"
    assert [entry["content"][0]["text"] for entry in response.document["content"]] == [
        "Erster Absatz",
        "Zweiter Absatz",
    ]
    assert response.document["attrs"]["importProvenance"] == {
        "sourceObjectId": "source-docx-1",
        "sourceVersionId": "v7",
        "sourceContentHash": record.metadata.content_hash,
        "sourceAclVersion": 4,
        "parserProfileId": "rich-document-parser-worker:1",
        "parserTextHash": response.parser_text_hash,
        "importScope": "bounded_flattened_text_preview",
    }
    event = audit.events[-1]
    assert event.source_object_ids == ["source-docx-1"]
    assert "Erster Absatz" not in str(event.metadata)
    assert event.metadata["content_persisted"] is False


def test_import_preview_denies_unreadable_source_before_parser_dispatch() -> None:
    dispatched = False

    def forbidden_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        nonlocal dispatched
        dispatched = True
        return parser(request)

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=forbidden_parser,
    )

    with pytest.raises(OfficeImportPreviewDenied):
        service.preview(user_context=user(readable=False), command=command())
    assert dispatched is False


def test_import_preview_does_not_cross_tenants_or_leak_existence() -> None:
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )

    with pytest.raises(OfficeImportPreviewNotFound):
        service.preview(user_context=user(tenant_id="tenant-other"), command=command())


def test_import_preview_rejects_parser_evidence_for_different_bytes() -> None:
    def mismatched_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        return parser(request).__class__(**{**parser(request).__dict__, "input_hash": sha256_bytes(b"different")})

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=mismatched_parser,
    )

    with pytest.raises(OfficeImportPreviewInvalid, match="parser evidence"):
        service.preview(user_context=user(), command=command())


def test_import_preview_rejects_non_docx_source_before_parser_dispatch() -> None:
    dispatched = False

    def forbidden_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        nonlocal dispatched
        dispatched = True
        return parser(request)

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(mime_type="application/pdf"),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=forbidden_parser,
    )

    with pytest.raises(OfficeImportPreviewInvalid, match="not a DOCX"):
        service.preview(user_context=user(), command=command())
    assert dispatched is False


def test_native_schema_rejects_tampered_import_provenance() -> None:
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    document = service.preview(user_context=user(), command=command()).document
    document["attrs"]["importProvenance"]["sourceAclVersion"] = True

    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
