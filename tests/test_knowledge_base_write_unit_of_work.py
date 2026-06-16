import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    InMemoryKnowledgeBaseWriteApprovalLedger,
    KnowledgeBaseArticleService,
    KnowledgeBaseEvidenceRefreshPreviewCommand,
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteApprovalTransitionCommand,
    KnowledgeBaseWriteExecutionCommand,
    KnowledgeBaseWriteExecutionSkeletonCommand,
    KnowledgeBaseWriteOperation,
    PgKnowledgeBaseArticleRepository,
)
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.source_object_storage import InMemorySourceObjectContentStore, PgSourceObjectRepository
from suite.storage.source_objects import (
    LegalHoldState,
    PgSourceObjectWriteReceiptStore,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


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


def source_record_for_unit_of_work(
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
        created_at_utc="2026-06-12T12:00:00Z",
        updated_at_utc="2026-06-12T12:00:00Z",
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


def write_command_for_unit_of_work(
    *,
    source_record: SourceObjectRecord,
    article_object_id: str,
    article_key: str,
    title: str,
) -> KnowledgeBaseWriteApprovalCommand:
    metadata = source_record.metadata
    return KnowledgeBaseWriteApprovalCommand(
        approval_reference=f"approval:{metadata.object_id}",
        reason="prepare coordinated knowledge base unit-of-work create",
        operation=KnowledgeBaseWriteOperation.CREATE,
        article_object_id=article_object_id,
        article_key=article_key,
        title=title,
        proposed_version_object_id=metadata.object_id,
        proposed_version_label=metadata.version_id,
        proposed_source_object_id=metadata.object_id,
        proposed_source_version_id=metadata.version_id,
        proposed_source_object_type=metadata.object_type,
        proposed_source_manifest_hash=metadata.manifest_hash,
        proposed_content_hash=metadata.content_hash,
        proposed_acl_version=metadata.acl_version,
        data_classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state.value,
        source_system=metadata.source_system,
    )


def set_tenant(connection: psycopg.Connection[object], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def test_pg_knowledge_base_write_unit_of_work_commits_receipt_source_and_article_metadata(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-kb-uow-{suffix}"
    article_object_id = f"kb-article-uow-{suffix}"
    source_record = source_record_for_unit_of_work(
        tenant_id=tenant_id,
        object_id=f"kb-article-version-uow-{suffix}-v1",
        version_id="v1",
        title="Unit of Work Runbook v1",
        text="Unit-of-work source content must stay outside audit and metadata tables.",
    )
    source_repository = PgSourceObjectRepository(
        database_dsn=live_database.app_dsn,
        content_store=InMemorySourceObjectContentStore(stored_at_clock=lambda: "2026-06-12T12:01:00Z"),
        retention_policy=load_retention_manifest_policy(RETENTION_POLICY_PATH),
        storage_policy=load_storage_adapter_policy(STORAGE_POLICY_PATH),
    )
    service = KnowledgeBaseArticleService(
        repository=PgKnowledgeBaseArticleRepository(database_dsn=live_database.app_dsn),
        source_repository=source_repository,
        audit_logger=InMemoryAuditLogger(),
        write_approval_ledger=InMemoryKnowledgeBaseWriteApprovalLedger(),
        source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn),
    )
    user_context = UserContext(
        tenant_id=tenant_id,
        user_id=f"tenant-admin-{tenant_id}",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )
    write_command = write_command_for_unit_of_work(
        source_record=source_record,
        article_object_id=article_object_id,
        article_key=f"KB-UOW-{suffix[:8]}",
        title="Unit of Work Runbook",
    )

    dry_run = service.dry_run_write_approval(command=write_command, user_context=user_context)
    approval = service.approve_write_approval(
        command=KnowledgeBaseWriteApprovalTransitionCommand(
            dry_run_write_approval_evidence_hash=dry_run.write_approval_evidence_hash,
            approval_reference=f"approval:kb-uow-approved-{suffix}",
            reason="approve coordinated knowledge base unit-of-work create",
        ),
        user_context=user_context,
    )
    preview = service.preview_write_evidence_refresh(
        command=KnowledgeBaseEvidenceRefreshPreviewCommand(
            approved_write_approval_evidence_hash=approval.approved_write_approval_evidence_hash,
            preview_reference=f"preview:kb-uow-{suffix}",
            reason="preview unit-of-work restore evidence refresh",
        ),
        user_context=user_context,
    )
    guard_decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=approval.approved_write_approval_evidence_hash,
        proposed_source_record=source_record,
    )
    skeleton = service.prepare_write_execution_skeleton(
        command=KnowledgeBaseWriteExecutionSkeletonCommand(
            approved_write_approval_evidence_hash=approval.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_reference=f"execution:kb-uow-{suffix}",
            human_confirmation_reference=f"human-confirmation:kb-uow-{suffix}",
            reason="prepare unit-of-work write execution",
        ),
        user_context=user_context,
    )

    response = service.execute_write(
        command=KnowledgeBaseWriteExecutionCommand(
            approved_write_approval_evidence_hash=approval.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_skeleton_command_hash=skeleton.execution_command_hash,
            execution_plan_hash=skeleton.execution_plan_hash,
            execution_reference=f"execution:kb-uow-{suffix}",
            human_confirmation_reference=f"human-confirmation:kb-uow-{suffix}",
            proposed_source_record=source_record,
            reason="execute coordinated knowledge base unit-of-work create",
        ),
        user_context=user_context,
    )

    assert response.write_unit_of_work_committed is True
    assert response.write_unit_of_work_contract == "knowledge_base_write_unit_of_work.v1"
    assert response.source_object_write_receipt_hash.startswith("sha256:")
    assert response.current_version_object_id == source_record.metadata.object_id
    assert response.refreshed_source_version_evidence_hash == approval.proposed_source_version_evidence_hash
    assert (
        source_repository.get(
            tenant_id=tenant_id,
            object_id=source_record.metadata.object_id,
            version_id=source_record.metadata.version_id,
        )
        == source_record
    )

    with psycopg.connect(live_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        source_metadata = connection.execute(
            """
            SELECT source_object_write_receipt_hash, storage_manifest_hash
            FROM collabio.source_object_metadata
            WHERE tenant_id = %s
              AND object_id = %s
              AND version_id = %s
            """,
            (tenant_id, source_record.metadata.object_id, source_record.metadata.version_id),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_write_receipts WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        article_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.articles WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        article_version_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.article_versions WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        source_evidence_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.source_version_evidence WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        restore_evidence_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.restore_evidence WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()

    assert source_metadata is not None
    assert source_metadata[0] == response.source_object_write_receipt_hash
    assert str(source_metadata[1]).startswith("sha256:")
    assert receipt_count is not None and int(receipt_count[0]) == 1
    assert article_count is not None and int(article_count[0]) == 1
    assert article_version_count is not None and int(article_version_count[0]) == 1
    assert source_evidence_count is not None and int(source_evidence_count[0]) == 1
    assert restore_evidence_count is not None and int(restore_evidence_count[0]) == 1
