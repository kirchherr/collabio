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

LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_approval_boundary.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_approval_boundary_no_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-approval-boundary"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT = "I prepare the LMS package installation dry-run execution approval boundary without recording execution approval, enqueuing workers, dispatching workers, or starting dry-run execution."  # noqa: E501
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_READY_NEXT_ACTION = (
    "record_lms_dry_run_execution_approval_with_explicit_human_confirmation"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RETRY_NEXT_ACTION = (
    "prepare_lms_package_installation_dry_run_execution_approval_boundary_without_execution"
)

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_final_readiness_gate_evidence_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_approval_boundary_ref: str
    change_request_ref: str
    idempotency_key_ref: str
    prepared_at_utc: datetime
    audit_chain_ref: str
    dry_run_execution_approval_boundary_statement: str
    dry_run_execution_approval_boundary_requested: bool = True
    explicit_human_execution_approval_requested: bool = False
    scheduler_activation_requested: bool = False
    scheduler_job_creation_requested: bool = False
    worker_image_resolution_requested: bool = False
    worker_image_pull_requested: bool = False
    worker_image_digest_lookup_requested: bool = False
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "dry_run_execution_final_readiness_gate_evidence_hash",
        "dry_run_execution_scheduler_boundary_evidence_hash",
        "dry_run_execution_worker_image_boundary_evidence_hash",
    )
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution approval boundary hashes must be sha256 references")
        return value

    @field_validator(
        "dry_run_execution_approval_boundary_ref", "change_request_ref", "idempotency_key_ref", "audit_chain_ref"
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS dry-run execution approval boundary references must use a typed ref prefix")
        return value.strip()

    @field_validator("dry_run_execution_approval_boundary_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT:
            raise ValueError("LMS dry-run execution approval boundary requires the exact preparation statement")
        return normalized

    @field_validator("prepared_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution approval boundary prepared_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionApprovalBoundarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_approval_boundary_step_count: int
    required_dry_run_execution_approval_boundary_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionApprovalBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    package_installation_ready: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool
    human_approval_ready: bool
    dry_run_execution_final_readiness_gate_evidence_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    dry_run_execution_approval_boundary_statement_hash: str
    dry_run_execution_approval_boundary_ref: str
    change_request_ref: str
    audit_chain_ref: str
    prepared_by: str
    prepared_at_utc: datetime
    preparer_role_allowed: bool
    dry_run_execution_approval_boundary_requested: bool
    dry_run_execution_approval_boundary_ready: bool
    worker_image_boundary_evidence_bound: bool = False
    future_dry_run_execution_approval_record_required: bool = True
    explicit_human_execution_approval_present: bool = False
    scheduler_activation_allowed: bool = False
    scheduler_job_creation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_image_digest_lookup_allowed: bool = False
    worker_image_digest_looked_up: bool = False
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
    content_included: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    dry_run_execution_approval_boundary_steps: tuple[str, ...]
    required_dry_run_execution_approval_boundary_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionApprovalBoundarySummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "dry_run_execution_approval_boundary_ref",
        "change_request_ref",
        "audit_chain_ref",
        "prepared_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution approval boundary text fields must not be empty")
        return value

    @field_validator(
        "dry_run_execution_final_readiness_gate_evidence_hash",
        "dry_run_execution_scheduler_boundary_evidence_hash",
        "dry_run_execution_worker_image_boundary_evidence_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "dry_run_execution_approval_boundary_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution approval boundary hashes must be sha256 references")
        return value

    @field_validator(
        "dry_run_execution_approval_boundary_steps",
        "required_dry_run_execution_approval_boundary_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution approval boundary lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution approval boundary list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_approval_boundary(
        self,
    ) -> LmsPackageInstallationDryRunExecutionApprovalBoundaryResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution approval boundary schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT:
            raise ValueError("LMS dry-run execution approval boundary endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution approval boundary result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution approval boundary only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution approval boundary continuity domain is invalid")
        expected_ready = (
            self.package_installation_ready
            and self.preparer_role_allowed
            and self.dry_run_execution_approval_boundary_requested
            and not self.blocking_reasons
        )
        if self.dry_run_execution_approval_boundary_ready != expected_ready:
            raise ValueError("LMS dry-run execution approval boundary readiness must match prerequisites")
        if not self.future_dry_run_execution_approval_record_required:
            raise ValueError("LMS dry-run execution approval boundary must require a future approval record")
        if self.explicit_human_execution_approval_present:
            raise ValueError("LMS dry-run execution approval boundary must not record execution approval")
        expected_worker_image_bound = (
            self.dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
            or self.dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
        )
        if self.worker_image_boundary_evidence_bound != expected_worker_image_bound:
            raise ValueError("LMS dry-run execution approval boundary worker-image binding flag is invalid")
        if (
            self.explicit_human_execution_approval_present
            or self.scheduler_activation_allowed
            or self.scheduler_job_creation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_image_digest_lookup_allowed
            or self.worker_image_digest_looked_up
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
            or self.content_included
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution approval boundary must remain metadata-only and non-executing")
        if self.summary.dry_run_execution_approval_boundary_step_count != len(
            self.dry_run_execution_approval_boundary_steps
        ):
            raise ValueError("LMS dry-run execution approval boundary step count must match boundary steps")
        if self.summary.required_dry_run_execution_approval_boundary_evidence_count != len(
            self.required_dry_run_execution_approval_boundary_evidence
        ):
            raise ValueError("LMS dry-run execution approval boundary evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution approval boundary blocking count must match blocking reasons")
        return self


def build_lms_package_installation_dry_run_execution_approval_boundary_response(
    *,
    command: LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    approval_record_store: LmsTenantAdminPackageApprovalRecordStore | None,
) -> LmsPackageInstallationDryRunExecutionApprovalBoundaryResponse:
    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
        approval_record_store=approval_record_store,
    )
    command_hash = build_lms_package_installation_dry_run_execution_approval_boundary_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_execution_approval_boundary_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "dry_run_execution_final_readiness_gate_evidence_hash": (
                    command.dry_run_execution_final_readiness_gate_evidence_hash
                ),
                "dry_run_execution_scheduler_boundary_evidence_hash": (
                    command.dry_run_execution_scheduler_boundary_evidence_hash
                ),
                "dry_run_execution_worker_image_boundary_evidence_hash": (
                    command.dry_run_execution_worker_image_boundary_evidence_hash
                ),
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    statement_hash = stable_hash(command.dry_run_execution_approval_boundary_statement)
    preparer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    blocking_reasons = _dry_run_execution_approval_boundary_blocking_reasons(
        command=command,
        package_installation_ready=readiness.package_installation_ready,
        expected_approval_record_hash=readiness.tenant_admin_approval_record_hash,
        preparer_role_allowed=preparer_role_allowed,
    )
    boundary_ready = not blocking_reasons
    worker_image_boundary_evidence_bound = (
        command.dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
        or command.dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
    )
    contract_fields = (
        "verify_lms_catalog_status_not_installed",
        "bind_lms_package_installation_dry_run_execution_final_readiness_gate_hash",
        "bind_lms_package_installation_dry_run_execution_scheduler_boundary_hash_when_present",
        "bind_lms_package_installation_dry_run_execution_worker_image_boundary_hash_when_present",
        "verify_dry_run_execution_final_readiness_gate_schema_bound",
        "confirm_worker_image_boundary_chain_preserved_at_approval_boundary_when_present",
        "define_approval_boundary_idempotency_and_hash_closure",
        "define_approval_boundary_requires_separate_explicit_human_approval_record",
        "confirm_no_execution_approval_recorded_at_approval_boundary",
        "confirm_scheduler_no_activation_no_job_creation_flags",
        "confirm_worker_image_no_resolution_no_pull_no_digest_lookup_flags",
        "confirm_worker_no_enqueue_no_dispatch_no_execution_flags",
        "defer_dry_run_result_persistence",
        "confirm_no_tenant_module_state_creation",
        "confirm_no_lms_business_api_activation",
        "emit_audit_hashes_without_prompt_or_confirmation_text",
    )
    required_evidence = (
        "tenant_admin_role",
        "package_installation_readiness_true",
        "package_installation_dry_run_execution_final_readiness_gate_hash",
        "optional_package_installation_dry_run_execution_scheduler_boundary_hash",
        "optional_package_installation_dry_run_execution_worker_image_boundary_hash",
        "worker_image_boundary_chain_hashes_when_present",
        "tenant_admin_package_install_approval_gate_hash",
        "tenant_admin_package_install_approval_record_hash",
        "restore_drill_evidence_hash",
        "exact_dry_run_execution_approval_boundary_statement_hash",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "dry_run_execution_approval_boundary_schema_version",
        "dry_run_execution_final_readiness_gate_schema_version",
        "approval_boundary_idempotency_and_hash_closure",
        "scheduler_activation_disabled",
        "scheduler_job_creation_disabled",
        "worker_image_resolution_disabled",
        "worker_image_pull_disabled",
        "worker_image_digest_lookup_disabled",
        "separate_explicit_execution_approval_record_required",
        "future_dry_run_execution_approval_record_required",
        "no_lms_dry_run_execution_confirmation",
        "no_dry_run_result_persistence_confirmation",
    )
    draft = LmsPackageInstallationDryRunExecutionApprovalBoundaryResponse(
        tenant_id=user_context.tenant_id,
        package_installation_ready=readiness.package_installation_ready,
        migration_plan_ready=readiness.migration_plan_ready,
        restore_evidence_ready=readiness.restore_evidence_ready,
        human_approval_ready=readiness.human_approval_ready,
        dry_run_execution_final_readiness_gate_evidence_hash=(
            command.dry_run_execution_final_readiness_gate_evidence_hash
        ),
        dry_run_execution_scheduler_boundary_evidence_hash=(command.dry_run_execution_scheduler_boundary_evidence_hash),
        dry_run_execution_worker_image_boundary_evidence_hash=(
            command.dry_run_execution_worker_image_boundary_evidence_hash
        ),
        tenant_admin_approval_gate_hash=readiness.tenant_admin_approval_gate_hash or ZERO_SHA256,
        tenant_admin_approval_record_hash=readiness.tenant_admin_approval_record_hash or ZERO_SHA256,
        lms_restore_drill_evidence_hash=readiness.lms_restore_drill_evidence_hash or ZERO_SHA256,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        dry_run_execution_approval_boundary_statement_hash=statement_hash,
        dry_run_execution_approval_boundary_ref=command.dry_run_execution_approval_boundary_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        prepared_by=user_context.user_id,
        prepared_at_utc=command.prepared_at_utc,
        preparer_role_allowed=preparer_role_allowed,
        dry_run_execution_approval_boundary_requested=command.dry_run_execution_approval_boundary_requested,
        dry_run_execution_approval_boundary_ready=boundary_ready,
        worker_image_boundary_evidence_bound=worker_image_boundary_evidence_bound,
        dry_run_execution_approval_boundary_steps=contract_fields,
        required_dry_run_execution_approval_boundary_evidence=required_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationDryRunExecutionApprovalBoundarySummary(
            dry_run_execution_approval_boundary_step_count=len(contract_fields),
            required_dry_run_execution_approval_boundary_evidence_count=len(required_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_scheduler_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_worker_image_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_final_readiness_gate.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_boundary.py",
            "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
            "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
            "tests/test_lms_package_installation_dry_run_execution_scheduler_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_worker_image_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_final_readiness_gate.py",
            "tests/test_lms_package_installation_dry_run_execution_approval_boundary.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_READY_NEXT_ACTION
            if boundary_ready
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_package_installation_dry_run_execution_approval_boundary_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_approval_boundary_command_hash(
    command: LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"dry_run_execution_approval_boundary_statement"})
    payload["dry_run_execution_approval_boundary_statement_hash"] = stable_hash(
        command.dry_run_execution_approval_boundary_statement
    )
    return stable_hash(canonical_json(payload))


def build_lms_package_installation_dry_run_execution_approval_boundary_hash(
    response: LmsPackageInstallationDryRunExecutionApprovalBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _dry_run_execution_approval_boundary_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand,
    package_installation_ready: bool,
    expected_approval_record_hash: str | None,
    preparer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not package_installation_ready:
        reasons.append("lms_package_installation_readiness_not_ready")
    if command.dry_run_execution_final_readiness_gate_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_final_readiness_gate_hash_missing")
    new_worker_image_chain_requested = (
        command.dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
        or command.dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
    )
    if new_worker_image_chain_requested and command.dry_run_execution_scheduler_boundary_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_scheduler_boundary_hash_missing")
    if (
        new_worker_image_chain_requested
        and command.dry_run_execution_worker_image_boundary_evidence_hash == ZERO_SHA256
    ):
        reasons.append("package_installation_dry_run_execution_worker_image_boundary_hash_missing")
    if expected_approval_record_hash is None:
        reasons.append("tenant_admin_package_install_approval_record_missing")
    if not preparer_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.dry_run_execution_approval_boundary_requested:
        reasons.append("dry_run_execution_approval_boundary_not_requested")
    if command.explicit_human_execution_approval_requested:
        reasons.append("explicit_human_execution_approval_requires_separate_record")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_request_forbidden")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_request_forbidden")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_request_forbidden")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_request_forbidden")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_request_forbidden")
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
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
