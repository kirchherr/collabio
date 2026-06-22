from __future__ import annotations

from enum import StrEnum
from urllib.parse import quote

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
from suite.platform.source_object_preview import (
    SourceObjectPreviewGateStatus,
    SourceObjectPreviewSlot,
    build_source_object_preview_slots,
)
from suite.platform.source_object_preview_decisions import (
    SourceObjectPreviewDecisionEvidence,
    SourceObjectPreviewDecisionLedger,
    SourceObjectPreviewDecisionStatus,
)
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


class ProductCockpitFlowReadinessStatus(StrEnum):
    METADATA_READY_PREVIEW_DECISION_PENDING = "metadata_ready_preview_decision_pending"
    METADATA_READY_PREVIEW_BLOCKED = "metadata_ready_preview_blocked"
    METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED = (
        "metadata_ready_preview_evidence_complete_content_blocked"
    )


class ProductCockpitSourceObjectFlowReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_source_object_flow_readiness.v1"
    status: ProductCockpitFlowReadinessStatus
    source_detail_ready: bool = True
    access_checked: bool = True
    acl_version: int = Field(ge=1)
    audit_visible: bool = True
    source_audit_chain_ref: str
    cockpit_audit_event_id: str | None = None
    preview_gate_status: SourceObjectPreviewGateStatus
    preview_decision_required: bool = True
    preview_decision_available: bool = False
    latest_preview_decision_status: SourceObjectPreviewDecisionStatus | None = None
    latest_preview_decision_evidence_hash: str | None = None
    latest_preview_decision_ledger_ref: str | None = None
    latest_preview_decision_audit_event_id: str | None = None
    latest_preview_decision_missing_evidence: tuple[str, ...] = ()
    latest_preview_decision_blocking_reasons: tuple[str, ...] = ()
    renderer_sandbox_evidence_verified: bool = False
    backup_coverage_evidence_verified: bool = False
    restore_evidence_verified: bool = False
    human_confirmation_verified: bool = False
    content_release_evidence_complete: bool = False
    content_release_allowed: bool = False
    content_included: bool = False
    next_action: str
    blocking_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]


class ProductCockpitReadinessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_readiness_summary.v1"
    metadata_ready_flow_count: int = Field(ge=0)
    access_checked_flow_count: int = Field(ge=0)
    audit_visible_flow_count: int = Field(ge=0)
    preview_decision_pending_count: int = Field(ge=0)
    preview_decision_blocked_count: int = Field(ge=0)
    preview_evidence_complete_but_content_blocked_count: int = Field(ge=0)
    content_release_allowed_count: int = Field(ge=0)
    content_included_count: int = Field(ge=0)


class ProductCockpitWorkItemScope(StrEnum):
    MODULE = "module"
    SOURCE_OBJECT_FLOW = "source_object_flow"


class ProductCockpitWorkItemPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProductCockpitWorkItemUiAction(StrEnum):
    OPEN_FLOW = "open_flow"
    GUIDED_PREVIEW_DECISION = "guided_preview_decision"
    MODULE_PROVISION = "module_provision"
    MODULE_ENABLE = "module_enable"
    MODULE_REVIEW = "module_review"


class ProductCockpitWorkItemActionHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_work_item_action_hint.v1"
    ui_action: ProductCockpitWorkItemUiAction
    label: str
    target_route: str | None = None
    api_method: str | None = None
    api_action: str | None = None
    api_path_templates: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    state_gate: str
    requires_confirmation: bool = False
    compliance_relevant: bool = False
    destructive: bool = False
    external_side_effect: bool = False
    metadata_only: bool = True
    persistent_task_created: bool = False
    content_included: bool = False


class ProductCockpitWorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_work_item.v1"
    work_item_id: str
    scope: ProductCockpitWorkItemScope
    priority: ProductCockpitWorkItemPriority
    action: str
    title: str
    target_label: str
    module_id: str | None = None
    module_status: ModuleStatus | None = None
    flow_id: str | None = None
    source_object_id: str | None = None
    source_version_id: str | None = None
    source_object_type: SourceObjectType | None = None
    origin: ProductCockpitSourceOrigin | None = None
    reason: str
    blocking_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    primary_action_hint: ProductCockpitWorkItemActionHint
    secondary_action_hints: tuple[ProductCockpitWorkItemActionHint, ...] = ()
    persistent_task_created: bool = False
    content_included: bool = False


class ProductCockpitWorkItemOperationalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_work_item_operational_summary.v1"
    work_item_count: int = Field(ge=0)
    action_hint_count: int = Field(ge=0)
    module_work_item_count: int = Field(ge=0)
    source_object_flow_work_item_count: int = Field(ge=0)
    high_priority_work_item_count: int = Field(ge=0)
    medium_priority_work_item_count: int = Field(ge=0)
    low_priority_work_item_count: int = Field(ge=0)
    confirmation_required_action_count: int = Field(ge=0)
    role_required_action_count: int = Field(ge=0)
    admin_role_required_action_count: int = Field(ge=0)
    metadata_only_action_count: int = Field(ge=0)
    content_included_action_count: int = Field(ge=0)
    persistent_task_created_count: int = Field(ge=0)
    destructive_action_count: int = Field(ge=0)
    external_side_effect_action_count: int = Field(ge=0)
    state_transition_signal_count: int = Field(ge=0)
    ui_actions: tuple[str, ...]
    state_gates: tuple[str, ...]
    role_gates: tuple[str, ...]
    state_transition_signals: tuple[str, ...]
    content_included: bool = False


class ProductCockpitMvpReadinessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_readiness_summary.v1"
    entrypoint_route: str = "/workspace"
    mvp_entry_ready: bool
    ready_surface_count: int = Field(ge=0)
    ready_surfaces: tuple[str, ...]
    foundation_gap_count: int = Field(ge=0)
    foundation_gaps: tuple[str, ...]
    deferred_item_count: int = Field(ge=0)
    deferred_items: tuple[str, ...]
    next_foundation_action: str
    module_count: int = Field(ge=0)
    work_item_count: int = Field(ge=0)
    source_object_flow_count: int = Field(ge=0)
    detail_surface_ready: bool
    content_included: bool = False
    persistent_task_created: bool = False


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
    readiness: ProductCockpitSourceObjectFlowReadiness
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
    flow_readiness_summary: ProductCockpitReadinessSummary
    work_items: tuple[ProductCockpitWorkItem, ...]
    work_item_count: int = Field(ge=0)
    work_item_operational_summary: ProductCockpitWorkItemOperationalSummary
    mvp_readiness_summary: ProductCockpitMvpReadinessSummary
    audit_event_id: str


