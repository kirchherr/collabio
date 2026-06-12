from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
    source_object_content_bytes,
)

KNOWLEDGE_BASE_MODULE_ID = "knowledge_base"
KB_ARTICLES_FEATURE_ID = "knowledge_base.articles.read"
KB_ARTICLE_OBJECT_TYPE = "kb.article"
KB_ARTICLE_VERSION_OBJECT_TYPE = "kb.article_version"
KB_ARTICLE_SCHEMA_VERSION = "kb_article.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")
ZERO_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


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
    current_source_object_id: str
    current_source_version_id: str
    current_source_object_type: SourceObjectType = SourceObjectType.WIKI
    current_source_manifest_hash: str
    current_content_hash: str
    current_acl_version: int = Field(ge=1)
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
        "current_source_object_id",
        "current_source_version_id",
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

    @field_validator("kms_key_ref", "audit_chain_ref", "current_source_manifest_hash", "current_content_hash")
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
        if self.current_source_object_id != self.current_version_object_id:
            raise ValueError("current source object must be the current kb.article_version object")
        return self


class KnowledgeBaseArticleView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    article_key: str
    title: str
    current_version_object_id: str
    current_version_label: str
    current_source_object_id: str
    current_source_version_id: str
    current_source_object_type: SourceObjectType
    source_version_evidence_hash: str
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


class KnowledgeBaseSourceVersionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    article_object_id: str
    article_version_object_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_manifest_hash: str
    content_hash: str
    acl_version: int = Field(ge=1)
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    evidence_hash: str
    schema_version: str = "knowledge_base_source_version_evidence.v1"

    @field_validator(
        "tenant_id",
        "article_object_id",
        "article_version_object_id",
        "source_object_id",
        "source_version_id",
        "retention_policy_id",
        "legal_hold_state",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base source evidence fields must not be empty")
        return value

    @field_validator("source_manifest_hash", "content_hash", "evidence_hash")
    @classmethod
    def validate_namespaced_hashes(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base source evidence hashes must be namespaced")
        return value


class KnowledgeBaseRestoreEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    continuity_domain: str = "knowledge_base_content"
    article_count: int = Field(ge=0)
    article_version_count: int = Field(ge=0)
    source_version_evidence_count: int = Field(ge=0)
    source_version_evidence_hashes: tuple[str, ...]
    restore_drill_report_hash: str
    row_count_hash: str
    checksum_manifest_hash: str
    tenant_isolation_verified: bool
    disabled_state_restore_verified: bool
    legal_hold_restore_verified: bool
    audit_chain_ref: str
    evidence_hash: str
    schema_version: str = "knowledge_base_restore_evidence.v1"

    @field_validator("tenant_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base restore evidence fields must not be empty")
        return value

    @field_validator("source_version_evidence_hashes")
    @classmethod
    def validate_evidence_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source version evidence hashes must be unique")
        for evidence_hash in value:
            if not NAMESPACED_REF_PATTERN.fullmatch(evidence_hash):
                raise ValueError("source version evidence hashes must be namespaced")
        return value

    @field_validator(
        "restore_drill_report_hash",
        "row_count_hash",
        "checksum_manifest_hash",
        "audit_chain_ref",
        "evidence_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base restore evidence references must be namespaced")
        return value

    @model_validator(mode="after")
    def require_complete_restore_checks(self) -> KnowledgeBaseRestoreEvidence:
        if self.module_id != KNOWLEDGE_BASE_MODULE_ID:
            raise ValueError("knowledge base restore evidence must belong to knowledge_base")
        if self.continuity_domain != "knowledge_base_content":
            raise ValueError("knowledge base restore evidence must use knowledge_base_content")
        if self.article_version_count != self.source_version_evidence_count:
            raise ValueError("article versions and source-version evidence counts must match")
        if len(self.source_version_evidence_hashes) != self.source_version_evidence_count:
            raise ValueError("source_version_evidence_hashes must match source_version_evidence_count")
        if not self.tenant_isolation_verified:
            raise ValueError("restore evidence must verify tenant isolation")
        if not self.disabled_state_restore_verified:
            raise ValueError("restore evidence must verify disabled-state restore behavior")
        if not self.legal_hold_restore_verified:
            raise ValueError("restore evidence must verify Legal Hold state")
        return self


class KnowledgeBaseArticlesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_FEATURE_ID
    articles: list[KnowledgeBaseArticleView]
    source_version_evidence_hashes: list[str]
    restore_evidence_hash: str
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
        current_source_object_id=record.current_source_object_id,
        current_source_version_id=record.current_source_version_id,
        current_source_object_type=record.current_source_object_type,
        source_version_evidence_hash=build_source_version_evidence_stub(record).evidence_hash,
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
        source_records = {record.metadata.object_id: record for record in demo_knowledge_base_source_object_records()}
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
                    current_source_object_id="kb-article-version-backup-runbook-v1-demo",
                    current_source_version_id=source_records[
                        "kb-article-version-backup-runbook-v1-demo"
                    ].metadata.version_id,
                    current_source_manifest_hash=source_records[
                        "kb-article-version-backup-runbook-v1-demo"
                    ].metadata.manifest_hash,
                    current_content_hash=source_records[
                        "kb-article-version-backup-runbook-v1-demo"
                    ].metadata.content_hash,
                    current_acl_version=source_records[
                        "kb-article-version-backup-runbook-v1-demo"
                    ].metadata.acl_version,
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
                    current_source_object_id="kb-article-version-security-baseline-v1-demo",
                    current_source_version_id=source_records[
                        "kb-article-version-security-baseline-v1-demo"
                    ].metadata.version_id,
                    current_source_manifest_hash=source_records[
                        "kb-article-version-security-baseline-v1-demo"
                    ].metadata.manifest_hash,
                    current_content_hash=source_records[
                        "kb-article-version-security-baseline-v1-demo"
                    ].metadata.content_hash,
                    current_acl_version=source_records[
                        "kb-article-version-security-baseline-v1-demo"
                    ].metadata.acl_version,
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
                    current_source_object_id="kb-article-version-other-tenant-v1",
                    current_source_version_id=source_records["kb-article-version-other-tenant-v1"].metadata.version_id,
                    current_source_manifest_hash=source_records[
                        "kb-article-version-other-tenant-v1"
                    ].metadata.manifest_hash,
                    current_content_hash=source_records["kb-article-version-other-tenant-v1"].metadata.content_hash,
                    current_acl_version=source_records["kb-article-version-other-tenant-v1"].metadata.acl_version,
                    published_at_utc="2026-06-12T08:10:00Z",
                ),
            )
        )

    def list_articles(self, *, tenant_id: str) -> Sequence[KnowledgeBaseArticleRecord]:
        return tuple(article for article in self._articles if article.tenant_id == tenant_id)


class KnowledgeBaseArticleService:
    def __init__(
        self,
        *,
        repository: KnowledgeBaseArticleRepository,
        source_repository: SourceObjectRepository,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.repository = repository
        self.source_repository = source_repository
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
            and record.current_source_object_id in user_context.readable_object_ids
        ]
        source_evidences = [self.source_version_evidence(record) for record in records]
        evidence_by_article = {evidence.article_object_id: evidence for evidence in source_evidences}
        views = [
            knowledge_base_article_view(record).model_copy(
                update={"source_version_evidence_hash": evidence_by_article[record.object_id].evidence_hash}
            )
            for record in records
        ]
        source_object_ids = [
            source_object_id
            for record in records
            for source_object_id in (record.object_id, record.current_version_object_id)
        ]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
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
                "source_version_evidence_hashes": sorted(evidence.evidence_hash for evidence in source_evidences),
                "restore_evidence_hash": restore_evidence.evidence_hash,
                "continuity_domain": restore_evidence.continuity_domain,
            },
        )
        return KnowledgeBaseArticlesResponse(
            tenant_id=user_context.tenant_id,
            articles=views,
            source_version_evidence_hashes=sorted(evidence.evidence_hash for evidence in source_evidences),
            restore_evidence_hash=restore_evidence.evidence_hash,
            audit_event_id=event.event_id,
        )

    def source_version_evidence(self, record: KnowledgeBaseArticleRecord) -> KnowledgeBaseSourceVersionEvidence:
        source_record = self.source_repository.get(
            tenant_id=record.tenant_id,
            object_id=record.current_source_object_id,
            version_id=record.current_source_version_id,
        )
        return build_knowledge_base_source_version_evidence(record, source_record)


