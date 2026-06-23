from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
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


BLOCKED_PREVIEW_DEFERRED_EVIDENCE = (
    "content_release_gate_policy_review",
    "viewer_adapter_runtime",
    "full_content_preview_rendering",
)

CONTENT_RELEASE_GATE_DEFERRED_DEPENDENCIES = (
    "content_release_gate_policy_review",
    "viewer_adapter_runtime",
    "full_content_preview_rendering",
)

MVP_RELEASE_REVIEW_GUARDRAIL_CHECKS = (
    "tenant_context_required",
    "metadata_only_contract",
    "no_content_included",
    "no_persistent_tasks_created",
    "no_automation_created",
    "audit_chain_present",
    "role_gates_visible",
    "backup_failover_guardrail_metadata_only",
    "content_release_gate_deferred",
    "open_foundation_gaps_visible",
    "operator_handover_summary_present",
    "reviewer_checklist_present",
)

MVP_RELEASE_REVIEW_SECURITY_GUARDRAILS = (
    "tenant_context_required",
    "metadata_only_contract",
    "no_content_included",
    "audit_chain_present",
    "role_gates_visible",
    "content_release_gate_deferred",
)

MVP_RELEASE_REVIEW_COMPLIANCE_GUARDRAILS = (
    "no_persistent_tasks_created",
    "no_automation_created",
    "backup_failover_guardrail_metadata_only",
    "open_foundation_gaps_visible",
    "operator_handover_summary_present",
    "reviewer_checklist_present",
)

MVP_PILOT_GATE_CHECKS = (
    "release_review_ready",
    "security_guardrails_passed",
    "compliance_guardrails_passed",
    "release_candidate_smoke_passed",
    "metadata_only_path",
    "no_content_included",
    "no_persistent_tasks_created",
    "no_automation_created",
    "audit_chain_present",
    "open_foundation_gaps_tracked",
    "deferred_scope_visible",
)

MVP_PILOT_ALLOWED_SURFACES = (
    "workspace_shell",
    "platform_module_discovery",
    "product_cockpit",
    "mvp_snapshot",
    "mvp_release_evidence",
)

MVP_PILOT_DEFERRED_SURFACES = (
    "content_preview_rendering",
    "office_mail_full_clients",
    "tickets_and_automations",
    "lms_time_tracking_activity_modules",
)

MVP_PILOT_STATUS_SECTIONS = (
    "pilot_gate",
    "release_review",
    "foundation_gaps",
    "allowed_pilot_surfaces",
    "deferred_scope",
    "operator_actions",
)

MVP_PILOT_READINESS_REPORT_SECTIONS = (
    "readiness_decision",
    "evidence_chain",
    "operator_summary",
    "foundation_gap_summary",
    "deferred_scope",
    "reviewer_actions",
)

MVP_PILOT_START_SCOPE_CONTRACTS = (
    "metadata_only_workspace_shell",
    "tenant_safe_module_discovery",
    "product_cockpit_status_views",
    "mvp_release_evidence_review",
    "foundation_gap_tracking",
)

MVP_PILOT_START_SCOPE_EXCLUDED_CONTRACTS = (
    "content_preview_rendering",
    "office_mail_full_clients",
    "tickets_and_automations",
    "new_module_workflows",
)

MVP_PILOT_RUNBOOK_SECTIONS = (
    "scope",
    "evidence_chain",
    "operator_steps",
    "foundation_gaps",
    "deferred_scope",
    "stop_conditions",
)

MVP_PILOT_REVIEW_POINT_SECTIONS = (
    "review_scope",
    "evidence_chain",
    "operator_review",
    "foundation_gaps",
    "deferred_scope",
    "review_outcome",
)

MVP_PILOT_START_DECISION_TEMPLATE_SECTIONS = (
    "confirmation_scope",
    "required_evidence",
    "human_confirmation",
    "foundation_gaps",
    "deferred_scope",
    "non_authorization",
)

MVP_PILOT_DECISION_RECORD_SCHEMA_SECTIONS = (
    "record_identity",
    "required_evidence",
    "human_confirmation",
    "audit_chain",
    "foundation_gaps",
    "non_authorization",
)

MVP_PILOT_DECISION_PREFLIGHT_SECTIONS = (
    "schema_readiness",
    "evidence_chain",
    "confirmation_readiness",
    "foundation_gaps",
    "deferred_scope",
    "preflight_outcome",
)

MVP_PILOT_APPROVAL_WORKFLOW_BOUNDARY_SECTIONS = (
    "workflow_boundary",
    "required_inputs",
    "human_confirmation",
    "decision_record",
    "approval_controls",
    "non_execution",
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
    latest_preview_decision_required_evidence: tuple[str, ...] = ()
    latest_preview_decision_provided_evidence: tuple[str, ...] = ()
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


class ProductCockpitMvpReadinessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_readiness_decision.v1"
    decision: str
    metadata_only_productive_path: bool
    entrypoint_route: str = "/workspace"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    role_gate_status: str
    required_roles: tuple[str, ...] = ()
    audit_gate_status: str
    audit_visible_flow_count: int = Field(ge=0)
    audit_required_flow_count: int = Field(ge=0)
    backup_failover_gate_status: str
    backup_restore_verified_flow_count: int = Field(ge=0)
    backup_restore_deferred_flow_count: int = Field(ge=0)
    module_gate_status: str
    module_count: int = Field(ge=0)
    enabled_module_ids: tuple[str, ...] = ()
    module_action_required_ids: tuple[str, ...] = ()
    foundation_gap_status: str
    active_foundation_gap_ids: tuple[str, ...] = ()
    ready_foundation_gap_ids: tuple[str, ...] = ()
    deferred_foundation_gap_ids: tuple[str, ...] = ()
    content_gate_status: str
    next_foundation_action: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False


class ProductCockpitFoundationGapEvidenceBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_foundation_gap_evidence_brief.v1"
    required_evidence: tuple[str, ...] = ()
    provided_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    evidence_required_now: tuple[str, ...] = ()
    deferred_evidence: tuple[str, ...] = ()
    verified_evidence: tuple[str, ...] = ()
    decision_ledger_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    policy_blocking_reasons: tuple[str, ...] = ()
    content_release_allowed: bool = False
    content_included: bool = False


class ProductCockpitFoundationGapConfirmationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_foundation_gap_confirmation_brief.v1"
    confirmation_work_item_ids: tuple[str, ...] = ()
    covered_by_specific_gap_work_item_ids: tuple[str, ...] = ()
    standalone_work_item_ids: tuple[str, ...] = ()
    covering_gap_ids: tuple[str, ...] = ()
    next_confirmation_action: str = "use_specific_foundation_gap_actions_first"
    requires_separate_foundation_action: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False


class ProductCockpitFoundationGapContentReleaseBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_foundation_gap_content_release_brief.v1"
    blocked_flow_ids: tuple[str, ...] = ()
    blocked_source_object_ids: tuple[str, ...] = ()
    content_release_blocked_count: int = Field(ge=0)
    content_release_allowed_count: int = Field(ge=0)
    content_included_count: int = Field(ge=0)
    preview_decision_pending_count: int = Field(ge=0)
    preview_decision_blocked_count: int = Field(ge=0)
    preview_evidence_complete_but_content_blocked_count: int = Field(ge=0)
    metadata_only_mvp_ready: bool = False
    deferred_dependencies: tuple[str, ...] = ()
    next_release_action: str = "keep_content_release_gate_deferred_for_mvp"
    blocking_reasons: tuple[str, ...] = ()
    content_release_allowed: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False


class ProductCockpitFoundationGapAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_foundation_gap_action.v1"
    priority: int = Field(ge=1)
    gap_id: str
    status: str
    next_action: str
    covered_by_work_item_ids: tuple[str, ...] = ()
    source_object_ids: tuple[str, ...] = ()
    module_ids: tuple[str, ...] = ()
    ui_actions: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    requires_confirmation: bool = False
    metadata_only: bool = True
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    deferred_reason: str | None = None
    evidence_brief: ProductCockpitFoundationGapEvidenceBrief | None = None
    confirmation_brief: ProductCockpitFoundationGapConfirmationBrief | None = None
    content_release_brief: ProductCockpitFoundationGapContentReleaseBrief | None = None


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
    mvp_readiness_decision: ProductCockpitMvpReadinessDecision
    foundation_gap_action_count: int = Field(ge=0)
    foundation_gap_actions: tuple[ProductCockpitFoundationGapAction, ...]
    audit_event_id: str


class ProductCockpitMvpSnapshotModuleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    status: ModuleStatus
    normal_use_enabled: bool
    compliance_access_allowed: bool
    next_action: str
    continuity_domain: str


class ProductCockpitMvpSnapshotSourceObjectFlowRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: str
    origin: ProductCockpitSourceOrigin
    module_id: str | None = None
    module_status: ModuleStatus | None = None
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    acl_version: int = Field(ge=1)
    readiness_status: ProductCockpitFlowReadinessStatus
    next_action: str
    content_release_allowed: bool
    content_included: bool = False
    latest_preview_decision_status: SourceObjectPreviewDecisionStatus | None = None
    cockpit_audit_event_id: str | None = None
    evidence_ref_count: int = Field(ge=0)


class ProductCockpitMvpSnapshotWorkItemRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_item_id: str
    scope: ProductCockpitWorkItemScope
    priority: ProductCockpitWorkItemPriority
    action: str
    module_id: str | None = None
    flow_id: str | None = None
    source_object_id: str | None = None
    source_version_id: str | None = None
    primary_ui_action: ProductCockpitWorkItemUiAction
    requires_confirmation: bool
    required_roles: tuple[str, ...]
    state_gate: str
    content_included: bool = False
    persistent_task_created: bool = False


class ProductCockpitMvpReleaseCandidateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_release_candidate_smoke_report.v1"
    result_contract: str = "metadata_only_mvp_release_candidate_smoke"
    tenant_id: str
    run_id: str
    checked_by: str
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    audit_event_id: str | None = None
    audit_event_types: tuple[str, ...]
    audit_refs: tuple[str, ...]
    snapshot_hash: str
    snapshot_exported: bool
    review_sections: tuple[str, ...]
    demo_tenant_checked: bool
    role_matrix_checked: bool
    context_role_ids: tuple[str, ...]
    role_gates: tuple[str, ...]
    required_roles: tuple[str, ...]
    admin_role_required_action_count: int = Field(ge=0)
    mvp_readiness_decision: str
    metadata_only_productive_path: bool
    module_gate_status: str
    content_gate_status: str
    foundation_gap_status: str
    backup_failover_gate_status: str
    backup_restore_verified_flow_count: int = Field(ge=0)
    backup_restore_deferred_flow_count: int = Field(ge=0)
    source_object_flow_count: int = Field(ge=0)
    module_count: int = Field(ge=0)
    work_item_count: int = Field(ge=0)
    foundation_gap_action_count: int = Field(ge=0)
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    smoke_passed: bool
    recommended_actions: tuple[str, ...]
    evidence_hash: str


class ProductCockpitMvpReleaseHandoverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_release_handover.v1"
    result_contract: str = "metadata_only_mvp_release_handover"
    tenant_id: str
    checked_by: str
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    snapshot_hash: str
    release_candidate_smoke_hash: str
    release_candidate_smoke_passed: bool
    mvp_readiness_decision: str
    metadata_only_productive_path: bool
    handover_status: str
    operator_handover_summary: tuple[str, ...]
    reviewer_checklist: tuple[str, ...]
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpReleaseReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_release_review.v1"
    result_contract: str = "metadata_only_mvp_release_review"
    tenant_id: str
    checked_by: str
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    release_candidate_smoke_passed: bool
    mvp_readiness_decision: str
    metadata_only_productive_path: bool
    handover_status: str
    review_status: str
    security_guardrail_status: str
    compliance_guardrail_status: str
    guardrail_checks: tuple[str, ...]
    passed_guardrail_checks: tuple[str, ...]
    blocked_guardrail_checks: tuple[str, ...]
    operator_handover_summary: tuple[str, ...]
    reviewer_checklist: tuple[str, ...]
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    reviewer_actions: tuple[str, ...]
    evidence_hash: str


class ProductCockpitMvpPilotGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_gate.v1"
    result_contract: str = "metadata_only_mvp_pilot_gate"
    tenant_id: str
    checked_by: str
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    release_candidate_smoke_passed: bool
    release_review_status: str
    security_guardrail_status: str
    compliance_guardrail_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    gate_checks: tuple[str, ...]
    passed_gate_checks: tuple[str, ...]
    blocked_gate_checks: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    pilot_constraints: tuple[str, ...]
    pilot_operator_actions: tuple[str, ...]
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_status.v1"
    result_contract: str = "metadata_only_mvp_pilot_status"
    tenant_id: str
    checked_by: str
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    pilot_gate_status: str
    pilot_gate_decision: str
    release_review_status: str
    security_guardrail_status: str
    compliance_guardrail_status: str
    operational_status: str
    read_only_status: str = "read_only_no_state_change"
    status_sections: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    operator_status_summary: tuple[str, ...]
    operator_attention_items: tuple[str, ...]
    pilot_operator_actions: tuple[str, ...]
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotReadinessReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_readiness_report.v1"
    result_contract: str = "metadata_only_mvp_pilot_readiness_report"
    tenant_id: str
    checked_by: str
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    release_review_status: str
    readiness_status: str
    readiness_decision: str
    report_sections: tuple[str, ...]
    executive_summary: tuple[str, ...]
    foundation_gap_summary: tuple[str, ...]
    deferred_scope_summary: tuple[str, ...]
    reviewer_actions: tuple[str, ...]
    operator_attention_items: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotStartScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_start_scope.v1"
    result_contract: str = "metadata_only_mvp_pilot_start_scope"
    tenant_id: str
    checked_by: str
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    start_scope_summary: tuple[str, ...]
    operator_start_actions: tuple[str, ...]
    expansion_blockers: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotRunbookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_runbook.v1"
    result_contract: str = "metadata_only_mvp_pilot_runbook"
    tenant_id: str
    checked_by: str
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    runbook_sections: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    start_scope_summary: tuple[str, ...]
    expansion_blockers: tuple[str, ...]
    operator_runbook_steps: tuple[str, ...]
    operator_stop_conditions: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotReviewPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_review_point.v1"
    result_contract: str = "metadata_only_mvp_pilot_review_point"
    tenant_id: str
    checked_by: str
    review_point_route: str = "/v1/platform/cockpit/mvp-pilot-review-point"
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    runbook_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    runbook_evidence_hash: str
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    review_point_status: str
    review_point_decision: str
    review_point_sections: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    review_point_summary: tuple[str, ...]
    reviewer_actions: tuple[str, ...]
    review_blockers: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    human_review_required: bool = True
    pilot_start_authorized: bool = False
    approval_record_created: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotStartDecisionTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_start_decision_template.v1"
    result_contract: str = "metadata_only_mvp_pilot_start_decision_template"
    tenant_id: str
    checked_by: str
    template_route: str = "/v1/platform/cockpit/mvp-pilot-start-decision-template"
    review_point_route: str = "/v1/platform/cockpit/mvp-pilot-review-point"
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    runbook_audit_event_id: str
    review_point_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    review_point_evidence_hash: str
    runbook_evidence_hash: str
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    review_point_status: str
    review_point_decision: str
    template_status: str
    template_decision: str
    template_sections: tuple[str, ...]
    confirmation_template_id: str
    confirmation_fields: tuple[str, ...]
    required_confirmation_roles: tuple[str, ...]
    required_confirmation_statements: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    template_summary: tuple[str, ...]
    reviewer_actions: tuple[str, ...]
    confirmation_blockers: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    human_review_required: bool = True
    human_confirmation_required: bool = True
    human_confirmation_captured: bool = False
    pilot_start_authorized: bool = False
    approval_record_created: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotDecisionRecordSchemaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_decision_record_schema.v1"
    result_contract: str = "metadata_only_mvp_pilot_decision_record_schema"
    tenant_id: str
    checked_by: str
    decision_record_schema_route: str = "/v1/platform/cockpit/mvp-pilot-decision-record-schema"
    template_route: str = "/v1/platform/cockpit/mvp-pilot-start-decision-template"
    review_point_route: str = "/v1/platform/cockpit/mvp-pilot-review-point"
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    runbook_audit_event_id: str
    review_point_audit_event_id: str
    template_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    template_evidence_hash: str
    review_point_evidence_hash: str
    runbook_evidence_hash: str
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    review_point_status: str
    review_point_decision: str
    template_status: str
    template_decision: str
    record_schema_status: str
    record_schema_decision: str
    record_schema_sections: tuple[str, ...]
    decision_record_schema_id: str
    decision_record_required_fields: tuple[str, ...]
    immutable_evidence_fields: tuple[str, ...]
    audit_required_fields: tuple[str, ...]
    confirmation_template_id: str
    confirmation_fields: tuple[str, ...]
    required_confirmation_roles: tuple[str, ...]
    required_confirmation_statements: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    record_schema_summary: tuple[str, ...]
    reviewer_actions: tuple[str, ...]
    record_blockers: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    human_review_required: bool = True
    human_confirmation_required: bool = True
    human_confirmation_captured: bool = False
    decision_record_created: bool = False
    pilot_start_authorized: bool = False
    approval_record_created: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotDecisionPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_decision_preflight.v1"
    result_contract: str = "metadata_only_mvp_pilot_decision_preflight"
    tenant_id: str
    checked_by: str
    preflight_route: str = "/v1/platform/cockpit/mvp-pilot-decision-preflight"
    decision_record_schema_route: str = "/v1/platform/cockpit/mvp-pilot-decision-record-schema"
    template_route: str = "/v1/platform/cockpit/mvp-pilot-start-decision-template"
    review_point_route: str = "/v1/platform/cockpit/mvp-pilot-review-point"
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    runbook_audit_event_id: str
    review_point_audit_event_id: str
    template_audit_event_id: str
    decision_record_schema_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    decision_record_schema_evidence_hash: str
    template_evidence_hash: str
    review_point_evidence_hash: str
    runbook_evidence_hash: str
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    review_point_status: str
    review_point_decision: str
    template_status: str
    template_decision: str
    record_schema_status: str
    record_schema_decision: str
    preflight_status: str
    preflight_decision: str
    preflight_sections: tuple[str, ...]
    decision_record_schema_id: str
    decision_record_required_fields: tuple[str, ...]
    immutable_evidence_fields: tuple[str, ...]
    audit_required_fields: tuple[str, ...]
    confirmation_template_id: str
    confirmation_fields: tuple[str, ...]
    required_confirmation_roles: tuple[str, ...]
    required_confirmation_statements: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    preflight_summary: tuple[str, ...]
    preflight_checks: tuple[str, ...]
    preflight_blockers: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    human_review_required: bool = True
    human_confirmation_required: bool = True
    human_confirmation_captured: bool = False
    decision_record_created: bool = False
    pilot_start_authorized: bool = False
    approval_record_created: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpPilotApprovalWorkflowBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "product_cockpit_mvp_pilot_approval_workflow_boundary.v1"
    result_contract: str = "metadata_only_mvp_pilot_approval_workflow_boundary"
    tenant_id: str
    checked_by: str
    approval_workflow_boundary_route: str = "/v1/platform/cockpit/mvp-pilot-approval-workflow-boundary"
    preflight_route: str = "/v1/platform/cockpit/mvp-pilot-decision-preflight"
    decision_record_schema_route: str = "/v1/platform/cockpit/mvp-pilot-decision-record-schema"
    template_route: str = "/v1/platform/cockpit/mvp-pilot-start-decision-template"
    review_point_route: str = "/v1/platform/cockpit/mvp-pilot-review-point"
    runbook_route: str = "/v1/platform/cockpit/mvp-pilot-runbook"
    start_scope_route: str = "/v1/platform/cockpit/mvp-pilot-start-scope"
    readiness_report_route: str = "/v1/platform/cockpit/mvp-pilot-readiness-report"
    pilot_status_route: str = "/v1/platform/cockpit/mvp-pilot-status"
    pilot_gate_route: str = "/v1/platform/cockpit/mvp-pilot-gate"
    review_route: str = "/v1/platform/cockpit/mvp-release-review"
    handover_route: str = "/v1/platform/cockpit/mvp-release-handover"
    entrypoint_route: str = "/workspace"
    cockpit_route: str = "/v1/platform/cockpit"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    smoke_route: str = "/v1/platform/cockpit/mvp-release-candidate-smoke"
    cockpit_audit_event_id: str
    snapshot_audit_event_id: str
    smoke_audit_event_id: str
    handover_audit_event_id: str
    release_review_audit_event_id: str
    pilot_gate_audit_event_id: str
    pilot_status_audit_event_id: str
    readiness_report_audit_event_id: str
    start_scope_audit_event_id: str
    runbook_audit_event_id: str
    review_point_audit_event_id: str
    template_audit_event_id: str
    decision_record_schema_audit_event_id: str
    preflight_audit_event_id: str
    audit_event_id: str | None = None
    audit_refs: tuple[str, ...]
    preflight_evidence_hash: str
    decision_record_schema_evidence_hash: str
    template_evidence_hash: str
    review_point_evidence_hash: str
    runbook_evidence_hash: str
    start_scope_evidence_hash: str
    readiness_report_evidence_hash: str
    pilot_status_evidence_hash: str
    pilot_gate_evidence_hash: str
    release_review_evidence_hash: str
    handover_evidence_hash: str
    snapshot_hash: str
    release_candidate_smoke_hash: str
    readiness_status: str
    readiness_decision: str
    operational_status: str
    read_only_status: str
    pilot_gate_status: str
    pilot_gate_decision: str
    start_scope_status: str
    start_scope_decision: str
    runbook_status: str
    runbook_decision: str
    review_point_status: str
    review_point_decision: str
    template_status: str
    template_decision: str
    record_schema_status: str
    record_schema_decision: str
    preflight_status: str
    preflight_decision: str
    boundary_status: str
    boundary_decision: str
    boundary_sections: tuple[str, ...]
    workflow_boundary_id: str
    workflow_inputs: tuple[str, ...]
    workflow_prohibited_outputs: tuple[str, ...]
    workflow_required_controls: tuple[str, ...]
    decision_record_schema_id: str
    decision_record_required_fields: tuple[str, ...]
    immutable_evidence_fields: tuple[str, ...]
    audit_required_fields: tuple[str, ...]
    confirmation_template_id: str
    confirmation_fields: tuple[str, ...]
    required_confirmation_roles: tuple[str, ...]
    required_confirmation_statements: tuple[str, ...]
    start_scope_contracts: tuple[str, ...]
    excluded_scope_contracts: tuple[str, ...]
    allowed_pilot_surfaces: tuple[str, ...]
    deferred_pilot_surfaces: tuple[str, ...]
    boundary_summary: tuple[str, ...]
    workflow_steps: tuple[str, ...]
    workflow_blockers: tuple[str, ...]
    evidence_chain_summary: tuple[str, ...]
    open_foundation_gap_count: int = Field(ge=0)
    ready_foundation_gap_count: int = Field(ge=0)
    deferred_foundation_gap_count: int = Field(ge=0)
    open_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    role_gates: tuple[str, ...]
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    human_review_required: bool = True
    human_confirmation_required: bool = True
    human_confirmation_captured: bool = False
    decision_record_created: bool = False
    approval_record_created: bool = False
    pilot_start_authorized: bool = False
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    evidence_hash: str


class ProductCockpitMvpSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: str = "product_cockpit_mvp_snapshot.v1"
    result_contract: str = "metadata_only_mvp_handover_snapshot"
    snapshot_route: str = "/v1/platform/cockpit/mvp-snapshot"
    cockpit_route: str = "/v1/platform/cockpit"
    entrypoint_route: str = "/workspace"
    generated_from_cockpit_audit_event_id: str
    review_sections: tuple[str, ...]
    mvp_readiness_summary: ProductCockpitMvpReadinessSummary
    mvp_readiness_decision: ProductCockpitMvpReadinessDecision
    flow_readiness_summary: ProductCockpitReadinessSummary
    work_item_operational_summary: ProductCockpitWorkItemOperationalSummary
    module_refs: tuple[ProductCockpitMvpSnapshotModuleRef, ...]
    source_object_flow_refs: tuple[ProductCockpitMvpSnapshotSourceObjectFlowRef, ...]
    work_item_refs: tuple[ProductCockpitMvpSnapshotWorkItemRef, ...]
    foundation_gap_action_count: int = Field(ge=0)
    foundation_gap_actions: tuple[ProductCockpitFoundationGapAction, ...]
    next_foundation_action: str
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
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
    preliminary_foundation_gap_actions = _foundation_gap_actions(
        mvp_readiness_summary=mvp_readiness_summary,
        work_items=preliminary_work_items,
        source_object_flows=source_object_flows,
    )
    preliminary_mvp_readiness_decision = _mvp_readiness_decision(
        modules=modules,
        source_object_flows=source_object_flows,
        work_item_summary=preliminary_work_item_summary,
        mvp_readiness_summary=mvp_readiness_summary,
        foundation_gap_actions=preliminary_foundation_gap_actions,
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
            "mvp_readiness_decision": preliminary_mvp_readiness_decision.decision,
            "mvp_metadata_only_productive_path": preliminary_mvp_readiness_decision.metadata_only_productive_path,
            "mvp_role_gate_status": preliminary_mvp_readiness_decision.role_gate_status,
            "mvp_audit_gate_status": preliminary_mvp_readiness_decision.audit_gate_status,
            "mvp_backup_failover_gate_status": preliminary_mvp_readiness_decision.backup_failover_gate_status,
            "mvp_module_gate_status": preliminary_mvp_readiness_decision.module_gate_status,
            "mvp_content_gate_status": preliminary_mvp_readiness_decision.content_gate_status,
            "mvp_content_included": mvp_readiness_summary.content_included,
            "mvp_persistent_task_created": mvp_readiness_summary.persistent_task_created,
            "foundation_gap_action_count": len(preliminary_foundation_gap_actions),
            "foundation_gap_action_ids": tuple(action.gap_id for action in preliminary_foundation_gap_actions),
            "foundation_gap_ready_action_count": sum(
                1 for action in preliminary_foundation_gap_actions if action.status == "ready"
            ),
            "foundation_gap_deferred_action_count": sum(
                1 for action in preliminary_foundation_gap_actions if action.status == "deferred"
            ),
            "foundation_gap_content_included": False,
            "foundation_gap_persistent_task_created": False,
            "foundation_gap_automation_created": False,
        },
    )
    source_object_flows = _attach_cockpit_audit_event_id(source_object_flows, event.event_id)
    work_items = _product_work_items(modules=modules, source_object_flows=source_object_flows)
    work_item_operational_summary = _work_item_operational_summary(work_items)
    foundation_gap_actions = _foundation_gap_actions(
        mvp_readiness_summary=mvp_readiness_summary,
        work_items=work_items,
        source_object_flows=source_object_flows,
    )
    mvp_readiness_decision = _mvp_readiness_decision(
        modules=modules,
        source_object_flows=source_object_flows,
        work_item_summary=work_item_operational_summary,
        mvp_readiness_summary=mvp_readiness_summary,
        foundation_gap_actions=foundation_gap_actions,
    )
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
        mvp_readiness_decision=mvp_readiness_decision,
        foundation_gap_action_count=len(foundation_gap_actions),
        foundation_gap_actions=foundation_gap_actions,
        audit_event_id=event.event_id,
    )


