import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.knowledge_base import (
    KB_ARTICLE_OBJECT_TYPE,
    KB_ARTICLE_VERSION_OBJECT_TYPE,
    KB_ARTICLES_FEATURE_ID,
    KB_ARTICLES_WRITE_FEATURE_ID,
    KNOWLEDGE_BASE_MODULE_ID,
    InMemoryKnowledgeBaseArticleRepository,
    InMemoryKnowledgeBaseWriteApprovalLedger,
    KnowledgeBaseArticleRecord,
    KnowledgeBaseArticleService,
    KnowledgeBaseEvidenceRefreshPreviewCommand,
    KnowledgeBaseSourceObjectWriteGuard,
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteApprovalState,
    KnowledgeBaseWriteApprovalTransitionCommand,
    KnowledgeBaseWriteExecutionCommand,
    KnowledgeBaseWriteExecutionSkeletonCommand,
    KnowledgeBaseWriteOperation,
    build_knowledge_base_restore_evidence,
    build_knowledge_base_source_version_evidence,
    build_restore_evidence_hash,
    build_source_version_evidence_for_source_record,
    build_source_version_evidence_hash,
    build_write_approval_command_hash,
    build_write_approval_evidence,
    build_write_approval_evidence_hash,
    demo_knowledge_base_source_object_repository,
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


def knowledge_base_source_record_for_write(
    *,
    tenant_id: str = "tenant-demo",
    object_id: str = "kb-article-version-backup-runbook-v2-demo",
    version_id: str = "v2",
    title: str = "Backup Restore Runbook v2",
    text: str = "Backup restore runbook source content v2.",
    retention_policy_id: str = "rp-standard",
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.WIKI,
        version_id=version_id,
        title=title,
        owner_principal_id="user-demo",
        created_by="tenant-admin-demo",
        created_at_utc="2026-06-12T09:00:00Z",
        updated_at_utc="2026-06-12T09:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
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


def write_command_for_source_record(
    source_record: SourceObjectRecord,
    *,
    operation: KnowledgeBaseWriteOperation = KnowledgeBaseWriteOperation.EDIT,
    article_object_id: str = "kb-article-backup-runbook-demo",
    article_key: str = "KB-BACKUP-001",
    article_title: str = "Backup Restore Runbook",
    expected_current_version_object_id: str | None = "kb-article-version-backup-runbook-v1-demo",
) -> KnowledgeBaseWriteApprovalCommand:
    metadata = source_record.metadata
    return KnowledgeBaseWriteApprovalCommand(
        approval_reference=f"approval:{metadata.object_id}",
        reason="prepare guarded knowledge base source-object write",
        operation=operation,
        article_object_id=article_object_id,
        article_key=article_key,
        title=article_title,
        proposed_version_object_id=metadata.object_id,
        proposed_version_label=metadata.version_id,
        proposed_source_object_id=metadata.object_id,
        proposed_source_version_id=metadata.version_id,
        proposed_source_object_type=metadata.object_type,
        proposed_source_manifest_hash=metadata.manifest_hash,
        proposed_content_hash=metadata.content_hash,
        proposed_acl_version=metadata.acl_version,
        expected_current_version_object_id=expected_current_version_object_id,
        data_classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state.value,
        source_system=metadata.source_system,
    )


def test_knowledge_base_article_records_require_internal_compliance_metadata() -> None:
    article = InMemoryKnowledgeBaseArticleRepository.demo().list_articles(tenant_id="tenant-demo")[0]

    assert article.object_type == KB_ARTICLE_OBJECT_TYPE
    assert article.data_classification == DataClass.INTERNAL
    assert article.retention_policy_id == "rp-standard"
    assert article.legal_hold_state == "none"
    assert article.kms_key_ref.startswith("kms:")
    assert article.audit_chain_ref.startswith("audit:")
    assert article.source_system == "native"
    assert article.schema_version == "kb_article.v1"
    assert article.current_version_object_id.startswith("kb-article-version-")
    assert article.current_source_object_id == article.current_version_object_id
    assert article.current_source_version_id == "v1"
    assert article.current_source_manifest_hash.startswith("sha256:")
    assert article.current_content_hash.startswith("sha256:")
    assert article.current_acl_version >= 1


def test_knowledge_base_article_records_reject_wrong_object_type_classification_or_bodies() -> None:
    values = {
        "tenant_id": "tenant-demo",
        "object_id": "kb-article-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-12T08:00:00Z",
        "updated_at_utc": "2026-06-12T08:00:00Z",
        "kms_key_ref": "kms:tenant-demo:kb-article",
        "audit_chain_ref": "audit:kb-article-invalid",
        "article_key": "KB-INVALID",
        "title": "Invalid Article",
        "current_version_object_id": "kb-article-version-invalid-v1",
        "current_version_label": "v1",
        "published_at_utc": "2026-06-12T08:00:00Z",
    }

    with pytest.raises(ValidationError, match=r"kb\.article"):
        KnowledgeBaseArticleRecord.model_validate({**values, "object_type": "crm.account"})

    with pytest.raises(ValidationError, match="internal"):
        KnowledgeBaseArticleRecord.model_validate({**values, "data_classification": "personal"})

    with pytest.raises(ValidationError, match="Extra inputs"):
        KnowledgeBaseArticleRecord.model_validate({**values, "article_body": "must stay outside metadata slice"})


def test_knowledge_base_article_service_filters_by_tenant_and_article_version_acl() -> None:
    audit_logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "kb-article-backup-runbook-demo",
            "kb-article-version-backup-runbook-v1-demo",
            "kb-article-security-baseline-demo",
            "kb-article-version-security-baseline-v1-demo",
        },
    )

    response = service.list_articles(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == KNOWLEDGE_BASE_MODULE_ID
    assert response.feature_id == KB_ARTICLES_FEATURE_ID
    assert response.restore_evidence_hash.startswith("sha256:")
    assert len(response.source_version_evidence_hashes) == 2
    assert [article.title for article in response.articles] == ["Backup Restore Runbook", "Security Baseline"]
    assert {article.object_type for article in response.articles} == {KB_ARTICLE_OBJECT_TYPE}
    assert {article.data_classification for article in response.articles} == {DataClass.INTERNAL}
    assert all(article.access_checked for article in response.articles)
    assert all(article.source_version_access_checked for article in response.articles)
    assert {article.current_source_version_id for article in response.articles} == {"v1"}
    assert all(article.source_version_evidence_hash.startswith("sha256:") for article in response.articles)
    assert "Other Tenant Article" not in {article.title for article in response.articles}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "knowledge_base.article.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == [
        "kb-article-backup-runbook-demo",
        "kb-article-version-backup-runbook-v1-demo",
        "kb-article-security-baseline-demo",
        "kb-article-version-security-baseline-v1-demo",
    ]
    assert event.metadata == {
        "feature_id": KB_ARTICLES_FEATURE_ID,
        "module_id": KNOWLEDGE_BASE_MODULE_ID,
        "object_type": KB_ARTICLE_OBJECT_TYPE,
        "version_object_type": KB_ARTICLE_VERSION_OBJECT_TYPE,
        "candidate_count": 2,
        "continuity_domain": "knowledge_base_content",
        "result_contract": "metadata_only",
        "result_count": 2,
        "restore_evidence_hash": response.restore_evidence_hash,
        "source_version_evidence_hashes": response.source_version_evidence_hashes,
    }


