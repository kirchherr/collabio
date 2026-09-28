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


def running_document() -> dict[str, Any]:
    return {
        "type": "doc",
        "attrs": {"running": {"header": 'Café "quote" \\ 😀', "footer": "Internal", "numbering": "pageOfPages"}},
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Café 😀 text"}]}],
    }


def test_running_text_preserves_legacy_bytes_positions_and_replacement() -> None:
    document = running_document()
    before = canonical_json(document)
    assert validate_office_document(document) is document
    anchor = ReviewAnchor.model_validate({"from": 1, "to": 5})
    assert derive_review_quote(document, anchor) == "Café"
    changed = replace_suggestion_text(document, anchor, "New")
    assert changed["attrs"] == document["attrs"]
    validate_office_document(changed)
    assert canonical_json(document) == before
    del document["attrs"]
    assert canonical_json(validate_office_document(document)) == canonical_json(document)


@pytest.mark.parametrize("field", ["header", "footer"])
@pytest.mark.parametrize(
    "value", [None, True, 1, [], {}, "x" * 65, "\n", "\t", "\0", "\u0085", "\u2028", "\u2029", "\ud800"]
)
def test_running_text_rejects_invalid_literal_fields(field: str, value: Any) -> None:
    document = running_document()
    document["attrs"]["running"][field] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize("value", [None, {}, [], True, "SECRET", {"header": "SECRET"}])
def test_running_text_requires_complete_inert_shape(value: Any) -> None:
    document = running_document()
    document["attrs"]["running"] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize("tamper", ["numbering", "extra", "nested", "top", "bottom"])
def test_running_text_rejects_before_commit_without_echo(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    enable_office()
    document = running_document()
    if tamper == "numbering":
        document["attrs"]["running"]["numbering"] = "SECRET"
    elif tamper == "extra":
        document["attrs"]["running"]["css"] = "SECRET"
    elif tamper == "nested":
        document["content"][0]["attrs"] = {"running": document["attrs"]["running"]}
    else:
        document["attrs"]["page"] = {
            "paper": "a4",
            "orientation": "portrait",
            "margins": {"top": 18, "right": 18, "bottom": 18, "left": 18},
        }
        document["attrs"]["page"]["margins"][tamper] = 15
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    response = office_api.client.post(
        BASE, headers=office_api.headers, json={**create_payload("bad-running"), "document": document}
    )
    assert response.status_code == 422 and "SECRET" not in response.text
    assert response.headers["cache-control"] == "no-store"
    commit.assert_not_called()


@pytest.mark.parametrize("numbering", ["none", "page", "pageOfPages"])
def test_running_text_accepts_unicode_bounds_and_preserves_explicit_empty(numbering: str) -> None:
    document = running_document()
    document["attrs"]["running"] = {"header": "😀" * 64, "footer": "", "numbering": numbering}
    assert validate_office_document(document) is document
    document["attrs"]["running"] = {"header": "", "footer": "", "numbering": "none"}
    assert "running" in validate_office_document(document)["attrs"]


def test_running_text_versions_replay_reset_and_authorization(office_api: OfficeApiHarness) -> None:
    enable_office()
    payload = {**create_payload("running-create"), "document": running_document()}
    response = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert response.status_code == 200
    first = response.json()
    object_id = first["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    reset = deepcopy(payload["document"])
    del reset["attrs"]
    command = {
        **payload,
        "document": reset,
        "mutation_reference": "running-reset",
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
            path, headers=office_api.headers, json={**command, "mutation_reference": "stale-running"}
        ).status_code
        == 409
    )
    enable_office(read=False)
    assert office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers).status_code == 403