def default_knowledge_base_enabled_features() -> dict[str, bool]:
    return {KB_ARTICLES_FEATURE_ID: True}


def build_knowledge_base_source_version_evidence(
    article: KnowledgeBaseArticleRecord,
    source_record: SourceObjectRecord,
) -> KnowledgeBaseSourceVersionEvidence:
    metadata = source_record.metadata
    expected_manifest_hash = build_source_object_manifest_hash(metadata)
    expected_content_hash = sha256_bytes(source_object_content_bytes(source_record))
    mismatches: list[str] = []
    if metadata.tenant_id != article.tenant_id:
        mismatches.append("tenant_id")
    if metadata.object_id != article.current_source_object_id:
        mismatches.append("source_object_id")
    if metadata.version_id != article.current_source_version_id:
        mismatches.append("source_version_id")
    if metadata.object_id != article.current_version_object_id:
        mismatches.append("article_version_object_id")
    if metadata.object_type != article.current_source_object_type:
        mismatches.append("source_object_type")
    if (
        metadata.manifest_hash != article.current_source_manifest_hash
        or metadata.manifest_hash != expected_manifest_hash
    ):
        mismatches.append("source_manifest_hash")
    if metadata.content_hash != article.current_content_hash or metadata.content_hash != expected_content_hash:
        mismatches.append("content_hash")
    if metadata.acl_version != article.current_acl_version:
        mismatches.append("acl_version")
    if metadata.classification != article.data_classification:
        mismatches.append("data_classification")
    if metadata.retention_policy_id != article.retention_policy_id:
        mismatches.append("retention_policy_id")
    if metadata.legal_hold_state.value != article.legal_hold_state:
        mismatches.append("legal_hold_state")
    if mismatches:
        raise ValueError(f"knowledge base source version evidence mismatch: {', '.join(sorted(mismatches))}")

    draft = KnowledgeBaseSourceVersionEvidence(
        tenant_id=article.tenant_id,
        article_object_id=article.object_id,
        article_version_object_id=article.current_version_object_id,
        source_object_id=metadata.object_id,
        source_version_id=metadata.version_id,
        source_object_type=metadata.object_type,
        source_manifest_hash=metadata.manifest_hash,
        content_hash=metadata.content_hash,
        acl_version=metadata.acl_version,
        data_classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state.value,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_version_evidence_hash(draft)})


def build_source_version_evidence_stub(article: KnowledgeBaseArticleRecord) -> KnowledgeBaseSourceVersionEvidence:
    draft = KnowledgeBaseSourceVersionEvidence(
        tenant_id=article.tenant_id,
        article_object_id=article.object_id,
        article_version_object_id=article.current_version_object_id,
        source_object_id=article.current_source_object_id,
        source_version_id=article.current_source_version_id,
        source_object_type=article.current_source_object_type,
        source_manifest_hash=article.current_source_manifest_hash,
        content_hash=article.current_content_hash,
        acl_version=article.current_acl_version,
        data_classification=article.data_classification,
        retention_policy_id=article.retention_policy_id,
        legal_hold_state=article.legal_hold_state,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_version_evidence_hash(draft)})