def test_knowledge_base_article_service_filters_unreadable_versions() -> None:
    audit_logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "kb-article-backup-runbook-demo",
            "kb-article-version-backup-runbook-v1-demo",
            "kb-article-security-baseline-demo",
        },
    )

    response = service.list_articles(user_context=user_context)

    assert [article.object_id for article in response.articles] == ["kb-article-backup-runbook-demo"]
    event = audit_logger.events[-1]
    assert event.source_object_ids == [
        "kb-article-backup-runbook-demo",
        "kb-article-version-backup-runbook-v1-demo",
    ]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1


def test_knowledge_base_compliance_evidence_returns_metadata_for_admin_without_article_acl() -> None:
    audit_logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )

    response = service.read_compliance_evidence(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == KNOWLEDGE_BASE_MODULE_ID
    assert response.continuity_domain == "knowledge_base_content"
    assert len(response.source_version_evidence) == 2
    assert response.restore_evidence.source_version_evidence_count == 2
    assert response.restore_evidence.evidence_hash.startswith("sha256:")
    assert {evidence.source_version_id for evidence in response.source_version_evidence} == {"v1"}
    assert {evidence.data_classification for evidence in response.source_version_evidence} == {DataClass.INTERNAL}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.evidence.read"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == [
        "kb-article-backup-runbook-demo",
        "kb-article-version-backup-runbook-v1-demo",
        "kb-article-security-baseline-demo",
        "kb-article-version-security-baseline-v1-demo",
    ]
    assert event.metadata["surface"] == "compliance_api"
    assert event.metadata["result_contract"] == "metadata_only"
    assert event.metadata["restore_evidence_hash"] == response.restore_evidence.evidence_hash


def test_knowledge_base_write_approval_command_rejects_bodies_and_unsafe_contracts() -> None:
    source_record = demo_knowledge_base_source_object_repository().get(
        tenant_id="tenant-demo",
        object_id="kb-article-version-backup-runbook-v1-demo",
        version_id="v1",
    )
    values = {
        "approval_reference": "approval:kb-write-dry-run",
        "reason": "prepare controlled knowledge base edit",
        "operation": "edit",
        "article_object_id": "kb-article-backup-runbook-demo",
        "article_key": "KB-BACKUP-001",
        "title": "Backup Restore Runbook",
        "proposed_version_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_version_label": "v2",
        "proposed_source_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_source_version_id": "v2",
        "proposed_source_manifest_hash": source_record.metadata.manifest_hash,
        "proposed_content_hash": source_record.metadata.content_hash,
        "proposed_acl_version": 1,
        "expected_current_version_object_id": "kb-article-version-backup-runbook-v1-demo",
    }

    command = KnowledgeBaseWriteApprovalCommand.model_validate(values)

    assert command.operation == KnowledgeBaseWriteOperation.EDIT
    assert command.data_classification == DataClass.INTERNAL

    with pytest.raises(ValidationError, match="Extra inputs"):
        KnowledgeBaseWriteApprovalCommand.model_validate({**values, "article_body": "body is not allowed"})

    with pytest.raises(ValidationError, match="expected_current_version_object_id"):
        KnowledgeBaseWriteApprovalCommand.model_validate({**values, "expected_current_version_object_id": None})

    with pytest.raises(ValidationError, match="proposed source object"):
        KnowledgeBaseWriteApprovalCommand.model_validate(
            {**values, "proposed_source_object_id": "kb-article-version-other"}
        )


