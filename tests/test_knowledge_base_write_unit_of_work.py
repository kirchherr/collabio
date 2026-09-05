import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    InMemoryKnowledgeBaseWriteApprovalLedger,
    KnowledgeBaseArticleRecord,
    KnowledgeBaseArticleService,
    KnowledgeBaseEvidenceRefreshPreviewCommand,
    KnowledgeBaseProductionWriteDeploymentGateStatus,
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteApprovalEvidence,
    KnowledgeBaseWriteApprovalTransitionCommand,
    KnowledgeBaseWriteExecutionCommand,
    KnowledgeBaseWriteExecutionSkeletonCommand,
    KnowledgeBaseWriteOperation,
    PgKnowledgeBaseArticleRepository,
    PostgresKnowledgeBaseWriteUnitOfWork,
    build_knowledge_base_production_write_deployment_gate,
    build_knowledge_base_restore_evidence,
    build_production_write_deployment_gate_hash,
    build_source_version_evidence_for_source_record,
    build_write_approval_command_hash,
    build_write_approval_evidence,
    build_write_approval_transition_evidence,
)
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleProviderProfileEvidence,
    S3CompatibleProviderProfileStatus,
    build_s3_compatible_provider_profile_evidence_hash,
)
from suite.storage.source_object_storage import (
    InMemorySourceObjectContentStore,
    PgSourceObjectRepository,
    SourceObjectContentReconciliationAction,
    SourceObjectContentReconciliationWorker,
    SourceObjectContentRecoveryStatus,
)
from suite.storage.source_objects import (
    LegalHoldState,
    PgSourceObjectWriteReceiptStore,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
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


def provider_profile_evidence_for_unit_of_work(
    *,
    ready: bool = True,
    blocking_reasons: tuple[str, ...] = (),
) -> S3CompatibleProviderProfileEvidence:
    draft = S3CompatibleProviderProfileEvidence(
        provider_profile_id="minio-dev-object-lock",
        checked_at_utc="2026-06-12T12:00:20Z",
        storage_policy_hash=sha256_bytes(b"storage-adapter-policy-v1"),
        bucket_profile_count=4,
        object_lock_bucket_count=2,
        bucket_capability_hashes=(sha256_bytes(b"working-objects"), sha256_bytes(b"business-records")),
        versioning_verified=True,
        object_lock_verified=ready,
        legal_hold_verified=ready,
        blocking_reasons=blocking_reasons,
        provider_profile_ready=ready,
        profile_status=S3CompatibleProviderProfileStatus.READY if ready else S3CompatibleProviderProfileStatus.BLOCKED,
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_s3_compatible_provider_profile_evidence_hash(draft)})


class FailingTransactionalKnowledgeBaseArticleRepository:
    def apply_write_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        source_record: SourceObjectRecord,
        audit_chain_ref: str,
    ) -> KnowledgeBaseArticleRecord:
        raise RuntimeError("forced article metadata failure")


