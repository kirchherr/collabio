from copy import deepcopy
from typing import Any

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text


def paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def test_page_breaks_preserve_legacy_bytes_and_exact_root_positions() -> None:
    legacy: dict[str, Any] = {"type": "doc", "content": [paragraph("Before"), paragraph("After")]}
    before = canonical_json(legacy)
    assert validate_office_document(legacy) is legacy
    assert canonical_json(legacy) == before
    content = deepcopy(legacy)
    content["content"].insert(1, {"type": "pageBreak"})
    assert validate_office_document(content) == content
    assert content["content"][1] == {"type": "pageBreak"}
    assert legacy["content"] == [paragraph("Before"), paragraph("After")]


@pytest.mark.parametrize("field,value", [("attrs", {}), ("content", []), ("marks", []), ("text", ""), ("src", "x")])
def test_page_break_is_an_exact_inert_leaf(field: str, value: Any) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [{"type": "pageBreak", field: value}]})


@pytest.mark.parametrize("parent", ["blockquote", "paragraph", "heading", "codeBlock", "listItem", "tableCell"])
def test_page_break_cannot_be_nested(parent: str) -> None:
    nested: dict[str, Any] = {"type": parent, "content": [paragraph("Keep"), {"type": "pageBreak"}]}
    if parent == "heading":
        nested["attrs"] = {"level": 2}
    if parent == "listItem":
        nested = {"type": "bulletList", "content": [nested]}
    if parent == "tableCell":
        nested = {"type": "table", "content": [{"type": "tableRow", "content": [nested]}]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [nested]})


def test_page_break_limit_includes_leading_trailing_and_repeated_markers() -> None:
    content: dict[str, Any] = {"type": "doc", "content": [{"type": "pageBreak"}] * 100}
    assert validate_office_document(content) == content
    content["content"].append({"type": "pageBreak"})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(content)


def test_review_and_suggestion_positions_after_page_break_preserve_boundary() -> None:
    content = {"type": "doc", "content": [paragraph("A😀"), {"type": "pageBreak"}, paragraph("After")]}
    before = deepcopy(content)
    anchor = ReviewAnchor.model_validate({"from": 7, "to": 12})
    assert derive_review_quote(content, anchor) == "After"
    replaced = replace_suggestion_text(content, anchor, "Replacement")
    assert replaced == {"type": "doc", "content": [paragraph("A😀"), {"type": "pageBreak"}, paragraph("Replacement")]}
    assert content == before
    with pytest.raises(OfficeDocumentInvalidContentError):
        derive_review_quote(content, ReviewAnchor.model_validate({"from": 5, "to": 8}))