def test_knowledge_base_write_approval_dry_run_is_audit_only_and_blocks_persistence() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    source_record = demo_knowledge_base_source_object_repository().get(
        tenant_id="tenant-demo",
        object_id="kb-article-version-backup-runbook-v1-demo",
        version_id="v1",
    )
    command = KnowledgeBaseWriteApprovalCommand(
        approval_reference="approval:kb-write-dry-run",
        reason="prepare controlled knowledge base edit",
        operation=KnowledgeBaseWriteOperation.EDIT,
        article_object_id="kb-article-backup-runbook-demo",
        article_key="KB-BACKUP-001",
        title="Backup Restore Runbook",
        proposed_version_object_id="kb-article-version-backup-runbook-v2-demo",
        proposed_version_label="v2",
        proposed_source_object_id="kb-article-version-backup-runbook-v2-demo",
        proposed_source_version_id="v2",
        proposed_source_manifest_hash=source_record.metadata.manifest_hash,
        proposed_content_hash=source_record.metadata.content_hash,
        proposed_acl_version=1,
        expected_current_version_object_id="kb-article-version-backup-runbook-v1-demo",
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )

    response = service.dry_run_write_approval(command=command, user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == KNOWLEDGE_BASE_MODULE_ID
    assert response.feature_id == KB_ARTICLES_WRITE_FEATURE_ID
    assert response.operation == KnowledgeBaseWriteOperation.EDIT
    assert response.dry_run is True
    assert response.persistence_allowed is False
    assert response.rag_indexing_allowed is False
    assert response.source_authority_verified is False
    assert response.command_hash == build_write_approval_command_hash(command)
    assert response.proposed_source_version_evidence_hash.startswith("sha256:")
    assert response.current_restore_evidence_hash.startswith("sha256:")
    assert response.write_approval_evidence_hash.startswith("sha256:")
    assert service.repository.list_articles(tenant_id="tenant-demo")[0].current_version_label == "v1"
    ledger_evidences = write_approval_ledger.list_evidence(tenant_id="tenant-demo")
    assert len(ledger_evidences) == 1
    persisted_evidence = ledger_evidences[0]
    assert persisted_evidence.evidence_hash == response.write_approval_evidence_hash
    assert persisted_evidence.tenant_id == "tenant-demo"
    assert persisted_evidence.article_object_id == "kb-article-backup-runbook-demo"
    assert persisted_evidence.article_key == "KB-BACKUP-001"
    assert persisted_evidence.title == "Backup Restore Runbook"
    assert persisted_evidence.proposed_version_label == "v2"
    assert persisted_evidence.source_system == "native"
    assert persisted_evidence.approval_state == KnowledgeBaseWriteApprovalState.DRY_RUN
    assert persisted_evidence.persistence_allowed is False
    assert persisted_evidence.rag_indexing_allowed is False
    assert persisted_evidence.source_authority_verified is False
    assert "article_body" not in persisted_evidence.model_dump_json()
    assert write_approval_ledger.list_evidence(tenant_id="tenant-other") == ()
    with pytest.raises(ValueError, match="already exists"):
        write_approval_ledger.append(persisted_evidence)

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.dry_run"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["feature_id"] == KB_ARTICLES_WRITE_FEATURE_ID
    assert event.metadata["dry_run"] is True
    assert event.metadata["persistence_allowed"] is False
    assert event.metadata["command_hash"] == response.command_hash
    assert event.source_object_ids == [
        "kb-article-backup-runbook-demo",
        "kb-article-version-backup-runbook-v1-demo",
        "kb-article-version-backup-runbook-v2-demo",
    ]

    evidence = build_write_approval_evidence(
        tenant_id="tenant-demo",
        command=command,
        command_hash=response.command_hash,
        proposed_source_version_evidence_hash=response.proposed_source_version_evidence_hash,
        current_restore_evidence_hash=response.current_restore_evidence_hash,
        requested_by="tenant-admin-demo",
        audit_event_id=response.audit_event_id,
        audit_chain_ref=f"audit:{response.audit_event_id}",
    )
    assert evidence.approval_state == KnowledgeBaseWriteApprovalState.DRY_RUN
    assert evidence.persistence_allowed is False
    assert evidence.rag_indexing_allowed is False
    assert evidence.source_authority_verified is False
    assert evidence.evidence_hash == build_write_approval_evidence_hash(evidence)
    assert response.write_approval_evidence_hash == evidence.evidence_hash
    assert persisted_evidence == evidence


def test_knowledge_base_write_approval_transition_appends_approved_evidence_without_writes() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    write_command = write_command_for_source_record(proposed_source_record)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )
    dry_run_response = service.dry_run_write_approval(command=write_command, user_context=user_context)
    transition_command = KnowledgeBaseWriteApprovalTransitionCommand(
        dry_run_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
        approval_reference="approval:kb-write-approve",
        reason="human approved guarded knowledge base write",
    )

    transition_response = service.approve_write_approval(command=transition_command, user_context=user_context)

    assert transition_response.tenant_id == "tenant-demo"
    assert transition_response.approval_state == KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE
    assert transition_response.dry_run_write_approval_evidence_hash == dry_run_response.write_approval_evidence_hash
    assert transition_response.approved_write_approval_evidence_hash.startswith("sha256:")
    assert transition_response.approved_write_approval_evidence_hash != dry_run_response.write_approval_evidence_hash
    assert transition_response.persistence_allowed is True
    assert transition_response.rag_indexing_allowed is False
    assert transition_response.source_authority_verified is False
    assert "approved_write_approval_ledger_entry" in transition_response.required_evidence
    assert service.repository.list_articles(tenant_id="tenant-demo")[0].current_version_label == "v1"

    ledger_evidences = write_approval_ledger.list_evidence(tenant_id="tenant-demo")
    assert len(ledger_evidences) == 2
    dry_run_evidence = write_approval_ledger.get(
        tenant_id="tenant-demo",
        evidence_hash=dry_run_response.write_approval_evidence_hash,
    )
    approved_evidence = write_approval_ledger.get(
        tenant_id="tenant-demo",
        evidence_hash=transition_response.approved_write_approval_evidence_hash,
    )
    assert dry_run_evidence.approval_state == KnowledgeBaseWriteApprovalState.DRY_RUN
    assert dry_run_evidence.transition_source_evidence_hash is None
    assert approved_evidence.approval_state == KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE
    assert approved_evidence.transition_source_evidence_hash == dry_run_evidence.evidence_hash
    assert approved_evidence.approval_reference == "approval:kb-write-approve"
    assert approved_evidence.article_key == dry_run_evidence.article_key
    assert approved_evidence.title == dry_run_evidence.title
    assert approved_evidence.proposed_version_label == dry_run_evidence.proposed_version_label
    assert approved_evidence.source_system == dry_run_evidence.source_system
    assert approved_evidence.persistence_allowed is True
    assert approved_evidence.rag_indexing_allowed is False
    assert approved_evidence.source_authority_verified is False
    assert approved_evidence.evidence_hash == build_write_approval_evidence_hash(approved_evidence)
    assert "Backup restore runbook source content v2" not in approved_evidence.model_dump_json()

    event = audit_logger.events[-1]
    assert transition_response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.approved"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["approval_reference"] == "approval:kb-write-approve"
    assert event.metadata["dry_run_write_approval_evidence_hash"] == dry_run_evidence.evidence_hash
    assert event.metadata["persistence_allowed"] is True
    assert event.metadata["rag_indexing_allowed"] is False

    decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=approved_evidence.evidence_hash,
        proposed_source_record=proposed_source_record,
    )
    assert decision.allowed is True
    assert decision.persistence_allowed is True

    with pytest.raises(ValueError, match="already approved"):
        service.approve_write_approval(command=transition_command, user_context=user_context)


