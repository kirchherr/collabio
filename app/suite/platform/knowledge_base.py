from __future__ import annotations

import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

import psycopg
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    InMemorySourceObjectWriteReceiptStore,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteDeniedError,
    SourceObjectWriteGuard,
    SourceObjectWriteReceiptStore,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
    source_object_content_bytes,
)

KNOWLEDGE_BASE_MODULE_ID = "knowledge_base"
KB_ARTICLES_FEATURE_ID = "knowledge_base.articles.read"
KB_ARTICLES_WRITE_FEATURE_ID = "knowledge_base.articles.write"
KB_ARTICLE_OBJECT_TYPE = "kb.article"
KB_ARTICLE_VERSION_OBJECT_TYPE = "kb.article_version"
KB_ARTICLE_SCHEMA_VERSION = "kb_article.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")
ZERO_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
KB_WRITE_DRY_RUN_REQUIRED_EVIDENCE = (
    "human_approval_reference",
    "write_approval_ledger_entry",
    "source_object_write_guard",
    "source_version_evidence_persisted",
    "restore_evidence_refreshed",
    "audit_event_hash",
)
KB_SOURCE_OBJECT_WRITE_GUARD_REQUIRED_EVIDENCE = (
    "approved_write_approval_ledger_entry",
    "expected_current_version_match",
    "source_object_metadata_guard",
    "proposed_source_version_evidence_hash",
    "current_restore_evidence_hash",
    "retention_policy_evaluation",
    "legal_hold_evaluation",
)
KB_WRITE_APPROVAL_TRANSITION_REQUIRED_EVIDENCE = (
    "dry_run_write_approval_evidence_hash",
    "human_approval_reference",
    "current_restore_evidence_hash",
    "expected_current_version_match",
    "approved_write_approval_ledger_entry",
    "audit_event_hash",
)
KB_WRITE_REFRESH_PREVIEW_REQUIRED_EVIDENCE = (
    "approved_write_approval_ledger_entry",
    "expected_current_version_match",
    "current_restore_evidence_hash",
    "projected_source_version_evidence_hashes",
    "projected_restore_evidence_preview_hash",
    "source_object_write_guard_still_required_before_persistence",
    "audit_event_hash",
)
KB_WRITE_EXECUTION_SKELETON_REQUIRED_EVIDENCE = (
    "approved_write_approval_ledger_entry",
    "source_object_write_guard_decision",
    "source_object_write_guard_ref",
    "restore_evidence_refresh_preview_hash",
    "explicit_human_confirmation_reference",
    "write_execution_adapter_not_enabled",
    "post_write_source_restore_evidence_refresh_required",
    "audit_event_hash",
)
KB_WRITE_EXECUTION_REQUIRED_EVIDENCE = (
    "approved_write_approval_ledger_entry",
    "source_object_write_guard_decision",
    "source_object_write_guard_ref",
    "source_object_write_receipt_hash",
    "restore_evidence_refresh_preview_hash",
    "write_execution_plan_hash",
    "explicit_human_confirmation_reference",
    "source_object_persisted",
    "article_metadata_persisted",
    "source_version_evidence_refreshed",
    "restore_evidence_refreshed",
    "rag_indexing_disabled",
    "audit_event_hash",
)


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


class KnowledgeBaseWriteOperation(StrEnum):
    CREATE = "create"
    EDIT = "edit"


class KnowledgeBaseWriteApprovalState(StrEnum):
    DRY_RUN = "dry_run"
    APPROVED_FOR_WRITE = "approved_for_write"
    REJECTED = "rejected"
    EXPIRED = "expired"


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


class KnowledgeBaseEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    continuity_domain: str = "knowledge_base_content"
    source_version_evidence: list[KnowledgeBaseSourceVersionEvidence]
    restore_evidence: KnowledgeBaseRestoreEvidence
    audit_event_id: str


class KnowledgeBaseWriteApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_reference: str
    reason: str
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    article_key: str
    title: str
    proposed_version_object_id: str
    proposed_version_label: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    proposed_source_object_type: SourceObjectType = SourceObjectType.WIKI
    proposed_source_manifest_hash: str
    proposed_content_hash: str
    proposed_acl_version: int = Field(ge=1)
    expected_current_version_object_id: str | None = None
    data_classification: DataClass = DataClass.INTERNAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    source_system: str = "native"

    @field_validator(
        "approval_reference",
        "article_object_id",
        "article_key",
        "title",
        "proposed_version_object_id",
        "proposed_version_label",
        "proposed_source_object_id",
        "proposed_source_version_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base write approval command fields must not be empty")
        return value

    @field_validator("approval_reference")
    @classmethod
    def validate_approval_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("approval_reference must be a namespaced reference")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value

    @field_validator("proposed_source_manifest_hash", "proposed_content_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("proposed source hashes must be sha256 references")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_internal_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.INTERNAL:
            raise ValueError("knowledge base write dry-run only accepts internal classification")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("knowledge base write dry-run requires rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("knowledge base write dry-run legal_hold_state must be none or active")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write dry-run source_system must be lowercase and non-empty")
        return value

    @model_validator(mode="after")
    def require_write_safety_contract(self) -> KnowledgeBaseWriteApprovalCommand:
        if self.proposed_source_object_id != self.proposed_version_object_id:
            raise ValueError("proposed source object must be the proposed kb.article_version object")
        if self.operation == KnowledgeBaseWriteOperation.EDIT and self.expected_current_version_object_id is None:
            raise ValueError("edit dry-run requires expected_current_version_object_id")
        if self.operation == KnowledgeBaseWriteOperation.CREATE and self.expected_current_version_object_id is not None:
            raise ValueError("create dry-run must not include expected_current_version_object_id")
        return self


class KnowledgeBaseWriteDryRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_WRITE_FEATURE_ID
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    proposed_version_object_id: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    dry_run: bool = True
    persistence_allowed: bool = False
    rag_indexing_allowed: bool = False
    source_authority_verified: bool = False
    approval_reference: str
    command_hash: str
    proposed_source_version_evidence_hash: str
    current_restore_evidence_hash: str
    write_approval_evidence_hash: str
    required_evidence: tuple[str, ...] = KB_WRITE_DRY_RUN_REQUIRED_EVIDENCE
    audit_event_id: str


class KnowledgeBaseWriteApprovalTransitionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_write_approval_evidence_hash: str
    approval_reference: str
    reason: str

    @field_validator("dry_run_write_approval_evidence_hash")
    @classmethod
    def validate_dry_run_hash(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("dry_run_write_approval_evidence_hash must be a sha256 reference")
        return value

    @field_validator("approval_reference")
    @classmethod
    def validate_approval_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("approval_reference must be a namespaced reference")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value


class KnowledgeBaseWriteApprovalTransitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_WRITE_FEATURE_ID
    dry_run_write_approval_evidence_hash: str
    approved_write_approval_evidence_hash: str
    approval_state: KnowledgeBaseWriteApprovalState
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    proposed_version_object_id: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    persistence_allowed: bool
    rag_indexing_allowed: bool
    source_authority_verified: bool
    command_hash: str
    proposed_source_version_evidence_hash: str
    current_restore_evidence_hash: str
    required_evidence: tuple[str, ...] = KB_WRITE_APPROVAL_TRANSITION_REQUIRED_EVIDENCE
    audit_event_id: str


class KnowledgeBaseEvidenceRefreshPreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_write_approval_evidence_hash: str
    preview_reference: str
    reason: str

    @field_validator("approved_write_approval_evidence_hash")
    @classmethod
    def validate_approved_evidence_hash(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("approved_write_approval_evidence_hash must be a sha256 reference")
        return value

    @field_validator("preview_reference")
    @classmethod
    def validate_preview_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("preview_reference must be a namespaced reference")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value


class KnowledgeBaseEvidenceRefreshPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_WRITE_FEATURE_ID
    approved_write_approval_evidence_hash: str
    transition_source_evidence_hash: str
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    expected_current_version_object_id: str | None = None
    proposed_version_object_id: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    command_hash: str
    preview_command_hash: str
    proposed_source_version_evidence_hash: str
    current_source_version_evidence_hashes: tuple[str, ...]
    projected_source_version_evidence_hashes: tuple[str, ...]
    current_restore_evidence_hash: str
    projected_restore_evidence_preview_hash: str
    article_count_before: int = Field(ge=0)
    article_count_after: int = Field(ge=0)
    article_version_count_before: int = Field(ge=0)
    article_version_count_after: int = Field(ge=0)
    source_version_evidence_count_before: int = Field(ge=0)
    source_version_evidence_count_after: int = Field(ge=0)
    preview_only: bool = True
    article_source_writes_allowed: bool = False
    evidence_persistence_allowed: bool = False
    rag_indexing_allowed: bool = False
    source_authority_verified: bool = False
    required_evidence: tuple[str, ...] = KB_WRITE_REFRESH_PREVIEW_REQUIRED_EVIDENCE
    audit_event_id: str
    schema_version: str = "knowledge_base_evidence_refresh_preview.v1"

    @field_validator(
        "tenant_id",
        "article_object_id",
        "proposed_version_object_id",
        "proposed_source_object_id",
        "proposed_source_version_id",
        "audit_event_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base refresh preview fields must not be empty")
        return value

    @field_validator(
        "approved_write_approval_evidence_hash",
        "transition_source_evidence_hash",
        "command_hash",
        "preview_command_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
        "projected_restore_evidence_preview_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base refresh preview hashes must be sha256 references")
        return value

    @field_validator("current_source_version_evidence_hashes", "projected_source_version_evidence_hashes")
    @classmethod
    def validate_source_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source version evidence hashes must be unique")
        for evidence_hash in value:
            if not SHA256_REF_PATTERN.fullmatch(evidence_hash):
                raise ValueError("source version evidence hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_preview(self) -> KnowledgeBaseEvidenceRefreshPreviewResponse:
        if not self.preview_only:
            raise ValueError("knowledge base refresh preview must be preview_only")
        if self.article_source_writes_allowed:
            raise ValueError("knowledge base refresh preview cannot allow article/source writes")
        if self.evidence_persistence_allowed:
            raise ValueError("knowledge base refresh preview cannot allow evidence persistence")
        if self.rag_indexing_allowed:
            raise ValueError("knowledge base refresh preview cannot allow RAG indexing")
        if self.source_authority_verified:
            raise ValueError("knowledge base refresh preview cannot verify source authority")
        if self.operation == KnowledgeBaseWriteOperation.EDIT:
            if self.article_count_after != self.article_count_before:
                raise ValueError("edit refresh preview must not change article count")
            if self.article_version_count_after != self.article_version_count_before:
                raise ValueError("edit refresh preview must not change article version count in preview")
            if self.source_version_evidence_count_after != self.source_version_evidence_count_before:
                raise ValueError("edit refresh preview must not change source evidence count")
        if self.operation == KnowledgeBaseWriteOperation.CREATE:
            if self.article_count_after != self.article_count_before + 1:
                raise ValueError("create refresh preview must project one additional article")
            if self.article_version_count_after != self.article_version_count_before + 1:
                raise ValueError("create refresh preview must project one additional article version")
            if self.source_version_evidence_count_after != self.source_version_evidence_count_before + 1:
                raise ValueError("create refresh preview must project one additional source evidence")
        if len(self.current_source_version_evidence_hashes) != self.source_version_evidence_count_before:
            raise ValueError("current source evidence hashes must match before count")
        if len(self.projected_source_version_evidence_hashes) != self.source_version_evidence_count_after:
            raise ValueError("projected source evidence hashes must match after count")
        return self


class KnowledgeBaseWriteApprovalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    approval_reference: str
    operation: KnowledgeBaseWriteOperation
    approval_state: KnowledgeBaseWriteApprovalState = KnowledgeBaseWriteApprovalState.DRY_RUN
    article_object_id: str
    article_key: str
    title: str
    expected_current_version_object_id: str | None = None
    proposed_version_object_id: str
    proposed_version_label: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    proposed_source_object_type: SourceObjectType = SourceObjectType.WIKI
    proposed_source_manifest_hash: str
    proposed_content_hash: str
    proposed_acl_version: int = Field(ge=1)
    command_hash: str
    proposed_source_version_evidence_hash: str
    current_restore_evidence_hash: str
    source_object_write_guard_ref: str
    transition_source_evidence_hash: str | None = None
    requested_by: str
    persistence_allowed: bool = False
    rag_indexing_allowed: bool = False
    source_authority_verified: bool = False
    audit_event_id: str
    audit_chain_ref: str
    source_system: str = "native"
    evidence_hash: str
    schema_version: str = "knowledge_base_write_approval_evidence.v1"

    @field_validator(
        "tenant_id",
        "approval_reference",
        "article_object_id",
        "article_key",
        "title",
        "proposed_version_object_id",
        "proposed_version_label",
        "proposed_source_object_id",
        "proposed_source_version_id",
        "requested_by",
        "audit_event_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base write approval evidence fields must not be empty")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write approval evidence source_system must be lowercase and non-empty")
        return value

    @field_validator(
        "approval_reference",
        "source_object_write_guard_ref",
        "audit_chain_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write approval evidence references must be namespaced")
        return value

    @field_validator(
        "proposed_source_manifest_hash",
        "proposed_content_hash",
        "command_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write approval evidence hashes must be sha256 references")
        return value

    @field_validator("transition_source_evidence_hash")
    @classmethod
    def validate_transition_source_hash(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("transition_source_evidence_hash must be a sha256 reference")
        return value

    @model_validator(mode="after")
    def require_approval_ledger_safety(self) -> KnowledgeBaseWriteApprovalEvidence:
        if self.proposed_source_object_id != self.proposed_version_object_id:
            raise ValueError("proposed source object must be the proposed kb.article_version object")
        if self.operation == KnowledgeBaseWriteOperation.EDIT and self.expected_current_version_object_id is None:
            raise ValueError("edit approval evidence requires expected_current_version_object_id")
        if self.operation == KnowledgeBaseWriteOperation.CREATE and self.expected_current_version_object_id is not None:
            raise ValueError("create approval evidence must not include expected_current_version_object_id")
        if self.approval_state == KnowledgeBaseWriteApprovalState.DRY_RUN and self.persistence_allowed:
            raise ValueError("dry-run approval evidence cannot allow persistence")
        if self.approval_state == KnowledgeBaseWriteApprovalState.DRY_RUN and self.transition_source_evidence_hash:
            raise ValueError("dry-run approval evidence cannot reference a transition source")
        if (
            self.approval_state != KnowledgeBaseWriteApprovalState.DRY_RUN
            and self.transition_source_evidence_hash is None
        ):
            raise ValueError("approval state transitions require transition_source_evidence_hash")
        if self.transition_source_evidence_hash == self.evidence_hash:
            raise ValueError("transition_source_evidence_hash cannot equal evidence_hash")
        if self.approval_state != KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE and self.rag_indexing_allowed:
            raise ValueError("RAG indexing cannot be allowed before write approval")
        return self


class KnowledgeBaseSourceObjectWriteGuardDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_write_guard_ref: str
    allowed: bool
    blocking_reasons: tuple[str, ...]
    write_approval_evidence_hash: str
    approval_state: KnowledgeBaseWriteApprovalState
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    expected_current_version_object_id: str | None = None
    proposed_source_object_id: str
    proposed_source_version_id: str
    proposed_source_version_evidence_hash: str
    current_restore_evidence_hash: str
    persistence_allowed: bool
    rag_indexing_allowed: bool
    source_authority_verified: bool
    required_evidence: tuple[str, ...] = KB_SOURCE_OBJECT_WRITE_GUARD_REQUIRED_EVIDENCE
    schema_version: str = "knowledge_base_source_object_write_guard.v1"

    @field_validator(
        "tenant_id",
        "article_object_id",
        "proposed_source_object_id",
        "proposed_source_version_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base source-object write guard fields must not be empty")
        return value

    @field_validator("source_object_write_guard_ref")
    @classmethod
    def validate_guard_ref(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("source_object_write_guard_ref must be namespaced")
        return value

    @field_validator(
        "write_approval_evidence_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base source-object write guard hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blocking_reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("blocking_reasons must not contain empty values")
        return value

    @model_validator(mode="after")
    def require_decision_alignment(self) -> KnowledgeBaseSourceObjectWriteGuardDecision:
        if self.allowed and self.blocking_reasons:
            raise ValueError("allowed source-object writes must not carry blocking reasons")
        if not self.allowed and not self.blocking_reasons:
            raise ValueError("blocked source-object writes require blocking reasons")
        if not self.allowed and self.persistence_allowed:
            raise ValueError("blocked source-object writes cannot allow persistence")
        if not self.allowed and self.rag_indexing_allowed:
            raise ValueError("blocked source-object writes cannot allow RAG indexing")
        if self.source_authority_verified and not self.allowed:
            raise ValueError("source authority is verified only for allowed write decisions")
        return self


class KnowledgeBaseWriteExecutionSkeletonCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_write_approval_evidence_hash: str
    source_object_write_guard_decision: KnowledgeBaseSourceObjectWriteGuardDecision
    refresh_preview_command_hash: str
    projected_restore_evidence_preview_hash: str
    execution_reference: str
    human_confirmation_reference: str
    reason: str

    @field_validator(
        "approved_write_approval_evidence_hash",
        "refresh_preview_command_hash",
        "projected_restore_evidence_preview_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution hashes must be sha256 references")
        return value

    @field_validator("execution_reference", "human_confirmation_reference")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution references must be namespaced")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value


class KnowledgeBaseWriteExecutionSkeletonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_WRITE_FEATURE_ID
    execution_reference: str
    human_confirmation_reference: str
    approved_write_approval_evidence_hash: str
    transition_source_evidence_hash: str
    source_object_write_guard_ref: str
    refresh_preview_command_hash: str
    projected_restore_evidence_preview_hash: str
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    expected_current_version_object_id: str | None = None
    proposed_version_object_id: str
    proposed_source_object_id: str
    proposed_source_version_id: str
    command_hash: str
    execution_command_hash: str
    execution_plan_hash: str
    proposed_source_version_evidence_hash: str
    current_restore_evidence_hash: str
    preconditions_verified: bool
    source_object_write_guard_verified: bool
    human_confirmation_verified: bool
    source_authority_verified: bool
    execution_allowed: bool = False
    article_source_writes_allowed: bool = False
    article_metadata_persistence_allowed: bool = False
    source_object_persistence_allowed: bool = False
    evidence_persistence_allowed: bool = False
    rag_indexing_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    required_evidence: tuple[str, ...] = KB_WRITE_EXECUTION_SKELETON_REQUIRED_EVIDENCE
    audit_event_id: str
    schema_version: str = "knowledge_base_write_execution_skeleton.v1"

    @field_validator(
        "tenant_id",
        "article_object_id",
        "proposed_version_object_id",
        "proposed_source_object_id",
        "proposed_source_version_id",
        "audit_event_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base write execution fields must not be empty")
        return value

    @field_validator("execution_reference", "human_confirmation_reference", "source_object_write_guard_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution references must be namespaced")
        return value

    @field_validator(
        "approved_write_approval_evidence_hash",
        "transition_source_evidence_hash",
        "refresh_preview_command_hash",
        "projected_restore_evidence_preview_hash",
        "command_hash",
        "execution_command_hash",
        "execution_plan_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blocking_reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("blocking_reasons must not contain empty values")
        return value

    @model_validator(mode="after")
    def require_skeleton_no_write_contract(self) -> KnowledgeBaseWriteExecutionSkeletonResponse:
        if not self.preconditions_verified:
            raise ValueError("write execution skeleton must verify preconditions before returning")
        if not self.source_object_write_guard_verified:
            raise ValueError("write execution skeleton requires verified source-object guard evidence")
        if not self.human_confirmation_verified:
            raise ValueError("write execution skeleton requires explicit human confirmation")
        if not self.source_authority_verified:
            raise ValueError("write execution skeleton requires source authority from the guard decision")
        if self.execution_allowed:
            raise ValueError("write execution skeleton cannot allow execution")
        if self.article_source_writes_allowed:
            raise ValueError("write execution skeleton cannot allow article/source writes")
        if self.article_metadata_persistence_allowed:
            raise ValueError("write execution skeleton cannot allow article metadata persistence")
        if self.source_object_persistence_allowed:
            raise ValueError("write execution skeleton cannot allow source object persistence")
        if self.evidence_persistence_allowed:
            raise ValueError("write execution skeleton cannot allow evidence persistence")
        if self.rag_indexing_allowed:
            raise ValueError("write execution skeleton cannot allow RAG indexing")
        if not self.blocking_reasons:
            raise ValueError("write execution skeleton must explain why execution remains blocked")
        return self


class KnowledgeBaseWriteExecutionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_write_approval_evidence_hash: str
    source_object_write_guard_decision: KnowledgeBaseSourceObjectWriteGuardDecision
    refresh_preview_command_hash: str
    projected_restore_evidence_preview_hash: str
    execution_skeleton_command_hash: str
    execution_plan_hash: str
    execution_reference: str
    human_confirmation_reference: str
    proposed_source_record: SourceObjectRecord
    reason: str

    @field_validator(
        "approved_write_approval_evidence_hash",
        "refresh_preview_command_hash",
        "projected_restore_evidence_preview_hash",
        "execution_skeleton_command_hash",
        "execution_plan_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution hashes must be sha256 references")
        return value

    @field_validator("execution_reference", "human_confirmation_reference")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution references must be namespaced")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value


class KnowledgeBaseWriteExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = KNOWLEDGE_BASE_MODULE_ID
    feature_id: str = KB_ARTICLES_WRITE_FEATURE_ID
    execution_reference: str
    human_confirmation_reference: str
    approved_write_approval_evidence_hash: str
    transition_source_evidence_hash: str
    source_object_write_guard_ref: str
    source_object_write_receipt_hash: str
    refresh_preview_command_hash: str
    projected_restore_evidence_preview_hash: str
    execution_skeleton_command_hash: str
    execution_plan_hash: str
    execution_command_hash: str
    operation: KnowledgeBaseWriteOperation
    article_object_id: str
    previous_version_object_id: str | None = None
    current_version_object_id: str
    current_source_object_id: str
    current_source_version_id: str
    proposed_source_version_evidence_hash: str
    refreshed_source_version_evidence_hash: str
    previous_restore_evidence_hash: str
    refreshed_restore_evidence_hash: str
    source_version_evidence_hashes_after: tuple[str, ...]
    article_count_after: int = Field(ge=0)
    article_version_count_after: int = Field(ge=0)
    source_version_evidence_count_after: int = Field(ge=0)
    execution_allowed: bool = True
    source_object_persisted: bool = True
    source_object_write_receipt_persisted: bool = True
    article_metadata_persisted: bool = True
    article_version_metadata_persisted: bool = True
    source_version_evidence_refreshed: bool = True
    restore_evidence_refreshed: bool = True
    rag_indexing_allowed: bool = False
    search_indexing_allowed: bool = False
    required_evidence: tuple[str, ...] = KB_WRITE_EXECUTION_REQUIRED_EVIDENCE
    audit_event_id: str
    schema_version: str = "knowledge_base_write_execution.v1"

    @field_validator(
        "tenant_id",
        "article_object_id",
        "current_version_object_id",
        "current_source_object_id",
        "current_source_version_id",
        "audit_event_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base write execution response fields must not be empty")
        return value

    @field_validator("execution_reference", "human_confirmation_reference", "source_object_write_guard_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution references must be namespaced")
        return value

    @field_validator(
        "approved_write_approval_evidence_hash",
        "transition_source_evidence_hash",
        "source_object_write_receipt_hash",
        "refresh_preview_command_hash",
        "projected_restore_evidence_preview_hash",
        "execution_skeleton_command_hash",
        "execution_plan_hash",
        "execution_command_hash",
        "proposed_source_version_evidence_hash",
        "refreshed_source_version_evidence_hash",
        "previous_restore_evidence_hash",
        "refreshed_restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("knowledge base write execution response hashes must be sha256 references")
        return value

    @field_validator("source_version_evidence_hashes_after")
    @classmethod
    def validate_source_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source version evidence hashes must be unique")
        for evidence_hash in value:
            if not SHA256_REF_PATTERN.fullmatch(evidence_hash):
                raise ValueError("source version evidence hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_execution_commit_contract(self) -> KnowledgeBaseWriteExecutionResponse:
        if not self.execution_allowed:
            raise ValueError("knowledge base write execution response must represent an executed write")
        if not self.source_object_persisted:
            raise ValueError("knowledge base write execution must persist the source object")
        if not self.source_object_write_receipt_persisted:
            raise ValueError("knowledge base write execution must persist the source object write receipt")
        if not self.article_metadata_persisted:
            raise ValueError("knowledge base write execution must persist article metadata")
        if not self.article_version_metadata_persisted:
            raise ValueError("knowledge base write execution must persist article version metadata")
        if not self.source_version_evidence_refreshed:
            raise ValueError("knowledge base write execution must refresh source-version evidence")
        if not self.restore_evidence_refreshed:
            raise ValueError("knowledge base write execution must refresh restore evidence")
        if self.rag_indexing_allowed:
            raise ValueError("knowledge base write execution must not enable RAG indexing")
        if self.search_indexing_allowed:
            raise ValueError("knowledge base write execution must not enable search indexing")
        if self.refreshed_source_version_evidence_hash != self.proposed_source_version_evidence_hash:
            raise ValueError("refreshed source-version evidence must match approved proposed evidence")
        if len(self.source_version_evidence_hashes_after) != self.source_version_evidence_count_after:
            raise ValueError("source_version_evidence_hashes_after must match source evidence count")
        return self


class KnowledgeBaseArticleRepository(Protocol):
    def list_articles(self, *, tenant_id: str) -> Sequence[KnowledgeBaseArticleRecord]:
        pass

    def apply_write(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        source_record: SourceObjectRecord,
        audit_chain_ref: str,
    ) -> KnowledgeBaseArticleRecord:
        pass


class KnowledgeBaseWriteApprovalLedger(Protocol):
    def append(self, evidence: KnowledgeBaseWriteApprovalEvidence) -> KnowledgeBaseWriteApprovalEvidence:
        pass

    def get(self, *, tenant_id: str, evidence_hash: str) -> KnowledgeBaseWriteApprovalEvidence:
        pass

    def list_evidence(self, *, tenant_id: str) -> Sequence[KnowledgeBaseWriteApprovalEvidence]:
        pass


def knowledge_base_audit_source_object_ids(records: Sequence[KnowledgeBaseArticleRecord]) -> list[str]:
    source_object_ids: list[str] = []
    seen: set[str] = set()
    for record in records:
        for object_id in (record.object_id, record.current_version_object_id, record.current_source_object_id):
            if object_id not in seen:
                source_object_ids.append(object_id)
                seen.add(object_id)
    return source_object_ids


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


def require_source_record_matches_write_evidence(
    *,
    tenant_id: str,
    evidence: KnowledgeBaseWriteApprovalEvidence,
    source_record: SourceObjectRecord,
) -> SourceObjectMetadata:
    metadata = source_record.metadata
    if metadata.tenant_id != tenant_id:
        raise ValueError("source object tenant does not match write tenant")
    if metadata.object_id != evidence.proposed_source_object_id:
        raise ValueError("source object ID does not match approved write evidence")
    if metadata.version_id != evidence.proposed_source_version_id:
        raise ValueError("source version ID does not match approved write evidence")
    if metadata.object_type != evidence.proposed_source_object_type:
        raise ValueError("source object type does not match approved write evidence")
    if metadata.manifest_hash != evidence.proposed_source_manifest_hash:
        raise ValueError("source manifest hash does not match approved write evidence")
    if metadata.content_hash != evidence.proposed_content_hash:
        raise ValueError("source content hash does not match approved write evidence")
    if metadata.acl_version != evidence.proposed_acl_version:
        raise ValueError("source ACL version does not match approved write evidence")
    return metadata


def build_created_article_from_write_evidence(
    *,
    tenant_id: str,
    evidence: KnowledgeBaseWriteApprovalEvidence,
    source_record: SourceObjectRecord,
    audit_chain_ref: str,
) -> KnowledgeBaseArticleRecord:
    metadata = require_source_record_matches_write_evidence(
        tenant_id=tenant_id,
        evidence=evidence,
        source_record=source_record,
    )
    if metadata.source_system != evidence.source_system:
        raise ValueError("source system does not match approved write evidence")
    return KnowledgeBaseArticleRecord(
        tenant_id=tenant_id,
        object_id=evidence.article_object_id,
        owner_principal_id=metadata.owner_principal_id,
        created_by=metadata.created_by,
        created_at_utc=metadata.created_at_utc,
        updated_at_utc=metadata.updated_at_utc,
        data_classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state.value,
        kms_key_ref=metadata.kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=evidence.source_system,
        article_key=evidence.article_key,
        title=evidence.title,
        current_version_object_id=evidence.proposed_version_object_id,
        current_version_label=evidence.proposed_version_label,
        current_source_object_id=evidence.proposed_source_object_id,
        current_source_version_id=evidence.proposed_source_version_id,
        current_source_object_type=evidence.proposed_source_object_type,
        current_source_manifest_hash=metadata.manifest_hash,
        current_content_hash=metadata.content_hash,
        current_acl_version=metadata.acl_version,
        published_at_utc=metadata.updated_at_utc,
    )


def build_edited_article_from_write_evidence(
    *,
    tenant_id: str,
    evidence: KnowledgeBaseWriteApprovalEvidence,
    source_record: SourceObjectRecord,
    existing_article: KnowledgeBaseArticleRecord,
    audit_chain_ref: str,
) -> KnowledgeBaseArticleRecord:
    metadata = require_source_record_matches_write_evidence(
        tenant_id=tenant_id,
        evidence=evidence,
        source_record=source_record,
    )
    if existing_article.current_version_object_id != evidence.expected_current_version_object_id:
        raise ValueError("expected current article version does not match approved evidence")
    return existing_article.model_copy(
        update={
            "updated_at_utc": metadata.updated_at_utc,
            "current_version_object_id": evidence.proposed_version_object_id,
            "current_version_label": evidence.proposed_version_label,
            "current_source_object_id": evidence.proposed_source_object_id,
            "current_source_version_id": evidence.proposed_source_version_id,
            "current_source_object_type": evidence.proposed_source_object_type,
            "current_source_manifest_hash": metadata.manifest_hash,
            "current_content_hash": metadata.content_hash,
            "current_acl_version": metadata.acl_version,
            "audit_chain_ref": audit_chain_ref,
        }
    )


def pg_timestamp_to_utc_string(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def source_object_version_ref(article: KnowledgeBaseArticleRecord) -> str:
    return f"source:{article.current_source_object_id}:{article.current_source_version_id}"


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

    def apply_write(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        source_record: SourceObjectRecord,
        audit_chain_ref: str,
    ) -> KnowledgeBaseArticleRecord:
        articles = list(self._articles)
        if evidence.operation == KnowledgeBaseWriteOperation.CREATE:
            if any(
                article.tenant_id == tenant_id and article.object_id == evidence.article_object_id
                for article in articles
            ):
                raise ValueError("create write target article already exists")
            if any(
                article.tenant_id == tenant_id and article.article_key == evidence.article_key for article in articles
            ):
                raise ValueError("create write target article key already exists")
            created_article = build_created_article_from_write_evidence(
                tenant_id=tenant_id,
                evidence=evidence,
                source_record=source_record,
                audit_chain_ref=audit_chain_ref,
            )
            self._articles = tuple([*articles, created_article])
            return created_article

        for index, article in enumerate(articles):
            if article.tenant_id != tenant_id or article.object_id != evidence.article_object_id:
                continue
            updated_article = build_edited_article_from_write_evidence(
                tenant_id=tenant_id,
                evidence=evidence,
                source_record=source_record,
                existing_article=article,
                audit_chain_ref=audit_chain_ref,
            )
            articles[index] = updated_article
            self._articles = tuple(articles)
            return updated_article
        raise LookupError(f"knowledge base article not found: {evidence.article_object_id}")


class PgKnowledgeBaseArticleRepository:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def list_articles(self, *, tenant_id: str) -> Sequence[KnowledgeBaseArticleRecord]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            return self._list_articles(connection, tenant_id=tenant_id, for_update=False)

    def apply_write(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        source_record: SourceObjectRecord,
        audit_chain_ref: str,
    ) -> KnowledgeBaseArticleRecord:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, tenant_id)
                with connection.transaction():
                    records = list(self._list_articles(connection, tenant_id=tenant_id, for_update=True))
                    records_by_object_id = {record.object_id: record for record in records}
                    existing_article = records_by_object_id.get(evidence.article_object_id)

                    if evidence.operation == KnowledgeBaseWriteOperation.CREATE:
                        if existing_article is not None:
                            raise ValueError("create write target article already exists")
                        if any(article.article_key == evidence.article_key for article in records):
                            raise ValueError("create write target article key already exists")
                        updated_article = build_created_article_from_write_evidence(
                            tenant_id=tenant_id,
                            evidence=evidence,
                            source_record=source_record,
                            audit_chain_ref=audit_chain_ref,
                        )
                        refreshed_records = sorted(
                            [*records, updated_article],
                            key=lambda record: (record.title.lower(), record.object_id),
                        )
                        self._insert_article(connection, article=updated_article)
                    else:
                        if existing_article is None:
                            raise LookupError(f"knowledge base article not found: {evidence.article_object_id}")
                        updated_article = build_edited_article_from_write_evidence(
                            tenant_id=tenant_id,
                            evidence=evidence,
                            source_record=source_record,
                            existing_article=existing_article,
                            audit_chain_ref=audit_chain_ref,
                        )
                        refreshed_records = sorted(
                            [
                                updated_article if record.object_id == updated_article.object_id else record
                                for record in records
                            ],
                            key=lambda record: (record.title.lower(), record.object_id),
                        )

                    self._insert_article_version(connection, article=updated_article)
                    if evidence.operation == KnowledgeBaseWriteOperation.EDIT:
                        self._update_article_current_version(connection, article=updated_article)

                    refreshed_source_evidence = build_source_version_evidence_for_source_record(
                        tenant_id=tenant_id,
                        article_object_id=evidence.article_object_id,
                        article_version_object_id=evidence.proposed_version_object_id,
                        source_record=source_record,
                    )
                    if refreshed_source_evidence.evidence_hash != evidence.proposed_source_version_evidence_hash:
                        raise ValueError("post-write source-version evidence does not match approved evidence")
                    refreshed_source_evidences = [
                        (
                            refreshed_source_evidence
                            if record.object_id == updated_article.object_id
                            else build_source_version_evidence_stub(record)
                        )
                        for record in refreshed_records
                    ]
                    refreshed_restore_evidence = build_knowledge_base_restore_evidence(
                        tenant_id=tenant_id,
                        articles=refreshed_records,
                        source_evidences=refreshed_source_evidences,
                        restore_drill_report_hash=stable_hash(f"{tenant_id}:knowledge_base_content:restore-drill"),
                        audit_chain_ref="audit:knowledge-base-restore-evidence",
                    )

                    self._insert_source_version_evidence(
                        connection,
                        evidence=refreshed_source_evidence,
                        audit_chain_ref=audit_chain_ref,
                    )
                    self._insert_restore_evidence(connection, evidence=refreshed_restore_evidence)
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("knowledge base write transaction conflicts with existing metadata") from exc
        return updated_article

    def _list_articles(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        for_update: bool,
    ) -> tuple[KnowledgeBaseArticleRecord, ...]:
        lock_clause = " FOR UPDATE" if for_update else ""
        article_rows = connection.execute(
            f"""
            SELECT
                tenant_id,
                object_id,
                object_type,
                owner_principal_id,
                created_by,
                created_at_utc,
                updated_at_utc,
                data_classification,
                retention_policy_id,
                legal_hold_state,
                lifecycle_state,
                kms_key_ref,
                audit_chain_ref,
                source_system,
                schema_version,
                article_key,
                title,
                current_version_object_id,
                current_version_label,
                published_at_utc,
                status
            FROM knowledge_base.articles
            WHERE tenant_id = %s
            ORDER BY lower(title), object_id
            {lock_clause}
            """,
            (tenant_id,),
        ).fetchall()
        return tuple(
            self._article_from_row(
                article_row,
                self._latest_source_evidence_row(
                    connection,
                    tenant_id=tenant_id,
                    article_object_id=str(article_row[1]),
                    article_version_object_id=str(article_row[17]),
                ),
            )
            for article_row in article_rows
        )

    def _latest_source_evidence_row(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        article_object_id: str,
        article_version_object_id: str,
    ) -> tuple[Any, ...]:
        row = connection.execute(
            """
            SELECT
                source_object_id,
                source_version_id,
                source_object_type,
                source_manifest_hash,
                content_hash,
                acl_version
            FROM knowledge_base.source_version_evidence
            WHERE tenant_id = %s
              AND article_object_id = %s
              AND article_version_object_id = %s
            ORDER BY captured_at_utc DESC, evidence_hash DESC
            LIMIT 1
            """,
            (tenant_id, article_object_id, article_version_object_id),
        ).fetchone()
        if row is None:
            raise LookupError("knowledge base article is missing source-version evidence")
        return tuple(row)

    def _article_from_row(
        self,
        article_row: tuple[Any, ...],
        source_evidence_row: tuple[Any, ...],
    ) -> KnowledgeBaseArticleRecord:
        return KnowledgeBaseArticleRecord(
            tenant_id=str(article_row[0]),
            object_id=str(article_row[1]),
            object_type=str(article_row[2]),
            owner_principal_id=str(article_row[3]),
            created_by=str(article_row[4]),
            created_at_utc=pg_timestamp_to_utc_string(article_row[5]),
            updated_at_utc=pg_timestamp_to_utc_string(article_row[6]),
            data_classification=DataClass(str(article_row[7])),
            retention_policy_id=str(article_row[8]),
            legal_hold_state=str(article_row[9]),
            lifecycle_state=KnowledgeBaseArticleLifecycleState(str(article_row[10])),
            kms_key_ref=str(article_row[11]),
            audit_chain_ref=str(article_row[12]),
            source_system=str(article_row[13]),
            schema_version=str(article_row[14]),
            article_key=str(article_row[15]),
            title=str(article_row[16]),
            current_version_object_id=str(article_row[17]),
            current_version_label=str(article_row[18]),
            current_source_object_id=str(source_evidence_row[0]),
            current_source_version_id=str(source_evidence_row[1]),
            current_source_object_type=SourceObjectType(str(source_evidence_row[2])),
            current_source_manifest_hash=str(source_evidence_row[3]),
            current_content_hash=str(source_evidence_row[4]),
            current_acl_version=int(source_evidence_row[5]),
            published_at_utc=pg_timestamp_to_utc_string(article_row[19]) if article_row[19] is not None else None,
            status=KnowledgeBaseArticleStatus(str(article_row[20])),
        )

    def _insert_article(
        self,
        connection: psycopg.Connection[Any],
        *,
        article: KnowledgeBaseArticleRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_base.articles (
                tenant_id,
                object_id,
                object_type,
                owner_principal_id,
                created_by,
                created_at_utc,
                updated_at_utc,
                data_classification,
                retention_policy_id,
                legal_hold_state,
                lifecycle_state,
                kms_key_ref,
                audit_chain_ref,
                source_system,
                schema_version,
                article_key,
                title,
                current_version_object_id,
                current_version_label,
                published_at_utc,
                status
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                article.tenant_id,
                article.object_id,
                article.object_type,
                article.owner_principal_id,
                article.created_by,
                article.created_at_utc,
                article.updated_at_utc,
                article.data_classification,
                article.retention_policy_id,
                article.legal_hold_state,
                article.lifecycle_state,
                article.kms_key_ref,
                article.audit_chain_ref,
                article.source_system,
                article.schema_version,
                article.article_key,
                article.title,
                article.current_version_object_id,
                article.current_version_label,
                article.published_at_utc,
                article.status,
            ),
        )

    def _insert_article_version(
        self,
        connection: psycopg.Connection[Any],
        *,
        article: KnowledgeBaseArticleRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_base.article_versions (
                tenant_id,
                object_id,
                object_type,
                owner_principal_id,
                created_by,
                created_at_utc,
                updated_at_utc,
                data_classification,
                retention_policy_id,
                legal_hold_state,
                lifecycle_state,
                kms_key_ref,
                audit_chain_ref,
                source_system,
                schema_version,
                article_object_id,
                version_label,
                version_state,
                source_object_version_ref,
                content_hash,
                published_at_utc
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, 'published', %s, %s, %s
            )
            """,
            (
                article.tenant_id,
                article.current_version_object_id,
                KB_ARTICLE_VERSION_OBJECT_TYPE,
                article.owner_principal_id,
                article.created_by,
                article.updated_at_utc,
                article.updated_at_utc,
                article.data_classification,
                article.retention_policy_id,
                article.legal_hold_state,
                article.lifecycle_state,
                article.kms_key_ref,
                article.audit_chain_ref,
                article.source_system,
                "kb_article_version.v1",
                article.object_id,
                article.current_version_label,
                source_object_version_ref(article),
                article.current_content_hash,
                article.published_at_utc,
            ),
        )

    def _update_article_current_version(
        self,
        connection: psycopg.Connection[Any],
        *,
        article: KnowledgeBaseArticleRecord,
    ) -> None:
        result = connection.execute(
            """
            UPDATE knowledge_base.articles
            SET updated_at_utc = %s,
                audit_chain_ref = %s,
                current_version_object_id = %s,
                current_version_label = %s,
                published_at_utc = %s,
                status = %s
            WHERE tenant_id = %s
              AND object_id = %s
            """,
            (
                article.updated_at_utc,
                article.audit_chain_ref,
                article.current_version_object_id,
                article.current_version_label,
                article.published_at_utc,
                article.status,
                article.tenant_id,
                article.object_id,
            ),
        )
        if result.rowcount != 1:
            raise LookupError(f"knowledge base article not found: {article.object_id}")

    def _insert_source_version_evidence(
        self,
        connection: psycopg.Connection[Any],
        *,
        evidence: KnowledgeBaseSourceVersionEvidence,
        audit_chain_ref: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_base.source_version_evidence (
                tenant_id,
                article_object_id,
                article_version_object_id,
                source_object_id,
                source_version_id,
                source_object_type,
                source_manifest_hash,
                content_hash,
                acl_version,
                data_classification,
                retention_policy_id,
                legal_hold_state,
                evidence_hash,
                audit_chain_ref,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                evidence.tenant_id,
                evidence.article_object_id,
                evidence.article_version_object_id,
                evidence.source_object_id,
                evidence.source_version_id,
                evidence.source_object_type,
                evidence.source_manifest_hash,
                evidence.content_hash,
                evidence.acl_version,
                evidence.data_classification,
                evidence.retention_policy_id,
                evidence.legal_hold_state,
                evidence.evidence_hash,
                audit_chain_ref,
                evidence.schema_version,
            ),
        )

    def _insert_restore_evidence(
        self,
        connection: psycopg.Connection[Any],
        *,
        evidence: KnowledgeBaseRestoreEvidence,
    ) -> None:
        connection.execute(
            """
            INSERT INTO knowledge_base.restore_evidence (
                tenant_id,
                module_id,
                continuity_domain,
                article_count,
                article_version_count,
                source_version_evidence_count,
                source_version_evidence_hashes,
                restore_drill_report_hash,
                row_count_hash,
                checksum_manifest_hash,
                tenant_isolation_verified,
                disabled_state_restore_verified,
                legal_hold_restore_verified,
                evidence_hash,
                audit_chain_ref,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s
            )
            """,
            (
                evidence.tenant_id,
                evidence.module_id,
                evidence.continuity_domain,
                evidence.article_count,
                evidence.article_version_count,
                evidence.source_version_evidence_count,
                list(evidence.source_version_evidence_hashes),
                evidence.restore_drill_report_hash,
                evidence.row_count_hash,
                evidence.checksum_manifest_hash,
                evidence.tenant_isolation_verified,
                evidence.disabled_state_restore_verified,
                evidence.legal_hold_restore_verified,
                evidence.evidence_hash,
                evidence.audit_chain_ref,
                evidence.schema_version,
            ),
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


class InMemoryKnowledgeBaseWriteApprovalLedger:
    def __init__(self, evidences: Sequence[KnowledgeBaseWriteApprovalEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], KnowledgeBaseWriteApprovalEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(self, evidence: KnowledgeBaseWriteApprovalEvidence) -> KnowledgeBaseWriteApprovalEvidence:
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("knowledge base write approval evidence already exists")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> KnowledgeBaseWriteApprovalEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("knowledge base write approval evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[KnowledgeBaseWriteApprovalEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class PgKnowledgeBaseWriteApprovalLedger:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, evidence: KnowledgeBaseWriteApprovalEvidence) -> KnowledgeBaseWriteApprovalEvidence:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, evidence.tenant_id)
                connection.execute(
                    """
                    INSERT INTO knowledge_base.write_approval_evidence (
                        tenant_id,
                        approval_reference,
                        operation,
                        approval_state,
                        article_object_id,
                        article_key,
                        title,
                        expected_current_version_object_id,
                        proposed_version_object_id,
                        proposed_version_label,
                        proposed_source_object_id,
                        proposed_source_version_id,
                        proposed_source_object_type,
                        proposed_source_manifest_hash,
                        proposed_content_hash,
                        proposed_acl_version,
                        command_hash,
                        proposed_source_version_evidence_hash,
                        current_restore_evidence_hash,
                        source_object_write_guard_ref,
                        transition_source_evidence_hash,
                        requested_by,
                        persistence_allowed,
                        rag_indexing_allowed,
                        source_authority_verified,
                        audit_event_id,
                        audit_chain_ref,
                        source_system,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        evidence.tenant_id,
                        evidence.approval_reference,
                        evidence.operation,
                        evidence.approval_state,
                        evidence.article_object_id,
                        evidence.article_key,
                        evidence.title,
                        evidence.expected_current_version_object_id,
                        evidence.proposed_version_object_id,
                        evidence.proposed_version_label,
                        evidence.proposed_source_object_id,
                        evidence.proposed_source_version_id,
                        evidence.proposed_source_object_type,
                        evidence.proposed_source_manifest_hash,
                        evidence.proposed_content_hash,
                        evidence.proposed_acl_version,
                        evidence.command_hash,
                        evidence.proposed_source_version_evidence_hash,
                        evidence.current_restore_evidence_hash,
                        evidence.source_object_write_guard_ref,
                        evidence.transition_source_evidence_hash,
                        evidence.requested_by,
                        evidence.persistence_allowed,
                        evidence.rag_indexing_allowed,
                        evidence.source_authority_verified,
                        evidence.audit_event_id,
                        evidence.audit_chain_ref,
                        evidence.source_system,
                        evidence.evidence_hash,
                        evidence.schema_version,
                    ),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("knowledge base write approval evidence already exists") from exc
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> KnowledgeBaseWriteApprovalEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT
                    tenant_id,
                    approval_reference,
                    operation,
                    approval_state,
                    article_object_id,
                    article_key,
                    title,
                    expected_current_version_object_id,
                    proposed_version_object_id,
                    proposed_version_label,
                    proposed_source_object_id,
                    proposed_source_version_id,
                    proposed_source_object_type,
                    proposed_source_manifest_hash,
                    proposed_content_hash,
                    proposed_acl_version,
                    command_hash,
                    proposed_source_version_evidence_hash,
                    current_restore_evidence_hash,
                    source_object_write_guard_ref,
                    transition_source_evidence_hash,
                    requested_by,
                    persistence_allowed,
                    rag_indexing_allowed,
                    source_authority_verified,
                    audit_event_id,
                    audit_chain_ref,
                    source_system,
                    evidence_hash,
                    schema_version
                FROM knowledge_base.write_approval_evidence
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("knowledge base write approval evidence not found")
        return self._evidence_from_row(row)

    def list_evidence(self, *, tenant_id: str) -> Sequence[KnowledgeBaseWriteApprovalEvidence]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT
                    tenant_id,
                    approval_reference,
                    operation,
                    approval_state,
                    article_object_id,
                    article_key,
                    title,
                    expected_current_version_object_id,
                    proposed_version_object_id,
                    proposed_version_label,
                    proposed_source_object_id,
                    proposed_source_version_id,
                    proposed_source_object_type,
                    proposed_source_manifest_hash,
                    proposed_content_hash,
                    proposed_acl_version,
                    command_hash,
                    proposed_source_version_evidence_hash,
                    current_restore_evidence_hash,
                    source_object_write_guard_ref,
                    transition_source_evidence_hash,
                    requested_by,
                    persistence_allowed,
                    rag_indexing_allowed,
                    source_authority_verified,
                    audit_event_id,
                    audit_chain_ref,
                    source_system,
                    evidence_hash,
                    schema_version
                FROM knowledge_base.write_approval_evidence
                WHERE tenant_id = %s
                ORDER BY captured_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._evidence_from_row(row) for row in rows)

    def _evidence_from_row(self, row: tuple[Any, ...]) -> KnowledgeBaseWriteApprovalEvidence:
        return KnowledgeBaseWriteApprovalEvidence(
            tenant_id=str(row[0]),
            approval_reference=str(row[1]),
            operation=KnowledgeBaseWriteOperation(str(row[2])),
            approval_state=KnowledgeBaseWriteApprovalState(str(row[3])),
            article_object_id=str(row[4]),
            article_key=str(row[5]),
            title=str(row[6]),
            expected_current_version_object_id=str(row[7]) if row[7] is not None else None,
            proposed_version_object_id=str(row[8]),
            proposed_version_label=str(row[9]),
            proposed_source_object_id=str(row[10]),
            proposed_source_version_id=str(row[11]),
            proposed_source_object_type=SourceObjectType(str(row[12])),
            proposed_source_manifest_hash=str(row[13]),
            proposed_content_hash=str(row[14]),
            proposed_acl_version=int(row[15]),
            command_hash=str(row[16]),
            proposed_source_version_evidence_hash=str(row[17]),
            current_restore_evidence_hash=str(row[18]),
            source_object_write_guard_ref=str(row[19]),
            transition_source_evidence_hash=str(row[20]) if row[20] is not None else None,
            requested_by=str(row[21]),
            persistence_allowed=bool(row[22]),
            rag_indexing_allowed=bool(row[23]),
            source_authority_verified=bool(row[24]),
            audit_event_id=str(row[25]),
            audit_chain_ref=str(row[26]),
            source_system=str(row[27]),
            evidence_hash=str(row[28]),
            schema_version=str(row[29]),
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


class KnowledgeBaseSourceObjectWriteGuard:
    def __init__(self, *, source_object_write_guard: SourceObjectWriteGuard | None = None) -> None:
        self.source_object_write_guard = source_object_write_guard or SourceObjectWriteGuard()

    def evaluate(
        self,
        *,
        tenant_id: str,
        write_approval_evidence_hash: str,
        write_approval_ledger: KnowledgeBaseWriteApprovalLedger,
        current_article: KnowledgeBaseArticleRecord | None,
        proposed_source_record: SourceObjectRecord,
        current_restore_evidence: KnowledgeBaseRestoreEvidence,
    ) -> KnowledgeBaseSourceObjectWriteGuardDecision:
        evidence = write_approval_ledger.get(tenant_id=tenant_id, evidence_hash=write_approval_evidence_hash)
        blocking_reasons: list[str] = []

        if build_write_approval_evidence_hash(evidence) != evidence.evidence_hash:
            blocking_reasons.append("write_approval_evidence_hash_invalid")
        if evidence.approval_state != KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE:
            blocking_reasons.append("approval_state_not_approved_for_write")
        if not evidence.persistence_allowed:
            blocking_reasons.append("persistence_not_allowed_by_approval_evidence")

        self._evaluate_expected_version(
            tenant_id=tenant_id,
            evidence=evidence,
            current_article=current_article,
            blocking_reasons=blocking_reasons,
        )
        self._evaluate_proposed_source(
            tenant_id=tenant_id,
            evidence=evidence,
            proposed_source_record=proposed_source_record,
            blocking_reasons=blocking_reasons,
        )
        self._evaluate_restore_evidence(
            tenant_id=tenant_id,
            evidence=evidence,
            current_restore_evidence=current_restore_evidence,
            blocking_reasons=blocking_reasons,
        )

        allowed = not blocking_reasons
        draft = KnowledgeBaseSourceObjectWriteGuardDecision(
            tenant_id=tenant_id,
            source_object_write_guard_ref="guard:pending",
            allowed=allowed,
            blocking_reasons=tuple(blocking_reasons),
            write_approval_evidence_hash=evidence.evidence_hash,
            approval_state=evidence.approval_state,
            operation=evidence.operation,
            article_object_id=evidence.article_object_id,
            expected_current_version_object_id=evidence.expected_current_version_object_id,
            proposed_source_object_id=evidence.proposed_source_object_id,
            proposed_source_version_id=evidence.proposed_source_version_id,
            proposed_source_version_evidence_hash=evidence.proposed_source_version_evidence_hash,
            current_restore_evidence_hash=evidence.current_restore_evidence_hash,
            persistence_allowed=allowed and evidence.persistence_allowed,
            rag_indexing_allowed=allowed and evidence.rag_indexing_allowed,
            source_authority_verified=allowed,
        )
        return draft.model_copy(update={"source_object_write_guard_ref": build_source_object_write_guard_ref(draft)})

    def _evaluate_expected_version(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        current_article: KnowledgeBaseArticleRecord | None,
        blocking_reasons: list[str],
    ) -> None:
        if evidence.operation == KnowledgeBaseWriteOperation.CREATE:
            if current_article is not None:
                blocking_reasons.append("create_target_already_exists")
            return

        if current_article is None:
            blocking_reasons.append("current_article_missing")
            return
        if current_article.tenant_id != tenant_id:
            blocking_reasons.append("current_article_tenant_mismatch")
        if current_article.object_id != evidence.article_object_id:
            blocking_reasons.append("current_article_object_mismatch")
        if current_article.current_version_object_id != evidence.expected_current_version_object_id:
            blocking_reasons.append("expected_current_version_mismatch")
        if current_article.legal_hold_state == "active":
            blocking_reasons.append("current_article_legal_hold_active")
        if current_article.retention_policy_id != "rp-standard":
            blocking_reasons.append("current_article_retention_policy_unsupported")

    def _evaluate_proposed_source(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        proposed_source_record: SourceObjectRecord,
        blocking_reasons: list[str],
    ) -> None:
        metadata = proposed_source_record.metadata
        try:
            self.source_object_write_guard.validate_before_write(proposed_source_record)
        except SourceObjectWriteDeniedError as exc:
            blocking_reasons.append(f"source_object_metadata_guard_failed:{exc}")

        if metadata.tenant_id != tenant_id:
            blocking_reasons.append("proposed_source_tenant_mismatch")
        if metadata.object_id != evidence.proposed_source_object_id:
            blocking_reasons.append("proposed_source_object_mismatch")
        if metadata.version_id != evidence.proposed_source_version_id:
            blocking_reasons.append("proposed_source_version_mismatch")
        if metadata.object_type != evidence.proposed_source_object_type:
            blocking_reasons.append("proposed_source_object_type_mismatch")
        if metadata.manifest_hash != evidence.proposed_source_manifest_hash:
            blocking_reasons.append("proposed_source_manifest_hash_mismatch")
        if metadata.content_hash != evidence.proposed_content_hash:
            blocking_reasons.append("proposed_source_content_hash_mismatch")
        if metadata.acl_version != evidence.proposed_acl_version:
            blocking_reasons.append("proposed_source_acl_version_mismatch")
        if (
            evidence.operation == KnowledgeBaseWriteOperation.CREATE
            and metadata.source_system != evidence.source_system
        ):
            blocking_reasons.append("proposed_source_system_mismatch")
        if metadata.classification != DataClass.INTERNAL:
            blocking_reasons.append("proposed_source_classification_not_internal")
        if metadata.retention_policy_id != "rp-standard":
            blocking_reasons.append("proposed_source_retention_policy_unsupported")
        if metadata.legal_hold_state == LegalHoldState.ACTIVE:
            blocking_reasons.append("proposed_source_legal_hold_active")

        proposed_source_evidence = build_source_version_evidence_for_source_record(
            tenant_id=tenant_id,
            article_object_id=evidence.article_object_id,
            article_version_object_id=evidence.proposed_version_object_id,
            source_record=proposed_source_record,
        )
        if proposed_source_evidence.evidence_hash != evidence.proposed_source_version_evidence_hash:
            blocking_reasons.append("proposed_source_version_evidence_hash_mismatch")

    def _evaluate_restore_evidence(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
        current_restore_evidence: KnowledgeBaseRestoreEvidence,
        blocking_reasons: list[str],
    ) -> None:
        if current_restore_evidence.tenant_id != tenant_id:
            blocking_reasons.append("current_restore_evidence_tenant_mismatch")
        if current_restore_evidence.evidence_hash != evidence.current_restore_evidence_hash:
            blocking_reasons.append("current_restore_evidence_hash_mismatch")
        if build_restore_evidence_hash(current_restore_evidence) != current_restore_evidence.evidence_hash:
            blocking_reasons.append("current_restore_evidence_hash_invalid")
        if not current_restore_evidence.legal_hold_restore_verified:
            blocking_reasons.append("legal_hold_restore_not_verified")
        if not current_restore_evidence.disabled_state_restore_verified:
            blocking_reasons.append("disabled_state_restore_not_verified")
        if not current_restore_evidence.tenant_isolation_verified:
            blocking_reasons.append("tenant_isolation_restore_not_verified")


class KnowledgeBaseArticleService:
    def __init__(
        self,
        *,
        repository: KnowledgeBaseArticleRepository,
        source_repository: SourceObjectRepository,
        audit_logger: InMemoryAuditLogger,
        write_approval_ledger: KnowledgeBaseWriteApprovalLedger | None = None,
        source_object_write_guard: KnowledgeBaseSourceObjectWriteGuard | None = None,
        source_object_write_receipt_store: SourceObjectWriteReceiptStore | None = None,
    ) -> None:
        self.repository = repository
        self.source_repository = source_repository
        self.audit_logger = audit_logger
        self.write_approval_ledger = write_approval_ledger or InMemoryKnowledgeBaseWriteApprovalLedger()
        self.source_object_write_guard = source_object_write_guard or KnowledgeBaseSourceObjectWriteGuard()
        self.source_object_write_receipt_store = (
            source_object_write_receipt_store or InMemorySourceObjectWriteReceiptStore()
        )

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
            source_object_ids=knowledge_base_audit_source_object_ids(records),
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

    def read_compliance_evidence(self, *, user_context: UserContext) -> KnowledgeBaseEvidenceResponse:
        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.evidence.read",
            source_object_ids=knowledge_base_audit_source_object_ids(records),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "surface": "compliance_api",
                "continuity_domain": restore_evidence.continuity_domain,
                "article_count": len(records),
                "source_version_evidence_count": len(source_evidences),
                "result_contract": "metadata_only",
                "source_version_evidence_hashes": sorted(evidence.evidence_hash for evidence in source_evidences),
                "restore_evidence_hash": restore_evidence.evidence_hash,
            },
        )
        return KnowledgeBaseEvidenceResponse(
            tenant_id=user_context.tenant_id,
            source_version_evidence=source_evidences,
            restore_evidence=restore_evidence,
            audit_event_id=event.event_id,
        )

    def dry_run_write_approval(
        self,
        *,
        command: KnowledgeBaseWriteApprovalCommand,
        user_context: UserContext,
    ) -> KnowledgeBaseWriteDryRunResponse:
        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        existing_article = records_by_object_id.get(command.article_object_id)
        if command.operation == KnowledgeBaseWriteOperation.EDIT:
            if existing_article is None:
                raise LookupError(f"knowledge base article not found: {command.article_object_id}")
            if existing_article.current_version_object_id != command.expected_current_version_object_id:
                raise ValueError("expected current article version does not match")
        if command.operation == KnowledgeBaseWriteOperation.CREATE:
            if existing_article is not None:
                raise ValueError("create dry-run cannot target an existing knowledge base article")
            if any(article.article_key == command.article_key for article in records):
                raise ValueError("create dry-run cannot target an existing knowledge base article key")

        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        proposed_evidence = build_proposed_source_version_evidence(
            tenant_id=user_context.tenant_id,
            command=command,
        )
        command_hash = build_write_approval_command_hash(command)
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.write_approval.dry_run",
            source_object_ids=knowledge_base_write_target_object_ids(command, existing_article),
            input_text=canonical_json(command.model_dump(mode="json")),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
                "surface": "compliance_api",
                "operation": command.operation,
                "dry_run": True,
                "persistence_allowed": False,
                "rag_indexing_allowed": False,
                "source_authority_verified": False,
                "approval_reference": command.approval_reference,
                "command_hash": command_hash,
                "proposed_source_version_evidence_hash": proposed_evidence.evidence_hash,
                "current_restore_evidence_hash": restore_evidence.evidence_hash,
                "required_evidence": list(KB_WRITE_DRY_RUN_REQUIRED_EVIDENCE),
            },
        )
        write_approval_evidence = build_write_approval_evidence(
            tenant_id=user_context.tenant_id,
            command=command,
            command_hash=command_hash,
            proposed_source_version_evidence_hash=proposed_evidence.evidence_hash,
            current_restore_evidence_hash=restore_evidence.evidence_hash,
            requested_by=user_context.user_id,
            audit_event_id=event.event_id,
            audit_chain_ref=f"audit:{event.event_id}",
        )
        persisted_write_approval_evidence = self.write_approval_ledger.append(write_approval_evidence)
        return KnowledgeBaseWriteDryRunResponse(
            tenant_id=user_context.tenant_id,
            operation=command.operation,
            article_object_id=command.article_object_id,
            proposed_version_object_id=command.proposed_version_object_id,
            proposed_source_object_id=command.proposed_source_object_id,
            proposed_source_version_id=command.proposed_source_version_id,
            approval_reference=command.approval_reference,
            command_hash=command_hash,
            proposed_source_version_evidence_hash=proposed_evidence.evidence_hash,
            current_restore_evidence_hash=restore_evidence.evidence_hash,
            write_approval_evidence_hash=persisted_write_approval_evidence.evidence_hash,
            audit_event_id=event.event_id,
        )

    def approve_write_approval(
        self,
        *,
        command: KnowledgeBaseWriteApprovalTransitionCommand,
        user_context: UserContext,
    ) -> KnowledgeBaseWriteApprovalTransitionResponse:
        dry_run_evidence = self.write_approval_ledger.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=command.dry_run_write_approval_evidence_hash,
        )
        self._require_approvable_dry_run_evidence(dry_run_evidence)
        self._require_not_already_approved(
            tenant_id=user_context.tenant_id,
            dry_run_write_approval_evidence_hash=dry_run_evidence.evidence_hash,
        )
        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        existing_article = records_by_object_id.get(dry_run_evidence.article_object_id)
        if dry_run_evidence.operation == KnowledgeBaseWriteOperation.EDIT:
            if existing_article is None:
                raise LookupError(f"knowledge base article not found: {dry_run_evidence.article_object_id}")
            if existing_article.current_version_object_id != dry_run_evidence.expected_current_version_object_id:
                raise ValueError("expected current article version does not match dry-run evidence")
        if dry_run_evidence.operation == KnowledgeBaseWriteOperation.CREATE and existing_article is not None:
            raise ValueError("create approval cannot target an existing knowledge base article")

        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        if restore_evidence.evidence_hash != dry_run_evidence.current_restore_evidence_hash:
            raise ValueError("current restore evidence no longer matches dry-run evidence")

        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.write_approval.approved",
            source_object_ids=knowledge_base_write_evidence_target_object_ids(dry_run_evidence, existing_article),
            input_text=canonical_json(command.model_dump(mode="json")),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
                "surface": "compliance_api",
                "operation": dry_run_evidence.operation,
                "approval_reference": command.approval_reference,
                "approval_state": KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE,
                "dry_run_write_approval_evidence_hash": dry_run_evidence.evidence_hash,
                "command_hash": dry_run_evidence.command_hash,
                "proposed_source_version_evidence_hash": dry_run_evidence.proposed_source_version_evidence_hash,
                "current_restore_evidence_hash": dry_run_evidence.current_restore_evidence_hash,
                "persistence_allowed": True,
                "rag_indexing_allowed": False,
                "source_authority_verified": False,
                "required_evidence": list(KB_WRITE_APPROVAL_TRANSITION_REQUIRED_EVIDENCE),
            },
        )
        approved_evidence = build_write_approval_transition_evidence(
            source_evidence=dry_run_evidence,
            approval_reference=command.approval_reference,
            requested_by=user_context.user_id,
            audit_event_id=event.event_id,
            audit_chain_ref=f"audit:{event.event_id}",
        )
        persisted_approved_evidence = self.write_approval_ledger.append(approved_evidence)
        return KnowledgeBaseWriteApprovalTransitionResponse(
            tenant_id=user_context.tenant_id,
            dry_run_write_approval_evidence_hash=dry_run_evidence.evidence_hash,
            approved_write_approval_evidence_hash=persisted_approved_evidence.evidence_hash,
            approval_state=persisted_approved_evidence.approval_state,
            operation=persisted_approved_evidence.operation,
            article_object_id=persisted_approved_evidence.article_object_id,
            proposed_version_object_id=persisted_approved_evidence.proposed_version_object_id,
            proposed_source_object_id=persisted_approved_evidence.proposed_source_object_id,
            proposed_source_version_id=persisted_approved_evidence.proposed_source_version_id,
            persistence_allowed=persisted_approved_evidence.persistence_allowed,
            rag_indexing_allowed=persisted_approved_evidence.rag_indexing_allowed,
            source_authority_verified=persisted_approved_evidence.source_authority_verified,
            command_hash=persisted_approved_evidence.command_hash,
            proposed_source_version_evidence_hash=persisted_approved_evidence.proposed_source_version_evidence_hash,
            current_restore_evidence_hash=persisted_approved_evidence.current_restore_evidence_hash,
            audit_event_id=event.event_id,
        )

    def preview_write_evidence_refresh(
        self,
        *,
        command: KnowledgeBaseEvidenceRefreshPreviewCommand,
        user_context: UserContext,
    ) -> KnowledgeBaseEvidenceRefreshPreviewResponse:
        approved_evidence = self.write_approval_ledger.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=command.approved_write_approval_evidence_hash,
        )
        self._require_refresh_preview_approved_evidence(approved_evidence)

        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        existing_article = records_by_object_id.get(approved_evidence.article_object_id)
        if approved_evidence.operation == KnowledgeBaseWriteOperation.EDIT:
            if existing_article is None:
                raise LookupError(f"knowledge base article not found: {approved_evidence.article_object_id}")
            if existing_article.current_version_object_id != approved_evidence.expected_current_version_object_id:
                raise ValueError("expected current article version does not match approved evidence")
        if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE and existing_article is not None:
            raise ValueError("create refresh preview cannot target an existing knowledge base article")

        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        if restore_evidence.evidence_hash != approved_evidence.current_restore_evidence_hash:
            raise ValueError("current restore evidence no longer matches approved write evidence")

        current_source_hashes = tuple(sorted(evidence.evidence_hash for evidence in source_evidences))
        projected_source_hashes = build_projected_source_version_evidence_hashes(
            approved_evidence=approved_evidence,
            current_source_evidences=source_evidences,
        )
        count_delta = 1 if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE else 0
        article_count_before = len(records)
        source_evidence_count_before = len(source_evidences)
        preview_command_hash = build_evidence_refresh_preview_command_hash(command)
        projected_restore_hash = build_knowledge_base_restore_evidence_preview_hash(
            tenant_id=user_context.tenant_id,
            approved_evidence=approved_evidence,
            preview_command_hash=preview_command_hash,
            current_source_version_evidence_hashes=current_source_hashes,
            projected_source_version_evidence_hashes=projected_source_hashes,
            article_count_before=article_count_before,
            article_count_after=article_count_before + count_delta,
            article_version_count_before=article_count_before,
            article_version_count_after=article_count_before + count_delta,
            source_version_evidence_count_before=source_evidence_count_before,
            source_version_evidence_count_after=source_evidence_count_before + count_delta,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.write_approval.refresh_preview",
            source_object_ids=knowledge_base_write_evidence_target_object_ids(approved_evidence, existing_article),
            input_text=canonical_json(command.model_dump(mode="json")),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
                "surface": "compliance_api",
                "operation": approved_evidence.operation,
                "preview_reference": command.preview_reference,
                "approval_state": approved_evidence.approval_state,
                "approved_write_approval_evidence_hash": approved_evidence.evidence_hash,
                "transition_source_evidence_hash": approved_evidence.transition_source_evidence_hash,
                "command_hash": approved_evidence.command_hash,
                "preview_command_hash": preview_command_hash,
                "proposed_source_version_evidence_hash": approved_evidence.proposed_source_version_evidence_hash,
                "current_restore_evidence_hash": restore_evidence.evidence_hash,
                "projected_restore_evidence_preview_hash": projected_restore_hash,
                "current_source_version_evidence_hashes": list(current_source_hashes),
                "projected_source_version_evidence_hashes": list(projected_source_hashes),
                "article_count_before": article_count_before,
                "article_count_after": article_count_before + count_delta,
                "source_version_evidence_count_before": source_evidence_count_before,
                "source_version_evidence_count_after": source_evidence_count_before + count_delta,
                "result_contract": "metadata_only",
                "preview_only": True,
                "article_source_writes_allowed": False,
                "evidence_persistence_allowed": False,
                "rag_indexing_allowed": False,
                "source_authority_verified": False,
                "required_evidence": list(KB_WRITE_REFRESH_PREVIEW_REQUIRED_EVIDENCE),
            },
        )
        return KnowledgeBaseEvidenceRefreshPreviewResponse(
            tenant_id=user_context.tenant_id,
            approved_write_approval_evidence_hash=approved_evidence.evidence_hash,
            transition_source_evidence_hash=str(approved_evidence.transition_source_evidence_hash),
            operation=approved_evidence.operation,
            article_object_id=approved_evidence.article_object_id,
            expected_current_version_object_id=approved_evidence.expected_current_version_object_id,
            proposed_version_object_id=approved_evidence.proposed_version_object_id,
            proposed_source_object_id=approved_evidence.proposed_source_object_id,
            proposed_source_version_id=approved_evidence.proposed_source_version_id,
            command_hash=approved_evidence.command_hash,
            preview_command_hash=preview_command_hash,
            proposed_source_version_evidence_hash=approved_evidence.proposed_source_version_evidence_hash,
            current_source_version_evidence_hashes=current_source_hashes,
            projected_source_version_evidence_hashes=projected_source_hashes,
            current_restore_evidence_hash=restore_evidence.evidence_hash,
            projected_restore_evidence_preview_hash=projected_restore_hash,
            article_count_before=article_count_before,
            article_count_after=article_count_before + count_delta,
            article_version_count_before=article_count_before,
            article_version_count_after=article_count_before + count_delta,
            source_version_evidence_count_before=source_evidence_count_before,
            source_version_evidence_count_after=source_evidence_count_before + count_delta,
            audit_event_id=event.event_id,
        )

    def prepare_write_execution_skeleton(
        self,
        *,
        command: KnowledgeBaseWriteExecutionSkeletonCommand,
        user_context: UserContext,
    ) -> KnowledgeBaseWriteExecutionSkeletonResponse:
        approved_evidence = self.write_approval_ledger.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=command.approved_write_approval_evidence_hash,
        )
        self._require_refresh_preview_approved_evidence(approved_evidence)

        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        existing_article = records_by_object_id.get(approved_evidence.article_object_id)
        if approved_evidence.operation == KnowledgeBaseWriteOperation.EDIT:
            if existing_article is None:
                raise LookupError(f"knowledge base article not found: {approved_evidence.article_object_id}")
            if existing_article.current_version_object_id != approved_evidence.expected_current_version_object_id:
                raise ValueError("expected current article version does not match approved evidence")
        if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE and existing_article is not None:
            raise ValueError("create execution skeleton cannot target an existing knowledge base article")

        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        if restore_evidence.evidence_hash != approved_evidence.current_restore_evidence_hash:
            raise ValueError("current restore evidence no longer matches approved write evidence")

        self._require_matching_source_object_write_guard_decision(
            approved_evidence=approved_evidence,
            decision=command.source_object_write_guard_decision,
        )

        current_source_hashes = tuple(sorted(evidence.evidence_hash for evidence in source_evidences))
        projected_source_hashes = build_projected_source_version_evidence_hashes(
            approved_evidence=approved_evidence,
            current_source_evidences=source_evidences,
        )
        count_delta = 1 if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE else 0
        article_count_before = len(records)
        source_evidence_count_before = len(source_evidences)
        projected_restore_hash = build_knowledge_base_restore_evidence_preview_hash(
            tenant_id=user_context.tenant_id,
            approved_evidence=approved_evidence,
            preview_command_hash=command.refresh_preview_command_hash,
            current_source_version_evidence_hashes=current_source_hashes,
            projected_source_version_evidence_hashes=projected_source_hashes,
            article_count_before=article_count_before,
            article_count_after=article_count_before + count_delta,
            article_version_count_before=article_count_before,
            article_version_count_after=article_count_before + count_delta,
            source_version_evidence_count_before=source_evidence_count_before,
            source_version_evidence_count_after=source_evidence_count_before + count_delta,
        )
        if projected_restore_hash != command.projected_restore_evidence_preview_hash:
            raise ValueError("projected restore evidence preview hash does not match current approved evidence")

        execution_command_hash = build_write_execution_skeleton_command_hash(command)
        execution_plan_hash = build_write_execution_plan_hash(
            tenant_id=user_context.tenant_id,
            approved_evidence=approved_evidence,
            command=command,
            execution_command_hash=execution_command_hash,
        )
        blocking_reasons = (
            "write_execution_adapter_not_enabled",
            "post_write_source_restore_evidence_refresh_not_connected",
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.write_approval.execution_skeleton",
            source_object_ids=knowledge_base_write_evidence_target_object_ids(approved_evidence, existing_article),
            input_text=canonical_json(command.model_dump(mode="json")),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
                "surface": "compliance_api",
                "operation": approved_evidence.operation,
                "execution_reference": command.execution_reference,
                "human_confirmation_reference": command.human_confirmation_reference,
                "approved_write_approval_evidence_hash": approved_evidence.evidence_hash,
                "transition_source_evidence_hash": approved_evidence.transition_source_evidence_hash,
                "source_object_write_guard_ref": (
                    command.source_object_write_guard_decision.source_object_write_guard_ref
                ),
                "refresh_preview_command_hash": command.refresh_preview_command_hash,
                "projected_restore_evidence_preview_hash": command.projected_restore_evidence_preview_hash,
                "command_hash": approved_evidence.command_hash,
                "execution_command_hash": execution_command_hash,
                "execution_plan_hash": execution_plan_hash,
                "proposed_source_version_evidence_hash": approved_evidence.proposed_source_version_evidence_hash,
                "current_restore_evidence_hash": restore_evidence.evidence_hash,
                "preconditions_verified": True,
                "source_object_write_guard_verified": True,
                "human_confirmation_verified": True,
                "source_authority_verified": True,
                "execution_allowed": False,
                "article_source_writes_allowed": False,
                "article_metadata_persistence_allowed": False,
                "source_object_persistence_allowed": False,
                "evidence_persistence_allowed": False,
                "rag_indexing_allowed": False,
                "blocking_reasons": list(blocking_reasons),
                "result_contract": "metadata_only",
                "required_evidence": list(KB_WRITE_EXECUTION_SKELETON_REQUIRED_EVIDENCE),
            },
        )
        return KnowledgeBaseWriteExecutionSkeletonResponse(
            tenant_id=user_context.tenant_id,
            execution_reference=command.execution_reference,
            human_confirmation_reference=command.human_confirmation_reference,
            approved_write_approval_evidence_hash=approved_evidence.evidence_hash,
            transition_source_evidence_hash=str(approved_evidence.transition_source_evidence_hash),
            source_object_write_guard_ref=command.source_object_write_guard_decision.source_object_write_guard_ref,
            refresh_preview_command_hash=command.refresh_preview_command_hash,
            projected_restore_evidence_preview_hash=command.projected_restore_evidence_preview_hash,
            operation=approved_evidence.operation,
            article_object_id=approved_evidence.article_object_id,
            expected_current_version_object_id=approved_evidence.expected_current_version_object_id,
            proposed_version_object_id=approved_evidence.proposed_version_object_id,
            proposed_source_object_id=approved_evidence.proposed_source_object_id,
            proposed_source_version_id=approved_evidence.proposed_source_version_id,
            command_hash=approved_evidence.command_hash,
            execution_command_hash=execution_command_hash,
            execution_plan_hash=execution_plan_hash,
            proposed_source_version_evidence_hash=approved_evidence.proposed_source_version_evidence_hash,
            current_restore_evidence_hash=restore_evidence.evidence_hash,
            preconditions_verified=True,
            source_object_write_guard_verified=True,
            human_confirmation_verified=True,
            source_authority_verified=True,
            blocking_reasons=blocking_reasons,
            audit_event_id=event.event_id,
        )

    def execute_write(
        self,
        *,
        command: KnowledgeBaseWriteExecutionCommand,
        user_context: UserContext,
    ) -> KnowledgeBaseWriteExecutionResponse:
        approved_evidence = self.write_approval_ledger.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=command.approved_write_approval_evidence_hash,
        )
        self._require_refresh_preview_approved_evidence(approved_evidence)

        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        existing_article = records_by_object_id.get(approved_evidence.article_object_id)
        if approved_evidence.operation == KnowledgeBaseWriteOperation.EDIT:
            if existing_article is None:
                raise LookupError(f"knowledge base article not found: {approved_evidence.article_object_id}")
            if existing_article.current_version_object_id != approved_evidence.expected_current_version_object_id:
                raise ValueError("expected current article version does not match approved evidence")
        if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE and existing_article is not None:
            raise ValueError("create execution cannot target an existing knowledge base article")

        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        if restore_evidence.evidence_hash != approved_evidence.current_restore_evidence_hash:
            raise ValueError("current restore evidence no longer matches approved write evidence")

        self._require_matching_source_object_write_guard_decision(
            approved_evidence=approved_evidence,
            decision=command.source_object_write_guard_decision,
        )
        reevaluated_guard = self.source_object_write_guard.evaluate(
            tenant_id=user_context.tenant_id,
            write_approval_evidence_hash=approved_evidence.evidence_hash,
            write_approval_ledger=self.write_approval_ledger,
            current_article=existing_article,
            proposed_source_record=command.proposed_source_record,
            current_restore_evidence=restore_evidence,
        )
        if (
            reevaluated_guard.source_object_write_guard_ref
            != command.source_object_write_guard_decision.source_object_write_guard_ref
        ):
            raise ValueError("source-object write guard decision does not match proposed source record")

        current_source_hashes = tuple(sorted(evidence.evidence_hash for evidence in source_evidences))
        projected_source_hashes = build_projected_source_version_evidence_hashes(
            approved_evidence=approved_evidence,
            current_source_evidences=source_evidences,
        )
        count_delta = 1 if approved_evidence.operation == KnowledgeBaseWriteOperation.CREATE else 0
        projected_restore_hash = build_knowledge_base_restore_evidence_preview_hash(
            tenant_id=user_context.tenant_id,
            approved_evidence=approved_evidence,
            preview_command_hash=command.refresh_preview_command_hash,
            current_source_version_evidence_hashes=current_source_hashes,
            projected_source_version_evidence_hashes=projected_source_hashes,
            article_count_before=len(records),
            article_count_after=len(records) + count_delta,
            article_version_count_before=len(records),
            article_version_count_after=len(records) + count_delta,
            source_version_evidence_count_before=len(source_evidences),
            source_version_evidence_count_after=len(source_evidences) + count_delta,
        )
        if projected_restore_hash != command.projected_restore_evidence_preview_hash:
            raise ValueError("projected restore evidence preview hash does not match current approved evidence")
        expected_plan_hash = build_write_execution_plan_hash(
            tenant_id=user_context.tenant_id,
            approved_evidence=approved_evidence,
            command=command,
            execution_command_hash=command.execution_skeleton_command_hash,
        )
        if expected_plan_hash != command.execution_plan_hash:
            raise ValueError("write execution plan hash does not match approved skeleton")

        self._require_source_object_absent(tenant_id=user_context.tenant_id, evidence=approved_evidence)
        execution_command_hash = build_write_execution_command_hash(command)
        audit_chain_ref = f"audit:{command.execution_reference}"
        source_object_write_receipt = build_source_object_write_receipt(
            record=command.proposed_source_record,
            receipt_reference=f"receipt:{command.execution_reference}",
            audit_chain_ref=audit_chain_ref,
        )
        persisted_write_receipt = self.source_object_write_receipt_store.append(source_object_write_receipt)
        self.source_repository.add(command.proposed_source_record)
        updated_article = self.repository.apply_write(
            tenant_id=user_context.tenant_id,
            evidence=approved_evidence,
            source_record=command.proposed_source_record,
            audit_chain_ref=audit_chain_ref,
        )
        refreshed_records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        refreshed_source_evidences = [self.source_version_evidence(record) for record in refreshed_records]
        refreshed_restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=refreshed_records,
            source_evidences=refreshed_source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        refreshed_evidence_by_article = {
            evidence.article_object_id: evidence for evidence in refreshed_source_evidences
        }
        refreshed_source_evidence = refreshed_evidence_by_article[approved_evidence.article_object_id]
        if refreshed_source_evidence.evidence_hash != approved_evidence.proposed_source_version_evidence_hash:
            raise ValueError("post-write source-version evidence does not match approved evidence")
        if refreshed_restore_evidence.source_version_evidence_hashes != projected_source_hashes:
            raise ValueError("post-write source-version evidence hashes do not match refresh preview")

        event = self.audit_logger.record(
            user_context=user_context,
            event_type="knowledge_base.write_approval.executed",
            source_object_ids=knowledge_base_write_evidence_target_object_ids(approved_evidence, existing_article),
            input_text=canonical_json(build_write_execution_audit_payload(command)),
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
                "surface": "compliance_api",
                "operation": approved_evidence.operation,
                "execution_reference": command.execution_reference,
                "human_confirmation_reference": command.human_confirmation_reference,
                "approved_write_approval_evidence_hash": approved_evidence.evidence_hash,
                "transition_source_evidence_hash": approved_evidence.transition_source_evidence_hash,
                "source_object_write_guard_ref": (
                    command.source_object_write_guard_decision.source_object_write_guard_ref
                ),
                "refresh_preview_command_hash": command.refresh_preview_command_hash,
                "projected_restore_evidence_preview_hash": command.projected_restore_evidence_preview_hash,
                "execution_skeleton_command_hash": command.execution_skeleton_command_hash,
                "execution_plan_hash": command.execution_plan_hash,
                "execution_command_hash": execution_command_hash,
                "source_object_write_receipt_hash": persisted_write_receipt.receipt_hash,
                "previous_restore_evidence_hash": restore_evidence.evidence_hash,
                "refreshed_restore_evidence_hash": refreshed_restore_evidence.evidence_hash,
                "refreshed_source_version_evidence_hash": refreshed_source_evidence.evidence_hash,
                "source_version_evidence_hashes_after": list(refreshed_restore_evidence.source_version_evidence_hashes),
                "source_object_persisted": True,
                "source_object_write_receipt_persisted": True,
                "article_metadata_persisted": True,
                "article_version_metadata_persisted": True,
                "source_version_evidence_refreshed": True,
                "restore_evidence_refreshed": True,
                "rag_indexing_allowed": False,
                "search_indexing_allowed": False,
                "result_contract": "metadata_only",
                "required_evidence": list(KB_WRITE_EXECUTION_REQUIRED_EVIDENCE),
            },
        )
        return KnowledgeBaseWriteExecutionResponse(
            tenant_id=user_context.tenant_id,
            execution_reference=command.execution_reference,
            human_confirmation_reference=command.human_confirmation_reference,
            approved_write_approval_evidence_hash=approved_evidence.evidence_hash,
            transition_source_evidence_hash=str(approved_evidence.transition_source_evidence_hash),
            source_object_write_guard_ref=command.source_object_write_guard_decision.source_object_write_guard_ref,
            source_object_write_receipt_hash=persisted_write_receipt.receipt_hash,
            refresh_preview_command_hash=command.refresh_preview_command_hash,
            projected_restore_evidence_preview_hash=command.projected_restore_evidence_preview_hash,
            execution_skeleton_command_hash=command.execution_skeleton_command_hash,
            execution_plan_hash=command.execution_plan_hash,
            execution_command_hash=execution_command_hash,
            operation=approved_evidence.operation,
            article_object_id=approved_evidence.article_object_id,
            previous_version_object_id=existing_article.current_version_object_id if existing_article else None,
            current_version_object_id=updated_article.current_version_object_id,
            current_source_object_id=updated_article.current_source_object_id,
            current_source_version_id=updated_article.current_source_version_id,
            proposed_source_version_evidence_hash=approved_evidence.proposed_source_version_evidence_hash,
            refreshed_source_version_evidence_hash=refreshed_source_evidence.evidence_hash,
            previous_restore_evidence_hash=restore_evidence.evidence_hash,
            refreshed_restore_evidence_hash=refreshed_restore_evidence.evidence_hash,
            source_version_evidence_hashes_after=refreshed_restore_evidence.source_version_evidence_hashes,
            article_count_after=refreshed_restore_evidence.article_count,
            article_version_count_after=refreshed_restore_evidence.article_version_count,
            source_version_evidence_count_after=refreshed_restore_evidence.source_version_evidence_count,
            audit_event_id=event.event_id,
        )

    def _require_approvable_dry_run_evidence(self, evidence: KnowledgeBaseWriteApprovalEvidence) -> None:
        if evidence.approval_state != KnowledgeBaseWriteApprovalState.DRY_RUN:
            raise ValueError("only dry-run write approval evidence can be approved")
        if build_write_approval_evidence_hash(evidence) != evidence.evidence_hash:
            raise ValueError("dry-run write approval evidence hash is invalid")
        if evidence.persistence_allowed or evidence.rag_indexing_allowed or evidence.source_authority_verified:
            raise ValueError("dry-run write approval evidence must not already allow persistence, RAG, or authority")

    def _require_not_already_approved(
        self,
        *,
        tenant_id: str,
        dry_run_write_approval_evidence_hash: str,
    ) -> None:
        for evidence in self.write_approval_ledger.list_evidence(tenant_id=tenant_id):
            if (
                evidence.transition_source_evidence_hash == dry_run_write_approval_evidence_hash
                and evidence.approval_state == KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE
            ):
                raise ValueError("dry-run write approval evidence is already approved")

    def _require_refresh_preview_approved_evidence(self, evidence: KnowledgeBaseWriteApprovalEvidence) -> None:
        if evidence.approval_state != KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE:
            raise ValueError("only approved write approval evidence can be used for refresh preview")
        if build_write_approval_evidence_hash(evidence) != evidence.evidence_hash:
            raise ValueError("approved write approval evidence hash is invalid")
        if not evidence.persistence_allowed:
            raise ValueError("approved write approval evidence must allow persistence before refresh preview")
        if evidence.transition_source_evidence_hash is None:
            raise ValueError("approved write approval evidence must reference transition source evidence")

    def _require_matching_source_object_write_guard_decision(
        self,
        *,
        approved_evidence: KnowledgeBaseWriteApprovalEvidence,
        decision: KnowledgeBaseSourceObjectWriteGuardDecision,
    ) -> None:
        if build_source_object_write_guard_ref(decision) != decision.source_object_write_guard_ref:
            raise ValueError("source-object write guard reference is invalid")
        if not decision.allowed:
            raise ValueError("source-object write guard decision must allow the proposed source write")
        if decision.blocking_reasons:
            raise ValueError("source-object write guard decision must not contain blocking reasons")
        if not decision.persistence_allowed:
            raise ValueError("source-object write guard decision must allow persistence")
        if decision.rag_indexing_allowed:
            raise ValueError("source-object write guard decision must not allow RAG indexing")
        if not decision.source_authority_verified:
            raise ValueError("source-object write guard decision must verify source authority")
        if decision.write_approval_evidence_hash != approved_evidence.evidence_hash:
            raise ValueError("source-object write guard decision does not match approved evidence")
        if decision.approval_state != approved_evidence.approval_state:
            raise ValueError("source-object write guard approval state does not match approved evidence")
        if decision.operation != approved_evidence.operation:
            raise ValueError("source-object write guard operation does not match approved evidence")
        if decision.article_object_id != approved_evidence.article_object_id:
            raise ValueError("source-object write guard article does not match approved evidence")
        if decision.expected_current_version_object_id != approved_evidence.expected_current_version_object_id:
            raise ValueError("source-object write guard expected version does not match approved evidence")
        if decision.proposed_source_object_id != approved_evidence.proposed_source_object_id:
            raise ValueError("source-object write guard proposed source object does not match approved evidence")
        if decision.proposed_source_version_id != approved_evidence.proposed_source_version_id:
            raise ValueError("source-object write guard proposed source version does not match approved evidence")
        if decision.proposed_source_version_evidence_hash != approved_evidence.proposed_source_version_evidence_hash:
            raise ValueError("source-object write guard proposed evidence hash does not match approved evidence")
        if decision.current_restore_evidence_hash != approved_evidence.current_restore_evidence_hash:
            raise ValueError("source-object write guard restore evidence hash does not match approved evidence")

    def _require_source_object_absent(
        self,
        *,
        tenant_id: str,
        evidence: KnowledgeBaseWriteApprovalEvidence,
    ) -> None:
        try:
            self.source_repository.get(
                tenant_id=tenant_id,
                object_id=evidence.proposed_source_object_id,
                version_id=evidence.proposed_source_version_id,
            )
        except KeyError:
            return
        raise ValueError("proposed source object version already exists")

    def evaluate_source_object_write_guard(
        self,
        *,
        user_context: UserContext,
        write_approval_evidence_hash: str,
        proposed_source_record: SourceObjectRecord,
    ) -> KnowledgeBaseSourceObjectWriteGuardDecision:
        records = sorted(
            self.repository.list_articles(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records_by_object_id = {record.object_id: record for record in records}
        source_evidences = [self.source_version_evidence(record) for record in records]
        restore_evidence = build_knowledge_base_restore_evidence(
            tenant_id=user_context.tenant_id,
            articles=records,
            source_evidences=source_evidences,
            restore_drill_report_hash=stable_hash(f"{user_context.tenant_id}:knowledge_base_content:restore-drill"),
            audit_chain_ref="audit:knowledge-base-restore-evidence",
        )
        evidence = self.write_approval_ledger.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=write_approval_evidence_hash,
        )
        return self.source_object_write_guard.evaluate(
            tenant_id=user_context.tenant_id,
            write_approval_evidence_hash=write_approval_evidence_hash,
            write_approval_ledger=self.write_approval_ledger,
            current_article=records_by_object_id.get(evidence.article_object_id),
            proposed_source_record=proposed_source_record,
            current_restore_evidence=restore_evidence,
        )

    def source_version_evidence(self, record: KnowledgeBaseArticleRecord) -> KnowledgeBaseSourceVersionEvidence:
        source_record = self.source_repository.get(
            tenant_id=record.tenant_id,
            object_id=record.current_source_object_id,
            version_id=record.current_source_version_id,
        )
        return build_knowledge_base_source_version_evidence(record, source_record)


def default_knowledge_base_enabled_features() -> dict[str, bool]:
    return {KB_ARTICLES_FEATURE_ID: True, KB_ARTICLES_WRITE_FEATURE_ID: False}


def build_default_knowledge_base_write_approval_ledger() -> KnowledgeBaseWriteApprovalLedger:
    backend = os.getenv("SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryKnowledgeBaseWriteApprovalLedger()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = os.getenv("SUITE_KB_WRITE_APPROVAL_LEDGER_DSN") or os.getenv("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL knowledge base write approval ledger requires "
                "SUITE_KB_WRITE_APPROVAL_LEDGER_DSN or SUITE_DATABASE_DSN"
            )
        return PgKnowledgeBaseWriteApprovalLedger(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND: {backend}")


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


def build_proposed_source_version_evidence(
    *,
    tenant_id: str,
    command: KnowledgeBaseWriteApprovalCommand,
) -> KnowledgeBaseSourceVersionEvidence:
    draft = KnowledgeBaseSourceVersionEvidence(
        tenant_id=tenant_id,
        article_object_id=command.article_object_id,
        article_version_object_id=command.proposed_version_object_id,
        source_object_id=command.proposed_source_object_id,
        source_version_id=command.proposed_source_version_id,
        source_object_type=command.proposed_source_object_type,
        source_manifest_hash=command.proposed_source_manifest_hash,
        content_hash=command.proposed_content_hash,
        acl_version=command.proposed_acl_version,
        data_classification=command.data_classification,
        retention_policy_id=command.retention_policy_id,
        legal_hold_state=command.legal_hold_state,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_version_evidence_hash(draft)})


def build_source_version_evidence_for_source_record(
    *,
    tenant_id: str,
    article_object_id: str,
    article_version_object_id: str,
    source_record: SourceObjectRecord,
) -> KnowledgeBaseSourceVersionEvidence:
    metadata = source_record.metadata
    draft = KnowledgeBaseSourceVersionEvidence(
        tenant_id=tenant_id,
        article_object_id=article_object_id,
        article_version_object_id=article_version_object_id,
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


def build_write_approval_command_hash(command: KnowledgeBaseWriteApprovalCommand) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_write_approval_evidence(
    *,
    tenant_id: str,
    command: KnowledgeBaseWriteApprovalCommand,
    command_hash: str,
    proposed_source_version_evidence_hash: str,
    current_restore_evidence_hash: str,
    requested_by: str,
    audit_event_id: str,
    audit_chain_ref: str,
    approval_state: KnowledgeBaseWriteApprovalState = KnowledgeBaseWriteApprovalState.DRY_RUN,
    transition_source_evidence_hash: str | None = None,
    persistence_allowed: bool = False,
    rag_indexing_allowed: bool = False,
    source_authority_verified: bool = False,
) -> KnowledgeBaseWriteApprovalEvidence:
    draft = KnowledgeBaseWriteApprovalEvidence(
        tenant_id=tenant_id,
        approval_reference=command.approval_reference,
        operation=command.operation,
        approval_state=approval_state,
        article_object_id=command.article_object_id,
        article_key=command.article_key,
        title=command.title,
        expected_current_version_object_id=command.expected_current_version_object_id,
        proposed_version_object_id=command.proposed_version_object_id,
        proposed_version_label=command.proposed_version_label,
        proposed_source_object_id=command.proposed_source_object_id,
        proposed_source_version_id=command.proposed_source_version_id,
        proposed_source_object_type=command.proposed_source_object_type,
        proposed_source_manifest_hash=command.proposed_source_manifest_hash,
        proposed_content_hash=command.proposed_content_hash,
        proposed_acl_version=command.proposed_acl_version,
        command_hash=command_hash,
        proposed_source_version_evidence_hash=proposed_source_version_evidence_hash,
        current_restore_evidence_hash=current_restore_evidence_hash,
        source_object_write_guard_ref="guard:source-object-write-guard-pending",
        transition_source_evidence_hash=transition_source_evidence_hash,
        requested_by=requested_by,
        persistence_allowed=persistence_allowed,
        rag_indexing_allowed=rag_indexing_allowed,
        source_authority_verified=source_authority_verified,
        audit_event_id=audit_event_id,
        audit_chain_ref=audit_chain_ref,
        source_system=command.source_system,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_write_approval_evidence_hash(draft)})


def build_write_approval_transition_evidence(
    *,
    source_evidence: KnowledgeBaseWriteApprovalEvidence,
    approval_reference: str,
    requested_by: str,
    audit_event_id: str,
    audit_chain_ref: str,
) -> KnowledgeBaseWriteApprovalEvidence:
    draft = KnowledgeBaseWriteApprovalEvidence(
        tenant_id=source_evidence.tenant_id,
        approval_reference=approval_reference,
        operation=source_evidence.operation,
        approval_state=KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE,
        article_object_id=source_evidence.article_object_id,
        article_key=source_evidence.article_key,
        title=source_evidence.title,
        expected_current_version_object_id=source_evidence.expected_current_version_object_id,
        proposed_version_object_id=source_evidence.proposed_version_object_id,
        proposed_version_label=source_evidence.proposed_version_label,
        proposed_source_object_id=source_evidence.proposed_source_object_id,
        proposed_source_version_id=source_evidence.proposed_source_version_id,
        proposed_source_object_type=source_evidence.proposed_source_object_type,
        proposed_source_manifest_hash=source_evidence.proposed_source_manifest_hash,
        proposed_content_hash=source_evidence.proposed_content_hash,
        proposed_acl_version=source_evidence.proposed_acl_version,
        command_hash=source_evidence.command_hash,
        proposed_source_version_evidence_hash=source_evidence.proposed_source_version_evidence_hash,
        current_restore_evidence_hash=source_evidence.current_restore_evidence_hash,
        source_object_write_guard_ref="guard:source-object-write-guard-pending",
        transition_source_evidence_hash=source_evidence.evidence_hash,
        requested_by=requested_by,
        persistence_allowed=True,
        rag_indexing_allowed=False,
        source_authority_verified=False,
        audit_event_id=audit_event_id,
        audit_chain_ref=audit_chain_ref,
        source_system=source_evidence.source_system,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_write_approval_evidence_hash(draft)})


