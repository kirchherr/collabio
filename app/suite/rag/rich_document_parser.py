from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from suite.rag.docx_images import extract_docx_images
from suite.rag.docx_lists import DocxListBuilder, DocxNumbering, UnsupportedDocxList, docx_list_reference
from suite.rag.docx_navigation import DocxNavigation, UnsupportedDocxNavigation, docx_navigation
from suite.rag.docx_running_text import UnsupportedDocxRunningText
from suite.rag.docx_sections import UnsupportedDocxSection, docx_section_layout
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
DOCX_RUN_FONT_SIZES = {str(size * 2): size for size in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48)}
DOCX_RUN_TEXT_COLORS = {
    "111827": "black",
    "475569": "slate",
    "B91C1C": "red",
    "9A3412": "orange",
    "166534": "green",
    "115E59": "teal",
    "1D4ED8": "blue",
    "7E22CE": "purple",
}
DOCX_PARAGRAPH_ALIGNMENTS = {"left": "left", "center": "center", "right": "right", "both": "justify"}
DOCX_PARAGRAPH_SPACING = {"0": 0, "120": 6, "240": 12, "360": 18, "480": 24}
DOCX_LINE_SPACING = {"240": "1", "276": "1.15", "360": "1.5", "480": "2"}
DOCX_PARAGRAPH_INDENTS = {"0": 0, "360": 18, "720": 36, "1080": 54, "1440": 72}


class UnsupportedDocxParagraphAlignment(ValueError):
    pass


class UnsupportedDocxParagraphSpacing(ValueError):
    pass


class UnsupportedDocxParagraphIndentation(ValueError):
    pass