def test_knowledge_base_write_refresh_preview_projects_restore_evidence_without_writes() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    write_command = write_command_for_source_record(proposed_source_record)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )
    dry_run_response = service.dry_run_write_approval(command=write_command, user_context=user_context)
    dry_run_preview_command = KnowledgeBaseEvidenceRefreshPreviewCommand(
        approved_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
        preview_reference="preview:kb-refresh-should-block",
        reason="dry-run evidence is not enough for refresh preview",
    )
    with pytest.raises(ValueError, match="only approved"):
        service.preview_write_evidence_refresh(command=dry_run_preview_command, user_context=user_context)

    transition_response = service.approve_write_approval(
        command=KnowledgeBaseWriteApprovalTransitionCommand(
            dry_run_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
            approval_reference="approval:kb-write-approve",
            reason="human approved guarded knowledge base write",
        ),
        user_context=user_context,
    )
    preview_command = KnowledgeBaseEvidenceRefreshPreviewCommand(
        approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
        preview_reference="preview:kb-refresh-1",
        reason="preview metadata-only source and restore evidence refresh",
    )

    preview = service.preview_write_evidence_refresh(command=preview_command, user_context=user_context)

    assert preview.tenant_id == "tenant-demo"
    assert preview.approved_write_approval_evidence_hash == transition_response.approved_write_approval_evidence_hash
    assert preview.transition_source_evidence_hash == dry_run_response.write_approval_evidence_hash
    assert preview.operation == KnowledgeBaseWriteOperation.EDIT
    assert preview.command_hash == transition_response.command_hash
    assert preview.preview_command_hash.startswith("sha256:")
    assert preview.proposed_source_version_evidence_hash == transition_response.proposed_source_version_evidence_hash
    assert preview.current_restore_evidence_hash == transition_response.current_restore_evidence_hash
    assert preview.projected_restore_evidence_preview_hash.startswith("sha256:")
    assert preview.article_count_before == 2
    assert preview.article_count_after == 2
    assert preview.article_version_count_before == 2
    assert preview.article_version_count_after == 2
    assert preview.source_version_evidence_count_before == 2
    assert preview.source_version_evidence_count_after == 2
    assert len(preview.current_source_version_evidence_hashes) == 2
    assert len(preview.projected_source_version_evidence_hashes) == 2
    assert preview.proposed_source_version_evidence_hash not in preview.current_source_version_evidence_hashes
    assert preview.proposed_source_version_evidence_hash in preview.projected_source_version_evidence_hashes
    assert preview.preview_only is True
    assert preview.article_source_writes_allowed is False
    assert preview.evidence_persistence_allowed is False
    assert preview.rag_indexing_allowed is False
    assert preview.source_authority_verified is False
    assert "projected_restore_evidence_preview_hash" in preview.required_evidence
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == 2
    assert service.repository.list_articles(tenant_id="tenant-demo")[0].current_version_label == "v1"
    assert "Backup restore runbook source content v2" not in preview.model_dump_json()

    event = audit_logger.events[-1]
    assert preview.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.refresh_preview"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["result_contract"] == "metadata_only"
    assert event.metadata["preview_only"] is True
    assert event.metadata["article_source_writes_allowed"] is False
    assert event.metadata["evidence_persistence_allowed"] is False
    assert event.metadata["rag_indexing_allowed"] is False
    assert event.metadata["source_authority_verified"] is False
    assert event.metadata["projected_restore_evidence_preview_hash"] == preview.projected_restore_evidence_preview_hash


