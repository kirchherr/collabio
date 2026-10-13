from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_documents import (
    OfficeDocumentCollaborationPreflightCommand,
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentEditLeaseCommand,
    OfficeDocumentEditLeaseReleaseCommand,
    OfficeDocumentGatewayPreflightCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import InMemorySourceObjectRepository, SourceObjectRecord


def document_text(text: str = "Confidential native draft") -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def create_command(reference: str = "create-1") -> OfficeDocumentCreateCommand:
    return OfficeDocumentCreateCommand(
        title="Private document title", document=document_text(), mutation_reference=reference, human_confirmation=True
    )


def test_native_document_supports_bounded_rich_structure_without_active_content() -> None:
    paragraph = document_text()["content"][0]
    rich = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Title"}]},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "<script>literal</script>",
                        "marks": [{"type": "bold"}, {"type": "underline"}],
                    },
                    {"type": "hardBreak"},
                ],
            },
            {"type": "orderedList", "attrs": {"start": 3}, "content": [{"type": "listItem", "content": [paragraph]}]},
            {"type": "blockquote", "content": [paragraph]},
            {"type": "codeBlock", "attrs": {"language": None}, "content": [{"type": "text", "text": "a\n\tb"}]},
            {"type": "horizontalRule"},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                                "content": [paragraph],
                            },
                            {"type": "tableCell", "content": [paragraph]},
                        ],
                    }
                ],
            },
        ],
    }
    assert validate_office_document(rich) == rich


def test_native_document_accepts_only_rectangular_bounded_table_spans() -> None:
    paragraph: dict[str, Any] = {"type": "paragraph"}
    merged: dict[str, Any] = {
        "type": "table",
        "attrs": {
            "style": "accent",
            "width": "compact",
            "align": "center",
            "columns": "first-wide",
            "captionPosition": "top",
        },
        "content": [
            {
                "type": "tableRow",
                "content": [{"type": "tableHeader", "attrs": {"colspan": 3, "rowspan": 1}, "content": [paragraph]}],
            },
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 2}, "content": [paragraph]},
                    {
                        "type": "tableCell",
                        "attrs": {
                            "background": "blue",
                            "verticalAlign": "middle",
                            "horizontalAlign": "center",
                            "padding": "spacious",
                            "border": "strong",
                        },
                        "content": [paragraph],
                    },
                    {"type": "tableCell", "content": [paragraph]},
                ],
            },
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "content": [paragraph]},
                    {"type": "tableCell", "content": [paragraph]},
                ],
            },
        ],
    }
    document = {"type": "doc", "content": [merged]}
    assert validate_office_document(document) == document
    invalid = [
        {**merged, "content": merged["content"][:2]},
        {
            **merged,
            "content": [merged["content"][0], merged["content"][1], {**merged["content"][2], "content": []}],
        },
        {
            "type": "table",
            "attrs": {"style": "url(secret)"},
            "content": [{"type": "tableRow", "content": [{"type": "tableCell", "content": [paragraph]}]}],
        },
        {
            "type": "table",
            "attrs": {"width": "42px"},
            "content": [{"type": "tableRow", "content": [{"type": "tableCell", "content": [paragraph]}]}],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"colspan": 21, "rowspan": 1}, "content": [paragraph]}],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"horizontalAlign": "justify"}, "content": [paragraph]}],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"padding": "24px"}, "content": [paragraph]}],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"border": "url(secret)"}, "content": [paragraph]}],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"background": "url(secret)"}, "content": [paragraph]}],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"verticalAlign": "baseline"}, "content": [paragraph]}],
                }
            ],
        },
    ]
    for table in invalid:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [table]})


def test_native_document_accepts_only_bounded_inert_table_formulas_and_matching_results() -> None:
    formula_cell: dict[str, Any] = {
        "type": "tableCell",
        "attrs": {"formula": "=SUM(A1:B1)", "formulaResult": "3"},
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "3"}]}],
    }

    def value(text: str) -> dict[str, object]:
        return {
            "type": "tableCell",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    table: dict[str, Any] = {
        "type": "table",
        "content": [{"type": "tableRow", "content": [value("1"), value("2"), formula_cell]}],
    }
    document: dict[str, Any] = {"type": "doc", "content": [table]}
    assert validate_office_document(document) == document
    anchored = deepcopy(document)
    anchored["content"][0]["content"][0]["content"][2] = {
        **formula_cell,
        "attrs": {"formula": "=SUM($A$1:B$1)", "formulaResult": "3"},
    }
    assert validate_office_document(anchored) == anchored
    reference_error = deepcopy(document)
    reference_error["content"][0]["content"][0]["content"][2] = {
        **formula_cell,
        "attrs": {"formula": "=SUM(#BEZUG!:B1)", "formulaResult": "#BEZUG!"},
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "#BEZUG!"}]}],
    }
    assert validate_office_document(reference_error) == reference_error
    invalid = [
        {**formula_cell, "attrs": {"formula": "=A1", "formulaResult": "4"}},
        {**formula_cell, "attrs": {"formula": "=[external]A1", "formulaResult": "3"}},
        {**formula_cell, "attrs": {"formula": "=FOO(A1)", "formulaResult": "3"}},
        {**formula_cell, "attrs": {"formula": "=U1", "formulaResult": "3"}},
        {**formula_cell, "attrs": {"formula": "=#BROKEN!", "formulaResult": "#BEZUG!"}},
        {**formula_cell, "attrs": {"formula": "=$$A1", "formulaResult": "1"}},
        {**formula_cell, "attrs": {"formula": "=A$$1", "formulaResult": "1"}},
        {**formula_cell, "attrs": {"formula": "=A1", "formulaResult": "3", "colspan": 2}},
        {**formula_cell, "type": "tableHeader"},
        {**formula_cell, "attrs": {"formula": "=A1"}},
    ]
    forged = deepcopy(formula_cell)
    forged["attrs"]["formulaResult"] = "4"
    forged["content"][0]["content"][0]["text"] = "4"
    invalid.append(forged)
    for cell in invalid:
        candidate = deepcopy(document)
        candidate["content"][0]["content"][0]["content"][2] = cell
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(candidate)


def test_native_document_recalculates_advanced_formula_results_with_lazy_conditions() -> None:
    def cell(text: str, formula: str | None = None) -> dict[str, Any]:
        attrs = {"formula": formula, "formulaResult": text} if formula else None
        return {
            "type": "tableCell",
            **({"attrs": attrs} if attrs else {}),
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    table: dict[str, Any] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    cell("5"),
                    cell("2"),
                    cell("8.33", "=IF(A1>B1,ROUND(POWER(A1,2)/3,2),1/0)"),
                    cell("18.5", "=PRODUCT(A1:B1)+MEDIAN(A1:B1)+SQRT(4)+ABS(-3)"),
                ],
            },
            {
                "type": "tableRow",
                "content": [
                    cell("1", "=AND(C1=8.33,NOT(A1=B1),OR(0,1))"),
                    cell("26.83", "=C1+D1"),
                    cell("7", "=IF(0,1/0,7)"),
                    cell("#WERT!", "=SQRT(-1)"),
                ],
            },
        ],
    }
    document: dict[str, Any] = {"type": "doc", "content": [table]}
    assert validate_office_document(document) == document
    for formula, result in (("=ROUND(1,11)", "#WERT!"), ("=POWER(10,20)", "#LIMIT!"), ("=NOT(1,2)", "#WERT!")):
        candidate = deepcopy(document)
        candidate["content"][0]["content"][1]["content"][3] = cell(result, formula)
        assert validate_office_document(candidate) == candidate


