"""ACL-checked, non-persisting native Office import previews."""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import pairwise
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_schema import (
    FONT_FAMILIES,
    FONT_SIZES,
    MAX_DOCUMENT_CHARACTERS,
    PARAGRAPH_VALUES,
    TEXT_COLORS,
    validate_office_document,
)
from suite.platform.office_docx_images import DocxPreviewImages, ImageNormalizer
from suite.platform.office_image_codec import normalize_image
from suite.rag.docx_lists import LIST_DEPTH, LIST_ITEMS, LIST_MAX_NUMBER
from suite.rag.docx_navigation import BOOKMARK_LIMIT, BOOKMARK_NAME, BOOKMARK_NUMBER, BOOKMARK_PREFIX, LINK_RUN_LIMIT
from suite.rag.docx_running_text import NATIVE_RUNNING_FIELD_PREFIX
from suite.rag.parser_worker import (
    ParsedTextArtifact,
    ParserWorkerRequest,
    hash_document_blocks,
    normalize_extracted_text,
    sha256_bytes,
)
from suite.rag.repositories import ReadableObjectAclAuthorizer
from suite.rag.rich_document_parser import DOCX_MIME_TYPE
from suite.rag.rich_document_parser_socket import parse_rich_document
from suite.storage.source_objects import (
    SourceObjectMetadata,
    SourceObjectRepository,
    build_source_object_manifest_hash,
    source_object_content_bytes,
)

OfficeInformationClassification = Literal["public", "internal", "confidential", "restricted"]
ParserDispatch = Callable[[ParserWorkerRequest], ParsedTextArtifact]
IMPORT_SOURCE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
DOCX_INLINE_MARKS = ("bold", "italic", "underline", "strike")


class OfficeImportSourceRepository(Protocol):
    def list_latest_metadata(
        self, *, tenant_id: str, limit: int = 100, mime_type: str | None = None
    ) -> tuple[SourceObjectMetadata, ...]: ...


class OfficeImportPreviewNotFound(LookupError):
    pass


class OfficeImportPreviewDenied(PermissionError):
    pass


class OfficeImportPreviewInvalid(ValueError):
    pass


class OfficeImportPreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    source_version_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class OfficeImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["office_import_preview.v2"] = "office_import_preview.v2"
    tenant_id: str
    source_object_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    source_version_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    source_title: str = Field(min_length=1, max_length=200)
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    information_classification: OfficeInformationClassification
    parser_profile_id: Literal["rich-document-parser-worker:1"] = "rich-document-parser-worker:1"
    parser_text_hash: str
    parser_structure_hash: str
    warnings: tuple[str, ...]
    document: dict[str, Any]
    content_persisted: Literal[False] = False
    save_requires_explicit_confirmation: Literal[True] = True
    fidelity_preserved: Literal[False] = False
    import_scope: Literal["bounded_structured_docx_preview"] = "bounded_structured_docx_preview"
    audit_event_id: str
    image_previews: tuple[dict[str, Any], ...] = ()


class OfficeImportSourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str
    source_version_id: str
    source_title: str
    updated_at_utc: str
    information_classification: OfficeInformationClassification
    content_byte_length: int = Field(ge=1)


class OfficeImportSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["office_import_sources.v1"] = "office_import_sources.v1"
    tenant_id: str
    items: tuple[OfficeImportSourceItem, ...]
    content_returned: Literal[False] = False
    current_acl_validated: Literal[True] = True
    audit_event_id: str


def _text_content(text: str) -> list[dict[str, str]]:
    return [] if not text else [{"type": "text", "text": text}]


def _docx_bookmark_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(BOOKMARK_PREFIX)
        and BOOKMARK_NUMBER.fullmatch(value.removeprefix(BOOKMARK_PREFIX)) is not None
    )