def test_knowledge_base_write_execution_skeleton_verifies_preconditions_and_still_blocks_writes() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    write_command = write_command_for_source_record(proposed_source_record)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )
    dry_run_response = service.dry_run_write_approval(command=write_command, user_context=user_context)
    transition_response = service.approve_write_approval(
        command=KnowledgeBaseWriteApprovalTransitionCommand(
            dry_run_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
            approval_reference="approval:kb-write-approve",
            reason="human approved guarded knowledge base write",
        ),
        user_context=user_context,
    )
    preview = service.preview_write_evidence_refresh(
        command=KnowledgeBaseEvidenceRefreshPreviewCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            preview_reference="preview:kb-refresh-1",
            reason="preview metadata-only source and restore evidence refresh",
        ),
        user_context=user_context,
    )
    guard_decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
        proposed_source_record=proposed_source_record,
    )
    assert guard_decision.allowed is True

    command = KnowledgeBaseWriteExecutionSkeletonCommand(
        approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
        source_object_write_guard_decision=guard_decision,
        refresh_preview_command_hash=preview.preview_command_hash,
        projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
        execution_reference="execution:kb-write-skeleton-1",
        human_confirmation_reference="human-confirmation:kb-write-1",
        reason="prepare guarded write execution without persistence",
    )
    response = service.prepare_write_execution_skeleton(command=command, user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.approved_write_approval_evidence_hash == transition_response.approved_write_approval_evidence_hash
    assert response.transition_source_evidence_hash == dry_run_response.write_approval_evidence_hash
    assert response.source_object_write_guard_ref == guard_decision.source_object_write_guard_ref
    assert response.refresh_preview_command_hash == preview.preview_command_hash
    assert response.projected_restore_evidence_preview_hash == preview.projected_restore_evidence_preview_hash
    assert response.preconditions_verified is True
    assert response.source_object_write_guard_verified is True
    assert response.human_confirmation_verified is True
    assert response.source_authority_verified is True
    assert response.execution_allowed is False
    assert response.article_source_writes_allowed is False
    assert response.article_metadata_persistence_allowed is False
    assert response.source_object_persistence_allowed is False
    assert response.evidence_persistence_allowed is False
    assert response.rag_indexing_allowed is False
    assert "write_execution_adapter_not_enabled" in response.blocking_reasons
    assert "post_write_source_restore_evidence_refresh_not_connected" in response.blocking_reasons
    assert "explicit_human_confirmation_reference" in response.required_evidence
    assert response.execution_command_hash.startswith("sha256:")
    assert response.execution_plan_hash.startswith("sha256:")
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == 2
    assert service.repository.list_articles(tenant_id="tenant-demo")[0].current_version_label == "v1"
    assert "Backup restore runbook source content v2" not in response.model_dump_json()

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.execution_skeleton"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["result_contract"] == "metadata_only"
    assert event.metadata["execution_reference"] == "execution:kb-write-skeleton-1"
    assert event.metadata["human_confirmation_reference"] == "human-confirmation:kb-write-1"
    assert event.metadata["execution_allowed"] is False
    assert event.metadata["execution_plan_hash"] == response.execution_plan_hash

    tampered_guard_decision = guard_decision.model_copy(
        update={"source_object_write_guard_ref": "guard:sha256:" + "1" * 64}
    )
    with pytest.raises(ValueError, match="guard reference is invalid"):
        service.prepare_write_execution_skeleton(
            command=command.model_copy(update={"source_object_write_guard_decision": tampered_guard_decision}),
            user_context=user_context,
        )
    with pytest.raises(ValueError, match="preview hash does not match"):
        service.prepare_write_execution_skeleton(
            command=command.model_copy(update={"projected_restore_evidence_preview_hash": "sha256:" + "2" * 64}),
            user_context=user_context,
        )


def test_knowledge_base_write_execution_commits_edit_and_refreshes_restore_evidence() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    source_repository = demo_knowledge_base_source_object_repository()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=source_repository,
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    write_command = write_command_for_source_record(proposed_source_record)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )
    dry_run_response = service.dry_run_write_approval(command=write_command, user_context=user_context)
    transition_response = service.approve_write_approval(
        command=KnowledgeBaseWriteApprovalTransitionCommand(
            dry_run_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
            approval_reference="approval:kb-write-approve",
            reason="human approved guarded knowledge base write",
        ),
        user_context=user_context,
    )
    preview = service.preview_write_evidence_refresh(
        command=KnowledgeBaseEvidenceRefreshPreviewCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            preview_reference="preview:kb-refresh-1",
            reason="preview metadata-only source and restore evidence refresh",
        ),
        user_context=user_context,
    )
    guard_decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
        proposed_source_record=proposed_source_record,
    )
    skeleton = service.prepare_write_execution_skeleton(
        command=KnowledgeBaseWriteExecutionSkeletonCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_reference="execution:kb-write-skeleton-1",
            human_confirmation_reference="human-confirmation:kb-write-1",
            reason="prepare guarded write execution without persistence",
        ),
        user_context=user_context,
    )

    response = service.execute_write(
        command=KnowledgeBaseWriteExecutionCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_skeleton_command_hash=skeleton.execution_command_hash,
            execution_plan_hash=skeleton.execution_plan_hash,
            execution_reference="execution:kb-write-skeleton-1",
            human_confirmation_reference="human-confirmation:kb-write-1",
            proposed_source_record=proposed_source_record,
            reason="execute guarded knowledge base edit",
        ),
        user_context=user_context,
    )

    assert response.execution_allowed is True
    assert response.source_object_persisted is True
    assert response.article_metadata_persisted is True
    assert response.article_version_metadata_persisted is True
    assert response.source_version_evidence_refreshed is True
    assert response.restore_evidence_refreshed is True
    assert response.rag_indexing_allowed is False
    assert response.search_indexing_allowed is False
    assert response.previous_version_object_id == "kb-article-version-backup-runbook-v1-demo"
    assert response.current_version_object_id == proposed_source_record.metadata.object_id
    assert response.current_source_version_id == proposed_source_record.metadata.version_id
    assert response.refreshed_source_version_evidence_hash == transition_response.proposed_source_version_evidence_hash
    assert response.refreshed_source_version_evidence_hash in response.source_version_evidence_hashes_after
    assert response.previous_restore_evidence_hash == transition_response.current_restore_evidence_hash
    assert response.refreshed_restore_evidence_hash.startswith("sha256:")
    assert response.refreshed_restore_evidence_hash != response.previous_restore_evidence_hash
    assert "source_object_persisted" in response.required_evidence
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == 2

    updated_article = next(
        article
        for article in service.repository.list_articles(tenant_id="tenant-demo")
        if article.object_id == "kb-article-backup-runbook-demo"
    )
    assert updated_article.current_version_label == "v2"
    assert updated_article.current_source_version_id == "v2"
    assert (
        source_repository.get(
            tenant_id="tenant-demo",
            object_id=proposed_source_record.metadata.object_id,
            version_id=proposed_source_record.metadata.version_id,
        )
        == proposed_source_record
    )
    evidence_response = service.read_compliance_evidence(user_context=user_context)
    assert {evidence.source_version_id for evidence in evidence_response.source_version_evidence} == {"v1", "v2"}
    assert evidence_response.restore_evidence.evidence_hash == response.refreshed_restore_evidence_hash
    assert "Backup restore runbook source content v2" not in response.model_dump_json()

    event = audit_logger.events[-2]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.executed"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["result_contract"] == "metadata_only"
    assert event.metadata["source_object_persisted"] is True
    assert event.metadata["article_metadata_persisted"] is True
    assert event.metadata["refreshed_restore_evidence_hash"] == response.refreshed_restore_evidence_hash

    with pytest.raises(ValueError, match="expected current article version"):
        service.execute_write(
            command=KnowledgeBaseWriteExecutionCommand(
                approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
                source_object_write_guard_decision=guard_decision,
                refresh_preview_command_hash=preview.preview_command_hash,
                projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
                execution_skeleton_command_hash=skeleton.execution_command_hash,
                execution_plan_hash=skeleton.execution_plan_hash,
                execution_reference="execution:kb-write-skeleton-1",
                human_confirmation_reference="human-confirmation:kb-write-1",
                proposed_source_record=proposed_source_record,
                reason="execute guarded knowledge base edit again",
            ),
            user_context=user_context,
        )


