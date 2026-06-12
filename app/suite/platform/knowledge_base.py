from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext

KNOWLEDGE_BASE_MODULE_ID = "knowledge_base"
KB_ARTICLES_FEATURE_ID = "knowledge_base.articles.read"
KB_ARTICLE_OBJECT_TYPE = "kb.article"
KB_ARTICLE_VERSION_OBJECT_TYPE = "kb.article_version"
KB_ARTICLE_SCHEMA_VERSION = "kb_article.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class KnowledgeBaseArticleLifecycleState(StrEnum):
    WORKING = "working"
    PUBLISHED = "published"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class KnowledgeBaseArticleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class KnowledgeBaseArticleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = KB_ARTICLE_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.INTERNAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: KnowledgeBaseArticleLifecycleState = KnowledgeBaseArticleLifecycleState.PUBLISHED
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = KB_ARTICLE_SCHEMA_VERSION
    article_key: str
    title: str
    current_version_object_id: str
    current_version_label: str
    published_at_utc: str | None = None
    status: KnowledgeBaseArticleStatus = KnowledgeBaseArticleStatus.PUBLISHED

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "article_key",
        "title",
        "current_version_object_id",
        "current_version_label",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base article fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_article_object_type(cls, value: str) -> str:
        if value != KB_ARTICLE_OBJECT_TYPE:
            raise ValueError("knowledge base article records must use kb.article object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_internal_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.INTERNAL:
            raise ValueError("knowledge base article metadata is internal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("knowledge base articles must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("knowledge base article legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base article references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("knowledge base article source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != KB_ARTICLE_SCHEMA_VERSION:
            raise ValueError("knowledge base article schema_version must match kb_article.v1")
        return value

    @model_validator(mode="after")
    def require_status_lifecycle_alignment(self) -> KnowledgeBaseArticleRecord:
        if self.status == KnowledgeBaseArticleStatus.RESTRICTED and (
            self.lifecycle_state != KnowledgeBaseArticleLifecycleState.RESTRICTED
        ):
            raise ValueError("restricted knowledge base articles must use restricted lifecycle_state")
        if self.status == KnowledgeBaseArticleStatus.PUBLISHED and self.published_at_utc is None:
            raise ValueError("published knowledge base articles require published_at_utc")
        return self


class KnowledgeBaseArticleView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    article_key: str
    title: str
    current_version_object_id: str
    current_version_label: str
    published_at_utc: str | None = None
    status: KnowledgeBaseArticleStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: KnowledgeBaseArticleLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    source_version_access_checked: bool = True


class KnowledgeBaseArticlesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_FEATURE_ID
    articles: list[KnowledgeBaseArticleView]
    audit_event_id: str


class KnowledgeBaseArticleRepository(Protocol):
    def list_articles(self, *, tenant_id: str) -> Sequence[KnowledgeBaseArticleRecord]:
        pass


def knowledge_base_article_view(record: KnowledgeBaseArticleRecord) -> KnowledgeBaseArticleView:
    return KnowledgeBaseArticleView(
        object_id=record.object_id,
        object_type=record.object_type,
        article_key=record.article_key,
        title=record.title,
        current_version_object_id=record.current_version_object_id,
        current_version_label=record.current_version_label,
        published_at_utc=record.published_at_utc,
        status=record.status,
        owner_principal_id=record.owner_principal_id,
        created_at_utc=record.created_at_utc,
        updated_at_utc=record.updated_at_utc,
        data_classification=record.data_classification,
        retention_policy_id=record.retention_policy_id,
        legal_hold_state=record.legal_hold_state,
        lifecycle_state=record.lifecycle_state,
        source_system=record.source_system,
        schema_version=record.schema_version,
        audit_chain_ref=record.audit_chain_ref,
    )


class InMemoryKnowledgeBaseArticleRepository:
    def __init__(self, articles: Sequence[KnowledgeBaseArticleRecord]) -> None:
        self._articles = tuple(articles)

    @classmethod
    def demo(cls) -> InMemoryKnowledgeBaseArticleRepository:
        return cls(
            articles=(
                KnowledgeBaseArticleRecord(
                    tenant_id="tenant-demo",
                    object_id="kb-article-backup-runbook-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-12T08:00:00Z",
                    updated_at_utc="2026-06-12T08:00:00Z",
                    kms_key_ref="kms:tenant-demo:kb-article",
                    audit_chain_ref="audit:kb-article-backup-runbook-demo",
                    article_key="KB-BACKUP-001",
                    title="Backup Restore Runbook",
                    current_version_object_id="kb-article-version-backup-runbook-v1-demo",
                    current_version_label="v1",
                    published_at_utc="2026-06-12T08:00:00Z",
                ),
                KnowledgeBaseArticleRecord(
                    tenant_id="tenant-demo",
                    object_id="kb-article-security-baseline-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-12T08:05:00Z",
                    updated_at_utc="2026-06-12T08:05:00Z",
                    kms_key_ref="kms:tenant-demo:kb-article",
                    audit_chain_ref="audit:kb-article-security-baseline-demo",
                    article_key="KB-SEC-001",
                    title="Security Baseline",
                    current_version_object_id="kb-article-version-security-baseline-v1-demo",
                    current_version_label="v1",
                    published_at_utc="2026-06-12T08:05:00Z",
                ),
                KnowledgeBaseArticleRecord(
                    tenant_id="tenant-other",
                    object_id="kb-article-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-12T08:10:00Z",
                    updated_at_utc="2026-06-12T08:10:00Z",
                    kms_key_ref="kms:tenant-other:kb-article",
                    audit_chain_ref="audit:kb-article-other-tenant",
                    article_key="KB-OTHER-001",
                    title="Other Tenant Article",
                    current_version_object_id="kb-article-version-other-tenant-v1",
                    current_version_label="v1",
                    published_at_utc="2026-06-12T08:10:00Z",
                ),
            )
        )

    def list_articles(self, *, tenant_id: str) -> Sequence[KnowledgeBaseArticleRecord]:
        return tuple(article for article in self._articles if article.tenant_id == tenant_id)


class KnowledgeBaseArticleService:
    def __init__(self, *, repository: KnowledgeBaseArticleRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_articles(self, *, user_context: UserContext) -> KnowledgeBaseArticlesResponse:
        candidate_records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records = [
            record
            for record in candidate_records
            if record.object_id in user_context.readable_object_ids
            and record.current_version_object_id in user_context.readable_object_ids
        ]
        views = [knowledge_base_article_view(record) for record in records]
        source_object_ids = [
            source_object_id
            for record in records
            for source_object_id in (record.object_id, record.current_version_object_id)
        ]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.article.list",
            source_object_ids=source_object_ids,
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_FEATURE_ID,
                "object_type": KB_ARTICLE_OBJECT_TYPE,
                "version_object_type": KB_ARTICLE_VERSION_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
            },
        )
        return KnowledgeBaseArticlesResponse(
            tenant_id=user_context.tenant_id,
            articles=views,
            audit_event_id=event.event_id,
        )


def default_knowledge_base_enabled_features() -> dict[str, bool]:
    return {KB_ARTICLES_FEATURE_ID: True}
