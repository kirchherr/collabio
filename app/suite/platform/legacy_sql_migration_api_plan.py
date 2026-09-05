from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.crm_erp_legacy_mapping import CRM_ERP_MODULE_ID
from suite.platform.legacy_sql_discovery import NAMESPACED_REF_PATTERN
from suite.platform.legacy_sql_import_write_approval_gate import (
    LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN,
    SHA256_REF_PATTERN,
    ZERO_HASH,
)

LEGACY_SQL_MIGRATION_API_PLAN_SCHEMA_VERSION = "legacy_sql_migration_api_plan.v1"
LEGACY_SQL_MIGRATION_API_PLAN_COMMAND_REF = "api:v1-admin-crm-erp-legacy-sql-migration-api-plan"
LEGACY_SQL_MIGRATION_API_PLAN_REQUIRED_GUARDRAILS = (
    "tenant_admin_scope",
    "module_compliance_gate",
    "tenant_scoped_rls",
    "append_only_run_registry",
    "idempotency_key_required",
    "approval_record_required_before_future_execution",
    "restore_evidence_required",
    "audit_event_required",
    "no_raw_legacy_data_in_api_responses",
)


class LegacySqlMigrationApiPlanStatus(StrEnum):
    READY_FOR_RUN_REGISTRY_DESIGN = "ready_for_run_registry_design"
    BLOCKED = "blocked"


class LegacySqlMigrationApiEndpointKind(StrEnum):
    CREATE_RUN = "create_run"
    LIST_RUNS = "list_runs"
    GET_RUN = "get_run"
    GET_REPORT = "get_report"
    REQUEST_APPROVAL = "request_approval"
    GRANT_APPROVAL = "grant_approval"


class LegacySqlMigrationApiPlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system_ref: str
    approval_record_store_ref: str
    migration_run_registry_ref: str
    migration_report_store_ref: str
    approval_reference: str
    change_control_ref: str
    restore_drill_ref: str
    reason: str
    migration_api_planning_requested: bool = True
    run_creation_requested: bool = True
    report_retrieval_requested: bool = True
    approval_grant_requested: bool = True
    import_write_execution_requested: bool = False
    raw_data_access_requested: bool = False
    import_write_payload_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "source_system_ref",
        "approval_record_store_ref",
        "migration_run_registry_ref",
        "migration_report_store_ref",
        "approval_reference",
        "change_control_ref",
        "restore_drill_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration API plan references must be namespaced")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration API plan reason must not be empty")
        return value


class LegacySqlMigrationApiEndpointPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_kind: LegacySqlMigrationApiEndpointKind
    method: str
    path: str
    purpose: str
    required_roles: tuple[str, ...]
    required_guardrails: tuple[str, ...]
    future_state_domain: str | None
    planned_now: bool = True
    implemented_now: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator("method", "path", "purpose")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration API endpoint text fields must not be empty")
        return value

    @field_validator("required_roles", "required_guardrails")
    @classmethod
    def validate_unique_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL migration API endpoint lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL migration API endpoint lists must not contain empty items")
        return value

    @model_validator(mode="after")
    def require_non_executing_endpoint(self) -> Self:
        if (
            self.implemented_now
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL migration API endpoint plan must remain non-executing")
        return self


class LegacySqlMigrationApiPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_MIGRATION_API_PLAN_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_MIGRATION_API_PLAN_COMMAND_REF
    approval_record_store_ref: str
    migration_run_registry_ref: str
    migration_report_store_ref: str
    approval_reference: str
    change_control_ref: str
    restore_drill_ref: str
    planned_endpoints: tuple[LegacySqlMigrationApiEndpointPlan, ...]
    required_guardrails: tuple[str, ...] = LEGACY_SQL_MIGRATION_API_PLAN_REQUIRED_GUARDRAILS
    migration_api_planning_requested: bool
    migration_api_plan_accepted: bool
    run_creation_planned: bool
    run_listing_planned: bool
    report_retrieval_planned: bool
    approval_request_planned: bool
    approval_grant_planned: bool
    future_import_write_execution_gate_required: bool = True
    run_creation_enabled: bool = False
    report_retrieval_enabled: bool = False
    approval_grant_enabled: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    plan_status: LegacySqlMigrationApiPlanStatus
    blocking_reasons: tuple[str, ...]
    planned_by: str
    planned_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "planned_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL migration API plan text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL migration API plan only applies to module crm_erp")
        return value

    @field_validator(
        "source_system_ref",
        "approval_record_store_ref",
        "migration_run_registry_ref",
        "migration_report_store_ref",
        "approval_reference",
        "change_control_ref",
        "restore_drill_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration API plan references must be namespaced")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL migration API plan hashes must be sha256 references")
        return value

    @field_validator("required_guardrails", "blocking_reasons")
    @classmethod
    def validate_unique_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL migration API plan lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL migration API plan lists must not contain empty items")
        return value

    @model_validator(mode="after")
    def require_safe_plan(self) -> Self:
        if (
            self.run_creation_enabled
            or self.report_retrieval_enabled
            or self.approval_grant_enabled
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL migration API plan must remain non-executing")
        if not self.future_import_write_execution_gate_required:
            raise ValueError("legacy SQL migration API plan must require a future execution gate")
        if self.plan_status == LegacySqlMigrationApiPlanStatus.READY_FOR_RUN_REGISTRY_DESIGN:
            endpoint_kinds = {endpoint.endpoint_kind for endpoint in self.planned_endpoints}
            required_kinds = set(LegacySqlMigrationApiEndpointKind)
            if (
                not self.migration_api_plan_accepted
                or self.blocking_reasons
                or not required_kinds.issubset(endpoint_kinds)
                or not self.run_creation_planned
                or not self.run_listing_planned
                or not self.report_retrieval_planned
                or not self.approval_request_planned
                or not self.approval_grant_planned
            ):
                raise ValueError("ready legacy SQL migration API plan requires complete endpoint coverage")
        if self.plan_status == LegacySqlMigrationApiPlanStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL migration API plan requires blocking reasons")
            if self.migration_api_plan_accepted:
                raise ValueError("blocked legacy SQL migration API plan cannot be accepted")
        return self


def build_legacy_sql_migration_api_plan_hash(plan: LegacySqlMigrationApiPlanResponse) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_migration_api_plan(
    *,
    command: LegacySqlMigrationApiPlanCommand,
    tenant_id: str,
    planned_by: str,
    planned_at_utc: datetime | None = None,
) -> LegacySqlMigrationApiPlanResponse:
    planned_at = planned_at_utc or datetime.now(UTC)
    blocking_reasons = _migration_api_plan_blocking_reasons(command)
    ready = not blocking_reasons
    endpoints = _planned_migration_api_endpoints()
    draft = LegacySqlMigrationApiPlanResponse(
        tenant_id=tenant_id,
        source_system_ref=command.source_system_ref,
        approval_record_store_ref=command.approval_record_store_ref,
        migration_run_registry_ref=command.migration_run_registry_ref,
        migration_report_store_ref=command.migration_report_store_ref,
        approval_reference=command.approval_reference,
        change_control_ref=command.change_control_ref,
        restore_drill_ref=command.restore_drill_ref,
        planned_endpoints=endpoints,
        migration_api_planning_requested=command.migration_api_planning_requested,
        migration_api_plan_accepted=ready,
        run_creation_planned=command.run_creation_requested,
        run_listing_planned=command.run_creation_requested,
        report_retrieval_planned=command.report_retrieval_requested,
        approval_request_planned=command.approval_grant_requested,
        approval_grant_planned=command.approval_grant_requested,
        plan_status=(
            LegacySqlMigrationApiPlanStatus.READY_FOR_RUN_REGISTRY_DESIGN
            if ready
            else LegacySqlMigrationApiPlanStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        planned_by=planned_by,
        planned_at_utc=planned_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_migration_api_plan_hash(draft)})


def _migration_api_plan_blocking_reasons(command: LegacySqlMigrationApiPlanCommand) -> tuple[str, ...]:
    reasons: list[str] = []
    if not command.migration_api_planning_requested:
        reasons.append("migration_api_planning_not_requested")
    if not command.run_creation_requested:
        reasons.append("run_creation_plan_not_requested")
    if not command.report_retrieval_requested:
        reasons.append("report_retrieval_plan_not_requested")
    if not command.approval_grant_requested:
        reasons.append("approval_grant_plan_not_requested")
    if command.import_write_execution_requested:
        reasons.append("import_write_execution_requires_future_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_forbidden")
    if command.import_write_payload_requested:
        reasons.append("import_write_payload_request_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(dict.fromkeys(reasons))


def _planned_migration_api_endpoints() -> tuple[LegacySqlMigrationApiEndpointPlan, ...]:
    tenant_admin_roles = ("tenant-admin",)
    guardrails = LEGACY_SQL_MIGRATION_API_PLAN_REQUIRED_GUARDRAILS
    return (
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.CREATE_RUN,
            method="POST",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs",
            purpose=(
                "Plan a tenant-scoped migration run record after dry-run, approval-record and restore evidence exist."
            ),
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_run_registry",
        ),
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.LIST_RUNS,
            method="GET",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs",
            purpose="List tenant-scoped migration run metadata without raw legacy rows or payloads.",
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_run_registry",
        ),
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.GET_RUN,
            method="GET",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs/{run_id}",
            purpose="Show one tenant-scoped migration run metadata record and evidence hashes.",
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_run_registry",
        ),
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.GET_REPORT,
            method="GET",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs/{run_id}/report",
            purpose="Return metadata-only migration report hashes, counts and restore evidence.",
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_report_store",
        ),
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.REQUEST_APPROVAL,
            method="POST",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs/{run_id}/approval-request",
            purpose="Prepare human approval evidence for a future execution gate without executing writes.",
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_approval_workflow",
        ),
        LegacySqlMigrationApiEndpointPlan(
            endpoint_kind=LegacySqlMigrationApiEndpointKind.GRANT_APPROVAL,
            method="POST",
            path="/v1/admin/crm-erp/legacy-sql/migration-runs/{run_id}/approval",
            purpose="Record explicit human approval metadata for a future execution gate.",
            required_roles=tenant_admin_roles,
            required_guardrails=guardrails,
            future_state_domain="legacy_sql_migration_approval_workflow",
        ),
    )
