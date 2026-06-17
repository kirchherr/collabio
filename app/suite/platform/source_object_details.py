from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.knowledge_base import (
    KB_ARTICLE_OBJECT_TYPE,
    KB_ARTICLES_FEATURE_ID,
    KNOWLEDGE_BASE_MODULE_ID,
    KnowledgeBaseArticleService,
)
from suite.platform.modules import InMemoryModuleRegistry, ModuleStatus, PgModuleRegistry, PlatformModuleView
from suite.platform.source_object_preview import SourceObjectPreviewSlot, build_source_object_preview_slots
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry


class SourceObjectDetailOrigin(StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    DOCUMENT = "document"
    MAIL = "mail"


class SourceObjectDetailAccessDenied(PermissionError):
    pass


class SourceObjectDetailNotFound(LookupError):
    pass


class SourceObjectMetadataDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: str = "source_object_metadata_detail.v1"
    result_contract: str = "metadata_only_acl_checked_source_object_detail"
    origin: SourceObjectDetailOrigin
    module_id: str | None = None
    module_status: ModuleStatus | None = None
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    title: str
    source_system: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: LegalHoldState
    lifecycle_state: SourceLifecycleState
    manifest_hash: str
    content_hash: str
    acl_version: int = Field(ge=1)
    kms_key_ref: str
    audit_chain_ref: str
    mime_type: str
    content_byte_length: int = Field(ge=0)
    parent_object_id: str | None = None
    thread_id: str | None = None
    parser_profile_id: str | None = None
    downstream_surfaces: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    preview_slots: tuple[SourceObjectPreviewSlot, ...]
    access_checked: bool = True
    content_included: bool = False
    audit_event_id: str


def build_source_object_metadata_detail_response(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    source_object_id: str,
    source_version_id: str,
) -> SourceObjectMetadataDetailResponse:
    if source_object_id not in user_context.readable_object_ids:
        _audit_detail_denial(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            denial_reason="acl_object_not_readable",
        )
        raise SourceObjectDetailAccessDenied("User cannot read requested source object metadata")

    workspace_record = _get_source_record_or_none(
        repository=workspace_source_repository,
        tenant_id=user_context.tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
    )
    if workspace_record is not None:
        origin = (
            SourceObjectDetailOrigin.MAIL
            if workspace_record.metadata.object_type == SourceObjectType.MAIL
            else SourceObjectDetailOrigin.DOCUMENT
        )
        downstream_surfaces = (
            ("mail.message.preview", "source_object.indexing_candidate")
            if origin == SourceObjectDetailOrigin.MAIL
            else ("office.document.preview", "source_object.indexing_candidate")
        )
        return _detail_response(
            record=workspace_record,
            origin=origin,
            module_id=None,
            module_status=None,
            downstream_surfaces=downstream_surfaces,
            evidence_refs=(workspace_record.metadata.manifest_hash, workspace_record.metadata.content_hash),
            audit_logger=audit_logger,
            user_context=user_context,
        )

    kb_module = _knowledge_base_module(module_registry=module_registry, tenant_id=user_context.tenant_id)
    if not _knowledge_base_detail_enabled(kb_module):
        _audit_detail_not_found(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            detail_origin="workspace",
        )
        raise SourceObjectDetailNotFound("Source object metadata was not found")
    assert kb_module is not None

    kb_source = _knowledge_base_source_record(
        user_context=user_context,
        knowledge_base_article_service=knowledge_base_article_service,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        audit_logger=audit_logger,
    )
    if kb_source is None:
        _audit_detail_not_found(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            detail_origin=SourceObjectDetailOrigin.KNOWLEDGE_BASE.value,
        )
        raise SourceObjectDetailNotFound("Source object metadata was not found")

    record, evidence_refs = kb_source
    return _detail_response(
        record=record,
        origin=SourceObjectDetailOrigin.KNOWLEDGE_BASE,
        module_id=KNOWLEDGE_BASE_MODULE_ID,
        module_status=kb_module.status,
        downstream_surfaces=("knowledge_base.article.read", "source_object.restore_evidence"),
        evidence_refs=evidence_refs,
        audit_logger=audit_logger,
        user_context=user_context,
    )


def _knowledge_base_source_record(
    *,
    user_context: UserContext,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    source_object_id: str,
    source_version_id: str,
    audit_logger: InMemoryAuditLogger,
) -> tuple[SourceObjectRecord, tuple[str, ...]] | None:
    for article in knowledge_base_article_service.repository.list_articles(tenant_id=user_context.tenant_id):
        if (
            article.current_source_object_id != source_object_id
            or article.current_source_version_id != source_version_id
        ):
            continue
        missing_acl = {
            article.object_id,
            article.current_version_object_id,
            article.current_source_object_id,
        } - user_context.readable_object_ids
        if missing_acl:
            _audit_detail_denial(
                audit_logger=audit_logger,
                user_context=user_context,
                source_object_id=source_object_id,
                source_version_id=source_version_id,
                denial_reason="kb_article_acl_not_readable",
            )
            raise SourceObjectDetailAccessDenied("User cannot read requested knowledge base source metadata")
        try:
            source_record = knowledge_base_article_service.source_repository.get(
                tenant_id=user_context.tenant_id,
                object_id=source_object_id,
                version_id=source_version_id,
            )
        except KeyError:
            return None
        source_evidence = knowledge_base_article_service.source_version_evidence(article)
        return (
            source_record,
            (
                source_evidence.evidence_hash,
                source_evidence.source_manifest_hash,
                source_evidence.content_hash,
                f"article:{article.object_id}",
                f"object_type:{KB_ARTICLE_OBJECT_TYPE}",
            ),
        )
    return None


def _detail_response(
    *,
    record: SourceObjectRecord,
    origin: SourceObjectDetailOrigin,
    module_id: str | None,
    module_status: ModuleStatus | None,
    downstream_surfaces: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
) -> SourceObjectMetadataDetailResponse:
    metadata = record.metadata
    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.metadata_detail.read",
        source_object_ids=[metadata.object_id],
        metadata={
            "source_object_id": metadata.object_id,
            "source_version_id": metadata.version_id,
            "origin": origin.value,
            "module_id": module_id,
            "module_status": module_status.value if module_status is not None else None,
            "source_object_type": metadata.object_type.value,
            "result_contract": "metadata_only",
            "content_included": False,
            "access_checked": True,
            "acl_version": metadata.acl_version,
            "retention_policy_id": metadata.retention_policy_id,
        },
    )
    return SourceObjectMetadataDetailResponse(
        tenant_id=metadata.tenant_id,
        origin=origin,
        module_id=module_id,
        module_status=module_status,
        source_object_id=metadata.object_id,
        source_version_id=metadata.version_id,
        source_object_type=metadata.object_type,
        title=metadata.title,
        source_system=metadata.source_system,
        data_classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state,
        lifecycle_state=metadata.lifecycle_state,
        manifest_hash=metadata.manifest_hash,
        content_hash=metadata.content_hash,
        acl_version=metadata.acl_version,
        kms_key_ref=metadata.kms_key_ref,
        audit_chain_ref=metadata.audit_chain_ref,
        mime_type=metadata.mime_type,
        content_byte_length=metadata.content_byte_length,
        parent_object_id=metadata.parent_object_id,
        thread_id=metadata.thread_id,
        parser_profile_id=metadata.parser_profile_id,
        downstream_surfaces=downstream_surfaces,
        evidence_refs=evidence_refs,
        preview_slots=build_source_object_preview_slots(metadata.object_type),
        audit_event_id=event.event_id,
    )


