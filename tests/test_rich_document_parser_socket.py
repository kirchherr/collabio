from __future__ import annotations

import socket
import threading
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from suite.rag.office_active_content import OfficeActiveContentBlockedError
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.rag.rich_document_parser_socket import (
    handle_rich_document_parser_connection,
    parse_rich_document,
)


def docx_bytes(*, macro: bool = False) -> bytes:
    from io import BytesIO

    target = BytesIO()
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + (
                '<Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/>'
                if macro
                else ""
            )
            + "</Types>",
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Sicherer Inhalt</w:t></w:r></w:p></w:body></w:document>",
        )
        if macro:
            archive.writestr("word/vbaProject.bin", b"blocked")
    return target.getvalue()


def parse_once(socket_path: Path, request: ParserWorkerRequest) -> ParsedTextArtifact:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)

    def handle() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                handle_rich_document_parser_connection(connection, worker=RichDocumentParserWorker())
        finally:
            listener.close()

    thread = threading.Thread(target=handle, daemon=True)
    thread.start()
    try:
        return parse_rich_document(request, socket_path=str(socket_path), timeout_seconds=2)
    finally:
        thread.join(timeout=2)


def request_for(content: bytes) -> ParserWorkerRequest:
    return ParserWorkerRequest(
        tenant_id="tenant-office",
        source_object_id="source-docx-1",
        source_version_id="v7",
        source_object_type="document",
        mime_type=DOCX_MIME_TYPE,
        content=content,
        filename="source.docx",
    )


def test_socket_transport_returns_hash_bound_flattened_text(tmp_path: Path) -> None:
    artifact = parse_once(tmp_path / "parser.sock", request_for(docx_bytes()))

    assert artifact.text == "Sicherer Inhalt"
    assert artifact.parser_name == "rich-document-parser-worker"
    assert artifact.source_object_type == "document"
    assert artifact.document_blocks == ({"kind": "paragraph", "runs": [{"text": "Sicherer Inhalt", "marks": []}]},)
    assert artifact.document_blocks_hash.startswith("sha256:")


def test_socket_transport_preserves_active_content_block(tmp_path: Path) -> None:
    with pytest.raises(OfficeActiveContentBlockedError):
        parse_once(tmp_path / "parser.sock", request_for(docx_bytes(macro=True)))
