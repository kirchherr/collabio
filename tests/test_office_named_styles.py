from copy import deepcopy
from typing import Any

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text


def styled_document() -> dict[str, Any]:
    return {
        "type": "doc",
        "attrs": {
            "styles": [
                {
                    "id": "body",
                    "name": "Fließtext 😀",
                    "paragraph": {"lineSpacing": "1.5"},
                    "character": {"fontSize": 18, "textColor": "blue"},
                }
            ]
        },
        "content": [
            {
                "type": "paragraph",
                "attrs": {"styleId": "body", "textAlign": "right"},
                "content": [{"type": "text", "text": "Café 😀 text", "marks": [{"type": "bold"}]}],
            }
        ],
    }


def test_styles_preserve_exact_bytes_and_review_and_replacement_positions() -> None:
    document = styled_document()
    before = canonical_json(document)
    assert validate_office_document(document) is document
    assert canonical_json(document) == before
    anchor = ReviewAnchor.model_validate({"from": 1, "to": 5})
    assert derive_review_quote(document, anchor) == "Café"
    changed = replace_suggestion_text(document, anchor, "New")
    assert changed["attrs"] == document["attrs"]
    assert changed["content"][0]["attrs"] == document["content"][0]["attrs"]
    validate_office_document(changed)
    assert canonical_json(document) == before
    legacy = {"type": "doc", "content": [{"type": "paragraph"}]}
    assert canonical_json(validate_office_document(legacy)) == '{"content":[{"type":"paragraph"}],"type":"doc"}'


@pytest.mark.parametrize("value", [None, {}, "body", True, [None], [{"id": "body"}]])
def test_styles_reject_invalid_catalog_shapes(value: Any) -> None:
    document = styled_document()
    document["attrs"]["styles"] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize(
    "key,value",
    [
        ("id", ""),
        ("id", "Upper"),
        ("id", "../file"),
        ("id", "x" * 49),
        ("id", None),
        ("name", ""),
        ("name", " space"),
        ("name", "x" * 61),
        ("name", "secret\n"),
        ("name", "a\ud800"),
        ("name", "a\x85b"),
        ("name", 5),
        ("paragraph", None),
        ("paragraph", {"fontSize": 18}),
        ("paragraph", {"textAlign": "SECRET"}),
        ("paragraph", {"spacingAfter": True}),
        ("paragraph", {"spacingAfter": 6.0}),
        ("paragraph", {"lineSpacing": 1.5}),
        ("character", {"fontSize": "18"}),
        ("character", {"fontSize": 18.0}),
        ("character", {"fontSize": True}),
        ("character", {"textColor": "#fff"}),
        ("character", {"textColor": None}),
        ("character", {"style": "SECRET"}),
        ("url", "SECRET"),
    ],
)
def test_styles_reject_untrusted_definition_values_without_mutation(key: str, value: Any) -> None:
    document = styled_document()
    document["attrs"]["styles"][0][key] = value
    before = deepcopy(document)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
    assert document == before


@pytest.mark.parametrize(
    "tamper", ["duplicate-id", "duplicate-name", "limit", "dangling", "null", "wrong-node", "unknown-root"]
)
def test_styles_reject_ambiguous_or_dangling_references(tamper: str) -> None:
    document = styled_document()
    styles = document["attrs"]["styles"]
    if tamper in {"duplicate-id", "duplicate-name"}:
        styles.append(
            {
                **deepcopy(styles[0]),
                "id": "other" if tamper == "duplicate-name" else "body",
                "name": "Other" if tamper == "duplicate-id" else styles[0]["name"],
            }
        )
    elif tamper == "limit":
        document["attrs"]["styles"] = [
            {**deepcopy(styles[0]), "id": f"style-{n}", "name": f"Style {n}"} for n in range(21)
        ]
        document["content"][0]["attrs"]["styleId"] = "style-0"
    elif tamper in {"dangling", "null"}:
        document["content"][0]["attrs"]["styleId"] = None if tamper == "null" else "missing"
    elif tamper == "wrong-node":
        document["content"] = [{"type": "horizontalRule", "attrs": {"styleId": "body"}}]
    else:
        document["attrs"]["url"] = "SECRET"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_style_catalog_is_counted_in_canonical_byte_limit() -> None:
    document = styled_document()
    document["content"][0]["content"][0]["text"] = "界" * 66580
    assert len(canonical_json(document).encode()) < 400_000
    for n in range(1, 20):
        document["attrs"]["styles"].append(
            {"id": f"style-{n}", "name": "界" * 58 + str(n), "paragraph": {}, "character": {}}
        )
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