def _get_source_record_or_none(
    *,
    repository: SourceObjectRepository,
    tenant_id: str,
    source_object_id: str,
    source_version_id: str,
) -> SourceObjectRecord | None:
    try:
        return repository.get(
            tenant_id=tenant_id,
            object_id=source_object_id,
            version_id=source_version_id,
        )
    except KeyError:
        return None


def _knowledge_base_module(
    *,
    module_registry: ModuleRegistryStore,
    tenant_id: str,
) -> PlatformModuleView | None:
    module_response = module_registry.discover_tenant_modules(tenant_id)
    return next((module for module in module_response.modules if module.module_id == KNOWLEDGE_BASE_MODULE_ID), None)


def _knowledge_base_detail_enabled(module: PlatformModuleView | None) -> bool:
    return (
        module is not None and module.normal_use_enabled and module.enabled_features.get(KB_ARTICLES_FEATURE_ID, False)
    )


def _audit_detail_denial(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    denial_reason: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.metadata_detail.denied",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "result_contract": "metadata_only",
            "content_included": False,
            "access_checked": True,
            "denial_reason": denial_reason,
        },
    )


def _audit_detail_not_found(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    detail_origin: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.metadata_detail.not_found",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "origin": detail_origin,
            "result_contract": "metadata_only",
            "content_included": False,
            "access_checked": True,
        },
    )
