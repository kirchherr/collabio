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
        decision_rule="foundation_first_only_pull_forward_items_that_unlock_current_crm_erp_slice",
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
            work_item_id="crm_accounts_contacts_activities_operational_hardening",
            title="CRM Basis stabilisieren",
            summary="Accounts, Contacts, Activities und Notes bleiben der aktuelle Produktivitaets-Pfad.",
            priority=RoadmapPlanPriority.NOW,
            capability_ids=("crm_erp_first_slices",),
            readiness_gate="tenant_module_gate_and_acl_contracts_ready",
            decision="must_now_because_it_turns_foundation_into_a_usable_business_slice",
            evidence_refs=("tests/test_crm_accounts.py", "tests/test_crm_contacts.py", "tests/test_crm_activities.py"),
            can_start_now=True,
        ),
        RoadmapPlanItem(
            work_item_id="erp_products_to_orders_invoices_slice",
            title="ERP Slice von Produkten zu Belegen ziehen",
            summary="Orders und Invoices folgen als naechster schmaler Slice ohne Legacy-Write-Freigabe.",
            priority=RoadmapPlanPriority.NOW,
            capability_ids=("crm_erp_first_slices", "legacy_migration_registry"),
            readiness_gate="metadata_only_erp_product_slice_ready_and_legacy_writes_blocked",
            decision="must_now_because_it_completes_the_first_crm_erp_workflow_without_destructive_imports",
            evidence_refs=(
                "tests/test_erp_products.py",
                "tests/test_erp_sales.py",
                "tests/test_legacy_sql_migration_run_registry.py",
            ),
            can_start_now=True,
        ),
        RoadmapPlanItem(
            work_item_id="crm_erp_search_acl_first_then_rag",
            title="CRM/ERP Suche von Keyword zu RAG fuehren",
            summary=(
                "ACL-first Keyword-Suche, Source-Resolver, Citation-, Prompt-Audit-, Redaction- und "
                "Authorized-Context-Contract stehen; RAG-Antwortgenerierung wartet auf die Inference-Grenze."
            ),
            priority=RoadmapPlanPriority.NEXT,
            capability_ids=(
                "crm_erp_first_slices",
                "crm_erp_acl_first_search",
                "rag_vector_security",
                "source_objects",
            ),
            readiness_gate="search_readiness_and_authoritative_acl_validation_before_vector_results",
            decision="next_because_context_contract_is_safe_but_answer_generation_needs_inference_boundary",
            evidence_refs=(
                "tests/test_crm_erp_search.py",
                "app/suite/platform/crm_erp_search_readiness.py",
                "tests/test_rag_security.py",
                "docs/RAG_SECURITY_MODEL.md",
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
            readiness_gate="content_release_policy_viewer_runtime_and_retention_controls_required",
            decision="later_because_current_foundation_needs_crm_erp_and_content_policy_first",
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
            readiness_gate="mail_preview_release_policy_and_attachment_scan_evidence_required",
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
