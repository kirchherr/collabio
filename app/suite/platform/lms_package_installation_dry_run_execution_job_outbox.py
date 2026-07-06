from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID

LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_SCHEMA_VERSION = (
    "lms_package_installation_dry_run_execution_job_outbox.v1"
)
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_CONTINUITY_DOMAIN = "background_jobs_queues"
LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_REF_PREFIX = "lms-dry-run-execution-job"
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
