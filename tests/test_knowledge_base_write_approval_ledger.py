import os
from dataclasses import dataclass
from uuid import uuid4

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteOperation,
    PgKnowledgeBaseWriteApprovalLedger,
    build_write_approval_command_hash,
    build_write_approval_evidence,
)


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


def test_pg_knowledge_base_write_approval_ledger_appends_metadata_only_evidence(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-kb-ledger-{suffix}"
    command = KnowledgeBaseWriteApprovalCommand(
        approval_reference=f"approval:kb-ledger-{suffix}",
        reason="persist metadata-only write approval dry-run evidence",
        operation=KnowledgeBaseWriteOperation.CREATE,
        article_object_id=f"kb-article-{suffix}",
        article_key=f"KB-{suffix[:8]}",
        title="Ledger Persistence Check",
        proposed_version_object_id=f"kb-article-version-{suffix}",
        proposed_version_label="v1",
        proposed_source_object_id=f"kb-article-version-{suffix}",
        proposed_source_version_id="v1",
        proposed_source_manifest_hash="sha256:" + "1" * 64,
        proposed_content_hash="sha256:" + "2" * 64,
        proposed_acl_version=1,
    )
    command_hash = build_write_approval_command_hash(command)
    evidence = build_write_approval_evidence(
        tenant_id=tenant_id,
        command=command,
        command_hash=command_hash,
        proposed_source_version_evidence_hash="sha256:" + "3" * 64,
        current_restore_evidence_hash="sha256:" + "4" * 64,
        requested_by=f"tenant-admin-{suffix}",
        audit_event_id=f"audit-event-{suffix}",
        audit_chain_ref=f"audit:{suffix}",
    )
    ledger = PgKnowledgeBaseWriteApprovalLedger(database_dsn=live_database.app_dsn)

    persisted = ledger.append(evidence)

    assert persisted == evidence
    assert ledger.get(tenant_id=tenant_id, evidence_hash=evidence.evidence_hash) == evidence
    assert ledger.list_evidence(tenant_id="tenant-other") == ()
    with pytest.raises(KeyError, match="not found"):
        ledger.get(tenant_id="tenant-other", evidence_hash=evidence.evidence_hash)
    rows = ledger.list_evidence(tenant_id=tenant_id)
    assert rows == (evidence,)
    row_json = rows[0].model_dump_json()
    assert "article_body" not in row_json
    assert "source content" not in row_json
    assert "prompt_text" not in row_json
    assert "output_text" not in row_json
    with pytest.raises(ValueError, match="already exists"):
        ledger.append(evidence)
