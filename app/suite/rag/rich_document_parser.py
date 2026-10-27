from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from suite.rag.office_active_content import DOCM_MIME_TYPE, enforce_office_active_content_policy
from suite.rag.parser_worker import (
    ParsedTextArtifact,
    ParserInputTooLargeError,
    ParserSandboxPolicy,
    ParserWorkerError,
    ParserWorkerRequest,
    UnsupportedParserInputError,
    hash_document_blocks,
    normalize_extracted_text,
    sha256_bytes,
)

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ODT_MIME_TYPE = "application/vnd.oasis.opendocument.text"
PDF_MIME_TYPE = "application/pdf"
RICH_DOCUMENT_MIME_TYPES = frozenset({DOCX_MIME_TYPE, ODT_MIME_TYPE, PDF_MIME_TYPE})
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NS}}}"
DOCX_INLINE_MARKS = ("bold", "italic", "underline", "strike")


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
                "active_content_execution_allowed=false",
            ),
        )

    def parse(self, request: ParserWorkerRequest) -> ParsedTextArtifact:
        claimed_mime_type = request.mime_type.partition(";")[0].strip().lower()
        if claimed_mime_type == DOCM_MIME_TYPE:
            enforce_office_active_content_policy(
                mime_type=claimed_mime_type,
                content=request.content,
                max_archive_uncompressed_bytes=self.max_archive_uncompressed_bytes,
                max_control_part_bytes=self.max_archive_uncompressed_bytes,
            )
        mime_type = self.policy.validate(request)
        if self.policy.network_access_allowed:
            raise ParserWorkerError("rich document parser must run without network access")
        if self.policy.external_processes_allowed:
            raise ParserWorkerError("rich document parser must not spawn external processes")

        active_content = enforce_office_active_content_policy(
            mime_type=mime_type,
            content=request.content,
            max_archive_uncompressed_bytes=self.max_archive_uncompressed_bytes,
            max_control_part_bytes=self.max_archive_uncompressed_bytes,
        )
        warnings: tuple[str, ...] = (
            ("non-executable security markers require review",) if active_content.review_markings else ()
        )
        document_blocks: tuple[dict[str, object], ...] = ()
        if mime_type == DOCX_MIME_TYPE:
            text, document_blocks = self._parse_docx(request.content)
        elif mime_type == ODT_MIME_TYPE:
            text = self._parse_odt(request.content)
        elif mime_type == PDF_MIME_TYPE:
            text = self._parse_pdf(request.content)
            warnings = (*warnings, "basic PDF text parser used; scanned or complex PDFs require a dedicated engine")
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
            document_blocks=document_blocks,
            document_blocks_hash=hash_document_blocks(document_blocks),
        )

    def _parse_docx(self, content: bytes) -> tuple[str, tuple[dict[str, object], ...]]:
        with self._open_zip(content) as archive:
            xml_bytes = self._read_zip_member(archive, "word/document.xml")
            numbering = self._docx_numbering(archive)
        if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
            raise ParserWorkerError("DOCX document.xml contains forbidden declarations")
        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            raise ParserWorkerError("DOCX document.xml is not valid XML") from exc

        body = root.find(f"{W}body")
        if body is None:
            raise ParserWorkerError("DOCX document.xml has no body")
        blocks: list[dict[str, object]] = []
        text_lines: list[str] = []
        list_kind: str | None = None
        list_items: list[list[dict[str, object]]] = []
        page_breaks = 0

        def flush_list() -> None:
            nonlocal list_kind, list_items
            if list_kind is not None and list_items:
                blocks.append({"kind": list_kind, "items": list_items})
            list_kind, list_items = None, []

        for element in body:
            if element.tag == f"{W}p":
                segments = self._docx_paragraph_segments(element)
                has_page_break = any(segment is None for segment in segments)
                number_id = self._docx_number_id(element)
                level = self._docx_heading_level(element)
                if has_page_break and (number_id is not None or level is not None):
                    raise ParserWorkerError("DOCX page breaks inside headings or lists are outside preview scope")
                if has_page_break:
                    flush_list()
                    for segment in segments:
                        if segment is None:
                            page_breaks += 1
                            if page_breaks > 100:
                                raise ParserWorkerError("DOCX page-break count exceeds the structured preview limit")
                            blocks.append({"kind": "page_break"})
                        elif self._docx_runs_text(segment).strip():
                            blocks.append({"kind": "paragraph", "runs": segment})
                            text_lines.append(self._docx_runs_text(segment))
                    continue
                runs = next((segment for segment in segments if segment is not None), [])
                text = self._docx_runs_text(runs)
                if not text.strip():
                    flush_list()
                    continue
                text_lines.append(text)
                if number_id is not None:
                    kind = "bullet_list" if numbering.get(number_id, "bullet") == "bullet" else "ordered_list"
                    if list_kind != kind:
                        flush_list()
                        list_kind = kind
                    list_items.append(runs)
                    continue
                flush_list()
                page_break_before = self._docx_page_break_before(element)
                if level:
                    block = {"kind": "heading", "level": level, "runs": runs}
                else:
                    block = {"kind": "paragraph", "runs": runs}
                if page_break_before:
                    block["page_break_before"] = True
                blocks.append(block)
            elif element.tag == f"{W}tbl":
                flush_list()
                rows = self._docx_table_rows(element)
                if rows:
                    blocks.append({"kind": "table", "rows": rows})
                    text_lines.extend("\t".join(self._docx_runs_text(cell) for cell in row) for row in rows)
        flush_list()
        return "\n".join(text_lines), tuple(blocks)

    def _docx_paragraph_text(self, paragraph: ElementTree.Element) -> str:
        return self._docx_runs_text(self._docx_paragraph_runs(paragraph))

    def _docx_paragraph_runs(self, paragraph: ElementTree.Element) -> list[dict[str, object]]:
        segments = self._docx_paragraph_segments(paragraph)
        if any(segment is None for segment in segments):
            raise ParserWorkerError("DOCX page breaks inside table cells are outside preview scope")
        return next((segment for segment in segments if segment is not None), [])

    def _docx_paragraph_segments(self, paragraph: ElementTree.Element) -> list[list[dict[str, object]] | None]:
        revision_tags = {f"{W}del", f"{W}ins", f"{W}moveFrom", f"{W}moveTo"}
        if any(node.tag in revision_tags for node in paragraph.iter()):
            raise ParserWorkerError("DOCX tracked revisions are outside the structured preview scope")
        segments: list[list[dict[str, object]] | None] = [[]]
        for run in paragraph.iter(f"{W}r"):
            properties = run.find(f"{W}rPr")
            marks = [mark for mark in DOCX_INLINE_MARKS if self._docx_run_mark_enabled(properties, mark)]
            parts: list[str] = []
            for node in run:
                if node.tag == f"{W}t":
                    parts.append(node.text or "")
                elif node.tag == f"{W}tab":
                    parts.append("\t")
                elif (
                    node.tag == f"{W}br" and node.get(f"{W}type", "textWrapping") == "page"
                ) or node.tag == f"{W}lastRenderedPageBreak":
                    self._append_docx_run_segment(segments, parts, marks)
                    segments.extend([None, []])
                elif node.tag in {f"{W}br", f"{W}cr"}:
                    parts.append("\n")
            self._append_docx_run_segment(segments, parts, marks)
        run_count = sum(len(segment) for segment in segments if segment is not None)
        if run_count > 4_000:
            raise ParserWorkerError("DOCX paragraph exceeds the structured run limit")
        return segments

    def _append_docx_run_segment(
        self,
        segments: list[list[dict[str, object]] | None],
        parts: list[str],
        marks: list[str],
    ) -> None:
        if not parts:
            return
        current = segments[-1]
        if current is None:
            current = []
            segments.append(current)
        current.append({"text": "".join(parts), "marks": marks})
        parts.clear()

    def _docx_run_mark_enabled(self, properties: ElementTree.Element | None, mark: str) -> bool:
        if properties is None:
            return False
        tag_names = {"bold": ("b",), "italic": ("i",), "underline": ("u",), "strike": ("strike", "dstrike")}
        for tag_name in tag_names[mark]:
            value = properties.find(f"{W}{tag_name}")
            if value is None:
                continue
            raw = value.get(f"{W}val", "true").casefold()
            return raw not in {"0", "false", "off", "no", "none"}
        return False

    def _docx_runs_text(self, runs: list[dict[str, object]]) -> str:
        return "".join(str(run["text"]) for run in runs)

    def _docx_heading_level(self, paragraph: ElementTree.Element) -> int | None:
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        value = "" if style is None else style.get(f"{W}val", "")
        normalized = value.casefold().replace(" ", "")
        match = re.fullmatch(r"(?:heading|berschrift|ueberschrift)([1-3])", normalized)
        return int(match.group(1)) if match else None

    def _docx_number_id(self, paragraph: ElementTree.Element) -> str | None:
        value = paragraph.find(f"{W}pPr/{W}numPr/{W}numId")
        return None if value is None else value.get(f"{W}val")

    def _docx_page_break_before(self, paragraph: ElementTree.Element) -> bool:
        value = paragraph.find(f"{W}pPr/{W}pageBreakBefore")
        if value is None:
            return False
        return value.get(f"{W}val", "true").casefold() not in {"0", "false", "off", "no"}

    def _docx_numbering(self, archive: ZipFile) -> dict[str, str]:
        if "word/numbering.xml" not in archive.namelist():
            return {}
        xml_bytes = self._read_zip_member(archive, "word/numbering.xml")
        if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
            raise ParserWorkerError("DOCX numbering.xml contains forbidden declarations")
        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            raise ParserWorkerError("DOCX numbering.xml is not valid XML") from exc
        abstract_formats: dict[str, str] = {}
        for abstract_number in root.findall(f"{W}abstractNum"):
            identifier = abstract_number.get(f"{W}abstractNumId")
            level = abstract_number.find(f"{W}lvl[@{W}ilvl='0']/{W}numFmt")
            if identifier and level is not None:
                abstract_formats[identifier] = level.get(f"{W}val", "bullet")
        result: dict[str, str] = {}
        for number in root.findall(f"{W}num"):
            identifier = number.get(f"{W}numId")
            abstract_reference = number.find(f"{W}abstractNumId")
            abstract_id = None if abstract_reference is None else abstract_reference.get(f"{W}val")
            if identifier and abstract_id:
                result[identifier] = abstract_formats.get(abstract_id, "bullet")
        return result

    def _docx_table_rows(self, table: ElementTree.Element) -> list[list[list[dict[str, object]]]]:
        rows: list[list[list[dict[str, object]]]] = []
        for row in table.findall(f"{W}tr"):
            cells: list[list[dict[str, object]]] = []
            for cell in row.findall(f"{W}tc"):
                if cell.find(f"{W}tcPr/{W}gridSpan") is not None or cell.find(f"{W}tcPr/{W}vMerge") is not None:
                    raise ParserWorkerError("DOCX merged tables are outside the structured preview scope")
                cell_runs: list[dict[str, object]] = []
                for paragraph in cell.findall(f"{W}p"):
                    paragraph_runs = self._docx_paragraph_runs(paragraph)
                    if not self._docx_runs_text(paragraph_runs).strip():
                        continue
                    if cell_runs:
                        cell_runs.append({"text": "\n", "marks": []})
                    cell_runs.extend(paragraph_runs)
                cells.append(cell_runs)
            if cells:
                rows.append(cells)
        if not rows:
            return []
        width = len(rows[0])
        if not 1 <= width <= 20 or len(rows) > 200 or any(len(row) != width for row in rows):
            raise ParserWorkerError("DOCX table is outside the structured preview limits")
        return rows

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