def test_knowledge_base_write_execution_commits_create_from_trusted_approval_metadata() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    source_repository = demo_knowledge_base_source_object_repository()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=source_repository,
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write(
        object_id="kb-article-version-new-runbook-v1-demo",
        version_id="v1",
        title="New Runbook v1",
        text="New runbook source content.",
    )
    write_command = write_command_for_source_record(
        proposed_source_record,
        operation=KnowledgeBaseWriteOperation.CREATE,
        article_object_id="kb-article-new-runbook-demo",
        article_key="KB-NEW-001",
        article_title="New Runbook",
        expected_current_version_object_id=None,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )

    dry_run_response = service.dry_run_write_approval(command=write_command, user_context=user_context)
    dry_run_evidence = write_approval_ledger.get(
        tenant_id="tenant-demo",
        evidence_hash=dry_run_response.write_approval_evidence_hash,
    )
    assert dry_run_evidence.operation == KnowledgeBaseWriteOperation.CREATE
    assert dry_run_evidence.article_key == "KB-NEW-001"
    assert dry_run_evidence.title == "New Runbook"
    assert dry_run_evidence.proposed_version_label == "v1"
    assert dry_run_evidence.source_system == "collabio"

    transition_response = service.approve_write_approval(
        command=KnowledgeBaseWriteApprovalTransitionCommand(
            dry_run_write_approval_evidence_hash=dry_run_response.write_approval_evidence_hash,
            approval_reference="approval:kb-create-approve",
            reason="human approved governed knowledge base create",
        ),
        user_context=user_context,
    )
    approved_evidence = write_approval_ledger.get(
        tenant_id="tenant-demo",
        evidence_hash=transition_response.approved_write_approval_evidence_hash,
    )
    assert approved_evidence.article_key == dry_run_evidence.article_key
    assert approved_evidence.title == dry_run_evidence.title
    assert approved_evidence.proposed_version_label == dry_run_evidence.proposed_version_label
    assert approved_evidence.source_system == dry_run_evidence.source_system

    preview = service.preview_write_evidence_refresh(
        command=KnowledgeBaseEvidenceRefreshPreviewCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            preview_reference="preview:kb-create-refresh",
            reason="preview metadata-only source and restore evidence refresh for create",
        ),
        user_context=user_context,
    )
    assert preview.operation == KnowledgeBaseWriteOperation.CREATE
    assert preview.article_count_before == 2
    assert preview.article_count_after == 3
    assert preview.article_version_count_before == 2
    assert preview.article_version_count_after == 3
    assert preview.source_version_evidence_count_before == 2
    assert preview.source_version_evidence_count_after == 3
    assert preview.proposed_source_version_evidence_hash in preview.projected_source_version_evidence_hashes

    guard_decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
        proposed_source_record=proposed_source_record,
    )
    assert guard_decision.allowed is True

    skeleton = service.prepare_write_execution_skeleton(
        command=KnowledgeBaseWriteExecutionSkeletonCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_reference="execution:kb-create-skeleton-1",
            human_confirmation_reference="human-confirmation:kb-create-1",
            reason="prepare guarded create execution",
        ),
        user_context=user_context,
    )

    response = service.execute_write(
        command=KnowledgeBaseWriteExecutionCommand(
            approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
            source_object_write_guard_decision=guard_decision,
            refresh_preview_command_hash=preview.preview_command_hash,
            projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
            execution_skeleton_command_hash=skeleton.execution_command_hash,
            execution_plan_hash=skeleton.execution_plan_hash,
            execution_reference="execution:kb-create-skeleton-1",
            human_confirmation_reference="human-confirmation:kb-create-1",
            proposed_source_record=proposed_source_record,
            reason="execute governed knowledge base create",
        ),
        user_context=user_context,
    )

    assert response.execution_allowed is True
    assert response.operation == KnowledgeBaseWriteOperation.CREATE
    assert response.previous_version_object_id is None
    assert response.current_version_object_id == proposed_source_record.metadata.object_id
    assert response.current_source_object_id == proposed_source_record.metadata.object_id
    assert response.current_source_version_id == "v1"
    assert response.refreshed_source_version_evidence_hash == transition_response.proposed_source_version_evidence_hash
    assert response.article_count_after == 3
    assert response.article_version_count_after == 3
    assert response.source_version_evidence_count_after == 3
    assert response.rag_indexing_allowed is False
    assert response.search_indexing_allowed is False

    created_article = next(
        article
        for article in service.repository.list_articles(tenant_id="tenant-demo")
        if article.object_id == "kb-article-new-runbook-demo"
    )
    assert created_article.article_key == "KB-NEW-001"
    assert created_article.title == "New Runbook"
    assert created_article.current_version_label == "v1"
    assert created_article.source_system == "collabio"
    assert created_article.current_source_manifest_hash == proposed_source_record.metadata.manifest_hash
    assert (
        source_repository.get(
            tenant_id="tenant-demo",
            object_id=proposed_source_record.metadata.object_id,
            version_id=proposed_source_record.metadata.version_id,
        )
        == proposed_source_record
    )
    assert "New runbook source content" not in response.model_dump_json()

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "knowledge_base.write_approval.executed"
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["operation"] == KnowledgeBaseWriteOperation.CREATE
    assert event.metadata["article_metadata_persisted"] is True
    assert event.metadata["source_object_persisted"] is True

    evidence_response = service.read_compliance_evidence(user_context=user_context)
    assert evidence_response.restore_evidence.article_count == 3
    assert evidence_response.restore_evidence.source_version_evidence_count == 3
    assert response.refreshed_source_version_evidence_hash in {
        evidence.evidence_hash for evidence in evidence_response.source_version_evidence
    }

    with pytest.raises(ValueError, match="existing knowledge base article"):
        service.execute_write(
            command=KnowledgeBaseWriteExecutionCommand(
                approved_write_approval_evidence_hash=transition_response.approved_write_approval_evidence_hash,
                source_object_write_guard_decision=guard_decision,
                refresh_preview_command_hash=preview.preview_command_hash,
                projected_restore_evidence_preview_hash=preview.projected_restore_evidence_preview_hash,
                execution_skeleton_command_hash=skeleton.execution_command_hash,
                execution_plan_hash=skeleton.execution_plan_hash,
                execution_reference="execution:kb-create-skeleton-1",
                human_confirmation_reference="human-confirmation:kb-create-1",
                proposed_source_record=proposed_source_record,
                reason="execute governed knowledge base create again",
            ),
            user_context=user_context,
        )


