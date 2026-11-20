from copy import deepcopy

import pytest

from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document


def table(table_id: str | None = None, caption: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "attrs": {"colspan": 1, "rowspan": 1},
                        "content": [{"type": "paragraph"}],
                    }
                ],
            }
        ],
    }
    if table_id is not None or caption is not None:
        value["attrs"] = {"tableId": table_id, "caption": caption}
    return value


def test_numbered_tables_are_optional_bounded_and_keep_legacy_tables_exact() -> None:
    legacy = {"type": "doc", "content": [table()]}
    assert validate_office_document(deepcopy(legacy)) == legacy
    numbered = {"type": "doc", "content": [table("table-" + "a" * 24, "Quarterly totals")]}
    assert validate_office_document(deepcopy(numbered)) == numbered


@pytest.mark.parametrize(
    "attrs",
    [
        {"tableId": "table-short", "caption": "Caption"},
        {"tableId": "table-" + "A" * 24, "caption": "Caption"},
        {"tableId": "table-" + "a" * 24, "caption": ""},
        {"tableId": "table-" + "a" * 24, "caption": " "},
        {"tableId": "table-" + "a" * 24, "caption": "x" * 1001},
        {"tableId": "table-" + "a" * 24, "caption": "bad\ncaption"},
        {"tableId": "table-" + "a" * 24},
        {"caption": "Caption"},
    ],
)
def test_numbered_tables_reject_partial_active_or_unbounded_attributes(attrs: dict[str, object]) -> None:
    value = table()
    value["attrs"] = attrs
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [value]})


def test_table_targets_are_unique_across_tables_figures_and_bookmarks() -> None:
    identifier = "table-" + "a" * 24
    duplicate = {"type": "doc", "content": [table(identifier, "One"), table(identifier, "Two")]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(duplicate)
    bookmark = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "bookmark", "attrs": {"id": identifier, "label": "Summary"}}]},
            table(identifier, "One"),
        ],
    }
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(bookmark)
