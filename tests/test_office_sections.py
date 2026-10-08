from copy import deepcopy
from typing import Any

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text
from test_office_documents_api import BASE, OfficeApiHarness, create_payload, enable_office
from test_office_documents_api import office_api as office_api


def paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def profile() -> dict[str, Any]:
    return {
        "page": {
            "paper": "letter",
            "orientation": "landscape",
            "columns": "three",
            "margins": {"top": 20, "right": 12, "bottom": 22, "left": 14},
        },
        "running": {"header": "Appendix", "footer": "Internal", "numbering": "pageOfPages"},
    }


def section_break() -> dict[str, Any]:
    return {"type": "sectionBreak", "attrs": profile()}


def test_section_break_preserves_legacy_bytes_and_exact_profile() -> None:
    legacy: dict[str, Any] = {"type": "doc", "content": [paragraph("Before"), paragraph("After")]}
    before = canonical_json(legacy)
    document = deepcopy(legacy)
    document["content"].insert(1, section_break())
    assert validate_office_document(document) is document
    assert document["content"][1] == section_break()
    assert canonical_json(validate_office_document(legacy)) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra=True),
        lambda value: value.pop("page"),
        lambda value: value["page"].update(paper="SECRET"),
        lambda value: value["page"].update(columns="repeat(3, 1fr)"),
        lambda value: value["page"]["margins"].update(left=4),
        lambda value: value["running"].update(numbering="counter(secret)"),
        lambda value: value["running"].update(header="x" * 65),
        lambda value: value["running"].update(header="line\nbreak"),
        lambda value: value["running"].update(firstPage={"header": "x", "footer": "", "showNumber": False}),
    ],
)
def test_section_profile_rejects_non_literal_or_incomplete_values(mutate: Any) -> None:
    value = profile()
    mutate(value)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {
                "type": "doc",
                "content": [paragraph("Before"), {"type": "sectionBreak", "attrs": value}, paragraph("After")],
            }
        )


@pytest.mark.parametrize(
    "content",
    [
        [section_break(), paragraph("After")],
        [paragraph("Before"), section_break()],
        [paragraph("Before"), section_break(), section_break(), paragraph("After")],
        [paragraph("Before"), {"type": "pageBreak"}, section_break(), paragraph("After")],
        [paragraph("Before"), section_break(), {"type": "pageBreak"}, paragraph("After")],
    ],
)
def test_section_break_requires_distinct_non_adjacent_root_sections(content: list[dict[str, Any]]) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": content})


def test_section_break_limit_is_twelve_and_nested_markers_fail_closed() -> None:
    content: list[dict[str, Any]] = [paragraph("0")]
    for number in range(12):
        content.extend([section_break(), paragraph(str(number + 1))])
    assert validate_office_document({"type": "doc", "content": content})["content"] == content
    content.extend([section_break(), paragraph("13")])
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": content})
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            {"type": "doc", "content": [{"type": "blockquote", "content": [paragraph("x"), section_break()]}]}
        )


def test_section_break_preserves_review_positions_replacement_and_metadata() -> None:
    document = {"type": "doc", "content": [paragraph("A😀"), section_break(), paragraph("After")]}
    before = deepcopy(document)
    anchor = ReviewAnchor.model_validate({"from": 7, "to": 12})
    assert derive_review_quote(document, anchor) == "After"
    changed = replace_suggestion_text(document, anchor, "Replacement")
    assert changed["content"] == [paragraph("A😀"), section_break(), paragraph("Replacement")]
    assert document == before


def test_section_versions_replay_stale_write_history_and_authorization(office_api: OfficeApiHarness) -> None:
    enable_office()
    original: dict[str, Any] = {"type": "doc", "content": [paragraph("Before"), paragraph("After")]}
    payload = {**create_payload("section-create"), "document": original}
    created_response = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert created_response.status_code == 200
    created = created_response.json()
    object_id = created["document"]["object_id"]
    first_version_id = created["version"]["version_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    sectioned = deepcopy(original)
    sectioned["content"].insert(1, section_break())
    command = {
        **payload,
        "document": sectioned,
        "mutation_reference": "section-save",
        "expected_current_version_id": first_version_id,
    }
    path = f"{BASE}/{object_id}/versions"
    saved = office_api.client.post(path, headers=office_api.headers, json=command)
    assert saved.status_code == 200 and saved.json()["content"] == sectioned
    replay = office_api.client.post(path, headers=office_api.headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    historical = office_api.client.get(
        f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": first_version_id}
    )
    assert historical.status_code == 200 and historical.json()["content"] == original
    assert historical.headers["cache-control"] == "no-store"
    stale = office_api.client.post(
        path, headers=office_api.headers, json={**command, "mutation_reference": "section-stale"}
    )
    assert stale.status_code == 409
    enable_office(read=False)
    denied = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers)
    assert denied.status_code == 403
