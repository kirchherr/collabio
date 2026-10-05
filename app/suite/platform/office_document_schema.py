"""The deliberately small, inert native Office document format.

This is a Collabio JSON format, not an OOXML import or an engine admission.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_image_schema import validate_image_attributes

OFFICE_DOCUMENT_SCHEMA_VERSION = "collabio_document.v1"
OFFICE_DOCUMENT_MIME_TYPE = "application/vnd.collabio.document+json"
MAX_DOCUMENT_BYTES = 400_000
MAX_DOCUMENT_CHARACTERS = 100_000
MAX_DOCUMENT_NODES = 10_000
MAX_DOCUMENT_DEPTH = 32
BLOCKS = {
    "paragraph",
    "heading",
    "blockquote",
    "codeBlock",
    "bulletList",
    "orderedList",
    "horizontalRule",
    "table",
    "image",
    "imageGroup",
    "shape",
    "shapeGroup",
    "pageBreak",
    "sectionBreak",
    "tableOfContents",
    "bibliography",
    "equation",
    "referenceIndex",
}
MARKS = {
    "bold",
    "italic",
    "strike",
    "code",
    "underline",
    "textStyle",
    "link",
    "crossReference",
    "documentReference",
}
FONT_SIZES = {8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48}
TEXT_COLORS = {"black", "slate", "red", "orange", "green", "teal", "blue", "purple"}
PARAGRAPH_FORMAT_ATTRIBUTES = {"textAlign", "lineSpacing", "spacingBefore", "spacingAfter"}
PARAGRAPH_VALUES: dict[str, set[Any]] = {
    "textAlign": {"left", "center", "right", "justify"},
    "lineSpacing": {"1", "1.15", "1.5", "2"},
    "spacingBefore": {0, 6, 12, 18, 24},
    "spacingAfter": {0, 6, 12, 18, 24},
}
STYLE_CHARACTER_VALUES: dict[str, set[Any]] = {"fontSize": FONT_SIZES, "textColor": TEXT_COLORS}


class OfficeDocumentInvalidContentError(ValueError):
    pass


def _valid_link_href(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 2048 or value != value.strip():
        return False
    if any(
        ord(character) < 33 or 127 <= ord(character) <= 159 or character in {"<", ">", '"', "'", "\\"}
        for character in value
    ):
        return False
    if value.startswith("mailto:"):
        address = value[7:]
        return (
            len(address) <= 320
            and ".." not in address
            and re.fullmatch(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?",
                address,
            )
            is not None
        )
    if not value.startswith("https://"):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65535)
    )


def validate_office_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate structure and resource limits before canonicalization or storage."""
    nodes = 0
    characters = 0
    images = 0
    page_breaks = 0
    section_breaks = 0
    bookmarks = 0
    bookmark_ids: set[str] = set()
    bookmark_labels: set[str] = set()
    figure_ids: set[str] = set()
    table_ids: set[str] = set()
    numbered_tables = 0
    document_fields: set[str] = set()
    citation_sources: set[str] = set()
    note_ids: set[str] = set()
    equations = 0
    document_references = 0
    equation_ids: set[str] = set()
    generated_blocks: set[str] = set()
    image_group_ids: set[str] = set()
    shape_ids: set[str] = set()
    shape_group_ids: set[str] = set()

    def reject() -> None:
        raise OfficeDocumentInvalidContentError("Native document content is invalid or exceeds its limits")

    style_ids: set[str] = set()
    style_names: set[str] = set()
    root_attrs = document.get("attrs", {})
    if not isinstance(root_attrs, dict) or set(root_attrs) - {
        "styles",
        "page",
        "running",
        "documentFields",
        "citationSources",
    }:
        reject()
    fields = root_attrs.get("documentFields", [])
    if not isinstance(fields, list) or len(fields) > 50:
        reject()
    for field in fields:
        if (
            not isinstance(field, dict)
            or set(field) != {"key", "label", "value"}
            or not isinstance(field["key"], str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", field["key"]) is None
            or field["key"] in document_fields
            or not isinstance(field["label"], str)
            or not 1 <= len(field["label"]) <= 64
            or field["label"] != field["label"].strip()
            or not isinstance(field["value"], str)
            or len(field["value"]) > 1000
            or any(
                ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF
                for c in field["label"] + field["value"]
            )
        ):
            reject()
        document_fields.add(field["key"])
    sources = root_attrs.get("citationSources", [])
    if not isinstance(sources, list) or len(sources) > 100:
        reject()
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != {"id", "author", "title", "year", "locator"}
            or not isinstance(source["id"], str)
            or re.fullmatch(r"source-[a-f0-9]{24}", source["id"]) is None
            or source["id"] in citation_sources
            or any(not isinstance(source[key], str) for key in ("author", "title", "year", "locator"))
            or not source["title"].strip()
            or source["title"] != source["title"].strip()
            or len(source["author"]) > 200
            or len(source["title"]) > 500
            or len(source["year"]) > 20
            or len(source["locator"]) > 1000
            or any(
                ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF
                for key in ("author", "title", "year", "locator")
                for c in source[key]
            )
        ):
            reject()
        citation_sources.add(source["id"])
    if "page" in root_attrs:
        page = root_attrs["page"]
        if (
            not isinstance(page, dict)
            or set(page) != {"paper", "orientation", "margins"}
            or page["paper"] not in ("a4", "letter")
            or page["orientation"] not in ("portrait", "landscape")
            or not isinstance(page["margins"], dict)
            or set(page["margins"]) != {"top", "right", "bottom", "left"}
            or any(type(value) is not int or not 5 <= value <= 50 for value in page["margins"].values())
        ):
            reject()
    if "running" in root_attrs:
        running = root_attrs["running"]
        first_page = running.get("firstPage") if isinstance(running, dict) else None
        if (
            not isinstance(running, dict)
            or set(running) not in ({"header", "footer", "numbering"}, {"header", "footer", "numbering", "firstPage"})
            or running["numbering"] not in ("none", "page", "pageOfPages")
            or any(
                not isinstance(text, str)
                or len(text) > 64
                or any(
                    ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF or c in "\u2028\u2029"
                    for c in text
                )
                for text in (running["header"], running["footer"])
            )
            or (
                "firstPage" in running
                and (
                    not isinstance(first_page, dict)
                    or set(first_page) != {"header", "footer", "showNumber"}
                    or type(first_page["showNumber"]) is not bool
                    or (first_page["showNumber"] and running["numbering"] == "none")
                    or any(
                        not isinstance(text, str)
                        or len(text) > 64
                        or any(
                            ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF or c in "\u2028\u2029"
                            for c in text
                        )
                        for text in (first_page["header"], first_page["footer"])
                    )
                )
            )
        ):
            reject()
        margins = root_attrs.get("page", {}).get("margins", {"top": 18, "bottom": 18})
        if (running["header"] and margins["top"] < 16) or (
            (running["footer"] or running["numbering"] != "none") and margins["bottom"] < 16
        ):
            reject()
        if first_page and (
            (first_page["header"] and margins["top"] < 16)
            or ((first_page["footer"] or first_page["showNumber"]) and margins["bottom"] < 16)
        ):
            reject()
    styles = root_attrs.get("styles", [])
    if not isinstance(styles, list) or len(styles) > 20:
        reject()
    for style in styles:
        if not isinstance(style, dict) or set(style) != {"id", "name", "paragraph", "character"}:
            reject()
        identifier, name = style["id"], style["name"]
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", identifier) is None
            or identifier in style_ids
            or not isinstance(name, str)
            or not 1 <= len(name) <= 60
            or name != name.strip()
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in name)
            or name in style_names
        ):
            reject()
        style_ids.add(identifier)
        style_names.add(name)
        for key, values in (
            ("paragraph", PARAGRAPH_VALUES),
            ("character", STYLE_CHARACTER_VALUES),
        ):
            attributes = style[key]
            if not isinstance(attributes, dict) or set(attributes) - set(values):
                reject()
            for attribute, value in attributes.items():
                expected_type = int if attribute in {"fontSize", "spacingBefore", "spacingAfter"} else str
                if type(value) is not expected_type or value not in values[attribute]:
                    reject()

    def validate_section_profile(value: Any) -> None:
        if not isinstance(value, dict) or set(value) != {"page", "running"}:
            reject()
        page = value["page"]
        if (
            not isinstance(page, dict)
            or set(page) != {"paper", "orientation", "margins"}
            or page["paper"] not in ("a4", "letter")
            or page["orientation"] not in ("portrait", "landscape")
            or not isinstance(page["margins"], dict)
            or set(page["margins"]) != {"top", "right", "bottom", "left"}
            or any(type(item) is not int or not 5 <= item <= 50 for item in page["margins"].values())
        ):
            reject()
        running = value["running"]
        if (
            not isinstance(running, dict)
            or set(running) != {"header", "footer", "numbering"}
            or running["numbering"] not in ("none", "page", "pageOfPages")
            or any(
                not isinstance(text, str)
                or len(text) > 64
                or any(
                    ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF or c in "\u2028\u2029"
                    for c in text
                )
                for text in (running["header"], running["footer"])
            )
            or (running["header"] and page["margins"]["top"] < 16)
            or ((running["footer"] or running["numbering"] != "none") and page["margins"]["bottom"] < 16)
        ):
            reject()

    content = document.get("content", [])
    if isinstance(content, list):
        for index, entry in enumerate(content):
            if isinstance(entry, dict) and entry.get("type") == "sectionBreak":
                before = content[index - 1] if index else None
                after = content[index + 1] if index + 1 < len(content) else None
                if (
                    index == 0
                    or index == len(content) - 1
                    or not isinstance(before, dict)
                    or not isinstance(after, dict)
                    or before.get("type") in {"pageBreak", "sectionBreak"}
                    or after.get("type") in {"pageBreak", "sectionBreak"}
                ):
                    reject()

    def visit(node: Any, depth: int, parent_kind: str | None = None) -> None:
        nonlocal nodes, characters, images, page_breaks, section_breaks, bookmarks, numbered_tables, equations
        nonlocal document_references
        nodes += 1
        if nodes > MAX_DOCUMENT_NODES or depth > MAX_DOCUMENT_DEPTH or not isinstance(node, dict):
            reject()
        if set(node) - {"type", "attrs", "content", "text", "marks"}:
            reject()
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in BLOCKS | {
            "doc",
            "text",
            "hardBreak",
            "listItem",
            "tableRow",
            "tableCell",
            "tableHeader",
            "bookmark",
            "documentField",
            "noteReference",
            "citationReference",
        }:
            reject()
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict):
            reject()
        if kind in {"paragraph", "heading"}:
            allowed = PARAGRAPH_FORMAT_ATTRIBUTES | {"styleId"} | ({"level"} if kind == "heading" else set())
            if set(attrs) - allowed:
                reject()
            if "styleId" in attrs and (not isinstance(attrs["styleId"], str) or attrs["styleId"] not in style_ids):
                reject()
            if kind == "heading" and (type(attrs.get("level")) is not int or attrs["level"] not in {1, 2, 3}):
                reject()
            if "textAlign" in attrs and (
                not isinstance(attrs["textAlign"], str)
                or attrs["textAlign"] not in {"left", "center", "right", "justify"}
            ):
                reject()
            if "lineSpacing" in attrs and (
                not isinstance(attrs["lineSpacing"], str) or attrs["lineSpacing"] not in {"1", "1.15", "1.5", "2"}
            ):
                reject()
            for key in ("spacingBefore", "spacingAfter"):
                if key in attrs and (type(attrs[key]) is not int or attrs[key] not in {0, 6, 12, 18, 24}):
                    reject()
        elif kind == "pageBreak":
            page_breaks += 1
            if depth != 1 or set(node) != {"type"} or page_breaks > 100:
                reject()
        elif kind == "sectionBreak":
            section_breaks += 1
            if depth != 1 or set(node) != {"type", "attrs"} or section_breaks > 12:
                reject()
            validate_section_profile(attrs)
        elif kind == "image":
            images += 1
            if images > 40:
                reject()
            try:
                validate_image_attributes(attrs)
            except ValueError:
                reject()
            figure_id = attrs.get("figureId")
            if figure_id is not None:
                if figure_id in figure_ids or figure_id in bookmark_ids or figure_id in table_ids:
                    reject()
                figure_ids.add(figure_id)
        elif kind == "imageGroup":
            identifier = attrs.get("id")
            if (
                depth != 1
                or set(attrs) != {"id", "layout", "gap"}
                or not isinstance(identifier, str)
                or re.fullmatch(r"image-group-[a-f0-9]{24}", identifier) is None
                or identifier in image_group_ids
                or attrs.get("layout") not in {"row", "stack"}
                or type(attrs.get("gap")) is not int
                or not 0 <= attrs["gap"] <= 48
                or len(image_group_ids) >= 20
            ):
                reject()
            image_group_ids.add(identifier)
        elif kind == "shape":
            identifier = attrs.get("id")
            text = attrs.get("text")
            colors = {
                "transparent",
                "white",
                "slate",
                "red",
                "orange",
                "yellow",
                "green",
                "teal",
                "blue",
                "purple",
                "black",
            }
            required_shape_attrs = {
                "id",
                "kind",
                "width",
                "height",
                "fill",
                "stroke",
                "strokeWidth",
                "text",
                "textAlign",
            }
            if (
                (depth != 1 and parent_kind != "shapeGroup")
                or set(attrs)
                - (
                    required_shape_attrs
                    | {"fontSize", "position", "rotation", "textColor", "textStyle", "wrap"}
                )
                or not required_shape_attrs.issubset(attrs)
                or not isinstance(identifier, str)
                or re.fullmatch(r"shape-[a-f0-9]{24}", identifier) is None
                or identifier in shape_ids
                or len(shape_ids) >= 100
                or attrs.get("kind") not in {"rectangle", "roundedRectangle", "ellipse"}
                or type(attrs.get("width")) is not int
                or not 80 <= attrs["width"] <= 1200
                or type(attrs.get("height")) is not int
                or not 40 <= attrs["height"] <= 800
                or attrs.get("fill") not in colors
                or attrs.get("stroke") not in colors
                or type(attrs.get("strokeWidth")) is not int
                or not 0 <= attrs["strokeWidth"] <= 8
                or not isinstance(text, str)
                or len(text) > 1000
                or any(
                    (ord(c) < 32 and c not in "\n\t")
                    or 127 <= ord(c) <= 159
                    or 0xD800 <= ord(c) <= 0xDFFF
                    or c in "\u2028\u2029"
                    for c in text
                )
                or attrs.get("textAlign") not in {"left", "center", "right"}
                or (
                    "fontSize" in attrs
                    and (
                        type(attrs.get("fontSize")) is not int
                        or not 10 <= attrs["fontSize"] <= 72
                        or attrs["fontSize"] == 16
                    )
                )
                or ("textColor" in attrs and attrs.get("textColor") not in colors - {"transparent"})
                or (
                    "textStyle" in attrs
                    and attrs.get("textStyle") not in {"bold", "italic", "boldItalic"}
                )
                or (
                    "rotation" in attrs
                    and (type(attrs.get("rotation")) is not int or attrs.get("rotation") not in {90, 180, 270})
                )
            ):
                reject()
            position = attrs.get("position")
            if position is not None and (
                not isinstance(position, dict)
                or set(position) != {"layer", "x", "y"}
                or position.get("layer") not in {"front", "behind"}
                or type(position.get("x")) is not int
                or not 0 <= position["x"] <= 1000
                or type(position.get("y")) is not int
                or not -1200 <= position["y"] <= 1200
            ):
                reject()
            wrap = attrs.get("wrap")
            if wrap is not None and (
                not isinstance(wrap, dict)
                or set(wrap) != {"side", "gap"}
                or wrap.get("side") not in {"left", "right"}
                or type(wrap.get("gap")) is not int
                or not 0 <= wrap["gap"] <= 48
            ):
                reject()
            if position is not None and wrap is not None:
                reject()
            shape_ids.add(identifier)
            characters += len(text)
            if characters > MAX_DOCUMENT_CHARACTERS:
                reject()
        elif kind == "shapeGroup":
            identifier = attrs.get("id")
            connection = attrs.get("connection")
            if (
                depth != 1
                or set(attrs) - {"id", "layout", "gap", "connection"}
                or not {"id", "layout", "gap"}.issubset(attrs)
                or not isinstance(identifier, str)
                or re.fullmatch(r"shape-group-[a-f0-9]{24}", identifier) is None
                or identifier in shape_group_ids
                or attrs.get("layout") not in {"row", "stack"}
                or type(attrs.get("gap")) is not int
                or not 0 <= attrs["gap"] <= 48
                or len(shape_group_ids) >= 20
            ):
                reject()
            if connection is not None and (
                not isinstance(connection, dict)
                or set(connection) != {"kind", "color", "width"}
                or connection.get("kind") not in {"line", "arrow", "doubleArrow"}
                or connection.get("color") not in {"slate", "red", "green", "teal", "blue", "purple", "black"}
                or type(connection.get("width")) is not int
                or not 1 <= connection["width"] <= 8
            ):
                reject()
            shape_group_ids.add(identifier)
        elif kind == "bookmark":
            bookmarks += 1
            identifier, label = attrs.get("id"), attrs.get("label")
            if (
                set(attrs) != {"id", "label"}
                or bookmarks > 100
                or not isinstance(identifier, str)
                or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", identifier) is None
                or identifier in bookmark_ids
                or identifier in table_ids
                or not isinstance(label, str)
                or not 1 <= len(label) <= 64
                or label != label.strip()
                or any(
                    ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF or c in "\u2028\u2029"
                    for c in label
                )
                or label.lower() in bookmark_labels
            ):
                reject()
            bookmark_ids.add(identifier)
            bookmark_labels.add(label.lower())
            if identifier in figure_ids or identifier in table_ids:
                reject()
        elif kind == "documentField":
            if (
                set(attrs) != {"key"}
                or not isinstance(attrs.get("key"), str)
                or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", attrs["key"]) is None
            ):
                reject()
        elif kind == "noteReference":
            identifier, note_kind, text = attrs.get("id"), attrs.get("kind"), attrs.get("text")
            if (
                set(attrs) != {"id", "kind", "text"}
                or not isinstance(identifier, str)
                or re.fullmatch(r"note-[a-f0-9]{24}", identifier) is None
                or identifier in note_ids
                or note_kind not in {"footnote", "endnote"}
                or not isinstance(text, str)
                or not text.strip()
                or text != text.strip()
                or len(text) > 2000
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in text)
            ):
                reject()
            note_ids.add(identifier)
            if len(note_ids) > 200:
                reject()
        elif kind == "citationReference":
            if (
                set(attrs) != {"sourceId", "locator"}
                or not isinstance(attrs.get("sourceId"), str)
                or re.fullmatch(r"source-[a-f0-9]{24}", attrs["sourceId"]) is None
            ):
                reject()
            locator = attrs.get("locator")
            if (
                not isinstance(locator, str)
                or len(locator) > 100
                or locator != locator.strip()
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in locator)
            ):
                reject()
        elif kind == "tableOfContents":
            if (
                depth != 1
                or set(attrs) != {"maxLevel"}
                or type(attrs.get("maxLevel")) is not int
                or attrs["maxLevel"] not in {1, 2, 3}
                or kind in generated_blocks
            ):
                reject()
            generated_blocks.add(kind)
        elif kind == "bibliography" or kind == "referenceIndex":
            if depth != 1 or attrs or kind in generated_blocks:
                reject()
            generated_blocks.add(kind)
        elif kind == "equation":
            equations += 1
            if (
                depth != 1
                or equations > 100
                or set(attrs) != {"id", "source", "alt"}
                or not isinstance(attrs.get("id"), str)
                or re.fullmatch(r"equation-[a-f0-9]{24}", attrs["id"]) is None
                or attrs["id"] in equation_ids
                or not isinstance(attrs.get("source"), str)
                or not 1 <= len(attrs["source"]) <= 1000
                or not isinstance(attrs.get("alt"), str)
                or not 1 <= len(attrs["alt"]) <= 500
                or any(
                    ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF
                    for c in attrs["source"] + attrs["alt"]
                )
            ):
                reject()
            equation_ids.add(attrs["id"])
        elif kind == "orderedList":
            if (
                set(attrs) - {"start"}
                or type(attrs.get("start", 1)) is not int
                or not 1 <= attrs.get("start", 1) <= 1_000_000
            ):
                reject()
        elif kind == "codeBlock":
            if set(attrs) - {"language"} or attrs.get("language") is not None:
                reject()
        elif kind == "table":
            if attrs:
                identifier, caption = attrs.get("tableId"), attrs.get("caption")
                if (
                    set(attrs) != {"tableId", "caption"}
                    or not isinstance(identifier, str)
                    or re.fullmatch(r"table-[a-f0-9]{24}", identifier) is None
                    or identifier in table_ids
                    or identifier in bookmark_ids
                    or identifier in figure_ids
                    or not isinstance(caption, str)
                    or not caption.strip()
                    or len(caption) > 1000
                    or any(
                        ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF or c in "\u2028\u2029"
                        for c in caption
                    )
                ):
                    reject()
                numbered_tables += 1
                if numbered_tables > 100:
                    reject()
                table_ids.add(identifier)
        elif kind in {"tableCell", "tableHeader"}:
            if set(attrs) - {"colspan", "rowspan", "colwidth"}:
                reject()
            if any(type(attrs.get(key, 1)) is not int or attrs.get(key, 1) != 1 for key in ("colspan", "rowspan")):
                reject()
            if attrs.get("colwidth") is not None:
                reject()
        elif kind == "doc":
            if depth != 0 or set(attrs) - {"styles", "page", "running", "documentFields", "citationSources"}:
                reject()
        elif attrs:
            reject()
        children = node.get("content", [])
        if not isinstance(children, list):
            reject()
        marks = node.get("marks", [])
        if not isinstance(marks, list) or len(marks) > len(MARKS):
            reject()
        seen: set[str] = set()
        for mark in marks:
            if not isinstance(mark, dict):
                reject()
            name = mark.get("type")
            if not isinstance(name, str) or name not in MARKS or name in seen:
                reject()
            if name == "textStyle":
                style = mark.get("attrs")
                if (
                    set(mark) != {"type", "attrs"}
                    or not isinstance(style, dict)
                    or not style
                    or set(style) - {"fontSize", "textColor"}
                ):
                    reject()
                if "fontSize" in style and (type(style["fontSize"]) is not int or style["fontSize"] not in FONT_SIZES):
                    reject()
                if "textColor" in style and (
                    not isinstance(style["textColor"], str) or style["textColor"] not in TEXT_COLORS
                ):
                    reject()
            elif name == "link":
                if (
                    set(mark) != {"type", "attrs"}
                    or not isinstance(mark["attrs"], dict)
                    or set(mark["attrs"]) != {"href"}
                ):
                    reject()
                if not _valid_link_href(mark["attrs"]["href"]):
                    reject()
            elif name == "crossReference":
                if (
                    set(mark) != {"type", "attrs"}
                    or not isinstance(mark["attrs"], dict)
                    or set(mark["attrs"]) != {"targetId"}
                    or not isinstance(mark["attrs"]["targetId"], str)
                    or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", mark["attrs"]["targetId"]) is None
                ):
                    reject()
            elif name == "documentReference":
                document_references += 1
                if (
                    document_references > 100
                    or set(mark) != {"type", "attrs"}
                    or not isinstance(mark["attrs"], dict)
                    or set(mark["attrs"]) != {"targetObjectId", "targetVersionId"}
                    or not isinstance(mark["attrs"]["targetObjectId"], str)
                    or re.fullmatch(r"office-doc-[a-f0-9]{32}", mark["attrs"]["targetObjectId"]) is None
                    or not isinstance(mark["attrs"]["targetVersionId"], str)
                    or re.fullmatch(r"office-version-[a-f0-9]{32}", mark["attrs"]["targetVersionId"]) is None
                ):
                    reject()
            elif set(mark) != {"type"}:
                reject()
            seen.add(name)
        if "code" in seen and len(seen) > 1:
            reject()
        if "documentReference" in seen and seen & {"link", "crossReference"}:
            reject()
        if "link" in seen and "crossReference" in seen:
            reject()
        if kind == "text":
            value = node.get("text")
            if not isinstance(value, str) or not value or children:
                reject()
            if any(
                (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF
                for character in value
            ):
                reject()
            characters += len(value)
            if characters > MAX_DOCUMENT_CHARACTERS:
                reject()
        elif "text" in node or marks:
            reject()
        child_types = [child.get("type") if isinstance(child, dict) else None for child in children]
        if any(not isinstance(child, str) for child in child_types):
            reject()
        if kind in {"doc", "blockquote", "tableCell", "tableHeader"}:
            if not children or any(child not in BLOCKS for child in child_types):
                reject()
        elif kind == "imageGroup":
            if (
                not 2 <= len(children) <= 8
                or any(child != "image" for child in child_types)
                or any(child.get("attrs", {}).get("wrap") is not None for child in children)
                or any(child.get("attrs", {}).get("position") is not None for child in children)
            ):
                reject()
        elif kind == "shapeGroup":
            if (
                not 2 <= len(children) <= 8
                or any(child != "shape" for child in child_types)
                or any(child.get("attrs", {}).get("wrap") is not None for child in children)
                or any(child.get("attrs", {}).get("position") is not None for child in children)
            ):
                reject()
        elif kind in {"paragraph", "heading"}:
            if any(
                child not in {"text", "hardBreak", "bookmark", "documentField", "noteReference", "citationReference"}
                for child in child_types
            ):
                reject()
        elif kind == "codeBlock":
            if any(child != "text" or children[index].get("marks") for index, child in enumerate(child_types)):
                reject()
        elif kind in {"bulletList", "orderedList"}:
            if not children or any(child != "listItem" for child in child_types):
                reject()
        elif kind == "listItem":
            if not children or child_types[0] != "paragraph" or any(child not in BLOCKS for child in child_types):
                reject()
        elif kind == "table":
            if not 1 <= len(children) <= 200 or any(child != "tableRow" for child in child_types):
                reject()
        elif kind == "tableRow":
            if not 1 <= len(children) <= 20 or any(child not in {"tableCell", "tableHeader"} for child in child_types):
                reject()
        elif children:
            reject()
        for child in children:
            visit(child, depth + 1, kind)
        if kind == "table" and len({len(row["content"]) for row in children}) != 1:
            reject()

    if document.get("type") != "doc":
        reject()
    visit(document, 0)
    if len(canonical_json(document).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        reject()
    return document


def office_document_reference_counts(document: dict[str, Any]) -> tuple[tuple[str, str, int], ...]:
    """Return ordered outbound targets and occurrence counts from a bounded document."""
    validate_office_document(document)
    references: dict[tuple[str, str], int] = {}

    def walk(node: dict[str, Any]) -> None:
        for mark in node.get("marks", []):
            if mark.get("type") != "documentReference":
                continue
            attrs = mark["attrs"]
            target = (attrs["targetObjectId"], attrs["targetVersionId"])
            references[target] = references.get(target, 0) + 1
        for child in node.get("content", []):
            walk(child)

    walk(document)
    return tuple((object_id, version_id, count) for (object_id, version_id), count in references.items())


def office_document_references(document: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return unique outbound targets from an already bounded native document."""
    return tuple((object_id, version_id) for object_id, version_id, _ in office_document_reference_counts(document))