def test_native_document_validates_named_cross_table_lookup_and_date_formulas() -> None:
    def cell(text: str, formula: str | None = None) -> dict[str, Any]:
        return {
            "type": "tableCell",
            **({"attrs": {"formula": formula, "formulaResult": text}} if formula else {}),
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    source_id, result_id = "table-" + "a" * 24, "table-" + "b" * 24
    source: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": source_id, "caption": "Source"},
        "content": [
            {"type": "tableRow", "content": [cell("101"), cell("5"), cell("2")]},
            {"type": "tableRow", "content": [cell("102"), cell("7"), cell("3")]},
        ],
    }
    result: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": result_id, "caption": "Result"},
        "content": [
            {
                "type": "tableRow",
                "content": [
                    cell("12", "=SUM(SALES)+XLOOKUP(102,ITEM_IDS,PRICES)"),
                    cell("2048", "=YEAR(DATE(2026,10,12))+MONTH(DATE(2026,10,12))+DAY(DATE(2026,10,12))"),
                ],
            }
        ],
    }
    document: dict[str, Any] = {
        "type": "doc",
        "attrs": {
            "tableRanges": [
                {"name": "ITEM_IDS", "tableId": source_id, "range": "A1:A2"},
                {"name": "PRICES", "tableId": source_id, "range": "B1:B2"},
                {"name": "SALES", "tableId": source_id, "range": "C1:C2"},
            ]
        },
        "content": [source, result],
    }
    assert validate_office_document(document) == document
    forged = deepcopy(document)
    forged["content"][1]["content"][0]["content"][0] = cell("13", "=SUM(SALES)+XLOOKUP(102,ITEM_IDS,PRICES)")
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(forged)
    for invalid_range in (
        {"name": "A1", "tableId": source_id, "range": "A1:A2"},
        {"name": "SUM", "tableId": source_id, "range": "A1:A2"},
        {"name": "MISSING", "tableId": "table-" + "f" * 24, "range": "A1:A2"},
        {"name": "OUTSIDE", "tableId": source_id, "range": "A1:A3"},
    ):
        candidate = deepcopy(document)
        candidate["attrs"]["tableRanges"] = [invalid_range]
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(candidate)


