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
from suite.platform.workspace_source_objects import WorkspaceSourceObjectRef
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry


class ProductCockpitSourceOrigin(StrEnum):
    KNOWLEDGE_BASE = "knowledge_base"
    DOCUMENT = "document"
    MAIL = "mail"


class ProductCockpitModuleView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    display_name: str
    status: ModuleStatus
    normal_use_enabled: bool
    compliance_access_allowed: bool
    enabled_feature_count: int = Field(ge=0)
    continuity_domain: str
    primary_routes: tuple[str, ...]
    next_action: str


class ProductCockpitSourceObjectFlowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: str
    origin: ProductCockpitSourceOrigin
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
    downstream_surfaces: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    preview_slots: tuple[SourceObjectPreviewSlot, ...]
    access_checked: bool = True
    content_included: bool = False


class ProductCockpitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: str = "product_cockpit.v1"
    result_contract: str = "metadata_only_authorized_source_object_flow"
    modules: tuple[ProductCockpitModuleView, ...]
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...]
    source_object_flow_count: int = Field(ge=0)
    audit_event_id: str


def build_product_cockpit_response(
    *,
    user_context: UserContext,
    module_registry: ModuleRegistryStore,
    workspace_source_repository: SourceObjectRepository,
    workspace_source_refs: tuple[WorkspaceSourceObjectRef, ...],
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitResponse:
    module_response = module_registry.discover_tenant_modules(user_context.tenant_id)
    modules = tuple(_module_view(module) for module in module_response.modules)
    module_by_id = {module.module_id: module for module in module_response.modules}
    source_object_flows = tuple(
        sorted(
            [
                *_workspace_source_object_flows(
                    user_context=user_context,
                    workspace_source_repository=workspace_source_repository,
                    workspace_source_refs=workspace_source_refs,
                ),
                *_knowledge_base_source_object_flows(
                    user_context=user_context,
                    knowledge_base_article_service=knowledge_base_article_service,
                    module=module_by_id.get(KNOWLEDGE_BASE_MODULE_ID),
                ),
            ],
            key=lambda flow: (flow.origin.value, flow.title.lower(), flow.source_object_id),
        )
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.module_cockpit.read",
        source_object_ids=[flow.source_object_id for flow in source_object_flows],
        metadata={
            "result_contract": "metadata_only",
            "module_count": len(modules),
            "source_object_flow_count": len(source_object_flows),
            "source_object_types": sorted({flow.source_object_type.value for flow in source_object_flows}),
            "origins": sorted({flow.origin.value for flow in source_object_flows}),
            "content_included": False,
            "access_checked": True,
        },
    )
    return ProductCockpitResponse(
        tenant_id=user_context.tenant_id,
        modules=modules,
        source_object_flows=source_object_flows,
        source_object_flow_count=len(source_object_flows),
        audit_event_id=event.event_id,
    )


def _workspace_source_object_flows(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    workspace_source_refs: tuple[WorkspaceSourceObjectRef, ...],
) -> tuple[ProductCockpitSourceObjectFlowView, ...]:
    flows: list[ProductCockpitSourceObjectFlowView] = []
    for source_ref in workspace_source_refs:
        if source_ref.object_id not in user_context.readable_object_ids:
            continue
        try:
            record = workspace_source_repository.get(
                tenant_id=user_context.tenant_id,
                object_id=source_ref.object_id,
                version_id=source_ref.version_id,
            )
        except KeyError:
            continue
        metadata = record.metadata
        if metadata.object_type not in {SourceObjectType.DOCUMENT, SourceObjectType.MAIL}:
            continue
        origin = (
            ProductCockpitSourceOrigin.MAIL
            if metadata.object_type == SourceObjectType.MAIL
            else ProductCockpitSourceOrigin.DOCUMENT
        )
        downstream = (
            ("mail.message.preview", "source_object.indexing_candidate")
            if origin == ProductCockpitSourceOrigin.MAIL
            else ("office.document.preview", "source_object.indexing_candidate")
        )
        flows.append(
            _source_object_flow(
                record=record,
                origin=origin,
                module_id=None,
                module_status=None,
                downstream_surfaces=downstream,
                evidence_refs=(metadata.manifest_hash, metadata.content_hash),
            )
        )
    return tuple(flows)


def _knowledge_base_source_object_flows(
    *,
    user_context: UserContext,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    module: PlatformModuleView | None,
) -> tuple[ProductCockpitSourceObjectFlowView, ...]:
    kb_articles_enabled = (
        module is not None
        and module.normal_use_enabled
        and module.enabled_features.get(
            KB_ARTICLES_FEATURE_ID,
            False,
        )
    )
    if not kb_articles_enabled:
        return ()
    assert module is not None

    flows: list[ProductCockpitSourceObjectFlowView] = []
    for article in knowledge_base_article_service.repository.list_articles(tenant_id=user_context.tenant_id):
        if (
            article.object_id not in user_context.readable_object_ids
            or article.current_version_object_id not in user_context.readable_object_ids
            or article.current_source_object_id not in user_context.readable_object_ids
        ):
            continue
        source_record = knowledge_base_article_service.source_repository.get(
            tenant_id=user_context.tenant_id,
            object_id=article.current_source_object_id,
            version_id=article.current_source_version_id,
        )
        source_evidence = knowledge_base_article_service.source_version_evidence(article)
        flows.append(
            _source_object_flow(
                record=source_record,
                origin=ProductCockpitSourceOrigin.KNOWLEDGE_BASE,
                module_id=KNOWLEDGE_BASE_MODULE_ID,
                module_status=module.status,
                downstream_surfaces=("knowledge_base.article.read", "source_object.restore_evidence"),
                evidence_refs=(
                    source_evidence.evidence_hash,
                    source_evidence.source_manifest_hash,
                    source_evidence.content_hash,
                    f"article:{article.object_id}",
                    f"object_type:{KB_ARTICLE_OBJECT_TYPE}",
                ),
            )
        )
    return tuple(flows)


def _module_view(module: PlatformModuleView) -> ProductCockpitModuleView:
    enabled_feature_count = sum(1 for enabled in module.enabled_features.values() if enabled)
    return ProductCockpitModuleView(
        module_id=module.module_id,
        display_name=module.display_name,
        status=module.status,
        normal_use_enabled=module.normal_use_enabled,
        compliance_access_allowed=module.compliance_access_allowed,
        enabled_feature_count=enabled_feature_count,
        continuity_domain=_continuity_domain(module.module_id),
        primary_routes=_primary_routes(module.module_id),
        next_action=_next_action(module),
    )


def _source_object_flow(
    *,
    record: SourceObjectRecord,
    origin: ProductCockpitSourceOrigin,
    module_id: str | None,
    module_status: ModuleStatus | None,
    downstream_surfaces: tuple[str, ...],
    evidence_refs: tuple[str, ...],
) -> ProductCockpitSourceObjectFlowView:
    metadata = record.metadata
    return ProductCockpitSourceObjectFlowView(
        flow_id=f"{origin.value}:{metadata.object_id}:{metadata.version_id}",
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
        downstream_surfaces=downstream_surfaces,
        evidence_refs=evidence_refs,
        preview_slots=build_source_object_preview_slots(metadata.object_type),
    )


def _continuity_domain(module_id: str) -> str:
    if module_id == KNOWLEDGE_BASE_MODULE_ID:
        return "knowledge_base_content"
    if module_id == "crm_erp":
        return "crm_erp_business_records"
    return "module_registry_state"


def _primary_routes(module_id: str) -> tuple[str, ...]:
    if module_id == KNOWLEDGE_BASE_MODULE_ID:
        return ("/v1/kb/articles", "/v1/admin/kb/evidence")
    if module_id == "crm_erp":
        return ("/v1/crm/accounts", "/v1/crm/contacts", "/v1/crm/activities", "/v1/erp/products")
    return ()


def _next_action(module: PlatformModuleView) -> str:
    if module.normal_use_enabled:
        return "open_module"
    if module.status == ModuleStatus.AVAILABLE:
        return "provision_module"
    if module.status == ModuleStatus.DISABLED:
        return "enable_module"
    if module.status == ModuleStatus.SUSPENDED:
        return "resolve_suspension"
    if module.status in {ModuleStatus.DECOMMISSION_REQUESTED, ModuleStatus.DECOMMISSION_BLOCKED}:
        return "continue_decommission_workflow"
    if module.status == ModuleStatus.DECOMMISSIONED:
        return "retain_compliance_evidence"
    return "review_module_state"
