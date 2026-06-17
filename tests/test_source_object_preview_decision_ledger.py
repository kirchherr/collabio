import os
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.source_object_preview_decisions import (
    PgSourceObjectPreviewDecisionLedger,
    SourceObjectPreviewDecisionStatus,
    build_source_object_preview_decision_evidence,
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


def test_pg_source_object_preview_decision_ledger_is_tenant_scoped_append_only_and_metadata_only(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-preview-ledger-{suffix}"
    evidence = build_source_object_preview_decision_evidence(
        tenant_id=tenant_id,
        source_object_id=f"doc-preview-{suffix}",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        tenant_preview_policy_enabled=True,
        required_content_release_evidence=(
            "tenant_preview_policy_enabled",
            "source_object_acl_checked",
            "source_detail_audit_event",
            "parser_sanitizer_evidence",
            "human_content_release_confirmation",
            "renderer_sandbox_worker_evidence",
            "backup_coverage_evidence",
            "restore_drill_evidence",
        ),
        provided_evidence=(
            "tenant_preview_policy_enabled",
            "source_object_acl_checked",
            "source_detail_audit_event",
            "parser_sanitizer_evidence",
            "human_content_release_confirmation",
            "renderer_sandbox_worker_evidence",
            "backup_coverage_evidence",
            "restore_drill_evidence",
        ),
        provided_evidence_refs=(
            f"tenant_policy:{tenant_id}:content_preview_enabled",
            f"acl:source_object:doc-preview-{suffix}:v1",
            f"audit:detail-{suffix}",
            f"parser-sanitizer:preview-{suffix}",
            f"approval:preview-{suffix}",
            f"renderer-sandbox:worker-{suffix}",
            f"backup:preview-{suffix}",
            f"restore-drill:preview-{suffix}",
        ),
        missing_evidence=(),
        blocking_reasons=(
            "content_release_requires_policy_acl_audit_and_sanitizer_evidence",
            "content_preview_skeleton_blocks_release_until_renderer_operational",
        ),
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        renderer_sandbox_evidence_ref=f"renderer-sandbox:worker-{suffix}",
        backup_coverage_evidence_ref=f"backup:preview-{suffix}",
        restore_evidence_ref=f"restore-drill:preview-{suffix}",
        human_confirmation_reference=f"approval:preview-{suffix}",
        renderer_sandbox_evidence_verified=True,
        backup_coverage_evidence_verified=True,
        restore_evidence_verified=True,
        human_confirmation_verified=True,
        content_release_evidence_complete=True,
        source_detail_audit_event_id=f"detail-audit-{suffix}",
        audit_event_id=f"decision-audit-{suffix}",
        requested_by=f"user-preview-{suffix}",
        reason_hash="sha256:" + "1" * 64,
    )
    ledger = PgSourceObjectPreviewDecisionLedger(database_dsn=live_database.app_dsn)

    persisted = ledger.append(evidence)

    assert persisted == evidence
    assert ledger.get(tenant_id=tenant_id, evidence_hash=evidence.evidence_hash) == evidence
    assert ledger.list_decisions(tenant_id=tenant_id) == (evidence,)
    assert ledger.list_decisions(tenant_id=f"tenant-other-{suffix}") == ()
    with pytest.raises(KeyError, match="not found"):
        ledger.get(tenant_id=f"tenant-other-{suffix}", evidence_hash=evidence.evidence_hash)
    with pytest.raises(ValueError, match="already exists"):
        ledger.append(evidence)

    evidence_json = evidence.model_dump_json()
    assert evidence.decision_status == SourceObjectPreviewDecisionStatus.BLOCKED
    assert evidence.content_release_allowed is False
    assert evidence.content_included is False
    assert "source content" not in evidence_json
    assert "mail body" not in evidence_json
    assert "prompt_text" not in evidence_json
    assert "output_text" not in evidence_json

    with psycopg.connect(live_database.app_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            connection.execute(
                """
                UPDATE collabio.source_object_preview_decision_evidence
                SET content_release_allowed = true
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, evidence.evidence_hash),
            )