def build_product_cockpit_mvp_snapshot_response(
    *,
    user_context: UserContext,
    cockpit_response: ProductCockpitResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpSnapshotResponse:
    module_refs = tuple(_mvp_snapshot_module_ref(module) for module in cockpit_response.modules)
    source_object_flow_refs = tuple(
        _mvp_snapshot_source_object_flow_ref(flow) for flow in cockpit_response.source_object_flows
    )
    work_item_refs = tuple(_mvp_snapshot_work_item_ref(item) for item in cockpit_response.work_items)
    review_sections = (
        "mvp_readiness_summary",
        "mvp_readiness_decision",
        "flow_readiness_summary",
        "work_item_operational_summary",
        "module_refs",
        "source_object_flow_refs",
        "work_item_refs",
        "foundation_gap_actions",
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_snapshot.export",
        source_object_ids=[flow.source_object_id for flow in cockpit_response.source_object_flows],
        metadata={
            "result_contract": "metadata_only_mvp_handover_snapshot",
            "generated_from_cockpit_audit_event_id": cockpit_response.audit_event_id,
            "review_sections": review_sections,
            "module_ref_count": len(module_refs),
            "source_object_flow_ref_count": len(source_object_flow_refs),
            "work_item_ref_count": len(work_item_refs),
            "foundation_gap_action_count": cockpit_response.foundation_gap_action_count,
            "foundation_gap_action_ids": tuple(action.gap_id for action in cockpit_response.foundation_gap_actions),
            "foundation_gap_ready_action_count": sum(
                1 for action in cockpit_response.foundation_gap_actions if action.status == "ready"
            ),
            "foundation_gap_deferred_action_count": sum(
                1 for action in cockpit_response.foundation_gap_actions if action.status == "deferred"
            ),
            "mvp_entry_ready": cockpit_response.mvp_readiness_summary.mvp_entry_ready,
            "mvp_foundation_gap_count": cockpit_response.mvp_readiness_summary.foundation_gap_count,
            "mvp_deferred_item_count": cockpit_response.mvp_readiness_summary.deferred_item_count,
            "mvp_next_foundation_action": cockpit_response.mvp_readiness_summary.next_foundation_action,
            "mvp_readiness_decision": cockpit_response.mvp_readiness_decision.decision,
            "mvp_metadata_only_productive_path": cockpit_response.mvp_readiness_decision.metadata_only_productive_path,
            "mvp_role_gate_status": cockpit_response.mvp_readiness_decision.role_gate_status,
            "mvp_audit_gate_status": cockpit_response.mvp_readiness_decision.audit_gate_status,
            "mvp_backup_failover_gate_status": cockpit_response.mvp_readiness_decision.backup_failover_gate_status,
            "mvp_module_gate_status": cockpit_response.mvp_readiness_decision.module_gate_status,
            "mvp_content_gate_status": cockpit_response.mvp_readiness_decision.content_gate_status,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
            "foundation_gap_content_included": False,
            "foundation_gap_persistent_task_created": False,
            "foundation_gap_automation_created": False,
        },
    )
    return ProductCockpitMvpSnapshotResponse(
        tenant_id=cockpit_response.tenant_id,
        generated_from_cockpit_audit_event_id=cockpit_response.audit_event_id,
        review_sections=review_sections,
        mvp_readiness_summary=cockpit_response.mvp_readiness_summary,
        mvp_readiness_decision=cockpit_response.mvp_readiness_decision,
        flow_readiness_summary=cockpit_response.flow_readiness_summary,
        work_item_operational_summary=cockpit_response.work_item_operational_summary,
        module_refs=module_refs,
        source_object_flow_refs=source_object_flow_refs,
        work_item_refs=work_item_refs,
        foundation_gap_action_count=cockpit_response.foundation_gap_action_count,
        foundation_gap_actions=cockpit_response.foundation_gap_actions,
        next_foundation_action=cockpit_response.mvp_readiness_summary.next_foundation_action,
        audit_event_id=event.event_id,
    )


def build_product_cockpit_mvp_release_candidate_smoke_report(
    *,
    user_context: UserContext,
    cockpit_response: ProductCockpitResponse,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpReleaseCandidateSmokeReport:
    snapshot_hash = stable_hash(canonical_json(snapshot_response.model_dump(mode="json")))
    context_role_ids = tuple(sorted(user_context.role_ids))
    role_gates = snapshot_response.work_item_operational_summary.role_gates
    required_roles = snapshot_response.mvp_readiness_decision.required_roles
    content_included = (
        snapshot_response.content_included
        or snapshot_response.mvp_readiness_decision.content_included
        or snapshot_response.work_item_operational_summary.content_included
    )
    persistent_task_created = (
        snapshot_response.persistent_task_created
        or snapshot_response.mvp_readiness_decision.persistent_task_created
        or snapshot_response.work_item_operational_summary.persistent_task_created_count > 0
    )
    automation_created = (
        snapshot_response.automation_created or snapshot_response.mvp_readiness_decision.automation_created
    )
    role_matrix_checked = bool(role_gates) and "context" in role_gates
    smoke_passed = (
        snapshot_response.tenant_id == cockpit_response.tenant_id == user_context.tenant_id
        and user_context.tenant_id == "tenant-demo"
        and role_matrix_checked
        and snapshot_response.generated_from_cockpit_audit_event_id == cockpit_response.audit_event_id
        and snapshot_response.result_contract == "metadata_only_mvp_handover_snapshot"
        and snapshot_response.mvp_readiness_decision.metadata_only_productive_path
        and snapshot_response.mvp_readiness_decision.audit_gate_status == "audit_visible"
        and snapshot_response.mvp_readiness_decision.backup_failover_gate_status == "metadata_only_no_state_change"
        and snapshot_response.mvp_readiness_decision.content_gate_status == "deferred_metadata_only_ready"
        and not content_included
        and not persistent_task_created
        and not automation_created
    )
    draft = ProductCockpitMvpReleaseCandidateSmokeReport(
        tenant_id=user_context.tenant_id,
        run_id=f"mvp-release-candidate-smoke:{snapshot_response.audit_event_id}",
        checked_by=user_context.user_id,
        cockpit_audit_event_id=cockpit_response.audit_event_id,
        snapshot_audit_event_id=snapshot_response.audit_event_id,
        audit_event_types=("platform.module_cockpit.read", "platform.mvp_snapshot.export"),
        audit_refs=(f"audit:{cockpit_response.audit_event_id}", f"audit:{snapshot_response.audit_event_id}"),
        snapshot_hash=snapshot_hash,
        snapshot_exported=bool(snapshot_response.audit_event_id),
        review_sections=snapshot_response.review_sections,
        demo_tenant_checked=user_context.tenant_id == "tenant-demo",
        role_matrix_checked=role_matrix_checked,
        context_role_ids=context_role_ids,
        role_gates=role_gates,
        required_roles=required_roles,
        admin_role_required_action_count=snapshot_response.work_item_operational_summary.admin_role_required_action_count,
        mvp_readiness_decision=snapshot_response.mvp_readiness_decision.decision,
        metadata_only_productive_path=snapshot_response.mvp_readiness_decision.metadata_only_productive_path,
        module_gate_status=snapshot_response.mvp_readiness_decision.module_gate_status,
        content_gate_status=snapshot_response.mvp_readiness_decision.content_gate_status,
        foundation_gap_status=snapshot_response.mvp_readiness_decision.foundation_gap_status,
        backup_failover_gate_status=snapshot_response.mvp_readiness_decision.backup_failover_gate_status,
        backup_restore_verified_flow_count=snapshot_response.mvp_readiness_decision.backup_restore_verified_flow_count,
        backup_restore_deferred_flow_count=snapshot_response.mvp_readiness_decision.backup_restore_deferred_flow_count,
        source_object_flow_count=snapshot_response.mvp_readiness_summary.source_object_flow_count,
        module_count=snapshot_response.mvp_readiness_summary.module_count,
        work_item_count=snapshot_response.mvp_readiness_summary.work_item_count,
        foundation_gap_action_count=snapshot_response.foundation_gap_action_count,
        content_included=content_included,
        persistent_task_created=persistent_task_created,
        automation_created=automation_created,
        smoke_passed=smoke_passed,
        recommended_actions=_mvp_release_candidate_recommended_actions(smoke_passed=smoke_passed),
        evidence_hash="sha256:" + "0" * 64,
    )
    smoke_event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_release_candidate_smoke.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "snapshot_hash": snapshot_hash,
            "snapshot_audit_event_id": snapshot_response.audit_event_id,
            "cockpit_audit_event_id": cockpit_response.audit_event_id,
            "mvp_readiness_decision": draft.mvp_readiness_decision,
            "metadata_only_productive_path": draft.metadata_only_productive_path,
            "smoke_passed": smoke_passed,
            "role_matrix_checked": draft.role_matrix_checked,
            "backup_failover_gate_status": draft.backup_failover_gate_status,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": smoke_event.event_id,
            "audit_event_types": (*draft.audit_event_types, "platform.mvp_release_candidate_smoke.export"),
            "audit_refs": (*draft.audit_refs, f"audit:{smoke_event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_release_candidate_smoke_report_hash(audited)})


def build_mvp_release_candidate_smoke_report_hash(
    report: ProductCockpitMvpReleaseCandidateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def _mvp_release_candidate_recommended_actions(*, smoke_passed: bool) -> tuple[str, ...]:
    if smoke_passed:
        return (
            "retain MVP snapshot and release-candidate smoke hashes with release evidence",
            "run this smoke before promoting viewer, Office, Mail, ticketing or automation paths",
            "keep content release gate deferred until policy and viewer runtime evidence are ready",
        )
    return ("repair metadata-only MVP release-candidate smoke before productive pilot",)


def build_product_cockpit_mvp_release_handover_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    smoke_report: ProductCockpitMvpReleaseCandidateSmokeReport,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpReleaseHandoverResponse:
    open_gap_ids = snapshot_response.mvp_readiness_decision.active_foundation_gap_ids
    handover_status = (
        "ready_for_operator_reviewer_handover"
        if smoke_report.smoke_passed
        and smoke_report.metadata_only_productive_path
        and not smoke_report.content_included
        and not smoke_report.persistent_task_created
        and not smoke_report.automation_created
        else "handover_blocked"
    )
    draft = ProductCockpitMvpReleaseHandoverResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=smoke_report.cockpit_audit_event_id,
        snapshot_audit_event_id=smoke_report.snapshot_audit_event_id,
        smoke_audit_event_id=smoke_report.audit_event_id or "",
        audit_refs=smoke_report.audit_refs,
        snapshot_hash=smoke_report.snapshot_hash,
        release_candidate_smoke_hash=smoke_report.evidence_hash,
        release_candidate_smoke_passed=smoke_report.smoke_passed,
        mvp_readiness_decision=smoke_report.mvp_readiness_decision,
        metadata_only_productive_path=smoke_report.metadata_only_productive_path,
        handover_status=handover_status,
        operator_handover_summary=(
            f"metadata-only MVP decision: {smoke_report.mvp_readiness_decision}",
            f"snapshot hash: {smoke_report.snapshot_hash}",
            f"release-candidate smoke hash: {smoke_report.evidence_hash}",
            f"open foundation gaps: {','.join(open_gap_ids) if open_gap_ids else 'none'}",
            "content preview, Office/Mail clients, tickets and automations remain deferred",
        ),
        reviewer_checklist=(
            "verify release-candidate smoke_passed is true",
            "retain snapshot_hash and release_candidate_smoke_hash with release evidence",
            "review ready foundation gaps before pilot operation",
            "keep content release gate deferred until policy and viewer runtime evidence are ready",
        ),
        open_foundation_gap_ids=open_gap_ids,
        ready_foundation_gap_ids=snapshot_response.mvp_readiness_decision.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=snapshot_response.mvp_readiness_decision.deferred_foundation_gap_ids,
        next_foundation_action=snapshot_response.mvp_readiness_decision.next_foundation_action,
        required_roles=smoke_report.required_roles,
        role_gates=smoke_report.role_gates,
        module_gate_status=smoke_report.module_gate_status,
        content_gate_status=smoke_report.content_gate_status,
        backup_failover_gate_status=smoke_report.backup_failover_gate_status,
        content_included=smoke_report.content_included,
        persistent_task_created=smoke_report.persistent_task_created,
        automation_created=smoke_report.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_release_handover.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "handover_status": handover_status,
            "snapshot_hash": smoke_report.snapshot_hash,
            "release_candidate_smoke_hash": smoke_report.evidence_hash,
            "release_candidate_smoke_passed": smoke_report.smoke_passed,
            "open_foundation_gap_ids": open_gap_ids,
            "next_foundation_action": draft.next_foundation_action,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_release_handover_hash(audited)})


def build_mvp_release_handover_hash(report: ProductCockpitMvpReleaseHandoverResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_release_review_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    handover_response: ProductCockpitMvpReleaseHandoverResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpReleaseReviewResponse:
    passed_guardrails = _mvp_release_review_passed_guardrails(handover_response)
    blocked_guardrails = tuple(
        guardrail for guardrail in MVP_RELEASE_REVIEW_GUARDRAIL_CHECKS if guardrail not in passed_guardrails
    )
    security_guardrail_status = (
        "passed"
        if all(guardrail in passed_guardrails for guardrail in MVP_RELEASE_REVIEW_SECURITY_GUARDRAILS)
        else "blocked"
    )
    compliance_guardrail_status = (
        "passed"
        if all(guardrail in passed_guardrails for guardrail in MVP_RELEASE_REVIEW_COMPLIANCE_GUARDRAILS)
        else "blocked"
    )
    review_status = (
        "ready_for_release_review"
        if handover_response.handover_status == "ready_for_operator_reviewer_handover"
        and security_guardrail_status == "passed"
        and compliance_guardrail_status == "passed"
        and not blocked_guardrails
        else "release_review_blocked"
    )
    reviewer_actions = _mvp_release_review_reviewer_actions(review_status=review_status)
    draft = ProductCockpitMvpReleaseReviewResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=handover_response.cockpit_audit_event_id,
        snapshot_audit_event_id=handover_response.snapshot_audit_event_id,
        smoke_audit_event_id=handover_response.smoke_audit_event_id,
        handover_audit_event_id=handover_response.audit_event_id or "",
        audit_refs=handover_response.audit_refs,
        handover_evidence_hash=handover_response.evidence_hash,
        snapshot_hash=handover_response.snapshot_hash,
        release_candidate_smoke_hash=handover_response.release_candidate_smoke_hash,
        release_candidate_smoke_passed=handover_response.release_candidate_smoke_passed,
        mvp_readiness_decision=handover_response.mvp_readiness_decision,
        metadata_only_productive_path=handover_response.metadata_only_productive_path,
        handover_status=handover_response.handover_status,
        review_status=review_status,
        security_guardrail_status=security_guardrail_status,
        compliance_guardrail_status=compliance_guardrail_status,
        guardrail_checks=MVP_RELEASE_REVIEW_GUARDRAIL_CHECKS,
        passed_guardrail_checks=passed_guardrails,
        blocked_guardrail_checks=blocked_guardrails,
        operator_handover_summary=handover_response.operator_handover_summary,
        reviewer_checklist=handover_response.reviewer_checklist,
        open_foundation_gap_ids=handover_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=handover_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=handover_response.deferred_foundation_gap_ids,
        next_foundation_action=handover_response.next_foundation_action,
        required_roles=handover_response.required_roles,
        role_gates=handover_response.role_gates,
        module_gate_status=handover_response.module_gate_status,
        content_gate_status=handover_response.content_gate_status,
        backup_failover_gate_status=handover_response.backup_failover_gate_status,
        content_included=handover_response.content_included,
        persistent_task_created=handover_response.persistent_task_created,
        automation_created=handover_response.automation_created,
        reviewer_actions=reviewer_actions,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_release_review.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "review_status": review_status,
            "security_guardrail_status": security_guardrail_status,
            "compliance_guardrail_status": compliance_guardrail_status,
            "handover_evidence_hash": handover_response.evidence_hash,
            "snapshot_hash": handover_response.snapshot_hash,
            "release_candidate_smoke_hash": handover_response.release_candidate_smoke_hash,
            "release_candidate_smoke_passed": handover_response.release_candidate_smoke_passed,
            "passed_guardrail_checks": passed_guardrails,
            "blocked_guardrail_checks": blocked_guardrails,
            "open_foundation_gap_ids": handover_response.open_foundation_gap_ids,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_release_review_hash(audited)})


def build_mvp_release_review_hash(report: ProductCockpitMvpReleaseReviewResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def _mvp_release_review_passed_guardrails(
    handover_response: ProductCockpitMvpReleaseHandoverResponse,
) -> tuple[str, ...]:
    passed: list[str] = []
    if handover_response.tenant_id and handover_response.checked_by:
        passed.append("tenant_context_required")
    if handover_response.result_contract == "metadata_only_mvp_release_handover" and (
        handover_response.metadata_only_productive_path
    ):
        passed.append("metadata_only_contract")
    if not handover_response.content_included:
        passed.append("no_content_included")
    if not handover_response.persistent_task_created:
        passed.append("no_persistent_tasks_created")
    if not handover_response.automation_created:
        passed.append("no_automation_created")
    if handover_response.audit_event_id and f"audit:{handover_response.audit_event_id}" in handover_response.audit_refs:
        passed.append("audit_chain_present")
    if handover_response.required_roles and handover_response.role_gates:
        passed.append("role_gates_visible")
    if handover_response.backup_failover_gate_status == "metadata_only_no_state_change":
        passed.append("backup_failover_guardrail_metadata_only")
    if handover_response.content_gate_status == "deferred_metadata_only_ready":
        passed.append("content_release_gate_deferred")
    if handover_response.open_foundation_gap_ids:
        passed.append("open_foundation_gaps_visible")
    if handover_response.operator_handover_summary:
        passed.append("operator_handover_summary_present")
    if handover_response.reviewer_checklist:
        passed.append("reviewer_checklist_present")
    return tuple(guardrail for guardrail in MVP_RELEASE_REVIEW_GUARDRAIL_CHECKS if guardrail in passed)


def _mvp_release_review_reviewer_actions(*, review_status: str) -> tuple[str, ...]:
    if review_status == "ready_for_release_review":
        return (
            "retain handover_evidence_hash, snapshot_hash and release_candidate_smoke_hash with release evidence",
            "review open foundation gaps before pilot operation",
            "keep content preview, Office/Mail clients, tickets and automations deferred outside MVP release",
        )
    return ("repair blocked release-review guardrails before productive pilot",)


def build_product_cockpit_mvp_pilot_gate_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    release_review_response: ProductCockpitMvpReleaseReviewResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotGateResponse:
    passed_gate_checks = _mvp_pilot_gate_passed_checks(release_review_response)
    blocked_gate_checks = tuple(check for check in MVP_PILOT_GATE_CHECKS if check not in passed_gate_checks)
    pilot_gate_status = "pilot_gate_open_with_deferred_scope" if not blocked_gate_checks else "pilot_gate_blocked"
    pilot_gate_decision = (
        "metadata_only_pilot_allowed_with_deferred_content_release"
        if pilot_gate_status == "pilot_gate_open_with_deferred_scope"
        else "metadata_only_pilot_blocked"
    )
    draft = ProductCockpitMvpPilotGateResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=release_review_response.cockpit_audit_event_id,
        snapshot_audit_event_id=release_review_response.snapshot_audit_event_id,
        smoke_audit_event_id=release_review_response.smoke_audit_event_id,
        handover_audit_event_id=release_review_response.handover_audit_event_id,
        release_review_audit_event_id=release_review_response.audit_event_id or "",
        audit_refs=release_review_response.audit_refs,
        release_review_evidence_hash=release_review_response.evidence_hash,
        handover_evidence_hash=release_review_response.handover_evidence_hash,
        snapshot_hash=release_review_response.snapshot_hash,
        release_candidate_smoke_hash=release_review_response.release_candidate_smoke_hash,
        release_candidate_smoke_passed=release_review_response.release_candidate_smoke_passed,
        release_review_status=release_review_response.review_status,
        security_guardrail_status=release_review_response.security_guardrail_status,
        compliance_guardrail_status=release_review_response.compliance_guardrail_status,
        pilot_gate_status=pilot_gate_status,
        pilot_gate_decision=pilot_gate_decision,
        gate_checks=MVP_PILOT_GATE_CHECKS,
        passed_gate_checks=passed_gate_checks,
        blocked_gate_checks=blocked_gate_checks,
        allowed_pilot_surfaces=MVP_PILOT_ALLOWED_SURFACES,
        deferred_pilot_surfaces=MVP_PILOT_DEFERRED_SURFACES,
        pilot_constraints=_mvp_pilot_gate_constraints(release_review_response),
        pilot_operator_actions=_mvp_pilot_gate_operator_actions(pilot_gate_status=pilot_gate_status),
        open_foundation_gap_ids=release_review_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=release_review_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=release_review_response.deferred_foundation_gap_ids,
        next_foundation_action=release_review_response.next_foundation_action,
        required_roles=release_review_response.required_roles,
        role_gates=release_review_response.role_gates,
        module_gate_status=release_review_response.module_gate_status,
        content_gate_status=release_review_response.content_gate_status,
        backup_failover_gate_status=release_review_response.backup_failover_gate_status,
        content_included=release_review_response.content_included,
        persistent_task_created=release_review_response.persistent_task_created,
        automation_created=release_review_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_gate.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "pilot_gate_status": pilot_gate_status,
            "pilot_gate_decision": pilot_gate_decision,
            "release_review_status": release_review_response.review_status,
            "security_guardrail_status": release_review_response.security_guardrail_status,
            "compliance_guardrail_status": release_review_response.compliance_guardrail_status,
            "release_review_evidence_hash": release_review_response.evidence_hash,
            "handover_evidence_hash": release_review_response.handover_evidence_hash,
            "snapshot_hash": release_review_response.snapshot_hash,
            "release_candidate_smoke_hash": release_review_response.release_candidate_smoke_hash,
            "release_candidate_smoke_passed": release_review_response.release_candidate_smoke_passed,
            "passed_gate_checks": passed_gate_checks,
            "blocked_gate_checks": blocked_gate_checks,
            "allowed_pilot_surfaces": MVP_PILOT_ALLOWED_SURFACES,
            "deferred_pilot_surfaces": MVP_PILOT_DEFERRED_SURFACES,
            "open_foundation_gap_ids": release_review_response.open_foundation_gap_ids,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_gate_hash(audited)})


