from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from suite.persistence.migration_catalog import get_migration
from suite.platform.lms_package_installation_dry_run_execution_job_outbox import (
    InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore,
    LmsPackageInstallationDryRunExecutionJobOutboxEntry,
    LmsPackageInstallationDryRunExecutionJobStatus,
    build_lms_dry_run_execution_job_outbox_entry,
    build_lms_dry_run_execution_job_outbox_entry_hash,
)

ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
ADMISSION_GATE_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
APPROVAL_BOUNDARY_HASH = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
APPROVAL_RECORD_HASH = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
SCHEDULER_BOUNDARY_HASH = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
WORKER_IMAGE_BOUNDARY_HASH = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
FINAL_READINESS_HASH = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
RESTORE_EVIDENCE_HASH = "sha256:1111111111111111111111111111111111111111111111111111111111111111"


def _job(
    *, tenant_id: str = "tenant-demo", max_attempts: int = 3
) -> LmsPackageInstallationDryRunExecutionJobOutboxEntry:
    return build_lms_dry_run_execution_job_outbox_entry(
        tenant_id=tenant_id,
        dry_run_execution_admission_gate_evidence_hash=ADMISSION_GATE_HASH,
        dry_run_execution_approval_boundary_evidence_hash=APPROVAL_BOUNDARY_HASH,
        dry_run_execution_approval_record_hash=APPROVAL_RECORD_HASH,
        dry_run_execution_scheduler_boundary_evidence_hash=SCHEDULER_BOUNDARY_HASH,
        dry_run_execution_worker_image_boundary_evidence_hash=WORKER_IMAGE_BOUNDARY_HASH,
        dry_run_execution_final_readiness_gate_evidence_hash=FINAL_READINESS_HASH,
        worker_queue_ref="worker-queue:lms-dry-run-execution",
        restore_evidence_hash=RESTORE_EVIDENCE_HASH,
        enqueued_at_utc=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        max_attempts=max_attempts,
    )


def test_lms_dry_run_execution_job_outbox_is_idempotent_tenant_scoped_and_retriable() -> None:
    job = _job()
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore()

    persisted = store.enqueue(job)
    duplicate = store.enqueue(job)
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="worker-test",
        lease_duration_seconds=60,
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    retry = store.record_retry(
        tenant_id="tenant-demo",
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id or "",
        error_type="worker-not-enabled-yet",
        next_attempt_after_utc=datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
        now=datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC),
    )

    assert duplicate == persisted
    assert len(store.list_jobs(tenant_id="tenant-demo")) == 1
    assert store.list_jobs(tenant_id="tenant-other") == ()
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    assert leased.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert leased.attempt_count == 1
    assert leased.lease_id is not None
    assert retry.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
    assert retry.last_error_type == "worker-not-enabled-yet"
    assert retry.restore_evidence_hash == RESTORE_EVIDENCE_HASH
    assert retry.evidence_hash == build_lms_dry_run_execution_job_outbox_entry_hash(retry)

    payload = retry.model_dump_json().lower()
    assert "human_confirmation_statement" not in payload
    assert "dry_run_result_payload" not in payload
    assert "course_payload" not in payload
    assert 'worker_executed":true' not in payload


def test_lms_dry_run_execution_job_outbox_blocks_incomplete_evidence_or_execution_flags() -> None:
    with pytest.raises(ValidationError, match="complete evidence chain"):
        build_lms_dry_run_execution_job_outbox_entry(
            tenant_id="tenant-demo",
            dry_run_execution_admission_gate_evidence_hash=ADMISSION_GATE_HASH,
            dry_run_execution_approval_boundary_evidence_hash=APPROVAL_BOUNDARY_HASH,
            dry_run_execution_approval_record_hash=APPROVAL_RECORD_HASH,
            dry_run_execution_scheduler_boundary_evidence_hash=ZERO_SHA256,
            dry_run_execution_worker_image_boundary_evidence_hash=WORKER_IMAGE_BOUNDARY_HASH,
            dry_run_execution_final_readiness_gate_evidence_hash=FINAL_READINESS_HASH,
            worker_queue_ref="worker-queue:lms-dry-run-execution",
            restore_evidence_hash=RESTORE_EVIDENCE_HASH,
            enqueued_at_utc=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        )

    job = _job().model_copy(update={"worker_execution_allowed": True})
    with pytest.raises(ValidationError, match="non-executing"):
        type(job).model_validate(job.model_dump())


def test_lms_dry_run_execution_job_outbox_blocks_after_max_attempts() -> None:
    job = _job(max_attempts=1)
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((job,))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="worker-test",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None

    blocked = store.record_retry(
        tenant_id="tenant-demo",
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id or "",
        error_type="worker-not-enabled-yet",
        next_attempt_after_utc=datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
        now=datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC),
    )

    assert blocked.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
    assert blocked.last_error_type == "worker-not-enabled-yet"
    assert blocked.worker_execution_allowed is False
    assert blocked.dry_run_result_persistence_allowed is False


def test_lms_dry_run_execution_job_outbox_migration_declares_rls_and_metadata_only_state() -> None:
    migration = get_migration("0049")
    sql = " ".join(migration.sql().lower().split())

    assert migration.module_id == "lms"
    assert "create table if not exists lms.dry_run_execution_job_outbox" in sql
    assert "lms_package_installation_dry_run_execution_job_outbox.v1" in sql
    assert (
        "queue_status text not null check (queue_status in ('queued', 'leased', 'retry_scheduled', 'blocked'))" in sql
    )
    assert "dry_run_execution_worker_image_boundary_evidence_hash text not null" in sql
    assert "dry_run_execution_final_readiness_gate_evidence_hash text not null" in sql
    assert "worker_idempotency_key_hash text not null" in sql
    assert "restore_evidence_hash text not null" in sql
    assert "worker_execution_allowed boolean not null default false check (worker_execution_allowed = false)" in sql
    assert "dry_run_result_persistence_allowed boolean not null default false check" in sql
    assert "not (job_evidence ? 'human_confirmation_statement')" in sql
    assert "not (job_evidence ? 'dry_run_result_payload')" in sql
    assert "alter table lms.dry_run_execution_job_outbox enable row level security" in sql
    assert "alter table lms.dry_run_execution_job_outbox force row level security" in sql
    assert "create policy lms_dry_run_execution_job_outbox_tenant_select" in sql
    assert "create policy lms_dry_run_execution_job_outbox_tenant_insert" in sql
    assert "create policy lms_dry_run_execution_job_outbox_tenant_lease_retry_update" in sql
    assert "create policy lms_dry_run_execution_job_outbox_no_hard_delete" in sql
    assert "grant update (" in sql
