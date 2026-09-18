from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import time
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    HmacJwtVerifier,
    InMemoryPrincipalDirectory,
    JwtPrincipalResolver,
    ObjectAclRecord,
    PrincipalRecord,
    TenantMembership,
)
from suite.platform.modules import ModuleStatus, TenantModuleState, default_module_registry
from suite.platform.office_api import MAX_OFFICE_REQUEST_BYTES, OFFICE_CSP, build_office_document_service
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OFFICE_DOCUMENTS_MODULE_ID,
    OFFICE_DOCUMENTS_READ_FEATURE_ID,
    OFFICE_DOCUMENTS_WRITE_FEATURE_ID,
    OfficeDocumentService,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import InMemorySourceObjectRepository

BASE = "/v1/office/documents"
SECRET = "OFFICE PRIVATE BODY must never appear in error or audit logs"


@dataclass
class OfficeApiHarness:
    client: TestClient
    service: OfficeDocumentService
    repository: InMemoryOfficeDocumentRepository
    headers: dict[str, str]


@pytest.fixture
def office_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[OfficeApiHarness]:
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    sources = InMemorySourceObjectRepository()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    service = OfficeDocumentService(
        repository=repository, source_repository=sources, audit=InMemoryAuditLogger()
    )
    monkeypatch.setattr(app.state, "office_document_service", service)
    monkeypatch.setattr(app.state, "module_registry", default_module_registry())
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "office-api-editor",
        "X-Role-Ids": "office-editor",
        "X-Readable-Object-Ids": "",
    }
    with TestClient(app) as client:
        yield OfficeApiHarness(client, service, repository, headers)


def enable_office(*, read: bool = True, write: bool = True) -> None:
    registry = app.state.module_registry
    now = datetime.now(UTC)
    registry.upsert_tenant_module(
        TenantModuleState(
            tenant_id="tenant-demo",
            module_id=OFFICE_DOCUMENTS_MODULE_ID,
            status=ModuleStatus.ENABLED,
            enabled_features={
                OFFICE_DOCUMENTS_READ_FEATURE_ID: read,
                OFFICE_DOCUMENTS_WRITE_FEATURE_ID: write,
            },
            policy_snapshot_hash="sha256:office-api-synthetic-policy",
            provisioned_at_utc=now,
            enabled_at_utc=now,
            changed_by="office-api-test",
            audit_chain_ref="audit:office-api-module",
            migration_evidence=registry.migration_evidence_for_module(
                module_id=OFFICE_DOCUMENTS_MODULE_ID,
                migration_manifest_entries=app.state.migration_manifest,
            ),
        )
    )


def create_payload(reference: str = "office-api-create") -> dict[str, Any]:
    return {
        "title": "Synthetic private title",
        "document": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": SECRET}]}],
        },
        "mutation_reference": reference,
        "human_confirmation": True,
    }


def create_document(office_api: OfficeApiHarness) -> dict[str, Any]:
    enable_office()
    response = office_api.client.post(BASE, headers=office_api.headers, json=create_payload())
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    # Dev headers model the next request's fresh resolver snapshot. They are
    # insufficient without the repository's independently checked grant.
    office_api.headers["X-Readable-Object-Ids"] = result["document"]["object_id"]
    return result


def save_payload(created: dict[str, Any], reference: str = "office-api-save") -> dict[str, Any]:
    return {
        **create_payload(reference),
        "title": "Revised private title",
        "expected_current_version_id": created["version"]["version_id"],
    }


def test_office_module_defaults_closed_before_repository_access(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = Mock(wraps=office_api.repository.list_documents)
    write = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "list_documents", read)
    monkeypatch.setattr(office_api.repository, "commit", write)
    for method in ("GET", "POST"):
        response = office_api.client.request(
            method, BASE, headers=office_api.headers, **({"json": create_payload()} if method == "POST" else {})
        )
        assert response.status_code in {403, 404}
        assert response.headers["Cache-Control"] == "no-store"
    read.assert_not_called()
    write.assert_not_called()