def build_write_approval_evidence_hash(evidence: KnowledgeBaseWriteApprovalEvidence) -> str:
    excluded_fields = {"evidence_hash"}
    if evidence.transition_source_evidence_hash is None:
        excluded_fields.add("transition_source_evidence_hash")
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude=excluded_fields)))


def build_evidence_refresh_preview_command_hash(command: KnowledgeBaseEvidenceRefreshPreviewCommand) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_write_execution_skeleton_command_hash(command: KnowledgeBaseWriteExecutionSkeletonCommand) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_write_execution_audit_payload(command: KnowledgeBaseWriteExecutionCommand) -> dict[str, Any]:
    payload = command.model_dump(mode="json", exclude={"proposed_source_record"})
    payload["proposed_source_record"] = {
        "metadata": command.proposed_source_record.metadata.model_dump(mode="json"),
    }
    return payload


def build_write_execution_command_hash(command: KnowledgeBaseWriteExecutionCommand) -> str:
    return stable_hash(canonical_json(build_write_execution_audit_payload(command)))


def build_write_execution_plan_hash(
    *,
    tenant_id: str,
    approved_evidence: KnowledgeBaseWriteApprovalEvidence,
    command: KnowledgeBaseWriteExecutionSkeletonCommand | KnowledgeBaseWriteExecutionCommand,
    execution_command_hash: str,
) -> str:
    payload = {
        "schema_version": "knowledge_base_write_execution_plan.v1",
        "tenant_id": tenant_id,
        "module_id": KNOWLEDGE_BASE_MODULE_ID,
        "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
        "execution_reference": command.execution_reference,
        "human_confirmation_reference": command.human_confirmation_reference,
        "approved_write_approval_evidence_hash": approved_evidence.evidence_hash,
        "transition_source_evidence_hash": approved_evidence.transition_source_evidence_hash,
        "source_object_write_guard_ref": command.source_object_write_guard_decision.source_object_write_guard_ref,
        "refresh_preview_command_hash": command.refresh_preview_command_hash,
        "projected_restore_evidence_preview_hash": command.projected_restore_evidence_preview_hash,
        "operation": approved_evidence.operation,
        "article_object_id": approved_evidence.article_object_id,
        "expected_current_version_object_id": approved_evidence.expected_current_version_object_id,
        "proposed_version_object_id": approved_evidence.proposed_version_object_id,
        "proposed_source_object_id": approved_evidence.proposed_source_object_id,
        "proposed_source_version_id": approved_evidence.proposed_source_version_id,
        "command_hash": approved_evidence.command_hash,
        "execution_command_hash": execution_command_hash,
        "proposed_source_version_evidence_hash": approved_evidence.proposed_source_version_evidence_hash,
        "current_restore_evidence_hash": approved_evidence.current_restore_evidence_hash,
        "preconditions_verified": True,
        "source_object_write_guard_verified": True,
        "human_confirmation_verified": True,
        "source_authority_verified": True,
        "execution_allowed": False,
        "article_source_writes_allowed": False,
        "article_metadata_persistence_allowed": False,
        "source_object_persistence_allowed": False,
        "evidence_persistence_allowed": False,
        "rag_indexing_allowed": False,
        "blocking_reasons": (
            "write_execution_adapter_not_enabled",
            "post_write_source_restore_evidence_refresh_not_connected",
        ),
        "required_evidence": KB_WRITE_EXECUTION_SKELETON_REQUIRED_EVIDENCE,
    }
    return stable_hash(canonical_json(payload))


