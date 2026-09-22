from copy import deepcopy
from typing import Any

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text
from work_e2e_character import character_recovery_document


def formatted_document() -> dict[str, Any]:
    return character_recovery_document(2)


@pytest.mark.parametrize("attrs", [{"fontSize": size} for size in (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48)]
    + [{"textColor": color} for color in ("black", "slate", "red", "orange", "green", "teal", "blue", "purple")]
    + [{"fontSize": 48, "textColor": "purple"}])
def test_character_values_preserve_exact_canonical_payload_without_mutation(attrs: dict[str, Any]) -> None:
    document = formatted_document()
    document["content"][0]["content"][0]["marks"] = [{"type": "textStyle", "attrs": attrs}]
    before = canonical_json(document)
    assert validate_office_document(document) is document
    assert canonical_json(document) == before


@pytest.mark.parametrize("mark", [
    {"type": "textStyle"}, {"type": "textStyle", "attrs": {}}, {"type": "textStyle", "attrs": None},
    *[{"type": "textStyle", "attrs": {"fontSize": size}} for size in (True, 12.0, "12", "12pt", None, 0, 13, 49, [], {})],
    *[{"type": "textStyle", "attrs": {"textColor": color}} for color in (None, True, [], {}, "#ff0000", "RED", "default", "red;SECRET")],
    {"type": "textStyle", "attrs": {"fontSize": 12, "style": "SECRET"}},
    {"type": "textStyle", "attrs": {"textColor": "red"}, "extra": "SECRET"},
    {"type": "bold", "attrs": {"fontSize": 12}},
])
def test_invalid_character_marks_fail_closed_without_mutation(mark: Any) -> None:
    document = formatted_document()
    document["content"][0]["content"][0]["marks"] = [mark]
    before = deepcopy(document)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
    assert document == before


@pytest.mark.parametrize("placement", ["duplicate", "code", "codeBlock", "block"])
def test_character_marks_reject_duplicate_and_invalid_placements(placement: str) -> None:
    mark = {"type": "textStyle", "attrs": {"fontSize": 12}}
    leaf: dict[str, Any] = {"type": "text", "text": "Example", "marks": [mark]}
    block: dict[str, Any] = {"type": "paragraph", "content": [leaf]}
    if placement == "duplicate":
        leaf["marks"].append(deepcopy(mark))
    elif placement == "code":
        leaf["marks"].append({"type": "code"})
    elif placement == "codeBlock":
        block["type"] = "codeBlock"
    else:
        block["marks"] = [mark]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [block]})


def test_character_legacy_bytes_and_suggestion_offsets_and_outside_attributes() -> None:
    document = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "😀 café", "marks": [{"type": "textStyle", "attrs": {"fontSize": 18, "textColor": "blue"}}]},
        {"type": "text", "text": " FIN", "marks": [{"type": "textStyle", "attrs": {"fontSize": 12, "textColor": "red"}}]},
    ]}]}
    original = deepcopy(document)
    anchor = ReviewAnchor.model_validate({"from": 4, "to": 8})
    assert derive_review_quote(document, anchor) == "café"
    replaced = replace_suggestion_text(document, anchor, "NEU")
    assert document == original
    assert replaced["content"][0]["content"][-1] == original["content"][0]["content"][-1]
    assert replaced["content"][0]["content"][1]["marks"] == original["content"][0]["content"][0]["marks"]
    validate_office_document(replaced)
    legacy = character_recovery_document(1)
    before = canonical_json(legacy)
    assert validate_office_document(legacy) is legacy and canonical_json(legacy) == before


def test_character_attributes_count_toward_canonical_byte_limit() -> None:
    plain = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "界" * 90}]} for _ in range(620)]}
    validate_office_document(plain)
    for block in plain["content"]:
        block["content"][0]["marks"] = [{"type": "textStyle", "attrs": {"fontSize": 48, "textColor": "purple"}}]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(plain)