def approved_evidence_for_empty_unit_of_work_create(
    *,
    tenant_id: str,
    command: KnowledgeBaseWriteApprovalCommand,
    source_record: SourceObjectRecord,
) -> KnowledgeBaseWriteApprovalEvidence:
    proposed_source_evidence = build_source_version_evidence_for_source_record(
        tenant_id=tenant_id,
        article_object_id=command.article_object_id,
        article_version_object_id=command.proposed_version_object_id,
        source_record=source_record,
    )
    current_restore_evidence = build_knowledge_base_restore_evidence(
        tenant_id=tenant_id,
        articles=(),
        source_evidences=(),
        restore_drill_report_hash=stable_hash(f"{tenant_id}:knowledge_base_content:restore-drill"),
        audit_chain_ref="audit:knowledge-base-restore-evidence",
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
        approval_reference=f"approval:kb-uow-approved-{uuid4().hex}",
        requested_by=f"tenant-admin-{tenant_id}",
        audit_event_id=f"audit-event-approved-{uuid4().hex}",
        audit_chain_ref=f"audit:approved-{uuid4().hex}",
    )


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
    clean_recovery_evidence = source_repository.build_content_recovery_evidence(
        tenant_id=tenant_id,
        restore_drill_report_hash="sha256:" + "d" * 64,
        checked_at_utc="2026-06-12T12:00:30Z",
    )
    assert clean_recovery_evidence.api_wiring_allowed is True
    provider_profile_evidence = provider_profile_evidence_for_unit_of_work()
    production_gate_evidence = build_knowledge_base_production_write_deployment_gate(
        tenant_id=tenant_id,
        source_content_recovery_evidence=clean_recovery_evidence,
        provider_profile_evidence=provider_profile_evidence,
        restore_drill_report_hash=clean_recovery_evidence.restore_drill_report_hash,
    )
    assert production_gate_evidence.gate_status == KnowledgeBaseProductionWriteDeploymentGateStatus.READY
    assert production_gate_evidence.api_wiring_allowed is True
    assert production_gate_evidence.evidence_hash == build_production_write_deployment_gate_hash(
        production_gate_evidence
    )
    blocked_provider_gate = build_knowledge_base_production_write_deployment_gate(
        tenant_id=tenant_id,
        source_content_recovery_evidence=clean_recovery_evidence,
        provider_profile_evidence=provider_profile_evidence_for_unit_of_work(
            ready=False,
            blocking_reasons=("business-records:object_lock_required",),
        ),
        restore_drill_report_hash=clean_recovery_evidence.restore_drill_report_hash,
    )
    assert blocked_provider_gate.gate_status == KnowledgeBaseProductionWriteDeploymentGateStatus.BLOCKED
    assert "provider_profile_not_ready" in blocked_provider_gate.blocking_reasons
    restore_drift_gate = build_knowledge_base_production_write_deployment_gate(
        tenant_id=tenant_id,
        source_content_recovery_evidence=clean_recovery_evidence,
        provider_profile_evidence=provider_profile_evidence,
        restore_drill_report_hash="sha256:" + "e" * 64,
    )
    assert restore_drift_gate.gate_status == KnowledgeBaseProductionWriteDeploymentGateStatus.BLOCKED
    assert "restore_drill_evidence_not_bound" in restore_drift_gate.blocking_reasons
    with pytest.raises(ValueError, match="production write deployment gate does not allow API wiring"):
        PostgresKnowledgeBaseWriteUnitOfWork(
            database_dsn=live_database.app_dsn,
            article_repository=PgKnowledgeBaseArticleRepository(database_dsn=live_database.app_dsn),
            source_repository=source_repository,
            source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn),
            source_content_recovery_evidence=clean_recovery_evidence,
            production_write_deployment_gate_evidence=blocked_provider_gate,
            require_source_content_recovery_gate=True,
        )
    article_repository = PgKnowledgeBaseArticleRepository(database_dsn=live_database.app_dsn)
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn)
    audit_logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=article_repository,
        source_repository=source_repository,
        audit_logger=audit_logger,
        write_approval_ledger=InMemoryKnowledgeBaseWriteApprovalLedger(),
        source_object_write_receipt_store=receipt_store,
        write_unit_of_work=PostgresKnowledgeBaseWriteUnitOfWork(
            database_dsn=live_database.app_dsn,
            article_repository=article_repository,
            source_repository=source_repository,
            source_object_write_receipt_store=receipt_store,
            source_content_recovery_evidence=clean_recovery_evidence,
            production_write_deployment_gate_evidence=production_gate_evidence,
            require_source_content_recovery_gate=True,
        ),
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
    assert response.write_unit_of_work_transaction_scope == "shared_postgres_metadata_transaction"
    assert response.source_content_recovery_required is False
    assert response.source_content_recovery_evidence_hash == clean_recovery_evidence.evidence_hash
    assert response.production_write_deployment_gate_evidence_hash == production_gate_evidence.evidence_hash
    assert "source_content_recovery_evidence_hash" in response.required_evidence
    assert "production_write_deployment_gate_evidence_hash" in response.required_evidence
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
    write_event = audit_logger.events[-1]
    assert write_event.event_type == "knowledge_base.write_approval.executed"
    assert write_event.metadata["write_unit_of_work_transaction_scope"] == "shared_postgres_metadata_transaction"
    assert write_event.metadata["source_content_recovery_required"] is False
    assert write_event.metadata["source_content_recovery_evidence_hash"] == clean_recovery_evidence.evidence_hash
    assert (
        write_event.metadata["production_write_deployment_gate_evidence_hash"] == production_gate_evidence.evidence_hash
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


def test_pg_knowledge_base_write_unit_of_work_rolls_back_metadata_on_article_failure(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-kb-uow-rollback-{suffix}"
    source_record = source_record_for_unit_of_work(
        tenant_id=tenant_id,
        object_id=f"kb-article-version-uow-rollback-{suffix}-v1",
        version_id="v1",
        title="Rollback Runbook v1",
        text="Rollback source content may be stored before metadata transaction failure.",
    )
    command = write_command_for_unit_of_work(
        source_record=source_record,
        article_object_id=f"kb-article-uow-rollback-{suffix}",
        article_key=f"KB-RB-{suffix[:8]}",
        title="Rollback Runbook",
    )
    approved_evidence = approved_evidence_for_empty_unit_of_work_create(
        tenant_id=tenant_id,
        command=command,
        source_record=source_record,
    )
    source_repository = PgSourceObjectRepository(
        database_dsn=live_database.app_dsn,
        content_store=InMemorySourceObjectContentStore(stored_at_clock=lambda: "2026-06-12T12:02:00Z"),
        retention_policy=load_retention_manifest_policy(RETENTION_POLICY_PATH),
        storage_policy=load_storage_adapter_policy(STORAGE_POLICY_PATH),
    )
    unit_of_work = PostgresKnowledgeBaseWriteUnitOfWork(
        database_dsn=live_database.app_dsn,
        article_repository=FailingTransactionalKnowledgeBaseArticleRepository(),
        source_repository=source_repository,
        source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn),
    )
    receipt = build_source_object_write_receipt(
        record=source_record,
        receipt_reference=f"receipt:execution:kb-uow-rollback-{suffix}",
        audit_chain_ref=f"audit:execution:kb-uow-rollback-{suffix}",
    )

    with pytest.raises(RuntimeError, match="forced article metadata failure"):
        unit_of_work.commit(
            tenant_id=tenant_id,
            evidence=approved_evidence,
            source_record=source_record,
            source_object_write_receipt=receipt,
            audit_chain_ref=f"audit:execution:kb-uow-rollback-{suffix}",
        )

    with pytest.raises(KeyError, match="not found"):
        source_repository.get(
            tenant_id=tenant_id,
            object_id=source_record.metadata.object_id,
            version_id=source_record.metadata.version_id,
        )
    recovery_evidence = source_repository.build_content_recovery_evidence(
        tenant_id=tenant_id,
        restore_drill_report_hash="sha256:" + "c" * 64,
        checked_at_utc="2026-06-12T12:03:00Z",
    )
    assert recovery_evidence.reconciliation_status == SourceObjectContentRecoveryStatus.RECONCILIATION_REQUIRED
    assert recovery_evidence.stored_object_count == 1
    assert recovery_evidence.storage_manifest_count == 0
    assert recovery_evidence.verified_content_count == 0
    assert recovery_evidence.orphaned_content_count == 1
    assert recovery_evidence.missing_content_count == 0
    assert recovery_evidence.source_content_recovery_required is True
    assert recovery_evidence.api_wiring_allowed is False
    reconciliation_run = SourceObjectContentReconciliationWorker(source_repository).run(
        tenant_id=tenant_id,
        restore_drill_report_hash="sha256:" + "c" * 64,
        checked_at_utc="2026-06-12T12:03:00Z",
    )
    assert reconciliation_run.evidence_hash == recovery_evidence.evidence_hash
    assert (
        reconciliation_run.recommended_action == SourceObjectContentReconciliationAction.MANUAL_RECONCILIATION_REQUIRED
    )
    assert reconciliation_run.api_wiring_allowed is False

    with pytest.raises(ValueError, match="does not allow API wiring"):
        PostgresKnowledgeBaseWriteUnitOfWork(
            database_dsn=live_database.app_dsn,
            article_repository=FailingTransactionalKnowledgeBaseArticleRepository(),
            source_repository=source_repository,
            source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn),
            source_content_recovery_evidence=recovery_evidence,
            require_source_content_recovery_gate=True,
        )

    with psycopg.connect(live_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_write_receipts WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        source_metadata_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_metadata WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        storage_manifest_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_storage_manifests WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        article_count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.articles WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()

    assert receipt_count is not None and int(receipt_count[0]) == 0
    assert source_metadata_count is not None and int(source_metadata_count[0]) == 0
    assert storage_manifest_count is not None and int(storage_manifest_count[0]) == 0
    assert article_count is not None and int(article_count[0]) == 0
