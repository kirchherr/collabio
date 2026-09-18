from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import time
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET, DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER, HmacJwtVerifier,
    InMemoryPrincipalDirectory, JwtPrincipalResolver, PrincipalRecord, TenantMembership,
)
from suite.platform.modules import ModuleStatus
from suite.platform.office_api import build_office_review_service
from suite.platform.office_documents import OFFICE_DOCUMENTS_MODULE_ID
from suite.platform.office_reviews import OfficeReviewService
from suite.storage.source_object_storage import SourceObjectStorageError
from test_office_documents_api import OfficeApiHarness, create_document, enable_office, office_api  # noqa: F401

REVIEW_BODY = "PRIVATE REVIEW BODY <script>not executable</script>"


@dataclass
class ReviewApiHarness:
    office: OfficeApiHarness
    service: OfficeReviewService
    object_id: str
    version_id: str

    @property
    def base(self) -> str:
        return f"/v1/office/documents/{self.object_id}/review-threads"

    def payload(self, reference: str = "review-api-create") -> dict[str, Any]:
        return {"anchor_version_id": self.version_id, "expected_current_version_id": self.version_id,
            "anchor": {"from": 1, "to": 7}, "body": REVIEW_BODY,
            "mutation_reference": reference, "human_confirmation": True}

    def create(self) -> dict[str, Any]:
        response = self.office.client.post(self.base, headers=self.office.headers, json=self.payload())
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result


@pytest.fixture
def review_api(office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch) -> ReviewApiHarness:
    created = create_document(office_api)
    service = build_office_review_service(document_service=office_api.service, audit=InMemoryAuditLogger())
    monkeypatch.setattr(app.state, "office_review_service", service)
    return ReviewApiHarness(office_api, service, created["document"]["object_id"], created["version"]["version_id"])


def test_review_api_create_reply_resolve_reopen_are_noncacheable_and_literal(review_api: ReviewApiHarness, caplog: pytest.LogCaptureFixture) -> None:
    created = review_api.create()
    assert created["quote"] == "OFFICE" and created["thread"]["anchor"] == {"from": 1, "to": 7}
    thread_url = f"{review_api.base}/{created['thread']['thread_id']}"
    for revision, operation in enumerate(("reply", "resolve", "reopen"), start=1):
        response = review_api.office.client.post(f"{thread_url}/events", headers=review_api.office.headers, json={
            "operation": operation, "expected_revision": revision, "body": REVIEW_BODY if operation == "reply" else None,
            "mutation_reference": operation, "human_confirmation": True})
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["applied_revision"] == revision + 1
        assert response.json()["rag_indexing_allowed"] is response.json()["search_indexing_allowed"] is False
    for path in (review_api.base, thread_url):
        response = review_api.office.client.get(path, headers=review_api.office.headers)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    result = response.json()
    assert [event["operation"] for event in result["events"]] == ["create", "reply", "resolve", "reopen"]
    assert result["events"][1]["body"] == REVIEW_BODY and result["thread"]["status"] == "open"
    assert REVIEW_BODY not in caplog.text
    assert REVIEW_BODY not in json.dumps([event.model_dump(mode="json") for event in review_api.service.audit.events])


@pytest.mark.parametrize("block", ["module", "read", "write", "authentication"])
def test_review_api_gate_changes_precede_mutation_and_cached_capabilities(review_api: ReviewApiHarness, monkeypatch: pytest.MonkeyPatch, block: str) -> None:
    created = review_api.create()
    headers = review_api.office.headers
    if block == "module":
        module = app.state.module_registry.get_tenant_module("tenant-demo", OFFICE_DOCUMENTS_MODULE_ID)
        app.state.module_registry.upsert_tenant_module(module.model_copy(update={"status": ModuleStatus.DISABLED, "disabled_at_utc": datetime.now(UTC)}))
    elif block == "read":
        enable_office(read=False)
    elif block == "write":
        enable_office(write=False)
        listing = review_api.office.client.get(review_api.base, headers=headers)
        assert listing.status_code == 200 and not listing.json()["can_create"]
        assert not listing.json()["threads"][0]["can_comment"]
    else:
        headers = {}
    commit = Mock(wraps=review_api.service.repository.commit)
    monkeypatch.setattr(review_api.service.repository, "commit", commit)
    response = review_api.office.client.post(review_api.base, headers=headers, json=review_api.payload("blocked"))
    assert response.status_code == (401 if block == "authentication" else 403)
    event = review_api.office.client.post(f"{review_api.base}/{created['thread']['thread_id']}/events", headers=headers,
        json={"operation": "resolve", "expected_revision": 1, "mutation_reference": "blocked-state", "human_confirmation": True})
    assert event.status_code == response.status_code
    assert response.headers["Cache-Control"] == event.headers["Cache-Control"] == "no-store"
    commit.assert_not_called()


