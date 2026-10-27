from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.ai_control_plane.models import UserContext
from test_office_documents_api import BASE, OfficeApiHarness, enable_office
from test_office_documents_api import office_api as office_api
from test_office_version_pagination import seed_version_history


def api_history_fixture(harness: OfficeApiHarness, count: int = 205) -> tuple[str, list[str]]:
    enable_office(write=False)
    user = UserContext(tenant_id=harness.headers["X-Tenant-Id"], user_id=harness.headers["X-User-Id"])
    object_id, ids = seed_version_history(harness.repository, user, count)
    harness.headers["X-Role-Ids"] = "office-reader"
    harness.headers["X-Readable-Object-Ids"] = object_id
    return object_id, ids


def test_history_api_preserves_legacy_fields_and_reads_all_pages_without_write(
    office_api: OfficeApiHarness, monkeypatch: Any
) -> None:
    object_id, ids = api_history_fixture(office_api)
    source_read = Mock(side_effect=AssertionError("history is metadata only"))
    monkeypatch.setattr(office_api.service.source_repository, "get", source_read)
    path = f"{BASE}/{object_id}/versions"
    response = office_api.client.get(path, headers=office_api.headers)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    first = response.json()
    assert first["tenant_id"] == "tenant-demo" and first["object_id"] == object_id and first["audit_event_id"]
    assert first["history_head_version_id"] == first["current_version_id"] == ids[-1]
    assert first["page_size"] == 200 and len(first["versions"]) == 200 and first["has_more"]
    result = office_api.client.get(path, headers=office_api.headers, params={"cursor": first["next_cursor"]})
    assert result.status_code == 200 and result.headers["Cache-Control"] == "no-store"
    last = result.json()
    assert [version["version_id"] for version in first["versions"] + last["versions"]] == list(reversed(ids))
    assert not last["has_more"] and last["next_cursor"] is None
    assert '"content":' not in response.text and "total" not in first
    audit = canonical_json([event.model_dump() for event in office_api.service.audit.events])
    assert "Private history title" not in audit and first["next_cursor"] not in audit
    source_read.assert_not_called()


@pytest.mark.parametrize(
    "params,status",
    [
        ({"page_size": "0"}, 422),
        ({"page_size": "201"}, 422),
        ({"page_size": "true"}, 422),
        ({"page_size": "1.5"}, 422),
        ({"cursor": "private-invalid"}, 400),
        ({"cursor": "x" * 1025}, 422),
    ],
)
def test_history_api_invalid_cursor_and_limits_never_echo_request(
    office_api: OfficeApiHarness,
    monkeypatch: Any,
    params: dict[str, str],
    status: int,
) -> None:
    enable_office()
    read = Mock(side_effect=AssertionError("invalid input before repository"))
    monkeypatch.setattr(office_api.repository, "history_page", read)
    response = office_api.client.get(f"{BASE}/unreadable/versions", headers=office_api.headers, params=params)
    assert response.status_code == status and response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "detail": "Invalid version history request" if status == 400 else "Invalid document request"
    }
    read.assert_not_called()


def test_history_api_cursor_cannot_bypass_authentication_feature_or_current_parent_acl(
    office_api: OfficeApiHarness,
) -> None:
    object_id, _ = api_history_fixture(office_api, 3)
    path = f"{BASE}/{object_id}/versions"
    cursor = office_api.client.get(path, headers=office_api.headers, params={"page_size": 1}).json()["next_cursor"]
    params = {"page_size": 1, "cursor": cursor}
    assert office_api.client.get(path, params=params).status_code == 401
    changed = office_api.client.get(path, headers={**office_api.headers, "X-Role-Ids": "office-editor"}, params=params)
    assert changed.status_code == 400 and changed.json() == {"detail": "Invalid version history request"}
    assert changed.headers["Cache-Control"] == "no-store"
    enable_office(read=False, write=False)
    disabled = office_api.client.get(path, headers=office_api.headers, params=params)
    assert disabled.status_code == 403 and disabled.headers["Cache-Control"] == "no-store"
    enable_office(write=False)
    del office_api.repository.grants[("tenant-demo", object_id, office_api.headers["X-User-Id"])]
    denied = office_api.client.get(path, headers=office_api.headers, params=params)
    assert denied.status_code == 404 and denied.json() == {"detail": "Document not found"}
    assert denied.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("case", ["missing", "foreign", "forged"])
def test_history_api_missing_and_denied_are_indistinguishable(office_api: OfficeApiHarness, case: str) -> None:
    object_id, _ = api_history_fixture(office_api, 2)
    headers = dict(office_api.headers)
    if case == "missing":
        object_id = "office-doc-" + "f" * 32
    elif case == "foreign":
        document = office_api.repository.documents.pop(("tenant-demo", object_id))
        office_api.repository.documents[("other-tenant", object_id)] = document.model_copy(
            update={"tenant_id": "other-tenant"}
        )
    else:
        headers["X-User-Id"] = "forged-reader"
    response = office_api.client.get(f"{BASE}/{object_id}/versions", headers=headers)
    assert response.status_code == 404 and response.json() == {"detail": "Document not found"}
    assert response.headers["Cache-Control"] == "no-store"


def test_history_api_integrity_and_database_failures_are_safe(office_api: OfficeApiHarness, monkeypatch: Any) -> None:
    object_id, ids = api_history_fixture(office_api, 2)
    del office_api.repository.saved_versions[("tenant-demo", object_id, ids[0])]
    path = f"{BASE}/{object_id}/versions"
    broken = office_api.client.get(path, headers=office_api.headers)
    assert broken.status_code == 400 and broken.json() == {"detail": "Document validation failed"}
    assert broken.headers["Cache-Control"] == "no-store"
    monkeypatch.setattr(
        office_api.repository, "history_page", Mock(side_effect=psycopg.OperationalError("private history secret"))
    )
    failed = office_api.client.get(path, headers=office_api.headers)
    assert failed.status_code == 503 and failed.json() == {"detail": "Office storage unavailable"}
    assert failed.headers["Cache-Control"] == "no-store" and "private" not in failed.text
