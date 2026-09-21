from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest

from test_office_documents_api import BASE, OfficeApiHarness, create_payload, enable_office
from test_office_documents_api import office_api as office_api
from test_office_paragraph_formatting import FORMAT, formatted_document


def test_api_formatting_is_saved_as_exact_versions_and_defaults_are_not_injected(office_api: OfficeApiHarness) -> None:
    enable_office()
    legacy = create_payload("formatting-legacy")
    created = office_api.client.post(BASE, headers=office_api.headers, json=legacy)
    assert created.status_code == 200
    first = created.json()
    object_id = first["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    payload = {**legacy, "document": formatted_document(), "mutation_reference": "formatting-save", "expected_current_version_id": first["version"]["version_id"]}
    saved = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=payload)
    assert saved.status_code == 200
    result = saved.json()
    assert result["content"] == formatted_document()
    assert result["version"]["previous_version_id"] == first["version"]["version_id"]
    assert result["version"]["content_hash"] != first["version"]["content_hash"]
    assert result["schema_version"] == first["schema_version"] == "collabio_document.v1"
    for version, expected in ((first["version"], legacy["document"]), (result["version"], formatted_document())):
        read = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": version["version_id"]})
        assert read.status_code == 200
        assert read.headers["cache-control"] == "no-store"
        assert read.json()["content"] == expected
        assert read.json()["version"]["content_hash"] == version["content_hash"]
    replay = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=payload)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["version"]["version_id"] == result["version"]["version_id"]
    stale = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json={**payload, "mutation_reference": "formatting-stale"})
    assert stale.status_code == 409
    assert len(office_api.repository.saved_versions) == 2


@pytest.mark.parametrize("attrs", [{"spacingBefore": True}, {"spacingAfter": 6.0}, {"lineSpacing": 1.5}, {"textAlign": "center;SECRET"}, {"lineSpacing": None}])
def test_api_invalid_formatting_fails_before_commit_with_no_input_echo(office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, attrs: dict[str, Any]) -> None:
    enable_office()
    payload = create_payload("formatting-invalid")
    payload["document"] = formatted_document()
    payload["document"]["content"][0]["attrs"] = attrs
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    response = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert "SECRET" not in response.text and "PRIVATE" not in response.text
    commit.assert_not_called()


def test_api_format_reset_is_explicit_omission_and_read_feature_remains_required(office_api: OfficeApiHarness) -> None:
    enable_office()
    payload = {**create_payload("formatted-create"), "document": formatted_document()}
    created = office_api.client.post(BASE, headers=office_api.headers, json=payload).json()
    object_id = created["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    reset = deepcopy(formatted_document())
    del reset["content"][0]["attrs"]
    reset["content"][1]["attrs"] = {"level": 2}
    result = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json={**payload, "document": reset, "mutation_reference": "reset", "expected_current_version_id": created["version"]["version_id"]})
    assert result.status_code == 200 and result.json()["content"] == reset
    old = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": created["version"]["version_id"]})
    assert old.json()["content"]["content"][0]["attrs"] == FORMAT
    enable_office(read=False)
    denied = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers)
    assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
