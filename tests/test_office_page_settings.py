from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text
from test_office_documents_api import BASE, OfficeApiHarness, create_payload, enable_office
from test_office_documents_api import office_api as office_api
from test_office_named_styles import styled_document


def page_settings() -> dict[str, Any]:
    return {
        "paper": "letter",
        "orientation": "landscape",
        "margins": {"top": 12, "right": 25, "bottom": 30, "left": 40},
    }


def page_document() -> dict[str, Any]:
    document = styled_document()
    document["attrs"]["page"] = page_settings()
    document["content"].append({"type": "pageBreak"})
    return document


def test_page_settings_preserve_legacy_bytes_positions_styles_and_replacement() -> None:
    document = page_document()
    before = canonical_json(document)
    assert validate_office_document(document) is document
    anchor = ReviewAnchor.model_validate({"from": 1, "to": 5})
    assert derive_review_quote(document, anchor) == "Café"
    changed = replace_suggestion_text(document, anchor, "New")
    assert changed["attrs"] == document["attrs"]
    assert changed["content"][-1] == {"type": "pageBreak"}
    validate_office_document(changed)
    assert canonical_json(document) == before
    legacy = {"type": "doc", "content": [{"type": "paragraph"}]}
    assert canonical_json(validate_office_document(legacy)) == '{"content":[{"type":"paragraph"}],"type":"doc"}'


@pytest.mark.parametrize("paper", ["a4", "letter"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
@pytest.mark.parametrize("margin", [5, 18, 50])
def test_page_settings_accept_bounded_geometry(paper: str, orientation: str, margin: int) -> None:
    document = page_document()
    document["attrs"]["page"] = {
        "paper": paper,
        "orientation": orientation,
        "margins": dict.fromkeys(("top", "right", "bottom", "left"), margin),
    }
    assert validate_office_document(document) == document


@pytest.mark.parametrize("value", [None, {}, [], True, "SECRET", {"paper": "a4"}])
def test_page_settings_reject_incomplete_shapes(value: Any) -> None:
    document = page_document()
    document["attrs"]["page"] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize("value", [True, False, None, "18", 18.5, 18.0, 4, 51, [], {}, "url(SECRET)"])
@pytest.mark.parametrize("side", ["top", "right", "bottom", "left"])
def test_page_settings_reject_invalid_margin_types_and_bounds(side: str, value: Any) -> None:
    document = page_document()
    document["attrs"]["page"]["margins"][side] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize("tamper", ["paper", "orientation", "extra", "margin-extra", "margin-missing", "nested"])
def test_page_settings_fail_before_commit_without_content_echo(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    enable_office()
    document = page_document()
    page = document["attrs"]["page"]
    if tamper in {"paper", "orientation"}:
        page[tamper] = "SECRET"
    elif tamper == "extra":
        page["css"] = "SECRET"
    elif tamper == "margin-extra":
        page["margins"]["css"] = "SECRET"
    elif tamper == "margin-missing":
        del page["margins"]["top"]
    else:
        document["content"][0]["attrs"]["page"] = page
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    response = office_api.client.post(
        BASE, headers=office_api.headers, json={**create_payload("bad-page"), "document": document}
    )
    assert response.status_code == 422 and "SECRET" not in response.text
    assert response.headers["cache-control"] == "no-store"
    commit.assert_not_called()


def test_page_settings_api_versions_replay_reset_history_conflict_and_access(office_api: OfficeApiHarness) -> None:
    enable_office()
    payload = {**create_payload("page-create"), "document": page_document()}
    first_response = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert first_response.status_code == 200
    first = first_response.json()
    object_id = first["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    reset = deepcopy(payload["document"])
    del reset["attrs"]["page"]
    command = {
        **payload,
        "document": reset,
        "mutation_reference": "page-reset",
        "expected_current_version_id": first["version"]["version_id"],
    }
    path = f"{BASE}/{object_id}/versions"
    saved = office_api.client.post(path, headers=office_api.headers, json=command)
    assert saved.status_code == 200 and saved.json()["content"] == reset
    replay = office_api.client.post(path, headers=office_api.headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"]
    old = office_api.client.get(
        f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": first["version"]["version_id"]}
    )
    assert old.status_code == 200 and old.json()["content"] == payload["document"]
    assert old.headers["cache-control"] == "no-store"
    assert (
        office_api.client.post(
            path, headers=office_api.headers, json={**command, "mutation_reference": "stale-page"}
        ).status_code
        == 409
    )
    enable_office(read=False)
    assert office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers).status_code == 403