def build_mvp_pilot_gate_hash(report: ProductCockpitMvpPilotGateResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_status_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    pilot_gate_response: ProductCockpitMvpPilotGateResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotStatusResponse:
    operational_status = (
        "metadata_only_pilot_operational_ready"
        if pilot_gate_response.pilot_gate_status == "pilot_gate_open_with_deferred_scope"
        and pilot_gate_response.security_guardrail_status == "passed"
        and pilot_gate_response.compliance_guardrail_status == "passed"
        and not pilot_gate_response.content_included
        and not pilot_gate_response.persistent_task_created
        and not pilot_gate_response.automation_created
        else "metadata_only_pilot_operational_blocked"
    )
    draft = ProductCockpitMvpPilotStatusResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=pilot_gate_response.cockpit_audit_event_id,
        snapshot_audit_event_id=pilot_gate_response.snapshot_audit_event_id,
        smoke_audit_event_id=pilot_gate_response.smoke_audit_event_id,
        handover_audit_event_id=pilot_gate_response.handover_audit_event_id,
        release_review_audit_event_id=pilot_gate_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=pilot_gate_response.audit_event_id or "",
        audit_refs=pilot_gate_response.audit_refs,
        pilot_gate_evidence_hash=pilot_gate_response.evidence_hash,
        release_review_evidence_hash=pilot_gate_response.release_review_evidence_hash,
        handover_evidence_hash=pilot_gate_response.handover_evidence_hash,
        snapshot_hash=pilot_gate_response.snapshot_hash,
        release_candidate_smoke_hash=pilot_gate_response.release_candidate_smoke_hash,
        pilot_gate_status=pilot_gate_response.pilot_gate_status,
        pilot_gate_decision=pilot_gate_response.pilot_gate_decision,
        release_review_status=pilot_gate_response.release_review_status,
        security_guardrail_status=pilot_gate_response.security_guardrail_status,
        compliance_guardrail_status=pilot_gate_response.compliance_guardrail_status,
        operational_status=operational_status,
        status_sections=MVP_PILOT_STATUS_SECTIONS,
        allowed_pilot_surfaces=pilot_gate_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=pilot_gate_response.deferred_pilot_surfaces,
        open_foundation_gap_count=len(pilot_gate_response.open_foundation_gap_ids),
        ready_foundation_gap_count=len(pilot_gate_response.ready_foundation_gap_ids),
        deferred_foundation_gap_count=len(pilot_gate_response.deferred_foundation_gap_ids),
        open_foundation_gap_ids=pilot_gate_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=pilot_gate_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=pilot_gate_response.deferred_foundation_gap_ids,
        next_foundation_action=pilot_gate_response.next_foundation_action,
        operator_status_summary=_mvp_pilot_status_summary(
            pilot_gate_response=pilot_gate_response,
            operational_status=operational_status,
        ),
        operator_attention_items=_mvp_pilot_status_attention_items(pilot_gate_response),
        pilot_operator_actions=pilot_gate_response.pilot_operator_actions,
        required_roles=pilot_gate_response.required_roles,
        role_gates=pilot_gate_response.role_gates,
        module_gate_status=pilot_gate_response.module_gate_status,
        content_gate_status=pilot_gate_response.content_gate_status,
        backup_failover_gate_status=pilot_gate_response.backup_failover_gate_status,
        content_included=pilot_gate_response.content_included,
        persistent_task_created=pilot_gate_response.persistent_task_created,
        automation_created=pilot_gate_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_status.read",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "operational_status": operational_status,
            "read_only_status": draft.read_only_status,
            "pilot_gate_status": pilot_gate_response.pilot_gate_status,
            "pilot_gate_decision": pilot_gate_response.pilot_gate_decision,
            "release_review_status": pilot_gate_response.release_review_status,
            "pilot_gate_evidence_hash": pilot_gate_response.evidence_hash,
            "release_review_evidence_hash": pilot_gate_response.release_review_evidence_hash,
            "handover_evidence_hash": pilot_gate_response.handover_evidence_hash,
            "snapshot_hash": pilot_gate_response.snapshot_hash,
            "release_candidate_smoke_hash": pilot_gate_response.release_candidate_smoke_hash,
            "status_sections": MVP_PILOT_STATUS_SECTIONS,
            "allowed_pilot_surfaces": pilot_gate_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": pilot_gate_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": pilot_gate_response.open_foundation_gap_ids,
            "open_foundation_gap_count": len(pilot_gate_response.open_foundation_gap_ids),
            "next_foundation_action": pilot_gate_response.next_foundation_action,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_status_hash(audited)})


def build_mvp_pilot_status_hash(report: ProductCockpitMvpPilotStatusResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_readiness_report_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    pilot_status_response: ProductCockpitMvpPilotStatusResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotReadinessReportResponse:
    readiness_status = (
        "ready_for_metadata_only_pilot_review"
        if pilot_status_response.operational_status == "metadata_only_pilot_operational_ready"
        and pilot_status_response.read_only_status == "read_only_no_state_change"
        and not pilot_status_response.content_included
        and not pilot_status_response.persistent_task_created
        and not pilot_status_response.automation_created
        else "pilot_readiness_blocked"
    )
    readiness_decision = (
        "metadata_only_pilot_ready_with_tracked_foundation_gaps"
        if readiness_status == "ready_for_metadata_only_pilot_review"
        else "metadata_only_pilot_not_ready"
    )
    draft = ProductCockpitMvpPilotReadinessReportResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=pilot_status_response.cockpit_audit_event_id,
        snapshot_audit_event_id=pilot_status_response.snapshot_audit_event_id,
        smoke_audit_event_id=pilot_status_response.smoke_audit_event_id,
        handover_audit_event_id=pilot_status_response.handover_audit_event_id,
        release_review_audit_event_id=pilot_status_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=pilot_status_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=pilot_status_response.audit_event_id or "",
        audit_refs=pilot_status_response.audit_refs,
        pilot_status_evidence_hash=pilot_status_response.evidence_hash,
        pilot_gate_evidence_hash=pilot_status_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=pilot_status_response.release_review_evidence_hash,
        handover_evidence_hash=pilot_status_response.handover_evidence_hash,
        snapshot_hash=pilot_status_response.snapshot_hash,
        release_candidate_smoke_hash=pilot_status_response.release_candidate_smoke_hash,
        operational_status=pilot_status_response.operational_status,
        read_only_status=pilot_status_response.read_only_status,
        pilot_gate_status=pilot_status_response.pilot_gate_status,
        pilot_gate_decision=pilot_status_response.pilot_gate_decision,
        release_review_status=pilot_status_response.release_review_status,
        readiness_status=readiness_status,
        readiness_decision=readiness_decision,
        report_sections=MVP_PILOT_READINESS_REPORT_SECTIONS,
        executive_summary=_mvp_pilot_readiness_executive_summary(
            pilot_status_response=pilot_status_response,
            readiness_decision=readiness_decision,
        ),
        foundation_gap_summary=_mvp_pilot_readiness_foundation_gap_summary(pilot_status_response),
        deferred_scope_summary=_mvp_pilot_readiness_deferred_scope_summary(pilot_status_response),
        reviewer_actions=_mvp_pilot_readiness_reviewer_actions(readiness_status=readiness_status),
        operator_attention_items=pilot_status_response.operator_attention_items,
        allowed_pilot_surfaces=pilot_status_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=pilot_status_response.deferred_pilot_surfaces,
        open_foundation_gap_count=pilot_status_response.open_foundation_gap_count,
        ready_foundation_gap_count=pilot_status_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=pilot_status_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=pilot_status_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=pilot_status_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=pilot_status_response.deferred_foundation_gap_ids,
        next_foundation_action=pilot_status_response.next_foundation_action,
        required_roles=pilot_status_response.required_roles,
        role_gates=pilot_status_response.role_gates,
        module_gate_status=pilot_status_response.module_gate_status,
        content_gate_status=pilot_status_response.content_gate_status,
        backup_failover_gate_status=pilot_status_response.backup_failover_gate_status,
        content_included=pilot_status_response.content_included,
        persistent_task_created=pilot_status_response.persistent_task_created,
        automation_created=pilot_status_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_readiness_report.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "readiness_status": readiness_status,
            "readiness_decision": readiness_decision,
            "operational_status": pilot_status_response.operational_status,
            "read_only_status": pilot_status_response.read_only_status,
            "pilot_status_evidence_hash": pilot_status_response.evidence_hash,
            "pilot_gate_evidence_hash": pilot_status_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": pilot_status_response.release_review_evidence_hash,
            "handover_evidence_hash": pilot_status_response.handover_evidence_hash,
            "snapshot_hash": pilot_status_response.snapshot_hash,
            "release_candidate_smoke_hash": pilot_status_response.release_candidate_smoke_hash,
            "report_sections": MVP_PILOT_READINESS_REPORT_SECTIONS,
            "allowed_pilot_surfaces": pilot_status_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": pilot_status_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": pilot_status_response.open_foundation_gap_ids,
            "open_foundation_gap_count": pilot_status_response.open_foundation_gap_count,
            "next_foundation_action": pilot_status_response.next_foundation_action,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_readiness_report_hash(audited)})