class UnsupportedDocxParagraphPagination(ValueError):
    pass


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
            declarations = xml_bytes.replace(b"\x00", b"").upper()
            if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                raise ParserWorkerError("DOCX document.xml contains forbidden declarations")
            try:
                root = ElementTree.fromstring(xml_bytes)
            except ElementTree.ParseError as exc:
                raise ParserWorkerError("DOCX document.xml is not valid XML") from exc

            body = root.find(f"{W}body")
            if body is None:
                raise ParserWorkerError("DOCX document.xml has no body")
            blocks: list[dict[str, object]] = []
            following_profiles: dict[int, dict[str, object]] = {}
            try:
                first_profile, following_profiles = docx_section_layout(archive, root, body)
            except (UnsupportedDocxSection, UnsupportedDocxRunningText):
                # Text-only callers still receive the same extracted text. Office rejects this structure.
                blocks.append({"kind": "unsupported_section_layout"})
            else:
                if first_profile is not None:
                    blocks.append({"kind": "page_profile", **first_profile})
        images = extract_docx_images(content, root)
        navigation = None
        try:
            navigation = docx_navigation(root, body)
        except UnsupportedDocxNavigation:
            blocks.insert(0, {"kind": "unsupported_navigation"})
        text_lines: list[str] = []
        lists = DocxListBuilder(numbering, blocks)
        page_breaks = 0
        unsupported_alignment = False
        unsupported_spacing = False
        unsupported_indentation = False
        unsupported_pagination = False

        for index, element in enumerate(body):
            if index in following_profiles:
                lists.flush()
                blocks.append({"kind": "section_break", **following_profiles[index]})
            if element in images:
                lists.flush()
                if self._docx_page_break_before(element):
                    page_breaks += 1
                    if page_breaks > 100:
                        raise ParserWorkerError("DOCX page-break count exceeds the structured preview limit")
                    blocks.append({"kind": "page_break"})
                blocks.append(images[element])
                continue
            if element.tag == f"{W}p":
                segments = self._docx_paragraph_segments(element, navigation)
                has_page_break = any(segment is None for segment in segments)
                try:
                    list_reference = docx_list_reference(element)
                except UnsupportedDocxList:
                    lists.unsupported = True
                    list_reference = None
                level = self._docx_heading_level(element)
                paragraph_format: dict[str, object] = {}
                if list_reference is None:
                    try:
                        alignment = self._docx_paragraph_alignment(element)
                    except UnsupportedDocxParagraphAlignment:
                        unsupported_alignment = True
                    else:
                        if alignment is not None:
                            paragraph_format["text_align"] = alignment
                    try:
                        spacing = self._docx_paragraph_spacing(element)
                        if spacing and has_page_break:
                            raise UnsupportedDocxParagraphSpacing
                    except UnsupportedDocxParagraphSpacing:
                        unsupported_spacing = True
                    else:
                        paragraph_format.update(spacing)
                    try:
                        indentation = self._docx_paragraph_indentation(element)
                        if indentation and has_page_break:
                            raise UnsupportedDocxParagraphIndentation
                    except UnsupportedDocxParagraphIndentation:
                        unsupported_indentation = True
                    else:
                        paragraph_format.update(indentation)
                    try:
                        pagination = self._docx_paragraph_pagination(element)
                        if pagination and has_page_break:
                            raise UnsupportedDocxParagraphPagination
                    except UnsupportedDocxParagraphPagination:
                        unsupported_pagination = True
                    else:
                        paragraph_format.update(pagination)
                if has_page_break and (list_reference is not None or level is not None):
                    raise ParserWorkerError("DOCX page breaks inside headings or lists are outside preview scope")
                if has_page_break:
                    lists.flush()
                    for segment in segments:
                        if segment is None:
                            page_breaks += 1
                            if page_breaks > 100:
                                raise ParserWorkerError("DOCX page-break count exceeds the structured preview limit")
                            blocks.append({"kind": "page_break"})
                        elif self._docx_runs_text(segment).strip():
                            blocks.append({"kind": "paragraph", "runs": segment, **paragraph_format})
                            text_lines.append(self._docx_runs_text(segment))
                    continue
                runs = next((segment for segment in segments if segment is not None), [])
                text = self._docx_runs_text(runs)
                if not text.strip() and not any("bookmark" in run for run in runs):
                    if list_reference is not None:
                        lists.unsupported = True
                    lists.flush()
                    continue
                if text.strip():
                    text_lines.append(text)
                page_break_before = self._docx_page_break_before(element)
                if list_reference is not None:
                    if level is not None or page_break_before:
                        lists.unsupported = True
                    lists.append(list_reference, runs)
                    continue
                lists.flush()
                if level:
                    block = {"kind": "heading", "level": level, "runs": runs, **paragraph_format}
                else:
                    block = {"kind": "paragraph", "runs": runs, **paragraph_format}
                if page_break_before:
                    block["page_break_before"] = True
                blocks.append(block)
            elif element.tag == f"{W}tbl":
                lists.flush()
                table, lines = self._docx_table(element)
                if table is not None:
                    blocks.append(table)
                    text_lines.extend(lines)
            else:
                lists.flush()
        lists.flush()
        if lists.unsupported:
            blocks.insert(0, {"kind": "unsupported_list_layout"})
        if unsupported_alignment:
            blocks.insert(0, {"kind": "unsupported_paragraph_alignment"})
        if unsupported_spacing:
            blocks.insert(0, {"kind": "unsupported_paragraph_spacing"})
        if unsupported_indentation:
            blocks.insert(0, {"kind": "unsupported_paragraph_indentation"})
        if unsupported_pagination:
            blocks.insert(0, {"kind": "unsupported_paragraph_pagination"})
        return "\n".join(text_lines), tuple(blocks)

    def _docx_paragraph_text(self, paragraph: ElementTree.Element) -> str:
        return self._docx_runs_text(self._docx_paragraph_runs(paragraph))

    def _docx_paragraph_runs(self, paragraph: ElementTree.Element) -> list[dict[str, object]]:
        segments = self._docx_paragraph_segments(paragraph)
        if any(segment is None for segment in segments):
            raise ParserWorkerError("DOCX page breaks inside table cells are outside preview scope")
        return next((segment for segment in segments if segment is not None), [])

    def _docx_paragraph_segments(
        self, paragraph: ElementTree.Element, navigation: DocxNavigation | None = None
    ) -> list[list[dict[str, object]] | None]:
        revision_tags = {f"{W}del", f"{W}ins", f"{W}moveFrom", f"{W}moveTo"}
        if any(node.tag in revision_tags for node in paragraph.iter()):
            raise ParserWorkerError("DOCX tracked revisions are outside the structured preview scope")
        segments: list[list[dict[str, object]] | None] = [[]]
        for run in paragraph.iter():
            if navigation is not None and run in navigation.bookmarks:
                current = segments[-1]
                if current is not None:
                    current.append({"bookmark": navigation.bookmarks[run]})
            if run.tag != f"{W}r":
                continue
            properties = run.find(f"{W}rPr")
            marks = [mark for mark in DOCX_INLINE_MARKS if self._docx_run_mark_enabled(properties, mark)]
            style_attrs = {**self._docx_run_font_size(run), **self._docx_run_text_color(run)}
            parts: list[str] = []
            for node in run:
                if node.tag == f"{W}t":
                    parts.append(node.text or "")
                elif node.tag == f"{W}tab":
                    parts.append("\t")
                elif (
                    node.tag == f"{W}br" and node.get(f"{W}type", "textWrapping") == "page"
                ) or node.tag == f"{W}lastRenderedPageBreak":
                    self._append_docx_run_segment(segments, parts, marks, style_attrs)
                    segments.extend([None, []])
                elif node.tag in {f"{W}br", f"{W}cr"}:
                    parts.append("\n")
            self._append_docx_run_segment(segments, parts, marks, style_attrs)
            if navigation is not None and run in navigation.links:
                current = segments[-1]
                if current:
                    current[-1]["target"] = navigation.links[run]
        run_count = sum("text" in run for segment in segments if segment is not None for run in segment)
        if run_count > 4_000:
            raise ParserWorkerError("DOCX paragraph exceeds the structured run limit")
        return segments

    def _append_docx_run_segment(
        self,
        segments: list[list[dict[str, object]] | None],
        parts: list[str],
        marks: list[str],
        style_attrs: dict[str, object],
    ) -> None:
        if not parts:
            return
        current = segments[-1]
        if current is None:
            current = []
            segments.append(current)
        current.append({"text": "".join(parts), "marks": marks, **style_attrs})
        parts.clear()

    def _docx_run_font_size(self, run: ElementTree.Element) -> dict[str, object]:
        markers = run.findall(f"{W}rPr/{W}sz")
        complex_markers = run.findall(f"{W}rPr/{W}szCs")
        if not markers and not complex_markers and run.find(f"{W}sz") is None and run.find(f"{W}szCs") is None:
            return {}
        unsupported: dict[str, object] = {"unsupported_font_size": True}
        if (
            len(markers) != 1
            or len(complex_markers) > 1
            or len(run.findall(f"{W}rPr")) != 1
            or run.find(f"{W}sz") is not None
            or run.find(f"{W}szCs") is not None
            or run.find(f"{W}rPr/{W}cs") is not None
            or run.find(f"{W}rPr/{W}rtl") is not None
        ):
            return unsupported
        size = markers[0].get(f"{W}val", "")
        for marker in markers + complex_markers:
            if (
                len(marker)
                or (marker.text or "").strip()
                or set(marker.attrib) != {f"{W}val"}
                or marker.get(f"{W}val") != size
            ):
                return unsupported
        if size not in DOCX_RUN_FONT_SIZES:
            return unsupported
        return {"font_size": DOCX_RUN_FONT_SIZES[size]}

    def _docx_run_text_color(self, run: ElementTree.Element) -> dict[str, object]:
        markers = run.findall(f"{W}rPr/{W}color")
        misplaced = run.find(f"{W}color") is not None
        if not markers and not misplaced:
            return {}
        unsupported: dict[str, object] = {"unsupported_text_color": True}
        if len(markers) != 1 or len(run.findall(f"{W}rPr")) != 1 or misplaced:
            return unsupported
        marker = markers[0]
        raw = marker.get(f"{W}val", "")
        if len(marker) or (marker.text or "").strip() or set(marker.attrib) != {f"{W}val"} or len(raw) != 6:
            return unsupported
        color = DOCX_RUN_TEXT_COLORS.get(raw.upper())
        return unsupported if color is None else {"text_color": color}

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
        return "".join(str(run.get("text", "")) for run in runs)

    def _docx_heading_level(self, paragraph: ElementTree.Element) -> int | None:
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        value = "" if style is None else style.get(f"{W}val", "")
        normalized = value.casefold().replace(" ", "")
        match = re.fullmatch(r"(?:heading|berschrift|ueberschrift)([1-3])", normalized)
        return int(match.group(1)) if match else None

    def _docx_page_break_before(self, paragraph: ElementTree.Element) -> bool:
        value = paragraph.find(f"{W}pPr/{W}pageBreakBefore")
        if value is None:
            return False
        return value.get(f"{W}val", "true").casefold() not in {"0", "false", "off", "no"}

    def _docx_paragraph_alignment(self, paragraph: ElementTree.Element) -> str | None:
        markers = paragraph.findall(f"{W}pPr/{W}jc")
        if paragraph.find(f"{W}jc") is not None:
            raise UnsupportedDocxParagraphAlignment
        if not markers:
            return None
        if len(markers) != 1 or len(paragraph.findall(f"{W}pPr")) != 1:
            raise UnsupportedDocxParagraphAlignment
        marker = markers[0]
        alignment = DOCX_PARAGRAPH_ALIGNMENTS.get(marker.get(f"{W}val", ""))
        if alignment is None or len(marker) or (marker.text or "").strip() or set(marker.attrib) != {f"{W}val"}:
            raise UnsupportedDocxParagraphAlignment
        return alignment

    def _docx_paragraph_spacing(self, paragraph: ElementTree.Element) -> dict[str, object]:
        markers = paragraph.findall(f"{W}pPr/{W}spacing")
        if paragraph.find(f"{W}spacing") is not None:
            raise UnsupportedDocxParagraphSpacing
        if not markers:
            return {}
        if len(markers) != 1 or len(paragraph.findall(f"{W}pPr")) != 1:
            raise UnsupportedDocxParagraphSpacing
        marker = markers[0]
        if (
            len(marker)
            or (marker.text or "").strip()
            or set(marker.attrib) - {f"{W}{name}" for name in ("before", "after", "line", "lineRule")}
        ):
            raise UnsupportedDocxParagraphSpacing
        result: dict[str, object] = {}
        for name in ("before", "after"):
            value = marker.get(f"{W}{name}")
            if value is not None:
                if value not in DOCX_PARAGRAPH_SPACING:
                    raise UnsupportedDocxParagraphSpacing
                result[f"spacing_{name}"] = DOCX_PARAGRAPH_SPACING[value]
        line = marker.get(f"{W}line")
        rule = marker.get(f"{W}lineRule")
        if line is not None:
            if line not in DOCX_LINE_SPACING or rule not in {None, "auto"}:
                raise UnsupportedDocxParagraphSpacing
            result["line_spacing"] = DOCX_LINE_SPACING[line]
        elif rule is not None:
            raise UnsupportedDocxParagraphSpacing
        return result

    def _docx_paragraph_indentation(self, paragraph: ElementTree.Element) -> dict[str, object]:
        markers = paragraph.findall(f"{W}pPr/{W}ind")
        if paragraph.find(f"{W}ind") is not None:
            raise UnsupportedDocxParagraphIndentation
        if not markers:
            return {}
        if len(markers) != 1 or len(paragraph.findall(f"{W}pPr")) != 1:
            raise UnsupportedDocxParagraphIndentation
        marker = markers[0]
        if (
            len(marker)
            or (marker.text or "").strip()
            or set(marker.attrib) - {f"{W}{name}" for name in ("left", "right", "firstLine", "hanging")}
            or paragraph.find(f"{W}pPr/{W}bidi") is not None
            or paragraph.find(f"{W}pPr/{W}mirrorIndents") is not None
        ):
            raise UnsupportedDocxParagraphIndentation
        result: dict[str, object] = {}
        for name in ("left", "right"):
            value = marker.get(f"{W}{name}")
            if value is not None:
                if value not in DOCX_PARAGRAPH_INDENTS:
                    raise UnsupportedDocxParagraphIndentation
                result[f"indent_{name}"] = DOCX_PARAGRAPH_INDENTS[value]
        first, hanging = marker.get(f"{W}firstLine"), marker.get(f"{W}hanging")
        if first is not None and hanging is not None:
            raise UnsupportedDocxParagraphIndentation
        special = first if first is not None else hanging
        if special is not None:
            if special not in {"0", "360", "720"}:
                raise UnsupportedDocxParagraphIndentation
            points = DOCX_PARAGRAPH_INDENTS[special]
            result["special_indent"] = "none" if points == 0 else f"firstLine{points}"
            if hanging is not None and points:
                left = marker.get(f"{W}left")
                if left is None or DOCX_PARAGRAPH_INDENTS[left] < points:
                    raise UnsupportedDocxParagraphIndentation
                # Native hanging indents add padding before shifting the first line back.
                result["indent_left"] = DOCX_PARAGRAPH_INDENTS[left] - points
                result["special_indent"] = f"hanging{points}"
        return result

    def _docx_paragraph_pagination(self, paragraph: ElementTree.Element) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, field in (("keepNext", "keep_with_next"), ("keepLines", "keep_lines")):
            markers = paragraph.findall(f"{W}pPr/{W}{name}")
            if paragraph.find(f"{W}{name}") is not None:
                raise UnsupportedDocxParagraphPagination
            if not markers:
                continue
            if len(markers) != 1 or len(paragraph.findall(f"{W}pPr")) != 1:
                raise UnsupportedDocxParagraphPagination
            marker = markers[0]
            value = marker.get(f"{W}val", "true")
            if (
                len(marker)
                or (marker.text or "").strip()
                or set(marker.attrib) - {f"{W}val"}
                or value not in {"true", "1", "on", "false", "0", "off"}
            ):
                raise UnsupportedDocxParagraphPagination
            result[field] = value in {"true", "1", "on"}
        return result

    def _docx_numbering(self, archive: ZipFile) -> DocxNumbering:
        if "word/numbering.xml" not in archive.namelist():
            return DocxNumbering(None)
        xml_bytes = self._read_zip_member(archive, "word/numbering.xml")
        declarations = xml_bytes.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
            raise ParserWorkerError("DOCX numbering.xml contains forbidden declarations")
        try:
            root = ElementTree.fromstring(xml_bytes)
        except ElementTree.ParseError as exc:
            raise ParserWorkerError("DOCX numbering.xml is not valid XML") from exc
        return DocxNumbering(root)

    def _docx_table(self, table: ElementTree.Element) -> tuple[dict[str, object] | None, list[str]]:
        span_tags = {f"{W}gridSpan", f"{W}vMerge", f"{W}hMerge"}
        spans = {node for node in table.iter() if node.tag in span_tags}
        found_spans: set[ElementTree.Element] = set()
        physical_rows = table.findall(f"{W}tr")
        if len(physical_rows) > 200:
            raise ParserWorkerError("DOCX table is outside the structured preview limits")
        header_row = self._docx_table_header(table, physical_rows)
        explicit_layout = bool(spans or header_row)
        if explicit_layout and (
            sum(1 for _ in table.iter(f"{W}tbl")) != 1
            or any(node.tag in {f"{W}gridBefore", f"{W}gridAfter", f"{W}hMerge"} for node in table.iter())
        ):
            raise ParserWorkerError("DOCX explicit table layout is unsupported")
        rows: list[list[dict[str, object]]] = []
        simple_rows: list[list[list[dict[str, object]]]] = []
        text_lines: list[str] = []
        width: int | None = None
        for row in physical_rows:
            cells: list[dict[str, object]] = []
            simple_cells: list[list[dict[str, object]]] = []
            row_width = 0
            for cell in row.findall(f"{W}tc"):
                colspan, merge = 1, "none"
                if spans:
                    properties = cell.findall(f"{W}tcPr")
                    if len(properties) > 1:
                        raise ParserWorkerError("DOCX merged table cell properties are ambiguous")
                    if properties:
                        colspan, merge = self._docx_cell_span(properties[0], found_spans)
                row_width += colspan
                if row_width > 20:
                    raise ParserWorkerError("DOCX table is outside the structured preview limits")
                cell_runs: list[dict[str, object]] = []
                for paragraph in cell.findall(f"{W}p"):
                    paragraph_runs = self._docx_paragraph_runs(paragraph)
                    if not self._docx_runs_text(paragraph_runs).strip():
                        continue
                    if cell_runs:
                        cell_runs.append({"text": "\n", "marks": []})
                    cell_runs.extend(paragraph_runs)
                if merge == "continue" and cell_runs:
                    raise ParserWorkerError("DOCX vertical merge continuation contains text")
                cells.append({"runs": cell_runs, "colspan": colspan, "merge": merge})
                simple_cells.append(cell_runs)
            if cells:
                if width is None:
                    width = row_width
                if row_width != width:
                    raise ParserWorkerError("DOCX table is outside the structured preview limits")
                rows.append(cells)
                simple_rows.append(simple_cells)
                text_lines.append("\t".join(self._docx_runs_text(cell) for cell in simple_cells))
            elif explicit_layout:
                raise ParserWorkerError("DOCX explicit table layout has an empty physical row")
        if not rows:
            if spans:
                raise ParserWorkerError("DOCX merged table has no physical rows")
            return None, []
        if explicit_layout:
            grids = table.findall(f"{W}tblGrid")
            if (
                spans != found_spans
                or len(grids) > 1
                or (grids and (len(grids[0]) != width or any(child.tag != f"{W}gridCol" for child in grids[0])))
            ):
                raise ParserWorkerError("DOCX explicit table grid does not match its physical cells")
        block: dict[str, object] = (
            {"kind": "merged_table", "rows": rows} if spans else {"kind": "table", "rows": simple_rows}
        )
        if header_row:
            block["header_row"] = True
        return block, text_lines

    def _docx_table_header(self, table: ElementTree.Element, rows: list[ElementTree.Element]) -> bool:
        tag = f"{W}tblHeader"
        markers = set(table.iter(tag))
        if not markers:
            return False
        found: set[ElementTree.Element] = set()
        header = False
        for index, row in enumerate(rows):
            direct = row.findall(f"{W}trPr/{tag}")
            if not direct:
                continue
            if len(direct) != 1 or len(row.findall(f"{W}trPr")) != 1:
                raise ParserWorkerError("DOCX table header properties are ambiguous")
            marker = direct[0]
            if len(marker) or (marker.text or "").strip() or set(marker.attrib) - {f"{W}val"}:
                raise ParserWorkerError("DOCX table header marker is invalid")
            found.add(marker)
            value = marker.get(f"{W}val", "true")
            if value in {"0", "false", "off"}:
                continue
            if value not in {"1", "true", "on"}:
                raise ParserWorkerError("DOCX table header marker is invalid")
            if index != 0:
                raise ParserWorkerError("DOCX table header must be the first physical row")
            header = True
        if markers != found:
            raise ParserWorkerError("DOCX table header marker is outside physical row properties")
        return header

    def _docx_cell_span(self, properties: ElementTree.Element, found: set[ElementTree.Element]) -> tuple[int, str]:
        colspan, merge = 1, "none"
        horizontal = properties.findall(f"{W}gridSpan")
        vertical = properties.findall(f"{W}vMerge")
        if len(horizontal) > 1 or len(vertical) > 1:
            raise ParserWorkerError("DOCX merged table cell properties are ambiguous")
        for node in horizontal + vertical:
            if len(node) or (node.text or "").strip() or set(node.attrib) - {f"{W}val"}:
                raise ParserWorkerError("DOCX table span is invalid")
            found.add(node)
        if horizontal:
            value = horizontal[0].get(f"{W}val", "")
            if re.fullmatch(r"[1-9]|1[0-9]|20", value) is None:
                raise ParserWorkerError("DOCX table column span is invalid")
            colspan = int(value)
        if vertical:
            merge = vertical[0].get(f"{W}val", "continue")
            if merge not in {"restart", "continue"}:
                raise ParserWorkerError("DOCX table vertical merge is invalid")
        return colspan, merge

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
