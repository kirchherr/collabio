from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.roadmap_dashboard import RoadmapDashboardResponse, build_roadmap_dashboard_response

ROADMAP_PLAN_SNAPSHOT_SCHEMA_VERSION = "platform_roadmap_plan_snapshot.v1"


class RoadmapPlanPriority(StrEnum):
    NOW = "now"
    NEXT = "next"
    LATER = "later"


class RoadmapPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_item_id: str
    title: str
    summary: str
    priority: RoadmapPlanPriority
    capability_ids: tuple[str, ...]
    readiness_gate: str
    decision: str
    evidence_refs: tuple[str, ...]
    can_start_now: bool
    deferred: bool = False

    @field_validator("work_item_id", "title", "summary", "readiness_gate", "decision")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roadmap plan item text fields must not be empty")
        return value

    @field_validator("capability_ids", "evidence_refs")
    @classmethod
    def require_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("roadmap plan item lists must not be empty")
        for item in value:
            if not item.strip():
                raise ValueError("roadmap plan item list entries must not be empty")
        return value

    @model_validator(mode="after")
    def require_later_items_to_be_deferred(self) -> RoadmapPlanItem:
        if self.priority == RoadmapPlanPriority.LATER and not self.deferred:
            raise ValueError("later roadmap plan items must be marked deferred")
        if self.deferred and self.can_start_now:
            raise ValueError("deferred roadmap plan items cannot start now")
        return self


class RoadmapPlanSnapshotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now_count: int
    next_count: int
    later_count: int
    total_count: int
    foundation_ready_count: int


class RoadmapPlanSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ROADMAP_PLAN_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    dashboard_schema_version: str
    current_focus: str
    decision_rule: str
    summary: RoadmapPlanSnapshotSummary
    items: tuple[RoadmapPlanItem, ...]
    content_included: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator("tenant_id", "dashboard_schema_version", "current_focus", "decision_rule")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roadmap plan snapshot text fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_snapshot(self) -> RoadmapPlanSnapshotResponse:
        if self.schema_version != ROADMAP_PLAN_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("roadmap plan snapshot schema version is invalid")
        if (
            self.content_included
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("roadmap plan snapshot must remain metadata-only and non-executing")
        if self.summary.total_count != len(self.items):
            raise ValueError("roadmap plan snapshot summary count must match item count")
        return self


def build_roadmap_plan_snapshot_response(*, user_context: UserContext) -> RoadmapPlanSnapshotResponse:
    dashboard = build_roadmap_dashboard_response(user_context=user_context)
    items = _roadmap_plan_items(dashboard=dashboard)
    _validate_capability_refs(dashboard=dashboard, items=items)
    return RoadmapPlanSnapshotResponse(
        tenant_id=user_context.tenant_id,
        dashboard_schema_version=dashboard.schema_version,
        current_focus=dashboard.current_focus,
        decision_rule="foundation_first_only_pull_forward_items_that_close_backend_readiness_or_unlock_productivity",
        summary=_roadmap_plan_summary(items=items, dashboard=dashboard),
        items=items,
    )


def _roadmap_plan_summary(
    *,
    items: tuple[RoadmapPlanItem, ...],
    dashboard: RoadmapDashboardResponse,
) -> RoadmapPlanSnapshotSummary:
    now_count = _priority_count(items=items, priority=RoadmapPlanPriority.NOW)
    next_count = _priority_count(items=items, priority=RoadmapPlanPriority.NEXT)
    later_count = _priority_count(items=items, priority=RoadmapPlanPriority.LATER)
    return RoadmapPlanSnapshotSummary(
        now_count=now_count,
        next_count=next_count,
        later_count=later_count,
        total_count=len(items),
        foundation_ready_count=dashboard.summary.foundation_ready_count,
    )


def _priority_count(*, items: tuple[RoadmapPlanItem, ...], priority: RoadmapPlanPriority) -> int:
    return sum(1 for item in items if item.priority == priority)


def _validate_capability_refs(
    *,
    dashboard: RoadmapDashboardResponse,
    items: tuple[RoadmapPlanItem, ...],
) -> None:
    capability_ids = {capability.capability_id for group in dashboard.groups for capability in group.capabilities}
    missing = sorted(
        capability_id for item in items for capability_id in item.capability_ids if capability_id not in capability_ids
    )
    if missing:
        raise ValueError(f"roadmap plan references unknown capabilities: {', '.join(missing)}")


def _roadmap_plan_items(*, dashboard: RoadmapDashboardResponse) -> tuple[RoadmapPlanItem, ...]:
    return (
        RoadmapPlanItem(
            work_item_id="self_hosted_provider_protocol_integration",
            title="Selbst gehosteten Provider an die Anwendung binden",
            summary=(
                "Der Ceph-/OpenBao-Entwicklungsstack laeuft. Als naechstes wird der implementierte, rein lesende "
                "Protokoll-Probe nach separater Bestaetigung ausgefuehrt; erst danach werden ein synthetischer "
                "Object-Lock-Nachweis und der isolierte Receipt-Restore vorbereitet."
            ),
            priority=RoadmapPlanPriority.NOW,
            capability_ids=("storage_kms_retention", "audit_chain", "backup_failover"),
            readiness_gate="explicit_read_only_probe_confirmation_then_separate_worm_mutation_authorization",
            decision="now_because_it_closes_the_application_to_provider_foundation_without_tenant_writes",
            evidence_refs=(
                "app/suite/operations/self_hosted_provider_protocol_probe.py",
                "infra/self-hosted/development/provider-protocol-probe.yaml",
                "docs/operations/SELF_HOSTED_PROVIDER_DEVELOPMENT.md",
                "docs/operations/AUDIT_WORM_SNAPSHOTS.md",
                "ARCHITECTURE_DECISIONS/ADR-0078-self-hosted-compliance-provider-stack.md",
            ),
            can_start_now=True,
        ),
        RoadmapPlanItem(
            work_item_id="real_user_productivity_pilot_admission",
            title="Realnutzer-Pilot separat aufnehmen",
            summary=(
                "Der Entwicklungs-Pilot ist append-only geschlossen und nach dem Closure-Write isoliert "
                "wiederhergestellt. Admission, hash-only Runtime und der separate Realnutzer-Closure-Pfad sind "
                "technisch vorbereitet. Nun muessen benannte Principals, Zweck und Rollen explizit freigegeben "
                "sowie Preflight, Monitoring, Rollback, Production Continuity und Start mit aktueller Evidenz neu "
                "erzeugt werden."
            ),
            priority=RoadmapPlanPriority.NEXT,
            capability_ids=(
                "productivity_pilot_preflight",
                "productivity_pilot_admission",
                "productivity_pilot_traffic_scope_enforcement",
                "productivity_pilot_start_authorization",
                "productivity_pilot_runtime_window",
                "productivity_pilot_closure_report",
                "productivity_pilot_real_user_admission_boundary",
                "productivity_pilot_real_user_runtime_boundary",
                "productivity_pilot_real_user_closure_boundary",
                "business_backend_release_gate",
                "crm_atomic_account_onboarding_runtime",
                "tasks_activities_runtime",
                "time_tracking_runtime",
                "module_registry",
                "tenant_authz",
                "audit_chain",
                "backup_failover",
                "production_continuity_deployment_gate",
            ),
            readiness_gate="named_principals_fresh_controls_production_continuity_and_four_eyes_required_before_runtime",
            decision="can_start_evidence_collection_but_runtime_stays_closed_until_human_evidence_is_ready",
            evidence_refs=(
                "docs/operations/PRODUCTIVITY_PILOT_PREFLIGHT.md",
                "docs/operations/PRODUCTIVITY_PILOT_ADMISSION.md",
                "docs/operations/PRODUCTIVITY_PILOT_TRAFFIC_SCOPE.md",
                "docs/operations/PRODUCTIVITY_PILOT_START_AUTHORIZATION.md",
                "docs/operations/PRODUCTIVITY_PILOT_RUNTIME_WINDOW.md",
                "docs/operations/PRODUCTIVITY_PILOT_CLOSURE_REPORT.md",
                "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_ADMISSION.md",
                "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW.md",
                "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT.md",
                "docs/operations/PRODUCTIVITY_PILOT_DEVELOPMENT_PROOF_20260731.md",
                "docs/operations/productivity_pilot_policy.json",
                "docs/operations/BUSINESS_BACKEND_RELEASE_GATE.md",
                "docs/operations/PRODUCTION_CONTINUITY_DEPLOYMENT_GATE.md",
                "docs/operations/PRODUCTION_CONTINUITY_EVIDENCE_READ_MODEL.md",
                "docs/operations/BACKUP_FAILOVER.md",
                "docs/ROADMAP.md",
            ),
            can_start_now=True,
        ),
        RoadmapPlanItem(
            work_item_id="module_family_backlog_kb_lms_tickets_time_tracking",
            title="Weitere Module als Familie takten",
            summary="KB, LMS, Tickets, Zeiterfassung und Aktivitaeten laufen ueber denselben Modulvertrag.",
            priority=RoadmapPlanPriority.NEXT,
            capability_ids=("module_registry", "knowledge_base", "future_modules", "backup_failover"),
            readiness_gate="module_contract_backup_failover_and_rights_management_must_follow_each_module",
            decision="next_because_it_keeps_the_suite_extensible_without_derailing_the_current_slice",
            evidence_refs=("docs/ROADMAP.md", "docs/operations/BACKUP_FAILOVER.md"),
            can_start_now=True,
        ),
        RoadmapPlanItem(
            work_item_id="full_office_suite_client",
            title="Office Suite Client",
            summary="Vollwertige Office-Oberflaechen bleiben eingeplant, aber sind kein aktueller Fundament-Blocker.",
            priority=RoadmapPlanPriority.LATER,
            capability_ids=("office_mail_clients",),
            readiness_gate="safe_text_release_ready_but_rich_format_viewer_collaboration_and_export_controls_required",
            decision="later_because_safe_text_foundation_is_ready_but_full_editor_runtime_is_a_separate_product_slice",
            evidence_refs=("docs/OFFICE_MAIL_CORE.md",),
            can_start_now=False,
            deferred=True,
        ),
        RoadmapPlanItem(
            work_item_id="mail_client_runtime",
            title="Mail Client Runtime",
            summary="Mail folgt nach Policy-Viewer, Retention, Legal Hold und sicheren Preview-Gates.",
            priority=RoadmapPlanPriority.LATER,
            capability_ids=("office_mail_clients", "preview_renderer"),
            readiness_gate="mail_body_policy_rfc_renderer_attachment_scan_and_send_action_gates_required",
            decision="later_because_mail_content_and_attachments_raise_content_release_risk",
            evidence_refs=("docs/OFFICE_MAIL_CORE.md", "tests/test_source_object_preview_renderer_release_gate.py"),
            can_start_now=False,
            deferred=True,
        ),
        RoadmapPlanItem(
            work_item_id="productive_legacy_sql_import_writes",
            title="Produktive Legacy Import-Writes",
            summary="Import-Writes bleiben blockiert bis Mapping, Restore-Evidence und Human Approval stimmen.",
            priority=RoadmapPlanPriority.LATER,
            capability_ids=("productive_import_writes", "legacy_dry_run_approval"),
            readiness_gate="explicit_human_confirmation_restore_evidence_and_write_gate_required",
            decision="later_because_it_is_destructive_and_not_needed_for_metadata_discovery",
            evidence_refs=("docs/LEGACY_SQL_DISCOVERY.md", "tests/test_legacy_sql_import_write_approval_gate.py"),
            can_start_now=False,
            deferred=True,
        ),
        RoadmapPlanItem(
            work_item_id="automation_execution_for_tasks_tickets_lms_time_tracking",
            title="Automation fuer spaetere Module",
            summary="Ausfuehrende Automationen warten, bis Aufgaben, Tickets, LMS und Zeiten fachlich geerdet sind.",
            priority=RoadmapPlanPriority.LATER,
            capability_ids=("future_modules",),
            readiness_gate="module_runtime_confirmation_and_audit_contract_required",
            decision="later_because_foundation_needs_contracts_before_execution",
            evidence_refs=("docs/ROADMAP.md",),
            can_start_now=False,
            deferred=True,
        ),
    )
