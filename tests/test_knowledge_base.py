import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.knowledge_base import (
    KB_ARTICLE_OBJECT_TYPE,
    KB_ARTICLE_VERSION_OBJECT_TYPE,
    KB_ARTICLES_FEATURE_ID,
    KNOWLEDGE_BASE_MODULE_ID,
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleRecord,
    KnowledgeBaseArticleService,
    build_knowledge_base_restore_evidence,
    build_knowledge_base_source_version_evidence,
    build_restore_evidence_hash,
    build_source_version_evidence_hash,
    demo_knowledge_base_source_object_repository,
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
