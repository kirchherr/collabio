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
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")


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
