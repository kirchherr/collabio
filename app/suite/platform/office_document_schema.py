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
    "pageBreak",
    "sectionBreak",
}
MARKS = {"bold", "italic", "strike", "code", "underline", "textStyle", "link", "crossReference"}
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

    def reject() -> None:
        raise OfficeDocumentInvalidContentError("Native document content is invalid or exceeds its limits")

    style_ids: set[str] = set()
    style_names: set[str] = set()
    root_attrs = document.get("attrs", {})
    if not isinstance(root_attrs, dict) or set(root_attrs) - {"styles", "page", "running"}:
        reject()
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

    def visit(node: Any, depth: int) -> None:
        nonlocal nodes, characters, images, page_breaks, section_breaks, bookmarks
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
        elif kind == "bookmark":
            bookmarks += 1
            identifier, label = attrs.get("id"), attrs.get("label")
            if (
                set(attrs) != {"id", "label"}
                or bookmarks > 100
                or not isinstance(identifier, str)
                or re.fullmatch(r"[a-z][a-z0-9-]{0,47}", identifier) is None
                or identifier in bookmark_ids
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
        elif kind in {"tableCell", "tableHeader"}:
            if set(attrs) - {"colspan", "rowspan", "colwidth"}:
                reject()
            if any(type(attrs.get(key, 1)) is not int or attrs.get(key, 1) != 1 for key in ("colspan", "rowspan")):
                reject()
            if attrs.get("colwidth") is not None:
                reject()
        elif kind == "doc":
            if depth != 0 or set(attrs) - {"styles", "page", "running"}:
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
            elif set(mark) != {"type"}:
                reject()
            seen.add(name)
        if "code" in seen and len(seen) > 1:
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
        elif kind in {"paragraph", "heading"}:
            if any(child not in {"text", "hardBreak", "bookmark"} for child in child_types):
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
            visit(child, depth + 1)
        if kind == "table" and len({len(row["content"]) for row in children}) != 1:
            reject()

    if document.get("type") != "doc":
        reject()
    visit(document, 0)
    if len(canonical_json(document).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        reject()
    return document
