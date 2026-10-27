from __future__ import annotations

from dataclasses import replace

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
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks, sha256_bytes
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
    object_id: str = "source-docx-1",
    version_id: str = "v7",
    title: str = "Importierte Notiz",
    acl_version: int = 4,
) -> SourceObjectRecord:
    draft = SourceObjectMetadata(
        tenant_id="tenant-office",
        object_id=object_id,
        object_type=SourceObjectType.DOCUMENT,
        version_id=version_id,
        title=title,
        owner_principal_id="editor",
        created_by="editor",
        created_at_utc="2026-10-27T08:00:00Z",
        updated_at_utc="2026-10-27T08:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        kms_key_ref="kms://tenant-office/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=f"audit:{object_id}-{version_id}",
        source_system="collabio-test",
        mime_type=mime_type,
        acl_hash=f"sha256:{object_id}-acl",
        acl_version=acl_version,
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
    blocks = (
        {"kind": "heading", "level": 1, "text": "Erster Absatz"},
        {"kind": "bullet_list", "items": ["Zweiter Absatz"]},
        {"kind": "table", "rows": [["A", "B"], ["1", "2"]]},
    )
    text = "Erster Absatz\nZweiter Absatz\nA\tB\n1\t2"
    return ParsedTextArtifact(
        text=text,
        parser_name="rich-document-parser-worker",
        parser_version="1",
        source_object_type=request.source_object_type,
        mime_type=DOCX_MIME_TYPE,
        input_hash=sha256_bytes(request.content),
        text_hash=sha256_bytes(text.encode("utf-8")),
        text_byte_length=len(text.encode("utf-8")),
        warnings=("non-executable security markers require review",),
        document_blocks=blocks,
        document_blocks_hash=hash_document_blocks(blocks),
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
    assert [entry["type"] for entry in response.document["content"]] == ["heading", "bulletList", "table"]
    assert response.document["content"][0]["content"][0]["text"] == "Erster Absatz"
    assert response.document["content"][1]["content"][0]["content"][0]["content"][0]["text"] == "Zweiter Absatz"
    assert response.document["attrs"]["importProvenance"] == {
        "sourceObjectId": "source-docx-1",
        "sourceVersionId": "v7",
        "sourceContentHash": record.metadata.content_hash,
        "sourceAclVersion": 4,
        "parserProfileId": "rich-document-parser-worker:1",
        "parserTextHash": response.parser_text_hash,
        "parserStructureHash": response.parser_structure_hash,
        "importScope": "bounded_structured_docx_preview",
    }
    event = audit.events[-1]
    assert event.source_object_ids == ["source-docx-1"]
    assert "Erster Absatz" not in str(event.metadata)
    assert event.metadata["content_persisted"] is False


def test_import_source_discovery_returns_only_current_acl_authorized_docx_metadata() -> None:
    old = source_record(version_id="v1", title="Alter Stand", acl_version=1)
    current = source_record(content=b"current", version_id="v2", title="Richtlinie Alpha", acl_version=2)
    hidden = source_record(content=b"hidden", object_id="source-hidden", title="Verdeckt")
    pdf = source_record(content=b"pdf", object_id="source-pdf", mime_type="application/pdf")
    unsafe = source_record(content=b"unsafe", object_id="source-unsafe", title="x" * 201)
    audit = InMemoryAuditLogger()
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((old, current, hidden, pdf, unsafe)),
        audit=audit,
        parser_dispatch=parser,
    )

    readable_user = user().model_copy(update={"readable_object_ids": {"source-docx-1", "source-unsafe"}})
    response = service.discover_sources(user_context=readable_user, query="", limit=10)

    assert [(item.source_object_id, item.source_version_id) for item in response.items] == [("source-docx-1", "v2")]
    assert response.content_returned is False
    assert response.current_acl_validated is True
    assert audit.events[-1].metadata == {
        "module_id": "office_documents",
        "surface": "api",
        "result_count": 1,
        "query_supplied": False,
        "content_returned": False,
        "current_acl_validated": True,
    }


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


def test_native_schema_keeps_legacy_flattened_import_provenance_readable() -> None:
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    document = service.preview(user_context=user(), command=command()).document
    provenance = document["attrs"]["importProvenance"]
    provenance.pop("parserStructureHash")
    provenance["importScope"] = "bounded_flattened_text_preview"

    assert validate_office_document(document)["attrs"]["importProvenance"] == provenance


def test_import_preview_maps_inline_runs_and_rejects_text_structure_drift() -> None:
    runs = (
        {
            "kind": "paragraph",
            "runs": [
                {"text": "Fett", "marks": ["bold"]},
                {"text": " und kursiv", "marks": ["italic", "underline"]},
            ],
        },
    )

    def formatted_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        text = "Fett und kursiv"
        return ParsedTextArtifact(
            text=text,
            parser_name="rich-document-parser-worker",
            parser_version="1",
            source_object_type=request.source_object_type,
            mime_type=request.mime_type,
            input_hash=sha256_bytes(request.content),
            text_hash=sha256_bytes(text.encode("utf-8")),
            text_byte_length=len(text.encode("utf-8")),
            document_blocks=runs,
            document_blocks_hash=hash_document_blocks(runs),
        )

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=formatted_parser,
    )
    document = service.preview(user_context=user(), command=command()).document
    assert document["content"][0]["content"] == [
        {"type": "text", "text": "Fett", "marks": [{"type": "bold"}]},
        {
            "type": "text",
            "text": " und kursiv",
            "marks": [{"type": "italic"}, {"type": "underline"}],
        },
    ]

    def drifting_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = formatted_parser(request)
        return replace(
            artifact,
            text="anderer Text",
            text_hash=sha256_bytes(b"anderer Text"),
            text_byte_length=len(b"anderer Text"),
        )

    drift_service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=drifting_parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="text and structured content"):
        drift_service.preview(user_context=user(), command=command())
