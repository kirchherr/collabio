from __future__ import annotations

import base64
import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
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
from suite.platform.knowledge_base import (
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleLifecycleState,
    KnowledgeBaseArticleRecord,
    KnowledgeBaseArticleService,
    KnowledgeBaseArticleStatus,
    demo_knowledge_base_source_object_repository,
)
from suite.platform.knowledge_base_runtime import (
    InMemoryKnowledgeBaseRuntimeActivationStore,
    KnowledgeBaseArticleServiceResolver,
)
from suite.platform.modules import default_module_registry
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

ARTICLE_ID = "kb-article-backup-runbook-demo"
VERSION_ID = "kb-article-version-backup-runbook-v1-demo"
PATH = f"/v1/kb/articles/{ARTICLE_ID}/content"


@dataclass
class ReadHarness:
    client: TestClient
    service: KnowledgeBaseArticleService
    headers: dict[str, str]
    article: KnowledgeBaseArticleRecord
    source: SourceObjectRecord


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[ReadHarness]:
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=logger,
    )
    article = next(a for a in service.repository.list_articles(tenant_id="tenant-demo") if a.object_id == ARTICLE_ID)
    source = service.source_repository.get(tenant_id="tenant-demo", object_id=VERSION_ID, version_id="v1")
    monkeypatch.setattr(app.state, "module_registry", default_module_registry())
    monkeypatch.setattr(
        app.state,
        "knowledge_base_article_service_resolver",
        KnowledgeBaseArticleServiceResolver(
            default_service=service,
            audit_logger=logger,
            activation_store=InMemoryKnowledgeBaseRuntimeActivationStore(),
            environ={},
        ),
    )
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "user-demo",
        "X-Role-Ids": "knowledge-worker",
        "X-Readable-Object-Ids": f"{ARTICLE_ID},{VERSION_ID}",
    }
    with TestClient(app) as client:
        admin_headers = {**headers, "X-Role-Ids": "tenant-admin"}
        for action in ("provision", "enable"):
            response = client.post(
                f"/v1/admin/tenant-modules/knowledge_base/{action}",
                headers=admin_headers,
                json={"approval_reference": "approval:synthetic-reader-test", "reason": "isolated reader test"},
            )
            assert response.status_code == 200, response.text
        yield ReadHarness(client, service, headers, article, source)