def build_source_version_evidence_hash(evidence: KnowledgeBaseSourceVersionEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_knowledge_base_restore_evidence(
    *,
    tenant_id: str,
    articles: Sequence[KnowledgeBaseArticleRecord],
    source_evidences: Sequence[KnowledgeBaseSourceVersionEvidence],
    restore_drill_report_hash: str,
    audit_chain_ref: str,
) -> KnowledgeBaseRestoreEvidence:
    if any(article.tenant_id != tenant_id for article in articles):
        raise ValueError("knowledge base restore evidence cannot mix tenants")
    if any(evidence.tenant_id != tenant_id for evidence in source_evidences):
        raise ValueError("knowledge base restore evidence cannot mix source evidence tenants")
    article_ids = {article.object_id for article in articles}
    evidence_article_ids = {evidence.article_object_id for evidence in source_evidences}
    if article_ids != evidence_article_ids:
        raise ValueError("knowledge base restore evidence must cover every article")

    row_count_payload = {
        "article_count": len(articles),
        "article_version_count": len(articles),
        "source_version_evidence_count": len(source_evidences),
        "tenant_id": tenant_id,
    }
    checksum_payload = [
        {
            "article_object_id": evidence.article_object_id,
            "article_version_object_id": evidence.article_version_object_id,
            "source_manifest_hash": evidence.source_manifest_hash,
            "content_hash": evidence.content_hash,
            "evidence_hash": evidence.evidence_hash,
        }
        for evidence in sorted(source_evidences, key=lambda item: item.article_object_id)
    ]
    draft = KnowledgeBaseRestoreEvidence(
        tenant_id=tenant_id,
        article_count=len(articles),
        article_version_count=len(articles),
        source_version_evidence_count=len(source_evidences),
        source_version_evidence_hashes=tuple(sorted(evidence.evidence_hash for evidence in source_evidences)),
        restore_drill_report_hash=restore_drill_report_hash,
        row_count_hash=stable_hash(canonical_json(row_count_payload)),
        checksum_manifest_hash=stable_hash(canonical_json(checksum_payload)),
        tenant_isolation_verified=True,
        disabled_state_restore_verified=True,
        legal_hold_restore_verified=True,
        audit_chain_ref=audit_chain_ref,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_restore_evidence_hash(draft)})


def build_restore_evidence_hash(evidence: KnowledgeBaseRestoreEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def demo_knowledge_base_source_object_repository() -> InMemorySourceObjectRepository:
    return InMemorySourceObjectRepository(records=demo_knowledge_base_source_object_records())


def demo_knowledge_base_source_object_records() -> tuple[SourceObjectRecord, ...]:
    return (
        _knowledge_base_source_record(
            tenant_id="tenant-demo",
            object_id="kb-article-version-backup-runbook-v1-demo",
            title="Backup Restore Runbook v1",
            text="Backup restore runbook source content.",
            audit_chain_ref="audit:kb-article-version-backup-runbook-v1-demo",
        ),
        _knowledge_base_source_record(
            tenant_id="tenant-demo",
            object_id="kb-article-version-security-baseline-v1-demo",
            title="Security Baseline v1",
            text="Security baseline source content.",
            audit_chain_ref="audit:kb-article-version-security-baseline-v1-demo",
        ),
        _knowledge_base_source_record(
            tenant_id="tenant-other",
            object_id="kb-article-version-other-tenant-v1",
            title="Other Tenant Article v1",
            text="Other tenant source content.",
            audit_chain_ref="audit:kb-article-version-other-tenant-v1",
        ),
    )


def _knowledge_base_source_record(
    *,
    tenant_id: str,
    object_id: str,
    title: str,
    text: str,
    audit_chain_ref: str,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.WIKI,
        version_id="v1",
        title=title,
        owner_principal_id="user-demo" if tenant_id == "tenant-demo" else "user-other",
        created_by="system",
        created_at_utc="2026-06-12T08:00:00Z",
        updated_at_utc="2026-06-12T08:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{tenant_id}/internal/v1",
        manifest_hash=ZERO_HASH,
        audit_chain_ref=audit_chain_ref,
        source_system="collabio",
        mime_type="text/plain",
        acl_hash=stable_hash(f"{tenant_id}:{object_id}:acl"),
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )
