from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.knowledge_base import (
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleService,
    build_source_object_manifest_hash,
    demo_knowledge_base_source_object_repository,
)
from suite.platform.knowledge_base_runtime import (
    InMemoryKnowledgeBaseRuntimeActivationStore,
    KnowledgeBaseArticleServiceResolver,
)
from suite.platform.modules import default_module_registry
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import SourceObjectMetadata, SourceObjectRecord, sha256_bytes

ARTICLE_ID = "kb-article-backup-runbook-demo"
VERSION_ID = "kb-article-version-backup-runbook-v1-demo"
BASE = "/v1/admin/kb/articles"
BODY = "Private synthetic body. ÄÖÜ — never write this body to audit or application logs."


@dataclass
class ProductHarness:
    client: TestClient
    service: KnowledgeBaseArticleService
    headers: dict[str, str]

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, headers=self.headers, json=body)
        assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProductHarness]:
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=logger,
    )
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
        "X-Role-Ids": "tenant-admin",
        "X-Readable-Object-Ids": f"{ARTICLE_ID},{VERSION_ID}",
    }
    with TestClient(app) as client:
        result = ProductHarness(client, service, headers)
        result.post(
            "/v1/admin/tenant-modules/knowledge_base/provision",
            {"approval_reference": "approval:synthetic-product-test", "reason": "isolated test"},
        )
        result.post(
            "/v1/admin/tenant-modules/knowledge_base/enable",
            {
                "approval_reference": "approval:synthetic-product-test",
                "reason": "isolated test",
                "enabled_features": {"knowledge_base.articles.read": True, "knowledge_base.articles.write": True},
            },
        )
        yield result


def staged_write(harness: ProductHarness, *, edit: bool = False) -> dict[str, dict[str, Any]]:
    proposal: dict[str, Any] = {"operation": "create", "title": "New article", "body": BODY}
    if edit:
        proposal.update(
            operation="edit",
            article_object_id=ARTICLE_ID,
            expected_current_version_object_id=VERSION_ID,
            title="Updated runbook title",
        )
    prepared = harness.post(f"{BASE}/prepare-write", proposal)
    dry = harness.post(f"{BASE}/write-dry-run", prepared["write_command"])
    approval_command = {
        "dry_run_write_approval_evidence_hash": dry["write_approval_evidence_hash"],
        "approval_reference": "approval:synthetic-product-write",
        "reason": "approve synthetic product write",
    }
    approved = harness.post(f"{BASE}/write-approvals/approve", approval_command)
    evidence_hash = approved["approved_write_approval_evidence_hash"]
    guard_command = {
        "approved_write_approval_evidence_hash": evidence_hash,
        "proposed_source_record": prepared["proposed_source_record"],
    }
    guard = harness.post(f"{BASE}/source-object-write-guard", guard_command)
    assert guard["allowed"] is True
    assert guard["rag_indexing_allowed"] is False
    preview_command = {
        "approved_write_approval_evidence_hash": evidence_hash,
        "preview_reference": "preview:synthetic-product-write",
        "reason": "verify source and restore evidence",
    }
    preview = harness.post(f"{BASE}/write-approvals/refresh-preview", preview_command)
    skeleton_command = {
        "approved_write_approval_evidence_hash": evidence_hash,
        "source_object_write_guard_decision": guard,
        "refresh_preview_command_hash": preview["preview_command_hash"],
        "projected_restore_evidence_preview_hash": preview["projected_restore_evidence_preview_hash"],
        "execution_reference": "execution:synthetic-product-write",
        "human_confirmation_reference": "human-confirmation:synthetic-product-write",
        "reason": "user explicitly confirms synthetic write",
    }
    skeleton = harness.post(f"{BASE}/write-approvals/execution-skeleton", skeleton_command)
    execute_command = {
        **skeleton_command,
        "execution_skeleton_command_hash": skeleton["execution_command_hash"],
        "execution_plan_hash": skeleton["execution_plan_hash"],
        "proposed_source_record": prepared["proposed_source_record"],
    }
    return {
        "prepare-write": proposal,
        "write-dry-run": prepared["write_command"],
        "write-approvals/approve": approval_command,
        "source-object-write-guard": guard_command,
        "write-approvals/refresh-preview": preview_command,
        "write-approvals/execution-skeleton": skeleton_command,
        "write-approvals/execute": execute_command,
    }


