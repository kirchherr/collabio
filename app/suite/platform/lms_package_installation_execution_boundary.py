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

LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_SCHEMA_VERSION = "lms_package_installation_execution_boundary.v1"
LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_execution_boundary_no_install"
)
LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-execution-boundary"
)
LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT = (
    "I request LMS package installation execution boundary review without executing installation."
)
LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_READY_NEXT_ACTION = (
    "prepare_lms_package_installation_executor_without_business_api_activation"
)
LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_RETRY_NEXT_ACTION = "review_lms_package_installation_execution_boundary"

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class LmsPackageInstallationExecutionBoundaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    execution_boundary_ref: str
    change_request_ref: str
    idempotency_key_ref: str
    reviewed_at_utc: datetime
    audit_chain_ref: str
    execution_boundary_review_statement: str
    execution_boundary_review_requested: bool = True
    package_installation_execution_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    lms_business_api_activation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("tenant_admin_approval_gate_hash", "tenant_admin_approval_record_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS execution boundary hashes must be sha256 references")
        return value

    @field_validator("execution_boundary_ref", "change_request_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS execution boundary references must use a typed ref prefix")
        return value.strip()

    @field_validator("execution_boundary_review_statement")
    @classmethod
    def require_exact_review_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT:
            raise ValueError("LMS execution boundary requires the exact review statement")
        return normalized

    @field_validator("reviewed_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS execution boundary reviewed_at_utc must include a timezone")
        return value


class LmsPackageInstallationExecutionBoundarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_execution_boundary_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationExecutionBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    package_installation_ready: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool
    human_approval_ready: bool
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    execution_boundary_review_statement_hash: str
    execution_boundary_ref: str
    change_request_ref: str
    audit_chain_ref: str
    reviewed_by: str
    reviewed_at_utc: datetime
    approver_role_allowed: bool
    execution_boundary_review_requested: bool
    execution_boundary_review_ready: bool
    package_installation_execution_boundary_ready: bool
    future_package_installation_executor_required: bool = True
    package_installation_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    lms_business_api_allowed: bool = False
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    tenant_module_state_created: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    required_execution_boundary_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationExecutionBoundarySummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "execution_boundary_ref",
        "change_request_ref",
        "audit_chain_ref",
        "reviewed_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS execution boundary text fields must not be empty")
        return value

    @field_validator(
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "execution_boundary_review_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS execution boundary hashes must be sha256 references")
        return value

    @field_validator("required_execution_boundary_evidence", "blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS execution boundary lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS execution boundary list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_boundary_contract(self) -> LmsPackageInstallationExecutionBoundaryResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_SCHEMA_VERSION:
            raise ValueError("LMS execution boundary schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_ENDPOINT:
            raise ValueError("LMS execution boundary endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_RESULT_CONTRACT:
            raise ValueError("LMS execution boundary result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS execution boundary only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS execution boundary continuity domain is invalid")
        expected_ready = (
            self.package_installation_ready
            and self.approver_role_allowed
            and self.execution_boundary_review_requested
            and not self.blocking_reasons
        )
        if self.execution_boundary_review_ready != expected_ready:
            raise ValueError("LMS execution boundary review readiness must match prerequisites")
        if self.package_installation_execution_boundary_ready != expected_ready:
            raise ValueError("LMS execution boundary readiness must match prerequisites")
        if not self.future_package_installation_executor_required:
            raise ValueError("LMS execution boundary must still require a future executor")
        if (
            self.package_installation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.package_installation_executed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS execution boundary must remain metadata-only and non-executing")
        if self.summary.required_execution_boundary_evidence_count != len(self.required_execution_boundary_evidence):
            raise ValueError("LMS execution boundary evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS execution boundary blocking count must match blocking reasons")
        return self


def build_lms_package_installation_execution_boundary_response(
    *,
    command: LmsPackageInstallationExecutionBoundaryCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    approval_record_store: LmsTenantAdminPackageApprovalRecordStore | None,
) -> LmsPackageInstallationExecutionBoundaryResponse:
    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
        approval_record_store=approval_record_store,
    )
    command_hash = build_lms_package_installation_execution_boundary_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_execution_boundary_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "tenant_admin_approval_gate_hash": command.tenant_admin_approval_gate_hash,
                "tenant_admin_approval_record_hash": command.tenant_admin_approval_record_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    review_statement_hash = stable_hash(command.execution_boundary_review_statement)
    approver_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    blocking_reasons = _execution_boundary_blocking_reasons(
        command=command,
        package_installation_ready=readiness.package_installation_ready,
        expected_approval_gate_hash=readiness.tenant_admin_approval_gate_hash,
        expected_approval_record_hash=readiness.tenant_admin_approval_record_hash,
        approver_role_allowed=approver_role_allowed,
    )
    boundary_ready = not blocking_reasons
    required_execution_boundary_evidence = (
        "tenant_admin_role",
        "package_installation_readiness_true",
        "tenant_admin_package_install_approval_gate_hash",
        "tenant_admin_package_install_approval_record_hash",
        "restore_drill_evidence_hash",
        "exact_execution_boundary_review_statement_hash",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_package_installation_executor_required",
        "no_lms_installation_execution_confirmation",
    )
    draft = LmsPackageInstallationExecutionBoundaryResponse(
        tenant_id=user_context.tenant_id,
        package_installation_ready=readiness.package_installation_ready,
        migration_plan_ready=readiness.migration_plan_ready,
        restore_evidence_ready=readiness.restore_evidence_ready,
        human_approval_ready=readiness.human_approval_ready,
        tenant_admin_approval_gate_hash=command.tenant_admin_approval_gate_hash,
        tenant_admin_approval_record_hash=command.tenant_admin_approval_record_hash,
        lms_restore_drill_evidence_hash=readiness.lms_restore_drill_evidence_hash
        or "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        execution_boundary_review_statement_hash=review_statement_hash,
        execution_boundary_ref=command.execution_boundary_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        reviewed_by=user_context.user_id,
        reviewed_at_utc=command.reviewed_at_utc,
        approver_role_allowed=approver_role_allowed,
        execution_boundary_review_requested=command.execution_boundary_review_requested,
        execution_boundary_review_ready=boundary_ready,
        package_installation_execution_boundary_ready=boundary_ready,
        required_execution_boundary_evidence=required_execution_boundary_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationExecutionBoundarySummary(
            required_execution_boundary_evidence_count=len(required_execution_boundary_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_package_installation_execution_boundary.py",
            "app/suite/platform/lms_tenant_admin_package_approval_gate.py",
            "app/suite/platform/lms_tenant_admin_package_approval_record.py",
            "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
            "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
            "tests/test_lms_package_installation_execution_boundary.py",
        ),
        evidence_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        next_action=(
            LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_READY_NEXT_ACTION
            if boundary_ready
            else LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_package_installation_execution_boundary_hash(draft)})


def build_lms_package_installation_execution_boundary_command_hash(
    command: LmsPackageInstallationExecutionBoundaryCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"execution_boundary_review_statement"})
    payload["execution_boundary_review_statement_hash"] = stable_hash(command.execution_boundary_review_statement)
    return stable_hash(canonical_json(payload))


def build_lms_package_installation_execution_boundary_hash(
    response: LmsPackageInstallationExecutionBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _execution_boundary_blocking_reasons(
    *,
    command: LmsPackageInstallationExecutionBoundaryCommand,
    package_installation_ready: bool,
    expected_approval_gate_hash: str | None,
    expected_approval_record_hash: str | None,
    approver_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not package_installation_ready:
        reasons.append("lms_package_installation_readiness_not_ready")
    if command.tenant_admin_approval_gate_hash != expected_approval_gate_hash:
        reasons.append("tenant_admin_approval_gate_hash_mismatch")
    if expected_approval_record_hash is None:
        reasons.append("tenant_admin_package_install_approval_record_missing")
    elif command.tenant_admin_approval_record_hash != expected_approval_record_hash:
        reasons.append("tenant_admin_package_install_approval_record_hash_mismatch")
    if not approver_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.execution_boundary_review_requested:
        reasons.append("execution_boundary_review_not_requested")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_request_forbidden")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_request_forbidden")
    if command.migration_execution_requested:
        reasons.append("migration_execution_request_forbidden")
    if command.lms_business_api_activation_requested:
        reasons.append("lms_business_api_activation_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
