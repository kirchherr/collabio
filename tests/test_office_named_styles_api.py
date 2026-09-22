from copy import deepcopy
from unittest.mock import Mock

import pytest

from test_office_documents_api import BASE, OfficeApiHarness, create_payload, enable_office
from test_office_documents_api import office_api as office_api
from test_office_named_styles import styled_document


def test_api_styles_versions_replay_history_and_conflicts(office_api: OfficeApiHarness) -> None:
    enable_office()
    payload = {**create_payload("named-style"), "document": styled_document()}
    response = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert response.status_code == 200
    first = response.json()
    object_id = first["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    changed = deepcopy(payload["document"])
    changed["attrs"]["styles"][0]["character"]["fontSize"] = 24
    command = {
        **payload,
        "document": changed,
        "mutation_reference": "style-update",
        "expected_current_version_id": first["version"]["version_id"],
    }
    saved = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=command)
    assert saved.status_code == 200 and saved.json()["content"] == changed
    replay = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"]
    old = office_api.client.get(
        f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": first["version"]["version_id"]}
    )
    assert old.json()["content"] == payload["document"] and old.headers["cache-control"] == "no-store"
    stale = office_api.client.post(
        f"{BASE}/{object_id}/versions",
        headers=office_api.headers,
        json={**command, "mutation_reference": "style-stale"},
    )
    assert stale.status_code == 409
    enable_office(read=False)
    assert office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers).status_code == 403


@pytest.mark.parametrize("tamper", ["unknown", "invalid", "duplicate"])
def test_api_invalid_styles_do_not_commit_or_echo(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    enable_office()
    document = styled_document()
    if tamper == "unknown":
        document["content"][0]["attrs"]["styleId"] = "SECRET"
    elif tamper == "invalid":
        document["attrs"]["styles"][0]["character"]["textColor"] = "SECRET"
    else:
        document["attrs"]["styles"].append(deepcopy(document["attrs"]["styles"][0]))
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    response = office_api.client.post(
        BASE, headers=office_api.headers, json={**create_payload("invalid-style"), "document": document}
    )
    assert response.status_code == 422 and "SECRET" not in response.text
    assert response.headers["cache-control"] == "no-store"
    commit.assert_not_called()