@pytest.mark.parametrize("edit", [False, True])
def test_product_write_server_prepares_source_and_commits_existing_chain(harness: ProductHarness, edit: bool) -> None:
    stages = staged_write(harness, edit=edit)
    proposed = stages["write-approvals/execute"]["proposed_source_record"]
    source = SourceObjectRecord.model_validate(proposed)
    assert source.metadata.manifest_hash == build_source_object_manifest_hash(source.metadata)
    assert source.metadata.content_hash == sha256_bytes(BODY.encode("utf-8"))
    assert source.metadata.created_by == "user-demo"
    assert source.metadata.owner_principal_id == "user-demo"
    assert source.metadata.retention_policy_id == "rp-standard"
    assert source.metadata.classification == "internal"
    result = harness.post(f"{BASE}/write-approvals/execute", stages["write-approvals/execute"])
    assert result["write_unit_of_work_committed"] is True
    assert result["rag_indexing_allowed"] is False
    assert result["search_indexing_allowed"] is False
    assert result["refreshed_source_version_evidence_hash"] == result["proposed_source_version_evidence_hash"]
    assert result["refreshed_restore_evidence_hash"] != result["previous_restore_evidence_hash"]
    assert result["source_object_write_receipt_hash"].startswith("sha256:")
    article_id = result["article_object_id"]
    harness.headers["X-Readable-Object-Ids"] = f"{article_id},{result['current_version_object_id']}"
    content = harness.client.get(f"{BASE}/{article_id}/edit-content", headers=harness.headers)
    assert content.status_code == 200
    assert content.json()["body"] == BODY
    assert content.json()["article"]["title"] == stages["prepare-write"]["title"]
    events = json.dumps([event.model_dump(mode="json") for event in harness.service.audit_logger.events])
    assert BODY not in events
    assert "Private synthetic body" not in events
    assert "proposed_source_record" not in events
    assert len(harness.service.write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == 2


def test_product_edit_uses_current_version_and_fails_stale_without_overwrite(harness: ProductHarness) -> None:
    stages = staged_write(harness, edit=True)
    result = harness.post(f"{BASE}/write-approvals/execute", stages["write-approvals/execute"])
    harness.headers["X-Readable-Object-Ids"] += f",{result['current_version_object_id']}"
    response = harness.client.post(f"{BASE}/prepare-write", headers=harness.headers, json=stages["prepare-write"])
    assert response.status_code == 409
    response = harness.client.post(f"{BASE}/write-dry-run", headers=harness.headers, json=stages["write-dry-run"])
    assert response.status_code == 409
    assert harness.client.get(f"{BASE}/{ARTICLE_ID}/edit-content", headers=harness.headers).json()["body"] == BODY


@pytest.mark.parametrize("block", ["feature", "module", "role", "acl"])
def test_every_product_stage_rechecks_current_policy_and_acl(harness: ProductHarness, block: str) -> None:
    stages = staged_write(harness, edit=True)
    before = len(harness.service.write_approval_ledger.list_evidence(tenant_id="tenant-demo"))
    if block == "role":
        harness.headers["X-Role-Ids"] = "knowledge-worker"
    elif block == "acl":
        harness.headers["X-Readable-Object-Ids"] = ARTICLE_ID
    elif block == "module":
        harness.post(
            "/v1/admin/tenant-modules/knowledge_base/disable",
            {"approval_reference": "approval:synthetic-disable", "reason": "test revocation"},
        )
    else:
        registry = app.state.module_registry
        current = registry.get_tenant_module("tenant-demo", "knowledge_base")
        registry.upsert_tenant_module(
            current.model_copy(update={"enabled_features": {"knowledge_base.articles.read": True}})
        )
    for path, payload in stages.items():
        response = harness.client.post(f"{BASE}/{path}", headers=harness.headers, json=payload)
        assert response.status_code == (404 if block == "acl" else 403), (path, response.text)
    response = harness.client.get(f"{BASE}/{ARTICLE_ID}/edit-content", headers=harness.headers)
    assert response.status_code == (404 if block == "acl" else 403)
    assert len(harness.service.write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == before
    article = next(
        a for a in harness.service.repository.list_articles(tenant_id="tenant-demo") if a.object_id == ARTICLE_ID
    )
    assert article.current_version_object_id == VERSION_ID


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": "tenant-other"},
        {"retention_policy_id": "forever"},
        {"acl_version": 9},
        {"owner_principal_id": "other"},
        {"proposed_content_hash": "sha256:" + "a" * 64},
    ],
)
def test_product_prepare_rejects_security_metadata(harness: ProductHarness, extra: dict[str, Any]) -> None:
    response = harness.client.post(
        f"{BASE}/prepare-write",
        headers=harness.headers,
        json={"operation": "create", "title": "Title", "body": BODY, **extra},
    )
    assert response.status_code == 422
    assert harness.service.write_approval_ledger.list_evidence(tenant_id="tenant-demo") == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "tenant-other"),
        ("owner_principal_id", "other"),
        ("created_by", "other"),
        ("kms_key_ref", "kms:foreign"),
        ("acl_version", 2),
        ("mime_type", "text/html"),
    ],
)
def test_guard_and_execution_reject_tampered_security_metadata(harness: ProductHarness, field: str, value: Any) -> None:
    stages = staged_write(harness)
    for path in ("source-object-write-guard", "write-approvals/execute"):
        payload = json.loads(json.dumps(stages[path]))
        payload["proposed_source_record"]["metadata"][field] = value
        response = harness.client.post(f"{BASE}/{path}", headers=harness.headers, json=payload)
        assert response.status_code == 400
        assert "security metadata" in response.json()["detail"]