def test_native_document_detects_cross_table_named_range_cycles() -> None:
    def formula_cell(formula: str) -> dict[str, Any]:
        return {
            "type": "tableCell",
            "attrs": {"formula": formula, "formulaResult": "#ZYKLUS!"},
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "#ZYKLUS!"}]}],
        }

    left_id, right_id = "table-" + "c" * 24, "table-" + "d" * 24
    document: dict[str, Any] = {
        "type": "doc",
        "attrs": {
            "tableRanges": [
                {"name": "LEFT_VALUE", "tableId": left_id, "range": "A1:A1"},
                {"name": "RIGHT_VALUE", "tableId": right_id, "range": "A1:A1"},
            ]
        },
        "content": [
            {
                "type": "table",
                "attrs": {"tableId": left_id, "caption": "Left"},
                "content": [{"type": "tableRow", "content": [formula_cell("=RIGHT_VALUE")]}],
            },
            {
                "type": "table",
                "attrs": {"tableId": right_id, "caption": "Right"},
                "content": [{"type": "tableRow", "content": [formula_cell("=LEFT_VALUE")]}],
            },
        ],
    }
    assert validate_office_document(document) == document
    stale = deepcopy(document)
    stale["content"][1]["content"][0]["content"][0]["attrs"]["formulaResult"] = "0"
    stale["content"][1]["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "0"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(stale)


def test_native_document_validates_text_lookup_and_calendar_formulas() -> None:
    def cell(text: str, formula: str | None = None) -> dict[str, Any]:
        return {
            "type": "tableCell",
            **({"attrs": {"formula": formula, "formulaResult": text}} if formula else {}),
            "content": [{"type": "paragraph", **({"content": [{"type": "text", "text": text}]} if text else {})}],
        }

    source_id = "table-" + "9" * 24
    source: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": source_id, "caption": "Labels"},
        "content": [
            {"type": "tableRow", "content": [cell("A"), cell("Alpha")]},
            {"type": "tableRow", "content": [cell("B"), cell("Beta")]},
        ],
    }
    result: dict[str, Any] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    cell("Beta / 26", '=CONCAT(XLOOKUP("B",ITEMS,LABELS)," / ",RIGHT("2026",2))'),
                    cell("29", "=DAY(EDATE(DATE(2024,1,31),1))"),
                    cell("28", "=DAY(EOMONTH(DATE(2025,2,4),0))"),
                    cell("12", "=DAYS(DATE(2026,10,13),DATE(2026,10,1))"),
                    cell("2", "=WEEKDAY(DATE(2026,10,13))"),
                    cell("2", '=LEN(CONCAT("A","😀"))'),
                ],
            }
        ],
    }
    document: dict[str, Any] = {
        "type": "doc",
        "attrs": {
            "tableRanges": [
                {"name": "ITEMS", "tableId": source_id, "range": "A1:A2"},
                {"name": "LABELS", "tableId": source_id, "range": "B1:B2"},
            ]
        },
        "content": [source, result],
    }
    assert validate_office_document(document) == document
    forged = deepcopy(document)
    forged["content"][1]["content"][0]["content"][0]["attrs"]["formulaResult"] = "Alpha / 26"
    forged["content"][1]["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "Alpha / 26"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(forged)


def test_native_document_validates_conditional_aggregates_and_number_formats() -> None:
    def cell(text: str, formula: str | None = None, number_format: str | None = None) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if formula:
            attrs.update({"formula": formula, "formulaResult": text})
        if number_format:
            attrs["numberFormat"] = number_format
        return {
            "type": "tableCell",
            **({"attrs": attrs} if attrs else {}),
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    source_id = "table-" + "e" * 24
    source: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": source_id, "caption": "Conditional values"},
        "content": [
            {"type": "tableRow", "content": [cell("1"), cell("10")]},
            {"type": "tableRow", "content": [cell("2"), cell("20")]},
            {"type": "tableRow", "content": [cell("1"), cell("30")]},
        ],
    }
    result: dict[str, Any] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    cell("40", "=SUMIF(KEYS,1,VALUES)", "currency-eur"),
                    cell("2", "=COUNTIF(KEYS,1)", "number-0"),
                    cell("20", "=AVERAGEIF(KEYS,1,VALUES)", "number-2"),
                    cell("20738", "=DATE(2026,10,12)", "date-de"),
                ],
            }
        ],
    }
    document: dict[str, Any] = {
        "type": "doc",
        "attrs": {
            "tableRanges": [
                {"name": "KEYS", "tableId": source_id, "range": "A1:A3"},
                {"name": "VALUES", "tableId": source_id, "range": "B1:B3"},
            ]
        },
        "content": [source, result],
    }
    assert validate_office_document(document) == document
    forged = deepcopy(document)
    forged["content"][1]["content"][0]["content"][0]["attrs"]["formulaResult"] = "41"
    forged["content"][1]["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "41"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(forged)
    invalid_format = deepcopy(document)
    invalid_format["content"][1]["content"][0]["content"][1]["attrs"]["numberFormat"] = "custom-js"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(invalid_format)


def test_native_document_validates_multiple_criteria_aggregates() -> None:
    def cell(text: str, formula: str | None = None) -> dict[str, Any]:
        return {
            "type": "tableCell",
            **({"attrs": {"formula": formula, "formulaResult": text}} if formula else {}),
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    source_id = "table-" + "e" * 24
    source: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": source_id, "caption": "Criteria"},
        "content": [
            {"type": "tableRow", "content": [cell("1"), cell("1"), cell("10")]},
            {"type": "tableRow", "content": [cell("1"), cell("2"), cell("20")]},
            {"type": "tableRow", "content": [cell("2"), cell("1"), cell("30")]},
            {"type": "tableRow", "content": [cell("1"), cell("1"), cell("40")]},
        ],
    }
    result: dict[str, Any] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    cell("50", "=SUMIFS(VALUES,REGIONS,1,QUARTERS,1)"),
                    cell("2", "=COUNTIFS(REGIONS,1,QUARTERS,1)"),
                    cell("25", "=AVERAGEIFS(VALUES,REGIONS,1,QUARTERS,1)"),
                ],
            }
        ],
    }
    document: dict[str, Any] = {
        "type": "doc",
        "attrs": {
            "tableRanges": [
                {"name": "REGIONS", "tableId": source_id, "range": "A1:A4"},
                {"name": "QUARTERS", "tableId": source_id, "range": "B1:B4"},
                {"name": "VALUES", "tableId": source_id, "range": "C1:C4"},
                {"name": "SHORT", "tableId": source_id, "range": "B1:B2"},
            ]
        },
        "content": [source, result],
    }
    assert validate_office_document(document) == document
    forged = deepcopy(document)
    forged["content"][1]["content"][0]["content"][0]["attrs"]["formulaResult"] = "51"
    forged["content"][1]["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "51"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(forged)

    invalid_lengths = deepcopy(document)
    invalid_lengths["content"][1]["content"][0]["content"][0] = cell("#WERT!", "=SUMIFS(VALUES,REGIONS,1,SHORT,1)")
    assert validate_office_document(invalid_lengths) == invalid_lengths


def test_native_linked_chart_must_match_its_numbered_table_range_exactly() -> None:
    def cell(text: str, formula: str | None = None) -> dict[str, Any]:
        return {
            "type": "tableCell",
            **({"attrs": {"formula": formula, "formulaResult": text}} if formula else {}),
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    table_id = "table-" + "b" * 24
    table: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": table_id, "caption": "Quarterly values"},
        "content": [
            {"type": "tableRow", "content": [cell("Quarter"), cell("Plan"), cell("Actual")]},
            {"type": "tableRow", "content": [cell("Q1"), cell("1.5"), cell("2.25")]},
            {"type": "tableRow", "content": [cell("Q2"), cell("3"), cell("3.75", "=ROUND(B3*1.25,2)")]},
        ],
    }
    chart: dict[str, Any] = {
        "type": "chart",
        "attrs": {
            "id": "chart-" + "c" * 24,
            "kind": "bar",
            "title": "Quarterly plan",
            "altText": "Plan and actual values for two quarters.",
            "legend": True,
            "categories": ["Q1", "Q2"],
            "series": [
                {"name": "Plan", "color": "teal", "values": [1.5, 3]},
                {"name": "Actual", "color": "blue", "values": [2.25, 3.75]},
            ],
            "source": {"tableId": table_id, "range": "A1:C3"},
        },
    }
    document: dict[str, Any] = {"type": "doc", "content": [table, chart]}
    assert validate_office_document(document) == document
    invalid: list[dict[str, Any]] = []
    stale = deepcopy(document)
    stale["content"][1]["attrs"]["series"][0]["values"][0] = 99
    invalid.append(stale)
    missing = deepcopy(document)
    missing["content"][1]["attrs"]["source"]["tableId"] = "table-" + "d" * 24
    invalid.append(missing)
    outside = deepcopy(document)
    outside["content"][1]["attrs"]["source"]["range"] = "A1:C4"
    invalid.append(outside)
    external = deepcopy(document)
    external["content"][1]["attrs"]["source"]["url"] = "https://example.invalid/data"
    invalid.append(external)
    for candidate in invalid:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(candidate)


def test_native_linked_chart_accepts_row_series_orientation_and_data_labels() -> None:
    def cell(text: str) -> dict[str, Any]:
        return {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}

    table_id = "table-" + "d" * 24
    table: dict[str, Any] = {
        "type": "table",
        "attrs": {"tableId": table_id, "caption": "Rows"},
        "content": [
            {"type": "tableRow", "content": [cell("Series"), cell("Q1"), cell("Q2")]},
            {"type": "tableRow", "content": [cell("Plan"), cell("10"), cell("20")]},
            {"type": "tableRow", "content": [cell("Actual"), cell("12"), cell("18")]},
        ],
    }
    chart: dict[str, Any] = {
        "type": "chart",
        "attrs": {
            "id": "chart-" + "e" * 24,
            "kind": "line",
            "title": "Rows as series",
            "altText": "Plan and actual values by quarter.",
            "legend": True,
            "dataLabels": True,
            "categories": ["Q1", "Q2"],
            "series": [
                {"name": "Plan", "color": "teal", "values": [10, 20]},
                {"name": "Actual", "color": "blue", "values": [12, 18]},
            ],
            "source": {"tableId": table_id, "range": "A1:C3", "orientation": "rows"},
        },
    }
    document: dict[str, Any] = {"type": "doc", "content": [table, chart]}
    assert validate_office_document(document) == document
    stale = deepcopy(document)
    stale["content"][1]["attrs"]["source"]["orientation"] = "columns"
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(stale)


@pytest.mark.parametrize(
    "node",
    [
        {"type": "image", "attrs": {"src": "https://example.invalid/private"}},
        {"type": "html", "text": "<img src=x>"},
        {"type": "paragraph", "attrs": {"onclick": "secret"}},
        {"type": "heading", "attrs": {"level": True}},
        {"type": "heading", "attrs": {"level": 4}},
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": "x"}}]}],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "bold", "attrs": {}}]}]},
        {"type": "codeBlock", "content": [{"type": "text", "text": "x", "marks": [{"type": "bold"}]}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "null\x00"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "\ud800"}]},
        {"type": "paragraph", "content": [{"type": []}]},
        {"type": "paragraph", "content": ["bad"]},
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"rowspan": 2}, "content": [{"type": "paragraph"}]}],
                }
            ],
        },
        {"type": "paragraph", "data": "unexpected"},
    ],
)
def test_native_schema_rejects_active_unsupported_and_malformed_nodes(node: dict[str, Any]) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [node]})


def test_native_schema_resource_limits_are_independent() -> None:
    deep: dict[str, Any] = {"type": "paragraph"}
    for _ in range(33):
        deep = {"type": "blockquote", "content": [deep]}
    for value in (
        {"type": "doc", "content": [deep]},
        {"type": "doc", "content": [{"type": "paragraph"}] * 10_001},
        document_text("a" * 100_001),
        document_text("\U0001f600" * 40_000),
    ):
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(value)


