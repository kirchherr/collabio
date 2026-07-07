from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID

LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_job_outbox.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN = "background_jobs_queues"
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_REF_PREFIX = "lms-dry-run-execution-job"
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_API_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_job_outbox_api.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_job_outbox_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_LIST_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_job_outbox_list_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_STATEMENT = (
    "I register the LMS package installation dry-run execution job outbox entry without scheduler activation, "
    "worker dispatch, worker queue enqueue, worker execution, dry-run result persistence, or package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_READY_NEXT_ACTION = (
    "inspect_lms_dry_run_execution_job_outbox_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_RETRY_NEXT_ACTION = (
    "prepare_lms_dry_run_execution_job_outbox_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/leases"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_outbox_lease_consumer.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_outbox_lease_consumer_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_STATEMENT = (
    "I lease the next LMS package installation dry-run execution outbox entry for metadata inspection only, "
    "without scheduler activation, worker dispatch, worker queue enqueue, worker execution, "
    "dry-run result persistence, "
    "or package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_READY_NEXT_ACTION = (
    "inspect_lms_dry_run_execution_outbox_leased_state_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_RETRY_NEXT_ACTION = (
    "wait_for_lms_dry_run_execution_outbox_entry_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/retries"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_API_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_outbox_retry_api.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_outbox_retry_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_STATEMENT = (
    "I record the LMS package installation dry-run execution outbox retry state for a leased metadata-only job, "
    "without scheduler activation, worker dispatch, worker queue enqueue, worker execution, "
    "dry-run result persistence, or package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_READY_NEXT_ACTION = (
    "inspect_lms_dry_run_execution_outbox_retry_state_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_REPAIR_NEXT_ACTION = (
    "repair_lms_dry_run_execution_outbox_retry_prerequisites_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/dead-letter-review"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_outbox_dead_letter_review.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_outbox_dead_letter_review_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_STATEMENT = (
    "I review LMS package installation dry-run execution outbox blocked jobs as dead-letter metadata only, "
    "without retry reset, requeue, scheduler activation, worker dispatch, worker execution, "
    "dry-run result persistence, or package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_READY_NEXT_ACTION = (
    "inspect_lms_dry_run_execution_outbox_dead_letter_review_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_REPAIR_NEXT_ACTION = (
    "repair_lms_dry_run_execution_outbox_dead_letter_review_prerequisites_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_ENDPOINT = (
    "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-admission-gate"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_outbox_worker_admission_gate.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_RESULT_CONTRACT = (
    "metadata_only_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_no_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_STATEMENT = (
    "I review LMS package installation dry-run execution outbox leased jobs for worker admission metadata only, "
    "without worker dispatch, worker queue enqueue, worker execution, dry-run result persistence, "
    "tenant module state creation, or package installation."
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_READY_NEXT_ACTION = (
    "inspect_lms_dry_run_execution_outbox_worker_admission_gate_without_worker_execution"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_REPAIR_NEXT_ACTION = (
    "repair_lms_dry_run_execution_outbox_worker_admission_gate_prerequisites_without_worker_execution"
)
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ERROR_TYPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")


class LmsPackageInstallationDryRunExecutionJobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RETRY_SCHEDULED = "retry_scheduled"
    BLOCKED = "blocked"


class LmsPackageInstallationDryRunExecutionJobOutboxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    dry_run_execution_admission_gate_evidence_hash: str
    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_approval_record_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str
    dry_run_execution_worker_image_boundary_evidence_hash: str
    dry_run_execution_final_readiness_gate_evidence_hash: str
    worker_queue_ref: str
    worker_job_ref: str
    worker_idempotency_key_hash: str
    restore_evidence_hash: str
    queue_status: LmsPackageInstallationDryRunExecutionJobStatus = LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    lease_id: str | None = None
    lease_owner: str | None = None
    leased_until_utc: datetime | None = None
    next_attempt_after_utc: datetime
    last_error_type: str | None = None
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    enqueued_at_utc: datetime
    updated_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def require_tenant_bound_metadata_only_outbox_entry(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution job outbox schema version is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution job outbox only applies to lms")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution job outbox continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution job outbox LMS continuity domain is invalid")
        for field_name in (
            "dry_run_execution_admission_gate_evidence_hash",
            "dry_run_execution_approval_boundary_evidence_hash",
            "dry_run_execution_approval_record_hash",
            "dry_run_execution_scheduler_boundary_evidence_hash",
            "dry_run_execution_worker_image_boundary_evidence_hash",
            "dry_run_execution_final_readiness_gate_evidence_hash",
            "worker_idempotency_key_hash",
            "restore_evidence_hash",
            "evidence_hash",
        ):
            value = getattr(self, field_name)
            if not SHA256_PATTERN.fullmatch(value):
                raise ValueError("LMS dry-run execution job outbox hashes must be sha256 references")
        for field_name in ("tenant_id", "worker_queue_ref", "worker_job_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("LMS dry-run execution job outbox text fields must not be empty")
        for field_name in ("worker_queue_ref", "worker_job_ref"):
            if not REF_PATTERN.fullmatch(getattr(self, field_name)):
                raise ValueError("LMS dry-run execution job outbox references must be typed refs")
        if self.lease_id is not None and not REF_PATTERN.fullmatch(self.lease_id):
            raise ValueError("LMS dry-run execution job outbox lease_id must be a typed ref")
        if self.lease_owner is not None and not self.lease_owner.strip():
            raise ValueError("LMS dry-run execution job outbox lease_owner must not be empty")
        if self.last_error_type is not None and not self.last_error_type.strip():
            raise ValueError("LMS dry-run execution job outbox last_error_type must not be empty")
        if self.worker_idempotency_key_hash != build_lms_dry_run_execution_job_idempotency_key_hash(self):
            raise ValueError("LMS dry-run execution job outbox idempotency hash mismatch")
        if self.worker_job_ref != lms_dry_run_execution_job_ref(self.worker_idempotency_key_hash):
            raise ValueError("LMS dry-run execution job outbox job ref mismatch")
        if (
            self.dry_run_execution_admission_gate_evidence_hash == ZERO_SHA256
            or self.dry_run_execution_approval_boundary_evidence_hash == ZERO_SHA256
            or self.dry_run_execution_approval_record_hash == ZERO_SHA256
            or self.dry_run_execution_scheduler_boundary_evidence_hash == ZERO_SHA256
            or self.dry_run_execution_worker_image_boundary_evidence_hash == ZERO_SHA256
            or self.dry_run_execution_final_readiness_gate_evidence_hash == ZERO_SHA256
        ):
            raise ValueError("LMS dry-run execution job outbox requires a complete evidence chain")
        if (
            self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution job outbox must remain non-executing until worker admission opens")
        if self.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED and (
            self.lease_id
            or self.lease_owner
            or self.leased_until_utc
            or self.last_error_type
            or self.attempt_count != 0
        ):
            raise ValueError("queued LMS dry-run execution jobs must not carry lease, error, or attempt state")
        if self.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED:
            if not self.lease_id or not self.lease_owner or self.leased_until_utc is None:
                raise ValueError("leased LMS dry-run execution jobs require lease metadata")
            if self.attempt_count < 1:
                raise ValueError("leased LMS dry-run execution jobs require at least one attempt")
            if self.last_error_type is not None:
                raise ValueError("leased LMS dry-run execution jobs must not carry a retry error")
        if self.queue_status in {
            LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED,
            LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED,
        }:
            if self.lease_id or self.lease_owner or self.leased_until_utc:
                raise ValueError("retry or blocked LMS dry-run execution jobs must not carry active lease metadata")
            if self.attempt_count < 1 or not self.last_error_type:
                raise ValueError("retry or blocked LMS dry-run execution jobs require attempt and error metadata")
        return self


class LmsPackageInstallationDryRunExecutionJobOutboxCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_execution_admission_gate_evidence_hash: str
    dry_run_execution_approval_boundary_evidence_hash: str
    dry_run_execution_approval_record_hash: str
    dry_run_execution_scheduler_boundary_evidence_hash: str
    dry_run_execution_worker_image_boundary_evidence_hash: str
    dry_run_execution_final_readiness_gate_evidence_hash: str
    worker_queue_ref: str
    restore_evidence_hash: str
    enqueued_at_utc: datetime
    max_attempts: int = Field(default=3, ge=1, le=20)
    change_request_ref: str
    idempotency_key_ref: str
    audit_chain_ref: str
    job_outbox_statement: str
    job_outbox_enqueue_requested: bool = True
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "dry_run_execution_admission_gate_evidence_hash",
        "dry_run_execution_approval_boundary_evidence_hash",
        "dry_run_execution_approval_record_hash",
        "dry_run_execution_scheduler_boundary_evidence_hash",
        "dry_run_execution_worker_image_boundary_evidence_hash",
        "dry_run_execution_final_readiness_gate_evidence_hash",
        "restore_evidence_hash",
    )
    @classmethod
    def require_nonzero_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution job outbox hashes must be sha256 references")
        if value == ZERO_SHA256:
            raise ValueError("LMS dry-run execution job outbox requires a complete evidence chain")
        return value

    @field_validator("worker_queue_ref", "change_request_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("LMS dry-run execution job outbox references must use a typed ref prefix")
        return normalized

    @field_validator("job_outbox_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_STATEMENT:
            raise ValueError("LMS dry-run execution job outbox requires the exact metadata-only statement")
        return normalized

    @field_validator("enqueued_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution job outbox enqueued_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionJobOutboxSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_outbox_entry_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionJobOutboxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_API_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    command_hash: str
    idempotency_key_ref_hash: str
    job_outbox_statement_hash: str
    job_outbox_entry_registered: bool
    preparer_role_allowed: bool
    job_outbox_enqueue_requested: bool
    job_outbox_entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionJobOutboxSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_continuity_domain",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution job outbox response text fields must not be empty")
        return value

    @field_validator("command_hash", "idempotency_key_ref_hash", "job_outbox_statement_hash", "evidence_hash")
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution job outbox response hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution job outbox response lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution job outbox response list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_registered_state(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_API_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution job outbox API schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_ENDPOINT:
            raise ValueError("LMS dry-run execution job outbox endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution job outbox result contract is invalid")
        if self.module_id != LMS_MODULE_ID or self.job_outbox_entry.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution job outbox only applies to lms")
        if self.tenant_id != self.job_outbox_entry.tenant_id:
            raise ValueError("LMS dry-run execution job outbox tenant must match the entry tenant")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution job outbox continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution job outbox LMS continuity domain is invalid")
        expected_registered = (
            self.preparer_role_allowed and self.job_outbox_enqueue_requested and not self.blocking_reasons
        )
        if self.job_outbox_entry_registered != expected_registered:
            raise ValueError("LMS dry-run execution job outbox registration flag must match prerequisites")
        if (
            self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution job outbox API must remain metadata-only and non-executing")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution job outbox blocking count must match blocking reasons")
        return self


class LmsPackageInstallationDryRunExecutionJobOutboxListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_API_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_LIST_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    job_outbox_entries: tuple[LmsPackageInstallationDryRunExecutionJobOutboxEntry, ...]
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    dry_run_result_persistence_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    summary: LmsPackageInstallationDryRunExecutionJobOutboxSummary
    evidence_hash: str
    next_action: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_READY_NEXT_ACTION

    @model_validator(mode="after")
    def require_tenant_scoped_metadata_only_list(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_API_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution job outbox list schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_ENDPOINT:
            raise ValueError("LMS dry-run execution job outbox list endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_LIST_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution job outbox list result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution job outbox list only applies to lms")
        if any(entry.tenant_id != self.tenant_id for entry in self.job_outbox_entries):
            raise ValueError("LMS dry-run execution job outbox list must be tenant scoped")
        if (
            self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.package_installation_dry_run_execution_allowed
            or self.dry_run_result_persistence_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution job outbox list must remain metadata-only and non-executing")
        if self.summary.job_outbox_entry_count != len(self.job_outbox_entries):
            raise ValueError("LMS dry-run execution job outbox list count must match entries")
        if self.summary.blocking_reason_count != 0:
            raise ValueError("LMS dry-run execution job outbox list must not carry blocking reasons")
        return self


class LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_owner_ref: str
    lease_duration_seconds: int = Field(default=300, ge=1, le=3600)
    checked_at_utc: datetime
    idempotency_key_ref: str
    audit_chain_ref: str
    lease_consumer_statement: str
    lease_requested: bool = True
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("lease_owner_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("LMS dry-run execution outbox lease consumer references must use a typed ref prefix")
        return normalized

    @field_validator("lease_consumer_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_STATEMENT:
            raise ValueError("LMS dry-run execution outbox lease consumer requires the exact metadata-only statement")
        return normalized

    @field_validator("checked_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution outbox lease consumer checked_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_outbox_entry_count: int
    leased_job_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    command_hash: str
    idempotency_key_ref_hash: str
    lease_consumer_statement_hash: str
    lease_consumer_ready: bool
    lease_requested: bool
    lease_owner_ref: str
    lease_duration_seconds: int
    checked_at_utc: datetime
    leased_job: LmsPackageInstallationDryRunExecutionJobOutboxEntry | None
    outbox_lease_created: bool
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_continuity_domain",
        "lease_owner_ref",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution outbox lease consumer response text fields must not be empty")
        return value

    @field_validator("command_hash", "idempotency_key_ref_hash", "lease_consumer_statement_hash", "evidence_hash")
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution outbox lease consumer response hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution outbox lease consumer response lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution outbox lease consumer response list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_lease_consumer_state(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution outbox lease consumer schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_ENDPOINT:
            raise ValueError("LMS dry-run execution outbox lease consumer endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution outbox lease consumer result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution outbox lease consumer only applies to lms")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox lease consumer continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox lease consumer LMS continuity domain is invalid")
        if self.leased_job is not None and self.leased_job.tenant_id != self.tenant_id:
            raise ValueError("LMS dry-run execution outbox lease consumer job must be tenant scoped")
        if self.lease_consumer_ready != (self.leased_job is not None and not self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox lease consumer readiness must match leased state")
        if self.outbox_lease_created != (self.leased_job is not None):
            raise ValueError("LMS dry-run execution outbox lease created flag must match leased job")
        if self.leased_job is not None:
            if self.leased_job.queue_status != LmsPackageInstallationDryRunExecutionJobStatus.LEASED:
                raise ValueError("LMS dry-run execution outbox lease consumer must return a leased job")
            if self.leased_job.lease_owner != self.lease_owner_ref:
                raise ValueError("LMS dry-run execution outbox lease consumer owner must match leased job")
        if (
            self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution outbox lease consumer must remain metadata-only and non-executing")
        if self.summary.leased_job_count != (1 if self.leased_job is not None else 0):
            raise ValueError("LMS dry-run execution outbox lease consumer leased count must match leased job")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox lease consumer blocking count must match reasons")
        return self


class LmsPackageInstallationDryRunExecutionOutboxRetryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_idempotency_key_hash: str
    lease_id: str
    error_type: str = Field(max_length=120)
    next_attempt_after_utc: datetime
    recorded_at_utc: datetime
    idempotency_key_ref: str
    audit_chain_ref: str
    retry_statement: str
    retry_requested: bool = True
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("worker_idempotency_key_hash")
    @classmethod
    def require_sha256_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution outbox retry worker idempotency must be a sha256 reference")
        return value

    @field_validator("lease_id", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("LMS dry-run execution outbox retry references must use a typed ref prefix")
        return normalized

    @field_validator("error_type")
    @classmethod
    def require_error_type_code(cls, value: str) -> str:
        normalized = value.strip()
        if not ERROR_TYPE_PATTERN.fullmatch(normalized):
            raise ValueError("LMS dry-run execution outbox retry error_type must be a bounded code")
        return normalized

    @field_validator("retry_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_STATEMENT:
            raise ValueError("LMS dry-run execution outbox retry requires the exact metadata-only statement")
        return normalized

    @field_validator("next_attempt_after_utc", "recorded_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution outbox retry timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_retry_schedule_not_in_the_past(self) -> Self:
        if self.next_attempt_after_utc < self.recorded_at_utc:
            raise ValueError("LMS dry-run execution outbox retry next attempt must not precede recorded_at_utc")
        return self


class LmsPackageInstallationDryRunExecutionOutboxRetrySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_outbox_entry_count: int
    retried_job_count: int
    retry_scheduled_job_count: int
    blocked_job_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionOutboxRetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_API_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    command_hash: str
    idempotency_key_ref_hash: str
    retry_statement_hash: str
    worker_idempotency_key_hash: str
    lease_id_hash: str
    error_type: str
    retry_recorded: bool
    retry_requested: bool
    recorded_at_utc: datetime
    next_attempt_after_utc: datetime
    retried_job: LmsPackageInstallationDryRunExecutionJobOutboxEntry | None
    outbox_retry_recorded: bool
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionOutboxRetrySummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_continuity_domain",
        "error_type",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution outbox retry response text fields must not be empty")
        return value

    @field_validator(
        "command_hash",
        "idempotency_key_ref_hash",
        "retry_statement_hash",
        "worker_idempotency_key_hash",
        "lease_id_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution outbox retry response hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution outbox retry response lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution outbox retry response list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_retry_state(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_API_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution outbox retry API schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_ENDPOINT:
            raise ValueError("LMS dry-run execution outbox retry endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution outbox retry result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution outbox retry only applies to lms")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox retry continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox retry LMS continuity domain is invalid")
        if self.retried_job is not None and self.retried_job.tenant_id != self.tenant_id:
            raise ValueError("LMS dry-run execution outbox retry job must be tenant scoped")
        if self.retry_recorded != (self.retried_job is not None and not self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox retry recorded flag must match retried state")
        if self.outbox_retry_recorded != (self.retried_job is not None):
            raise ValueError("LMS dry-run execution outbox retry recorded flag must match retried job")
        if self.retried_job is not None:
            if self.retried_job.worker_idempotency_key_hash != self.worker_idempotency_key_hash:
                raise ValueError("LMS dry-run execution outbox retry worker idempotency must match retried job")
            if self.retried_job.queue_status not in {
                LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED,
                LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED,
            }:
                raise ValueError("LMS dry-run execution outbox retry must return retry or blocked state")
            if self.retried_job.lease_id or self.retried_job.lease_owner or self.retried_job.leased_until_utc:
                raise ValueError("LMS dry-run execution outbox retry must clear active lease metadata")
            if self.retried_job.last_error_type != self.error_type:
                raise ValueError("LMS dry-run execution outbox retry error type must match retried job")
            if self.retried_job.next_attempt_after_utc != self.next_attempt_after_utc:
                raise ValueError("LMS dry-run execution outbox retry schedule must match retried job")
        if (
            self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution outbox retry must remain metadata-only and non-executing")
        if self.summary.retried_job_count != (1 if self.retried_job is not None else 0):
            raise ValueError("LMS dry-run execution outbox retry count must match retried job")
        expected_retry_count = (
            1
            if self.retried_job is not None
            and self.retried_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
            else 0
        )
        expected_blocked_count = (
            1
            if self.retried_job is not None
            and self.retried_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
            else 0
        )
        if self.summary.retry_scheduled_job_count != expected_retry_count:
            raise ValueError("LMS dry-run execution outbox retry scheduled count must match retried job")
        if self.summary.blocked_job_count != expected_blocked_count:
            raise ValueError("LMS dry-run execution outbox retry blocked count must match retried job")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox retry blocking count must match reasons")
        return self


class LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_ref: str
    checked_at_utc: datetime
    idempotency_key_ref: str
    audit_chain_ref: str
    dead_letter_review_statement: str
    review_requested: bool = True
    retry_reset_requested: bool = False
    requeue_requested: bool = False
    dead_letter_release_requested: bool = False
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("reviewer_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("LMS dry-run execution outbox dead-letter review references must use a typed ref prefix")
        return normalized

    @field_validator("dead_letter_review_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_STATEMENT:
            raise ValueError(
                "LMS dry-run execution outbox dead-letter review requires the exact metadata-only statement"
            )
        return normalized

    @field_validator("checked_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS dry-run execution outbox dead-letter review checked_at_utc must include a timezone")
        return value


class LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_outbox_entry_count: int
    blocked_job_count: int
    retry_scheduled_job_count: int
    leased_job_count: int
    queued_job_count: int
    restore_hash_bound_blocked_job_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    command_hash: str
    idempotency_key_ref_hash: str
    dead_letter_review_statement_hash: str
    reviewer_ref: str
    checked_at_utc: datetime
    dead_letter_review_ready: bool
    review_requested: bool
    blocked_jobs: tuple[LmsPackageInstallationDryRunExecutionJobOutboxEntry, ...]
    retry_reset_allowed: bool = False
    requeue_allowed: bool = False
    dead_letter_release_allowed: bool = False
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_continuity_domain",
        "reviewer_ref",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution outbox dead-letter review response text fields must not be empty")
        return value

    @field_validator(
        "command_hash",
        "idempotency_key_ref_hash",
        "dead_letter_review_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError(
                "LMS dry-run execution outbox dead-letter review response hashes must be sha256 references"
            )
        return value

    @field_validator("blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution outbox dead-letter review lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution outbox dead-letter review list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_dead_letter_review_state(self) -> Self:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_SCHEMA_VERSION:
            raise ValueError("LMS dry-run execution outbox dead-letter review schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_ENDPOINT:
            raise ValueError("LMS dry-run execution outbox dead-letter review endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_RESULT_CONTRACT:
            raise ValueError("LMS dry-run execution outbox dead-letter review result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution outbox dead-letter review only applies to lms")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox dead-letter review continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox dead-letter review LMS continuity domain is invalid")
        if any(job.tenant_id != self.tenant_id for job in self.blocked_jobs):
            raise ValueError("LMS dry-run execution outbox dead-letter review must be tenant scoped")
        if any(job.queue_status != LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED for job in self.blocked_jobs):
            raise ValueError("LMS dry-run execution outbox dead-letter review may only include blocked jobs")
        if any(job.lease_id or job.lease_owner or job.leased_until_utc for job in self.blocked_jobs):
            raise ValueError("LMS dry-run execution outbox dead-letter review jobs must not carry active leases")
        if self.dead_letter_review_ready != (self.review_requested and not self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox dead-letter review readiness must match prerequisites")
        if (
            self.retry_reset_allowed
            or self.requeue_allowed
            or self.dead_letter_release_allowed
            or self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError(
                "LMS dry-run execution outbox dead-letter review must remain metadata-only and non-executing"
            )
        if self.summary.blocked_job_count != len(self.blocked_jobs):
            raise ValueError("LMS dry-run execution outbox dead-letter review blocked count must match jobs")
        if self.summary.restore_hash_bound_blocked_job_count != len(self.blocked_jobs):
            raise ValueError("LMS dry-run execution outbox dead-letter review restore count must match blocked jobs")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox dead-letter review blocking count must match reasons")
        return self


class LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_ref: str
    checked_at_utc: datetime
    idempotency_key_ref: str
    audit_chain_ref: str
    worker_admission_gate_statement: str
    worker_admission_review_requested: bool = True
    worker_admission_grant_requested: bool = False
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
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("reviewer_ref", "idempotency_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError(
                "LMS dry-run execution outbox worker admission gate references must use a typed ref prefix"
            )
        return normalized

    @field_validator("worker_admission_gate_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_STATEMENT:
            raise ValueError(
                "LMS dry-run execution outbox worker admission gate requires the exact metadata-only statement"
            )
        return normalized

    @field_validator("checked_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "LMS dry-run execution outbox worker admission gate checked_at_utc must include a timezone"
            )
        return value


class LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_outbox_entry_count: int
    leased_job_count: int
    eligible_leased_job_count: int
    queued_job_count: int
    retry_scheduled_job_count: int
    blocked_job_count: int
    evidence_chain_bound_leased_job_count: int
    restore_hash_bound_leased_job_count: int
    blocking_reason_count: int


class LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_RESULT_CONTRACT
    continuity_domain: str = LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN
    lms_continuity_domain: str = LMS_CONTINUITY_DOMAIN
    command_hash: str
    idempotency_key_ref_hash: str
    worker_admission_gate_statement_hash: str
    reviewer_ref: str
    checked_at_utc: datetime
    worker_admission_gate_ready: bool
    worker_admission_review_requested: bool
    leased_jobs: tuple[LmsPackageInstallationDryRunExecutionJobOutboxEntry, ...]
    worker_admission_granted: bool = False
    scheduler_activation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    package_installation_dry_run_execution_allowed: bool = False
    package_installation_dry_run_executed: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    package_installation_execution_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_continuity_domain",
        "reviewer_ref",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS dry-run execution outbox worker admission gate text fields must not be empty")
        return value

    @field_validator(
        "command_hash",
        "idempotency_key_ref_hash",
        "worker_admission_gate_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS dry-run execution outbox worker admission gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS dry-run execution outbox worker admission gate lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS dry-run execution outbox worker admission gate list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_worker_admission_gate_state(self) -> Self:
        if (
            self.schema_version
            != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_SCHEMA_VERSION
        ):
            raise ValueError("LMS dry-run execution outbox worker admission gate schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_ENDPOINT:
            raise ValueError("LMS dry-run execution outbox worker admission gate endpoint is invalid")
        if (
            self.result_contract
            != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_RESULT_CONTRACT
        ):
            raise ValueError("LMS dry-run execution outbox worker admission gate result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS dry-run execution outbox worker admission gate only applies to lms")
        if self.continuity_domain != LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox worker admission gate continuity domain is invalid")
        if self.lms_continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS dry-run execution outbox worker admission gate LMS continuity domain is invalid")
        if any(job.tenant_id != self.tenant_id for job in self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate must be tenant scoped")
        if any(job.queue_status != LmsPackageInstallationDryRunExecutionJobStatus.LEASED for job in self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate may only include leased jobs")
        if any(not job.lease_id or not job.lease_owner or job.leased_until_utc is None for job in self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate leased jobs require lease metadata")
        if self.worker_admission_gate_ready != (
            self.worker_admission_review_requested and bool(self.leased_jobs) and not self.blocking_reasons
        ):
            raise ValueError("LMS dry-run execution outbox worker admission gate readiness must match prerequisites")
        if (
            self.worker_admission_granted
            or self.scheduler_activation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.package_installation_dry_run_execution_allowed
            or self.package_installation_dry_run_executed
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.package_installation_execution_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS dry-run execution outbox worker admission gate must remain metadata-only")
        if self.summary.leased_job_count != len(self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate leased count must match jobs")
        if self.summary.eligible_leased_job_count != len(self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate eligible count must match jobs")
        if self.summary.evidence_chain_bound_leased_job_count != len(self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate evidence count must match jobs")
        if self.summary.restore_hash_bound_leased_job_count != len(self.leased_jobs):
            raise ValueError("LMS dry-run execution outbox worker admission gate restore count must match jobs")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS dry-run execution outbox worker admission gate blocking count must match reasons")
        return self


class LmsPackageInstallationDryRunExecutionJobOutboxStore(Protocol):
    def enqueue(
        self,
        entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry: ...

    def get(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry: ...

    def list_jobs(self, *, tenant_id: str) -> tuple[LmsPackageInstallationDryRunExecutionJobOutboxEntry, ...]: ...

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry | None: ...

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry: ...


class InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore:
    def __init__(
        self,
        entries: Iterable[LmsPackageInstallationDryRunExecutionJobOutboxEntry] = (),
    ) -> None:
        self._by_tenant_idempotency: dict[tuple[str, str], LmsPackageInstallationDryRunExecutionJobOutboxEntry] = {}
        self._by_tenant_job_ref: dict[tuple[str, str], LmsPackageInstallationDryRunExecutionJobOutboxEntry] = {}
        for entry in entries:
            self.enqueue(entry)

    def enqueue(
        self,
        entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry:
        idempotency_key = (entry.tenant_id, entry.worker_idempotency_key_hash)
        existing_for_idempotency = self._by_tenant_idempotency.get(idempotency_key)
        if existing_for_idempotency is not None:
            return existing_for_idempotency
        job_ref_key = (entry.tenant_id, entry.worker_job_ref)
        if job_ref_key in self._by_tenant_job_ref:
            raise ValueError("LMS dry-run execution job outbox job ref already exists")
        self._by_tenant_idempotency[idempotency_key] = entry
        self._by_tenant_job_ref[job_ref_key] = entry
        return entry

    def get(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry:
        key = (tenant_id, worker_idempotency_key_hash)
        if key not in self._by_tenant_idempotency:
            raise KeyError("LMS dry-run execution job outbox entry not found")
        return self._by_tenant_idempotency[key]

    def list_jobs(self, *, tenant_id: str) -> tuple[LmsPackageInstallationDryRunExecutionJobOutboxEntry, ...]:
        return tuple(
            entry for (entry_tenant, _), entry in self._by_tenant_idempotency.items() if entry_tenant == tenant_id
        )

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry | None:
        now = now or datetime.now(tz=datetime.now().astimezone().tzinfo)
        candidates = sorted(
            (
                entry
                for entry in self.list_jobs(tenant_id=tenant_id)
                if entry.queue_status
                in {
                    LmsPackageInstallationDryRunExecutionJobStatus.QUEUED,
                    LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED,
                }
                and entry.next_attempt_after_utc <= now
            ),
            key=lambda entry: (entry.next_attempt_after_utc, entry.enqueued_at_utc),
        )
        if not candidates:
            return None
        current = candidates[0]
        leased = current.model_copy(
            update={
                "queue_status": LmsPackageInstallationDryRunExecutionJobStatus.LEASED,
                "attempt_count": current.attempt_count + 1,
                "lease_id": f"lease:{uuid4().hex}",
                "lease_owner": lease_owner,
                "leased_until_utc": now + timedelta(seconds=lease_duration_seconds),
                "last_error_type": None,
                "updated_at_utc": now,
                "evidence_hash": ZERO_SHA256,
            }
        )
        leased = leased.model_copy(update={"evidence_hash": build_lms_dry_run_execution_job_outbox_entry_hash(leased)})
        self._replace(leased)
        return leased

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry:
        now = now or datetime.now(tz=datetime.now().astimezone().tzinfo)
        current = self.get(tenant_id=tenant_id, worker_idempotency_key_hash=worker_idempotency_key_hash)
        if current.queue_status != LmsPackageInstallationDryRunExecutionJobStatus.LEASED:
            raise ValueError("LMS dry-run execution job retry requires a leased job")
        if current.lease_id != lease_id:
            raise ValueError("LMS dry-run execution job retry lease mismatch")
        status = (
            LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
            if current.attempt_count >= current.max_attempts
            else LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
        )
        retry = current.model_copy(
            update={
                "queue_status": status,
                "lease_id": None,
                "lease_owner": None,
                "leased_until_utc": None,
                "next_attempt_after_utc": next_attempt_after_utc,
                "last_error_type": error_type,
                "updated_at_utc": now,
                "evidence_hash": ZERO_SHA256,
            }
        )
        retry = retry.model_copy(update={"evidence_hash": build_lms_dry_run_execution_job_outbox_entry_hash(retry)})
        self._replace(retry)
        return retry

    def _replace(self, entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry) -> None:
        self._by_tenant_idempotency[(entry.tenant_id, entry.worker_idempotency_key_hash)] = entry
        self._by_tenant_job_ref[(entry.tenant_id, entry.worker_job_ref)] = entry


def build_lms_dry_run_execution_job_outbox_entry(
    *,
    tenant_id: str,
    dry_run_execution_admission_gate_evidence_hash: str,
    dry_run_execution_approval_boundary_evidence_hash: str,
    dry_run_execution_approval_record_hash: str,
    dry_run_execution_scheduler_boundary_evidence_hash: str,
    dry_run_execution_worker_image_boundary_evidence_hash: str,
    dry_run_execution_final_readiness_gate_evidence_hash: str,
    worker_queue_ref: str,
    restore_evidence_hash: str,
    enqueued_at_utc: datetime,
    max_attempts: int = 3,
) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry:
    worker_idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_execution_job_outbox_idempotency_key.v1",
                "tenant_id": tenant_id,
                "dry_run_execution_admission_gate_evidence_hash": dry_run_execution_admission_gate_evidence_hash,
                "dry_run_execution_approval_boundary_evidence_hash": dry_run_execution_approval_boundary_evidence_hash,
                "dry_run_execution_approval_record_hash": dry_run_execution_approval_record_hash,
                "dry_run_execution_scheduler_boundary_evidence_hash": (
                    dry_run_execution_scheduler_boundary_evidence_hash
                ),
                "dry_run_execution_worker_image_boundary_evidence_hash": (
                    dry_run_execution_worker_image_boundary_evidence_hash
                ),
                "dry_run_execution_final_readiness_gate_evidence_hash": (
                    dry_run_execution_final_readiness_gate_evidence_hash
                ),
                "worker_queue_ref": worker_queue_ref,
            }
        )
    )
    draft = LmsPackageInstallationDryRunExecutionJobOutboxEntry(
        tenant_id=tenant_id,
        dry_run_execution_admission_gate_evidence_hash=dry_run_execution_admission_gate_evidence_hash,
        dry_run_execution_approval_boundary_evidence_hash=dry_run_execution_approval_boundary_evidence_hash,
        dry_run_execution_approval_record_hash=dry_run_execution_approval_record_hash,
        dry_run_execution_scheduler_boundary_evidence_hash=dry_run_execution_scheduler_boundary_evidence_hash,
        dry_run_execution_worker_image_boundary_evidence_hash=dry_run_execution_worker_image_boundary_evidence_hash,
        dry_run_execution_final_readiness_gate_evidence_hash=dry_run_execution_final_readiness_gate_evidence_hash,
        worker_queue_ref=worker_queue_ref,
        worker_job_ref=lms_dry_run_execution_job_ref(worker_idempotency_key_hash),
        worker_idempotency_key_hash=worker_idempotency_key_hash,
        restore_evidence_hash=restore_evidence_hash,
        next_attempt_after_utc=enqueued_at_utc,
        enqueued_at_utc=enqueued_at_utc,
        updated_at_utc=enqueued_at_utc,
        max_attempts=max_attempts,
        evidence_hash=ZERO_SHA256,
    )
    return draft.model_copy(update={"evidence_hash": build_lms_dry_run_execution_job_outbox_entry_hash(draft)})


def build_lms_dry_run_execution_job_idempotency_key_hash(
    entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "schema_version": "lms_package_installation_dry_run_execution_job_outbox_idempotency_key.v1",
                "tenant_id": entry.tenant_id,
                "dry_run_execution_admission_gate_evidence_hash": entry.dry_run_execution_admission_gate_evidence_hash,
                "dry_run_execution_approval_boundary_evidence_hash": (
                    entry.dry_run_execution_approval_boundary_evidence_hash
                ),
                "dry_run_execution_approval_record_hash": entry.dry_run_execution_approval_record_hash,
                "dry_run_execution_scheduler_boundary_evidence_hash": (
                    entry.dry_run_execution_scheduler_boundary_evidence_hash
                ),
                "dry_run_execution_worker_image_boundary_evidence_hash": (
                    entry.dry_run_execution_worker_image_boundary_evidence_hash
                ),
                "dry_run_execution_final_readiness_gate_evidence_hash": (
                    entry.dry_run_execution_final_readiness_gate_evidence_hash
                ),
                "worker_queue_ref": entry.worker_queue_ref,
            }
        )
    )


def lms_dry_run_execution_job_ref(worker_idempotency_key_hash: str) -> str:
    if not SHA256_PATTERN.fullmatch(worker_idempotency_key_hash):
        raise ValueError("LMS dry-run execution job ref requires a sha256 idempotency key")
    return f"{LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_REF_PREFIX}:{worker_idempotency_key_hash}"


def build_lms_dry_run_execution_job_outbox_entry_hash(
    entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry,
) -> str:
    return stable_hash(canonical_json(entry.model_dump(mode="json", exclude={"evidence_hash"})))


def build_default_lms_package_installation_dry_run_execution_job_outbox_store() -> (
    InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore
):
    return InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore()


def build_lms_package_installation_dry_run_execution_job_outbox_response(
    *,
    command: LmsPackageInstallationDryRunExecutionJobOutboxCommand,
    tenant_id: str,
    user_role_ids: set[str],
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionJobOutboxResponse:
    command_hash = build_lms_package_installation_dry_run_execution_job_outbox_command_hash(command)
    idempotency_key_ref_hash = stable_hash(command.idempotency_key_ref)
    job_outbox_statement_hash = stable_hash(command.job_outbox_statement)
    entry = build_lms_dry_run_execution_job_outbox_entry(
        tenant_id=tenant_id,
        dry_run_execution_admission_gate_evidence_hash=command.dry_run_execution_admission_gate_evidence_hash,
        dry_run_execution_approval_boundary_evidence_hash=command.dry_run_execution_approval_boundary_evidence_hash,
        dry_run_execution_approval_record_hash=command.dry_run_execution_approval_record_hash,
        dry_run_execution_scheduler_boundary_evidence_hash=command.dry_run_execution_scheduler_boundary_evidence_hash,
        dry_run_execution_worker_image_boundary_evidence_hash=(
            command.dry_run_execution_worker_image_boundary_evidence_hash
        ),
        dry_run_execution_final_readiness_gate_evidence_hash=(
            command.dry_run_execution_final_readiness_gate_evidence_hash
        ),
        worker_queue_ref=command.worker_queue_ref,
        restore_evidence_hash=command.restore_evidence_hash,
        enqueued_at_utc=command.enqueued_at_utc,
        max_attempts=command.max_attempts,
    )
    preparer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_role_ids)
    blocking_reasons = _job_outbox_blocking_reasons(
        command=command,
        preparer_role_allowed=preparer_role_allowed,
    )
    registered_entry = store.enqueue(entry) if not blocking_reasons else entry
    job_count = len(store.list_jobs(tenant_id=tenant_id))
    draft = LmsPackageInstallationDryRunExecutionJobOutboxResponse(
        tenant_id=tenant_id,
        command_hash=command_hash,
        idempotency_key_ref_hash=idempotency_key_ref_hash,
        job_outbox_statement_hash=job_outbox_statement_hash,
        job_outbox_entry_registered=not blocking_reasons,
        preparer_role_allowed=preparer_role_allowed,
        job_outbox_enqueue_requested=command.job_outbox_enqueue_requested,
        job_outbox_entry=registered_entry,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationDryRunExecutionJobOutboxSummary(
            job_outbox_entry_count=job_count,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "app/suite/persistence/migrations/0049_lms_dry_run_execution_job_outbox.sql",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_api.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_READY_NEXT_ACTION
            if not blocking_reasons
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_dry_run_execution_job_outbox_response_hash(draft)})


def build_lms_package_installation_dry_run_execution_job_outbox_list_response(
    *,
    tenant_id: str,
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionJobOutboxListResponse:
    entries = tuple(sorted(store.list_jobs(tenant_id=tenant_id), key=lambda entry: entry.enqueued_at_utc))
    draft = LmsPackageInstallationDryRunExecutionJobOutboxListResponse(
        tenant_id=tenant_id,
        job_outbox_entries=entries,
        summary=LmsPackageInstallationDryRunExecutionJobOutboxSummary(
            job_outbox_entry_count=len(entries),
            blocking_reason_count=0,
        ),
        evidence_hash=ZERO_SHA256,
    )
    return draft.model_copy(update={"evidence_hash": build_lms_dry_run_execution_job_outbox_list_hash(draft)})


def build_lms_package_installation_dry_run_execution_job_outbox_command_hash(
    command: LmsPackageInstallationDryRunExecutionJobOutboxCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_lms_dry_run_execution_job_outbox_response_hash(
    response: LmsPackageInstallationDryRunExecutionJobOutboxResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def build_lms_dry_run_execution_job_outbox_list_hash(
    response: LmsPackageInstallationDryRunExecutionJobOutboxListResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _job_outbox_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionJobOutboxCommand,
    preparer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not preparer_role_allowed:
        reasons.append("tenant_admin_role_required_for_lms_dry_run_execution_job_outbox")
    if not command.job_outbox_enqueue_requested:
        reasons.append("lms_dry_run_execution_job_outbox_enqueue_not_requested")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_forbidden_until_worker_admission")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_forbidden_until_worker_admission")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_forbidden_until_worker_admission")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_forbidden_until_worker_admission")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_forbidden_until_worker_admission")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_forbidden_until_worker_admission")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_forbidden_until_worker_admission")
    if command.worker_execution_requested:
        reasons.append("worker_execution_forbidden_until_worker_admission")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_forbidden_until_worker_admission")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_forbidden_until_worker_admission")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_forbidden_until_worker_admission")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_forbidden_until_package_installation")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden_in_lms_dry_run_execution_job_outbox")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_forbidden_in_lms_dry_run_execution_job_outbox")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_forbidden_in_lms_dry_run_execution_job_outbox")
    return tuple(reasons)


def build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand,
    tenant_id: str,
    user_role_ids: set[str],
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerResponse:
    command_hash = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_command_hash(command)
    idempotency_key_ref_hash = stable_hash(command.idempotency_key_ref)
    lease_consumer_statement_hash = stable_hash(command.lease_consumer_statement)
    preparer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_role_ids)
    blocking_reasons = list(
        _outbox_lease_consumer_blocking_reasons(
            command=command,
            preparer_role_allowed=preparer_role_allowed,
        )
    )
    leased_job = None
    if not blocking_reasons:
        leased_job = store.lease_next(
            tenant_id=tenant_id,
            lease_owner=command.lease_owner_ref,
            lease_duration_seconds=command.lease_duration_seconds,
            now=command.checked_at_utc,
        )
        if leased_job is None:
            blocking_reasons.append("no_lms_dry_run_execution_outbox_entry_available_for_lease")
    job_count = len(store.list_jobs(tenant_id=tenant_id))
    draft = LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerResponse(
        tenant_id=tenant_id,
        command_hash=command_hash,
        idempotency_key_ref_hash=idempotency_key_ref_hash,
        lease_consumer_statement_hash=lease_consumer_statement_hash,
        lease_consumer_ready=leased_job is not None and not blocking_reasons,
        lease_requested=command.lease_requested,
        lease_owner_ref=command.lease_owner_ref,
        lease_duration_seconds=command.lease_duration_seconds,
        checked_at_utc=command.checked_at_utc,
        leased_job=leased_job,
        outbox_lease_created=leased_job is not None,
        blocking_reasons=tuple(blocking_reasons),
        summary=LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerSummary(
            job_outbox_entry_count=job_count,
            leased_job_count=1 if leased_job is not None else 0,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_api.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_READY_NEXT_ACTION
            if leased_job is not None and not blocking_reasons
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_dry_run_execution_outbox_lease_consumer_response_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_outbox_lease_consumer_command_hash(
    command: LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_lms_dry_run_execution_outbox_lease_consumer_response_hash(
    response: LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _outbox_lease_consumer_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand,
    preparer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not preparer_role_allowed:
        reasons.append("tenant_admin_role_required_for_lms_dry_run_execution_outbox_lease_consumer")
    if not command.lease_requested:
        reasons.append("lms_dry_run_execution_outbox_lease_not_requested")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_forbidden_until_worker_admission")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_forbidden_until_worker_admission")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_forbidden_until_worker_admission")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_forbidden_until_worker_admission")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_forbidden_until_worker_admission")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_forbidden_until_worker_admission")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_forbidden_until_worker_admission")
    if command.worker_execution_requested:
        reasons.append("worker_execution_forbidden_until_worker_admission")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_forbidden_until_worker_admission")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_forbidden_until_worker_admission")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_forbidden_until_worker_admission")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_forbidden_until_package_installation")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden_in_lms_dry_run_execution_outbox_lease_consumer")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_forbidden_in_lms_dry_run_execution_outbox_lease_consumer")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_forbidden_in_lms_dry_run_execution_outbox_lease_consumer")
    return tuple(reasons)


def build_lms_package_installation_dry_run_execution_outbox_retry_response(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxRetryCommand,
    tenant_id: str,
    user_role_ids: set[str],
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionOutboxRetryResponse:
    command_hash = build_lms_package_installation_dry_run_execution_outbox_retry_command_hash(command)
    idempotency_key_ref_hash = stable_hash(command.idempotency_key_ref)
    retry_statement_hash = stable_hash(command.retry_statement)
    lease_id_hash = stable_hash(command.lease_id)
    preparer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_role_ids)
    blocking_reasons = list(
        _outbox_retry_blocking_reasons(command=command, preparer_role_allowed=preparer_role_allowed)
    )
    retried_job = None
    if not blocking_reasons:
        try:
            current = store.get(
                tenant_id=tenant_id,
                worker_idempotency_key_hash=command.worker_idempotency_key_hash,
            )
        except KeyError:
            blocking_reasons.append("lms_dry_run_execution_outbox_retry_job_not_found")
        else:
            if current.queue_status != LmsPackageInstallationDryRunExecutionJobStatus.LEASED:
                blocking_reasons.append("lms_dry_run_execution_outbox_retry_requires_leased_job")
            elif current.lease_id != command.lease_id:
                blocking_reasons.append("lms_dry_run_execution_outbox_retry_lease_mismatch")
            else:
                try:
                    retried_job = store.record_retry(
                        tenant_id=tenant_id,
                        worker_idempotency_key_hash=command.worker_idempotency_key_hash,
                        lease_id=command.lease_id,
                        error_type=command.error_type,
                        next_attempt_after_utc=command.next_attempt_after_utc,
                        now=command.recorded_at_utc,
                    )
                except ValueError:
                    blocking_reasons.append("lms_dry_run_execution_outbox_retry_state_conflict")
    job_count = len(store.list_jobs(tenant_id=tenant_id))
    retry_scheduled_job_count = (
        1
        if retried_job is not None
        and retried_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
        else 0
    )
    blocked_job_count = (
        1
        if retried_job is not None
        and retried_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
        else 0
    )
    draft = LmsPackageInstallationDryRunExecutionOutboxRetryResponse(
        tenant_id=tenant_id,
        command_hash=command_hash,
        idempotency_key_ref_hash=idempotency_key_ref_hash,
        retry_statement_hash=retry_statement_hash,
        worker_idempotency_key_hash=command.worker_idempotency_key_hash,
        lease_id_hash=lease_id_hash,
        error_type=command.error_type,
        retry_recorded=retried_job is not None and not blocking_reasons,
        retry_requested=command.retry_requested,
        recorded_at_utc=command.recorded_at_utc,
        next_attempt_after_utc=command.next_attempt_after_utc,
        retried_job=retried_job,
        outbox_retry_recorded=retried_job is not None,
        blocking_reasons=tuple(blocking_reasons),
        summary=LmsPackageInstallationDryRunExecutionOutboxRetrySummary(
            job_outbox_entry_count=job_count,
            retried_job_count=1 if retried_job is not None else 0,
            retry_scheduled_job_count=retry_scheduled_job_count,
            blocked_job_count=blocked_job_count,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_api.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_READY_NEXT_ACTION
            if retried_job is not None and not blocking_reasons
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_REPAIR_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_dry_run_execution_outbox_retry_response_hash(draft)})


def build_lms_package_installation_dry_run_execution_outbox_retry_command_hash(
    command: LmsPackageInstallationDryRunExecutionOutboxRetryCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_lms_dry_run_execution_outbox_retry_response_hash(
    response: LmsPackageInstallationDryRunExecutionOutboxRetryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _outbox_retry_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxRetryCommand,
    preparer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not preparer_role_allowed:
        reasons.append("tenant_admin_role_required_for_lms_dry_run_execution_outbox_retry")
    if not command.retry_requested:
        reasons.append("lms_dry_run_execution_outbox_retry_not_requested")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_forbidden_until_worker_admission")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_forbidden_until_worker_admission")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_forbidden_until_worker_admission")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_forbidden_until_worker_admission")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_forbidden_until_worker_admission")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_forbidden_until_worker_admission")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_forbidden_until_worker_admission")
    if command.worker_execution_requested:
        reasons.append("worker_execution_forbidden_until_worker_admission")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_forbidden_until_worker_admission")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_forbidden_until_worker_admission")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_forbidden_until_worker_admission")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_forbidden_until_package_installation")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden_in_lms_dry_run_execution_outbox_retry")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_forbidden_in_lms_dry_run_execution_outbox_retry")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_forbidden_in_lms_dry_run_execution_outbox_retry")
    return tuple(reasons)


def build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_response(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand,
    tenant_id: str,
    user_role_ids: set[str],
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewResponse:
    command_hash = build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_command_hash(command)
    idempotency_key_ref_hash = stable_hash(command.idempotency_key_ref)
    review_statement_hash = stable_hash(command.dead_letter_review_statement)
    reviewer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_role_ids)
    blocking_reasons = list(
        _outbox_dead_letter_review_blocking_reasons(
            command=command,
            reviewer_role_allowed=reviewer_role_allowed,
        )
    )
    jobs = store.list_jobs(tenant_id=tenant_id)
    blocked_jobs = tuple(
        job for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
    )
    retry_scheduled_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
    )
    leased_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    )
    queued_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    )
    restore_hash_bound_blocked_job_count = sum(
        1 for job in blocked_jobs if SHA256_PATTERN.fullmatch(job.restore_evidence_hash)
    )
    if restore_hash_bound_blocked_job_count != len(blocked_jobs):
        blocking_reasons.append("lms_dry_run_execution_outbox_dead_letter_restore_evidence_unbound")
    draft = LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewResponse(
        tenant_id=tenant_id,
        command_hash=command_hash,
        idempotency_key_ref_hash=idempotency_key_ref_hash,
        dead_letter_review_statement_hash=review_statement_hash,
        reviewer_ref=command.reviewer_ref,
        checked_at_utc=command.checked_at_utc,
        dead_letter_review_ready=command.review_requested and not blocking_reasons,
        review_requested=command.review_requested,
        blocked_jobs=blocked_jobs,
        blocking_reasons=tuple(blocking_reasons),
        summary=LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewSummary(
            job_outbox_entry_count=len(jobs),
            blocked_job_count=len(blocked_jobs),
            retry_scheduled_job_count=retry_scheduled_job_count,
            leased_job_count=leased_job_count,
            queued_job_count=queued_job_count,
            restore_hash_bound_blocked_job_count=restore_hash_bound_blocked_job_count,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_api.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_READY_NEXT_ACTION
            if command.review_requested and not blocking_reasons
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_REPAIR_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_dry_run_execution_outbox_dead_letter_review_response_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_command_hash(
    command: LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_lms_dry_run_execution_outbox_dead_letter_review_response_hash(
    response: LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _outbox_dead_letter_review_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand,
    reviewer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not reviewer_role_allowed:
        reasons.append("tenant_admin_role_required_for_lms_dry_run_execution_outbox_dead_letter_review")
    if not command.review_requested:
        reasons.append("lms_dry_run_execution_outbox_dead_letter_review_not_requested")
    if command.retry_reset_requested:
        reasons.append("retry_reset_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    if command.requeue_requested:
        reasons.append("requeue_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    if command.dead_letter_release_requested:
        reasons.append("dead_letter_release_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_forbidden_until_worker_admission")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_forbidden_until_worker_admission")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_forbidden_until_worker_admission")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_forbidden_until_worker_admission")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_forbidden_until_worker_admission")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_forbidden_until_worker_admission")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_forbidden_until_worker_admission")
    if command.worker_execution_requested:
        reasons.append("worker_execution_forbidden_until_worker_admission")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_forbidden_until_worker_admission")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_forbidden_until_worker_admission")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_forbidden_until_worker_admission")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_forbidden_until_package_installation")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review")
    return tuple(reasons)


def build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_response(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand,
    tenant_id: str,
    user_role_ids: set[str],
    store: LmsPackageInstallationDryRunExecutionJobOutboxStore,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateResponse:
    command_hash = build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_command_hash(command)
    idempotency_key_ref_hash = stable_hash(command.idempotency_key_ref)
    statement_hash = stable_hash(command.worker_admission_gate_statement)
    reviewer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_role_ids)
    blocking_reasons = list(
        _outbox_worker_admission_gate_blocking_reasons(
            command=command,
            reviewer_role_allowed=reviewer_role_allowed,
        )
    )
    jobs = store.list_jobs(tenant_id=tenant_id)
    leased_jobs = tuple(
        job for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    )
    queued_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    )
    retry_scheduled_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
    )
    blocked_job_count = sum(
        1 for job in jobs if job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
    )
    evidence_chain_bound_leased_job_count = sum(1 for job in leased_jobs if _job_outbox_evidence_chain_bound(job))
    restore_hash_bound_leased_job_count = sum(
        1 for job in leased_jobs if SHA256_PATTERN.fullmatch(job.restore_evidence_hash)
    )
    if not leased_jobs:
        blocking_reasons.append("no_lms_dry_run_execution_outbox_leased_job_available_for_worker_admission_gate")
    if evidence_chain_bound_leased_job_count != len(leased_jobs):
        blocking_reasons.append("lms_dry_run_execution_outbox_worker_admission_evidence_chain_unbound")
    if restore_hash_bound_leased_job_count != len(leased_jobs):
        blocking_reasons.append("lms_dry_run_execution_outbox_worker_admission_restore_evidence_unbound")
    draft = LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateResponse(
        tenant_id=tenant_id,
        command_hash=command_hash,
        idempotency_key_ref_hash=idempotency_key_ref_hash,
        worker_admission_gate_statement_hash=statement_hash,
        reviewer_ref=command.reviewer_ref,
        checked_at_utc=command.checked_at_utc,
        worker_admission_gate_ready=command.worker_admission_review_requested
        and bool(leased_jobs)
        and not blocking_reasons,
        worker_admission_review_requested=command.worker_admission_review_requested,
        leased_jobs=leased_jobs,
        blocking_reasons=tuple(blocking_reasons),
        summary=LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateSummary(
            job_outbox_entry_count=len(jobs),
            leased_job_count=len(leased_jobs),
            eligible_leased_job_count=len(leased_jobs),
            queued_job_count=queued_job_count,
            retry_scheduled_job_count=retry_scheduled_job_count,
            blocked_job_count=blocked_job_count,
            evidence_chain_bound_leased_job_count=evidence_chain_bound_leased_job_count,
            restore_hash_bound_leased_job_count=restore_hash_bound_leased_job_count,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
            "tests/test_api.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_READY_NEXT_ACTION
            if command.worker_admission_review_requested and bool(leased_jobs) and not blocking_reasons
            else LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_REPAIR_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_lms_dry_run_execution_outbox_worker_admission_gate_response_hash(draft)}
    )


def build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_command_hash(
    command: LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_lms_dry_run_execution_outbox_worker_admission_gate_response_hash(
    response: LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _job_outbox_evidence_chain_bound(entry: LmsPackageInstallationDryRunExecutionJobOutboxEntry) -> bool:
    return all(
        SHA256_PATTERN.fullmatch(value) and value != ZERO_SHA256
        for value in (
            entry.dry_run_execution_admission_gate_evidence_hash,
            entry.dry_run_execution_approval_boundary_evidence_hash,
            entry.dry_run_execution_approval_record_hash,
            entry.dry_run_execution_scheduler_boundary_evidence_hash,
            entry.dry_run_execution_worker_image_boundary_evidence_hash,
            entry.dry_run_execution_final_readiness_gate_evidence_hash,
            entry.worker_idempotency_key_hash,
            entry.restore_evidence_hash,
            entry.evidence_hash,
        )
    )


def _outbox_worker_admission_gate_blocking_reasons(
    *,
    command: LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand,
    reviewer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not reviewer_role_allowed:
        reasons.append("tenant_admin_role_required_for_lms_dry_run_execution_outbox_worker_admission_gate")
    if not command.worker_admission_review_requested:
        reasons.append("lms_dry_run_execution_outbox_worker_admission_gate_review_not_requested")
    if command.worker_admission_grant_requested:
        reasons.append("worker_admission_grant_forbidden_without_separate_worker_enablement")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_forbidden_until_worker_admission")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_forbidden_until_worker_admission")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_forbidden_until_worker_admission")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_forbidden_until_worker_admission")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_forbidden_until_worker_admission")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_forbidden_until_worker_admission")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_forbidden_until_worker_admission")
    if command.worker_execution_requested:
        reasons.append("worker_execution_forbidden_until_worker_admission")
    if command.package_installation_dry_run_execution_requested:
        reasons.append("package_installation_dry_run_execution_forbidden_until_worker_admission")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_forbidden_until_worker_admission")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_forbidden_until_worker_admission")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_forbidden_until_package_installation")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden_in_lms_dry_run_execution_outbox_worker_admission_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_forbidden_in_lms_dry_run_execution_outbox_worker_admission_gate")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_forbidden_in_lms_dry_run_execution_outbox_worker_admission_gate")
    return tuple(reasons)
