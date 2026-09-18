"""The deliberately small, inert native Office document format.

This is a Collabio JSON format, not an OOXML import or an engine admission.
"""

from __future__ import annotations

from typing import Any

from suite.ai_control_plane.audit import canonical_json

OFFICE_DOCUMENT_SCHEMA_VERSION = "collabio_document.v1"
OFFICE_DOCUMENT_MIME_TYPE = "application/vnd.collabio.document+json"
MAX_DOCUMENT_BYTES = 400_000
MAX_DOCUMENT_CHARACTERS = 100_000
MAX_DOCUMENT_NODES = 10_000
MAX_DOCUMENT_DEPTH = 32
BLOCKS = {"paragraph", "heading", "blockquote", "codeBlock", "bulletList", "orderedList", "horizontalRule", "table"}
MARKS = {"bold", "italic", "strike", "code", "underline"}


class OfficeDocumentInvalidContentError(ValueError):
    pass


def validate_office_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate structure and resource limits before canonicalization or storage."""
    nodes = 0
    characters = 0

    def reject() -> None:
        raise OfficeDocumentInvalidContentError("Native document content is invalid or exceeds its limits")

    def visit(node: Any, depth: int) -> None:
        nonlocal nodes, characters
        nodes += 1
        if nodes > MAX_DOCUMENT_NODES or depth > MAX_DOCUMENT_DEPTH or not isinstance(node, dict):
            reject()
        if set(node) - {"type", "attrs", "content", "text", "marks"}:
            reject()
        kind = node.get("type")
        if not isinstance(kind, str) or kind not in BLOCKS | {"doc", "text", "hardBreak", "listItem", "tableRow", "tableCell", "tableHeader"}:
            reject()
        attrs = node.get("attrs", {})
        if not isinstance(attrs, dict):
            reject()
        if kind == "heading":
            if set(attrs) != {"level"} or type(attrs["level"]) is not int or attrs["level"] not in {1, 2, 3}:
                reject()
        elif kind == "orderedList":
            if set(attrs) - {"start"} or type(attrs.get("start", 1)) is not int or not 1 <= attrs.get("start", 1) <= 1_000_000:
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
            if not isinstance(mark, dict) or set(mark) != {"type"}:
                reject()
            name = mark.get("type")
            if not isinstance(name, str) or name not in MARKS or name in seen:
                reject()
            seen.add(name)
        if "code" in seen and len(seen) > 1:
            reject()
        if kind == "text":
            value = node.get("text")
            if not isinstance(value, str) or not value or children:
                reject()
            if any((ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF for character in value):
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
            if any(child not in {"text", "hardBreak"} for child in child_types):
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
