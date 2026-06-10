from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from suite.rag.parser_worker import (
    ParsedTextArtifact,
    ParserInputTooLargeError,
    ParserSandboxPolicy,
    ParserWorkerError,
    ParserWorkerRequest,
    UnsupportedParserInputError,
    normalize_extracted_text,
    sha256_bytes,
)

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ODT_MIME_TYPE = "application/vnd.oasis.opendocument.text"
PDF_MIME_TYPE = "application/pdf"
RICH_DOCUMENT_MIME_TYPES = frozenset({DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE})


@dataclass(frozen=True)
class RichDocumentParserManifest:
    parser_name: str
    parser_version: str
    supported_mime_types: tuple[str, ...]
    isolation_requirements: tuple[str, ...]


class RichDocumentParserWorker:
    def __init__(
        self,
        *,
        policy: ParserSandboxPolicy | None = None,
        parser_name: str = "rich-document-parser-worker",
        parser_version: str = "1",
        max_archive_uncompressed_bytes: int = 20_000_000,
        max_pdf_stream_bytes: int = 10_000_000,
    ) -> None:
        self.policy = policy or ParserSandboxPolicy(
            allowed_source_object_types=frozenset({"document", "attachment", "procedure_doc"}),
            allowed_mime_types=RICH_DOCUMENT_MIME_TYPES,
            max_input_bytes=25_000_000,
            max_extracted_characters=2_000_000,
        )
        self.parser_name = parser_name
        self.parser_version = parser_version
        self.max_archive_uncompressed_bytes = max_archive_uncompressed_bytes
        self.max_pdf_stream_bytes = max_pdf_stream_bytes

    def manifest(self) -> RichDocumentParserManifest:
        return RichDocumentParserManifest(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            supported_mime_types=tuple(sorted(RICH_DOCUMENT_MIME_TYPES)),
            isolation_requirements=(
                "network_access_allowed=false",
                "external_processes_allowed=false",
                "read_only_filesystem=true",
                "no_direct_storage_mutation=true",
                "no_direct_vector_writes=true",
            ),
        )

    def parse(self, request: ParserWorkerRequest) -> ParsedTextArtifact:
        mime_type = self.policy.validate(request)
        if self.policy.network_access_allowed:
            raise ParserWorkerError("rich document parser must run without network access")
        if self.policy.external_processes_allowed:
            raise ParserWorkerError("rich document parser must not spawn external processes")

        warnings: tuple[str, ...] = ()
        if mime_type == DOCX_MIME_TYPE:
            text = self._parse_docx(request.content)
        elif mime_type == ODT_MIME_TYPE:
            text = self._parse_odt(request.content)
        elif mime_type == PDF_MIME_TYPE:
            text = self._parse_pdf(request.content)
            warnings = ("basic PDF text parser used; scanned or complex PDFs require a dedicated engine",)
        else:
            raise UnsupportedParserInputError(f"unsupported rich document mime type: {mime_type}")

        normalized = normalize_extracted_text(text)
        if not normalized:
            raise ParserWorkerError("rich document parser output is empty after extraction")
        if len(normalized) > self.policy.max_extracted_characters:
            raise ParserInputTooLargeError("rich document parser output exceeds configured character limit")

        return ParsedTextArtifact(
            text=normalized,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            source_object_type=request.source_object_type,
            mime_type=mime_type,
            input_hash=sha256_bytes(request.content),
            text_hash=sha256_bytes(normalized.encode("utf-8")),
            text_byte_length=len(normalized.encode("utf-8")),
            warnings=warnings,
        )

    def _parse_docx(self, content: bytes) -> str:
        with self._open_zip(content) as archive:
            xml_bytes = self._read_zip_member(archive, "word/document.xml")
        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            raise ParserWorkerError("DOCX document.xml is not valid XML") from exc

        paragraphs: list[str] = []
        for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            text = "".join(
                node.text or ""
                for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            )
            if text.strip():
                paragraphs.append(text)
        return "\n".join(paragraphs)

    def _parse_odt(self, content: bytes) -> str:
        with self._open_zip(content) as archive:
            xml_bytes = self._read_zip_member(archive, "content.xml")
        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            raise ParserWorkerError("ODT content.xml is not valid XML") from exc

        text_names = {
            "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}h",
            "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p",
        }
        paragraphs = ["".join(element.itertext()) for element in root.iter() if element.tag in text_names]
        return "\n".join(paragraph for paragraph in paragraphs if paragraph.strip())

    def _parse_pdf(self, content: bytes) -> str:
        streams = self._pdf_streams(content)
        text_chunks: list[str] = []
        for stream in streams:
            text_chunks.extend(self._pdf_literal_strings(stream))
        return "\n".join(text_chunks)

    def _open_zip(self, content: bytes) -> ZipFile:
        try:
            archive = ZipFile(BytesIO(content))
        except BadZipFile as exc:
            raise ParserWorkerError("rich document input is not a valid zip container") from exc

        total_uncompressed = sum(member.file_size for member in archive.infolist())
        if total_uncompressed > self.max_archive_uncompressed_bytes:
            archive.close()
            raise ParserInputTooLargeError("rich document archive exceeds uncompressed byte limit")
        return archive

    def _read_zip_member(self, archive: ZipFile, name: str) -> bytes:
        if name not in archive.namelist():
            raise ParserWorkerError(f"rich document archive is missing {name}")
        return archive.read(name)

    def _pdf_streams(self, content: bytes) -> list[bytes]:
        streams: list[bytes] = []
        for match in re.finditer(rb"(?s)(.*?)stream\r?\n(.*?)\r?\nendstream", content):
            header = match.group(1)[-500:]
            stream = match.group(2)
            if len(stream) > self.max_pdf_stream_bytes:
                raise ParserInputTooLargeError("PDF stream exceeds configured byte limit")
            if b"/FlateDecode" in header:
                try:
                    stream = zlib.decompress(stream)
                except zlib.error as exc:
                    raise ParserWorkerError("failed to decompress PDF FlateDecode stream") from exc
            streams.append(stream)
        if not streams:
            raise ParserWorkerError("PDF contains no extractable content streams")
        return streams

    def _pdf_literal_strings(self, stream: bytes) -> list[str]:
        values: list[str] = []
        index = 0
        while index < len(stream):
            if stream[index : index + 1] != b"(":
                index += 1
                continue
            value, index = self._read_pdf_literal_string(stream, index + 1)
            decoded = value.decode("latin-1").strip()
            if decoded:
                values.append(decoded)
        return values

    def _read_pdf_literal_string(self, stream: bytes, start: int) -> tuple[bytes, int]:
        value = bytearray()
        depth = 1
        index = start
        while index < len(stream):
            byte = stream[index]
            if byte == 92:
                index += 1
                if index < len(stream):
                    value.append(stream[index])
            elif byte == 40:
                depth += 1
                value.append(byte)
            elif byte == 41:
                depth -= 1
                if depth == 0:
                    return bytes(value), index + 1
                value.append(byte)
            else:
                value.append(byte)
            index += 1
        raise ParserWorkerError("PDF literal string is unterminated")