def test_knowledge_base_source_object_write_guard_blocks_dry_run_ledger_evidence() -> None:
    audit_logger = InMemoryAuditLogger()
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=write_approval_ledger,
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    command = write_command_for_source_record(proposed_source_record)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="tenant-admin-demo",
        role_ids={"tenant-admin"},
        readable_object_ids=set(),
    )

    response = service.dry_run_write_approval(command=command, user_context=user_context)
    decision = service.evaluate_source_object_write_guard(
        user_context=user_context,
        write_approval_evidence_hash=response.write_approval_evidence_hash,
        proposed_source_record=proposed_source_record,
    )

    assert decision.allowed is False
    assert decision.persistence_allowed is False
    assert decision.source_authority_verified is False
    assert decision.source_object_write_guard_ref.startswith("guard:sha256:")
    assert "approval_state_not_approved_for_write" in decision.blocking_reasons
    assert "persistence_not_allowed_by_approval_evidence" in decision.blocking_reasons
    assert "expected_current_version_match" in decision.required_evidence
    assert service.repository.list_articles(tenant_id="tenant-demo")[0].current_version_label == "v1"
    assert "Backup restore runbook source content v2" not in decision.model_dump_json()


def test_knowledge_base_source_object_write_guard_allows_only_approved_matching_evidence() -> None:
    article_repository = InMemoryKnowledgeBaseArticleRepository.demo()
    article = article_repository.list_articles(tenant_id="tenant-demo")[0]
    source_repository = demo_knowledge_base_source_object_repository()
    source_evidences = [
        build_knowledge_base_source_version_evidence(
            existing_article,
            source_repository.get(
                tenant_id=existing_article.tenant_id,
                object_id=existing_article.current_source_object_id,
                version_id=existing_article.current_source_version_id,
            ),
        )
        for existing_article in article_repository.list_articles(tenant_id="tenant-demo")
    ]
    restore_evidence = build_knowledge_base_restore_evidence(
        tenant_id="tenant-demo",
        articles=article_repository.list_articles(tenant_id="tenant-demo"),
        source_evidences=source_evidences,
        restore_drill_report_hash="sha256:" + "5" * 64,
        audit_chain_ref="audit:knowledge-base-restore-evidence",
    )
    proposed_source_record = knowledge_base_source_record_for_write()
    command = write_command_for_source_record(proposed_source_record)
    command_hash = build_write_approval_command_hash(command)
    proposed_source_evidence = build_source_version_evidence_for_source_record(
        tenant_id="tenant-demo",
        article_object_id=command.article_object_id,
        article_version_object_id=command.proposed_version_object_id,
        source_record=proposed_source_record,
    )
    approved_evidence = build_write_approval_evidence(
        tenant_id="tenant-demo",
        command=command,
        command_hash=command_hash,
        proposed_source_version_evidence_hash=proposed_source_evidence.evidence_hash,
        current_restore_evidence_hash=restore_evidence.evidence_hash,
        requested_by="tenant-admin-demo",
        audit_event_id="audit-event-kb-approved-write",
        audit_chain_ref="audit:audit-event-kb-approved-write",
        approval_state=KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE,
        transition_source_evidence_hash="sha256:" + "7" * 64,
        persistence_allowed=True,
    )
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger((approved_evidence,))
    decision = KnowledgeBaseSourceObjectWriteGuard().evaluate(
        tenant_id="tenant-demo",
        write_approval_evidence_hash=approved_evidence.evidence_hash,
        write_approval_ledger=write_approval_ledger,
        current_article=article,
        proposed_source_record=proposed_source_record,
        current_restore_evidence=restore_evidence,
    )

    assert decision.allowed is True
    assert decision.blocking_reasons == ()
    assert decision.persistence_allowed is True
    assert decision.source_authority_verified is True
    assert decision.rag_indexing_allowed is False
    assert decision.write_approval_evidence_hash == approved_evidence.evidence_hash
    assert decision.proposed_source_version_evidence_hash == proposed_source_evidence.evidence_hash
    assert decision.current_restore_evidence_hash == restore_evidence.evidence_hash

    tampered_source_record = knowledge_base_source_record_for_write(retention_policy_id="rp-custom")
    tampered_decision = KnowledgeBaseSourceObjectWriteGuard().evaluate(
        tenant_id="tenant-demo",
        write_approval_evidence_hash=approved_evidence.evidence_hash,
        write_approval_ledger=write_approval_ledger,
        current_article=article,
        proposed_source_record=tampered_source_record,
        current_restore_evidence=restore_evidence,
    )
    assert tampered_decision.allowed is False
    assert "proposed_source_retention_policy_unsupported" in tampered_decision.blocking_reasons
    assert "proposed_source_version_evidence_hash_mismatch" in tampered_decision.blocking_reasons