def _run_content(
    values: Any, *, allow_empty: bool = False, navigation: bool = False
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(values, list) or len(values) > 4_000 or (not values and not allow_empty):
        raise OfficeImportPreviewInvalid("parser inline structure is invalid")
    content: list[dict[str, Any]] = []
    plain_parts: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            raise OfficeImportPreviewInvalid("parser inline run is invalid")
        if navigation and set(value) == {"bookmark"}:
            bookmark = value["bookmark"]
            if (
                not isinstance(bookmark, dict)
                or set(bookmark) != {"id", "label"}
                or not _docx_bookmark_id(bookmark["id"])
                or not isinstance(bookmark["label"], str)
                or BOOKMARK_NAME.fullmatch(bookmark["label"]) is None
            ):
                raise OfficeImportPreviewInvalid("parser bookmark is invalid")
            content.append({"type": "bookmark", "attrs": bookmark})
            continue
        fields = set(value)
        linked = navigation and "target" in fields
        allowed = {"text", "marks", "font_family", "font_size", "text_color"} | ({"target"} if navigation else set())
        if not {"text", "marks"}.issubset(fields) or fields - allowed:
            raise OfficeImportPreviewInvalid("parser inline run is invalid")
        text = value["text"]
        marks = value["marks"]
        if (
            not isinstance(text, str)
            or not text
            or len(text) > MAX_DOCUMENT_CHARACTERS
            or not isinstance(marks, list)
            or any(not isinstance(mark, str) for mark in marks)
            or marks != [mark for mark in DOCX_INLINE_MARKS if mark in marks]
            or len(set(marks)) != len(marks)
        ):
            raise OfficeImportPreviewInvalid("parser inline run is invalid")
        node: dict[str, Any] = {"type": "text", "text": text}
        native_marks: list[dict[str, Any]] = [{"type": mark} for mark in marks]
        native_style: dict[str, Any] = {}
        if "font_family" in value:
            family = value["font_family"]
            if not isinstance(family, str) or family not in FONT_FAMILIES:
                raise OfficeImportPreviewInvalid("parser font family is invalid")
            native_style["fontFamily"] = family
        if "font_size" in value:
            size = value["font_size"]
            if type(size) is not int or size not in FONT_SIZES:
                raise OfficeImportPreviewInvalid("parser font size is invalid")
            native_style["fontSize"] = size
        if "text_color" in value:
            color = value["text_color"]
            if not isinstance(color, str) or color not in TEXT_COLORS:
                raise OfficeImportPreviewInvalid("parser text color is invalid")
            native_style["textColor"] = color
        if native_style:
            native_marks.append({"type": "textStyle", "attrs": native_style})
        if linked:
            if not _docx_bookmark_id(value["target"]) or any(char in text for char in "\r\n\t"):
                raise OfficeImportPreviewInvalid("parser internal link is invalid")
            native_marks.append({"type": "crossReference", "attrs": {"targetId": value["target"]}})
        if native_marks:
            node["marks"] = native_marks
        content.append(node)
        plain_parts.append(text)
    return content, "".join(plain_parts)


def _legacy_or_run_content(
    value: Any, *, allow_empty: bool = False, navigation: bool = False
) -> tuple[list[dict[str, Any]], str]:
    if isinstance(value, str):
        return _text_content(value), value
    return _run_content(value, allow_empty=allow_empty, navigation=navigation)


def _section_profile(value: dict[str, Any], *, section: bool) -> dict[str, Any]:
    if set(value) not in ({"kind", "page"}, {"kind", "page", "running"}) or not isinstance(value["page"], dict):
        raise OfficeImportPreviewInvalid("parser section profile is invalid")
    profile = {"page": value["page"]}
    if "running" in value:
        running = value["running"]
        if (
            not isinstance(running, dict)
            or set(running) != {"header", "footer"}
            or any(not isinstance(text, str) or NATIVE_RUNNING_FIELD_PREFIX in text for text in running.values())
        ):
            raise OfficeImportPreviewInvalid("parser running-text profile is invalid")
        profile["running"] = {**running, "numbering": "none"}
    elif section:
        profile["running"] = {"header": "", "footer": "", "numbering": "none"}
    return profile


def _list_tree(value: Any, text_lines: list[str], depth: int = 1) -> dict[str, Any]:
    if depth > LIST_DEPTH or not isinstance(value, dict):
        raise OfficeImportPreviewInvalid("parser nested list is invalid")
    kind = value.get("kind")
    if kind == "bullet_list" and set(value) == {"kind", "items"}:
        node: dict[str, Any] = {"type": "bulletList"}
    elif kind == "ordered_list" and set(value) == {"kind", "items", "start"} and type(value["start"]) is int:
        node = {"type": "orderedList", "attrs": {"start": value["start"]}}
    else:
        raise OfficeImportPreviewInvalid("parser nested list is invalid")
    items = value["items"]
    start = value.get("start", 1)
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= LIST_ITEMS
        or not 1 <= start <= LIST_MAX_NUMBER - len(items) + 1
    ):
        raise OfficeImportPreviewInvalid("parser nested list is invalid")
    native_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or set(item) not in ({"runs"}, {"runs", "child"}) or len(text_lines) >= 2_000:
            raise OfficeImportPreviewInvalid("parser nested list item is invalid")
        content, plain = _run_content(item["runs"])
        if not plain.strip():
            raise OfficeImportPreviewInvalid("parser nested list item is invalid")
        text_lines.append(plain)
        children = [{"type": "paragraph", "content": content}]
        if "child" in item:
            children.append(_list_tree(item["child"], text_lines, depth + 1))
        native_items.append({"type": "listItem", "content": children})
    node["content"] = native_items
    return node


