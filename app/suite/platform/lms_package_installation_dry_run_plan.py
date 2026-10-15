from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID
from suite.platform.lms_package_installation_readiness import build_lms_package_installation_readiness_response
from suite.platform.lms_tenant_admin_package_approval_record import LmsTenantAdminPackageApprovalRecordStore
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_SCHEMA_VERSION = "lms_package_installation_dry_run_plan.v1"
LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_plan_no_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_ENDPOINT = "/v1/platform/modules/families/lms/package-installation-dry-run-plan"
LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_STATEMENT = (
    "I prepare the LMS package installation dry-run plan without executing installation or tenant activation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_READY_NEXT_ACTION = "review_lms_package_installation_dry_run_execution_boundary"
LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_RETRY_NEXT_ACTION = (
    "prepare_lms_package_installation_dry_run_plan_without_tenant_activation"
)

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class LmsPackageInstallationDryRunPlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_boundary_evidence_hash: str
    executor_skeleton_evidence_hash: str
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    dry_run_plan_ref: str
    change_request_ref: str
    idempotency_key_ref: str
    planned_at_utc: datetime
    audit_chain_ref: str
    dry_run_plan_statement: str
    dry_run_plan_requested: bool = True
    package_installation_dry_run_execution_requested: bool = False
    package_installation_execution_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    lms_business_api_activation_requested: bool = False
    persistent_task_creation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "execution_boundary_evidence_hash",
        "executor_skeleton_evidence_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
    )
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run plan hashes must be sha256 references")
        return value

    @field_validator("dry_run_plan_ref", "change_request_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS dry-run plan references must use a typed ref prefix")
        return value.strip()

    @field_validator("dry_run_plan_statement")
    @classmethod
    def require_exact_plan_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_STATEMENT:
            raise ValueError("LMS dry-run plan requires the exact preparation statement")
        return normalized

    @field_validator("planned_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run plan planned_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_check_count: int
    required_dry_run_plan_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    package_installation_ready: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool
    human_approval_ready: bool
    execution_boundary_evidence_hash: str
    executor_skeleton_evidence_hash: str
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    dry_run_plan_statement_hash: str
    dry_run_plan_ref: str
    change_request_ref: str
    audit_chain_ref: str
    planned_by: str
    planned_at_utc: datetime
    planner_role_allowed: bool
    dry_run_plan_requested: bool
    dry_run_plan_ready: bool
    dry_run_execution_boundary_required: bool = True
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    package_installation_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    lms_business_api_allowed: bool = False
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    tenant_module_state_created: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    dry_run_result_persistence_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    dry_run_checks: tuple[str, ...]
    required_dry_run_plan_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunPlanSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "dry_run_plan_ref",
        "change_request_ref",
        "audit_chain_ref",
        "planned_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run plan text fields must not be empty")
        return value

    @field_validator(
        "execution_boundary_evidence_hash",
        "executor_skeleton_evidence_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "dry_run_plan_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run plan hashes must be sha256 references")
        return value

    @field_validator("dry_run_checks", "required_dry_run_plan_evidence", "blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run plan lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run plan list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_dry_run_plan_contract(self) -> LmsPackageInstallationDryRunPlanResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_SCHEMA_VERSION:
            raise ValueError("LMS dry-run plan schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_ENDPOINT:
            raise ValueError("LMS dry-run plan endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_RESULT_CONTRACT:
            raise ValueError("LMS dry-run plan result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run plan only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run plan continuity domain is invalid")
        expected_ready = (
            self.package_installation_ready
            and self.planner_role_allowed
            and self.dry_run_plan_requested
            and not self.blocking_reasons
        )
        if self.dry_run_plan_ready != expected_ready:
            raise ValueError("LMS dry-run plan readiness must match prerequisites")
        if not self.dry_run_execution_boundary_required:
            raise ValueError("LMS dry-run plan must require a future dry-run execution boundary")
        if (
            self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.package_installation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.package_installation_executed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.content_included
            or self.dry_run_result_persistence_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run plan must remain metadata-only and non-executing")
        if self.summary.dry_run_check_count != len(self.dry_run_checks):
            raise ValueError("LMS dry-run plan check count must match dry-run checks")
        if self.summary.required_dry_run_plan_evidence_count != len(self.required_dry_run_plan_evidence):
            raise ValueError("LMS dry-run plan evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run plan blocking count must match blocking reasons")
        return self


def build_lms_package_installation_dry_run_plan_response(
    *,
    command: LmsPackageInstallationDryRunPlanCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    approval_record_store: LmsTenantAdminPackageApprovalRecordStore | None,
) -> LmsPackageInstallationDryRunPlanResponse:
    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
        approval_record_store=approval_record_store,
    )
    command_hash = build_lms_package_installation_dry_run_plan_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_plan_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "execution_boundary_evidence_hash": command.execution_boundary_evidence_hash,
                "executor_skeleton_evidence_hash": command.executor_skeleton_evidence_hash,
                "tenant_admin_approval_gate_hash": command.tenant_admin_approval_gate_hash,
                "tenant_admin_approval_record_hash": command.tenant_admin_approval_record_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    statement_hash = stable_hash(command.dry_run_plan_statement)
    planner_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    blocking_reasons = _dry_run_plan_blocking_reasons(
        command=command,
        package_installation_ready=readiness.package_installation_ready,
        expected_approval_gate_hash=readiness.tenant_admin_approval_gate_hash,
        expected_approval_record_hash=readiness.tenant_admin_approval_record_hash,
        planner_role_allowed=planner_role_allowed,
    )
    dry_run_plan_ready = not blocking_reasons
    dry_run_checks = (
        "verify_lms_catalog_status_not_installed",
        "verify_tenant_module_state_absent",
        "verify_lms_metadata_migrations_present",
        "verify_restore_drill_evidence_hash_bound",
        "verify_tenant_admin_approval_record_hash_bound",
        "verify_execution_boundary_hash_bound",
        "verify_executor_skeleton_hash_bound",
        "calculate_no_write_installation_candidate_summary",
        "confirm_no_lms_business_api_activation",
        "confirm_no_content_or_worker_registration",
        "confirm_no_dry_run_result_persistence",
    )
    required_dry_run_plan_evidence = (
        "tenant_admin_role",
        "package_installation_readiness_true",
        "package_installation_execution_boundary_hash",
        "package_installation_executor_skeleton_hash",
        "tenant_admin_package_install_approval_gate_hash",
        "tenant_admin_package_install_approval_record_hash",
        "restore_drill_evidence_hash",
        "exact_dry_run_plan_statement_hash",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_dry_run_execution_boundary_required",
        "no_lms_installation_execution_confirmation",
    )
    draft = LmsPackageInstallationDryRunPlanResponse(
        tenant_id=user_context.tenant_id,
        package_installation_ready=readiness.package_installation_ready,
        migration_plan_ready=readiness.migration_plan_ready,
        restore_evidence_ready=readiness.restore_evidence_ready,
        human_approval_ready=readiness.human_approval_ready,
        execution_boundary_evidence_hash=command.execution_boundary_evidence_hash,
        executor_skeleton_evidence_hash=command.executor_skeleton_evidence_hash,
        tenant_admin_approval_gate_hash=command.tenant_admin_approval_gate_hash,
        tenant_admin_approval_record_hash=command.tenant_admin_approval_record_hash,
        lms_restore_drill_evidence_hash=readiness.lms_restore_drill_evidence_hash or ZERO_SHA256,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        dry_run_plan_statement_hash=statement_hash,
        dry_run_plan_ref=command.dry_run_plan_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        planned_by=user_context.user_id,
        planned_at_utc=command.planned_at_utc,
        planner_role_allowed=planner_role_allowed,
        dry_run_plan_requested=command.dry_run_plan_requested,
        dry_run_plan_ready=dry_run_plan_ready,
        dry_run_checks=dry_run_checks,
        required_dry_run_plan_evidence=required_dry_run_plan_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationDryRunPlanSummary(
            dry_run_check_count=len(dry_run_checks),
            required_dry_run_plan_evidence_count=len(required_dry_run_plan_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_package_installation_execution_boundary.py",
            "app/suite/platform/lms_package_installation_executor_skeleton.py",
            "app/suite/platform/lms_package_installation_dry_run_plan.py",
            "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
            "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
            "tests/test_lms_package_installation_dry_run_plan.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_READY_NEXT_ACTION
            if dry_run_plan_ready
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_package_installation_dry_run_plan_hash(draft)})


def build_lms_package_installation_dry_run_plan_command_hash(
    command: LmsPackageInstallationDryRunPlanCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"dry_run_plan_statement"})
    payload["dry_run_plan_statement_hash"] = stable_hash(command.dry_run_plan_statement)
    return stable_hash(canonical_json(payload))


def build_lms_package_installation_dry_run_plan_hash(
    response: LmsPackageInstallationDryRunPlanResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _dry_run_plan_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunPlanCommand,
    package_installation_ready: bool,
    expected_approval_gate_hash: str | None,
    expected_approval_record_hash: str | None,
    planner_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not package_installation_ready:
        reasons.append("lms_package_installation_readiness_not_ready")
    if command.execution_boundary_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_execution_boundary_hash_missing")
    if command.executor_skeleton_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_executor_skeleton_hash_missing")
    if command.tenant_admin_approval_gate_hash != expected_approval_gate_hash:
        reasons.append("tenant_admin_approval_gate_hash_mismatch")
    if expected_approval_record_hash is None:
        reasons.append("tenant_admin_package_install_approval_record_missing")
    elif command.tenant_admin_approval_record_hash != expected_approval_record_hash:
        reasons.append("tenant_admin_package_install_approval_record_hash_mismatch")
    if not planner_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.dry_run_plan_requested:
        reasons.append("dry_run_plan_not_requested")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_request_forbidden")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_request_forbidden")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_request_forbidden")
    if command.migration_execution_requested:
        reasons.append("migration_execution_request_forbidden")
    if command.lms_business_api_activation_requested:
        reasons.append("lms_business_api_activation_request_forbidden")
    if command.persistent_task_creation_requested:
        reasons.append("persistent_task_creation_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