def build_product_cockpit_response(
    *,
    user_context: UserContext,
    module_registry: ModuleRegistryStore,
    workspace_source_repository: SourceObjectRepository,
    workspace_source_refs: tuple[WorkspaceSourceObjectRef, ...],
    knowledge_base_article_service: KnowledgeBaseArticleService,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitResponse:
    module_response = module_registry.discover_tenant_modules(user_context.tenant_id)
    modules = tuple(_module_view(module) for module in module_response.modules)
    module_by_id = {module.module_id: module for module in module_response.modules}
    latest_preview_decisions = _latest_preview_decision_by_source(
        tenant_id=user_context.tenant_id,
        preview_decision_ledger=preview_decision_ledger,
    )
    source_object_flows = tuple(
        sorted(
            [
                *_workspace_source_object_flows(
                    user_context=user_context,
                    workspace_source_repository=workspace_source_repository,
                    workspace_source_refs=workspace_source_refs,
                    latest_preview_decisions=latest_preview_decisions,
                ),
                *_knowledge_base_source_object_flows(
                    user_context=user_context,
                    knowledge_base_article_service=knowledge_base_article_service,
                    module=module_by_id.get(KNOWLEDGE_BASE_MODULE_ID),
                    latest_preview_decisions=latest_preview_decisions,
                ),
            ],
            key=lambda flow: (flow.origin.value, flow.title.lower(), flow.source_object_id),
        )
    )
    readiness_summary = _flow_readiness_summary(source_object_flows)
    preliminary_work_items = _product_work_items(modules=modules, source_object_flows=source_object_flows)
    preliminary_work_item_summary = _work_item_operational_summary(preliminary_work_items)
    mvp_readiness_summary = _mvp_readiness_summary(
        modules=modules,
        source_object_flows=source_object_flows,
        readiness_summary=readiness_summary,
        work_item_summary=preliminary_work_item_summary,
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
            "preview_decision_pending_count": readiness_summary.preview_decision_pending_count,
            "preview_decision_blocked_count": readiness_summary.preview_decision_blocked_count,
            "preview_evidence_complete_but_content_blocked_count": (
                readiness_summary.preview_evidence_complete_but_content_blocked_count
            ),
            "work_item_count": preliminary_work_item_summary.work_item_count,
            "work_item_action_hint_count": preliminary_work_item_summary.action_hint_count,
            "high_priority_work_item_count": preliminary_work_item_summary.high_priority_work_item_count,
            "confirmation_required_work_item_count": preliminary_work_item_summary.confirmation_required_action_count,
            "role_required_work_item_action_count": preliminary_work_item_summary.role_required_action_count,
            "admin_role_required_work_item_action_count": (
                preliminary_work_item_summary.admin_role_required_action_count
            ),
            "work_item_state_transition_signal_count": (preliminary_work_item_summary.state_transition_signal_count),
            "work_item_ui_actions": preliminary_work_item_summary.ui_actions,
            "work_item_state_gates": preliminary_work_item_summary.state_gates,
            "work_item_role_gates": preliminary_work_item_summary.role_gates,
            "work_item_state_transition_signals": preliminary_work_item_summary.state_transition_signals,
            "work_item_persistent_task_created_count": preliminary_work_item_summary.persistent_task_created_count,
            "work_item_content_included_action_count": preliminary_work_item_summary.content_included_action_count,
            "work_item_destructive_action_count": preliminary_work_item_summary.destructive_action_count,
            "work_item_external_side_effect_action_count": (
                preliminary_work_item_summary.external_side_effect_action_count
            ),
            "mvp_entry_ready": mvp_readiness_summary.mvp_entry_ready,
            "mvp_ready_surfaces": mvp_readiness_summary.ready_surfaces,
            "mvp_foundation_gap_count": mvp_readiness_summary.foundation_gap_count,
            "mvp_foundation_gaps": mvp_readiness_summary.foundation_gaps,
            "mvp_deferred_items": mvp_readiness_summary.deferred_items,
            "mvp_next_foundation_action": mvp_readiness_summary.next_foundation_action,
            "mvp_content_included": mvp_readiness_summary.content_included,
            "mvp_persistent_task_created": mvp_readiness_summary.persistent_task_created,
        },
    )
    source_object_flows = _attach_cockpit_audit_event_id(source_object_flows, event.event_id)
    work_items = _product_work_items(modules=modules, source_object_flows=source_object_flows)
    work_item_operational_summary = _work_item_operational_summary(work_items)
    return ProductCockpitResponse(
        tenant_id=user_context.tenant_id,
        modules=modules,
        source_object_flows=source_object_flows,
        source_object_flow_count=len(source_object_flows),
        flow_readiness_summary=readiness_summary,
        work_items=work_items,
        work_item_count=len(work_items),
        work_item_operational_summary=work_item_operational_summary,
        mvp_readiness_summary=mvp_readiness_summary,
        audit_event_id=event.event_id,
    )


def _workspace_source_object_flows(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    workspace_source_refs: tuple[WorkspaceSourceObjectRef, ...],
    latest_preview_decisions: dict[tuple[str, str], SourceObjectPreviewDecisionEvidence],
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
                latest_preview_decision=latest_preview_decisions.get((metadata.object_id, metadata.version_id)),
            )
        )
    return tuple(flows)