def _merged_docx_table(rows: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise OfficeImportPreviewInvalid("parser merged table structure is invalid")
    native_rows: list[dict[str, Any]] = []
    lines: list[str] = []
    active: dict[tuple[int, int], dict[str, Any]] = {}
    width: int | None = None
    for row in rows:
        if not isinstance(row, list) or not 1 <= len(row) <= 20:
            raise OfficeImportPreviewInvalid("parser merged table row is invalid")
        cells: list[dict[str, Any]] = []
        text: list[str] = []
        following: dict[tuple[int, int], dict[str, Any]] = {}
        column = 0
        for entry in row:
            if not isinstance(entry, dict) or set(entry) != {"runs", "colspan", "merge"}:
                raise OfficeImportPreviewInvalid("parser merged table cell is invalid")
            span, merge = entry["colspan"], entry["merge"]
            if type(span) is not int or not 1 <= span <= 20 - column or merge not in ("none", "restart", "continue"):
                raise OfficeImportPreviewInvalid("parser table span is invalid")
            key = (column, span)
            column += span
            content, plain = _run_content(entry["runs"], allow_empty=True)
            text.append(plain)
            if merge == "continue":
                owner = active.get(key)
                if owner is None or content:
                    raise OfficeImportPreviewInvalid("parser table merge continuation is invalid")
                attrs = owner.setdefault("attrs", {})
                attrs["rowspan"] = attrs.get("rowspan", 1) + 1
                following[key] = owner
                continue
            cell: dict[str, Any] = {"type": "tableCell", "content": [{"type": "paragraph", "content": content}]}
            if span > 1:
                cell["attrs"] = {"colspan": span}
            cells.append(cell)
            if merge == "restart":
                following[key] = cell
        if width is None:
            width = column
        if column != width or not cells:
            raise OfficeImportPreviewInvalid("parser merged table grid is invalid")
        native_rows.append({"type": "tableRow", "content": cells})
        lines.append("\t".join(text))
        active = following
    return {"type": "table", "content": native_rows}, lines


def _simple_docx_table(rows: Any) -> tuple[dict[str, Any], list[str]]:
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= 200
        or not isinstance(rows[0], list)
        or not 1 <= len(rows[0]) <= 20
        or any(not isinstance(row, list) or len(row) != len(rows[0]) for row in rows)
    ):
        raise OfficeImportPreviewInvalid("parser table structure is invalid")
    native_rows: list[dict[str, Any]] = []
    lines: list[str] = []
    for row in rows:
        native_cells: list[dict[str, Any]] = []
        plain_cells: list[str] = []
        for cell in row:
            content, plain = _legacy_or_run_content(cell, allow_empty=True)
            native_cells.append({"type": "tableCell", "content": [{"type": "paragraph", "content": content}]})
            plain_cells.append(plain)
        native_rows.append({"type": "tableRow", "content": native_cells})
        lines.append("\t".join(plain_cells))
    return {"type": "table", "content": native_rows}, lines


