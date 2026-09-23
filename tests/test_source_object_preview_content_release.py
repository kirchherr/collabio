from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.audit import stable_hash
from suite.ai_control_plane.models import DataClass, TenantPolicy
from suite.persistence.migrator import apply_migrations
from suite.platform.source_object_preview_content_release import (
    CONTENT_RELEASE_CONFIRMATION_STATEMENT,
    InMemorySourceObjectPreviewContentReleaseReceiptStore,
    PgSourceObjectPreviewContentReleaseReceiptStore,
    SourceObjectPreviewContentReleaseReceipt,
    build_source_object_preview_content_release_receipt_hash,
    sanitize_source_object_preview_text,
)
from suite.platform.source_object_preview_renderer_release_gate import (
    InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore,
    SourceObjectPreviewRendererReleaseGateEvidence,
    SourceObjectPreviewRendererReleaseGateStatus,
    build_source_object_preview_renderer_release_gate_hash,
)
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.storage.source_objects import SourceObjectType

ZERO_HASH = "sha256:" + ("0" * 64)
DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = os.environ.get("SUITE_DATABASE_DSN")
    if migration_dsn is None or app_dsn is None:
        pytest.skip("PostgreSQL test DSNs are not configured")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def test_content_release_endpoint_returns_sanitized_text_without_persisting_content() -> None:
    client = TestClient(app)
    previous_policy_repository = app.state.tenant_policy_repository
    previous_gate_store = app.state.source_object_preview_renderer_release_gate_store
    previous_receipt_store = app.state.source_object_preview_content_release_receipt_store
    gate_store = InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()
    receipt_store = InMemorySourceObjectPreviewContentReleaseReceiptStore()
    app.state.tenant_policy_repository = _enabled_policy_repository()
    app.state.source_object_preview_renderer_release_gate_store = gate_store
    app.state.source_object_preview_content_release_receipt_store = receipt_store
    gate = _ready_release_gate(tenant_id="tenant-demo")
    gate_store.append(gate)
    suffix = uuid4().hex

    try:
        renderer = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{suffix}",
                "backup_coverage_evidence_ref": f"backup:{suffix}",
                "restore_evidence_ref": f"restore-drill:{suffix}",
                "reason": "prepare safe text release",
            },
        )
        assert renderer.status_code == 200
        renderer_ref = renderer.json()["renderer_sandbox_evidence_ref"]
        confirmation_ref = f"approval:{suffix}"
        decision = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{suffix}",
                "renderer_sandbox_evidence_ref": renderer_ref,
                "backup_coverage_evidence_ref": f"backup:{suffix}",
                "restore_evidence_ref": f"restore-drill:{suffix}",
                "human_confirmation_reference": confirmation_ref,
                "reason": "collect complete release evidence",
            },
        )
        assert decision.status_code == 200
        assert decision.json()["content_release_evidence_complete"] is True

        release_reason = "show this authorized document once"
        release = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-content-releases",
            headers=DEMO_HEADERS,
            json={
                "preview_decision_evidence_hash": decision.json()["preview_decision_evidence_hash"],
                "renderer_release_gate_evidence_hash": gate.evidence_hash,
                "human_confirmation_reference": confirmation_ref,
                "human_confirmation_statement": CONTENT_RELEASE_CONFIRMATION_STATEMENT,
                "release_request_reference": f"preview-release:{suffix}",
                "reason": release_reason,
            },
        )
    finally:
        app.state.tenant_policy_repository = previous_policy_repository
        app.state.source_object_preview_renderer_release_gate_store = previous_gate_store
        app.state.source_object_preview_content_release_receipt_store = previous_receipt_store

    assert release.status_code == 200
    body = release.json()
    assert body["result_contract"] == "acl_checked_sanitized_plain_text_preview.v1"
    assert body["content"] == "Board pack draft source content."
    assert body["response_media_type"] == "text/plain; charset=utf-8"
    assert body["content_included"] is True
    assert body["content_persisted"] is False
    assert body["external_fetch_allowed"] is False
    assert body["active_content_allowed"] is False
    assert body["mail_body_release_allowed"] is False
    assert body["content_release_receipt_evidence_hash"].startswith("sha256:")

    receipts = receipt_store.list_receipts(tenant_id="tenant-demo")
    assert len(receipts) == 1
    receipt_json = receipts[0].model_dump_json()
    assert "Board pack draft source content" not in receipt_json
    assert CONTENT_RELEASE_CONFIRMATION_STATEMENT not in receipt_json
    assert release_reason not in receipt_json
    assert receipts[0].content_included_in_receipt is False
    assert receipts[0].content_persisted is False
    assert receipts[0].evidence_hash == body["content_release_receipt_evidence_hash"]

    release_event = next(
        event for event in reversed(app.state.audit_logger.events) if event.event_id == body["audit_event_id"]
    )
    audit_json = json.dumps(release_event.metadata)
    assert "Board pack draft source content" not in audit_json
    assert CONTENT_RELEASE_CONFIRMATION_STATEMENT not in audit_json
    assert release_reason not in audit_json
    assert release_event.metadata["content_included_in_audit"] is False


