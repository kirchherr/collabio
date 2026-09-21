from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_api import build_office_suggestion_service
from suite.platform.office_suggestions import OfficeSuggestionService
from suite.storage.source_object_storage import SourceObjectStorageError
from test_office_documents_api import OfficeApiHarness, create_document, enable_office
from test_office_documents_api import office_api as office_api

PRIVATE = "PRIVATE SUGGESTION <img src=x onerror=alert(1)>"


@dataclass
class SuggestionApiHarness:
    office: OfficeApiHarness
    service: OfficeSuggestionService
    object_id: str
    version_id: str

    @property
    def base(self) -> str:
        return f"/v1/office/documents/{self.object_id}/suggestions"

    def payload(self, reference: str = "create-suggestion") -> dict[str, Any]:
        return {"anchor_version_id": self.version_id, "expected_current_version_id": self.version_id,
                "anchor": {"from": 1, "to": 7}, "replacement_text": PRIVATE,
                "mutation_reference": reference, "human_confirmation": True}

    def create(self) -> dict[str, Any]:
        response = self.office.client.post(self.base, headers=self.office.headers, json=self.payload())
        assert response.status_code == 200, response.text
        return dict(response.json())


@pytest.fixture
def suggestion_api(office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch) -> SuggestionApiHarness:
    created = create_document(office_api)
    service = build_office_suggestion_service(document_service=office_api.service, audit=InMemoryAuditLogger())
    monkeypatch.setattr(app.state, "office_suggestion_service", service)
    return SuggestionApiHarness(office_api, service, created["document"]["object_id"], created["version"]["version_id"])


def test_suggestion_api_complete_accept_and_exact_retry_are_literal_noncacheable(
    suggestion_api: SuggestionApiHarness, caplog: pytest.LogCaptureFixture,
) -> None:
    harness = suggestion_api
    created = harness.create()
    assert created["quote"] == "OFFICE" and created["replacement_text"] == PRIVATE
    assert created["document_result"] is None
    url = f"{harness.base}/{created['suggestion']['suggestion_id']}"
    for path in (harness.base, url):
        response = harness.office.client.get(path, headers=harness.office.headers)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    decision = {"operation": "accept", "expected_revision": 1, "expected_current_version_id": harness.version_id,
                "mutation_reference": "accept", "human_confirmation": True}
    first = harness.office.client.post(f"{url}/decisions", headers=harness.office.headers, json=decision)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["suggestion"]["status"] == "accepted"
    assert result["document_result"]["version"]["previous_version_id"] == harness.version_id
    assert first.headers["Cache-Control"] == "no-store"
    replay = harness.office.client.post(f"{url}/decisions", headers=harness.office.headers, json=decision).json()
    assert replay["replayed"] and replay["suggestion"]["result_version_id"] == result["suggestion"]["result_version_id"]
    assert PRIVATE not in caplog.text
    assert PRIVATE not in str(harness.service.audit.events)
    assert result["rag_indexing_allowed"] is result["search_indexing_allowed"] is False


@pytest.mark.parametrize("payload_change", (
    {"human_confirmation": False}, {"replacement_text": "x" * 4001}, {"replacement_text": "a\x00b"},
    {"anchor": {"from": 1, "to": 7, "quote": "forged"}}, {"classification": "public"},
))
def test_suggestion_invalid_requests_never_echo_bodies(suggestion_api: SuggestionApiHarness, payload_change: dict[str, Any]) -> None:
    response = suggestion_api.office.client.post(suggestion_api.base, headers=suggestion_api.office.headers,
                                                  json={**suggestion_api.payload(), **payload_change})
    assert response.status_code == 422 and response.json() == {"detail": "Invalid document request"}
    assert PRIVATE not in response.text and response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("read,write", ((False, True), (True, False)))
def test_suggestion_gates_close_before_mutation(suggestion_api: SuggestionApiHarness, monkeypatch: pytest.MonkeyPatch, read: bool, write: bool) -> None:
    enable_office(read=read, write=write)
    commit = Mock(side_effect=AssertionError("must not reach persistence"))
    monkeypatch.setattr(suggestion_api.service.repository, "commit", commit)
    response = suggestion_api.office.client.post(suggestion_api.base, headers=suggestion_api.office.headers,
                                                  json=suggestion_api.payload())
    assert response.status_code == 403 and response.headers["Cache-Control"] == "no-store"
    commit.assert_not_called()


@pytest.mark.parametrize("error", (SourceObjectStorageError("PRIVATE backend URL"), psycopg.OperationalError("PRIVATE DSN")))
def test_suggestion_unavailable_storage_is_safe_503(suggestion_api: SuggestionApiHarness, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(suggestion_api.service.repository, "commit", Mock(side_effect=error))
    response = suggestion_api.office.client.post(suggestion_api.base, headers=suggestion_api.office.headers,
                                                  json=suggestion_api.payload())
    assert response.status_code == 503 and response.json() == {"detail": "Office storage unavailable"}
    assert response.headers["Cache-Control"] == "no-store"


def test_suggestion_reader_can_read_but_cannot_decide_and_foreign_is_generic(suggestion_api: SuggestionApiHarness) -> None:
    harness = suggestion_api
    created = harness.create()
    harness.office.repository.grants[("tenant-demo", harness.object_id, harness.office.headers["X-User-Id"])] = "read"
    url = f"{harness.base}/{created['suggestion']['suggestion_id']}"
    response = harness.office.client.get(url, headers=harness.office.headers)
    assert response.status_code == 200 and not response.json()["suggestion"]["can_accept"]
    denied = harness.office.client.post(f"{url}/decisions", headers=harness.office.headers, json={
        "operation": "reject", "expected_revision": 1, "mutation_reference": "deny", "human_confirmation": True,
    })
    assert denied.status_code == 403
    missing = harness.office.client.get(url, headers={**harness.office.headers, "X-User-Id": "unknown"})
    assert missing.status_code == 404 and missing.json() == {"detail": "Document not found"}