@pytest.mark.parametrize("update", [
    {"human_confirmation": False}, {"human_confirmation": "true"}, {"body": ""}, {"body": "x" * 4001},
    {"body": "secret\x00"}, {"anchor": {"from": True, "to": 3}}, {"quote": "forged quote"},
])
def test_review_api_invalid_requests_never_echo_bodies(review_api: ReviewApiHarness, update: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
    response = review_api.office.client.post(review_api.base, headers=review_api.office.headers, json={**review_api.payload(), **update})
    assert response.status_code == 422 and response.json() == {"detail": "Invalid document request"}
    assert REVIEW_BODY not in response.text and REVIEW_BODY not in caplog.text
    assert response.headers["Cache-Control"] == "no-store"


def test_review_api_current_acl_revocation_denies_before_source_reads(review_api: ReviewApiHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    created = review_api.create()
    url = f"{review_api.base}/{created['thread']['thread_id']}"
    read = Mock(wraps=review_api.service.source_repository.get)
    monkeypatch.setattr(review_api.service.source_repository, "get", read)
    del review_api.office.repository.grants[("tenant-demo", review_api.object_id, review_api.office.headers["X-User-Id"])]
    for path in (review_api.base, url):
        response = review_api.office.client.get(path, headers=review_api.office.headers)
        assert response.status_code == 404 and response.json() == {"detail": "Document not found"}
    replay = review_api.office.client.post(review_api.base, headers=review_api.office.headers, json=review_api.payload())
    assert replay.status_code == 404
    read.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "write", "database"])
def test_review_api_storage_failures_are_safe503_without_body_logs(review_api: ReviewApiHarness, monkeypatch: pytest.MonkeyPatch, operation: str, caplog: pytest.LogCaptureFixture) -> None:
    created = review_api.create()
    if operation == "read":
        monkeypatch.setattr(review_api.service.source_repository, "get", Mock(side_effect=SourceObjectStorageError(REVIEW_BODY)))
        response = review_api.office.client.get(f"{review_api.base}/{created['thread']['thread_id']}", headers=review_api.office.headers)
    elif operation == "write":
        monkeypatch.setattr(review_api.service.source_repository, "add", Mock(side_effect=SourceObjectStorageError(REVIEW_BODY)))
        response = review_api.office.client.post(review_api.base, headers=review_api.office.headers, json=review_api.payload("failed"))
    else:
        monkeypatch.setattr(review_api.service.repository, "list_threads", Mock(side_effect=psycopg.OperationalError(REVIEW_BODY)))
        response = review_api.office.client.get(review_api.base, headers=review_api.office.headers)
    assert response.status_code == 503 and response.json() == {"detail": "Office storage unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert REVIEW_BODY not in response.text and REVIEW_BODY not in caplog.text


def test_review_api_jwt_does_not_accept_forged_parent_grants(review_api: ReviewApiHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    created = review_api.create()
    principal = PrincipalRecord(issuer=DEFAULT_JWT_ISSUER, subject="review-subject", user_id="review-reader",
        memberships=[TenantMembership(tenant_id="tenant-demo", role_ids={"office-reader"})])
    resolver = JwtPrincipalResolver(verifier=HmacJwtVerifier(issuer=DEFAULT_JWT_ISSUER, audience=DEFAULT_JWT_AUDIENCE, secret=DEFAULT_DEV_JWT_SECRET),
        directory=InMemoryPrincipalDirectory(principals=[principal], object_acls=[]))
    monkeypatch.setattr(app.state, "principal_resolver", resolver)
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    payload = {"iss": DEFAULT_JWT_ISSUER, "aud": DEFAULT_JWT_AUDIENCE, "sub": principal.subject, "tenant_id": "tenant-demo",
        "iat": int(time()) - 1, "exp": int(time()) + 120, "roles": ["tenant-admin"], "readable_object_ids": [review_api.object_id]}
    segments = [base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=") for part in ({"alg": "HS256", "typ": "JWT"}, payload)]
    signing_input = ".".join(segments)
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode(), signing_input.encode(), sha256).digest()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    headers = {**review_api.office.headers, "Authorization": f"Bearer {token}", "X-Role-Ids": "tenant-admin"}
    review_api.office.repository.grants[("tenant-demo", review_api.object_id, principal.user_id)] = "admin"
    read = Mock(wraps=review_api.service.source_repository.get)
    monkeypatch.setattr(review_api.service.source_repository, "get", read)
    response = review_api.office.client.get(f"{review_api.base}/{created['thread']['thread_id']}", headers=headers)
    assert response.status_code == 404 and response.json() == {"detail": "Document not found"}
    assert review_api.office.client.post(review_api.base, headers=headers, json=review_api.payload()).status_code == 404
    read.assert_not_called()


def test_review_api_memory_runtime_factory_cannot_persist_review(review_api: ReviewApiHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    review_api.office.service.writes_available = False
    service = build_office_review_service(document_service=review_api.office.service, audit=InMemoryAuditLogger())
    monkeypatch.setattr(app.state, "office_review_service", service)
    commit = Mock(wraps=service.repository.commit)
    monkeypatch.setattr(service.repository, "commit", commit)
    listing = review_api.office.client.get(review_api.base, headers=review_api.office.headers)
    assert listing.status_code == 200 and not listing.json()["can_create"]
    response = review_api.office.client.post(review_api.base, headers=review_api.office.headers, json=review_api.payload())
    assert response.status_code == 403
    commit.assert_not_called()
