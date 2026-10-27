from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID
from suite.platform.lms_package_installation_dry_run_execution_approval_record import (
    LmsPackageInstallationDryRunExecutionApprovalRecordStore,
)
from suite.platform.lms_package_installation_dry_run_execution_plan import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_ENDPOINT,
)
from suite.platform.lms_package_installation_readiness import build_lms_package_installation_readiness_response
from suite.platform.lms_tenant_admin_package_approval_record import LmsTenantAdminPackageApprovalRecordStore
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_plan_review.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_plan_review_no_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-plan-review"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_STATEMENT = (
    "I review the LMS package installation dry-run execution plan without activating schedulers, "
    "resolving worker images, enqueuing workers, starting dry-run execution, persisting dry-run results, "
    "or executing package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_READY_NEXT_ACTION = (
    "prepare_lms_dry_run_execution_scheduler_boundary_without_activation"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_RETRY_NEXT_ACTION = (
    "prepare_lms_dry_run_execution_plan_review_without_execution"
)

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class LmsPackageInstallationDryRunExecutionPlanReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_plan_evidence_hash: str
    dry_run_execution_runbook_evidence_hash: str
    dry_run_execution_admission_gate_evidence_hash: str
    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_approval_record_hash: str
    dry_run_execution_plan_review_ref: str
    dry_run_execution_plan_ref: str
    backup_restore_runbook_ref: str
    rollback_runbook_ref: str
    operator_handoff_ref: str
    execution_window_ref: str
    resource_budget_ref: str
    scheduler_policy_ref: str
    idempotency_key_ref: str
    change_request_ref: str
    reviewed_at_utc: datetime
    audit_chain_ref: str
    dry_run_execution_plan_review_statement: str
    dry_run_execution_plan_review_requested: bool = True
    scheduler_activation_requested: bool = False
    worker_image_resolution_requested: bool = False
    worker_dispatch_requested: bool = False
    worker_queue_enqueue_requested: bool = False
    worker_execution_requested: bool = False
    package_installation_dry_run_execution_requested: bool = False
    dry_run_result_persistence_requested: bool = False
    package_installation_execution_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    lms_business_api_activation_requested: bool = False
    persistent_task_creation_requested: bool = False
    rollback_execution_requested: bool = False
    failover_execution_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "dry_run_execution_plan_evidence_hash",
        "dry_run_execution_runbook_evidence_hash",
        "dry_run_execution_admission_gate_evidence_hash",
        "dry_run_execution_approval_boundary_evidence_hash",
        "dry_run_execution_approval_record_hash",
    )
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution plan review hashes must be sha256 references")
        return value

    @field_validator(
        "dry_run_execution_plan_review_ref",
        "dry_run_execution_plan_ref",
        "backup_restore_runbook_ref",
        "rollback_runbook_ref",
        "operator_handoff_ref",
        "execution_window_ref",
        "resource_budget_ref",
        "scheduler_policy_ref",
        "idempotency_key_ref",
        "change_request_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS dry-run execution plan review references must use a typed ref prefix")
        return value.strip()

    @field_validator("dry_run_execution_plan_review_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_STATEMENT:
            raise ValueError("LMS dry-run execution plan review requires the exact review statement")
        return normalized

    @field_validator("reviewed_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution plan review reviewed_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionPlanReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_plan_review_step_count: int
    required_dry_run_execution_plan_review_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionPlanReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    package_installation_ready: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool
    human_approval_ready: bool
    dry_run_execution_plan_endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_ENDPOINT
    dry_run_execution_plan_evidence_hash: str
    dry_run_execution_runbook_evidence_hash: str
    dry_run_execution_admission_gate_evidence_hash: str
    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_approval_record_hash: str
    stored_dry_run_execution_approval_record_hash: str
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    dry_run_execution_plan_review_statement_hash: str
    dry_run_execution_plan_review_ref: str
    dry_run_execution_plan_ref: str
    backup_restore_runbook_ref: str
    rollback_runbook_ref: str
    operator_handoff_ref: str
    execution_window_ref: str
    resource_budget_ref: str
    scheduler_policy_ref: str
    change_request_ref: str
    audit_chain_ref: str
    reviewed_by: str
    reviewed_at_utc: datetime
    reviewer_role_allowed: bool
    dry_run_execution_plan_review_requested: bool
    dry_run_execution_plan_review_ready: bool
    explicit_human_execution_approval_present: bool
    approval_record_tenant_match: bool
    approval_record_hash_match: bool
    future_dry_run_execution_scheduler_boundary_required: bool = True
    scheduler_activation_allowed: bool = False
    worker_image_resolution_allowed: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
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
    rollback_execution_allowed: bool = False
    failover_execution_allowed: bool = False
    content_included: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    dry_run_execution_plan_review_steps: tuple[str, ...]
    required_dry_run_execution_plan_review_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionPlanReviewSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "dry_run_execution_plan_endpoint",
        "dry_run_execution_plan_review_ref",
        "dry_run_execution_plan_ref",
        "backup_restore_runbook_ref",
        "rollback_runbook_ref",
        "operator_handoff_ref",
        "execution_window_ref",
        "resource_budget_ref",
        "scheduler_policy_ref",
        "change_request_ref",
        "audit_chain_ref",
        "reviewed_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution plan review text fields must not be empty")
        return value

    @field_validator(
        "dry_run_execution_plan_evidence_hash",
        "dry_run_execution_runbook_evidence_hash",
        "dry_run_execution_admission_gate_evidence_hash",
        "dry_run_execution_approval_boundary_evidence_hash",
        "dry_run_execution_approval_record_hash",
        "stored_dry_run_execution_approval_record_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "dry_run_execution_plan_review_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution plan review hashes must be sha256 references")
        return value

    @field_validator(
        "dry_run_execution_plan_review_steps",
        "required_dry_run_execution_plan_review_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution plan review lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution plan review list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_plan_review(self) -> LmsPackageInstallationDryRunExecutionPlanReviewResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution plan review schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_ENDPOINT:
            raise ValueError("LMS dry-run execution plan review endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution plan review result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution plan review only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution plan review continuity domain is invalid")
        if self.explicit_human_execution_approval_present != (
            self.approval_record_tenant_match and self.approval_record_hash_match
        ):
            raise ValueError("LMS dry-run execution plan review approval flags must match stored approval record")
        expected_ready = (
            self.package_installation_ready
            and self.reviewer_role_allowed
            and self.dry_run_execution_plan_review_requested
            and self.explicit_human_execution_approval_present
            and not self.blocking_reasons
        )
        if self.dry_run_execution_plan_review_ready != expected_ready:
            raise ValueError("LMS dry-run execution plan review readiness must match prerequisites")
        if not self.future_dry_run_execution_scheduler_boundary_required:
            raise ValueError("LMS dry-run execution plan review must require a future scheduler boundary")
        if (
            self.scheduler_activation_allowed
            or self.worker_image_resolution_allowed
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.package_installation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.package_installation_executed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.rollback_execution_allowed
            or self.failover_execution_allowed
            or self.content_included
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution plan review must remain metadata-only and non-executing")
        if self.summary.dry_run_execution_plan_review_step_count != len(self.dry_run_execution_plan_review_steps):
            raise ValueError("LMS dry-run execution plan review step count must match review steps")
        if self.summary.required_dry_run_execution_plan_review_evidence_count != len(
            self.required_dry_run_execution_plan_review_evidence
        ):
            raise ValueError("LMS dry-run execution plan review evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution plan review blocking count must match blocking reasons")
        return self


def build_lms_package_installation_dry_run_execution_plan_review_response(
    *,
    command: LmsPackageInstallationDryRunExecutionPlanReviewCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    package_approval_record_store: LmsTenantAdminPackageApprovalRecordStore | None,
    dry_run_execution_approval_record_store: LmsPackageInstallationDryRunExecutionApprovalRecordStore | None,
) -> LmsPackageInstallationDryRunExecutionPlanReviewResponse:
    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
        approval_record_store=package_approval_record_store,
    )
    approval_record = (
        dry_run_execution_approval_record_store.latest_for_boundary(
            tenant_id=user_context.tenant_id,
            dry_run_execution_approval_boundary_evidence_hash=(
                command.dry_run_execution_approval_boundary_evidence_hash
            ),
        )
        if dry_run_execution_approval_record_store is not None
        else None
    )
    stored_approval_record_hash = approval_record.evidence_hash if approval_record is not None else ZERO_SHA256
    approval_record_tenant_match = approval_record is not None and approval_record.tenant_id == user_context.tenant_id
    approval_record_hash_match = (
        approval_record is not None and stored_approval_record_hash == command.dry_run_execution_approval_record_hash
    )
    explicit_human_execution_approval_present = approval_record_tenant_match and approval_record_hash_match
    command_hash = build_lms_package_installation_dry_run_execution_plan_review_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_execution_plan_review_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "dry_run_execution_plan_evidence_hash": command.dry_run_execution_plan_evidence_hash,
                "dry_run_execution_runbook_evidence_hash": command.dry_run_execution_runbook_evidence_hash,
                "dry_run_execution_admission_gate_evidence_hash": (
                    command.dry_run_execution_admission_gate_evidence_hash
                ),
                "dry_run_execution_approval_boundary_evidence_hash": (
                    command.dry_run_execution_approval_boundary_evidence_hash
                ),
                "dry_run_execution_approval_record_hash": command.dry_run_execution_approval_record_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    statement_hash = stable_hash(command.dry_run_execution_plan_review_statement)
    reviewer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    blocking_reasons = _dry_run_execution_plan_review_blocking_reasons(
        command=command,
        package_installation_ready=readiness.package_installation_ready,
        approval_record_present=approval_record is not None,
        approval_record_hash_match=approval_record_hash_match,
        reviewer_role_allowed=reviewer_role_allowed,
    )
    plan_review_ready = not blocking_reasons
    review_steps = (
        "verify_lms_catalog_status_not_installed",
        "bind_lms_package_installation_dry_run_execution_plan_hash",
        "bind_lms_package_installation_dry_run_execution_runbook_hash",
        "bind_lms_package_installation_dry_run_execution_admission_gate_hash",
        "bind_lms_package_installation_dry_run_execution_approval_boundary_hash",
        "bind_lms_dry_run_execution_approval_record_hash",
        "verify_approval_record_is_tenant_scoped_and_hash_matched",
        "review_backup_restore_runbook_ref",
        "review_rollback_runbook_ref",
        "review_operator_handoff_ref",
        "review_execution_window_ref",
        "review_resource_budget_ref",
        "review_scheduler_policy_ref_without_activation",
        "confirm_scheduler_boundary_is_future_metadata_gate",
        "confirm_worker_image_resolution_remains_disabled",
        "confirm_worker_no_enqueue_no_dispatch_no_execution_flags",
        "confirm_no_rollback_or_failover_execution",
        "confirm_no_tenant_module_state_creation",
        "confirm_no_lms_business_api_activation",
        "emit_audit_hashes_without_prompt_or_confirmation_text",
    )
    required_evidence = (
        "tenant_admin_role",
        "package_installation_readiness_true",
        "package_installation_dry_run_execution_plan_hash",
        "package_installation_dry_run_execution_runbook_hash",
        "package_installation_dry_run_execution_admission_gate_hash",
        "package_installation_dry_run_execution_approval_boundary_hash",
        "lms_dry_run_execution_approval_record_hash",
        "stored_lms_dry_run_execution_approval_record_hash",
        "approval_record_tenant_match",
        "approval_record_hash_match",
        "explicit_human_execution_approval_present",
        "tenant_admin_package_install_approval_gate_hash",
        "tenant_admin_package_install_approval_record_hash",
        "restore_drill_evidence_hash",
        "exact_dry_run_execution_plan_review_statement_hash",
        "backup_restore_runbook_ref",
        "rollback_runbook_ref",
        "operator_handoff_ref",
        "execution_window_ref",
        "resource_budget_ref",
        "scheduler_policy_ref_reviewed_without_activation",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "dry_run_execution_plan_review_schema_version",
        "future_dry_run_execution_scheduler_boundary_required",
        "scheduler_not_activated",
        "worker_image_resolution_disabled",
        "worker_no_enqueue_no_dispatch_no_execution_flags",
        "no_rollback_or_failover_execution",
        "no_lms_dry_run_execution_confirmation",
        "no_dry_run_result_persistence_confirmation",
    )
    draft = LmsPackageInstallationDryRunExecutionPlanReviewResponse(
        tenant_id=user_context.tenant_id,
        package_installation_ready=readiness.package_installation_ready,
        migration_plan_ready=readiness.migration_plan_ready,
        restore_evidence_ready=readiness.restore_evidence_ready,
        human_approval_ready=readiness.human_approval_ready,
        dry_run_execution_plan_evidence_hash=command.dry_run_execution_plan_evidence_hash,
        dry_run_execution_runbook_evidence_hash=command.dry_run_execution_runbook_evidence_hash,
        dry_run_execution_admission_gate_evidence_hash=command.dry_run_execution_admission_gate_evidence_hash,
        dry_run_execution_approval_boundary_evidence_hash=(command.dry_run_execution_approval_boundary_evidence_hash),
        dry_run_execution_approval_record_hash=command.dry_run_execution_approval_record_hash,
        stored_dry_run_execution_approval_record_hash=stored_approval_record_hash,
        tenant_admin_approval_gate_hash=readiness.tenant_admin_approval_gate_hash or ZERO_SHA256,
        tenant_admin_approval_record_hash=readiness.tenant_admin_approval_record_hash or ZERO_SHA256,
        lms_restore_drill_evidence_hash=readiness.lms_restore_drill_evidence_hash or ZERO_SHA256,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        dry_run_execution_plan_review_statement_hash=statement_hash,
        dry_run_execution_plan_review_ref=command.dry_run_execution_plan_review_ref,
        dry_run_execution_plan_ref=command.dry_run_execution_plan_ref,
        backup_restore_runbook_ref=command.backup_restore_runbook_ref,
        rollback_runbook_ref=command.rollback_runbook_ref,
        operator_handoff_ref=command.operator_handoff_ref,
        execution_window_ref=command.execution_window_ref,
        resource_budget_ref=command.resource_budget_ref,
        scheduler_policy_ref=command.scheduler_policy_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        reviewed_by=user_context.user_id,
        reviewed_at_utc=command.reviewed_at_utc,
        reviewer_role_allowed=reviewer_role_allowed,
        dry_run_execution_plan_review_requested=command.dry_run_execution_plan_review_requested,
        dry_run_execution_plan_review_ready=plan_review_ready,
        explicit_human_execution_approval_present=explicit_human_execution_approval_present,
        approval_record_tenant_match=approval_record_tenant_match,
        approval_record_hash_match=approval_record_hash_match,
        dry_run_execution_plan_review_steps=review_steps,
        required_dry_run_execution_plan_review_evidence=required_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationDryRunExecutionPlanReviewSummary(
            dry_run_execution_plan_review_step_count=len(review_steps),
            required_dry_run_execution_plan_review_evidence_count=len(required_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "docs/operations/BACKUP_FAILOVER.md",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_runbook.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_plan.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_plan_review.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_record.py",
            "app/suite/persistence/migrations/0048_lms_dry_run_execution_approval_records.sql",
            "tests/test_lms_package_installation_dry_run_execution_plan_review.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_READY_NEXT_ACTION
            if plan_review_ready
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PLAN_REVIEW_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_package_installation_dry_run_execution_plan_review_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_plan_review_command_hash(
    command: LmsPackageInstallationDryRunExecutionPlanReviewCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"dry_run_execution_plan_review_statement"})
    payload["dry_run_execution_plan_review_statement_hash"] = stable_hash(
        command.dry_run_execution_plan_review_statement
    )
    return stable_hash(canonical_json(payload))


def build_lms_package_installation_dry_run_execution_plan_review_hash(
    response: LmsPackageInstallationDryRunExecutionPlanReviewResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _dry_run_execution_plan_review_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionPlanReviewCommand,
    package_installation_ready: bool,
    approval_record_present: bool,
    approval_record_hash_match: bool,
    reviewer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not package_installation_ready:
        reasons.append("lms_package_installation_readiness_not_ready")
    if command.dry_run_execution_plan_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_plan_hash_missing")
    if command.dry_run_execution_runbook_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_runbook_hash_missing")
    if command.dry_run_execution_admission_gate_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_admission_gate_hash_missing")
    if command.dry_run_execution_approval_boundary_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_approval_boundary_hash_missing")
    if command.dry_run_execution_approval_record_hash == ZERO_SHA256:
        reasons.append("lms_dry_run_execution_approval_record_hash_missing")
    if not approval_record_present:
        reasons.append("lms_dry_run_execution_approval_record_missing")
    elif not approval_record_hash_match:
        reasons.append("lms_dry_run_execution_approval_record_hash_mismatch")
    if not reviewer_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.dry_run_execution_plan_review_requested:
        reasons.append("dry_run_execution_plan_review_not_requested")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_request_forbidden")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_request_forbidden")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_request_forbidden")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_request_forbidden")
    if command.worker_execution_requested:
        reasons.append("worker_execution_request_forbidden")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_request_forbidden")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_request_forbidden")
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
    if command.rollback_execution_requested:
        reasons.append("rollback_execution_request_forbidden")
    if command.failover_execution_requested:
        reasons.append("failover_execution_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
