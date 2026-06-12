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
    assert [article.title for article in response.articles] == ["Backup Restore Runbook", "Security Baseline"]
    assert {article.object_type for article in response.articles} == {KB_ARTICLE_OBJECT_TYPE}
    assert {article.data_classification for article in response.articles} == {DataClass.INTERNAL}
    assert all(article.access_checked for article in response.articles)
    assert all(article.source_version_access_checked for article in response.articles)
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
        "result_contract": "metadata_only",
        "result_count": 2,
    }


def test_knowledge_base_article_service_filters_unreadable_versions() -> None:
    audit_logger = InMemoryAuditLogger()
    service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
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
