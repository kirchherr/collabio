import os
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.source_object_preview_renderer import (
    RENDERER_SANDBOX_BOUNDARIES,
    RENDERER_SANDBOX_WORKER_PROFILE_ID,
    RENDERER_SANDBOX_WORKER_QUEUE_ID,
    PgSourceObjectPreviewRendererEvidenceStore,
    build_source_object_preview_renderer_run_evidence,
    build_source_object_preview_renderer_worker_idempotency_key_hash,
)
from suite.storage.source_objects import SourceObjectType


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def test_pg_source_object_preview_renderer_store_is_tenant_scoped_append_only_and_metadata_only(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-preview-renderer-{suffix}"
    worker_idempotency_key_hash = build_source_object_preview_renderer_worker_idempotency_key_hash(
        tenant_id=tenant_id,
        source_object_id=f"doc-preview-renderer-{suffix}",
        source_version_id="v1",
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        parser_sanitizer_evidence_ref=f"parser-sanitizer:preview-renderer-{suffix}",
        backup_coverage_evidence_ref=f"backup:preview-renderer-{suffix}",
        restore_evidence_ref=f"restore-drill:preview-renderer-{suffix}",
    )
    evidence = build_source_object_preview_renderer_run_evidence(
        tenant_id=tenant_id,
        source_object_id=f"doc-preview-renderer-{suffix}",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        source_manifest_hash="sha256:" + "1" * 64,
        source_content_hash="sha256:" + "2" * 64,
        source_acl_version=3,
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        gate_id="office.document.preview.gate.v1",
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        worker_profile_id=RENDERER_SANDBOX_WORKER_PROFILE_ID,
        worker_queue_id=RENDERER_SANDBOX_WORKER_QUEUE_ID,
        worker_job_id=f"preview-renderer-job:{worker_idempotency_key_hash}",
        worker_idempotency_key_hash=worker_idempotency_key_hash,
        worker_queue_binding_ref=f"worker-queue:{RENDERER_SANDBOX_WORKER_QUEUE_ID}:{worker_idempotency_key_hash}",
        parser_sanitizer_evidence_ref=f"parser-sanitizer:preview-renderer-{suffix}",
        backup_coverage_evidence_ref=f"backup:preview-renderer-{suffix}",
        restore_evidence_ref=f"restore-drill:preview-renderer-{suffix}",
        sandbox_boundaries=RENDERER_SANDBOX_BOUNDARIES,
        source_detail_audit_event_id=f"detail-audit-{suffix}",
        audit_event_id=f"renderer-audit-{suffix}",
        requested_by=f"user-preview-renderer-{suffix}",
        reason_hash="sha256:" + "3" * 64,
    )
    store = PgSourceObjectPreviewRendererEvidenceStore(database_dsn=live_database.app_dsn)

    persisted = store.append(evidence)

    assert persisted == evidence
    assert store.get(tenant_id=tenant_id, evidence_hash=evidence.renderer_sandbox_evidence_hash) == evidence
    assert store.list_evidence(tenant_id=tenant_id) == (evidence,)
    assert store.list_evidence(tenant_id=f"tenant-other-{suffix}") == ()
    assert evidence.renderer_sandbox_evidence_ref == f"renderer-sandbox:{evidence.renderer_sandbox_evidence_hash}"
    assert evidence.worker_queue_id == RENDERER_SANDBOX_WORKER_QUEUE_ID
    assert evidence.worker_queue_binding_ref.endswith(evidence.worker_idempotency_key_hash)
    assert evidence.rendering_allowed is False
    assert evidence.content_rendered is False
    assert evidence.content_included is False
    assert "source content" not in evidence.model_dump_json()
    assert "mail body" not in evidence.model_dump_json()
    assert "prompt_text" not in evidence.model_dump_json()
    assert "output_text" not in evidence.model_dump_json()

    with pytest.raises(KeyError, match="not found"):
        store.get(tenant_id=f"tenant-other-{suffix}", evidence_hash=evidence.renderer_sandbox_evidence_hash)
    with pytest.raises(ValueError, match="already exists"):
        store.append(evidence)

    with psycopg.connect(live_database.app_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            connection.execute(
                """
                UPDATE collabio.source_object_preview_renderer_evidence
                SET content_rendered = true
                WHERE tenant_id = %s
                  AND renderer_sandbox_evidence_hash = %s
                """,
                (tenant_id, evidence.renderer_sandbox_evidence_hash),
            )
