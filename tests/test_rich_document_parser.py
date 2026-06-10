from __future__ import annotations

import base64
import json
import subprocess
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from suite.ai_control_plane.models import DataClass
from suite.rag.models import SourceDocument, VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.parser_worker import (
    ParserInputTooLargeError,
    ParserWorkerError,
    ParserWorkerRequest,
    ParserWorkerTextExtractor,
)
from suite.rag.repositories import InMemorySourceRepository
from suite.rag.rich_document_parser import (
    DOCX_MIME_TYPE,
    ODT_MIME_TYPE,
    PDF_MIME_TYPE,
    RichDocumentParserWorker,
)
from suite.rag.source_indexing import (
    DeterministicHashEmbeddingProvider,
    FixedSizeTextChunker,
    RepositorySourceResolver,
    SourceIndexCommand,
    SourceIndexingPipeline,
)
from suite.rag.vector_worker import VectorIndexWorker

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


@dataclass
class CapturingVectorIndexStore:
    upserted: list[VectorEmbeddingRecord] = field(default_factory=list)

    def mark_source_for_reindex(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        audit_event_id: str | None = None,
    ) -> int:
        return 0

    def upsert_embedding(self, record: VectorEmbeddingRecord) -> None:
        self.upserted.append(record)

    def delete_reindex_orphans(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        keep_chunk_ids: set[str],
        audit_event_id: str | None = None,
    ) -> int:
        return 0

    def transition_source_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> int:
        raise AssertionError("rich document parser tests must not perform lifecycle deletion")


def request_for(*, mime_type: str, content: bytes, source_object_type: str = "document") -> ParserWorkerRequest:
    return ParserWorkerRequest(
        tenant_id="tenant-1",
        source_object_id="doc-1",
        source_version_id="v1",
        source_object_type=source_object_type,
        mime_type=mime_type,
        content=content,
    )


def docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def odt_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<text:p>{paragraph}</text:p>" for paragraph in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<office:document-content "
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text>{body}</office:text></office:body>"
        "</office:document-content>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", xml)
    return buffer.getvalue()


def simple_pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n" + f"<< /Length {len(stream)} >>\n".encode("ascii") + b"stream\n" + stream + b"\nendstream\n"
        b"endobj\n%%EOF"
    )


def test_rich_document_parser_manifest_declares_isolation_and_formats() -> None:
    manifest = RichDocumentParserWorker().manifest()

    assert manifest.parser_name == "rich-document-parser-worker"
    assert set(manifest.supported_mime_types) == {DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE}
    assert "network_access_allowed=false" in manifest.isolation_requirements
    assert "external_processes_allowed=false" in manifest.isolation_requirements
    assert "no_direct_storage_mutation=true" in manifest.isolation_requirements


def test_compose_declares_isolated_rich_document_parser_service() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "\n  rich-document-parser:\n" in compose
    assert "python -m suite.rag.rich_document_parser_service --describe" in compose
    assert 'network_mode: "none"' in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "./app:/workspace/app:ro" in compose


def test_rich_document_parser_extracts_docx_text() -> None:
    worker = RichDocumentParserWorker()

    artifact = worker.parse(
        request_for(mime_type=DOCX_MIME_TYPE, content=docx_bytes("First paragraph", "Second paragraph"))
    )

    assert artifact.text == "First paragraph\nSecond paragraph"
    assert artifact.mime_type == DOCX_MIME_TYPE
    assert artifact.input_hash.startswith("sha256:")
    assert artifact.text_hash.startswith("sha256:")
    assert artifact.warnings == ()


def test_rich_document_parser_extracts_odt_text() -> None:
    worker = RichDocumentParserWorker()

    artifact = worker.parse(request_for(mime_type=ODT_MIME_TYPE, content=odt_bytes("ODT heading", "ODT body")))

    assert artifact.text == "ODT heading\nODT body"
    assert artifact.mime_type == ODT_MIME_TYPE


def test_rich_document_parser_extracts_simple_pdf_text() -> None:
    worker = RichDocumentParserWorker()

    artifact = worker.parse(request_for(mime_type=PDF_MIME_TYPE, content=simple_pdf_bytes("PDF body text")))

    assert artifact.text == "PDF body text"
    assert artifact.mime_type == PDF_MIME_TYPE
    assert artifact.warnings == ("basic PDF text parser used; scanned or complex PDFs require a dedicated engine",)


def test_rich_document_parser_enforces_archive_size_limit() -> None:
    worker = RichDocumentParserWorker(max_archive_uncompressed_bytes=4)

    with pytest.raises(ParserInputTooLargeError, match="uncompressed byte limit"):
        worker.parse(request_for(mime_type=DOCX_MIME_TYPE, content=docx_bytes("too large")))


def test_rich_document_parser_rejects_missing_docx_body() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("custom.xml", "<root />")
    worker = RichDocumentParserWorker()

    with pytest.raises(ParserWorkerError, match=r"missing word/document\.xml"):
        worker.parse(request_for(mime_type=DOCX_MIME_TYPE, content=buffer.getvalue()))


def test_rich_document_parser_text_extractor_feeds_docx_bytes_into_indexing_pipeline() -> None:
    store = CapturingVectorIndexStore()
    repository = InMemorySourceRepository(
        documents={
            "docx-1": SourceDocument(
                object_id="docx-1",
                version_id="v1",
                title="Policy document",
                text="",
                classification=DataClass.INTERNAL,
                mime_type=DOCX_MIME_TYPE,
                content_bytes=docx_bytes("Index this DOCX body."),
            )
        }
    )
    pipeline = SourceIndexingPipeline(
        resolver=RepositorySourceResolver(
            repository,
            source_object_type="document",
            created_at_clock=lambda: "2026-06-10T00:00:00Z",
        ),
        text_extractor=ParserWorkerTextExtractor(RichDocumentParserWorker()),
        chunker=FixedSizeTextChunker(max_characters=512),
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=3),
        worker=VectorIndexWorker(store),
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:01:00Z",
    )

    result = pipeline.index_source(
        SourceIndexCommand(
            tenant_id="tenant-1",
            source_object_id="docx-1",
            source_version_id="v1",
            audit_event_id="audit-docx-index",
        )
    )

    assert result.chunk_count == 1
    assert store.upserted[0].metadata.source_object_id == "docx-1"
    assert store.upserted[0].content_byte_length == len(b"Index this DOCX body.")
    assert store.upserted[0].audit_event_id == "audit-docx-index"


def test_rich_document_parser_service_describes_worker_manifest() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "suite.rag.rich_document_parser_service", "--describe"],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads(result.stdout)
    assert set(manifest["supported_mime_types"]) == {DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE}
    assert "network_access_allowed=false" in manifest["isolation_requirements"]


def test_rich_document_parser_service_parses_base64_payload() -> None:
    payload = {
        "tenant_id": "tenant-1",
        "source_object_id": "doc-1",
        "source_version_id": "v1",
        "source_object_type": "document",
        "mime_type": DOCX_MIME_TYPE,
        "content_base64": base64.b64encode(docx_bytes("CLI DOCX body")).decode("ascii"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "suite.rag.rich_document_parser_service"],
        input=json.dumps(payload),
        check=True,
        capture_output=True,
        text=True,
    )

    artifact = json.loads(result.stdout)
    assert artifact["text"] == "CLI DOCX body"
    assert artifact["mime_type"] == DOCX_MIME_TYPE