def spy_source_reads(harness: ReadHarness, monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    repository = harness.service.source_repository
    metadata_read = Mock(wraps=repository.get_metadata)  # type: ignore[attr-defined]
    content_read = Mock(wraps=repository.get)
    monkeypatch.setattr(repository, "get_metadata", metadata_read)
    monkeypatch.setattr(repository, "get", content_read)
    return metadata_read, content_read


def replace_source(
    harness: ReadHarness,
    monkeypatch: pytest.MonkeyPatch,
    source: SourceObjectRecord,
    *,
    bind_article: bool = False,
) -> Mock:
    monkeypatch.setattr(harness.service.source_repository, "get_metadata", Mock(return_value=source.metadata))
    content_read = Mock(return_value=source)
    monkeypatch.setattr(harness.service.source_repository, "get", content_read)
    if bind_article:
        article = harness.article.model_copy(
            update={
                "current_source_manifest_hash": source.metadata.manifest_hash,
                "current_content_hash": source.metadata.content_hash,
            }
        )
        monkeypatch.setattr(harness.service.repository, "list_articles", Mock(return_value=(article,)))
    return content_read


def test_normal_reader_gets_exact_current_plaintext_with_write_disabled_and_metadata_only_audit(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    result = response.json()
    assert result["tenant_id"] == "tenant-demo"
    assert result["body"] == harness.source.text
    assert result["article"]["object_id"] == ARTICLE_ID
    assert result["article"]["current_version_object_id"] == VERSION_ID
    assert result["article"]["current_source_version_id"] == "v1"
    assert result["article"]["source_version_evidence_hash"].startswith("sha256:")
    assert result["article"]["access_checked"] is True
    assert result["article"]["source_version_access_checked"] is True
    assert result["rag_indexing_allowed"] is result["search_indexing_allowed"] is False
    for call in (metadata_read, content_read):
        call.assert_called_once_with(tenant_id="tenant-demo", object_id=VERSION_ID, version_id="v1")
    module = app.state.module_registry.get_tenant_module("tenant-demo", "knowledge_base")
    assert module.feature_enabled("knowledge_base.articles.read") is True
    assert module.feature_enabled("knowledge_base.articles.write") is False
    events = harness.service.audit_logger.events
    assert len(events) == 1
    event = events[0]
    assert event.event_id == result["audit_event_id"]
    assert event.event_type == "knowledge_base.article.content_read"
    assert set(event.source_object_ids) == {ARTICLE_ID, VERSION_ID}
    assert event.input_hash is event.output_hash is None
    assert event.metadata["surface"] == "api"
    assert event.metadata["feature_id"] == "knowledge_base.articles.read"
    assert event.metadata["content_included"] is False
    assert event.metadata["source_version_evidence_hash"] == result["article"]["source_version_evidence_hash"]
    assert harness.source.text not in json.dumps(event.model_dump(mode="json"))
    assert harness.source.text not in caplog.text
    edit = harness.client.get(f"/v1/admin/kb/articles/{ARTICLE_ID}/edit-content", headers=harness.headers)
    assert edit.status_code == 403


@pytest.mark.parametrize("readable", ["", ARTICLE_ID, VERSION_ID])
def test_missing_article_or_version_acl_denies_before_any_source_read(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, readable: str
) -> None:
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    response = harness.client.get(PATH, headers={**harness.headers, "X-Readable-Object-Ids": readable})
    assert response.status_code == 404
    assert response.json() == {"detail": "Knowledge Base article is unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    metadata_read.assert_not_called()
    content_read.assert_not_called()
    assert harness.service.audit_logger.events == ()


def test_distinct_unreadable_source_reference_denies_before_source_read(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    article = harness.article.model_copy(update={"current_source_object_id": "source-without-acl"})
    monkeypatch.setattr(harness.service.repository, "list_articles", Mock(return_value=(article,)))
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    assert harness.client.get(PATH, headers=harness.headers).status_code == 404
    metadata_read.assert_not_called()
    content_read.assert_not_called()


@pytest.mark.parametrize("target", ["kb-article-other-tenant", "kb-article-missing"])
def test_foreign_or_missing_article_is_generic_not_found_even_with_forged_readable_ids(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    response = harness.client.get(
        f"/v1/kb/articles/{target}/content",
        headers={**harness.headers, "X-Readable-Object-Ids": f"{target},kb-article-version-other-tenant-v1"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Knowledge Base article is unavailable"}
    metadata_read.assert_not_called()
    content_read.assert_not_called()


@pytest.mark.parametrize("block", ["module", "feature", "authentication"])
def test_reader_requires_authentication_module_and_read_feature_before_source_access(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, block: str
) -> None:
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    headers = harness.headers
    if block == "module":
        response = harness.client.post(
            "/v1/admin/tenant-modules/knowledge_base/disable",
            headers={**headers, "X-Role-Ids": "tenant-admin"},
            json={"approval_reference": "approval:synthetic-disable", "reason": "read gate test"},
        )
        assert response.status_code == 200
    elif block == "feature":
        registry = app.state.module_registry
        current = registry.get_tenant_module("tenant-demo", "knowledge_base")
        registry.upsert_tenant_module(current.model_copy(update={"enabled_features": {}}))
    else:
        headers = {}
    response = harness.client.get(PATH, headers=headers)
    assert response.status_code == (401 if block == "authentication" else 403)
    metadata_read.assert_not_called()
    content_read.assert_not_called()


@pytest.mark.parametrize(
    "status,lifecycle",
    [
        (KnowledgeBaseArticleStatus.DRAFT, KnowledgeBaseArticleLifecycleState.WORKING),
        (KnowledgeBaseArticleStatus.RESTRICTED, KnowledgeBaseArticleLifecycleState.RESTRICTED),
        (KnowledgeBaseArticleStatus.ARCHIVED, KnowledgeBaseArticleLifecycleState.DISPOSITION_PENDING),
        (KnowledgeBaseArticleStatus.PUBLISHED, KnowledgeBaseArticleLifecycleState.DISPOSITION_PENDING),
    ],
)
def test_nonpublished_article_state_denies_content_before_source_access(
    harness: ReadHarness,
    monkeypatch: pytest.MonkeyPatch,
    status: KnowledgeBaseArticleStatus,
    lifecycle: KnowledgeBaseArticleLifecycleState,
) -> None:
    article = harness.article.model_copy(update={"status": status, "lifecycle_state": lifecycle})
    monkeypatch.setattr(harness.service.repository, "list_articles", Mock(return_value=(article,)))
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    assert harness.client.get(PATH, headers=harness.headers).status_code == 404
    metadata_read.assert_not_called()
    content_read.assert_not_called()


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": "tenant-other"},
        {"object_id": "other-source"},
        {"version_id": "v2"},
        {"object_type": SourceObjectType.DOCUMENT},
        {"manifest_hash": "sha256:" + "f" * 64},
        {"content_hash": "sha256:" + "f" * 64},
        {"acl_version": 2},
    ],
)
def test_mismatched_source_metadata_is_rejected_before_content_fetch(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, updates: dict[str, Any]
) -> None:
    source = harness.source.model_copy(update={"metadata": harness.source.metadata.model_copy(update=updates)})
    content_read = replace_source(harness, monkeypatch, source)
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Knowledge Base source validation failed"}
    content_read.assert_not_called()
    assert harness.service.audit_logger.events == ()


@pytest.mark.parametrize(
    "updates",
    [
        {"mime_type": "text/html"},
        {"schema_version": "source_object.v999"},
        {"lifecycle_state": SourceLifecycleState.WORKING},
        {"lifecycle_state": SourceLifecycleState.RESTRICTED},
        {"lifecycle_state": SourceLifecycleState.DELETED},
        {"lifecycle_state": SourceLifecycleState.CRYPTOSHREDDED},
        {"content_byte_length": 400_001},
        {"content_byte_length": 0},
    ],
)
def test_bound_but_unsupported_source_metadata_never_loads_body(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, updates: dict[str, Any]
) -> None:
    metadata = harness.source.metadata.model_copy(update=updates)
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = harness.source.model_copy(update={"metadata": metadata})
    content_read = replace_source(harness, monkeypatch, source, bind_article=True)
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Knowledge Base source validation failed"}
    content_read.assert_not_called()
    assert harness.service.audit_logger.events == ()


@pytest.mark.parametrize("content", [b"\xff", b"null\x00text", b" " * 10, b"x" * 100_001])
def test_bound_content_must_be_bounded_utf8_plaintext(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    metadata = harness.source.metadata.model_copy(
        update={"content_byte_length": len(content), "content_hash": sha256_bytes(content)}
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = SourceObjectRecord(metadata=metadata, content_bytes=content)
    content_read = replace_source(harness, monkeypatch, source, bind_article=True)
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Knowledge Base source validation failed"}
    assert response.headers["Cache-Control"] == "no-store"
    content_read.assert_called_once()
    assert harness.service.audit_logger.events == ()


@pytest.mark.parametrize("corruption", ["bytes", "metadata"])
def test_content_fetch_revalidates_actual_source_and_does_not_trust_metadata_preflight(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    updates: dict[str, Any] = {"text": "x" * len(harness.source.text)}
    if corruption == "metadata":
        updates = {"metadata": harness.source.metadata.model_copy(update={"tenant_id": "tenant-other"})}
    corrupted = harness.source.model_copy(update=updates)
    monkeypatch.setattr(harness.service.source_repository, "get", Mock(return_value=corrupted))
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == 400
    assert response.json() == {"detail": "Knowledge Base source validation failed"}
    assert harness.service.audit_logger.events == ()


@pytest.mark.parametrize("surface", ["get_metadata", "get"])
@pytest.mark.parametrize("error", [SourceObjectStorageError, psycopg.OperationalError, KeyError])
def test_reader_storage_failure_is_redacted_and_does_not_audit_a_content_read(
    harness: ReadHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    surface: str,
    error: type[Exception],
) -> None:
    secret = "SECRET ARTICLE BODY inside storage exception"
    monkeypatch.setattr(harness.service.source_repository, surface, Mock(side_effect=error(secret)))
    response = harness.client.get(PATH, headers=harness.headers)
    assert response.status_code == (404 if error is KeyError else 503)
    assert response.json() == {
        "detail": "Knowledge Base article is unavailable" if error is KeyError else "Knowledge Base storage unavailable"
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert secret not in response.text
    assert secret not in caplog.text
    assert harness.service.audit_logger.events == ()


def test_jwt_reader_uses_server_principal_acl_and_ignores_forged_browser_grants(
    harness: ReadHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    principal = PrincipalRecord(
        issuer=DEFAULT_JWT_ISSUER,
        subject="reader-subject",
        user_id="reader-user",
        memberships=[TenantMembership(tenant_id="tenant-demo", role_ids={"knowledge-worker"})],
    )
    resolver = JwtPrincipalResolver(
        verifier=HmacJwtVerifier(
            issuer=DEFAULT_JWT_ISSUER, audience=DEFAULT_JWT_AUDIENCE, secret=DEFAULT_DEV_JWT_SECRET
        ),
        directory=InMemoryPrincipalDirectory(principals=[principal], object_acls=[]),
    )
    monkeypatch.setattr(app.state, "principal_resolver", resolver)
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": "reader-subject",
        "tenant_id": "tenant-demo",
        "iat": int(time()) - 1,
        "exp": int(time()) + 120,
        "roles": ["tenant-admin"],
        "readable_object_ids": [ARTICLE_ID, VERSION_ID],
    }
    segments = [
        base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")
        for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    ]
    signing_input = ".".join(segments)
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode(), signing_input.encode(), sha256).digest()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    headers = {
        **harness.headers,
        "X-Tenant-Id": "tenant-other",
        "X-User-Id": "forged-admin",
        "X-Role-Ids": "tenant-admin",
        "Authorization": f"Bearer {token}",
    }
    metadata_read, content_read = spy_source_reads(harness, monkeypatch)
    denied = harness.client.get(PATH, headers=headers)
    assert denied.status_code == 404
    metadata_read.assert_not_called()
    content_read.assert_not_called()
    resolver.directory = InMemoryPrincipalDirectory(
        principals=[principal],
        object_acls=[
            ObjectAclRecord(tenant_id="tenant-demo", object_id=object_id, readable_user_ids={"reader-user"})
            for object_id in (ARTICLE_ID, VERSION_ID)
        ],
    )
    allowed = harness.client.get(PATH, headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["tenant_id"] == "tenant-demo"
    assert harness.service.audit_logger.events[-1].user_id == "reader-user"
    assert harness.client.get(f"/v1/admin/kb/articles/{ARTICLE_ID}/edit-content", headers=headers).status_code == 403