def _structured_blocks(
    values: tuple[dict[str, Any], ...], image_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    if len(values) > 2_000:
        raise OfficeImportPreviewInvalid("parsed document exceeds structured preview limits")
    blocks: list[dict[str, Any]] = []
    text_lines: list[str] = []
    root_profile: dict[str, Any] = {}
    for index, value in enumerate(values):
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise OfficeImportPreviewInvalid("parser structure is invalid")
        kind = value["kind"]
        if kind == "page_profile" and index == 0:
            root_profile = _section_profile(value, section=False)
        elif kind == "section_break" and root_profile:
            blocks.append({"type": "sectionBreak", "attrs": _section_profile(value, section=True)})
        elif kind == "image" and image_builder is not None:
            try:
                blocks.append(image_builder(value))
            except (ValueError, TypeError, KeyError) as exc:
                raise OfficeImportPreviewInvalid("parser image evidence is invalid") from exc
        elif kind == "page_break" and set(value) == {"kind"}:
            blocks.append({"type": "pageBreak"})
        elif kind in {"paragraph", "heading"}:
            fields = set(value) - {"kind"}
            attrs: dict[str, Any] = {}
            if kind == "heading":
                level = value.get("level")
                if type(level) is not int or level not in {1, 2, 3}:
                    raise OfficeImportPreviewInvalid("parser heading level is invalid")
                attrs["level"] = level
                fields.remove("level")
            if fields != {"text"} and (
                "runs" not in fields
                or fields
                - {
                    "runs",
                    "page_break_before",
                    "text_align",
                    "spacing_before",
                    "spacing_after",
                    "line_spacing",
                    "indent_left",
                    "indent_right",
                    "special_indent",
                    "keep_with_next",
                    "keep_lines",
                }
            ):
                raise OfficeImportPreviewInvalid("parser paragraph structure is invalid")
            content, plain = _legacy_or_run_content(value.get("runs", value.get("text")), navigation=True)
            if "page_break_before" in value and type(value["page_break_before"]) is not bool:
                raise OfficeImportPreviewInvalid("parser paragraph page-break structure is invalid")
            if value.get("page_break_before") is True:
                attrs["pageBreakBefore"] = True
            if "text_align" in value:
                alignment = value["text_align"]
                if (
                    not isinstance(value["runs"], list)
                    or not isinstance(alignment, str)
                    or alignment not in PARAGRAPH_VALUES["textAlign"]
                ):
                    raise OfficeImportPreviewInvalid("parser paragraph alignment is invalid")
                attrs["textAlign"] = alignment
            for field, native in (
                ("spacing_before", "spacingBefore"),
                ("spacing_after", "spacingAfter"),
                ("line_spacing", "lineSpacing"),
            ):
                if field in value:
                    spacing = value[field]
                    expected_type = str if field == "line_spacing" else int
                    if (
                        not isinstance(value["runs"], list)
                        or type(spacing) is not expected_type
                        or spacing not in PARAGRAPH_VALUES[native]
                    ):
                        raise OfficeImportPreviewInvalid("parser paragraph spacing is invalid")
                    attrs[native] = spacing
            for field, native in (
                ("indent_left", "indentLeft"),
                ("indent_right", "indentRight"),
                ("special_indent", "specialIndent"),
            ):
                if field in value:
                    indentation = value[field]
                    expected_type = str if field == "special_indent" else int
                    if (
                        not isinstance(value["runs"], list)
                        or type(indentation) is not expected_type
                        or indentation not in PARAGRAPH_VALUES[native]
                    ):
                        raise OfficeImportPreviewInvalid("parser paragraph indentation is invalid")
                    attrs[native] = indentation
            for field, native in (("keep_with_next", "keepWithNext"), ("keep_lines", "keepLines")):
                if field in value:
                    if not isinstance(value["runs"], list) or type(value[field]) is not bool:
                        raise OfficeImportPreviewInvalid("parser paragraph pagination is invalid")
                    attrs[native] = value[field]
            blocks.append({"type": kind, "attrs": attrs, "content": content})
            if plain.strip() or not any(node["type"] == "bookmark" for node in content):
                text_lines.append(plain)
        elif kind == "list_tree" and set(value) == {"kind", "list"}:
            list_text: list[str] = []
            blocks.append(_list_tree(value["list"], list_text))
            text_lines.extend(list_text)
        elif kind in {"bullet_list", "ordered_list"} and set(value) == {"kind", "items"}:
            items = value["items"]
            if not isinstance(items, list) or not 1 <= len(items) <= 1_000:
                raise OfficeImportPreviewInvalid("parser list structure is invalid")
            native_items: list[dict[str, Any]] = []
            for item in items:
                content, plain = _legacy_or_run_content(item)
                native_items.append({"type": "listItem", "content": [{"type": "paragraph", "content": content}]})
                text_lines.append(plain)
            node: dict[str, Any] = {
                "type": "bulletList" if kind == "bullet_list" else "orderedList",
                "content": native_items,
            }
            if kind == "ordered_list":
                node["attrs"] = {"start": 1}
            blocks.append(node)
        elif kind in {"table", "merged_table"} and set(value) in ({"kind", "rows"}, {"kind", "rows", "header_row"}):
            table, table_text = (_merged_docx_table if kind == "merged_table" else _simple_docx_table)(value["rows"])
            if "header_row" in value:
                if value["header_row"] is not True:
                    raise OfficeImportPreviewInvalid("parser table header marker is invalid")
                for cell in table["content"][0]["content"]:
                    if cell.get("attrs", {}).get("rowspan", 1) != 1:
                        raise OfficeImportPreviewInvalid("parser table header merge crosses into the body")
                    cell["type"] = "tableHeader"
            blocks.append(table)
            text_lines.extend(table_text)
        else:
            raise OfficeImportPreviewInvalid("parser structure contains an unsupported block")
    if any(
        before["type"] == "sectionBreak" and after.get("attrs", {}).get("pageBreakBefore")
        for before, after in pairwise(blocks)
    ):
        raise OfficeImportPreviewInvalid("parser section boundary conflicts with a paragraph page break")
    _validate_navigation(blocks)
    return blocks, "\n".join(text_lines), root_profile


def _validate_navigation(blocks: list[dict[str, Any]]) -> None:
    bookmarks: set[str] = set()
    targets: list[str] = []
    for block in blocks:
        if block["type"] not in {"paragraph", "heading"}:
            continue
        for node in block["content"]:
            if node["type"] == "bookmark":
                bookmarks.add(node["attrs"]["id"])
            targets.extend(
                mark["attrs"]["targetId"] for mark in node.get("marks", []) if mark["type"] == "crossReference"
            )
    if len(bookmarks) > BOOKMARK_LIMIT or len(targets) > LINK_RUN_LIMIT or not bookmarks.issuperset(targets):
        raise OfficeImportPreviewInvalid("parser internal link targets are invalid")


def _native_document(
    text: str,
    *,
    document_blocks: tuple[dict[str, Any], ...],
    source_object_id: str,
    source_version_id: str,
    source_content_hash: str,
    source_acl_version: int,
    parser_text_hash: str,
    parser_structure_hash: str,
    image_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(text) > MAX_DOCUMENT_CHARACTERS:
        raise OfficeImportPreviewInvalid("parsed document exceeds native preview limits")
    root_profile: dict[str, Any] = {}
    if document_blocks:
        blocks, structured_text, root_profile = _structured_blocks(document_blocks, image_builder)
        if normalize_extracted_text(structured_text) != text:
            raise OfficeImportPreviewInvalid("parser text and structured content do not match")
    else:
        blocks = [{"type": "paragraph", "content": _text_content(line)} for line in text.splitlines()]
    if not blocks:
        blocks.append({"type": "paragraph", "content": []})
    try:
        return validate_office_document(
            {
                "type": "doc",
                "attrs": {
                    **root_profile,
                    "importProvenance": {
                        "sourceObjectId": source_object_id,
                        "sourceVersionId": source_version_id,
                        "sourceContentHash": source_content_hash,
                        "sourceAclVersion": source_acl_version,
                        "parserProfileId": "rich-document-parser-worker:1",
                        "parserTextHash": parser_text_hash,
                        "parserStructureHash": parser_structure_hash,
                        "importScope": "bounded_structured_docx_preview",
                    },
                },
                "content": blocks,
            }
        )
    except ValueError as exc:
        raise OfficeImportPreviewInvalid("parsed document cannot be represented as a native preview") from exc


class OfficeImportPreviewService:
    def __init__(
        self,
        *,
        source_repository: SourceObjectRepository,
        audit: InMemoryAuditLogger,
        parser_dispatch: ParserDispatch = parse_rich_document,
        image_normalizer: ImageNormalizer = normalize_image,
    ) -> None:
        self._source_repository = source_repository
        self._audit = audit
        self._parser_dispatch = parser_dispatch
        self._image_normalizer = image_normalizer
        self._acl = ReadableObjectAclAuthorizer()

    def discover_sources(
        self,
        *,
        user_context: UserContext,
        query: str = "",
        limit: int = 25,
    ) -> OfficeImportSourceResponse:
        normalized_query = query.strip().casefold()
        if len(normalized_query) > 100 or not 1 <= limit <= 50:
            raise OfficeImportPreviewInvalid("import source discovery request is invalid")
        items: list[OfficeImportSourceItem] = []
        repository = cast(OfficeImportSourceRepository, self._source_repository)
        for metadata in repository.list_latest_metadata(
            tenant_id=user_context.tenant_id,
            limit=500,
            mime_type=DOCX_MIME_TYPE,
        ):
            if metadata.mime_type.partition(";")[0].strip().lower() != DOCX_MIME_TYPE:
                continue
            if not self._acl.can_read(
                user_context=user_context,
                object_id=metadata.object_id,
                acl_version=metadata.acl_version,
            ):
                continue
            if normalized_query and normalized_query not in f"{metadata.title}\n{metadata.object_id}".casefold():
                continue
            if (
                IMPORT_SOURCE_IDENTIFIER.fullmatch(metadata.object_id) is None
                or IMPORT_SOURCE_IDENTIFIER.fullmatch(metadata.version_id) is None
                or not 1 <= len(metadata.title) <= 200
                or metadata.title != metadata.title.strip()
                or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in metadata.title)
            ):
                continue
            classification = metadata.classification.value
            if classification not in {"public", "internal", "confidential", "restricted"}:
                continue
            items.append(
                OfficeImportSourceItem(
                    source_object_id=metadata.object_id,
                    source_version_id=metadata.version_id,
                    source_title=metadata.title,
                    updated_at_utc=metadata.updated_at_utc,
                    information_classification=classification,  # type: ignore[arg-type]
                    content_byte_length=metadata.content_byte_length,
                )
            )
            if len(items) == limit:
                break
        event_id = self._audit.record(
            user_context=user_context,
            event_type="office.documents.import_sources.read",
            source_object_ids=[item.source_object_id for item in items],
            metadata={
                "module_id": "office_documents",
                "surface": "api",
                "result_count": len(items),
                "query_supplied": bool(normalized_query),
                "content_returned": False,
                "current_acl_validated": True,
            },
        ).event_id
        return OfficeImportSourceResponse(
            tenant_id=user_context.tenant_id,
            items=tuple(items),
            audit_event_id=event_id,
        )

    def preview(
        self,
        *,
        user_context: UserContext,
        command: OfficeImportPreviewCommand,
    ) -> OfficeImportPreviewResponse:
        if not self._acl.can_read(user_context=user_context, object_id=command.source_object_id, acl_version=1):
            raise OfficeImportPreviewDenied("source version is not readable")
        try:
            record = self._source_repository.get(
                tenant_id=user_context.tenant_id,
                object_id=command.source_object_id,
                version_id=command.source_version_id,
            )
        except KeyError as exc:
            raise OfficeImportPreviewNotFound("source version was not found") from exc
        metadata = record.metadata
        if (
            metadata.tenant_id != user_context.tenant_id
            or metadata.object_id != command.source_object_id
            or metadata.version_id != command.source_version_id
        ):
            raise OfficeImportPreviewNotFound("source version was not found")
        try:
            current_metadata = self._source_repository.latest(
                tenant_id=user_context.tenant_id,
                object_id=command.source_object_id,
            ).metadata
        except KeyError as exc:
            raise OfficeImportPreviewNotFound("source version was not found") from exc
        if not self._acl.can_read(
            user_context=user_context,
            object_id=metadata.object_id,
            acl_version=current_metadata.acl_version,
        ):
            raise OfficeImportPreviewDenied("source version is not readable")
        if metadata.mime_type.partition(";")[0].strip().lower() != DOCX_MIME_TYPE:
            raise OfficeImportPreviewInvalid("source version is not a DOCX document")
        content = source_object_content_bytes(record)
        if (
            sha256_bytes(content) != metadata.content_hash
            or build_source_object_manifest_hash(metadata) != metadata.manifest_hash
        ):
            raise OfficeImportPreviewInvalid("source evidence does not match stored content")
        artifact = self._parser_dispatch(
            ParserWorkerRequest(
                tenant_id=metadata.tenant_id,
                source_object_id=metadata.object_id,
                source_version_id=metadata.version_id,
                source_object_type=metadata.object_type.value,
                mime_type=metadata.mime_type,
                content=content,
                filename=metadata.title,
            )
        )
        if (
            artifact.parser_name != "rich-document-parser-worker"
            or artifact.parser_version != "1"
            or artifact.source_object_type != metadata.object_type.value
            or artifact.mime_type != metadata.mime_type.partition(";")[0].strip().lower()
            or artifact.input_hash != metadata.content_hash
            or artifact.text_hash != sha256_bytes(artifact.text.encode("utf-8"))
            or artifact.text_byte_length != len(artifact.text.encode("utf-8"))
            or artifact.document_blocks_hash != hash_document_blocks(artifact.document_blocks)
            or len(artifact.warnings) > 20
            or any(not warning or len(warning) > 200 for warning in artifact.warnings)
        ):
            raise OfficeImportPreviewInvalid("parser evidence does not match the authorized source")
        images = DocxPreviewImages(
            {
                "tenant_id": metadata.tenant_id,
                "source_object_id": metadata.object_id,
                "source_version_id": metadata.version_id,
                "source_content_hash": metadata.content_hash,
                "structure_hash": artifact.document_blocks_hash,
            },
            self._image_normalizer,
        )
        document = _native_document(
            artifact.text,
            document_blocks=artifact.document_blocks,
            source_object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            source_content_hash=metadata.content_hash,
            source_acl_version=current_metadata.acl_version,
            parser_text_hash=artifact.text_hash,
            parser_structure_hash=artifact.document_blocks_hash,
            image_builder=images.build,
        )
        audit_event_id = self._audit.record(
            user_context=user_context,
            event_type="office.documents.import_preview.read",
            source_object_ids=[metadata.object_id],
            metadata={
                "module_id": "office_documents",
                "surface": "api",
                "source_version_id": metadata.version_id,
                "source_content_hash": metadata.content_hash,
                "source_acl_version": current_metadata.acl_version,
                "parser_profile_id": f"{artifact.parser_name}:{artifact.parser_version}",
                "parser_text_hash": artifact.text_hash,
                "parser_structure_hash": artifact.document_blocks_hash,
                "warning_count": len(artifact.warnings),
                "content_persisted": False,
                "fidelity_preserved": False,
                "structured_block_count": len(artifact.document_blocks),
                "image_count": len(images.images),
                "rag_indexing_allowed": False,
                "search_indexing_allowed": False,
            },
        ).event_id
        classification = metadata.classification.value
        if classification not in {"public", "internal", "confidential", "restricted"}:
            raise OfficeImportPreviewInvalid("source classification cannot be represented by native Office")
        return OfficeImportPreviewResponse(
            tenant_id=metadata.tenant_id,
            source_object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            source_title=metadata.title,
            source_content_hash=metadata.content_hash,
            source_acl_version=current_metadata.acl_version,
            information_classification=classification,  # type: ignore[arg-type]
            parser_text_hash=artifact.text_hash,
            parser_structure_hash=artifact.document_blocks_hash,
            warnings=artifact.warnings,
            document=document,
            audit_event_id=audit_event_id,
            image_previews=tuple(images.images),
        )