def _knowledge_base_source_object_flows(
    *,
    user_context: UserContext,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    module: PlatformModuleView | None,
    latest_preview_decisions: dict[tuple[str, str], SourceObjectPreviewDecisionEvidence],
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
                latest_preview_decision=latest_preview_decisions.get(
                    (source_record.metadata.object_id, source_record.metadata.version_id)
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
    latest_preview_decision: SourceObjectPreviewDecisionEvidence | None,
) -> ProductCockpitSourceObjectFlowView:
    metadata = record.metadata
    preview_slots = build_source_object_preview_slots(metadata.object_type)
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
        preview_slots=preview_slots,
        readiness=_flow_readiness(
            record=record,
            preview_slots=preview_slots,
            source_evidence_refs=evidence_refs,
            latest_preview_decision=latest_preview_decision,
        ),
    )


def _latest_preview_decision_by_source(
    *,
    tenant_id: str,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
) -> dict[tuple[str, str], SourceObjectPreviewDecisionEvidence]:
    latest_by_source: dict[tuple[str, str], SourceObjectPreviewDecisionEvidence] = {}
    for evidence in preview_decision_ledger.list_decisions(tenant_id=tenant_id):
        latest_by_source[(evidence.source_object_id, evidence.source_version_id)] = evidence
    return latest_by_source


def _flow_readiness(
    *,
    record: SourceObjectRecord,
    preview_slots: tuple[SourceObjectPreviewSlot, ...],
    source_evidence_refs: tuple[str, ...],
    latest_preview_decision: SourceObjectPreviewDecisionEvidence | None,
) -> ProductCockpitSourceObjectFlowReadiness:
    metadata = record.metadata
    preview_gate = preview_slots[0].gate
    base_evidence_refs = (
        metadata.manifest_hash,
        metadata.content_hash,
        metadata.audit_chain_ref,
        *source_evidence_refs,
    )
    if latest_preview_decision is None:
        return ProductCockpitSourceObjectFlowReadiness(
            status=ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_DECISION_PENDING,
            acl_version=metadata.acl_version,
            source_audit_chain_ref=metadata.audit_chain_ref,
            preview_gate_status=preview_gate.status,
            next_action="request_preview_decision",
            blocking_reasons=("preview_decision_not_requested", *preview_gate.blocking_reasons),
            evidence_refs=_dedupe_refs(base_evidence_refs),
        )

    status = (
        ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED
        if latest_preview_decision.content_release_evidence_complete
        else ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_BLOCKED
    )
    latest_ref = f"preview-decision-ledger:{latest_preview_decision.evidence_hash}"
    return ProductCockpitSourceObjectFlowReadiness(
        status=status,
        acl_version=metadata.acl_version,
        source_audit_chain_ref=metadata.audit_chain_ref,
        preview_gate_status=preview_gate.status,
        preview_decision_available=True,
        latest_preview_decision_status=latest_preview_decision.decision_status,
        latest_preview_decision_evidence_hash=latest_preview_decision.evidence_hash,
        latest_preview_decision_ledger_ref=latest_ref,
        latest_preview_decision_audit_event_id=latest_preview_decision.audit_event_id,
        latest_preview_decision_missing_evidence=latest_preview_decision.missing_evidence,
        latest_preview_decision_blocking_reasons=latest_preview_decision.blocking_reasons,
        renderer_sandbox_evidence_verified=latest_preview_decision.renderer_sandbox_evidence_verified,
        backup_coverage_evidence_verified=latest_preview_decision.backup_coverage_evidence_verified,
        restore_evidence_verified=latest_preview_decision.restore_evidence_verified,
        human_confirmation_verified=latest_preview_decision.human_confirmation_verified,
        content_release_evidence_complete=latest_preview_decision.content_release_evidence_complete,
        content_release_allowed=latest_preview_decision.content_release_allowed,
        content_included=latest_preview_decision.content_included,
        next_action="review_latest_preview_decision",
        blocking_reasons=latest_preview_decision.blocking_reasons,
        evidence_refs=_dedupe_refs(
            (
                *base_evidence_refs,
                latest_preview_decision.evidence_hash,
                latest_ref,
                f"audit:{latest_preview_decision.audit_event_id}",
                f"audit:{latest_preview_decision.source_detail_audit_event_id}",
            )
        ),
    )