def test_native_charts_are_bounded_inert_unique_top_level_objects() -> None:
    attrs: dict[str, Any] = {
        "id": "chart-" + "a" * 24,
        "kind": "bar",
        "title": "Quarterly plan",
        "altText": "Plan and actual values rise across four quarters.",
        "legend": True,
        "categories": ["Q1", "Q2", "Q3", "Q4"],
        "series": [
            {"name": "Plan", "color": "teal", "values": [120, 140, 160, 180]},
            {"name": "Actual", "color": "blue", "values": [110, 152, 171, 176]},
        ],
    }
    document: dict[str, Any] = {"type": "doc", "content": [{"type": "chart", "attrs": attrs}]}
    assert validate_office_document(document) == document
    decimal = deepcopy(document)
    decimal["content"][0]["attrs"]["series"][0]["values"][0] = 1.5
    assert validate_office_document(decimal) == decimal
    pie = {**attrs, "kind": "pie", "series": [{"name": "Share", "color": "orange", "values": [1, 2, 3, 4]}]}
    assert validate_office_document({"type": "doc", "content": [{"type": "chart", "attrs": pie}]})
    invalid = [
        {**attrs, "id": "chart-short"},
        {**attrs, "kind": "script"},
        {**attrs, "title": ""},
        {**attrs, "altText": "bad\x00text"},
        {**attrs, "legend": 1},
        {**attrs, "categories": []},
        {**attrs, "categories": ["Q1", "Q1"]},
        {**attrs, "series": attrs["series"] * 3},
        {**attrs, "series": [{"name": "Plan", "color": "url", "values": [1, 2, 3, 4]}]},
        {**attrs, "series": [{"name": "Plan", "color": "teal", "values": [1, 2]}]},
        {**attrs, "series": [{"name": "Plan", "color": "teal", "values": [float("nan"), 2, 3, 4]}]},
        {**attrs, "series": [{"name": "Plan", "color": "teal", "values": [-1, 2, 3, 4]}]},
        {**pie, "series": [{"name": "Share", "color": "orange", "values": [0, 0, 0, 0]}]},
        {**pie, "series": [{"name": "Share", "color": "orange", "values": [-1, 2, 3, 4]}]},
        {**attrs, "onclick": "run()"},
    ]
    for candidate in invalid:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{"type": "chart", "attrs": candidate}]})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {"type": "doc", "content": [{"type": "blockquote", "content": [{"type": "chart", "attrs": attrs}]}]}
        )
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {"type": "doc", "content": [{"type": "chart", "attrs": attrs}, {"type": "chart", "attrs": attrs}]}
        )


def test_native_shapes_are_bounded_inert_unique_top_level_objects() -> None:
    attrs = {
        "id": "shape-" + "a" * 24,
        "kind": "roundedRectangle",
        "width": 320,
        "height": 160,
        "fill": "teal",
        "stroke": "slate",
        "strokeWidth": 2,
        "text": "Literal <script> text 😀",
        "textAlign": "center",
    }
    document = {"type": "doc", "content": [{"type": "shape", "attrs": attrs}]}
    assert validate_office_document(document) == document
    positioned = {**attrs, "position": {"layer": "front", "x": 500, "y": -1200}}
    positioned_document = {"type": "doc", "content": [{"type": "shape", "attrs": positioned}]}
    assert validate_office_document(positioned_document) == positioned_document
    rotated = {**attrs, "rotation": 37}
    rotated_document = {"type": "doc", "content": [{"type": "shape", "attrs": rotated}]}
    assert validate_office_document(rotated_document) == rotated_document
    for rotation in (1, 359):
        boundary = {"type": "doc", "content": [{"type": "shape", "attrs": {**attrs, "rotation": rotation}}]}
        assert validate_office_document(boundary) == boundary
    wrapped = {**attrs, "wrap": {"side": "right", "gap": 48}}
    wrapped_document = {"type": "doc", "content": [{"type": "shape", "attrs": wrapped}]}
    assert validate_office_document(wrapped_document) == wrapped_document
    formatted = {**attrs, "fontSize": 28, "textColor": "purple", "textStyle": "boldItalic"}
    formatted_document = {"type": "doc", "content": [{"type": "shape", "attrs": formatted}]}
    assert validate_office_document(formatted_document) == formatted_document
    accessible = {**attrs, "name": "Process start", "altText": "Starts the bounded approval process"}
    accessible_document = {"type": "doc", "content": [{"type": "shape", "attrs": accessible}]}
    assert validate_office_document(accessible_document) == accessible_document
    protected = {**accessible, "hidden": True, "locked": True}
    protected_document = {"type": "doc", "content": [{"type": "shape", "attrs": protected}]}
    assert validate_office_document(protected_document) == protected_document
    invalid = [
        {**attrs, "id": "shape-short"},
        {**attrs, "kind": "svg"},
        {**attrs, "width": 79},
        {**attrs, "height": 801},
        {**attrs, "fill": "url(https://example.invalid)"},
        {**attrs, "strokeWidth": True},
        {**attrs, "text": "bad\x00text"},
        {**attrs, "textAlign": "justify"},
        {**attrs, "fontSize": 9},
        {**attrs, "fontSize": 16},
        {**attrs, "fontSize": 73},
        {**attrs, "fontSize": True},
        {**attrs, "textColor": "transparent"},
        {**attrs, "textColor": "url(https://example.invalid)"},
        {**attrs, "textStyle": "normal"},
        {**attrs, "textStyle": "bold;position:fixed"},
        {**attrs, "rotation": 0},
        {**attrs, "rotation": -1},
        {**attrs, "rotation": 360},
        {**attrs, "rotation": 90.0},
        {**attrs, "rotation": True},
        {**attrs, "name": ""},
        {**attrs, "name": " leading"},
        {**attrs, "name": "x" * 81},
        {**attrs, "altText": "bad\ntext"},
        {**attrs, "altText": "x" * 501},
        {**attrs, "altText": True},
        {**attrs, "hidden": False},
        {**attrs, "hidden": 1},
        {**attrs, "locked": False},
        {**attrs, "locked": "true"},
        {**attrs, "wrap": {"side": "middle", "gap": 0}},
        {**attrs, "wrap": {"side": "left", "gap": 49}},
        {**attrs, "wrap": {"side": "right", "gap": True}},
        {**attrs, "wrap": {"side": "left", "gap": 0, "style": "float"}},
        {**attrs, "position": {"layer": "front", "x": 0, "y": 0}, "wrap": {"side": "left", "gap": 16}},
        {**attrs, "onclick": "run()"},
        {**attrs, "position": {"layer": "middle", "x": 0, "y": 0}},
        {**attrs, "position": {"layer": "behind", "x": 1001, "y": 0}},
        {**attrs, "position": {"layer": "front", "x": 0, "y": -1201}},
        {**attrs, "position": {"layer": "front", "x": True, "y": 0}},
        {**attrs, "position": {"layer": "front", "x": 0, "y": 0, "style": "fixed"}},
    ]
    for candidate in invalid:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{"type": "shape", "attrs": candidate}]})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {"type": "doc", "content": [{"type": "blockquote", "content": [{"type": "shape", "attrs": attrs}]}]}
        )
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {"type": "doc", "content": [{"type": "shape", "attrs": attrs}, {"type": "shape", "attrs": attrs}]}
        )