def build_mvp_pilot_readiness_report_hash(report: ProductCockpitMvpPilotReadinessReportResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_start_scope_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    readiness_report: ProductCockpitMvpPilotReadinessReportResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotStartScopeResponse:
    start_scope_status = (
        "metadata_only_pilot_start_scope_fixed"
        if readiness_report.readiness_status == "ready_for_metadata_only_pilot_review"
        and readiness_report.read_only_status == "read_only_no_state_change"
        and not readiness_report.content_included
        and not readiness_report.persistent_task_created
        and not readiness_report.automation_created
        else "metadata_only_pilot_start_scope_blocked"
    )
    start_scope_decision = (
        "minimal_metadata_only_pilot_scope_fixed_with_deferred_expansion"
        if start_scope_status == "metadata_only_pilot_start_scope_fixed"
        else "minimal_metadata_only_pilot_scope_not_fixed"
    )
    draft = ProductCockpitMvpPilotStartScopeResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=readiness_report.cockpit_audit_event_id,
        snapshot_audit_event_id=readiness_report.snapshot_audit_event_id,
        smoke_audit_event_id=readiness_report.smoke_audit_event_id,
        handover_audit_event_id=readiness_report.handover_audit_event_id,
        release_review_audit_event_id=readiness_report.release_review_audit_event_id,
        pilot_gate_audit_event_id=readiness_report.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=readiness_report.pilot_status_audit_event_id,
        readiness_report_audit_event_id=readiness_report.audit_event_id or "",
        audit_refs=readiness_report.audit_refs,
        readiness_report_evidence_hash=readiness_report.evidence_hash,
        pilot_status_evidence_hash=readiness_report.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=readiness_report.pilot_gate_evidence_hash,
        release_review_evidence_hash=readiness_report.release_review_evidence_hash,
        handover_evidence_hash=readiness_report.handover_evidence_hash,
        snapshot_hash=readiness_report.snapshot_hash,
        release_candidate_smoke_hash=readiness_report.release_candidate_smoke_hash,
        readiness_status=readiness_report.readiness_status,
        readiness_decision=readiness_report.readiness_decision,
        operational_status=readiness_report.operational_status,
        read_only_status=readiness_report.read_only_status,
        pilot_gate_status=readiness_report.pilot_gate_status,
        pilot_gate_decision=readiness_report.pilot_gate_decision,
        start_scope_status=start_scope_status,
        start_scope_decision=start_scope_decision,
        start_scope_contracts=MVP_PILOT_START_SCOPE_CONTRACTS,
        excluded_scope_contracts=MVP_PILOT_START_SCOPE_EXCLUDED_CONTRACTS,
        allowed_pilot_surfaces=readiness_report.allowed_pilot_surfaces,
        deferred_pilot_surfaces=readiness_report.deferred_pilot_surfaces,
        start_scope_summary=_mvp_pilot_start_scope_summary(
            readiness_report=readiness_report,
            start_scope_decision=start_scope_decision,
        ),
        operator_start_actions=_mvp_pilot_start_operator_actions(start_scope_status=start_scope_status),
        expansion_blockers=_mvp_pilot_start_expansion_blockers(readiness_report),
        open_foundation_gap_count=readiness_report.open_foundation_gap_count,
        ready_foundation_gap_count=readiness_report.ready_foundation_gap_count,
        deferred_foundation_gap_count=readiness_report.deferred_foundation_gap_count,
        open_foundation_gap_ids=readiness_report.open_foundation_gap_ids,
        ready_foundation_gap_ids=readiness_report.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=readiness_report.deferred_foundation_gap_ids,
        next_foundation_action=readiness_report.next_foundation_action,
        required_roles=readiness_report.required_roles,
        role_gates=readiness_report.role_gates,
        module_gate_status=readiness_report.module_gate_status,
        content_gate_status=readiness_report.content_gate_status,
        backup_failover_gate_status=readiness_report.backup_failover_gate_status,
        content_included=readiness_report.content_included,
        persistent_task_created=readiness_report.persistent_task_created,
        automation_created=readiness_report.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_start_scope.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "start_scope_status": start_scope_status,
            "start_scope_decision": start_scope_decision,
            "readiness_status": readiness_report.readiness_status,
            "readiness_decision": readiness_report.readiness_decision,
            "operational_status": readiness_report.operational_status,
            "read_only_status": readiness_report.read_only_status,
            "readiness_report_evidence_hash": readiness_report.evidence_hash,
            "pilot_status_evidence_hash": readiness_report.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": readiness_report.pilot_gate_evidence_hash,
            "release_review_evidence_hash": readiness_report.release_review_evidence_hash,
            "handover_evidence_hash": readiness_report.handover_evidence_hash,
            "snapshot_hash": readiness_report.snapshot_hash,
            "release_candidate_smoke_hash": readiness_report.release_candidate_smoke_hash,
            "start_scope_contracts": MVP_PILOT_START_SCOPE_CONTRACTS,
            "excluded_scope_contracts": MVP_PILOT_START_SCOPE_EXCLUDED_CONTRACTS,
            "allowed_pilot_surfaces": readiness_report.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": readiness_report.deferred_pilot_surfaces,
            "open_foundation_gap_ids": readiness_report.open_foundation_gap_ids,
            "open_foundation_gap_count": readiness_report.open_foundation_gap_count,
            "next_foundation_action": readiness_report.next_foundation_action,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_start_scope_hash(audited)})


def build_mvp_pilot_start_scope_hash(report: ProductCockpitMvpPilotStartScopeResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_runbook_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    start_scope_response: ProductCockpitMvpPilotStartScopeResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotRunbookResponse:
    runbook_status = (
        "metadata_only_pilot_runbook_ready"
        if start_scope_response.start_scope_status == "metadata_only_pilot_start_scope_fixed"
        and start_scope_response.readiness_status == "ready_for_metadata_only_pilot_review"
        and start_scope_response.read_only_status == "read_only_no_state_change"
        and start_scope_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not start_scope_response.content_included
        and not start_scope_response.persistent_task_created
        and not start_scope_response.automation_created
        else "metadata_only_pilot_runbook_blocked"
    )
    runbook_decision = (
        "pilot_operator_path_ready_with_tracked_gaps"
        if runbook_status == "metadata_only_pilot_runbook_ready"
        else "pilot_operator_path_blocked"
    )
    draft = ProductCockpitMvpPilotRunbookResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=start_scope_response.cockpit_audit_event_id,
        snapshot_audit_event_id=start_scope_response.snapshot_audit_event_id,
        smoke_audit_event_id=start_scope_response.smoke_audit_event_id,
        handover_audit_event_id=start_scope_response.handover_audit_event_id,
        release_review_audit_event_id=start_scope_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=start_scope_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=start_scope_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=start_scope_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=start_scope_response.audit_event_id or "",
        audit_refs=start_scope_response.audit_refs,
        start_scope_evidence_hash=start_scope_response.evidence_hash,
        readiness_report_evidence_hash=start_scope_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=start_scope_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=start_scope_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=start_scope_response.release_review_evidence_hash,
        handover_evidence_hash=start_scope_response.handover_evidence_hash,
        snapshot_hash=start_scope_response.snapshot_hash,
        release_candidate_smoke_hash=start_scope_response.release_candidate_smoke_hash,
        readiness_status=start_scope_response.readiness_status,
        readiness_decision=start_scope_response.readiness_decision,
        operational_status=start_scope_response.operational_status,
        read_only_status=start_scope_response.read_only_status,
        pilot_gate_status=start_scope_response.pilot_gate_status,
        pilot_gate_decision=start_scope_response.pilot_gate_decision,
        start_scope_status=start_scope_response.start_scope_status,
        start_scope_decision=start_scope_response.start_scope_decision,
        runbook_status=runbook_status,
        runbook_decision=runbook_decision,
        runbook_sections=MVP_PILOT_RUNBOOK_SECTIONS,
        start_scope_contracts=start_scope_response.start_scope_contracts,
        excluded_scope_contracts=start_scope_response.excluded_scope_contracts,
        allowed_pilot_surfaces=start_scope_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=start_scope_response.deferred_pilot_surfaces,
        start_scope_summary=start_scope_response.start_scope_summary,
        expansion_blockers=start_scope_response.expansion_blockers,
        operator_runbook_steps=_mvp_pilot_runbook_steps(start_scope_response),
        operator_stop_conditions=_mvp_pilot_runbook_stop_conditions(start_scope_response),
        evidence_chain_summary=_mvp_pilot_runbook_evidence_chain_summary(start_scope_response),
        open_foundation_gap_count=start_scope_response.open_foundation_gap_count,
        ready_foundation_gap_count=start_scope_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=start_scope_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=start_scope_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=start_scope_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=start_scope_response.deferred_foundation_gap_ids,
        next_foundation_action=start_scope_response.next_foundation_action,
        required_roles=start_scope_response.required_roles,
        role_gates=start_scope_response.role_gates,
        module_gate_status=start_scope_response.module_gate_status,
        content_gate_status=start_scope_response.content_gate_status,
        backup_failover_gate_status=start_scope_response.backup_failover_gate_status,
        content_included=start_scope_response.content_included,
        persistent_task_created=start_scope_response.persistent_task_created,
        automation_created=start_scope_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_runbook.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "runbook_status": runbook_status,
            "runbook_decision": runbook_decision,
            "start_scope_status": start_scope_response.start_scope_status,
            "start_scope_decision": start_scope_response.start_scope_decision,
            "readiness_status": start_scope_response.readiness_status,
            "readiness_decision": start_scope_response.readiness_decision,
            "operational_status": start_scope_response.operational_status,
            "read_only_status": start_scope_response.read_only_status,
            "start_scope_evidence_hash": start_scope_response.evidence_hash,
            "readiness_report_evidence_hash": start_scope_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": start_scope_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": start_scope_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": start_scope_response.release_review_evidence_hash,
            "handover_evidence_hash": start_scope_response.handover_evidence_hash,
            "snapshot_hash": start_scope_response.snapshot_hash,
            "release_candidate_smoke_hash": start_scope_response.release_candidate_smoke_hash,
            "runbook_sections": MVP_PILOT_RUNBOOK_SECTIONS,
            "start_scope_contracts": start_scope_response.start_scope_contracts,
            "excluded_scope_contracts": start_scope_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": start_scope_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": start_scope_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": start_scope_response.open_foundation_gap_ids,
            "open_foundation_gap_count": start_scope_response.open_foundation_gap_count,
            "next_foundation_action": start_scope_response.next_foundation_action,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_runbook_hash(audited)})


def build_mvp_pilot_runbook_hash(report: ProductCockpitMvpPilotRunbookResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_review_point_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    runbook_response: ProductCockpitMvpPilotRunbookResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotReviewPointResponse:
    review_point_status = (
        "metadata_only_pilot_review_point_ready"
        if runbook_response.runbook_status == "metadata_only_pilot_runbook_ready"
        and runbook_response.start_scope_status == "metadata_only_pilot_start_scope_fixed"
        and runbook_response.readiness_status == "ready_for_metadata_only_pilot_review"
        and runbook_response.read_only_status == "read_only_no_state_change"
        and runbook_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not runbook_response.content_included
        and not runbook_response.persistent_task_created
        and not runbook_response.automation_created
        else "metadata_only_pilot_review_point_blocked"
    )
    review_point_decision = (
        "pilot_start_review_required_with_tracked_gaps"
        if review_point_status == "metadata_only_pilot_review_point_ready"
        else "pilot_start_review_blocked"
    )
    draft = ProductCockpitMvpPilotReviewPointResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=runbook_response.cockpit_audit_event_id,
        snapshot_audit_event_id=runbook_response.snapshot_audit_event_id,
        smoke_audit_event_id=runbook_response.smoke_audit_event_id,
        handover_audit_event_id=runbook_response.handover_audit_event_id,
        release_review_audit_event_id=runbook_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=runbook_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=runbook_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=runbook_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=runbook_response.start_scope_audit_event_id,
        runbook_audit_event_id=runbook_response.audit_event_id or "",
        audit_refs=runbook_response.audit_refs,
        runbook_evidence_hash=runbook_response.evidence_hash,
        start_scope_evidence_hash=runbook_response.start_scope_evidence_hash,
        readiness_report_evidence_hash=runbook_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=runbook_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=runbook_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=runbook_response.release_review_evidence_hash,
        handover_evidence_hash=runbook_response.handover_evidence_hash,
        snapshot_hash=runbook_response.snapshot_hash,
        release_candidate_smoke_hash=runbook_response.release_candidate_smoke_hash,
        readiness_status=runbook_response.readiness_status,
        readiness_decision=runbook_response.readiness_decision,
        operational_status=runbook_response.operational_status,
        read_only_status=runbook_response.read_only_status,
        pilot_gate_status=runbook_response.pilot_gate_status,
        pilot_gate_decision=runbook_response.pilot_gate_decision,
        start_scope_status=runbook_response.start_scope_status,
        start_scope_decision=runbook_response.start_scope_decision,
        runbook_status=runbook_response.runbook_status,
        runbook_decision=runbook_response.runbook_decision,
        review_point_status=review_point_status,
        review_point_decision=review_point_decision,
        review_point_sections=MVP_PILOT_REVIEW_POINT_SECTIONS,
        start_scope_contracts=runbook_response.start_scope_contracts,
        excluded_scope_contracts=runbook_response.excluded_scope_contracts,
        allowed_pilot_surfaces=runbook_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=runbook_response.deferred_pilot_surfaces,
        review_point_summary=_mvp_pilot_review_point_summary(
            runbook_response=runbook_response,
            review_point_decision=review_point_decision,
        ),
        reviewer_actions=_mvp_pilot_review_point_reviewer_actions(review_point_status=review_point_status),
        review_blockers=_mvp_pilot_review_point_blockers(runbook_response),
        evidence_chain_summary=_mvp_pilot_review_point_evidence_chain_summary(runbook_response),
        open_foundation_gap_count=runbook_response.open_foundation_gap_count,
        ready_foundation_gap_count=runbook_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=runbook_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=runbook_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=runbook_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=runbook_response.deferred_foundation_gap_ids,
        next_foundation_action=runbook_response.next_foundation_action,
        required_roles=runbook_response.required_roles,
        role_gates=runbook_response.role_gates,
        module_gate_status=runbook_response.module_gate_status,
        content_gate_status=runbook_response.content_gate_status,
        backup_failover_gate_status=runbook_response.backup_failover_gate_status,
        human_review_required=True,
        pilot_start_authorized=False,
        approval_record_created=False,
        content_included=runbook_response.content_included,
        persistent_task_created=runbook_response.persistent_task_created,
        automation_created=runbook_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_review_point.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "review_point_status": review_point_status,
            "review_point_decision": review_point_decision,
            "runbook_status": runbook_response.runbook_status,
            "runbook_decision": runbook_response.runbook_decision,
            "start_scope_status": runbook_response.start_scope_status,
            "start_scope_decision": runbook_response.start_scope_decision,
            "readiness_status": runbook_response.readiness_status,
            "readiness_decision": runbook_response.readiness_decision,
            "operational_status": runbook_response.operational_status,
            "read_only_status": runbook_response.read_only_status,
            "runbook_evidence_hash": runbook_response.evidence_hash,
            "start_scope_evidence_hash": runbook_response.start_scope_evidence_hash,
            "readiness_report_evidence_hash": runbook_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": runbook_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": runbook_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": runbook_response.release_review_evidence_hash,
            "handover_evidence_hash": runbook_response.handover_evidence_hash,
            "snapshot_hash": runbook_response.snapshot_hash,
            "release_candidate_smoke_hash": runbook_response.release_candidate_smoke_hash,
            "review_point_sections": MVP_PILOT_REVIEW_POINT_SECTIONS,
            "start_scope_contracts": runbook_response.start_scope_contracts,
            "excluded_scope_contracts": runbook_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": runbook_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": runbook_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": runbook_response.open_foundation_gap_ids,
            "open_foundation_gap_count": runbook_response.open_foundation_gap_count,
            "next_foundation_action": runbook_response.next_foundation_action,
            "human_review_required": True,
            "pilot_start_authorized": False,
            "approval_record_created": False,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_review_point_hash(audited)})