def test_content_release_endpoint_fails_closed_before_evidence_when_policy_is_disabled() -> None:
    client = TestClient(app)
    previous_policy_repository = app.state.tenant_policy_repository
    app.state.tenant_policy_repository = InMemoryTenantPolicyRepository(
        policies={"tenant-demo": TenantPolicy(tenant_id="tenant-demo", content_preview_enabled=False)}
    )
    try:
        response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-content-releases",
            headers=DEMO_HEADERS,
            json={
                "preview_decision_evidence_hash": "sha256:" + ("1" * 64),
                "renderer_release_gate_evidence_hash": "sha256:" + ("2" * 64),
                "human_confirmation_reference": "approval:policy-disabled",
                "human_confirmation_statement": CONTENT_RELEASE_CONFIRMATION_STATEMENT,
                "release_request_reference": "preview-release:policy-disabled",
                "reason": "policy must reject this release",
            },
        )
    finally:
        app.state.tenant_policy_repository = previous_policy_repository

    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant content preview policy is disabled"


def test_content_release_endpoint_keeps_mail_body_closed_after_complete_evidence() -> None:
    client = TestClient(app)
    previous_policy_repository = app.state.tenant_policy_repository
    previous_gate_store = app.state.source_object_preview_renderer_release_gate_store
    previous_receipt_store = app.state.source_object_preview_content_release_receipt_store
    gate_store = InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()
    receipt_store = InMemorySourceObjectPreviewContentReleaseReceiptStore()
    app.state.tenant_policy_repository = _enabled_policy_repository()
    app.state.source_object_preview_renderer_release_gate_store = gate_store
    app.state.source_object_preview_content_release_receipt_store = receipt_store
    gate = _ready_release_gate(tenant_id="tenant-demo")
    gate_store.append(gate)
    suffix = uuid4().hex

    try:
        renderer = client.post(
            "/v1/source-objects/mail-1/versions/v1/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "mail.message.preview.metadata",
                "preview_policy_id": "preview-policy.mail.metadata-first.v1",
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{suffix}",
                "backup_coverage_evidence_ref": f"backup:{suffix}",
                "restore_evidence_ref": f"restore-drill:{suffix}",
                "reason": "prepare mail boundary test",
            },
        )
        confirmation_ref = f"approval:{suffix}"
        decision = client.post(
            "/v1/source-objects/mail-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "mail.message.preview.metadata",
                "preview_policy_id": "preview-policy.mail.metadata-first.v1",
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{suffix}",
                "renderer_sandbox_evidence_ref": renderer.json()["renderer_sandbox_evidence_ref"],
                "backup_coverage_evidence_ref": f"backup:{suffix}",
                "restore_evidence_ref": f"restore-drill:{suffix}",
                "human_confirmation_reference": confirmation_ref,
                "reason": "complete mail boundary evidence",
            },
        )
        release = client.post(
            "/v1/source-objects/mail-1/versions/v1/preview-content-releases",
            headers=DEMO_HEADERS,
            json={
                "preview_decision_evidence_hash": decision.json()["preview_decision_evidence_hash"],
                "renderer_release_gate_evidence_hash": gate.evidence_hash,
                "human_confirmation_reference": confirmation_ref,
                "human_confirmation_statement": CONTENT_RELEASE_CONFIRMATION_STATEMENT,
                "release_request_reference": f"preview-release:{suffix}",
                "reason": "mail content must remain closed",
            },
        )
    finally:
        app.state.tenant_policy_repository = previous_policy_repository
        app.state.source_object_preview_renderer_release_gate_store = previous_gate_store
        app.state.source_object_preview_content_release_receipt_store = previous_receipt_store

    assert renderer.status_code == 200
    assert decision.status_code == 200
    assert release.status_code == 415
    assert release.json()["detail"] == "source object type is not enabled for safe plain-text preview release"
    assert receipt_store.list_receipts(tenant_id="tenant-demo") == ()


def test_plain_text_sanitizer_normalizes_lines_and_removes_control_and_format_characters() -> None:
    assert sanitize_source_object_preview_text(b"hello\r\nworld\x07\xe2\x80\xae!") == "hello\nworld!"


def test_content_release_receipt_model_enforces_the_same_object_and_mime_allowlist() -> None:
    receipt = _release_receipt(tenant_id="tenant-model-guard")
    mail_payload = receipt.model_dump(mode="json") | {
        "source_object_type": "mail",
        "source_mime_type": "message/rfc822",
    }

    with pytest.raises(ValueError, match="source object type is not allowlisted"):
        SourceObjectPreviewContentReleaseReceipt.model_validate(mail_payload)