def test_knowledge_base_source_object_write_guard_blocks_version_legal_hold_and_restore_drift() -> None:
    article_repository = InMemoryKnowledgeBaseArticleRepository.demo()
    article = article_repository.list_articles(tenant_id="tenant-demo")[0]
    held_article = article.model_copy(update={"legal_hold_state": "active"})
    proposed_source_record = knowledge_base_source_record_for_write()
    command = write_command_for_source_record(proposed_source_record)
    source_evidence = build_source_version_evidence_for_source_record(
        tenant_id="tenant-demo",
        article_object_id=command.article_object_id,
        article_version_object_id=command.proposed_version_object_id,
        source_record=proposed_source_record,
    )
    source_repository = demo_knowledge_base_source_object_repository()
    current_source_evidences = [
        build_knowledge_base_source_version_evidence(
            existing_article,
            source_repository.get(
                tenant_id=existing_article.tenant_id,
                object_id=existing_article.current_source_object_id,
                version_id=existing_article.current_source_version_id,
            ),
        )
        for existing_article in article_repository.list_articles(tenant_id="tenant-demo")
    ]
    restore_evidence = build_knowledge_base_restore_evidence(
        tenant_id="tenant-demo",
        articles=article_repository.list_articles(tenant_id="tenant-demo"),
        source_evidences=current_source_evidences,
        restore_drill_report_hash="sha256:" + "6" * 64,
        audit_chain_ref="audit:knowledge-base-restore-evidence",
    )
    approved_evidence = build_write_approval_evidence(
        tenant_id="tenant-demo",
        command=command,
        command_hash=build_write_approval_command_hash(command),
        proposed_source_version_evidence_hash=source_evidence.evidence_hash,
        current_restore_evidence_hash=restore_evidence.evidence_hash,
        requested_by="tenant-admin-demo",
        audit_event_id="audit-event-kb-approved-write",
        audit_chain_ref="audit:audit-event-kb-approved-write",
        approval_state=KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE,
        transition_source_evidence_hash="sha256:" + "8" * 64,
        persistence_allowed=True,
    )
    write_approval_ledger = InMemoryKnowledgeBaseWriteApprovalLedger((approved_evidence,))

    decision = KnowledgeBaseSourceObjectWriteGuard().evaluate(
        tenant_id="tenant-demo",
        write_approval_evidence_hash=approved_evidence.evidence_hash,
        write_approval_ledger=write_approval_ledger,
        current_article=held_article.model_copy(update={"current_version_object_id": "unexpected-version"}),
        proposed_source_record=proposed_source_record,
        current_restore_evidence=restore_evidence.model_copy(update={"evidence_hash": "sha256:" + "f" * 64}),
    )

    assert decision.allowed is False
    assert "expected_current_version_mismatch" in decision.blocking_reasons
    assert "current_article_legal_hold_active" in decision.blocking_reasons
    assert "current_restore_evidence_hash_mismatch" in decision.blocking_reasons
    assert "current_restore_evidence_hash_invalid" in decision.blocking_reasons


def test_knowledge_base_source_version_evidence_matches_authoritative_source_object() -> None:
    article = InMemoryKnowledgeBaseArticleRepository.demo().list_articles(tenant_id="tenant-demo")[0]
    source_record = demo_knowledge_base_source_object_repository().get(
        tenant_id=article.tenant_id,
        object_id=article.current_source_object_id,
        version_id=article.current_source_version_id,
    )

    evidence = build_knowledge_base_source_version_evidence(article, source_record)

    assert evidence.article_object_id == article.object_id
    assert evidence.article_version_object_id == article.current_version_object_id
    assert evidence.source_object_id == article.current_source_object_id
    assert evidence.source_version_id == "v1"
    assert evidence.source_object_type == "wiki"
    assert evidence.source_manifest_hash == article.current_source_manifest_hash
    assert evidence.content_hash == article.current_content_hash
    assert evidence.acl_version == article.current_acl_version
    assert evidence.evidence_hash == build_source_version_evidence_hash(evidence)


def test_knowledge_base_source_version_evidence_rejects_manifest_drift() -> None:
    article = InMemoryKnowledgeBaseArticleRepository.demo().list_articles(tenant_id="tenant-demo")[0]
    tampered_article = article.model_copy(update={"current_source_manifest_hash": "sha256:" + "1" * 64})
    source_record = demo_knowledge_base_source_object_repository().get(
        tenant_id=article.tenant_id,
        object_id=article.current_source_object_id,
        version_id=article.current_source_version_id,
    )

    with pytest.raises(ValueError, match="source_manifest_hash"):
        build_knowledge_base_source_version_evidence(tampered_article, source_record)


def test_knowledge_base_restore_evidence_covers_articles_versions_and_source_evidence() -> None:
    articles = InMemoryKnowledgeBaseArticleRepository.demo().list_articles(tenant_id="tenant-demo")
    source_repository = demo_knowledge_base_source_object_repository()
    source_evidences = tuple(
        build_knowledge_base_source_version_evidence(
            article,
            source_repository.get(
                tenant_id=article.tenant_id,
                object_id=article.current_source_object_id,
                version_id=article.current_source_version_id,
            ),
        )
        for article in articles
    )

    restore_evidence = build_knowledge_base_restore_evidence(
        tenant_id="tenant-demo",
        articles=articles,
        source_evidences=source_evidences,
        restore_drill_report_hash="sha256:" + "2" * 64,
        audit_chain_ref="audit:kb-restore-evidence",
    )

    assert restore_evidence.continuity_domain == "knowledge_base_content"
    assert restore_evidence.article_count == 2
    assert restore_evidence.article_version_count == 2
    assert restore_evidence.source_version_evidence_count == 2
    assert restore_evidence.tenant_isolation_verified
    assert restore_evidence.disabled_state_restore_verified
    assert restore_evidence.legal_hold_restore_verified
    assert restore_evidence.evidence_hash == build_restore_evidence_hash(restore_evidence)

    with pytest.raises(ValueError, match="every article"):
        build_knowledge_base_restore_evidence(
            tenant_id="tenant-demo",
            articles=articles,
            source_evidences=source_evidences[:1],
            restore_drill_report_hash="sha256:" + "2" * 64,
            audit_chain_ref="audit:kb-restore-evidence",
        )