def build_source_object_write_guard_ref(decision: KnowledgeBaseSourceObjectWriteGuardDecision) -> str:
    payload = canonical_json(decision.model_dump(mode="json", exclude={"source_object_write_guard_ref"}))
    return f"guard:{stable_hash(payload)}"


def knowledge_base_write_target_object_ids(
    command: KnowledgeBaseWriteApprovalCommand,
    existing_article: KnowledgeBaseArticleRecord | None,
) -> list[str]:
    object_ids = [
        command.article_object_id,
        command.expected_current_version_object_id,
        existing_article.current_source_object_id if existing_article is not None else None,
        command.proposed_version_object_id,
        command.proposed_source_object_id,
    ]
    target_object_ids: list[str] = []
    seen: set[str] = set()
    for object_id in object_ids:
        if object_id is not None and object_id not in seen:
            target_object_ids.append(object_id)
            seen.add(object_id)
    return target_object_ids


def knowledge_base_write_evidence_target_object_ids(
    evidence: KnowledgeBaseWriteApprovalEvidence,
    existing_article: KnowledgeBaseArticleRecord | None,
) -> list[str]:
    object_ids = [
        evidence.article_object_id,
        evidence.expected_current_version_object_id,
        existing_article.current_source_object_id if existing_article is not None else None,
        evidence.proposed_version_object_id,
        evidence.proposed_source_object_id,
    ]
    target_object_ids: list[str] = []
    seen: set[str] = set()
    for object_id in object_ids:
        if object_id is not None and object_id not in seen:
            target_object_ids.append(object_id)
            seen.add(object_id)
    return target_object_ids