def build_mvp_pilot_review_point_hash(report: ProductCockpitMvpPilotReviewPointResponse) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_start_decision_template_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    review_point_response: ProductCockpitMvpPilotReviewPointResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotStartDecisionTemplateResponse:
    template_status = (
        "metadata_only_pilot_start_decision_template_ready"
        if review_point_response.review_point_status == "metadata_only_pilot_review_point_ready"
        and review_point_response.human_review_required
        and not review_point_response.pilot_start_authorized
        and not review_point_response.approval_record_created
        and review_point_response.read_only_status == "read_only_no_state_change"
        and review_point_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not review_point_response.content_included
        and not review_point_response.persistent_task_created
        and not review_point_response.automation_created
        else "metadata_only_pilot_start_decision_template_blocked"
    )
    template_decision = (
        "human_confirmation_template_ready_without_pilot_authorization"
        if template_status == "metadata_only_pilot_start_decision_template_ready"
        else "human_confirmation_template_blocked"
    )
    confirmation_fields = _mvp_pilot_start_decision_confirmation_fields()
    draft = ProductCockpitMvpPilotStartDecisionTemplateResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=review_point_response.cockpit_audit_event_id,
        snapshot_audit_event_id=review_point_response.snapshot_audit_event_id,
        smoke_audit_event_id=review_point_response.smoke_audit_event_id,
        handover_audit_event_id=review_point_response.handover_audit_event_id,
        release_review_audit_event_id=review_point_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=review_point_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=review_point_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=review_point_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=review_point_response.start_scope_audit_event_id,
        runbook_audit_event_id=review_point_response.runbook_audit_event_id,
        review_point_audit_event_id=review_point_response.audit_event_id or "",
        audit_refs=review_point_response.audit_refs,
        review_point_evidence_hash=review_point_response.evidence_hash,
        runbook_evidence_hash=review_point_response.runbook_evidence_hash,
        start_scope_evidence_hash=review_point_response.start_scope_evidence_hash,
        readiness_report_evidence_hash=review_point_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=review_point_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=review_point_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=review_point_response.release_review_evidence_hash,
        handover_evidence_hash=review_point_response.handover_evidence_hash,
        snapshot_hash=review_point_response.snapshot_hash,
        release_candidate_smoke_hash=review_point_response.release_candidate_smoke_hash,
        readiness_status=review_point_response.readiness_status,
        readiness_decision=review_point_response.readiness_decision,
        operational_status=review_point_response.operational_status,
        read_only_status=review_point_response.read_only_status,
        pilot_gate_status=review_point_response.pilot_gate_status,
        pilot_gate_decision=review_point_response.pilot_gate_decision,
        start_scope_status=review_point_response.start_scope_status,
        start_scope_decision=review_point_response.start_scope_decision,
        runbook_status=review_point_response.runbook_status,
        runbook_decision=review_point_response.runbook_decision,
        review_point_status=review_point_response.review_point_status,
        review_point_decision=review_point_response.review_point_decision,
        template_status=template_status,
        template_decision=template_decision,
        template_sections=MVP_PILOT_START_DECISION_TEMPLATE_SECTIONS,
        confirmation_template_id="mvp_pilot_start_decision_v1",
        confirmation_fields=confirmation_fields,
        required_confirmation_roles=review_point_response.required_roles,
        required_confirmation_statements=_mvp_pilot_start_decision_confirmation_statements(),
        start_scope_contracts=review_point_response.start_scope_contracts,
        excluded_scope_contracts=review_point_response.excluded_scope_contracts,
        allowed_pilot_surfaces=review_point_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=review_point_response.deferred_pilot_surfaces,
        template_summary=_mvp_pilot_start_decision_template_summary(
            review_point_response=review_point_response,
            template_decision=template_decision,
        ),
        reviewer_actions=_mvp_pilot_start_decision_reviewer_actions(template_status=template_status),
        confirmation_blockers=_mvp_pilot_start_decision_blockers(review_point_response),
        evidence_chain_summary=_mvp_pilot_start_decision_evidence_chain_summary(review_point_response),
        open_foundation_gap_count=review_point_response.open_foundation_gap_count,
        ready_foundation_gap_count=review_point_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=review_point_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=review_point_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=review_point_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=review_point_response.deferred_foundation_gap_ids,
        next_foundation_action=review_point_response.next_foundation_action,
        required_roles=review_point_response.required_roles,
        role_gates=review_point_response.role_gates,
        module_gate_status=review_point_response.module_gate_status,
        content_gate_status=review_point_response.content_gate_status,
        backup_failover_gate_status=review_point_response.backup_failover_gate_status,
        human_review_required=review_point_response.human_review_required,
        human_confirmation_required=True,
        human_confirmation_captured=False,
        pilot_start_authorized=False,
        approval_record_created=False,
        content_included=review_point_response.content_included,
        persistent_task_created=review_point_response.persistent_task_created,
        automation_created=review_point_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_start_decision_template.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "template_status": template_status,
            "template_decision": template_decision,
            "review_point_status": review_point_response.review_point_status,
            "review_point_decision": review_point_response.review_point_decision,
            "runbook_status": review_point_response.runbook_status,
            "runbook_decision": review_point_response.runbook_decision,
            "start_scope_status": review_point_response.start_scope_status,
            "start_scope_decision": review_point_response.start_scope_decision,
            "readiness_status": review_point_response.readiness_status,
            "readiness_decision": review_point_response.readiness_decision,
            "operational_status": review_point_response.operational_status,
            "read_only_status": review_point_response.read_only_status,
            "review_point_evidence_hash": review_point_response.evidence_hash,
            "runbook_evidence_hash": review_point_response.runbook_evidence_hash,
            "start_scope_evidence_hash": review_point_response.start_scope_evidence_hash,
            "readiness_report_evidence_hash": review_point_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": review_point_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": review_point_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": review_point_response.release_review_evidence_hash,
            "handover_evidence_hash": review_point_response.handover_evidence_hash,
            "snapshot_hash": review_point_response.snapshot_hash,
            "release_candidate_smoke_hash": review_point_response.release_candidate_smoke_hash,
            "template_sections": MVP_PILOT_START_DECISION_TEMPLATE_SECTIONS,
            "confirmation_template_id": "mvp_pilot_start_decision_v1",
            "confirmation_fields": confirmation_fields,
            "start_scope_contracts": review_point_response.start_scope_contracts,
            "excluded_scope_contracts": review_point_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": review_point_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": review_point_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": review_point_response.open_foundation_gap_ids,
            "open_foundation_gap_count": review_point_response.open_foundation_gap_count,
            "next_foundation_action": review_point_response.next_foundation_action,
            "human_review_required": True,
            "human_confirmation_required": True,
            "human_confirmation_captured": False,
            "pilot_start_authorized": False,
            "approval_record_created": False,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_start_decision_template_hash(audited)})


def build_mvp_pilot_start_decision_template_hash(
    report: ProductCockpitMvpPilotStartDecisionTemplateResponse,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_decision_record_schema_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    template_response: ProductCockpitMvpPilotStartDecisionTemplateResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotDecisionRecordSchemaResponse:
    record_schema_status = (
        "metadata_only_pilot_decision_record_schema_ready"
        if template_response.template_status == "metadata_only_pilot_start_decision_template_ready"
        and template_response.human_confirmation_required
        and not template_response.human_confirmation_captured
        and not template_response.pilot_start_authorized
        and not template_response.approval_record_created
        and template_response.read_only_status == "read_only_no_state_change"
        and template_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not template_response.content_included
        and not template_response.persistent_task_created
        and not template_response.automation_created
        else "metadata_only_pilot_decision_record_schema_blocked"
    )
    record_schema_decision = (
        "audit_decision_record_schema_ready_without_confirmation_capture"
        if record_schema_status == "metadata_only_pilot_decision_record_schema_ready"
        else "audit_decision_record_schema_blocked"
    )
    required_fields = _mvp_pilot_decision_record_required_fields()
    immutable_evidence_fields = _mvp_pilot_decision_record_immutable_evidence_fields()
    audit_required_fields = _mvp_pilot_decision_record_audit_required_fields()
    draft = ProductCockpitMvpPilotDecisionRecordSchemaResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=template_response.cockpit_audit_event_id,
        snapshot_audit_event_id=template_response.snapshot_audit_event_id,
        smoke_audit_event_id=template_response.smoke_audit_event_id,
        handover_audit_event_id=template_response.handover_audit_event_id,
        release_review_audit_event_id=template_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=template_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=template_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=template_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=template_response.start_scope_audit_event_id,
        runbook_audit_event_id=template_response.runbook_audit_event_id,
        review_point_audit_event_id=template_response.review_point_audit_event_id,
        template_audit_event_id=template_response.audit_event_id or "",
        audit_refs=template_response.audit_refs,
        template_evidence_hash=template_response.evidence_hash,
        review_point_evidence_hash=template_response.review_point_evidence_hash,
        runbook_evidence_hash=template_response.runbook_evidence_hash,
        start_scope_evidence_hash=template_response.start_scope_evidence_hash,
        readiness_report_evidence_hash=template_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=template_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=template_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=template_response.release_review_evidence_hash,
        handover_evidence_hash=template_response.handover_evidence_hash,
        snapshot_hash=template_response.snapshot_hash,
        release_candidate_smoke_hash=template_response.release_candidate_smoke_hash,
        readiness_status=template_response.readiness_status,
        readiness_decision=template_response.readiness_decision,
        operational_status=template_response.operational_status,
        read_only_status=template_response.read_only_status,
        pilot_gate_status=template_response.pilot_gate_status,
        pilot_gate_decision=template_response.pilot_gate_decision,
        start_scope_status=template_response.start_scope_status,
        start_scope_decision=template_response.start_scope_decision,
        runbook_status=template_response.runbook_status,
        runbook_decision=template_response.runbook_decision,
        review_point_status=template_response.review_point_status,
        review_point_decision=template_response.review_point_decision,
        template_status=template_response.template_status,
        template_decision=template_response.template_decision,
        record_schema_status=record_schema_status,
        record_schema_decision=record_schema_decision,
        record_schema_sections=MVP_PILOT_DECISION_RECORD_SCHEMA_SECTIONS,
        decision_record_schema_id="mvp_pilot_start_decision_record_v1",
        decision_record_required_fields=required_fields,
        immutable_evidence_fields=immutable_evidence_fields,
        audit_required_fields=audit_required_fields,
        confirmation_template_id=template_response.confirmation_template_id,
        confirmation_fields=template_response.confirmation_fields,
        required_confirmation_roles=template_response.required_confirmation_roles,
        required_confirmation_statements=template_response.required_confirmation_statements,
        start_scope_contracts=template_response.start_scope_contracts,
        excluded_scope_contracts=template_response.excluded_scope_contracts,
        allowed_pilot_surfaces=template_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=template_response.deferred_pilot_surfaces,
        record_schema_summary=_mvp_pilot_decision_record_schema_summary(
            template_response=template_response,
            record_schema_decision=record_schema_decision,
        ),
        reviewer_actions=_mvp_pilot_decision_record_schema_reviewer_actions(
            record_schema_status=record_schema_status,
        ),
        record_blockers=_mvp_pilot_decision_record_schema_blockers(template_response),
        evidence_chain_summary=_mvp_pilot_decision_record_schema_evidence_chain_summary(template_response),
        open_foundation_gap_count=template_response.open_foundation_gap_count,
        ready_foundation_gap_count=template_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=template_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=template_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=template_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=template_response.deferred_foundation_gap_ids,
        next_foundation_action=template_response.next_foundation_action,
        required_roles=template_response.required_roles,
        role_gates=template_response.role_gates,
        module_gate_status=template_response.module_gate_status,
        content_gate_status=template_response.content_gate_status,
        backup_failover_gate_status=template_response.backup_failover_gate_status,
        human_review_required=template_response.human_review_required,
        human_confirmation_required=template_response.human_confirmation_required,
        human_confirmation_captured=False,
        decision_record_created=False,
        pilot_start_authorized=False,
        approval_record_created=False,
        content_included=template_response.content_included,
        persistent_task_created=template_response.persistent_task_created,
        automation_created=template_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_decision_record_schema.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "record_schema_status": record_schema_status,
            "record_schema_decision": record_schema_decision,
            "template_status": template_response.template_status,
            "template_decision": template_response.template_decision,
            "review_point_status": template_response.review_point_status,
            "review_point_decision": template_response.review_point_decision,
            "runbook_status": template_response.runbook_status,
            "runbook_decision": template_response.runbook_decision,
            "start_scope_status": template_response.start_scope_status,
            "start_scope_decision": template_response.start_scope_decision,
            "readiness_status": template_response.readiness_status,
            "readiness_decision": template_response.readiness_decision,
            "operational_status": template_response.operational_status,
            "read_only_status": template_response.read_only_status,
            "template_evidence_hash": template_response.evidence_hash,
            "review_point_evidence_hash": template_response.review_point_evidence_hash,
            "runbook_evidence_hash": template_response.runbook_evidence_hash,
            "start_scope_evidence_hash": template_response.start_scope_evidence_hash,
            "readiness_report_evidence_hash": template_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": template_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": template_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": template_response.release_review_evidence_hash,
            "handover_evidence_hash": template_response.handover_evidence_hash,
            "snapshot_hash": template_response.snapshot_hash,
            "release_candidate_smoke_hash": template_response.release_candidate_smoke_hash,
            "record_schema_sections": MVP_PILOT_DECISION_RECORD_SCHEMA_SECTIONS,
            "decision_record_schema_id": "mvp_pilot_start_decision_record_v1",
            "decision_record_required_fields": required_fields,
            "immutable_evidence_fields": immutable_evidence_fields,
            "audit_required_fields": audit_required_fields,
            "confirmation_template_id": template_response.confirmation_template_id,
            "start_scope_contracts": template_response.start_scope_contracts,
            "excluded_scope_contracts": template_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": template_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": template_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": template_response.open_foundation_gap_ids,
            "open_foundation_gap_count": template_response.open_foundation_gap_count,
            "next_foundation_action": template_response.next_foundation_action,
            "human_review_required": True,
            "human_confirmation_required": True,
            "human_confirmation_captured": False,
            "decision_record_created": False,
            "pilot_start_authorized": False,
            "approval_record_created": False,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_decision_record_schema_hash(audited)})


def build_mvp_pilot_decision_record_schema_hash(
    report: ProductCockpitMvpPilotDecisionRecordSchemaResponse,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_product_cockpit_mvp_pilot_decision_preflight_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    decision_record_schema_response: ProductCockpitMvpPilotDecisionRecordSchemaResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotDecisionPreflightResponse:
    preflight_status = (
        "metadata_only_pilot_decision_preflight_ready"
        if decision_record_schema_response.record_schema_status == "metadata_only_pilot_decision_record_schema_ready"
        and decision_record_schema_response.human_confirmation_required
        and not decision_record_schema_response.human_confirmation_captured
        and not decision_record_schema_response.decision_record_created
        and not decision_record_schema_response.pilot_start_authorized
        and not decision_record_schema_response.approval_record_created
        and decision_record_schema_response.read_only_status == "read_only_no_state_change"
        and decision_record_schema_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not decision_record_schema_response.content_included
        and not decision_record_schema_response.persistent_task_created
        and not decision_record_schema_response.automation_created
        else "metadata_only_pilot_decision_preflight_blocked"
    )
    preflight_decision = (
        "pilot_decision_preflight_ready_without_confirmation_capture"
        if preflight_status == "metadata_only_pilot_decision_preflight_ready"
        else "pilot_decision_preflight_blocked"
    )
    draft = ProductCockpitMvpPilotDecisionPreflightResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=decision_record_schema_response.cockpit_audit_event_id,
        snapshot_audit_event_id=decision_record_schema_response.snapshot_audit_event_id,
        smoke_audit_event_id=decision_record_schema_response.smoke_audit_event_id,
        handover_audit_event_id=decision_record_schema_response.handover_audit_event_id,
        release_review_audit_event_id=decision_record_schema_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=decision_record_schema_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=decision_record_schema_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=decision_record_schema_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=decision_record_schema_response.start_scope_audit_event_id,
        runbook_audit_event_id=decision_record_schema_response.runbook_audit_event_id,
        review_point_audit_event_id=decision_record_schema_response.review_point_audit_event_id,
        template_audit_event_id=decision_record_schema_response.template_audit_event_id,
        decision_record_schema_audit_event_id=decision_record_schema_response.audit_event_id or "",
        audit_refs=decision_record_schema_response.audit_refs,
        decision_record_schema_evidence_hash=decision_record_schema_response.evidence_hash,
        template_evidence_hash=decision_record_schema_response.template_evidence_hash,
        review_point_evidence_hash=decision_record_schema_response.review_point_evidence_hash,
        runbook_evidence_hash=decision_record_schema_response.runbook_evidence_hash,
        start_scope_evidence_hash=decision_record_schema_response.start_scope_evidence_hash,
        readiness_report_evidence_hash=decision_record_schema_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=decision_record_schema_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=decision_record_schema_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=decision_record_schema_response.release_review_evidence_hash,
        handover_evidence_hash=decision_record_schema_response.handover_evidence_hash,
        snapshot_hash=decision_record_schema_response.snapshot_hash,
        release_candidate_smoke_hash=decision_record_schema_response.release_candidate_smoke_hash,
        readiness_status=decision_record_schema_response.readiness_status,
        readiness_decision=decision_record_schema_response.readiness_decision,
        operational_status=decision_record_schema_response.operational_status,
        read_only_status=decision_record_schema_response.read_only_status,
        pilot_gate_status=decision_record_schema_response.pilot_gate_status,
        pilot_gate_decision=decision_record_schema_response.pilot_gate_decision,
        start_scope_status=decision_record_schema_response.start_scope_status,
        start_scope_decision=decision_record_schema_response.start_scope_decision,
        runbook_status=decision_record_schema_response.runbook_status,
        runbook_decision=decision_record_schema_response.runbook_decision,
        review_point_status=decision_record_schema_response.review_point_status,
        review_point_decision=decision_record_schema_response.review_point_decision,
        template_status=decision_record_schema_response.template_status,
        template_decision=decision_record_schema_response.template_decision,
        record_schema_status=decision_record_schema_response.record_schema_status,
        record_schema_decision=decision_record_schema_response.record_schema_decision,
        preflight_status=preflight_status,
        preflight_decision=preflight_decision,
        preflight_sections=MVP_PILOT_DECISION_PREFLIGHT_SECTIONS,
        decision_record_schema_id=decision_record_schema_response.decision_record_schema_id,
        decision_record_required_fields=decision_record_schema_response.decision_record_required_fields,
        immutable_evidence_fields=decision_record_schema_response.immutable_evidence_fields,
        audit_required_fields=decision_record_schema_response.audit_required_fields,
        confirmation_template_id=decision_record_schema_response.confirmation_template_id,
        confirmation_fields=decision_record_schema_response.confirmation_fields,
        required_confirmation_roles=decision_record_schema_response.required_confirmation_roles,
        required_confirmation_statements=decision_record_schema_response.required_confirmation_statements,
        start_scope_contracts=decision_record_schema_response.start_scope_contracts,
        excluded_scope_contracts=decision_record_schema_response.excluded_scope_contracts,
        allowed_pilot_surfaces=decision_record_schema_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=decision_record_schema_response.deferred_pilot_surfaces,
        preflight_summary=_mvp_pilot_decision_preflight_summary(
            decision_record_schema_response=decision_record_schema_response,
            preflight_decision=preflight_decision,
        ),
        preflight_checks=_mvp_pilot_decision_preflight_checks(preflight_status=preflight_status),
        preflight_blockers=_mvp_pilot_decision_preflight_blockers(decision_record_schema_response),
        evidence_chain_summary=_mvp_pilot_decision_preflight_evidence_chain_summary(
            decision_record_schema_response,
        ),
        open_foundation_gap_count=decision_record_schema_response.open_foundation_gap_count,
        ready_foundation_gap_count=decision_record_schema_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=decision_record_schema_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=decision_record_schema_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=decision_record_schema_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=decision_record_schema_response.deferred_foundation_gap_ids,
        next_foundation_action=decision_record_schema_response.next_foundation_action,
        required_roles=decision_record_schema_response.required_roles,
        role_gates=decision_record_schema_response.role_gates,
        module_gate_status=decision_record_schema_response.module_gate_status,
        content_gate_status=decision_record_schema_response.content_gate_status,
        backup_failover_gate_status=decision_record_schema_response.backup_failover_gate_status,
        human_review_required=decision_record_schema_response.human_review_required,
        human_confirmation_required=decision_record_schema_response.human_confirmation_required,
        human_confirmation_captured=False,
        decision_record_created=False,
        pilot_start_authorized=False,
        approval_record_created=False,
        content_included=decision_record_schema_response.content_included,
        persistent_task_created=decision_record_schema_response.persistent_task_created,
        automation_created=decision_record_schema_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_decision_preflight.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "preflight_status": preflight_status,
            "preflight_decision": preflight_decision,
            "record_schema_status": decision_record_schema_response.record_schema_status,
            "record_schema_decision": decision_record_schema_response.record_schema_decision,
            "template_status": decision_record_schema_response.template_status,
            "template_decision": decision_record_schema_response.template_decision,
            "review_point_status": decision_record_schema_response.review_point_status,
            "review_point_decision": decision_record_schema_response.review_point_decision,
            "runbook_status": decision_record_schema_response.runbook_status,
            "runbook_decision": decision_record_schema_response.runbook_decision,
            "start_scope_status": decision_record_schema_response.start_scope_status,
            "start_scope_decision": decision_record_schema_response.start_scope_decision,
            "readiness_status": decision_record_schema_response.readiness_status,
            "readiness_decision": decision_record_schema_response.readiness_decision,
            "operational_status": decision_record_schema_response.operational_status,
            "read_only_status": decision_record_schema_response.read_only_status,
            "decision_record_schema_evidence_hash": decision_record_schema_response.evidence_hash,
            "template_evidence_hash": decision_record_schema_response.template_evidence_hash,
            "review_point_evidence_hash": decision_record_schema_response.review_point_evidence_hash,
            "runbook_evidence_hash": decision_record_schema_response.runbook_evidence_hash,
            "start_scope_evidence_hash": decision_record_schema_response.start_scope_evidence_hash,
            "readiness_report_evidence_hash": decision_record_schema_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": decision_record_schema_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": decision_record_schema_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": decision_record_schema_response.release_review_evidence_hash,
            "handover_evidence_hash": decision_record_schema_response.handover_evidence_hash,
            "snapshot_hash": decision_record_schema_response.snapshot_hash,
            "release_candidate_smoke_hash": decision_record_schema_response.release_candidate_smoke_hash,
            "preflight_sections": MVP_PILOT_DECISION_PREFLIGHT_SECTIONS,
            "decision_record_schema_id": decision_record_schema_response.decision_record_schema_id,
            "decision_record_required_fields": decision_record_schema_response.decision_record_required_fields,
            "immutable_evidence_fields": decision_record_schema_response.immutable_evidence_fields,
            "audit_required_fields": decision_record_schema_response.audit_required_fields,
            "confirmation_template_id": decision_record_schema_response.confirmation_template_id,
            "start_scope_contracts": decision_record_schema_response.start_scope_contracts,
            "excluded_scope_contracts": decision_record_schema_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": decision_record_schema_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": decision_record_schema_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": decision_record_schema_response.open_foundation_gap_ids,
            "open_foundation_gap_count": decision_record_schema_response.open_foundation_gap_count,
            "next_foundation_action": decision_record_schema_response.next_foundation_action,
            "human_review_required": True,
            "human_confirmation_required": True,
            "human_confirmation_captured": False,
            "decision_record_created": False,
            "pilot_start_authorized": False,
            "approval_record_created": False,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_decision_preflight_hash(audited)})


