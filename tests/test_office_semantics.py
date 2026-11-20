from __future__ import annotations

from copy import deepcopy

import pytest

from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document

FIELD = {"key": "project", "label": "Project", "value": "Apollo"}
SOURCE = {
    "id": "source-111111111111111111111111",
    "author": "Ada Lovelace",
    "title": "Notes on the Analytical Engine",
    "year": "1843",
    "locator": "https://example.org/source",
}


def semantic_document() -> dict[str, object]:
    return {
        "type": "doc",
        "attrs": {"documentFields": [FIELD], "citationSources": [SOURCE]},
        "content": [
            {"type": "tableOfContents", "attrs": {"maxLevel": 3}},
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Overview"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Project: "},
                    {"type": "documentField", "attrs": {"key": "project"}},
                    {
                        "type": "noteReference",
                        "attrs": {"id": "note-222222222222222222222222", "kind": "footnote", "text": "Primary note"},
                    },
                    {
                        "type": "noteReference",
                        "attrs": {"id": "note-333333333333333333333333", "kind": "endnote", "text": "Closing note"},
                    },
                    {"type": "citationReference", "attrs": {"sourceId": SOURCE["id"], "locator": "p. 12"}},
                ],
            },
            {"type": "bibliography"},
            {
                "type": "equation",
                "attrs": {
                    "id": "equation-444444444444444444444444",
                    "source": "E = mc^2",
                    "alt": "Energy equals mass times the speed of light squared",
                },
            },
            {"type": "referenceIndex"},
        ],
    }


def test_office_semantic_structures_are_inert_and_version_owned() -> None:
    value = semantic_document()
    assert validate_office_document(value) == value


def test_office_fields_and_citations_preserve_explicit_broken_references() -> None:
    value = semantic_document()
    value["attrs"] = {}
    assert validate_office_document(value) == value


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["attrs"]["documentFields"].append(deepcopy(FIELD)),
        lambda value: value["attrs"]["citationSources"].append(deepcopy(SOURCE)),
        lambda value: value["content"].append({"type": "tableOfContents", "attrs": {"maxLevel": 2}}),
        lambda value: value["content"].append({"type": "bibliography"}),
        lambda value: value["content"].append({"type": "referenceIndex"}),
        lambda value: value["content"].append(deepcopy(value["content"][4])),
    ],
)
def test_office_semantic_catalogs_and_generated_structures_are_unambiguous(mutation) -> None:  # type: ignore[no-untyped-def]
    value = semantic_document()
    mutation(value)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(value)


@pytest.mark.parametrize(
    "node",
    [
        {"type": "documentField", "attrs": {"key": "Project"}},
        {"type": "noteReference", "attrs": {"id": "note-short", "kind": "footnote", "text": "Note"}},
        {"type": "noteReference", "attrs": {"id": "note-222222222222222222222222", "kind": "side", "text": "Note"}},
        {"type": "citationReference", "attrs": {"sourceId": "https://example.org", "locator": ""}},
    ],
)
def test_office_inline_semantics_reject_malformed_identifiers(node: dict[str, object]) -> None:
    value = semantic_document()
    value["content"] = [{"type": "paragraph", "content": [node]}]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(value)


def test_office_formulas_are_bounded_literal_text_not_executable_objects() -> None:
    value = semantic_document()
    value["content"][4]["attrs"]["source"] = "x" * 1001  # type: ignore[index]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(value)
    value = semantic_document()
    value["content"][4]["attrs"]["engine"] = "javascript"  # type: ignore[index]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(value)


def test_office_semantic_limits_are_enforced() -> None:
    value = semantic_document()
    value["attrs"]["documentFields"] = [  # type: ignore[index]
        {"key": f"field-{number}", "label": f"Field {number}", "value": "value"} for number in range(51)
    ]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(value)
