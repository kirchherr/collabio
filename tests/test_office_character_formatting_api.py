from typing import Any
from unittest.mock import Mock

import pytest

from test_office_documents_api import BASE, OfficeApiHarness, create_payload, enable_office
from test_office_documents_api import office_api as office_api
from work_e2e_character import character_recovery_document


def test_api_character_versions_exact_retry_legacy_reads_and_feature_denial(office_api: OfficeApiHarness) -> None:
    enable_office()
    payload = {**create_payload("character-legacy"), "document": character_recovery_document(1)}
    created = office_api.client.post(BASE, headers=office_api.headers, json=payload)
    assert created.status_code == 200
    first = created.json()
    object_id = first["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = object_id
    command = {
        **payload,
        "document": character_recovery_document(2),
        "mutation_reference": "character-save",
        "expected_current_version_id": first["version"]["version_id"],
    }
    saved = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=command)
    assert saved.status_code == 200 and saved.json()["content"] == command["document"]
    replay = office_api.client.post(f"{BASE}/{object_id}/versions", headers=office_api.headers, json=command)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["version"] == saved.json()["version"]
    old = office_api.client.get(
        f"{BASE}/{object_id}/content", headers=office_api.headers, params={"version_id": first["version"]["version_id"]}
    )
    assert old.json()["content"] == payload["document"]
    assert old.headers["cache-control"] == "no-store"
    stale = office_api.client.post(
        f"{BASE}/{object_id}/versions", headers=office_api.headers, json={**command, "mutation_reference": "stale"}
    )
    assert stale.status_code == 409
    enable_office(read=False)
    assert office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers).status_code == 403


@pytest.mark.parametrize(
    "attrs",
    [
        {},
        {"fontSize": True},
        {"fontSize": 18.0},
        {"textColor": "SECRET"},
        {"fontSize": 12, "style": "SECRET"},
        {"textColor": None},
    ],
)
def test_api_invalid_character_attributes_never_commit_or_echo(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, attrs: dict[str, Any]
) -> None:
    enable_office()
    content = character_recovery_document(1)
    content["content"][0]["content"][0]["marks"] = [{"type": "textStyle", "attrs": attrs}]
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    response = office_api.client.post(
        BASE, headers=office_api.headers, json={**create_payload("character-invalid"), "document": content}
    )
    assert response.status_code == 422 and "SECRET" not in response.text
    assert response.headers["cache-control"] == "no-store"
    commit.assert_not_called()