def build_mvp_pilot_decision_preflight_hash(
    report: ProductCockpitMvpPilotDecisionPreflightResponse,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def _mvp_pilot_decision_preflight_summary(
    *,
    decision_record_schema_response: ProductCockpitMvpPilotDecisionRecordSchemaResponse,
    preflight_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(decision_record_schema_response.open_foundation_gap_ids) or "none"
    return (
        f"preflight decision: {preflight_decision}",
        f"record schema decision: {decision_record_schema_response.record_schema_decision}",
        f"template decision: {decision_record_schema_response.template_decision}",
        f"open foundation gaps: {open_gaps}",
        "preflight is read-only and creates no confirmation, decision record or pilot start",
    )


def _mvp_pilot_decision_preflight_checks(*, preflight_status: str) -> tuple[str, ...]:
    if preflight_status == "metadata_only_pilot_decision_preflight_ready":
        return (
            "verify decision record schema fields before approval workflow wiring",
            "compare decision_schema, template, review_point and pilot_gate evidence hashes",
            "confirm human confirmation is still not captured",
            "keep pilot start blocked until a separate authorized decision exists",
        )
    return ("repair blocked decision preflight conditions before approval workflow wiring",)


def _mvp_pilot_decision_preflight_blockers(
    decision_record_schema_response: ProductCockpitMvpPilotDecisionRecordSchemaResponse,
) -> tuple[str, ...]:
    return (
        "human confirmation has not been captured",
        "decision record has not been created",
        "pilot start authorization is not granted by this preflight",
        "approval record has not been created",
        f"open foundation gaps: {','.join(decision_record_schema_response.open_foundation_gap_ids)}",
    )


def _mvp_pilot_decision_preflight_evidence_chain_summary(
    decision_record_schema_response: ProductCockpitMvpPilotDecisionRecordSchemaResponse,
) -> tuple[str, ...]:
    return (
        f"decision schema hash: {decision_record_schema_response.evidence_hash}",
        f"template hash: {decision_record_schema_response.template_evidence_hash}",
        f"review point hash: {decision_record_schema_response.review_point_evidence_hash}",
        f"runbook hash: {decision_record_schema_response.runbook_evidence_hash}",
        f"pilot gate hash: {decision_record_schema_response.pilot_gate_evidence_hash}",
    )


def build_product_cockpit_mvp_pilot_approval_workflow_boundary_response(
    *,
    user_context: UserContext,
    snapshot_response: ProductCockpitMvpSnapshotResponse,
    preflight_response: ProductCockpitMvpPilotDecisionPreflightResponse,
    audit_logger: InMemoryAuditLogger,
) -> ProductCockpitMvpPilotApprovalWorkflowBoundaryResponse:
    boundary_status = (
        "metadata_only_pilot_approval_workflow_boundary_ready"
        if preflight_response.preflight_status == "metadata_only_pilot_decision_preflight_ready"
        and preflight_response.human_confirmation_required
        and not preflight_response.human_confirmation_captured
        and not preflight_response.decision_record_created
        and not preflight_response.approval_record_created
        and not preflight_response.pilot_start_authorized
        and preflight_response.read_only_status == "read_only_no_state_change"
        and preflight_response.backup_failover_gate_status == "metadata_only_no_state_change"
        and not preflight_response.content_included
        and not preflight_response.persistent_task_created
        and not preflight_response.automation_created
        else "metadata_only_pilot_approval_workflow_boundary_blocked"
    )
    boundary_decision = (
        "approval_workflow_boundary_ready_without_approval_persistence"
        if boundary_status == "metadata_only_pilot_approval_workflow_boundary_ready"
        else "approval_workflow_boundary_blocked"
    )
    workflow_inputs = _mvp_pilot_approval_workflow_inputs()
    workflow_prohibited_outputs = _mvp_pilot_approval_workflow_prohibited_outputs()
    workflow_required_controls = _mvp_pilot_approval_workflow_required_controls()
    draft = ProductCockpitMvpPilotApprovalWorkflowBoundaryResponse(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        cockpit_audit_event_id=preflight_response.cockpit_audit_event_id,
        snapshot_audit_event_id=preflight_response.snapshot_audit_event_id,
        smoke_audit_event_id=preflight_response.smoke_audit_event_id,
        handover_audit_event_id=preflight_response.handover_audit_event_id,
        release_review_audit_event_id=preflight_response.release_review_audit_event_id,
        pilot_gate_audit_event_id=preflight_response.pilot_gate_audit_event_id,
        pilot_status_audit_event_id=preflight_response.pilot_status_audit_event_id,
        readiness_report_audit_event_id=preflight_response.readiness_report_audit_event_id,
        start_scope_audit_event_id=preflight_response.start_scope_audit_event_id,
        runbook_audit_event_id=preflight_response.runbook_audit_event_id,
        review_point_audit_event_id=preflight_response.review_point_audit_event_id,
        template_audit_event_id=preflight_response.template_audit_event_id,
        decision_record_schema_audit_event_id=preflight_response.decision_record_schema_audit_event_id,
        preflight_audit_event_id=preflight_response.audit_event_id or "",
        audit_refs=preflight_response.audit_refs,
        preflight_evidence_hash=preflight_response.evidence_hash,
        decision_record_schema_evidence_hash=preflight_response.decision_record_schema_evidence_hash,
        template_evidence_hash=preflight_response.template_evidence_hash,
        review_point_evidence_hash=preflight_response.review_point_evidence_hash,
        runbook_evidence_hash=preflight_response.runbook_evidence_hash,
        start_scope_evidence_hash=preflight_response.start_scope_evidence_hash,
        readiness_report_evidence_hash=preflight_response.readiness_report_evidence_hash,
        pilot_status_evidence_hash=preflight_response.pilot_status_evidence_hash,
        pilot_gate_evidence_hash=preflight_response.pilot_gate_evidence_hash,
        release_review_evidence_hash=preflight_response.release_review_evidence_hash,
        handover_evidence_hash=preflight_response.handover_evidence_hash,
        snapshot_hash=preflight_response.snapshot_hash,
        release_candidate_smoke_hash=preflight_response.release_candidate_smoke_hash,
        readiness_status=preflight_response.readiness_status,
        readiness_decision=preflight_response.readiness_decision,
        operational_status=preflight_response.operational_status,
        read_only_status=preflight_response.read_only_status,
        pilot_gate_status=preflight_response.pilot_gate_status,
        pilot_gate_decision=preflight_response.pilot_gate_decision,
        start_scope_status=preflight_response.start_scope_status,
        start_scope_decision=preflight_response.start_scope_decision,
        runbook_status=preflight_response.runbook_status,
        runbook_decision=preflight_response.runbook_decision,
        review_point_status=preflight_response.review_point_status,
        review_point_decision=preflight_response.review_point_decision,
        template_status=preflight_response.template_status,
        template_decision=preflight_response.template_decision,
        record_schema_status=preflight_response.record_schema_status,
        record_schema_decision=preflight_response.record_schema_decision,
        preflight_status=preflight_response.preflight_status,
        preflight_decision=preflight_response.preflight_decision,
        boundary_status=boundary_status,
        boundary_decision=boundary_decision,
        boundary_sections=MVP_PILOT_APPROVAL_WORKFLOW_BOUNDARY_SECTIONS,
        workflow_boundary_id="mvp_pilot_approval_workflow_boundary_v1",
        workflow_inputs=workflow_inputs,
        workflow_prohibited_outputs=workflow_prohibited_outputs,
        workflow_required_controls=workflow_required_controls,
        decision_record_schema_id=preflight_response.decision_record_schema_id,
        decision_record_required_fields=preflight_response.decision_record_required_fields,
        immutable_evidence_fields=preflight_response.immutable_evidence_fields,
        audit_required_fields=preflight_response.audit_required_fields,
        confirmation_template_id=preflight_response.confirmation_template_id,
        confirmation_fields=preflight_response.confirmation_fields,
        required_confirmation_roles=preflight_response.required_confirmation_roles,
        required_confirmation_statements=preflight_response.required_confirmation_statements,
        start_scope_contracts=preflight_response.start_scope_contracts,
        excluded_scope_contracts=preflight_response.excluded_scope_contracts,
        allowed_pilot_surfaces=preflight_response.allowed_pilot_surfaces,
        deferred_pilot_surfaces=preflight_response.deferred_pilot_surfaces,
        boundary_summary=_mvp_pilot_approval_workflow_boundary_summary(
            preflight_response=preflight_response,
            boundary_decision=boundary_decision,
        ),
        workflow_steps=_mvp_pilot_approval_workflow_steps(boundary_status=boundary_status),
        workflow_blockers=_mvp_pilot_approval_workflow_blockers(preflight_response),
        evidence_chain_summary=_mvp_pilot_approval_workflow_evidence_chain_summary(preflight_response),
        open_foundation_gap_count=preflight_response.open_foundation_gap_count,
        ready_foundation_gap_count=preflight_response.ready_foundation_gap_count,
        deferred_foundation_gap_count=preflight_response.deferred_foundation_gap_count,
        open_foundation_gap_ids=preflight_response.open_foundation_gap_ids,
        ready_foundation_gap_ids=preflight_response.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=preflight_response.deferred_foundation_gap_ids,
        next_foundation_action=preflight_response.next_foundation_action,
        required_roles=preflight_response.required_roles,
        role_gates=preflight_response.role_gates,
        module_gate_status=preflight_response.module_gate_status,
        content_gate_status=preflight_response.content_gate_status,
        backup_failover_gate_status=preflight_response.backup_failover_gate_status,
        human_review_required=preflight_response.human_review_required,
        human_confirmation_required=preflight_response.human_confirmation_required,
        human_confirmation_captured=False,
        decision_record_created=False,
        approval_record_created=False,
        pilot_start_authorized=False,
        content_included=preflight_response.content_included,
        persistent_task_created=preflight_response.persistent_task_created,
        automation_created=preflight_response.automation_created,
        evidence_hash="sha256:" + "0" * 64,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="platform.mvp_pilot_approval_workflow_boundary.export",
        source_object_ids=[flow.source_object_id for flow in snapshot_response.source_object_flow_refs],
        metadata={
            "result_contract": draft.result_contract,
            "boundary_status": boundary_status,
            "boundary_decision": boundary_decision,
            "preflight_status": preflight_response.preflight_status,
            "preflight_decision": preflight_response.preflight_decision,
            "record_schema_status": preflight_response.record_schema_status,
            "record_schema_decision": preflight_response.record_schema_decision,
            "template_status": preflight_response.template_status,
            "template_decision": preflight_response.template_decision,
            "review_point_status": preflight_response.review_point_status,
            "review_point_decision": preflight_response.review_point_decision,
            "runbook_status": preflight_response.runbook_status,
            "runbook_decision": preflight_response.runbook_decision,
            "start_scope_status": preflight_response.start_scope_status,
            "start_scope_decision": preflight_response.start_scope_decision,
            "readiness_status": preflight_response.readiness_status,
            "readiness_decision": preflight_response.readiness_decision,
            "operational_status": preflight_response.operational_status,
            "read_only_status": preflight_response.read_only_status,
            "preflight_evidence_hash": preflight_response.evidence_hash,
            "decision_record_schema_evidence_hash": preflight_response.decision_record_schema_evidence_hash,
            "template_evidence_hash": preflight_response.template_evidence_hash,
            "review_point_evidence_hash": preflight_response.review_point_evidence_hash,
            "runbook_evidence_hash": preflight_response.runbook_evidence_hash,
            "start_scope_evidence_hash": preflight_response.start_scope_evidence_hash,
            "readiness_report_evidence_hash": preflight_response.readiness_report_evidence_hash,
            "pilot_status_evidence_hash": preflight_response.pilot_status_evidence_hash,
            "pilot_gate_evidence_hash": preflight_response.pilot_gate_evidence_hash,
            "release_review_evidence_hash": preflight_response.release_review_evidence_hash,
            "handover_evidence_hash": preflight_response.handover_evidence_hash,
            "snapshot_hash": preflight_response.snapshot_hash,
            "release_candidate_smoke_hash": preflight_response.release_candidate_smoke_hash,
            "boundary_sections": MVP_PILOT_APPROVAL_WORKFLOW_BOUNDARY_SECTIONS,
            "workflow_boundary_id": "mvp_pilot_approval_workflow_boundary_v1",
            "workflow_inputs": workflow_inputs,
            "workflow_prohibited_outputs": workflow_prohibited_outputs,
            "workflow_required_controls": workflow_required_controls,
            "decision_record_schema_id": preflight_response.decision_record_schema_id,
            "decision_record_required_fields": preflight_response.decision_record_required_fields,
            "immutable_evidence_fields": preflight_response.immutable_evidence_fields,
            "audit_required_fields": preflight_response.audit_required_fields,
            "confirmation_template_id": preflight_response.confirmation_template_id,
            "confirmation_fields": preflight_response.confirmation_fields,
            "start_scope_contracts": preflight_response.start_scope_contracts,
            "excluded_scope_contracts": preflight_response.excluded_scope_contracts,
            "allowed_pilot_surfaces": preflight_response.allowed_pilot_surfaces,
            "deferred_pilot_surfaces": preflight_response.deferred_pilot_surfaces,
            "open_foundation_gap_ids": preflight_response.open_foundation_gap_ids,
            "open_foundation_gap_count": preflight_response.open_foundation_gap_count,
            "next_foundation_action": preflight_response.next_foundation_action,
            "human_review_required": True,
            "human_confirmation_required": True,
            "human_confirmation_captured": False,
            "decision_record_created": False,
            "approval_record_created": False,
            "pilot_start_authorized": False,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
        },
    )
    audited = draft.model_copy(
        update={
            "audit_event_id": event.event_id,
            "audit_refs": (*draft.audit_refs, f"audit:{event.event_id}"),
        }
    )
    return audited.model_copy(update={"evidence_hash": build_mvp_pilot_approval_workflow_boundary_hash(audited)})


def build_mvp_pilot_approval_workflow_boundary_hash(
    report: ProductCockpitMvpPilotApprovalWorkflowBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def _mvp_pilot_approval_workflow_inputs() -> tuple[str, ...]:
    return (
        "decision_record_schema_id",
        "confirmation_template_id",
        "preflight_evidence_hash",
        "decision_record_schema_evidence_hash",
        "template_evidence_hash",
        "review_point_evidence_hash",
        "runbook_evidence_hash",
        "pilot_gate_evidence_hash",
    )


def _mvp_pilot_approval_workflow_prohibited_outputs() -> tuple[str, ...]:
    return (
        "approval_record_created",
        "pilot_start_authorized",
        "decision_record_created",
        "content_preview_rendered",
        "persistent_task_created",
        "automation_created",
    )


def _mvp_pilot_approval_workflow_required_controls() -> tuple[str, ...]:
    return (
        "explicit_human_confirmation",
        "immutable_evidence_hashes",
        "tenant_and_role_gates",
        "audit_record_before_execution",
        "separate_execution_boundary",
    )


def _mvp_pilot_approval_workflow_boundary_summary(
    *,
    preflight_response: ProductCockpitMvpPilotDecisionPreflightResponse,
    boundary_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(preflight_response.open_foundation_gap_ids) or "none"
    return (
        f"boundary decision: {boundary_decision}",
        f"preflight decision: {preflight_response.preflight_decision}",
        f"record schema decision: {preflight_response.record_schema_decision}",
        f"open foundation gaps: {open_gaps}",
        "approval workflow boundary is metadata-only and creates no approval, decision record or pilot start",
    )


def _mvp_pilot_approval_workflow_steps(*, boundary_status: str) -> tuple[str, ...]:
    if boundary_status == "metadata_only_pilot_approval_workflow_boundary_ready":
        return (
            "collect human confirmation using confirmation_template_id",
            "persist approval only in a separate approval workflow",
            "write decision record only after explicit human approval",
            "keep pilot execution outside this boundary until authorization exists",
        )
    return ("repair blocked approval workflow boundary conditions before approval persistence wiring",)


def _mvp_pilot_approval_workflow_blockers(
    preflight_response: ProductCockpitMvpPilotDecisionPreflightResponse,
) -> tuple[str, ...]:
    return (
        "approval record has not been created",
        "human confirmation has not been captured",
        "decision record has not been created",
        "pilot start authorization is not granted by this boundary",
        f"open foundation gaps: {','.join(preflight_response.open_foundation_gap_ids)}",
    )


def _mvp_pilot_approval_workflow_evidence_chain_summary(
    preflight_response: ProductCockpitMvpPilotDecisionPreflightResponse,
) -> tuple[str, ...]:
    return (
        f"preflight hash: {preflight_response.evidence_hash}",
        f"decision schema hash: {preflight_response.decision_record_schema_evidence_hash}",
        f"template hash: {preflight_response.template_evidence_hash}",
        f"review point hash: {preflight_response.review_point_evidence_hash}",
        f"pilot gate hash: {preflight_response.pilot_gate_evidence_hash}",
    )


def _mvp_pilot_decision_record_required_fields() -> tuple[str, ...]:
    return (
        "tenant_id",
        "decision_record_schema_id",
        "confirmation_template_id",
        "template_evidence_hash",
        "review_point_evidence_hash",
        "runbook_evidence_hash",
        "start_scope_evidence_hash",
        "pilot_gate_evidence_hash",
        "open_foundation_gap_ids",
        "deferred_pilot_surfaces",
        "human_confirmation_statement",
        "confirmed_by",
        "confirmed_at",
    )


def _mvp_pilot_decision_record_immutable_evidence_fields() -> tuple[str, ...]:
    return (
        "template_evidence_hash",
        "review_point_evidence_hash",
        "runbook_evidence_hash",
        "start_scope_evidence_hash",
        "pilot_gate_evidence_hash",
    )


def _mvp_pilot_decision_record_audit_required_fields() -> tuple[str, ...]:
    return (
        "tenant_id",
        "confirmed_by",
        "confirmed_at",
        "audit_refs",
        "decision_record_hash",
    )


def _mvp_pilot_decision_record_schema_summary(
    *,
    template_response: ProductCockpitMvpPilotStartDecisionTemplateResponse,
    record_schema_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(template_response.open_foundation_gap_ids) or "none"
    return (
        f"record schema decision: {record_schema_decision}",
        f"template decision: {template_response.template_decision}",
        f"required confirmation roles: {','.join(template_response.required_confirmation_roles)}",
        f"open foundation gaps: {open_gaps}",
        "record schema is metadata-only and creates no decision record",
    )


def _mvp_pilot_decision_record_schema_reviewer_actions(
    *,
    record_schema_status: str,
) -> tuple[str, ...]:
    if record_schema_status == "metadata_only_pilot_decision_record_schema_ready":
        return (
            "compare template, review_point, runbook and start_scope evidence hashes",
            "capture human confirmation only in a separate approval workflow",
            "store decision record only after explicit human approval",
            "keep pilot start blocked until a separate authorized decision exists",
        )
    return ("repair blocked decision record schema conditions before approval workflow wiring",)


def _mvp_pilot_decision_record_schema_blockers(
    template_response: ProductCockpitMvpPilotStartDecisionTemplateResponse,
) -> tuple[str, ...]:
    return (
        "decision record has not been created",
        "human confirmation has not been captured",
        "pilot start authorization is not granted by this schema",
        "approval record has not been created",
        f"open foundation gaps: {','.join(template_response.open_foundation_gap_ids)}",
    )


def _mvp_pilot_decision_record_schema_evidence_chain_summary(
    template_response: ProductCockpitMvpPilotStartDecisionTemplateResponse,
) -> tuple[str, ...]:
    return (
        f"template hash: {template_response.evidence_hash}",
        f"review point hash: {template_response.review_point_evidence_hash}",
        f"runbook hash: {template_response.runbook_evidence_hash}",
        f"start scope hash: {template_response.start_scope_evidence_hash}",
        f"pilot gate hash: {template_response.pilot_gate_evidence_hash}",
    )


def _mvp_pilot_start_decision_confirmation_fields() -> tuple[str, ...]:
    return (
        "tenant_id",
        "confirmation_template_id",
        "review_point_evidence_hash",
        "runbook_evidence_hash",
        "start_scope_evidence_hash",
        "pilot_gate_evidence_hash",
        "open_foundation_gap_ids",
        "deferred_pilot_surfaces",
        "human_confirmation_statement",
    )


def _mvp_pilot_start_decision_confirmation_statements() -> tuple[str, ...]:
    return (
        (
            "I confirm the pilot start scope is limited to metadata-only workspace shell, "
            "module discovery, cockpit status and release evidence"
        ),
        "I confirm open foundation gaps are tracked before any expansion",
        "I confirm content preview, tickets, automations and new module workflows remain excluded",
        "I confirm this template alone does not authorize pilot start",
    )


def _mvp_pilot_start_decision_template_summary(
    *,
    review_point_response: ProductCockpitMvpPilotReviewPointResponse,
    template_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(review_point_response.open_foundation_gap_ids) or "none"
    return (
        f"template decision: {template_decision}",
        f"review point decision: {review_point_response.review_point_decision}",
        f"required confirmation roles: {','.join(review_point_response.required_roles)}",
        f"open foundation gaps: {open_gaps}",
        "template is metadata-only and captures no human confirmation",
    )


def _mvp_pilot_start_decision_reviewer_actions(*, template_status: str) -> tuple[str, ...]:
    if template_status == "metadata_only_pilot_start_decision_template_ready":
        return (
            "compare review_point, runbook, start_scope and pilot_gate evidence hashes",
            "read open foundation gaps before signing pilot start decision",
            "confirm excluded scope remains deferred",
            "capture explicit human confirmation in a separate approval workflow",
        )
    return ("repair blocked start decision template conditions before human confirmation",)


def _mvp_pilot_start_decision_blockers(
    review_point_response: ProductCockpitMvpPilotReviewPointResponse,
) -> tuple[str, ...]:
    return (
        "human confirmation has not been captured",
        "pilot start authorization is not granted by this template",
        "approval record has not been created",
        f"open foundation gaps: {','.join(review_point_response.open_foundation_gap_ids)}",
        f"deferred pilot surfaces: {','.join(review_point_response.deferred_pilot_surfaces)}",
    )


def _mvp_pilot_start_decision_evidence_chain_summary(
    review_point_response: ProductCockpitMvpPilotReviewPointResponse,
) -> tuple[str, ...]:
    return (
        f"review point hash: {review_point_response.evidence_hash}",
        f"runbook hash: {review_point_response.runbook_evidence_hash}",
        f"start scope hash: {review_point_response.start_scope_evidence_hash}",
        f"readiness report hash: {review_point_response.readiness_report_evidence_hash}",
        f"pilot gate hash: {review_point_response.pilot_gate_evidence_hash}",
    )


def _mvp_pilot_review_point_summary(
    *,
    runbook_response: ProductCockpitMvpPilotRunbookResponse,
    review_point_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(runbook_response.open_foundation_gap_ids) or "none"
    return (
        f"review point decision: {review_point_decision}",
        f"runbook status: {runbook_response.runbook_status}",
        f"start scope decision: {runbook_response.start_scope_decision}",
        f"open foundation gaps: {open_gaps}",
        "review point is metadata-only and does not approve pilot start",
    )


def _mvp_pilot_review_point_reviewer_actions(*, review_point_status: str) -> tuple[str, ...]:
    if review_point_status == "metadata_only_pilot_review_point_ready":
        return (
            "verify runbook evidence_hash against start_scope and readiness evidence",
            "review open foundation gaps before pilot start confirmation",
            "confirm deferred scope remains outside pilot operation",
            "record explicit human approval outside this metadata-only endpoint before pilot start",
        )
    return ("repair blocked review point conditions before pilot start review",)


def _mvp_pilot_review_point_blockers(
    runbook_response: ProductCockpitMvpPilotRunbookResponse,
) -> tuple[str, ...]:
    return (
        "pilot start authorization is not granted by this endpoint",
        f"open foundation gaps: {','.join(runbook_response.open_foundation_gap_ids)}",
        f"deferred pilot surfaces: {','.join(runbook_response.deferred_pilot_surfaces)}",
        f"content gate: {runbook_response.content_gate_status}",
        f"module gate: {runbook_response.module_gate_status}",
    )


def _mvp_pilot_review_point_evidence_chain_summary(
    runbook_response: ProductCockpitMvpPilotRunbookResponse,
) -> tuple[str, ...]:
    return (
        f"runbook hash: {runbook_response.evidence_hash}",
        f"start scope hash: {runbook_response.start_scope_evidence_hash}",
        f"readiness report hash: {runbook_response.readiness_report_evidence_hash}",
        f"pilot gate hash: {runbook_response.pilot_gate_evidence_hash}",
        f"snapshot hash: {runbook_response.snapshot_hash}",
    )


def _mvp_pilot_runbook_steps(
    start_scope_response: ProductCockpitMvpPilotStartScopeResponse,
) -> tuple[str, ...]:
    if start_scope_response.start_scope_status != "metadata_only_pilot_start_scope_fixed":
        return ("repair blocked pilot start scope before admitting pilot users",)
    return (
        "verify tenant context and role gates before admitting pilot users",
        "retain start_scope, readiness_report, pilot_status and pilot_gate evidence hashes",
        f"operate only allowed pilot surfaces: {','.join(start_scope_response.allowed_pilot_surfaces)}",
        "track open foundation gaps before expanding pilot scope",
        "keep content preview, tickets, automations and new module workflows outside pilot operation",
    )


def _mvp_pilot_runbook_stop_conditions(
    start_scope_response: ProductCockpitMvpPilotStartScopeResponse,
) -> tuple[str, ...]:
    return (
        "tenant context or role gate is missing",
        "start scope, readiness, pilot status or pilot gate leaves ready state",
        "content preview, tickets, automations or new module workflows are requested",
        "open foundation gaps are not tracked",
        f"backup/failover gate is not {start_scope_response.backup_failover_gate_status}",
    )


def _mvp_pilot_runbook_evidence_chain_summary(
    start_scope_response: ProductCockpitMvpPilotStartScopeResponse,
) -> tuple[str, ...]:
    return (
        f"start scope hash: {start_scope_response.evidence_hash}",
        f"readiness report hash: {start_scope_response.readiness_report_evidence_hash}",
        f"pilot status hash: {start_scope_response.pilot_status_evidence_hash}",
        f"pilot gate hash: {start_scope_response.pilot_gate_evidence_hash}",
        f"snapshot hash: {start_scope_response.snapshot_hash}",
    )


def _mvp_pilot_start_scope_summary(
    *,
    readiness_report: ProductCockpitMvpPilotReadinessReportResponse,
    start_scope_decision: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(readiness_report.open_foundation_gap_ids) or "none"
    return (
        f"start scope decision: {start_scope_decision}",
        f"readiness decision: {readiness_report.readiness_decision}",
        f"allowed pilot surfaces: {','.join(readiness_report.allowed_pilot_surfaces)}",
        f"open foundation gaps: {open_gaps}",
        "start scope is metadata-only and excludes content preview, tickets, automations and new module workflows",
    )


def _mvp_pilot_start_operator_actions(*, start_scope_status: str) -> tuple[str, ...]:
    if start_scope_status == "metadata_only_pilot_start_scope_fixed":
        return (
            "retain start_scope evidence_hash with readiness_report evidence",
            "start pilot only on workspace shell, module discovery, cockpit status and release evidence",
            "track open foundation gaps before expanding pilot scope",
            "keep excluded scope contracts outside pilot operation until explicitly released",
        )
    return ("repair blocked start-scope conditions before admitting pilot users",)


def _mvp_pilot_start_expansion_blockers(
    readiness_report: ProductCockpitMvpPilotReadinessReportResponse,
) -> tuple[str, ...]:
    return (
        f"open foundation gaps: {','.join(readiness_report.open_foundation_gap_ids)}",
        f"deferred pilot surfaces: {','.join(readiness_report.deferred_pilot_surfaces)}",
        f"content gate: {readiness_report.content_gate_status}",
        f"module gate: {readiness_report.module_gate_status}",
    )


def _mvp_pilot_readiness_executive_summary(
    *,
    pilot_status_response: ProductCockpitMvpPilotStatusResponse,
    readiness_decision: str,
) -> tuple[str, ...]:
    return (
        f"readiness decision: {readiness_decision}",
        f"operational status: {pilot_status_response.operational_status}",
        f"pilot gate: {pilot_status_response.pilot_gate_status}",
        f"release review: {pilot_status_response.release_review_status}",
        "pilot remains limited to metadata-only surfaces and release evidence",
    )


def _mvp_pilot_readiness_foundation_gap_summary(
    pilot_status_response: ProductCockpitMvpPilotStatusResponse,
) -> tuple[str, ...]:
    open_gaps = ",".join(pilot_status_response.open_foundation_gap_ids) or "none"
    ready_gaps = ",".join(pilot_status_response.ready_foundation_gap_ids) or "none"
    deferred_gaps = ",".join(pilot_status_response.deferred_foundation_gap_ids) or "none"
    return (
        f"open foundation gaps ({pilot_status_response.open_foundation_gap_count}): {open_gaps}",
        f"ready foundation gaps ({pilot_status_response.ready_foundation_gap_count}): {ready_gaps}",
        f"deferred foundation gaps ({pilot_status_response.deferred_foundation_gap_count}): {deferred_gaps}",
        f"next foundation action: {pilot_status_response.next_foundation_action}",
    )


def _mvp_pilot_readiness_deferred_scope_summary(
    pilot_status_response: ProductCockpitMvpPilotStatusResponse,
) -> tuple[str, ...]:
    return (
        f"allowed pilot surfaces: {','.join(pilot_status_response.allowed_pilot_surfaces)}",
        f"deferred pilot surfaces: {','.join(pilot_status_response.deferred_pilot_surfaces)}",
        "content preview, tickets, automations and new module workflows remain out of scope",
        "report is metadata-only and creates no persistent work items",
    )


def _mvp_pilot_readiness_reviewer_actions(*, readiness_status: str) -> tuple[str, ...]:
    if readiness_status == "ready_for_metadata_only_pilot_review":
        return (
            "retain readiness_report evidence_hash with pilot_status and pilot_gate evidence",
            "review open foundation gaps before expanding pilot scope",
            "confirm deferred surfaces remain outside pilot operation",
            "use this report for operator review only; do not treat it as content release",
        )
    return ("repair blocked pilot readiness conditions before operator review",)


def _mvp_pilot_status_summary(
    *,
    pilot_gate_response: ProductCockpitMvpPilotGateResponse,
    operational_status: str,
) -> tuple[str, ...]:
    open_gaps = ",".join(pilot_gate_response.open_foundation_gap_ids)
    return (
        f"operational status: {operational_status}",
        f"pilot gate: {pilot_gate_response.pilot_gate_status}",
        f"release review: {pilot_gate_response.release_review_status}",
        f"open foundation gaps: {open_gaps if open_gaps else 'none'}",
        "status is read-only and creates no content preview, tickets, tasks or automations",
    )


def _mvp_pilot_status_attention_items(
    pilot_gate_response: ProductCockpitMvpPilotGateResponse,
) -> tuple[str, ...]:
    return (
        f"next foundation action: {pilot_gate_response.next_foundation_action}",
        f"module gate: {pilot_gate_response.module_gate_status}",
        f"content gate: {pilot_gate_response.content_gate_status}",
        f"backup/failover gate: {pilot_gate_response.backup_failover_gate_status}",
        "deferred scope must remain outside pilot operation until explicitly released",
    )


def _mvp_pilot_gate_passed_checks(
    release_review_response: ProductCockpitMvpReleaseReviewResponse,
) -> tuple[str, ...]:
    passed: list[str] = []
    if release_review_response.review_status == "ready_for_release_review":
        passed.append("release_review_ready")
    if release_review_response.security_guardrail_status == "passed":
        passed.append("security_guardrails_passed")
    if release_review_response.compliance_guardrail_status == "passed":
        passed.append("compliance_guardrails_passed")
    if release_review_response.release_candidate_smoke_passed:
        passed.append("release_candidate_smoke_passed")
    if release_review_response.metadata_only_productive_path:
        passed.append("metadata_only_path")
    if not release_review_response.content_included:
        passed.append("no_content_included")
    if not release_review_response.persistent_task_created:
        passed.append("no_persistent_tasks_created")
    if not release_review_response.automation_created:
        passed.append("no_automation_created")
    if release_review_response.audit_event_id and f"audit:{release_review_response.audit_event_id}" in (
        release_review_response.audit_refs
    ):
        passed.append("audit_chain_present")
    if release_review_response.open_foundation_gap_ids:
        passed.append("open_foundation_gaps_tracked")
    if release_review_response.content_gate_status == "deferred_metadata_only_ready":
        passed.append("deferred_scope_visible")
    return tuple(check for check in MVP_PILOT_GATE_CHECKS if check in passed)


def _mvp_pilot_gate_constraints(
    release_review_response: ProductCockpitMvpReleaseReviewResponse,
) -> tuple[str, ...]:
    open_gaps = ",".join(release_review_response.open_foundation_gap_ids)
    return (
        "pilot scope is limited to metadata-only workspace, module discovery, cockpit and release evidence",
        f"open foundation gaps remain tracked: {open_gaps if open_gaps else 'none'}",
        "content release, preview rendering, Office/Mail clients, tickets and automations remain deferred",
        "pilot gate creates no persistent tasks, automations or external side effects",
    )


def _mvp_pilot_gate_operator_actions(*, pilot_gate_status: str) -> tuple[str, ...]:
    if pilot_gate_status == "pilot_gate_open_with_deferred_scope":
        return (
            "retain pilot_gate evidence_hash with release_review_evidence_hash and handover_evidence_hash",
            "run pilot only through metadata-only workspace, cockpit and release evidence routes",
            "track open foundation gaps before expanding pilot scope",
            "keep content preview, Office/Mail clients, tickets and automations outside pilot scope",
        )
    return ("repair blocked pilot gate checks before admitting pilot users",)


def _mvp_snapshot_module_ref(module: ProductCockpitModuleView) -> ProductCockpitMvpSnapshotModuleRef:
    return ProductCockpitMvpSnapshotModuleRef(
        module_id=module.module_id,
        status=module.status,
        normal_use_enabled=module.normal_use_enabled,
        compliance_access_allowed=module.compliance_access_allowed,
        next_action=module.next_action,
        continuity_domain=module.continuity_domain,
    )


def _mvp_snapshot_source_object_flow_ref(
    flow: ProductCockpitSourceObjectFlowView,
) -> ProductCockpitMvpSnapshotSourceObjectFlowRef:
    return ProductCockpitMvpSnapshotSourceObjectFlowRef(
        flow_id=flow.flow_id,
        origin=flow.origin,
        module_id=flow.module_id,
        module_status=flow.module_status,
        source_object_id=flow.source_object_id,
        source_version_id=flow.source_version_id,
        source_object_type=flow.source_object_type,
        acl_version=flow.acl_version,
        readiness_status=flow.readiness.status,
        next_action=flow.readiness.next_action,
        content_release_allowed=flow.readiness.content_release_allowed,
        content_included=flow.content_included or flow.readiness.content_included,
        latest_preview_decision_status=flow.readiness.latest_preview_decision_status,
        cockpit_audit_event_id=flow.readiness.cockpit_audit_event_id,
        evidence_ref_count=len(flow.readiness.evidence_refs),
    )


def _mvp_snapshot_work_item_ref(item: ProductCockpitWorkItem) -> ProductCockpitMvpSnapshotWorkItemRef:
    return ProductCockpitMvpSnapshotWorkItemRef(
        work_item_id=item.work_item_id,
        scope=item.scope,
        priority=item.priority,
        action=item.action,
        module_id=item.module_id,
        flow_id=item.flow_id,
        source_object_id=item.source_object_id,
        source_version_id=item.source_version_id,
        primary_ui_action=item.primary_action_hint.ui_action,
        requires_confirmation=item.primary_action_hint.requires_confirmation,
        required_roles=item.primary_action_hint.required_roles,
        state_gate=item.primary_action_hint.state_gate,
        content_included=item.content_included or item.primary_action_hint.content_included,
        persistent_task_created=item.persistent_task_created or item.primary_action_hint.persistent_task_created,
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
        latest_preview_decision_required_evidence=latest_preview_decision.required_content_release_evidence,
        latest_preview_decision_provided_evidence=latest_preview_decision.provided_evidence,
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


def _foundation_gap_actions(
    *,
    mvp_readiness_summary: ProductCockpitMvpReadinessSummary,
    work_items: tuple[ProductCockpitWorkItem, ...],
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> tuple[ProductCockpitFoundationGapAction, ...]:
    gap_order = (
        "preview_decisions_pending",
        "preview_decisions_blocked",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    )
    gaps = set(mvp_readiness_summary.foundation_gaps)
    ordered_gaps = tuple(gap for gap in gap_order if gap in gaps) + tuple(
        gap for gap in mvp_readiness_summary.foundation_gaps if gap not in gap_order
    )
    actions: list[ProductCockpitFoundationGapAction] = []
    for gap_id in ordered_gaps:
        action = _foundation_gap_action(
            priority=len(actions) + 1,
            gap_id=gap_id,
            work_items=work_items,
            source_object_flows=source_object_flows,
        )
        actions.append(action)
    return tuple(actions)


def _foundation_gap_action(
    *,
    priority: int,
    gap_id: str,
    work_items: tuple[ProductCockpitWorkItem, ...],
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> ProductCockpitFoundationGapAction:
    if gap_id == "preview_decisions_pending":
        pending_items = tuple(
            item
            for item in work_items
            if item.scope == ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW
            and item.action == "request_preview_decision"
        )
        return _foundation_gap_action_from_work_items(
            priority=priority,
            gap_id=gap_id,
            status="ready" if pending_items else "blocked",
            next_action="resolve_preview_decision_work_items",
            work_items=pending_items,
        )
    if gap_id == "preview_decisions_blocked":
        blocked_flows = tuple(
            flow
            for flow in source_object_flows
            if flow.readiness.status
            in {
                ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_BLOCKED,
                ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED,
            }
        )
        blocked_items = tuple(
            item
            for item in work_items
            if item.scope == ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW
            and item.action == "review_latest_preview_decision"
        )
        return _foundation_gap_action_from_work_items(
            priority=priority,
            gap_id=gap_id,
            status="ready" if blocked_items else "blocked",
            next_action="complete_preview_release_evidence",
            work_items=blocked_items,
            source_object_ids=_source_object_ids_for_flows(blocked_flows),
            evidence_brief=_foundation_gap_evidence_brief_for_blocked_flows(blocked_flows),
        )
    if gap_id == "module_activation_work_items_open":
        module_items = tuple(item for item in work_items if item.scope == ProductCockpitWorkItemScope.MODULE)
        return _foundation_gap_action_from_work_items(
            priority=priority,
            gap_id=gap_id,
            status="ready" if module_items else "blocked",
            next_action="complete_module_activation_work_items",
            work_items=module_items,
        )
    if gap_id == "human_confirmation_required":
        confirmation_items = tuple(item for item in work_items if _work_item_requires_confirmation(item))
        standalone_items = tuple(item for item in confirmation_items if _confirmation_covering_gap_id(item) is None)
        if standalone_items:
            return _foundation_gap_action_from_work_items(
                priority=priority,
                gap_id=gap_id,
                status="ready",
                next_action="complete_explicit_human_confirmations",
                work_items=standalone_items,
                confirmation_brief=_foundation_gap_confirmation_brief_for_work_items(confirmation_items),
            )
        return _foundation_gap_action_from_work_items(
            priority=priority,
            gap_id=gap_id,
            status="deferred" if confirmation_items else "blocked",
            next_action="covered_by_specific_foundation_gap_actions",
            work_items=confirmation_items,
            requires_confirmation=False,
            deferred_reason="human_confirmations_are_covered_by_specific_foundation_gap_actions"
            if confirmation_items
            else None,
            confirmation_brief=_foundation_gap_confirmation_brief_for_work_items(confirmation_items),
        )
    if gap_id == "content_release_gate_blocks_content":
        gated_flows = tuple(flow for flow in source_object_flows if not flow.readiness.content_release_allowed)
        return ProductCockpitFoundationGapAction(
            priority=priority,
            gap_id=gap_id,
            status="deferred",
            next_action="keep_content_release_gate_deferred_for_mvp",
            source_object_ids=_source_object_ids_for_flows(gated_flows),
            metadata_only=True,
            content_included=False,
            persistent_task_created=False,
            automation_created=False,
            deferred_reason="content_release_requires_policy_viewer_runtime_after_mvp",
            content_release_brief=_foundation_gap_content_release_brief_for_flows(gated_flows),
        )
    return ProductCockpitFoundationGapAction(
        priority=priority,
        gap_id=gap_id,
        status="blocked",
        next_action=gap_id,
        deferred_reason="foundation_gap_has_no_safe_workspace_action_yet",
    )


def _foundation_gap_action_from_work_items(
    *,
    priority: int,
    gap_id: str,
    status: str,
    next_action: str,
    work_items: tuple[ProductCockpitWorkItem, ...],
    source_object_ids: tuple[str, ...] | None = None,
    evidence_brief: ProductCockpitFoundationGapEvidenceBrief | None = None,
    confirmation_brief: ProductCockpitFoundationGapConfirmationBrief | None = None,
    requires_confirmation: bool | None = None,
    deferred_reason: str | None = None,
) -> ProductCockpitFoundationGapAction:
    return ProductCockpitFoundationGapAction(
        priority=priority,
        gap_id=gap_id,
        status=status,
        next_action=next_action,
        covered_by_work_item_ids=tuple(item.work_item_id for item in work_items),
        source_object_ids=source_object_ids
        if source_object_ids is not None
        else _source_object_ids_for_work_items(work_items),
        module_ids=_module_ids_for_work_items(work_items),
        ui_actions=_ui_actions_for_work_items(work_items),
        required_roles=_required_roles_for_work_items(work_items),
        requires_confirmation=requires_confirmation
        if requires_confirmation is not None
        else any(_work_item_requires_confirmation(item) for item in work_items),
        metadata_only=True,
        content_included=any(item.content_included for item in work_items),
        persistent_task_created=any(item.persistent_task_created for item in work_items),
        automation_created=False,
        deferred_reason=deferred_reason,
        evidence_brief=evidence_brief,
        confirmation_brief=confirmation_brief,
    )


def _foundation_gap_evidence_brief_for_blocked_flows(
    flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> ProductCockpitFoundationGapEvidenceBrief | None:
    readinesses = tuple(flow.readiness for flow in flows if flow.readiness.preview_decision_available)
    if not readinesses:
        return None
    return ProductCockpitFoundationGapEvidenceBrief(
        required_evidence=_dedupe_strings(
            evidence for readiness in readinesses for evidence in readiness.latest_preview_decision_required_evidence
        ),
        provided_evidence=_dedupe_strings(
            evidence for readiness in readinesses for evidence in readiness.latest_preview_decision_provided_evidence
        ),
        missing_evidence=_dedupe_strings(
            evidence for readiness in readinesses for evidence in readiness.latest_preview_decision_missing_evidence
        ),
        evidence_required_now=_dedupe_strings(
            evidence for readiness in readinesses for evidence in readiness.latest_preview_decision_missing_evidence
        ),
        deferred_evidence=BLOCKED_PREVIEW_DEFERRED_EVIDENCE,
        verified_evidence=_dedupe_strings(
            evidence for readiness in readinesses for evidence in _verified_preview_evidence(readiness)
        ),
        decision_ledger_refs=_dedupe_strings(
            ref for readiness in readinesses if (ref := readiness.latest_preview_decision_ledger_ref) is not None
        ),
        audit_refs=_dedupe_strings(
            f"audit:{audit_id}"
            for readiness in readinesses
            if (audit_id := readiness.latest_preview_decision_audit_event_id) is not None
        ),
        policy_blocking_reasons=_dedupe_strings(
            reason for readiness in readinesses for reason in readiness.latest_preview_decision_blocking_reasons
        ),
        content_release_allowed=any(readiness.content_release_allowed for readiness in readinesses),
        content_included=any(readiness.content_included for readiness in readinesses),
    )


def _foundation_gap_confirmation_brief_for_work_items(
    work_items: tuple[ProductCockpitWorkItem, ...],
) -> ProductCockpitFoundationGapConfirmationBrief:
    standalone_items = tuple(item for item in work_items if _confirmation_covering_gap_id(item) is None)
    covered_items = tuple(item for item in work_items if _confirmation_covering_gap_id(item) is not None)
    return ProductCockpitFoundationGapConfirmationBrief(
        confirmation_work_item_ids=tuple(item.work_item_id for item in work_items),
        covered_by_specific_gap_work_item_ids=tuple(item.work_item_id for item in covered_items),
        standalone_work_item_ids=tuple(item.work_item_id for item in standalone_items),
        covering_gap_ids=_dedupe_strings(
            gap_id for item in covered_items if (gap_id := _confirmation_covering_gap_id(item)) is not None
        ),
        next_confirmation_action="complete_explicit_human_confirmations"
        if standalone_items
        else "use_specific_foundation_gap_actions_first",
        requires_separate_foundation_action=bool(standalone_items),
        content_included=any(item.content_included for item in work_items),
        persistent_task_created=any(item.persistent_task_created for item in work_items),
        automation_created=False,
    )


def _foundation_gap_content_release_brief_for_flows(
    flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> ProductCockpitFoundationGapContentReleaseBrief:
    readinesses = tuple(flow.readiness for flow in flows)
    return ProductCockpitFoundationGapContentReleaseBrief(
        blocked_flow_ids=tuple(flow.flow_id for flow in flows if not flow.readiness.content_release_allowed),
        blocked_source_object_ids=_source_object_ids_for_flows(
            tuple(flow for flow in flows if not flow.readiness.content_release_allowed)
        ),
        content_release_blocked_count=sum(1 for readiness in readinesses if not readiness.content_release_allowed),
        content_release_allowed_count=sum(1 for readiness in readinesses if readiness.content_release_allowed),
        content_included_count=sum(1 for readiness in readinesses if readiness.content_included),
        preview_decision_pending_count=sum(
            1
            for readiness in readinesses
            if readiness.status == ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_DECISION_PENDING
        ),
        preview_decision_blocked_count=sum(
            1
            for readiness in readinesses
            if readiness.status == ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_BLOCKED
        ),
        preview_evidence_complete_but_content_blocked_count=sum(
            1
            for readiness in readinesses
            if readiness.status
            == ProductCockpitFlowReadinessStatus.METADATA_READY_PREVIEW_EVIDENCE_COMPLETE_CONTENT_BLOCKED
        ),
        metadata_only_mvp_ready=bool(flows)
        and all(flow.access_checked and flow.readiness.source_detail_ready for flow in flows)
        and not any(flow.content_included or flow.readiness.content_included for flow in flows),
        deferred_dependencies=CONTENT_RELEASE_GATE_DEFERRED_DEPENDENCIES,
        blocking_reasons=_dedupe_strings(reason for readiness in readinesses for reason in readiness.blocking_reasons),
        content_release_allowed=any(readiness.content_release_allowed for readiness in readinesses),
        content_included=any(flow.content_included or flow.readiness.content_included for flow in flows),
        persistent_task_created=False,
        automation_created=False,
    )


def _confirmation_covering_gap_id(item: ProductCockpitWorkItem) -> str | None:
    if item.scope == ProductCockpitWorkItemScope.SOURCE_OBJECT_FLOW and item.action == "request_preview_decision":
        return "preview_decisions_pending"
    if item.scope == ProductCockpitWorkItemScope.MODULE and item.action in {
        "provision_module",
        "enable_module",
        "resolve_suspension",
    }:
        return "module_activation_work_items_open"
    return None


def _verified_preview_evidence(readiness: ProductCockpitSourceObjectFlowReadiness) -> tuple[str, ...]:
    verified: list[str] = []
    if readiness.renderer_sandbox_evidence_verified:
        verified.append("renderer_sandbox_worker_evidence")
    if readiness.backup_coverage_evidence_verified:
        verified.append("backup_coverage_evidence")
    if readiness.restore_evidence_verified:
        verified.append("restore_drill_evidence")
    if readiness.human_confirmation_verified:
        verified.append("human_content_release_confirmation")
    return tuple(verified)


def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _work_item_requires_confirmation(item: ProductCockpitWorkItem) -> bool:
    return any(hint.requires_confirmation for hint in (item.primary_action_hint, *item.secondary_action_hints))


def _source_object_ids_for_work_items(work_items: tuple[ProductCockpitWorkItem, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.source_object_id for item in work_items if item.source_object_id))


def _source_object_ids_for_flows(
    flows: tuple[ProductCockpitSourceObjectFlowView, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(flow.source_object_id for flow in flows))


def _module_ids_for_work_items(work_items: tuple[ProductCockpitWorkItem, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.module_id for item in work_items if item.module_id))


def _ui_actions_for_work_items(work_items: tuple[ProductCockpitWorkItem, ...]) -> tuple[str, ...]:
    actions = {
        hint.ui_action.value for item in work_items for hint in (item.primary_action_hint, *item.secondary_action_hints)
    }
    return tuple(sorted(actions))


def _required_roles_for_work_items(work_items: tuple[ProductCockpitWorkItem, ...]) -> tuple[str, ...]:
    roles = {
        role
        for item in work_items
        for hint in (item.primary_action_hint, *item.secondary_action_hints)
        for role in hint.required_roles
    }
    return tuple(sorted(roles))


def _mvp_readiness_decision(
    *,
    modules: tuple[ProductCockpitModuleView, ...],
    source_object_flows: tuple[ProductCockpitSourceObjectFlowView, ...],
    work_item_summary: ProductCockpitWorkItemOperationalSummary,
    mvp_readiness_summary: ProductCockpitMvpReadinessSummary,
    foundation_gap_actions: tuple[ProductCockpitFoundationGapAction, ...],
) -> ProductCockpitMvpReadinessDecision:
    required_roles = _dedupe_strings(role for action in foundation_gap_actions for role in action.required_roles)
    enabled_module_ids = tuple(module.module_id for module in modules if module.normal_use_enabled)
    module_action_required_ids = tuple(module.module_id for module in modules if not module.normal_use_enabled)
    audit_visible_flow_count = sum(1 for flow in source_object_flows if flow.readiness.audit_visible)
    backup_restore_verified_flow_count = sum(
        1
        for flow in source_object_flows
        if flow.readiness.backup_coverage_evidence_verified and flow.readiness.restore_evidence_verified
    )
    content_included = work_item_summary.content_included or any(
        action.content_included for action in foundation_gap_actions
    )
    persistent_task_created = work_item_summary.persistent_task_created_count > 0 or any(
        action.persistent_task_created for action in foundation_gap_actions
    )
    automation_created = any(action.automation_created for action in foundation_gap_actions)
    no_side_effects = (
        not content_included
        and not persistent_task_created
        and not automation_created
        and work_item_summary.destructive_action_count == 0
        and work_item_summary.external_side_effect_action_count == 0
    )
    audit_gate_status = (
        "audit_visible"
        if source_object_flows and audit_visible_flow_count == len(source_object_flows)
        else "audit_not_ready"
    )
    content_action = next(
        (action for action in foundation_gap_actions if action.gap_id == "content_release_gate_blocks_content"),
        None,
    )
    content_gate_status = (
        "content_gate_clear"
        if content_action is None
        else "deferred_metadata_only_ready"
        if content_action.content_release_brief is not None
        and content_action.content_release_brief.metadata_only_mvp_ready
        else "content_gate_blocking_mvp"
    )
    metadata_only_productive_path = (
        mvp_readiness_summary.mvp_entry_ready
        and audit_gate_status == "audit_visible"
        and no_side_effects
        and content_gate_status != "content_gate_blocking_mvp"
    )
    decision = (
        "metadata_only_mvp_ready_with_deferred_content_release"
        if metadata_only_productive_path and content_action is not None
        else "metadata_only_mvp_ready"
        if metadata_only_productive_path
        else "foundation_work_required"
    )
    return ProductCockpitMvpReadinessDecision(
        decision=decision,
        metadata_only_productive_path=metadata_only_productive_path,
        role_gate_status="role_gated_actions_visible" if required_roles else "context_only",
        required_roles=required_roles,
        audit_gate_status=audit_gate_status,
        audit_visible_flow_count=audit_visible_flow_count,
        audit_required_flow_count=len(source_object_flows),
        backup_failover_gate_status="metadata_only_no_state_change"
        if no_side_effects
        else "backup_restore_evidence_required",
        backup_restore_verified_flow_count=backup_restore_verified_flow_count,
        backup_restore_deferred_flow_count=len(source_object_flows) - backup_restore_verified_flow_count,
        module_gate_status="module_registry_empty"
        if not modules
        else "module_activation_required"
        if module_action_required_ids
        else "modules_enabled",
        module_count=len(modules),
        enabled_module_ids=enabled_module_ids,
        module_action_required_ids=module_action_required_ids,
        foundation_gap_status="clear"
        if not foundation_gap_actions
        else "deferred_only"
        if all(action.status == "deferred" for action in foundation_gap_actions)
        else "work_items_open",
        active_foundation_gap_ids=tuple(action.gap_id for action in foundation_gap_actions),
        ready_foundation_gap_ids=tuple(action.gap_id for action in foundation_gap_actions if action.status == "ready"),
        deferred_foundation_gap_ids=tuple(
            action.gap_id for action in foundation_gap_actions if action.status == "deferred"
        ),
        content_gate_status=content_gate_status,
        next_foundation_action=mvp_readiness_summary.next_foundation_action,
        content_included=content_included,
        persistent_task_created=persistent_task_created,
        automation_created=automation_created,
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
    if "human_confirmation_required" in foundation_gaps:
        return "complete_explicit_human_confirmations"
    if "content_release_gate_blocks_content" in foundation_gaps:
        return "keep_content_release_gate_deferred_for_mvp"
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