@pytest.mark.parametrize(
    "field,value",
    [("owner_principal_id", "other"), ("created_by", "other"), ("acl_hash", "sha256:" + "f" * 64)],
)
def test_guard_rejects_rehashed_security_metadata_even_with_valid_approval_lineage(
    harness: ProductHarness, field: str, value: str
) -> None:
    prepared = harness.post(f"{BASE}/prepare-write", {"operation": "create", "title": "Title", "body": BODY})
    proposed = prepared["proposed_source_record"]
    proposed["metadata"][field] = value
    metadata = SourceObjectMetadata.model_validate(proposed["metadata"])
    proposed["metadata"]["manifest_hash"] = build_source_object_manifest_hash(metadata)
    command = prepared["write_command"]
    command["proposed_source_manifest_hash"] = proposed["metadata"]["manifest_hash"]
    dry_run = harness.post(f"{BASE}/write-dry-run", command)
    approval = harness.post(
        f"{BASE}/write-approvals/approve",
        {
            "dry_run_write_approval_evidence_hash": dry_run["write_approval_evidence_hash"],
            "approval_reference": "approval:canonical-tamper-test",
            "reason": "test untrusted canonicalized browser metadata",
        },
    )
    response = harness.client.post(
        f"{BASE}/source-object-write-guard",
        headers=harness.headers,
        json={
            "approved_write_approval_evidence_hash": approval["approved_write_approval_evidence_hash"],
            "proposed_source_record": proposed,
        },
    )
    assert response.status_code == 400
    assert "security metadata" in response.json()["detail"]
    article_ids = {article.object_id for article in harness.service.repository.list_articles(tenant_id="tenant-demo")}
    assert command["article_object_id"] not in article_ids


@pytest.mark.parametrize("error_type", [SourceObjectStorageError, psycopg.OperationalError])
def test_product_storage_failure_is_redacted_and_does_not_report_commit(
    harness: ProductHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    stages = staged_write(harness)

    def fail_commit(**kwargs: Any) -> None:
        raise error_type(BODY)

    monkeypatch.setattr(harness.service.write_unit_of_work, "commit", fail_commit)
    response = harness.client.post(
        f"{BASE}/write-approvals/execute", headers=harness.headers, json=stages["write-approvals/execute"]
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Knowledge Base storage unavailable"}
    assert BODY not in caplog.text
    article_ids = {article.object_id for article in harness.service.repository.list_articles(tenant_id="tenant-demo")}
    assert stages["write-dry-run"]["article_object_id"] not in article_ids
    assert not any(
        event.event_type == "knowledge_base.write_approval.executed" for event in harness.service.audit_logger.events
    )


def test_product_read_capability_and_cross_tenant_evidence_are_authoritative(harness: ProductHarness) -> None:
    assert harness.client.get("/v1/kb/articles", headers=harness.headers).json()["can_write"] is True
    non_admin = {**harness.headers, "X-Role-Ids": "knowledge-worker"}
    assert harness.client.get("/v1/kb/articles", headers=non_admin).json()["can_write"] is False
    unknown = harness.client.get(f"{BASE}/kb-article-other-tenant/edit-content", headers=harness.headers)
    assert unknown.status_code == 404
    stages = staged_write(harness)
    foreign_evidence = {
        **stages["source-object-write-guard"],
        "approved_write_approval_evidence_hash": "sha256:" + "f" * 64,
    }
    assert (
        harness.client.post(
            f"{BASE}/source-object-write-guard", headers=harness.headers, json=foreign_evidence
        ).status_code
        == 404
    )


def test_product_execute_requires_explicit_confirmation_reference(harness: ProductHarness) -> None:
    payload = staged_write(harness)["write-approvals/execute"]
    del payload["human_confirmation_reference"]
    assert (
        harness.client.post(f"{BASE}/write-approvals/execute", headers=harness.headers, json=payload).status_code == 422
    )