def test_content_release_migration_is_metadata_only_rls_guarded_and_registered() -> None:
    from suite.persistence.migration_catalog import get_migration

    migration = get_migration("0055")
    hardening_migration = get_migration("0056")
    sql = migration.sql().lower()
    hardening_sql = hardening_migration.sql().lower()

    assert migration.module_id == "core"
    assert hardening_migration.module_id == "core"
    assert "source_object_preview_content_release_nonempty_output" in hardening_sql
    assert "sanitized_content_byte_length > 0" in hardening_sql
    assert "collabio.source_object_preview_content_release_receipts" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "source_object_preview_content_release_tenant_select" in sql
    assert "source_object_preview_content_release_tenant_insert" in sql
    assert "source_object_preview_content_release_no_update" in sql
    assert "source_object_preview_content_release_no_hard_delete" in sql
    assert "not (receipt ? 'content')" in sql
    assert "not (receipt ? 'human_confirmation_statement')" in sql
    assert "not (receipt ? 'reason')" in sql
    assert "grant select, insert on table collabio.source_object_preview_content_release_receipts" in sql


def test_pg_content_release_receipts_are_tenant_scoped_and_append_only(live_database: LiveDatabase) -> None:
    tenant_id = f"tenant-preview-release-{uuid4().hex}"
    other_tenant_id = f"tenant-preview-release-other-{uuid4().hex}"
    store = PgSourceObjectPreviewContentReleaseReceiptStore(database_dsn=live_database.app_dsn)
    receipt = _release_receipt(tenant_id=tenant_id)

    assert store.append(receipt) == receipt
    assert store.get(tenant_id=tenant_id, evidence_hash=receipt.evidence_hash) == receipt
    assert store.list_receipts(tenant_id=tenant_id) == (receipt,)
    with pytest.raises(KeyError, match="not found"):
        store.get(tenant_id=other_tenant_id, evidence_hash=receipt.evidence_hash)

    with psycopg.connect(live_database.app_dsn) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE collabio.source_object_preview_content_release_receipts
                SET sanitized_content_byte_length = 0
                WHERE tenant_id = %s AND evidence_hash = %s
                """,
                (tenant_id, receipt.evidence_hash),
            )


def _enabled_policy_repository() -> InMemoryTenantPolicyRepository:
    return InMemoryTenantPolicyRepository(
        policies={
            "tenant-demo": TenantPolicy(
                tenant_id="tenant-demo",
                content_preview_enabled=True,
                allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL},
            )
        }
    )


def _ready_release_gate(*, tenant_id: str) -> SourceObjectPreviewRendererReleaseGateEvidence:
    now = datetime.now(UTC)
    draft = SourceObjectPreviewRendererReleaseGateEvidence(
        tenant_id=tenant_id,
        api_smoke_report_hash="sha256:" + ("1" * 64),
        recovery_drill_report_hash="sha256:" + ("2" * 64),
        api_smoke_checked_at_utc=now,
        recovery_drill_checked_at_utc=now,
        evaluated_at_utc=now,
        freshness_window_hours=24,
        api_smoke_fresh=True,
        recovery_drill_fresh=True,
        api_smoke_passed=True,
        recovery_drill_ready=True,
        recovery_drill_bound=True,
        tenant_ready=True,
        metadata_only_boundary_verified=True,
        renderer_connection_allowed=True,
        viewer_connection_allowed=True,
        content_release_workflow_allowed=True,
        blocking_reasons=(),
        gate_status=SourceObjectPreviewRendererReleaseGateStatus.READY,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_renderer_release_gate_hash(draft)})


def _release_receipt(*, tenant_id: str) -> SourceObjectPreviewContentReleaseReceipt:
    draft = SourceObjectPreviewContentReleaseReceipt(
        tenant_id=tenant_id,
        source_object_id="doc-pg-release",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        source_manifest_hash="sha256:" + ("1" * 64),
        source_content_hash="sha256:" + ("2" * 64),
        source_acl_version=1,
        source_mime_type="text/plain",
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        preview_decision_evidence_hash="sha256:" + ("3" * 64),
        renderer_sandbox_evidence_hash="sha256:" + ("4" * 64),
        renderer_release_gate_evidence_hash="sha256:" + ("5" * 64),
        human_confirmation_reference="approval:pg-release",
        confirmation_statement_hash=stable_hash(CONTENT_RELEASE_CONFIRMATION_STATEMENT),
        release_request_reference="preview-release:pg-release",
        command_hash="sha256:" + ("6" * 64),
        reason_hash="sha256:" + ("7" * 64),
        sanitized_content_hash="sha256:" + ("8" * 64),
        sanitized_content_byte_length=42,
        requested_by="user-pg-release",
        released_at_utc=datetime.now(UTC),
        audit_event_id="audit:pg-release",
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_content_release_receipt_hash(draft)})