def test_runtime_memory_factory_does_not_advertise_or_perform_ephemeral_saves(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_office()
    service = build_office_document_service(
        source_repository=InMemorySourceObjectRepository(), audit=InMemoryAuditLogger()
    )
    monkeypatch.setattr(app.state, "office_document_service", service)
    commit = Mock(wraps=service.repository.commit)
    monkeypatch.setattr(service.repository, "commit", commit)
    listing = office_api.client.get(BASE, headers=office_api.headers)
    assert listing.status_code == 200
    assert listing.json()["can_create"] is False
    response = office_api.client.post(BASE, headers=office_api.headers, json=create_payload())
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    commit.assert_not_called()


def test_office_create_version_read_history_and_exact_retry_are_bound_and_noncacheable(
    office_api: OfficeApiHarness, caplog: pytest.LogCaptureFixture
) -> None:
    created = create_document(office_api)
    object_id = created["document"]["object_id"]
    old_version = created["version"]["version_id"]
    saved = office_api.client.post(
        f"{BASE}/{object_id}/versions", headers=office_api.headers, json=save_payload(created)
    )
    assert saved.status_code == 200
    assert saved.json()["version"]["previous_version_id"] == old_version
    assert saved.json()["version"]["version_id"] != old_version
    paths = (BASE, f"{BASE}/{object_id}/content", f"{BASE}/{object_id}/versions")
    for path in paths:
        response = office_api.client.get(path, headers=office_api.headers)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
    current = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers).json()
    assert current["document"]["current_version_id"] == saved.json()["version"]["version_id"]
    assert current["content"] == create_payload()["document"]
    assert current["can_write"] is True
    assert current["rag_indexing_allowed"] is current["search_indexing_allowed"] is False
    previous = office_api.client.get(
        f"{BASE}/{object_id}/content", params={"version_id": old_version}, headers=office_api.headers
    )
    assert previous.status_code == 200
    assert previous.json()["is_current_version"] is False
    assert previous.json()["version"]["title"] == "Synthetic private title"
    replay = office_api.client.post(BASE, headers=office_api.headers, json=create_payload())
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["version"]["version_id"] == old_version
    assert replay.json()["is_current_version"] is False
    assert len(office_api.repository.saved_versions) == 2
    assert SECRET not in json.dumps([event.model_dump(mode="json") for event in office_api.service.audit.events])
    assert SECRET not in caplog.text


@pytest.mark.parametrize("block", ["module", "read-feature", "write-feature", "authentication"])
def test_office_each_current_module_feature_and_authentication_gate_precedes_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, block: str
) -> None:
    created = create_document(office_api)
    object_id = created["document"]["object_id"]
    headers = office_api.headers
    if block == "module":
        module = app.state.module_registry.get_tenant_module("tenant-demo", OFFICE_DOCUMENTS_MODULE_ID)
        app.state.module_registry.upsert_tenant_module(
            module.model_copy(update={"status": ModuleStatus.DISABLED, "disabled_at_utc": datetime.now(UTC)})
        )
    elif block == "read-feature":
        enable_office(read=False)
    elif block == "write-feature":
        enable_office(write=False)
        read = office_api.client.get(f"{BASE}/{object_id}/content", headers=headers)
        assert read.status_code == 200
        assert read.json()["can_write"] is False
        listing = office_api.client.get(BASE, headers=headers).json()
        assert listing["can_create"] is False
    else:
        headers = {}
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    for path, payload in ((BASE, create_payload("another")), (f"{BASE}/{object_id}/versions", save_payload(created))):
        response = office_api.client.post(path, headers=headers, json=payload)
        assert response.status_code == (401 if block == "authentication" else 403)
        assert response.headers["Cache-Control"] == "no-store"
    commit.assert_not_called()
    assert len(office_api.repository.saved_versions) == 1