def build_projected_source_version_evidence_hashes(
    *,
    approved_evidence: KnowledgeBaseWriteApprovalEvidence,
    current_source_evidences: Sequence[KnowledgeBaseSourceVersionEvidence],
) -> tuple[str, ...]:
    current_by_article = {
        evidence.article_object_id: evidence.evidence_hash
        for evidence in sorted(current_source_evidences, key=lambda item: item.article_object_id)
    }
    if approved_evidence.operation == KnowledgeBaseWriteOperation.EDIT:
        if approved_evidence.article_object_id not in current_by_article:
            raise LookupError(f"knowledge base article not found: {approved_evidence.article_object_id}")
        current_by_article[approved_evidence.article_object_id] = (
            approved_evidence.proposed_source_version_evidence_hash
        )
        projected_hashes = tuple(sorted(current_by_article.values()))
    else:
        if approved_evidence.article_object_id in current_by_article:
            raise ValueError("create refresh preview cannot target an existing knowledge base article")
        projected_hashes = tuple(
            sorted((*current_by_article.values(), approved_evidence.proposed_source_version_evidence_hash))
        )
    if len(projected_hashes) != len(set(projected_hashes)):
        raise ValueError("projected source version evidence hashes must be unique")
    return projected_hashes


def build_knowledge_base_restore_evidence_preview_hash(
    *,
    tenant_id: str,
    approved_evidence: KnowledgeBaseWriteApprovalEvidence,
    preview_command_hash: str,
    current_source_version_evidence_hashes: tuple[str, ...],
    projected_source_version_evidence_hashes: tuple[str, ...],
    article_count_before: int,
    article_count_after: int,
    article_version_count_before: int,
    article_version_count_after: int,
    source_version_evidence_count_before: int,
    source_version_evidence_count_after: int,
) -> str:
    payload = {
        "schema_version": "knowledge_base_restore_evidence_refresh_preview.v1",
        "tenant_id": tenant_id,
        "module_id": KNOWLEDGE_BASE_MODULE_ID,
        "feature_id": KB_ARTICLES_WRITE_FEATURE_ID,
        "approved_write_approval_evidence_hash": approved_evidence.evidence_hash,
        "transition_source_evidence_hash": approved_evidence.transition_source_evidence_hash,
        "operation": approved_evidence.operation,
        "article_object_id": approved_evidence.article_object_id,
        "expected_current_version_object_id": approved_evidence.expected_current_version_object_id,
        "proposed_version_object_id": approved_evidence.proposed_version_object_id,
        "proposed_source_object_id": approved_evidence.proposed_source_object_id,
        "proposed_source_version_id": approved_evidence.proposed_source_version_id,
        "command_hash": approved_evidence.command_hash,
        "preview_command_hash": preview_command_hash,
        "proposed_source_version_evidence_hash": approved_evidence.proposed_source_version_evidence_hash,
        "current_restore_evidence_hash": approved_evidence.current_restore_evidence_hash,
        "current_source_version_evidence_hashes": current_source_version_evidence_hashes,
        "projected_source_version_evidence_hashes": projected_source_version_evidence_hashes,
        "article_count_before": article_count_before,
        "article_count_after": article_count_after,
        "article_version_count_before": article_version_count_before,
        "article_version_count_after": article_version_count_after,
        "source_version_evidence_count_before": source_version_evidence_count_before,
        "source_version_evidence_count_after": source_version_evidence_count_after,
        "preview_only": True,
        "article_source_writes_allowed": False,
        "evidence_persistence_allowed": False,
        "rag_indexing_allowed": False,
        "source_authority_verified": False,
        "required_evidence": KB_WRITE_REFRESH_PREVIEW_REQUIRED_EVIDENCE,
    }
    return stable_hash(canonical_json(payload))


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