def test_native_shape_groups_are_bounded_positionable_root_objects() -> None:
    def shape(index: int) -> dict[str, Any]:
        return {
            "type": "shape",
            "attrs": {
                "id": "shape-" + f"{index:024x}",
                "kind": "rectangle",
                "width": 240,
                "height": 120,
                "fill": "white",
                "stroke": "slate",
                "strokeWidth": 2,
                "text": f"Shape {index}",
                "textAlign": "center",
                **({"rotation": 143} if index == 2 else {}),
            },
        }

    group: dict[str, Any] = {
        "type": "shapeGroup",
        "attrs": {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16},
        "content": [shape(1), shape(2)],
    }
    document = {"type": "doc", "content": [group]}
    assert validate_office_document(document) == document
    accessible_group = {
        **group,
        "attrs": {**group["attrs"], "name": "Approval path", "altText": "Two connected approval steps"},
    }
    assert validate_office_document({"type": "doc", "content": [accessible_group]})["content"][0] == accessible_group
    protected_group = {
        **group,
        "attrs": {**group["attrs"], "hidden": True, "locked": True},
    }
    assert validate_office_document({"type": "doc", "content": [protected_group]})["content"][0] == protected_group
    connected = {
        **group,
        "attrs": {**group["attrs"], "connection": {"kind": "doubleArrow", "color": "purple", "width": 8}},
    }
    assert validate_office_document({"type": "doc", "content": [connected]})["content"][0] == connected
    per_edge = {
        **group,
        "attrs": {
            **group["attrs"],
            "connections": [{"kind": "arrow", "color": "red", "width": 3}],
        },
    }
    assert validate_office_document({"type": "doc", "content": [per_edge]})["content"][0] == per_edge
    aligned = {
        **group,
        "attrs": {
            **group["attrs"],
            "alignment": "center",
            "distributionExtent": 800,
        },
    }
    assert validate_office_document({"type": "doc", "content": [aligned]})["content"][0] == aligned
    for position in [
        {"layer": "front", "x": 0, "y": -1200},
        {"layer": "behind", "x": 1000, "y": 1200},
    ]:
        positioned = {**group, "attrs": {**group["attrs"], "position": position}}
        assert validate_office_document({"type": "doc", "content": [positioned]})["content"][0] == positioned
    for attrs in [
        {"id": "short", "layout": "row", "gap": 16},
        {"id": "shape-group-" + "a" * 24, "layout": "grid", "gap": 16},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": -1},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 49},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": True},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "name": ""},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "name": "x" * 81},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "altText": "bad\ttext"},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "altText": "x" * 501},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "hidden": False},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "hidden": 1},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "locked": False},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "locked": "true"},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "style": "display:flex"},
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "curve", "color": "blue", "width": 2},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "arrow", "color": "url", "width": 2},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "line", "color": "black", "width": 0},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "line", "color": "black", "width": True},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "line", "color": "black", "width": 2, "path": "M0 0"},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connection": {"kind": "line", "color": "black", "width": 2},
            "connections": [None],
        },
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "connections": []},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "connections": [False]},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "alignment": "start"},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "alignment": "stretch"},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "distributionExtent": 159},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "distributionExtent": 2401},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "distributionExtent": True},
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "connections": [{"kind": "line", "color": "black", "width": True}],
        },
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "position": {}},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "position": []},
        {"id": "shape-group-" + "a" * 24, "layout": "row", "gap": 16, "position": "front"},
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "middle", "x": 0, "y": 0},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "front", "x": -1, "y": 0},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "behind", "x": 1001, "y": 0},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "front", "x": True, "y": 0},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "front", "x": 0, "y": -1201},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "behind", "x": 0, "y": 1201},
        },
        {
            "id": "shape-group-" + "a" * 24,
            "layout": "row",
            "gap": 16,
            "position": {"layer": "front", "x": 0, "y": 0, "style": "fixed"},
        },
    ]:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{**group, "attrs": attrs}]})
    for members in [[shape(1)], [shape(index) for index in range(1, 10)]]:
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{**group, "content": members}]})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {
                "type": "doc",
                "content": [{**group, "attrs": {**group["attrs"], "connections": [None, None]}}],
            }
        )
    for key, value in (("wrap", {"side": "left", "gap": 16}), ("position", {"layer": "front", "x": 0, "y": 0})):
        member = shape(1)
        member["attrs"][key] = value
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{**group, "content": [member, shape(2)]}]})
    for key in ("hidden", "locked"):
        member = shape(1)
        member["attrs"][key] = True
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document({"type": "doc", "content": [{**group, "content": [member, shape(2)]}]})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [{"type": "blockquote", "content": [group]}]})
    duplicate = {"type": "doc", "content": [group, {**group, "content": [shape(3), shape(4)]}]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(duplicate)


@pytest.fixture
def office() -> tuple[OfficeDocumentService, InMemoryOfficeDocumentRepository, UserContext]:
    sources = InMemorySourceObjectRepository()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    service = OfficeDocumentService(repository=repository, source_repository=sources, audit=InMemoryAuditLogger())
    user = UserContext(tenant_id="tenant-native-office", user_id="editor", role_ids={"office-editor"})
    return service, repository, user


def test_native_create_save_history_and_actor_bound_idempotency(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    replay = service.create(user_context=user, command=create_command(), write_enabled=True)
    assert replay.replayed and replay.version == created.version
    saved = service.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Revised title",
            document=document_text("New text"),
            mutation_reference="save-1",
            human_confirmation=True,
            expected_current_version_id=created.version.version_id,
        ),
    )
    assert saved.version.previous_version_id == created.version.version_id
    assert saved.version.version_id != created.version.version_id
    assert service.read_content(user_context=user, object_id=object_id).content == document_text("New text")
    old = service.read_content(user_context=user, object_id=object_id, version_id=created.version.version_id)
    assert old.content == create_command().document and not old.is_current_version
    assert old.version.title == "Private document title" and old.document.title == "Revised title"
    late_replay = service.create(user_context=user, command=create_command(), write_enabled=True)
    assert late_replay.replayed and not late_replay.is_current_version
    assert late_replay.document.current_version_id == saved.version.version_id
    assert len(service.history(user_context=user, object_id=object_id).versions) == 2
    assert len(repository.receipt_store.list_receipts(tenant_id=user.tenant_id)) == 2
    with pytest.raises(OfficeDocumentConflictError):
        service.create(
            user_context=user, command=create_command().model_copy(update={"title": "Changed"}), write_enabled=True
        )
    assert not created.rag_indexing_allowed and not created.search_indexing_allowed
    audit_payload = canonical_json([event.model_dump() for event in service.audit.events])
    assert "Confidential native draft" not in audit_payload
    assert "Private document title" not in audit_payload
    assert "New text" not in audit_payload
    assert all(event.metadata["surface"] == "api" for event in service.audit.events)


def test_edit_lease_coordinates_sessions_without_replacing_version_cas(office: Any) -> None:
    service, _repository, user = office
    created = service.create(user_context=user, command=create_command("lease-create"), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    first_session = "office-session-" + "a" * 32
    second_session = "office-session-" + "b" * 32

    first = service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=first_session, expected_current_version_id=created.version.version_id
        ),
        write_enabled=True,
    )
    assert first.status == "held_by_current_session"
    assert first.can_acquire and not first.can_take_over and not first.takeover_performed

    blocked = service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=second_session, expected_current_version_id=created.version.version_id
        ),
        write_enabled=True,
    )
    assert blocked.status == "held_by_other" and blocked.can_take_over

    taken = service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=second_session,
            expected_current_version_id=created.version.version_id,
            takeover_confirmed=True,
        ),
        write_enabled=True,
    )
    assert taken.status == "held_by_current_session" and taken.takeover_performed
    assert (
        service.edit_lease(user_context=user, object_id=object_id, session_id=first_session, write_enabled=True).status
        == "held_by_other"
    )

    saved = service.save(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentSaveCommand(
            **create_command("lease-save").model_dump(), expected_current_version_id=created.version.version_id
        ),
        write_enabled=True,
    )
    stale_lease = service.edit_lease(
        user_context=user, object_id=object_id, session_id=first_session, write_enabled=True
    )
    assert stale_lease.status == "available" and stale_lease.base_version_id == saved.version.version_id
    with pytest.raises(OfficeDocumentConflictError):
        service.acquire_edit_lease(
            user_context=user,
            object_id=object_id,
            command=OfficeDocumentEditLeaseCommand(
                session_id=first_session, expected_current_version_id=created.version.version_id
            ),
            write_enabled=True,
        )

    renewed = service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=first_session, expected_current_version_id=saved.version.version_id
        ),
        write_enabled=True,
    )
    released = service.release_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseReleaseCommand(session_id=first_session),
        write_enabled=True,
    )
    assert released.status == "available" and released.lease_revision == renewed.lease_revision + 1
    assert released.release_performed
    denied_release = service.release_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseReleaseCommand(session_id=second_session),
        write_enabled=True,
    )
    assert denied_release.status == "available" and not denied_release.release_performed
    audit_payload = canonical_json([event.model_dump() for event in service.audit.events])
    assert first_session not in audit_payload and second_session not in audit_payload
    assert any(event.event_type == "office.documents.edit_lease.taken_over" for event in service.audit.events)
    assert any(event.event_type == "office.documents.edit_lease.release_requested" for event in service.audit.events)


def test_document_lifecycle_separates_ephemeral_work_saved_versions_and_closed_record_transitions(
    office: Any,
) -> None:
    service, _repository, user = office
    created = service.create(user_context=user, command=create_command("lifecycle-create"), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    session_id = "office-session-" + "c" * 32
    service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=session_id, expected_current_version_id=created.version.version_id
        ),
        write_enabled=True,
    )

    lifecycle = service.lifecycle(user_context=user, object_id=object_id, session_id=session_id, write_enabled=True)
    assert lifecycle.current_version_id == created.version.version_id
    assert lifecycle.working_data == "request_transient"
    assert lifecycle.draft_state == "browser_memory_only"
    assert lifecycle.collaborative_state == "held_by_current_session"
    assert lifecycle.collaborative_base_version_id == created.version.version_id
    assert lifecycle.saved_version_state == "current_immutable_version"
    assert lifecycle.business_record_state == lifecycle.worm_record_state == "transition_closed"
    assert lifecycle.save_requires_human_confirmation and lifecycle.save_requires_current_version
    assert lifecycle.business_record_requires_human_confirmation and not lifecycle.ai_may_commit_business_record

    read_only_view = service.lifecycle(
        user_context=user, object_id=object_id, session_id=session_id, write_enabled=False
    )
    assert read_only_view.collaborative_state == "unavailable"
    audit_payload = canonical_json([event.model_dump() for event in service.audit.events])
    assert session_id not in audit_payload
    assert any(event.event_type == "office.documents.lifecycle.read" for event in service.audit.events)


def test_collaboration_preflight_binds_acl_version_session_and_closed_runtime_without_state_writes(
    office: Any,
) -> None:
    service, repository, user = office
    created = service.create(
        user_context=user,
        command=create_command("collaboration-preflight-create"),
        write_enabled=True,
    )
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    session_id = "office-session-" + "d" * 32
    service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=session_id,
            expected_current_version_id=created.version.version_id,
        ),
        write_enabled=True,
    )
    for index in range(50):
        response = service.collaboration_preflight(
            user_context=user,
            object_id=object_id,
            command=OfficeDocumentCollaborationPreflightCommand(
                session_id=session_id,
                client_instance_id=f"office-client-{index:032x}",
                expected_current_version_id=created.version.version_id,
                capabilities=["awareness_v1", "binary_update_v1", "state_vector_v1"],
            ),
            write_enabled=True,
        )
        assert response.contract_state == "prepared_runtime_closed"
        assert response.transport_state == "websocket_not_admitted" and not response.runtime_admitted
        assert response.target_concurrent_editors == 50 and response.max_update_bytes == 262144
        assert response.document_acl_revalidation_required and response.update_acl_revalidation_required
        assert response.immutable_save_cas_required and not response.raw_session_or_client_id_persisted
        assert response.isolated_load_proof_state == "verified_50_parallel_editors"
        assert not response.websocket_load_verified and "fifty_editor_load_not_verified" not in response.blockers
    assert len(repository.documents) == len(repository.saved_versions) == len(repository.edit_leases) == 1
    audit_payload = canonical_json([event.model_dump(mode="json") for event in service.audit.events])
    assert session_id not in audit_payload and "office-client-" not in audit_payload
    assert sum(event.event_type == "office.documents.collaboration.preflight" for event in service.audit.events) == 50

    with pytest.raises(OfficeDocumentConflictError):
        service.collaboration_preflight(
            user_context=user,
            object_id=object_id,
            command=OfficeDocumentCollaborationPreflightCommand(
                session_id="office-session-" + "e" * 32,
                client_instance_id="office-client-" + "e" * 32,
                expected_current_version_id=created.version.version_id,
                capabilities=["binary_update_v1", "state_vector_v1"],
            ),
            write_enabled=True,
        )
    with pytest.raises(OfficeDocumentPermissionError):
        service.collaboration_preflight(
            user_context=user,
            object_id=object_id,
            command=OfficeDocumentCollaborationPreflightCommand(
                session_id=session_id,
                client_instance_id="office-client-" + "f" * 32,
                expected_current_version_id=created.version.version_id,
                capabilities=["binary_update_v1", "state_vector_v1"],
            ),
            write_enabled=False,
        )


@pytest.mark.parametrize(
    "capabilities",
    [
        ["binary_update_v1"],
        ["binary_update_v1", "binary_update_v1", "state_vector_v1"],
        ["state_vector_v1", "binary_update_v1"],
    ],
)
def test_collaboration_preflight_capabilities_are_complete_unique_and_canonical(capabilities: list[str]) -> None:
    with pytest.raises(ValidationError):
        OfficeDocumentCollaborationPreflightCommand.model_validate(
            {
                "session_id": "office-session-" + "1" * 32,
                "client_instance_id": "office-client-" + "2" * 32,
                "expected_current_version_id": "office-version-" + "3" * 32,
                "capabilities": capabilities,
            }
        )


def test_gateway_preflight_binds_same_origin_acl_version_and_lease_without_issuing_credentials_or_state(
    office: Any,
) -> None:
    service, repository, user = office
    created = service.create(
        user_context=user,
        command=create_command("gateway-preflight-create"),
        write_enabled=True,
    )
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    session_id = "office-session-" + "7" * 32
    client_id = "office-client-" + "8" * 32
    service.acquire_edit_lease(
        user_context=user,
        object_id=object_id,
        command=OfficeDocumentEditLeaseCommand(
            session_id=session_id,
            expected_current_version_id=created.version.version_id,
        ),
        write_enabled=True,
    )
    command = OfficeDocumentGatewayPreflightCommand(
        session_id=session_id,
        client_instance_id=client_id,
        expected_current_version_id=created.version.version_id,
        requested_subprotocols=["collabio-office-crdt.v1"],
        transport_capabilities=[
            "binary_frames_v1",
            "bounded_backpressure_v1",
            "heartbeat_v1",
            "reauth_v1",
            "resume_state_vector_v1",
        ],
    )
    response = service.gateway_preflight(
        user_context=user,
        object_id=object_id,
        command=command,
        browser_origin="https://office.example.test",
        request_origin="https://office.example.test",
        write_enabled=True,
    )
    assert response.gateway_contract_state == "prepared_upgrade_closed"
    assert response.upgrade_state == "http_upgrade_not_admitted" and not response.server_accepts_connections
    assert response.required_subprotocol == "collabio-office-crdt.v1"
    assert response.max_frame_bytes == 262144 and response.max_queued_bytes == 1048576
    assert response.backpressure_close_code == 1013
    assert response.heartbeat_interval_seconds == 25
    assert response.reauthorization_interval_seconds == 60 and response.max_connection_seconds == 300
    assert not response.query_credentials_allowed and not response.compression_admitted
    assert not response.credential_issued and "websocket_load_not_verified" in response.blockers
    assert len(repository.documents) == len(repository.saved_versions) == len(repository.edit_leases) == 1
    audit_payload = canonical_json([event.model_dump(mode="json") for event in service.audit.events])
    assert session_id not in audit_payload and client_id not in audit_payload
    assert "office.example.test" not in audit_payload

    with pytest.raises(OfficeDocumentPermissionError):
        service.gateway_preflight(
            user_context=user,
            object_id=object_id,
            command=command,
            browser_origin="https://attacker.example",
            request_origin="https://office.example.test",
            write_enabled=True,
        )
    with pytest.raises(OfficeDocumentPermissionError):
        service.gateway_preflight(
            user_context=user,
            object_id=object_id,
            command=command,
            browser_origin="null",
            request_origin="https://office.example.test",
            write_enabled=True,
        )


@pytest.mark.parametrize(
    ("subprotocols", "capabilities"),
    [
        (
            [],
            [
                "binary_frames_v1",
                "bounded_backpressure_v1",
                "heartbeat_v1",
                "reauth_v1",
                "resume_state_vector_v1",
            ],
        ),
        (
            ["collabio-office-crdt.v1"],
            [
                "bounded_backpressure_v1",
                "binary_frames_v1",
                "heartbeat_v1",
                "reauth_v1",
                "resume_state_vector_v1",
            ],
        ),
        (
            ["collabio-office-crdt.v1"],
            ["binary_frames_v1", "bounded_backpressure_v1", "heartbeat_v1", "reauth_v1"],
        ),
    ],
)
def test_gateway_preflight_requires_exact_subprotocol_and_transport_capabilities(
    subprotocols: list[str],
    capabilities: list[str],
) -> None:
    with pytest.raises(ValidationError):
        OfficeDocumentGatewayPreflightCommand.model_validate(
            {
                "session_id": "office-session-" + "1" * 32,
                "client_instance_id": "office-client-" + "2" * 32,
                "expected_current_version_id": "office-version-" + "3" * 32,
                "requested_subprotocols": subprotocols,
                "transport_capabilities": capabilities,
            }
        )


def test_parser_worker_plan_is_tenant_scoped_metadata_only_audited_and_dispatch_closed(office: Any) -> None:
    service, _repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.parser_worker_plan(user_context=user)

    response = service.parser_worker_plan(user_context=user, read_enabled=True)
    assert response.tenant_id == user.tenant_id
    assert response.plan_state == "planned_dispatch_closed"
    assert response.worker_profile_id == "rich-document-parser-worker:1"
    assert not response.dispatch_allowed and not response.production_admitted
    assert not response.content_accepted_by_plan_endpoint
    assert not response.direct_storage_mutation_allowed and not response.direct_vector_writes_allowed
    assert not response.normal_logs_may_contain_content and not response.output_trusted_without_validation
    event = service.audit.events[-1]
    assert event.event_type == "office.documents.parser_worker_plan.read"
    assert event.metadata["content_included"] is False
    assert set(event.metadata) == {
        "module_id",
        "surface",
        "rag_indexing_allowed",
        "search_indexing_allowed",
        "schema_version",
        "plan_state",
        "worker_profile_id",
        "supported_mime_type_count",
        "source_requirement_count",
        "pipeline_step_count",
        "isolation_requirement_count",
        "blocker_count",
        "dispatch_allowed",
        "production_admitted",
        "content_included",
    }


def test_macro_policy_is_tenant_scoped_metadata_only_audited_and_execution_closed(office: Any) -> None:
    service, _repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.macro_policy(user_context=user)

    response = service.macro_policy(user_context=user, read_enabled=True)
    assert response.tenant_id == user.tenant_id
    assert response.policy_state == "enforced_execution_disabled"
    assert response.active_content_detection_enforced_by_parser
    assert not response.active_content_execution_allowed and not response.automatic_active_content_removal_allowed
    assert not response.blocked_input_extraction_allowed and response.marked_input_extraction_allowed
    assert not response.content_accepted_by_policy_endpoint and not response.parser_dispatch_allowed
    event = service.audit.events[-1]
    assert event.event_type == "office.documents.macro_policy.read"
    assert event.metadata["content_included"] is False
    assert set(event.metadata) == {
        "module_id",
        "surface",
        "rag_indexing_allowed",
        "search_indexing_allowed",
        "schema_version",
        "policy_state",
        "supported_mime_type_count",
        "blocking_indicator_count",
        "review_marking_count",
        "blocker_count",
        "active_content_execution_allowed",
        "parser_dispatch_allowed",
        "content_included",
    }


def test_import_compatibility_matrix_is_tenant_scoped_metadata_only_audited_and_closed(office: Any) -> None:
    service, _repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.import_compatibility_matrix(user_context=user)

    response = service.import_compatibility_matrix(user_context=user, read_enabled=True)
    assert response.tenant_id == user.tenant_id
    assert response.matrix_state == "development_contract_dispatch_closed"
    assert len(response.entries) == 13
    assert not response.content_accepted_by_matrix_endpoint
    assert not response.import_dispatch_allowed and not response.export_allowed
    assert not response.round_trip_fidelity_claimed and not response.production_admitted
    event = service.audit.events[-1]
    assert event.event_type == "office.documents.import_compatibility_matrix.read"
    assert event.metadata["content_included"] is False
    assert set(event.metadata) == {
        "module_id",
        "surface",
        "rag_indexing_allowed",
        "search_indexing_allowed",
        "schema_version",
        "matrix_state",
        "entry_count",
        "supported_format_count",
        "blocked_entry_count",
        "marked_entry_count",
        "import_dispatch_allowed",
        "export_allowed",
        "round_trip_fidelity_claimed",
        "content_included",
    }


def test_interchange_corpus_manifest_is_tenant_scoped_metadata_only_audited_and_closed(office: Any) -> None:
    service, _repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.interchange_corpus_manifest(user_context=user)

    response = service.interchange_corpus_manifest(user_context=user, read_enabled=True)
    assert response.tenant_id == user.tenant_id
    assert len(response.fixtures) == 9
    assert not response.fixture_bytes_returned and not response.import_dispatch_allowed
    assert not response.export_engine_available and not response.round_trip_fidelity_claimed
    event = service.audit.events[-1]
    assert event.event_type == "office.documents.interchange_corpus_manifest.read"
    assert event.metadata["fixture_count"] == 9
    assert event.metadata["blocked_fixture_count"] == 3
    assert event.metadata["marked_fixture_count"] == 3
    assert event.metadata["fixture_bytes_returned"] is False