def _attach_cockpit_audit_event_id(
    flows: tuple[ProductCockpitSourceObjectFlowView, ...], audit_event_id: str
) -> tuple[ProductCockpitSourceObjectFlowView, ...]:
    return tuple(
        flow.model_copy(
            update={
                "readiness": flow.readiness.model_copy(
                    update={
                        "cockpit_audit_event_id": audit_event_id,
                        "evidence_refs": _dedupe_refs((*flow.readiness.evidence_refs, f"audit:{audit_event_id}")),
                    }
                )
            }
        )
        for flow in flows
    )


def _flow_readiness_summary(
    flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> ProductCockpitReadinessSummary:
    readinesses = tuple(flow.readiness for flow in flows)
    return ProductCockpitReadinessSummary(
        metadata_ready_flow_count=len(readinesses),
        access_checked_flow_count=sum(1 for readiness in readinesses if readiness.access_checked),
        audit_visible_flow_count=sum(1 for readiness in readinesses if readiness.audit_visible),
        preview_decision_pending_count=sum(
            1
            for readiness in readinesses
            if readiness.status == ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_DECISION_PENDING
        ),
        preview_decision_blocked_count=sum(
            1
            for readiness in readinesses
            if readiness.status
            in {
                ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_BLOCKED,
                ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED,
            }
        ),
        preview_evidence_complete_but_content_blocked_count=sum(
            1
            for readiness in readinesses
            if readiness.status
            == ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED
        ),
        content_release_allowed_count=sum(1 for readiness in readinesses if readiness.content_release_allowed),
        content_included_count=sum(1 for readiness in readinesses if readiness.content_included),
    )


def _product_work_items(
    *,
    modules: tuple[ProductCockpitModuleView, ...],
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> tuple[ProductCockpitWorkItem, ...]:
    items = [
        *(_source_object_work_item(flow) for flow in source_object_flows),
        *(_module_work_item(module) for module in modules if module.next_action != "open_module"),
    ]
    return tuple(sorted(items, key=_work_item_sort_key))


def _work_item_operational_summary(
    work_items: tuple[ProductCockpitWorkItem, ...],
) -> ProductCockpitWorkItemOperationalSummary:
    action_hints = tuple(
        hint for item in work_items for hint in (item.primary_action_hint, *item.secondary_action_hints)
    )
    state_transition_signals = tuple(sorted({f"{item.scope.value}:{item.action}" for item in work_items}))
    return ProductCockpitWorkItemOperationalSummary(
        work_item_count=len(work_items),
        action_hint_count=len(action_hints),
        module_work_item_count=sum(1 for item in work_items if item.scope == ProductCockpitWorkItemScope.MODULE),
        source_object_flow_work_item_count=sum(
            1 for item in work_items if item.scope == ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW
        ),
        high_priority_work_item_count=sum(
            1 for item in work_items if item.priority == ProductCockpitWorkItemPriority.HIGH
        ),
        medium_priority_work_item_count=sum(
            1 for item in work_items if item.priority == ProductCockpitWorkItemPriority.MEDIUM
        ),
        low_priority_work_item_count=sum(
            1 for item in work_items if item.priority == ProductCockpitWorkItemPriority.LOW
        ),
        confirmation_required_action_count=sum(1 for hint in action_hints if hint.requires_confirmation),
        role_required_action_count=sum(1 for hint in action_hints if hint.required_roles),
        admin_role_required_action_count=sum(
            1 for hint in action_hints if {"tenant-admin", "security-admin"}.intersection(set(hint.required_roles))
        ),
        metadata_only_action_count=sum(1 for hint in action_hints if hint.metadata_only),
        content_included_action_count=sum(1 for hint in action_hints if hint.content_included),
        persistent_task_created_count=sum(1 for item in work_items if item.persistent_task_created)
        + sum(1 for hint in action_hints if hint.persistent_task_created),
        destructive_action_count=sum(1 for hint in action_hints if hint.destructive),
        external_side_effect_action_count=sum(1 for hint in action_hints if hint.external_side_effect),
        state_transition_signal_count=len(state_transition_signals),
        ui_actions=tuple(sorted({hint.ui_action.value for hint in action_hints})),
        state_gates=tuple(sorted({hint.state_gate for hint in action_hints})),
        role_gates=tuple(sorted({_role_gate_label(hint.required_roles) for hint in action_hints})),
        state_transition_signals=state_transition_signals,
        content_included=any(item.content_included for item in work_items)
        or any(hint.content_included for hint in action_hints),
    )


def _mvp_readiness_summary(
    *,
    modules: tuple[ProductCockpitModuleView, ...],
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...],
    readiness_summary: ProductCockpitReadinessSummary,
    work_item_summary: ProductCockpitWorkItemOperationalSummary,
) -> ProductCockpitMvpReadinessSummary:
    detail_surface_ready = bool(source_object_flows) and all(
        flow.access_checked and flow.readiness.source_detail_ready and not flow.content_included
        for flow in source_object_flows
    )
    ready_surfaces: list[str] = []
    if modules:
        ready_surfaces.append("module_registry")
    ready_surfaces.append("work_item_queue")
    if source_object_flows:
        ready_surfaces.append("source_object_flows")
    if detail_surface_ready:
        ready_surfaces.append("metadata_detail")

    foundation_gaps: list[str] = []
    if not modules:
        foundation_gaps.append("module_registry_empty")
    if not source_object_flows:
        foundation_gaps.append("source_object_flow_empty")
    if source_object_flows and not detail_surface_ready:
        foundation_gaps.append("metadata_detail_not_ready")
    if readiness_summary.preview_decision_pending_count:
        foundation_gaps.append("preview_decisions_pending")
    if readiness_summary.preview_decision_blocked_count:
        foundation_gaps.append("preview_decisions_blocked")
    if work_item_summary.module_work_item_count:
        foundation_gaps.append("module_activation_work_items_open")
    if work_item_summary.confirmation_required_action_count:
        foundation_gaps.append("human_confirmation_required")
    if source_object_flows and readiness_summary.content_release_allowed_count < len(source_object_flows):
        foundation_gaps.append("content_release_gate_blocks_content")

    deferred_items = (
        "office_editor_suite",
        "mail_client_runtime",
        "persistent_tasks_and_ticketing",
        "lms_time_tracking_activity_modules",
        "full_content_preview_rendering",
    )
    required_surfaces = {"module_registry", "work_item_queue", "source_object_flows", "metadata_detail"}
    mvp_entry_ready = (
        required_surfaces.issubset(set(ready_surfaces))
        and not work_item_summary.content_included
        and work_item_summary.persistent_task_created_count == 0
    )

    return ProductCockpitMvpReadinessSummary(
        mvp_entry_ready=mvp_entry_ready,
        ready_surface_count=len(ready_surfaces),
        ready_surfaces=tuple(ready_surfaces),
        foundation_gap_count=len(foundation_gaps),
        foundation_gaps=tuple(foundation_gaps),
        deferred_item_count=len(deferred_items),
        deferred_items=deferred_items,
        next_foundation_action=_next_mvp_foundation_action(tuple(foundation_gaps)),
        module_count=len(modules),
        work_item_count=work_item_summary.work_item_count,
        source_object_flow_count=len(source_object_flows),
        detail_surface_ready=detail_surface_ready,
        content_included=work_item_summary.content_included,
        persistent_task_created=work_item_summary.persistent_task_created_count > 0,
    )


def _next_mvp_foundation_action(foundation_gaps: tuple[str, ...]) -> str:
    if "preview_decisions_pending" in foundation_gaps:
        return "resolve_preview_decision_work_items"
    if "preview_decisions_blocked" in foundation_gaps:
        return "complete_preview_release_evidence"
    if "module_activation_work_items_open" in foundation_gaps:
        return "complete_module_activation_work_items"
    if "content_release_gate_blocks_content" in foundation_gaps:
        return "keep_content_release_gate_until_renderer_ready"
    if foundation_gaps:
        return foundation_gaps[0]
    return "continue_foundation_review"


def _role_gate_label(required_roles: tuple[str, ...]) -> str:
    if not required_roles:
        return "context"
    return ",".join(required_roles)


def _source_object_work_item(flow: ProductCockpitSourceObjectFlowView) -> ProductCockpitWorkItem:
    readiness = flow.readiness
    if readiness.next_action == "request_preview_decision":
        priority = ProductCockpitWorkItemPriority.HIGH
        title = "Preview Decision anfordern"
        reason = "SourceObject ist metadata-ready; Preview Decision fehlt."
    else:
        priority = (
            ProductCockpitWorkItemPriority.MEDIUM
            if readiness.content_release_evidence_complete
            else ProductCockpitWorkItemPriority.HIGH
        )
        title = "Preview Decision pruefen"
        reason = "Preview Decision liegt vor; Content Release bleibt policy- und renderer-gesteuert blockiert."
    return ProductCockpitWorkItem(
        work_item_id=f"source-object-flow:{flow.flow_id}:{readiness.next_action}",
        scope=ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW,
        priority=priority,
        action=readiness.next_action,
        title=title,
        target_label=flow.title,
        module_id=flow.module_id,
        module_status=flow.module_status,
        flow_id=flow.flow_id,
        source_object_id=flow.source_object_id,
        source_version_id=flow.source_version_id,
        source_object_type=flow.source_object_type,
        origin=flow.origin,
        reason=reason,
        blocking_reasons=readiness.blocking_reasons,
        evidence_refs=readiness.evidence_refs,
        primary_action_hint=_source_object_primary_action_hint(flow),
        secondary_action_hints=(
            (_open_flow_action_hint(flow),) if readiness.next_action == "request_preview_decision" else ()
        ),
    )


def _module_work_item(module: ProductCockpitModuleView) -> ProductCockpitWorkItem:
    return ProductCockpitWorkItem(
        work_item_id=f"module:{module.module_id}:{module.next_action}",
        scope=ProductCockpitWorkItemScope.MODULE,
        priority=_module_work_item_priority(module.next_action),
        action=module.next_action,
        title=_module_work_item_title(module.next_action),
        target_label=module.display_name,
        module_id=module.module_id,
        module_status=module.status,
        reason="Modul ist im Cockpit sichtbar, aber noch nicht im Normalbetrieb offen.",
        blocking_reasons=(module.next_action,),
        evidence_refs=(f"module:{module.module_id}", f"status:{module.status.value}"),
        primary_action_hint=_module_action_hint(module),
    )


def _source_object_primary_action_hint(
    flow: ProductCockpitSourceObjectFlowView,
) -> ProductCockpitWorkItemActionHint:
    if flow.readiness.next_action == "request_preview_decision":
        return ProductCockpitWorkItemActionHint(
            ui_action=ProductCockpitWorkItemUiAction.GUIDED_PREVIEW_DECISION,
            label="Evidence + Decision",
            target_route=_flow_target_route(flow),
            api_method="POST",
            api_action="guided_preview_decision",
            api_path_templates=(
                "/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-renderer-runs",
                "/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-decisions",
            ),
            state_gate="source_object_read_access_and_preview_gate_available",
            requires_confirmation=True,
            compliance_relevant=True,
        )
    return _open_flow_action_hint(flow, label="Preview Decision pruefen")


def _open_flow_action_hint(
    flow: ProductCockpitSourceObjectFlowView, *, label: str = "Flow oeffnen"
) -> ProductCockpitWorkItemActionHint:
    return ProductCockpitWorkItemActionHint(
        ui_action=ProductCockpitWorkItemUiAction.OPEN_FLOW,
        label=label,
        target_route=_flow_target_route(flow),
        state_gate="source_object_read_access_checked",
    )


def _module_action_hint(module: ProductCockpitModuleView) -> ProductCockpitWorkItemActionHint:
    if module.next_action == "provision_module":
        return _module_api_action_hint(
            module=module,
            ui_action=ProductCockpitWorkItemUiAction.MODULE_PROVISION,
            label="Provisionieren",
            api_action="provision",
            state_gate="module_status_available_and_admin_role",
        )
    if module.next_action in {"enable_module", "resolve_suspension"}:
        return _module_api_action_hint(
            module=module,
            ui_action=ProductCockpitWorkItemUiAction.MODULE_ENABLE,
            label="Aktivieren",
            api_action="enable",
            state_gate="module_status_enableable_and_admin_role",
        )
    return ProductCockpitWorkItemActionHint(
        ui_action=ProductCockpitWorkItemUiAction.MODULE_REVIEW,
        label=_module_work_item_title(module.next_action),
        target_route="/workspace",
        required_roles=("tenant-admin", "security-admin"),
        state_gate=f"{module.next_action}_requires_admin_review",
        compliance_relevant=True,
    )


def _module_api_action_hint(
    *,
    module: ProductCockpitModuleView,
    ui_action: ProductCockpitWorkItemUiAction,
    label: str,
    api_action: str,
    state_gate: str,
) -> ProductCockpitWorkItemActionHint:
    return ProductCockpitWorkItemActionHint(
        ui_action=ui_action,
        label=label,
        target_route="/workspace",
        api_method="POST",
        api_action=api_action,
        api_path_templates=(f"/v1/admin/tenant-modules/{module.module_id}/{api_action}",),
        required_roles=("tenant-admin", "security-admin"),
        state_gate=state_gate,
        requires_confirmation=True,
        compliance_relevant=True,
    )


def _flow_target_route(flow: ProductCockpitSourceObjectFlowView) -> str:
    return f"/workspace#source-object={quote(flow.flow_id, safe='')}"


def _module_work_item_priority(action: str) -> ProductCockpitWorkItemPriority:
    if action in {"resolve_suspension", "continue_decommission_workflow"}:
        return ProductCockpitWorkItemPriority.HIGH
    if action in {"retain_compliance_evidence", "review_module_state"}:
        return ProductCockpitWorkItemPriority.LOW
    return ProductCockpitWorkItemPriority.MEDIUM


def _module_work_item_title(action: str) -> str:
    titles = {
        "provision_module": "Modul provisionieren",
        "enable_module": "Modul aktivieren",
        "resolve_suspension": "Modulsperre klaeren",
        "continue_decommission_workflow": "Decommissioning fortsetzen",
        "retain_compliance_evidence": "Compliance Evidence sichern",
        "review_module_state": "Modulstatus pruefen",
    }
    return titles.get(action, "Modulstatus pruefen")


def _work_item_sort_key(item: ProductCockpitWorkItem) -> tuple[int, int, str, str]:
    priority_order = {
        ProductCockpitWorkItemPriority.HIGH: 0,
        ProductCockpitWorkItemPriority.MEDIUM: 1,
        ProductCockpitWorkItemPriority.LOW: 2,
    }
    scope_order = {
        ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW: 0,
        ProductCockpitWorkItemScope.MODULE: 1,
    }
    return (
        priority_order[item.priority],
        scope_order[item.scope],
        item.target_label.lower(),
        item.work_item_id,
    )


def _dedupe_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(ref for ref in refs if ref.strip()))


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
