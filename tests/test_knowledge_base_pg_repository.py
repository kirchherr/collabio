import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import stable_hash
from suite.ai_control_plane.models import DataClass
from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    KnowledgeBaseArticleRecord,
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteApprovalEvidence,
    KnowledgeBaseWriteOperation,
    PgKnowledgeBaseArticleRepository,
    build_knowledge_base_restore_evidence,
    build_source_version_evidence_for_source_record,
    build_source_version_evidence_stub,
    build_write_approval_command_hash,
    build_write_approval_evidence,
    build_write_approval_transition_evidence,
)
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
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


def source_record_for_pg_write(
    *,
    tenant_id: str,
    object_id: str,
    version_id: str,
    title: str,
    text: str,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.WIKI,
        version_id=version_id,
        title=title,
        owner_principal_id=f"user-{tenant_id}",
        created_by=f"tenant-admin-{tenant_id}",
        created_at_utc="2026-06-12T09:00:00Z",
        updated_at_utc="2026-06-12T09:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{tenant_id}/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=f"audit:{object_id}",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:" + "a" * 64,
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def approved_evidence_for_command(
    *,
    tenant_id: str,
    command: KnowledgeBaseWriteApprovalCommand,
    proposed_source_record: SourceObjectRecord,
    current_articles: tuple[KnowledgeBaseArticleRecord, ...],
) -> KnowledgeBaseWriteApprovalEvidence:
    current_source_evidences = tuple(build_source_version_evidence_stub(article) for article in current_articles)
    current_restore_evidence = build_knowledge_base_restore_evidence(
        tenant_id=tenant_id,
        articles=current_articles,
        source_evidences=current_source_evidences,
        restore_drill_report_hash=stable_hash(f"{tenant_id}:knowledge_base_content:restore-drill"),
        audit_chain_ref="audit:knowledge-base-restore-evidence",
    )
    proposed_source_evidence = build_source_version_evidence_for_source_record(
        tenant_id=tenant_id,
        article_object_id=command.article_object_id,
        article_version_object_id=command.proposed_version_object_id,
        source_record=proposed_source_record,
    )
    dry_run_evidence = build_write_approval_evidence(
        tenant_id=tenant_id,
        command=command,
        command_hash=build_write_approval_command_hash(command),
        proposed_source_version_evidence_hash=proposed_source_evidence.evidence_hash,
        current_restore_evidence_hash=current_restore_evidence.evidence_hash,
        requested_by=f"tenant-admin-{tenant_id}",
        audit_event_id=f"audit-event-{uuid4().hex}",
        audit_chain_ref=f"audit:{uuid4().hex}",
    )
    return build_write_approval_transition_evidence(
        source_evidence=dry_run_evidence,
        approval_reference=f"approval:pg-write-approved-{uuid4().hex}",
        requested_by=f"tenant-admin-{tenant_id}",
        audit_event_id=f"audit-event-approved-{uuid4().hex}",
        audit_chain_ref=f"audit:approved-{uuid4().hex}",
    )


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def table_count(live_database: LiveDatabase, *, tenant_id: str, table: str) -> int:
    with psycopg.connect(live_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        row = connection.execute(
            f"SELECT COUNT(*) FROM knowledge_base.{table} WHERE tenant_id = %s",
            (tenant_id,),
        )
        result = row.fetchone()
    assert result is not None
    return int(result[0])


def test_pg_knowledge_base_article_repository_commits_create_edit_and_evidence_atomically(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-kb-pg-{suffix}"
    repository = PgKnowledgeBaseArticleRepository(database_dsn=live_database.app_dsn)
    article_object_id = f"kb-article-{suffix}"
    article_key = f"KB-{suffix[:8]}"

    create_source = source_record_for_pg_write(
        tenant_id=tenant_id,
        object_id=f"kb-article-version-{suffix}-v1",
        version_id="v1",
        title="Postgres Runbook v1",
        text="Postgres runbook source content v1.",
    )
    create_command = KnowledgeBaseWriteApprovalCommand(
        approval_reference=f"approval:kb-pg-create-{suffix}",
        reason="prepare governed postgres knowledge base create",
        operation=KnowledgeBaseWriteOperation.CREATE,
        article_object_id=article_object_id,
        article_key=article_key,
        title="Postgres Runbook",
        proposed_version_object_id=create_source.metadata.object_id,
        proposed_version_label=create_source.metadata.version_id,
        proposed_source_object_id=create_source.metadata.object_id,
        proposed_source_version_id=create_source.metadata.version_id,
        proposed_source_manifest_hash=create_source.metadata.manifest_hash,
        proposed_content_hash=create_source.metadata.content_hash,
        proposed_acl_version=create_source.metadata.acl_version,
        source_system=create_source.metadata.source_system,
    )
    create_evidence = approved_evidence_for_command(
        tenant_id=tenant_id,
        command=create_command,
        proposed_source_record=create_source,
        current_articles=(),
    )

    created_article = repository.apply_write(
        tenant_id=tenant_id,
        evidence=create_evidence,
        source_record=create_source,
        audit_chain_ref=f"audit:pg-create-{suffix}",
    )

    assert created_article.object_id == article_object_id
    assert created_article.article_key == article_key
    assert created_article.current_version_label == "v1"
    assert created_article.current_source_manifest_hash == create_source.metadata.manifest_hash
    assert len(repository.list_articles(tenant_id=tenant_id)) == 1
    assert table_count(live_database, tenant_id=tenant_id, table="articles") == 1
    assert table_count(live_database, tenant_id=tenant_id, table="article_versions") == 1
    assert table_count(live_database, tenant_id=tenant_id, table="source_version_evidence") == 1
    assert table_count(live_database, tenant_id=tenant_id, table="restore_evidence") == 1

    edit_source = source_record_for_pg_write(
        tenant_id=tenant_id,
        object_id=f"kb-article-version-{suffix}-v2",
        version_id="v2",
        title="Postgres Runbook v2",
        text="Postgres runbook source content v2.",
    )
    edit_command = KnowledgeBaseWriteApprovalCommand(
        approval_reference=f"approval:kb-pg-edit-{suffix}",
        reason="prepare governed postgres knowledge base edit",
        operation=KnowledgeBaseWriteOperation.EDIT,
        article_object_id=article_object_id,
        article_key=article_key,
        title="Postgres Runbook",
        proposed_version_object_id=edit_source.metadata.object_id,
        proposed_version_label=edit_source.metadata.version_id,
        proposed_source_object_id=edit_source.metadata.object_id,
        proposed_source_version_id=edit_source.metadata.version_id,
        proposed_source_manifest_hash=edit_source.metadata.manifest_hash,
        proposed_content_hash=edit_source.metadata.content_hash,
        proposed_acl_version=edit_source.metadata.acl_version,
        expected_current_version_object_id=create_source.metadata.object_id,
        source_system=edit_source.metadata.source_system,
    )
    edit_evidence = approved_evidence_for_command(
        tenant_id=tenant_id,
        command=edit_command,
        proposed_source_record=edit_source,
        current_articles=tuple(repository.list_articles(tenant_id=tenant_id)),
    )

    edited_article = repository.apply_write(
        tenant_id=tenant_id,
        evidence=edit_evidence,
        source_record=edit_source,
        audit_chain_ref=f"audit:pg-edit-{suffix}",
    )

    assert edited_article.object_id == article_object_id
    assert edited_article.current_version_label == "v2"
    assert edited_article.current_source_manifest_hash == edit_source.metadata.manifest_hash
    records = repository.list_articles(tenant_id=tenant_id)
    assert len(records) == 1
    assert records[0].current_version_object_id == edit_source.metadata.object_id
    assert table_count(live_database, tenant_id=tenant_id, table="articles") == 1
    assert table_count(live_database, tenant_id=tenant_id, table="article_versions") == 2
    assert table_count(live_database, tenant_id=tenant_id, table="source_version_evidence") == 2
    assert table_count(live_database, tenant_id=tenant_id, table="restore_evidence") == 2
    assert repository.list_articles(tenant_id=f"tenant-other-{suffix}") == ()