def test_document_information_classification_is_versioned_audited_and_admin_controls_downgrades(
    office: Any,
) -> None:
    service, repository, editor = office
    with pytest.raises(ValidationError):
        OfficeDocumentCreateCommand.model_validate(
            {**create_command().model_dump(), "information_classification": "secret"}
        )
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(
            user_context=editor,
            command=create_command("public-create").model_copy(update={"information_classification": "public"}),
            write_enabled=True,
        )

    created = service.create(user_context=editor, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    editor.readable_object_ids.add(object_id)
    protected = service.save(
        user_context=editor,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **{**create_command("protect").model_dump(), "information_classification": "restricted"},
            expected_current_version_id=created.version.version_id,
        ),
    )
    assert created.document.information_classification == "internal"
    assert created.version.information_classification == "internal"
    assert protected.document.information_classification == "restricted"
    assert protected.version.information_classification == "restricted"
    historical = service.read_content(user_context=editor, object_id=object_id, version_id=created.version.version_id)
    assert historical.document.information_classification == "restricted"
    assert historical.version.information_classification == "internal"
    metadata = repository.source_repository.get_metadata(
        tenant_id=editor.tenant_id, object_id=object_id, version_id=protected.version.version_id
    )
    assert metadata.classification.value == "internal"

    with pytest.raises(OfficeDocumentPermissionError):
        service.save(
            user_context=editor,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **{**create_command("downgrade-denied").model_dump(), "information_classification": "confidential"},
                expected_current_version_id=protected.version.version_id,
            ),
        )
    admin = editor.model_copy(update={"role_ids": {"tenant-admin"}})
    downgraded = service.save(
        user_context=admin,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **{**create_command("downgrade-admin").model_dump(), "information_classification": "confidential"},
            expected_current_version_id=protected.version.version_id,
        ),
    )
    assert downgraded.version.information_classification == "confidential"
    saved_event = [event for event in service.audit.events if event.event_type == "office.documents.saved"][-1]
    assert saved_event.metadata["information_classification"] == "confidential"
    assert saved_event.metadata["previous_information_classification"] == "restricted"
    assert saved_event.metadata["classification_changed"] is True


def test_native_write_gates_readonly_acl_revoke_and_foreign_tenant(office: Any) -> None:
    service, repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=user, command=create_command())
    viewer = user.model_copy(update={"role_ids": set()})
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=viewer, command=create_command(), write_enabled=True)
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    command = OfficeDocumentSaveCommand(
        **create_command("save").model_dump(), expected_current_version_id=created.version.version_id
    )
    repository.grants[(user.tenant_id, object_id, user.user_id)] = "read"
    assert service.read_content(user_context=user, object_id=object_id, write_enabled=True).can_write is False
    with pytest.raises(OfficeDocumentPermissionError):
        service.save(user_context=user, object_id=object_id, command=command, write_enabled=True)
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=user, command=create_command(), write_enabled=True)
    foreign = user.model_copy(update={"tenant_id": "tenant-foreign"})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=foreign, object_id=object_id)
    del repository.grants[(user.tenant_id, object_id, user.user_id)]
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=user, object_id=object_id)
    assert service.list_documents(user_context=user, write_enabled=True).documents == []


def test_stale_save_and_missing_confirmation_have_no_source_or_receipt_side_effect(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    user.readable_object_ids.add(created.document.object_id)
    command = OfficeDocumentSaveCommand(**create_command("save").model_dump(), expected_current_version_id="stale")
    with pytest.raises(OfficeDocumentConflictError):
        service.save(user_context=user, object_id=created.document.object_id, command=command, write_enabled=True)
    with pytest.raises(ValidationError):
        service.create(
            user_context=user,
            command=create_command().model_copy(update={"human_confirmation": False}),
            write_enabled=True,
        )
    with pytest.raises(ValidationError):
        OfficeDocumentCreateCommand.model_validate({**create_command().model_dump(), "human_confirmation": "true"})
    assert len(repository.saved_versions) == 1
    assert len(repository.receipt_store.list_receipts(tenant_id=user.tenant_id)) == 1


def test_unavailable_write_adapter_denies_writes_and_does_not_advertise_editing(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    readonly = OfficeDocumentService(
        repository=repository,
        source_repository=repository.source_repository,
        audit=service.audit,
        writes_available=False,
    )
    listed = readonly.list_documents(user_context=user, write_enabled=True)
    assert not listed.can_create and not listed.documents[0].can_write
    read = readonly.read_content(user_context=user, object_id=object_id, write_enabled=True)
    assert not read.can_write and not read.document.can_write
    with pytest.raises(OfficeDocumentPermissionError):
        readonly.create(user_context=user, command=create_command("new"), write_enabled=True)
    with pytest.raises(OfficeDocumentPermissionError):
        readonly.save(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **create_command("save").model_dump(), expected_current_version_id=created.version.version_id
            ),
        )
    assert len(repository.saved_versions) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "tenant-foreign"),
        ("mime_type", "text/html"),
        ("source_system", "other"),
        ("lifecycle_state", "restricted"),
        ("content_hash", "sha256:" + "f" * 64),
        ("content_byte_length", 400_001),
        ("created_by", "another-user"),
        ("acl_version", 99),
    ],
)
def test_source_metadata_corruption_is_rejected_before_content_read(
    office: Any, monkeypatch: Any, field: str, value: Any
) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    metadata = repository.source_repository.get_metadata(
        tenant_id=user.tenant_id, object_id=object_id, version_id=created.version.version_id
    )
    monkeypatch.setattr(
        repository.source_repository, "get_metadata", lambda **_: metadata.model_copy(update={field: value})
    )
    monkeypatch.setattr(
        repository.source_repository, "get", lambda **_: pytest.fail("preflight must block content access")
    )
    with pytest.raises(OfficeDocumentInvalidContentError):
        service.read_content(user_context=user, object_id=object_id)


def test_read_denied_before_metadata_and_storage_outage_is_not_misclassified(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    monkeypatch.setattr(repository.source_repository, "get_metadata", lambda **_: pytest.fail("denied before metadata"))
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=user, object_id=object_id)
    monkeypatch.undo()
    user.readable_object_ids.add(object_id)

    def unavailable(**_: Any) -> SourceObjectRecord:
        raise SourceObjectStorageError("private storage endpoint must not leak")

    monkeypatch.setattr(repository.source_repository, "get", unavailable)
    with pytest.raises(SourceObjectStorageError):
        service.read_content(user_context=user, object_id=object_id)


def test_loaded_bytes_must_match_exact_manifest_and_canonical_document(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    record = repository.source_repository.get(
        tenant_id=user.tenant_id, object_id=object_id, version_id=created.version.version_id
    )
    corrupted = deepcopy(record)
    corrupted.content_bytes = b"wrong bytes"
    monkeypatch.setattr(repository.source_repository, "get", lambda **_: corrupted)
    with pytest.raises(OfficeDocumentInvalidContentError):
        service.read_content(user_context=user, object_id=object_id)
