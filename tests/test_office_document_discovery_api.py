from __future__ import annotations

from unittest.mock import Mock

import psycopg
import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.ai_control_plane.models import UserContext
from test_office_document_discovery import seed_discovery_record
from test_office_documents_api import (
    BASE,
    OfficeApiHarness,
    enable_office,
)
from test_office_documents_api import (
    office_api as office_api,
)


def seed_api_list(harness: OfficeApiHarness, count: int = 3) -> None:
    enable_office()
    user = UserContext(tenant_id=harness.headers["X-Tenant-Id"], user_id=harness.headers["X-User-Id"])
    for index in range(1, count + 1):
        seed_discovery_record(harness.repository, user, index, title="Private Café %_\\")
    harness.headers["X-Readable-Object-Ids"] = ",".join(sorted(user.readable_object_ids))


def test_office_discovery_api_is_additive_and_current_capabilities_ignore_search(office_api: OfficeApiHarness) -> None:
    seed_api_list(office_api)
    legacy = office_api.client.get(BASE, headers=office_api.headers)
    assert legacy.status_code == 200 and legacy.json()["page_size"] == 200
    first = office_api.client.get(BASE, headers=office_api.headers, params={"query": "CAFÉ %_\\", "page_size": 2})
    assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
    body = first.json()
    assert len(body["documents"]) == 2 and body["has_more"] and body["next_cursor"]
    assert body["can_create"] and all(not entry["can_write"] for entry in body["documents"])
    enable_office(write=False)
    second = office_api.client.get(
        BASE,
        headers=office_api.headers,
        params={
            "query": "CAFÉ %_\\",
            "page_size": 2,
            "cursor": body["next_cursor"],
        },
    )
    assert second.status_code == 200 and len(second.json()["documents"]) == 1
    assert not second.json()["has_more"] and second.json()["next_cursor"] is None
    assert not second.json()["can_create"]
    empty = office_api.client.get(BASE, headers=office_api.headers, params={"query": "Missing private title"})
    assert empty.status_code == 200 and empty.json()["documents"] == []
    audit = canonical_json([event.model_dump() for event in office_api.service.audit.events])
    assert "CAFÉ" not in audit and "Missing private title" not in audit and body["next_cursor"] not in audit


@pytest.mark.parametrize(
    "params,status",
    [
        ({"query": "x" * 201}, 422),
        ({"query": "\x00private"}, 400),
        ({"query": "private\u0085"}, 400),
        ({"query": "private\u009f"}, 400),
        ({"page_size": "0"}, 422),
        ({"page_size": "201"}, 422),
        ({"page_size": "not-integer"}, 422),
        ({"cursor": "private-invalid-cursor"}, 400),
        ({"cursor": "x" * 1025}, 422),
    ],
)
def test_office_discovery_invalid_arguments_are_generic_and_uncacheable(
    office_api: OfficeApiHarness,
    params: dict[str, str],
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_office()
    listing = Mock(side_effect=AssertionError("invalid request must fail before repository"))
    monkeypatch.setattr(office_api.repository, "list_documents", listing)
    response = office_api.client.get(BASE, headers=office_api.headers, params=params)
    assert response.status_code == status
    assert response.json() == {
        "detail": "Invalid document list request" if status == 400 else "Invalid document request"
    }
    assert response.headers["Cache-Control"] == "no-store" and "private" not in response.text
    listing.assert_not_called()


def test_office_discovery_cursor_does_not_bypass_fresh_module_or_principal_checks(
    office_api: OfficeApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_api_list(office_api)
    cursor = office_api.client.get(BASE, headers=office_api.headers, params={"page_size": 1}).json()["next_cursor"]
    listing = Mock(side_effect=AssertionError("denied request must fail before repository"))
    monkeypatch.setattr(office_api.repository, "list_documents", listing)
    changed = {**office_api.headers, "X-User-Id": "different-actor"}
    denied = office_api.client.get(BASE, headers=changed, params={"page_size": 1, "cursor": cursor})
    assert denied.status_code == 400 and denied.json() == {"detail": "Invalid document list request"}
    enable_office(read=False)
    disabled = office_api.client.get(BASE, headers=office_api.headers, params={"page_size": 1, "cursor": cursor})
    assert disabled.status_code == 403 and disabled.headers["Cache-Control"] == "no-store"
    missing = office_api.client.get(BASE, params={"cursor": cursor})
    assert missing.status_code == 401 and missing.headers["Cache-Control"] == "no-store"
    listing.assert_not_called()


def test_office_discovery_database_failure_is_safe_with_search_parameters(
    office_api: OfficeApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_office()
    monkeypatch.setattr(
        office_api.repository, "list_documents", Mock(side_effect=psycopg.OperationalError("private title"))
    )
    response = office_api.client.get(
        BASE, headers=office_api.headers, params={"query": "private title", "page_size": 10}
    )
    assert response.status_code == 503 and response.json() == {"detail": "Office storage unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
