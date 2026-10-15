from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID
from suite.platform.lms_package_installation_dry_run_execution_approval_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT,
)
from suite.platform.lms_package_installation_readiness import build_lms_package_installation_readiness_response
from suite.platform.lms_tenant_admin_package_approval_record import LmsTenantAdminPackageApprovalRecordStore
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_approval_record.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_approval_record_no_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-approval-records"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT = (
    "I explicitly approve the LMS package installation dry-run execution for this tenant without "
    "running workers, persisting dry-run results, or executing package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CREATED_NEXT_ACTION = (
    "prepare_lms_dry_run_execution_admission_gate_without_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RETRY_NEXT_ACTION = (
    "record_lms_dry_run_execution_approval_with_explicit_human_confirmation"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_APPROVED = (
    "approved_for_dry_run_execution_admission_gate"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_BLOCKED = "blocked"

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class LmsPackageInstallationDryRunExecutionApprovalRecordCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    change_request_ref: str
    idempotency_key_ref: str
    approved_at_utc: datetime
    audit_chain_ref: str
    dry_run_execution_approval_record_requested: bool = True
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
        "dry_run_execution_approval_boundary_evidence_hash",
        "dry_run_execution_scheduler_boundary_evidence_hash",
        "dry_run_execution_worker_image_boundary_evidence_hash",
    )
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution approval record hashes must be sha256 references")
        return value

    @field_validator(
        "dry_run_execution_approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "idempotency_key_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS dry-run execution approval record references must use a typed ref prefix")
        return value.strip()

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT:
            raise ValueError("LMS dry-run execution approval record requires the exact confirmation statement")
        return normalized

    @field_validator("approved_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution approval record approved_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionApprovalRecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_approval_record_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionApprovalRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    package_installation_ready: bool
    dry_run_execution_approval_boundary_endpoint: str = (
        LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT
    )
    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    dry_run_execution_approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    change_request_ref: str
    audit_chain_ref: str
    approved_by: str
    approved_at_utc: datetime
    approver_role_allowed: bool
    record_status: str
    dry_run_execution_approval_record_created: bool
    human_confirmation_captured: bool
    human_confirmation_statement_matched: bool
    explicit_human_execution_approval_present: bool
    worker_image_boundary_evidence_bound: bool = False
    future_dry_run_execution_admission_gate_required: bool = True
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
    required_approval_record_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionApprovalRecordSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "dry_run_execution_approval_boundary_endpoint",
        "dry_run_execution_approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "audit_chain_ref",
        "approved_by",
        "record_status",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution approval record text fields must not be empty")
        return value

    @field_validator(
        "dry_run_execution_approval_boundary_evidence_hash",
        "dry_run_execution_scheduler_boundary_evidence_hash",
        "dry_run_execution_worker_image_boundary_evidence_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution approval record hashes must be sha256 references")
        return value

    @field_validator("required_approval_record_evidence", "blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution approval record lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution approval record list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_approval_record(
        self,
    ) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution approval record schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_ENDPOINT:
            raise ValueError("LMS dry-run execution approval record endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution approval record result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution approval record only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution approval record continuity domain is invalid")
        expected_created = (
            self.package_installation_ready
            and self.approver_role_allowed
            and self.human_confirmation_captured
            and self.human_confirmation_statement_matched
            and self.dry_run_execution_approval_boundary_evidence_hash != ZERO_SHA256
            and not self.blocking_reasons
        )
        if self.dry_run_execution_approval_record_created != expected_created:
            raise ValueError("LMS dry-run execution approval record creation flag must match prerequisites")
        if self.explicit_human_execution_approval_present != self.dry_run_execution_approval_record_created:
            raise ValueError("LMS dry-run execution approval presence must match created approval record")
        if (
            self.dry_run_execution_approval_record_created
            and self.record_status != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_APPROVED
        ):
            raise ValueError("created LMS dry-run execution approval records must use approved status")
        if (
            not self.dry_run_execution_approval_record_created
            and self.record_status != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_BLOCKED
        ):
            raise ValueError("blocked LMS dry-run execution approval records must use blocked status")
        if not self.future_dry_run_execution_admission_gate_required:
            raise ValueError("LMS dry-run execution approval record must require a future admission gate")
        expected_worker_image_bound = (
            self.dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
            or self.dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
        )
        if self.worker_image_boundary_evidence_bound != expected_worker_image_bound:
            raise ValueError("LMS dry-run execution approval record worker-image binding flag is invalid")
        if (
            self.scheduler_activation_allowed
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
            raise ValueError("LMS dry-run execution approval record must remain metadata-only and non-executing")
        if self.summary.required_approval_record_evidence_count != len(self.required_approval_record_evidence):
            raise ValueError("LMS dry-run execution approval record evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution approval record blocking count must match blocking reasons")
        return self


class LmsPackageInstallationDryRunExecutionApprovalRecordStore(Protocol):
    def append(
        self,
        record: LmsPackageInstallationDryRunExecutionApprovalRecordResponse,
    ) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse: ...

    def latest_for_boundary(
        self,
        *,
        tenant_id: str,
        dry_run_execution_approval_boundary_evidence_hash: str,
    ) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse | None: ...


class InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore:
    def __init__(
        self,
        records: Iterable[LmsPackageInstallationDryRunExecutionApprovalRecordResponse] = (),
    ) -> None:
        self._by_tenant_boundary: dict[
            tuple[str, str], LmsPackageInstallationDryRunExecutionApprovalRecordResponse
        ] = {}
        self._by_tenant_idempotency: dict[
            tuple[str, str], LmsPackageInstallationDryRunExecutionApprovalRecordResponse
        ] = {}
        for record in records:
            self.append(record)

    def append(
        self,
        record: LmsPackageInstallationDryRunExecutionApprovalRecordResponse,
    ) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse:
        if not record.dry_run_execution_approval_record_created:
            raise ValueError("blocked LMS dry-run execution approval record attempts must not be appended")
        boundary_key = (record.tenant_id, record.dry_run_execution_approval_boundary_evidence_hash)
        idempotency_key = (record.tenant_id, record.idempotency_key_hash)
        existing_for_idempotency = self._by_tenant_idempotency.get(idempotency_key)
        if existing_for_idempotency is not None:
            return existing_for_idempotency
        existing_for_boundary = self._by_tenant_boundary.get(boundary_key)
        if existing_for_boundary is not None:
            raise ValueError("LMS dry-run execution approval boundary already has an approval record")
        self._by_tenant_boundary[boundary_key] = record
        self._by_tenant_idempotency[idempotency_key] = record
        return record

    def latest_for_boundary(
        self,
        *,
        tenant_id: str,
        dry_run_execution_approval_boundary_evidence_hash: str,
    ) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse | None:
        return self._by_tenant_boundary.get((tenant_id, dry_run_execution_approval_boundary_evidence_hash))


def build_default_lms_package_installation_dry_run_execution_approval_record_store() -> (
    InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore
):
    return InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore()


def build_lms_package_installation_dry_run_execution_approval_record_response(
    *,
    command: LmsPackageInstallationDryRunExecutionApprovalRecordCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    package_approval_record_store: LmsTenantAdminPackageApprovalRecordStore | None,
) -> LmsPackageInstallationDryRunExecutionApprovalRecordResponse:
    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
        approval_record_store=package_approval_record_store,
    )
    command_hash = build_lms_package_installation_dry_run_execution_approval_record_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_execution_approval_record_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "dry_run_execution_approval_boundary_evidence_hash": (
                    command.dry_run_execution_approval_boundary_evidence_hash
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
    human_confirmation_statement_hash = stable_hash(command.human_confirmation_statement)
    approver_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    human_confirmation_statement_matched = (
        command.human_confirmation_statement
        == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
    )
    blocking_reasons = _approval_record_blocking_reasons(
        command=command,
        package_installation_ready=readiness.package_installation_ready,
        approver_role_allowed=approver_role_allowed,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
    )
    approval_record_created = not blocking_reasons
    worker_image_boundary_evidence_bound = (
        command.dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
        or command.dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
    )
    required_approval_evidence = (
        "tenant_admin_role",
        "package_installation_readiness_true",
        "dry_run_execution_approval_boundary_evidence_hash",
        "optional_package_installation_dry_run_execution_scheduler_boundary_hash",
        "optional_package_installation_dry_run_execution_worker_image_boundary_hash",
        "worker_image_boundary_chain_hashes_when_present",
        "scheduler_activation_disabled",
        "scheduler_job_creation_disabled",
        "worker_image_resolution_disabled",
        "worker_image_pull_disabled",
        "worker_image_digest_lookup_disabled",
        "tenant_admin_package_install_approval_gate_hash",
        "tenant_admin_package_install_approval_record_hash",
        "restore_drill_evidence_hash",
        "exact_human_confirmation_statement_hash",
        "approval_ticket_ref",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_dry_run_execution_admission_gate_required",
        "no_worker_dispatch_or_execution_confirmation",
        "no_dry_run_result_persistence_confirmation",
    )
    draft = LmsPackageInstallationDryRunExecutionApprovalRecordResponse(
        tenant_id=user_context.tenant_id,
        package_installation_ready=readiness.package_installation_ready,
        dry_run_execution_approval_boundary_evidence_hash=(command.dry_run_execution_approval_boundary_evidence_hash),
        dry_run_execution_scheduler_boundary_evidence_hash=(command.dry_run_execution_scheduler_boundary_evidence_hash),
        dry_run_execution_worker_image_boundary_evidence_hash=(
            command.dry_run_execution_worker_image_boundary_evidence_hash
        ),
        tenant_admin_approval_gate_hash=readiness.tenant_admin_approval_gate_hash or ZERO_SHA256,
        tenant_admin_approval_record_hash=readiness.tenant_admin_approval_record_hash or ZERO_SHA256,
        lms_restore_drill_evidence_hash=readiness.lms_restore_drill_evidence_hash or ZERO_SHA256,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        human_confirmation_statement_hash=human_confirmation_statement_hash,
        dry_run_execution_approval_record_ref=command.dry_run_execution_approval_record_ref,
        approval_ticket_ref=command.approval_ticket_ref,
        human_confirmation_reference=command.human_confirmation_reference,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        approved_by=user_context.user_id,
        approved_at_utc=command.approved_at_utc,
        approver_role_allowed=approver_role_allowed,
        record_status=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_APPROVED
            if approval_record_created
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_STATUS_BLOCKED
        ),
        dry_run_execution_approval_record_created=approval_record_created,
        human_confirmation_captured=True,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
        explicit_human_execution_approval_present=approval_record_created,
        worker_image_boundary_evidence_bound=worker_image_boundary_evidence_bound,
        required_approval_record_evidence=required_approval_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationDryRunExecutionApprovalRecordSummary(
            required_approval_record_evidence_count=len(required_approval_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_scheduler_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_worker_image_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_record.py",
            "app/suite/persistence/migrations/0048_lms_dry_run_execution_approval_records.sql",
            "tests/test_lms_package_installation_dry_run_execution_approval_record.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CREATED_NEXT_ACTION
            if approval_record_created
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_package_installation_dry_run_execution_approval_record_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_approval_record_command_hash(
    command: LmsPackageInstallationDryRunExecutionApprovalRecordCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"human_confirmation_statement"})
    payload["human_confirmation_statement_hash"] = stable_hash(command.human_confirmation_statement)
    return stable_hash(canonical_json(payload))


def build_lms_package_installation_dry_run_execution_approval_record_hash(
    response: LmsPackageInstallationDryRunExecutionApprovalRecordResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _approval_record_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionApprovalRecordCommand,
    package_installation_ready: bool,
    approver_role_allowed: bool,
    human_confirmation_statement_matched: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not package_installation_ready:
        reasons.append("lms_package_installation_readiness_not_ready")
    if command.dry_run_execution_approval_boundary_evidence_hash == ZERO_SHA256:
        reasons.append("package_installation_dry_run_execution_approval_boundary_hash_missing")
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
    if not approver_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.dry_run_execution_approval_record_requested:
        reasons.append("dry_run_execution_approval_record_not_requested")
    if not human_confirmation_statement_matched:
        reasons.append("human_confirmation_statement_mismatch")
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