def test_office_reader_cannot_create_or_write_and_revocation_is_fresh(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_document(office_api)
    object_id = created["document"]["object_id"]
    reader_id = "office-api-reader"
    reader_headers = {**office_api.headers, "X-User-Id": reader_id, "X-Role-Ids": "office-reader"}
    office_api.repository.grants[("tenant-demo", object_id, reader_id)] = "read"
    content = office_api.client.get(f"{BASE}/{object_id}/content", headers=reader_headers)
    assert content.status_code == 200 and content.json()["can_write"] is False
    assert office_api.client.post(BASE, headers=reader_headers, json=create_payload("reader-create")).status_code == 403
    for roles in ("office-reader", "tenant-admin"):
        rejected = office_api.client.post(
            f"{BASE}/{object_id}/versions",
            headers={**reader_headers, "X-Role-Ids": roles},
            json=save_payload(created),
        )
        assert rejected.status_code == 403
    metadata_read = Mock(wraps=office_api.service.source_repository.get_metadata)
    monkeypatch.setattr(office_api.service.source_repository, "get_metadata", metadata_read)
    del office_api.repository.grants[("tenant-demo", object_id, reader_id)]
    for suffix in ("content", "versions"):
        response = office_api.client.get(f"{BASE}/{object_id}/{suffix}", headers=reader_headers)
        assert response.status_code == 404
        assert response.json() == {"detail": "Document not found"}
        assert response.headers["Cache-Control"] == "no-store"
    assert office_api.client.get(BASE, headers=reader_headers).json()["documents"] == []
    metadata_read.assert_not_called()


@pytest.mark.parametrize("human_confirmation", [False, "true", None])
def test_office_validation_errors_never_echo_document_bodies(
    office_api: OfficeApiHarness, caplog: pytest.LogCaptureFixture, human_confirmation: Any
) -> None:
    enable_office()
    response = office_api.client.post(
        BASE, headers=office_api.headers, json={**create_payload(), "human_confirmation": human_confirmation}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid document request"}
    assert response.headers["Cache-Control"] == "no-store"
    assert SECRET not in response.text and SECRET not in caplog.text
    assert office_api.repository.saved_versions == {}


def test_office_active_json_validation_is_safe_before_any_write(office_api: OfficeApiHarness) -> None:
    enable_office()
    command = create_payload()
    command["document"]["content"].append({"type": "image", "attrs": {"src": f"https://invalid/{SECRET}"}})
    response = office_api.client.post(BASE, headers=office_api.headers, json=command)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid document request"}
    assert response.headers["Cache-Control"] == "no-store"
    assert SECRET not in response.text
    assert office_api.repository.saved_versions == {}


@pytest.mark.parametrize("chunked", [False, True])
def test_office_request_bytes_are_bounded_before_parser_even_without_content_length(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch, chunked: bool
) -> None:
    enable_office()
    commit = Mock(wraps=office_api.repository.commit)
    monkeypatch.setattr(office_api.repository, "commit", commit)
    payload = (SECRET.encode() + b"x" * MAX_OFFICE_REQUEST_BYTES)[: MAX_OFFICE_REQUEST_BYTES + 1]
    body = (payload[index : index + 17000] for index in range(0, len(payload), 17000)) if chunked else payload
    response = office_api.client.post(
        BASE, headers={**office_api.headers, "Content-Type": "application/json"}, content=body
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Document request is too large"}
    assert response.headers["Cache-Control"] == "no-store"
    if chunked:
        assert "content-length" not in response.request.headers
        assert response.request.headers["transfer-encoding"] == "chunked"
    assert SECRET not in response.text
    commit.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "save", "list"])
def test_office_storage_and_database_errors_are_safe_and_uncacheable(
    office_api: OfficeApiHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    operation: str,
) -> None:
    created = create_document(office_api)
    object_id = created["document"]["object_id"]
    if operation == "read":
        monkeypatch.setattr(office_api.service.source_repository, "get", Mock(side_effect=SourceObjectStorageError(SECRET)))
        response = office_api.client.get(f"{BASE}/{object_id}/content", headers=office_api.headers)
    elif operation == "save":
        monkeypatch.setattr(office_api.service.source_repository, "add", Mock(side_effect=SourceObjectStorageError(SECRET)))
        response = office_api.client.post(
            f"{BASE}/{object_id}/versions", headers=office_api.headers, json=save_payload(created)
        )
    else:
        monkeypatch.setattr(office_api.repository, "list_documents", Mock(side_effect=psycopg.OperationalError(SECRET)))
        response = office_api.client.get(BASE, headers=office_api.headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "Office storage unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert SECRET not in response.text and SECRET not in caplog.text
    assert len(office_api.repository.saved_versions) == 1


def test_office_shell_has_strict_same_origin_csp_and_no_external_editor_assets(office_api: OfficeApiHarness) -> None:
    response = office_api.client.get("/office")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == OFFICE_CSP
    assert "script-src 'self'" in OFFICE_CSP
    assert "style-src 'self'" in OFFICE_CSP
    assert "unsafe-inline" not in OFFICE_CSP and "unsafe-eval" not in OFFICE_CSP
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert 'src="/office/editor.js?v=1"' in response.text
    assert 'src="https://' not in response.text


def test_office_jwt_ignores_forged_browser_roles_ids_and_tenant(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_document(office_api)
    object_id = created["document"]["object_id"]
    principal = PrincipalRecord(
        issuer=DEFAULT_JWT_ISSUER,
        subject="office-reader-subject",
        user_id="office-jwt-reader",
        memberships=[TenantMembership(tenant_id="tenant-demo", role_ids={"office-reader"})],
    )
    resolver = JwtPrincipalResolver(
        verifier=HmacJwtVerifier(
            issuer=DEFAULT_JWT_ISSUER, audience=DEFAULT_JWT_AUDIENCE, secret=DEFAULT_DEV_JWT_SECRET
        ),
        directory=InMemoryPrincipalDirectory(principals=[principal], object_acls=[]),
    )
    monkeypatch.setattr(app.state, "principal_resolver", resolver)
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": principal.subject,
        "tenant_id": "tenant-demo",
        "iat": int(time()) - 1,
        "exp": int(time()) + 120,
        "roles": ["tenant-admin"],
        "readable_object_ids": [object_id],
    }
    segments = [
        base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")
        for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    ]
    signing_input = ".".join(segments)
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode(), signing_input.encode(), sha256).digest()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    headers = {
        **office_api.headers,
        "X-Tenant-Id": "tenant-other",
        "X-User-Id": "forged-admin",
        "X-Role-Ids": "tenant-admin",
        "Authorization": f"Bearer {token}",
    }
    office_api.repository.grants[("tenant-demo", object_id, principal.user_id)] = "read"
    assert office_api.client.get(f"{BASE}/{object_id}/content", headers=headers).status_code == 404
    resolver.directory = InMemoryPrincipalDirectory(
        principals=[principal],
        object_acls=[ObjectAclRecord(tenant_id="tenant-demo", object_id=object_id, readable_user_ids={principal.user_id})],
    )
    response = office_api.client.get(f"{BASE}/{object_id}/content", headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-demo"
    assert response.json()["can_write"] is False
    assert office_api.client.post(BASE, headers=headers, json=create_payload("forged-create")).status_code == 403
    assert office_api.client.post(
        f"{BASE}/{object_id}/versions", headers=headers, json=save_payload(created)
    ).status_code == 403
