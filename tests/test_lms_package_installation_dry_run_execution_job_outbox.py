from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from suite.persistence.migration_catalog import get_migration
from suite.platform.lms_package_installation_dry_run_execution_job_outbox import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_STATEMENT,
    InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore,
    LmsPackageInstallationDryRunExecutionJobOutboxCommand,
    LmsPackageInstallationDryRunExecutionJobOutboxEntry,
    LmsPackageInstallationDryRunExecutionJobStatus,
    LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand,
    build_lms_dry_run_execution_job_outbox_entry,
    build_lms_dry_run_execution_job_outbox_entry_hash,
    build_lms_package_installation_dry_run_execution_job_outbox_list_response,
    build_lms_package_installation_dry_run_execution_job_outbox_response,
    build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response,
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


def _command(**overrides: object) -> LmsPackageInstallationDryRunExecutionJobOutboxCommand:
    payload: dict[str, object] = {
        "dry_run_execution_admission_gate_evidence_hash": ADMISSION_GATE_HASH,
        "dry_run_execution_approval_boundary_evidence_hash": APPROVAL_BOUNDARY_HASH,
        "dry_run_execution_approval_record_hash": APPROVAL_RECORD_HASH,
        "dry_run_execution_scheduler_boundary_evidence_hash": SCHEDULER_BOUNDARY_HASH,
        "dry_run_execution_worker_image_boundary_evidence_hash": WORKER_IMAGE_BOUNDARY_HASH,
        "dry_run_execution_final_readiness_gate_evidence_hash": FINAL_READINESS_HASH,
        "worker_queue_ref": "worker-queue:lms-dry-run-execution",
        "restore_evidence_hash": RESTORE_EVIDENCE_HASH,
        "enqueued_at_utc": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        "max_attempts": 3,
        "change_request_ref": "change:lms-dry-run-job-outbox-unit",
        "idempotency_key_ref": "idempotency:lms-dry-run-job-outbox-unit",
        "audit_chain_ref": "audit:lms-dry-run-job-outbox-unit",
        "job_outbox_statement": LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_STATEMENT,
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionJobOutboxCommand.model_validate(payload)


def _lease_command(**overrides: object) -> LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand:
    payload: dict[str, object] = {
        "lease_owner_ref": "lease-consumer:lms-dry-run-unit",
        "lease_duration_seconds": 120,
        "checked_at_utc": datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-lease-consumer-unit",
        "audit_chain_ref": "audit:lms-dry-run-lease-consumer-unit",
        "lease_consumer_statement": LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_STATEMENT,
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand.model_validate(payload)


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


def test_lms_dry_run_execution_job_outbox_api_response_registers_and_lists_metadata_only_state() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore()

    response = build_lms_package_installation_dry_run_execution_job_outbox_response(
        command=_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    duplicate = build_lms_package_installation_dry_run_execution_job_outbox_response(
        command=_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    tenant_list = build_lms_package_installation_dry_run_execution_job_outbox_list_response(
        tenant_id="tenant-demo",
        store=store,
    )
    other_tenant_list = build_lms_package_installation_dry_run_execution_job_outbox_list_response(
        tenant_id="tenant-other",
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_job_outbox_api.v1"
    assert response.job_outbox_entry_registered is True
    assert response.preparer_role_allowed is True
    assert response.job_outbox_enqueue_requested is True
    assert response.blocking_reasons == ()
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.blocking_reason_count == 0
    assert response.job_outbox_entry.tenant_id == "tenant-demo"
    assert response.job_outbox_entry.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    assert response.job_outbox_entry.worker_dispatch_allowed is False
    assert response.job_outbox_entry.worker_queue_enqueued is False
    assert response.job_outbox_entry.worker_execution_allowed is False
    assert response.job_outbox_entry.dry_run_result_persistence_allowed is False
    assert response.job_outbox_entry.tenant_module_state_created is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.evidence_hash.startswith("sha256:")
    assert duplicate.job_outbox_entry.worker_job_ref == response.job_outbox_entry.worker_job_ref
    assert duplicate.summary.job_outbox_entry_count == 1
    assert tenant_list.job_outbox_entries == (response.job_outbox_entry,)
    assert tenant_list.worker_execution_allowed is False
    assert tenant_list.summary.job_outbox_entry_count == 1
    assert other_tenant_list.job_outbox_entries == ()
    assert other_tenant_list.summary.job_outbox_entry_count == 0


def test_lms_dry_run_execution_outbox_lease_consumer_leases_metadata_only_once() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))

    response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    second_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(checked_at_utc=datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC)),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_lease_consumer.v1"
    assert response.lease_consumer_ready is True
    assert response.outbox_lease_created is True
    assert response.leased_job is not None
    assert response.leased_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.leased_job.lease_owner == "lease-consumer:lms-dry-run-unit"
    assert response.leased_job.lease_id is not None
    assert response.leased_job.attempt_count == 1
    assert response.leased_job.worker_dispatch_allowed is False
    assert response.leased_job.worker_queue_enqueued is False
    assert response.leased_job.worker_execution_allowed is False
    assert response.leased_job.dry_run_result_persistence_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")
    assert second_response.lease_consumer_ready is False
    assert second_response.outbox_lease_created is False
    assert second_response.leased_job is None
    assert "no_lms_dry_run_execution_outbox_entry_available_for_lease" in second_response.blocking_reasons
    assert second_response.summary.job_outbox_entry_count == 1
    assert second_response.summary.leased_job_count == 0


def test_lms_dry_run_execution_outbox_lease_consumer_blocks_worker_requests_before_lease() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))

    response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.lease_consumer_ready is False
    assert response.outbox_lease_created is False
    assert response.leased_job is None
    assert "worker_dispatch_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_admission" in response.blocking_reasons
    assert (
        store.list_jobs(tenant_id="tenant-demo")[0].queue_status
        == LmsPackageInstallationDryRunExecutionJobStatus.QUEUED
    )


def test_lms_dry_run_execution_job_outbox_api_blocks_worker_requests_without_enqueue() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore()

    response = build_lms_package_installation_dry_run_execution_job_outbox_response(
        command=_command(
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.job_outbox_entry_registered is False
    assert "worker_dispatch_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_admission" in response.blocking_reasons
    assert response.summary.job_outbox_entry_count == 0
    assert response.job_outbox_entry.worker_dispatch_allowed is False
    assert response.job_outbox_entry.worker_queue_enqueued is False
    assert response.job_outbox_entry.worker_execution_allowed is False
    assert store.list_jobs(tenant_id="tenant-demo") == ()


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
