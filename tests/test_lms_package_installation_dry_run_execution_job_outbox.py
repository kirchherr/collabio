from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from suite.persistence.migration_catalog import get_migration
from suite.platform.lms_package_installation_dry_run_execution_job_outbox import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_JOB_OUTBOX_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_LEASE_CONSUMER_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_DISPATCH_ADMISSION_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_QUEUE_ADMISSION_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_RECEIPT_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_RESULT_STUB_STATEMENT,
    InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore,
    LmsPackageInstallationDryRunExecutionJobOutboxCommand,
    LmsPackageInstallationDryRunExecutionJobOutboxEntry,
    LmsPackageInstallationDryRunExecutionJobStatus,
    LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand,
    LmsPackageInstallationDryRunExecutionOutboxLeaseConsumerCommand,
    LmsPackageInstallationDryRunExecutionOutboxRetryCommand,
    LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand,
    LmsPackageInstallationDryRunExecutionOutboxWorkerDispatchAdmissionCommand,
    LmsPackageInstallationDryRunExecutionOutboxWorkerQueueAdmissionCommand,
    LmsPackageInstallationDryRunExecutionOutboxWorkerReceiptCommand,
    LmsPackageInstallationDryRunExecutionOutboxWorkerResultStubCommand,
    build_lms_dry_run_execution_job_outbox_entry,
    build_lms_dry_run_execution_job_outbox_entry_hash,
    build_lms_package_installation_dry_run_execution_job_outbox_list_response,
    build_lms_package_installation_dry_run_execution_job_outbox_response,
    build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_response,
    build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response,
    build_lms_package_installation_dry_run_execution_outbox_retry_response,
    build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_response,
    build_lms_package_installation_dry_run_execution_outbox_worker_dispatch_admission_response,
    build_lms_package_installation_dry_run_execution_outbox_worker_queue_admission_response,
    build_lms_package_installation_dry_run_execution_outbox_worker_receipt_response,
    build_lms_package_installation_dry_run_execution_outbox_worker_result_stub_response,
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


def _retry_command(
    *,
    worker_idempotency_key_hash: str,
    lease_id: str,
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxRetryCommand:
    payload: dict[str, object] = {
        "worker_idempotency_key_hash": worker_idempotency_key_hash,
        "lease_id": lease_id,
        "error_type": "worker-not-enabled-yet",
        "next_attempt_after_utc": datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
        "recorded_at_utc": datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-retry-unit",
        "audit_chain_ref": "audit:lms-dry-run-retry-unit",
        "retry_statement": LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_RETRY_STATEMENT,
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxRetryCommand.model_validate(payload)


def _dead_letter_review_command(
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand:
    payload: dict[str, object] = {
        "reviewer_ref": "reviewer:lms-dry-run-dead-letter-unit",
        "checked_at_utc": datetime(2026, 6, 30, 12, 10, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-dead-letter-review-unit",
        "audit_chain_ref": "audit:lms-dry-run-dead-letter-review-unit",
        "dead_letter_review_statement": LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_DEAD_LETTER_REVIEW_STATEMENT,
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxDeadLetterReviewCommand.model_validate(payload)


def _worker_admission_gate_command(
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand:
    payload: dict[str, object] = {
        "reviewer_ref": "reviewer:lms-dry-run-worker-admission-unit",
        "checked_at_utc": datetime(2026, 6, 30, 12, 15, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-worker-admission-unit",
        "audit_chain_ref": "audit:lms-dry-run-worker-admission-unit",
        "worker_admission_gate_statement": (
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_ADMISSION_GATE_STATEMENT
        ),
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxWorkerAdmissionGateCommand.model_validate(payload)


def _worker_dispatch_admission_command(
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerDispatchAdmissionCommand:
    payload: dict[str, object] = {
        "reviewer_ref": "reviewer:lms-dry-run-worker-dispatch-admission-unit",
        "checked_at_utc": datetime(2026, 6, 30, 12, 20, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-worker-dispatch-admission-unit",
        "audit_chain_ref": "audit:lms-dry-run-worker-dispatch-admission-unit",
        "worker_dispatch_admission_statement": (
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_DISPATCH_ADMISSION_STATEMENT
        ),
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxWorkerDispatchAdmissionCommand.model_validate(payload)


def _worker_queue_admission_command(
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerQueueAdmissionCommand:
    payload: dict[str, object] = {
        "reviewer_ref": "reviewer:lms-dry-run-worker-queue-admission-unit",
        "checked_at_utc": datetime(2026, 6, 30, 12, 25, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-worker-queue-admission-unit",
        "audit_chain_ref": "audit:lms-dry-run-worker-queue-admission-unit",
        "worker_queue_admission_statement": (
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_QUEUE_ADMISSION_STATEMENT
        ),
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxWorkerQueueAdmissionCommand.model_validate(payload)


def _worker_receipt_command(
    *,
    worker_idempotency_key_hash: str,
    lease_id: str,
    worker_ref: str = "lease-consumer:lms-dry-run-unit",
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerReceiptCommand:
    payload: dict[str, object] = {
        "worker_idempotency_key_hash": worker_idempotency_key_hash,
        "lease_id": lease_id,
        "worker_ref": worker_ref,
        "checked_at_utc": datetime(2026, 6, 30, 12, 30, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-worker-receipt-unit",
        "audit_chain_ref": "audit:lms-dry-run-worker-receipt-unit",
        "worker_receipt_statement": LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_RECEIPT_STATEMENT,
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxWorkerReceiptCommand.model_validate(payload)


def _worker_result_stub_command(
    *,
    worker_idempotency_key_hash: str,
    lease_id: str,
    worker_receipt_ref: str,
    worker_ref: str = "lease-consumer:lms-dry-run-unit",
    worker_receipt_idempotency_key_ref: str = "idempotency:lms-dry-run-worker-receipt-unit",
    **overrides: object,
) -> LmsPackageInstallationDryRunExecutionOutboxWorkerResultStubCommand:
    payload: dict[str, object] = {
        "worker_idempotency_key_hash": worker_idempotency_key_hash,
        "lease_id": lease_id,
        "worker_ref": worker_ref,
        "worker_receipt_ref": worker_receipt_ref,
        "worker_receipt_idempotency_key_ref": worker_receipt_idempotency_key_ref,
        "checked_at_utc": datetime(2026, 6, 30, 12, 35, tzinfo=UTC),
        "idempotency_key_ref": "idempotency:lms-dry-run-worker-result-stub-unit",
        "audit_chain_ref": "audit:lms-dry-run-worker-result-stub-unit",
        "worker_result_stub_statement": (
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_OUTBOX_WORKER_RESULT_STUB_STATEMENT
        ),
    }
    payload.update(overrides)
    return LmsPackageInstallationDryRunExecutionOutboxWorkerResultStubCommand.model_validate(payload)


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


def test_lms_dry_run_execution_outbox_retry_api_records_metadata_only_retry_state() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None
    assert leased.lease_id is not None

    response = build_lms_package_installation_dry_run_execution_outbox_retry_response(
        command=_retry_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_retry_api.v1"
    assert response.retry_recorded is True
    assert response.outbox_retry_recorded is True
    assert response.retry_requested is True
    assert response.retried_job is not None
    assert response.retried_job.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.RETRY_SCHEDULED
    assert response.retried_job.lease_id is None
    assert response.retried_job.lease_owner is None
    assert response.retried_job.leased_until_utc is None
    assert response.retried_job.last_error_type == "worker-not-enabled-yet"
    assert response.retried_job.attempt_count == 1
    assert response.retried_job.worker_dispatch_allowed is False
    assert response.retried_job.worker_queue_enqueued is False
    assert response.retried_job.worker_execution_allowed is False
    assert response.retried_job.dry_run_result_persistence_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.retried_job_count == 1
    assert response.summary.retry_scheduled_job_count == 1
    assert response.summary.blocked_job_count == 0
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")


def test_lms_dry_run_execution_outbox_retry_api_blocks_worker_requests_before_retry() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    assert leased.lease_id is not None

    response = build_lms_package_installation_dry_run_execution_outbox_retry_response(
        command=_retry_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.retry_recorded is False
    assert response.outbox_retry_recorded is False
    assert response.retried_job is None
    assert "worker_dispatch_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_admission" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


def test_lms_dry_run_execution_outbox_dead_letter_review_api_reports_blocked_jobs() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(max_attempts=1),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-dead-letter-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    assert leased.lease_id is not None
    blocked = store.record_retry(
        tenant_id="tenant-demo",
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id,
        error_type="worker-not-enabled-yet",
        next_attempt_after_utc=datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
        now=datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC),
    )
    assert blocked.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED

    response = build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_response(
        command=_dead_letter_review_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_dead_letter_review.v1"
    assert response.dead_letter_review_ready is True
    assert response.review_requested is True
    assert response.blocking_reasons == ()
    assert response.blocked_jobs == (blocked,)
    assert response.blocked_jobs[0].queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED
    assert response.blocked_jobs[0].restore_evidence_hash == RESTORE_EVIDENCE_HASH
    assert response.retry_reset_allowed is False
    assert response.requeue_allowed is False
    assert response.dead_letter_release_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.blocked_job_count == 1
    assert response.summary.restore_hash_bound_blocked_job_count == 1
    assert response.summary.retry_scheduled_job_count == 0
    assert response.summary.leased_job_count == 0
    assert response.summary.queued_job_count == 0
    assert response.evidence_hash.startswith("sha256:")


def test_lms_dry_run_execution_outbox_dead_letter_review_blocks_requeue_and_worker_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(max_attempts=1),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-dead-letter-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    assert leased.lease_id is not None
    store.record_retry(
        tenant_id="tenant-demo",
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id,
        error_type="worker-not-enabled-yet",
        next_attempt_after_utc=datetime(2026, 6, 30, 12, 5, tzinfo=UTC),
        now=datetime(2026, 6, 30, 12, 0, 2, tzinfo=UTC),
    )

    response = build_lms_package_installation_dry_run_execution_outbox_dead_letter_review_response(
        command=_dead_letter_review_command(
            retry_reset_requested=True,
            requeue_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.dead_letter_review_ready is False
    assert response.summary.blocked_job_count == 1
    assert "retry_reset_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review" in response.blocking_reasons
    assert "requeue_forbidden_in_lms_dry_run_execution_outbox_dead_letter_review" in response.blocking_reasons
    assert "worker_dispatch_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_admission" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.BLOCKED


def test_lms_dry_run_execution_outbox_worker_admission_gate_reports_leased_jobs_metadata_only() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_response(
        command=_worker_admission_gate_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_worker_admission_gate.v1"
    assert response.worker_admission_gate_ready is True
    assert response.worker_admission_review_requested is True
    assert response.worker_admission_granted is False
    assert response.leased_jobs == (leased,)
    assert response.leased_jobs[0].queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.leased_jobs[0].lease_id is not None
    assert response.leased_jobs[0].lease_owner == "lease-consumer:lms-dry-run-unit"
    assert response.scheduler_activation_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.eligible_leased_job_count == 1
    assert response.summary.evidence_chain_bound_leased_job_count == 1
    assert response.summary.restore_hash_bound_leased_job_count == 1
    assert response.summary.queued_job_count == 0
    assert response.summary.retry_scheduled_job_count == 0
    assert response.summary.blocked_job_count == 0
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")


def test_lms_dry_run_execution_outbox_worker_admission_gate_blocks_grant_and_worker_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-worker-admission-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_admission_gate_response(
        command=_worker_admission_gate_command(
            worker_admission_grant_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.worker_admission_gate_ready is False
    assert response.worker_admission_granted is False
    assert response.summary.leased_job_count == 1
    assert "worker_admission_grant_forbidden_without_separate_worker_enablement" in response.blocking_reasons
    assert "worker_dispatch_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_admission" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


def test_lms_dry_run_execution_outbox_worker_dispatch_admission_reports_leased_jobs_metadata_only() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_dispatch_admission_response(
        command=_worker_dispatch_admission_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_worker_dispatch_admission.v1"
    assert response.worker_dispatch_admission_ready is True
    assert response.worker_dispatch_admission_review_requested is True
    assert response.worker_dispatch_admission_granted is False
    assert response.leased_jobs == (leased,)
    assert response.leased_jobs[0].queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.leased_jobs[0].lease_id is not None
    assert response.leased_jobs[0].lease_owner == "lease-consumer:lms-dry-run-unit"
    assert response.scheduler_activation_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.dispatch_admissible_leased_job_count == 1
    assert response.summary.evidence_chain_bound_leased_job_count == 1
    assert response.summary.restore_hash_bound_leased_job_count == 1
    assert response.summary.queued_job_count == 0
    assert response.summary.retry_scheduled_job_count == 0
    assert response.summary.blocked_job_count == 0
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")


def test_lms_dry_run_execution_outbox_worker_dispatch_admission_blocks_grant_and_worker_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-worker-dispatch-admission-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_dispatch_admission_response(
        command=_worker_dispatch_admission_command(
            worker_dispatch_admission_grant_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.worker_dispatch_admission_ready is False
    assert response.worker_dispatch_admission_granted is False
    assert response.summary.leased_job_count == 1
    assert "worker_dispatch_admission_grant_forbidden_without_separate_worker_enablement" in response.blocking_reasons
    assert "worker_dispatch_forbidden_until_worker_dispatch_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_dispatch_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_dispatch_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_dispatch_admission" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


def test_lms_dry_run_execution_outbox_worker_queue_admission_reports_leased_jobs_metadata_only() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_queue_admission_response(
        command=_worker_queue_admission_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_worker_queue_admission.v1"
    assert response.worker_queue_admission_ready is True
    assert response.worker_queue_admission_review_requested is True
    assert response.worker_queue_admission_granted is False
    assert response.leased_jobs == (leased,)
    assert response.leased_jobs[0].queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.leased_jobs[0].lease_id is not None
    assert response.leased_jobs[0].lease_owner == "lease-consumer:lms-dry-run-unit"
    assert response.scheduler_activation_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.queue_admissible_leased_job_count == 1
    assert response.summary.evidence_chain_bound_leased_job_count == 1
    assert response.summary.restore_hash_bound_leased_job_count == 1
    assert response.summary.queued_job_count == 0
    assert response.summary.retry_scheduled_job_count == 0
    assert response.summary.blocked_job_count == 0
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")


def test_lms_dry_run_execution_outbox_worker_queue_admission_blocks_grant_and_worker_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-worker-queue-admission-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_queue_admission_response(
        command=_worker_queue_admission_command(
            worker_queue_admission_grant_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.worker_queue_admission_ready is False
    assert response.worker_queue_admission_granted is False
    assert response.summary.leased_job_count == 1
    assert "worker_queue_admission_grant_forbidden_without_separate_worker_enablement" in response.blocking_reasons
    assert "worker_dispatch_forbidden_until_worker_queue_admission" in response.blocking_reasons
    assert "worker_queue_enqueue_forbidden_until_worker_queue_admission" in response.blocking_reasons
    assert "worker_execution_forbidden_until_worker_queue_admission" in response.blocking_reasons
    assert "dry_run_result_persistence_forbidden_until_worker_queue_admission" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


def test_lms_dry_run_execution_outbox_worker_receipt_reports_leased_job_status_without_mutation() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None
    assert leased.lease_id is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_receipt_response(
        command=_worker_receipt_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_worker_receipt.v1"
    assert response.worker_receipt_ready is True
    assert response.worker_receipt_requested is True
    assert response.worker_receipt_issued is True
    assert response.worker_status_observed is True
    assert response.lease_validated is True
    assert response.worker_receipt_ref.startswith("worker-receipt:sha256:")
    assert response.received_job == leased
    assert response.received_job_queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.outbox_state_mutated is False
    assert response.business_writes_executed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.received_job_count == 1
    assert response.summary.lease_validated_job_count == 1
    assert response.summary.status_observed_job_count == 1
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted == leased


def test_lms_dry_run_execution_outbox_worker_receipt_blocks_bad_lease_and_business_write_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_receipt_response(
        command=_worker_receipt_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id="lease:wrong",
            worker_ref="lease-consumer:mismatch",
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
            business_write_requested=True,
            outbox_state_mutation_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.worker_receipt_ready is False
    assert response.worker_receipt_issued is False
    assert response.worker_status_observed is True
    assert response.lease_validated is False
    assert response.summary.received_job_count == 1
    assert response.summary.lease_validated_job_count == 0
    assert "lms_dry_run_execution_outbox_worker_receipt_lease_mismatch" in response.blocking_reasons
    assert "lms_dry_run_execution_outbox_worker_receipt_worker_ref_mismatch" in response.blocking_reasons
    assert "outbox_state_mutation_forbidden_in_lms_dry_run_execution_outbox_worker_receipt" in response.blocking_reasons
    assert "worker_execution_forbidden_in_lms_dry_run_execution_outbox_worker_receipt" in response.blocking_reasons
    assert (
        "dry_run_result_persistence_forbidden_in_lms_dry_run_execution_outbox_worker_receipt"
        in response.blocking_reasons
    )
    assert "business_write_forbidden_in_lms_dry_run_execution_outbox_worker_receipt" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


def test_lms_dry_run_execution_outbox_worker_result_stub_reports_receipt_bound_status_without_mutation() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    lease_response = build_lms_package_installation_dry_run_execution_outbox_lease_consumer_response(
        command=_lease_command(),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )
    leased = lease_response.leased_job
    assert leased is not None
    assert leased.lease_id is not None
    receipt_response = build_lms_package_installation_dry_run_execution_outbox_worker_receipt_response(
        command=_worker_receipt_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    response = build_lms_package_installation_dry_run_execution_outbox_worker_result_stub_response(
        command=_worker_result_stub_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
            worker_receipt_ref=receipt_response.worker_receipt_ref,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.schema_version == "lms_package_installation_dry_run_execution_outbox_worker_result_stub.v1"
    assert response.worker_result_stub_ready is True
    assert response.worker_result_stub_requested is True
    assert response.worker_result_stub_issued is True
    assert response.worker_receipt_ref_validated is True
    assert response.worker_status_observed is True
    assert response.lease_validated is True
    assert response.worker_result_stub_ref.startswith("worker-result-stub:sha256:")
    assert response.worker_receipt_ref == receipt_response.worker_receipt_ref
    assert response.expected_worker_receipt_ref == receipt_response.worker_receipt_ref
    assert response.received_job == leased
    assert response.received_job_queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED
    assert response.outbox_state_mutated is False
    assert response.business_writes_executed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.tenant_module_state_created is False
    assert response.summary.job_outbox_entry_count == 1
    assert response.summary.leased_job_count == 1
    assert response.summary.result_stub_job_count == 1
    assert response.summary.lease_validated_job_count == 1
    assert response.summary.receipt_ref_validated_job_count == 1
    assert response.summary.status_observed_job_count == 1
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted == leased


def test_lms_dry_run_execution_outbox_worker_result_stub_blocks_bad_receipt_and_business_write_requests() -> None:
    store = InMemoryLmsPackageInstallationDryRunExecutionJobOutboxStore((_job(),))
    leased = store.lease_next(
        tenant_id="tenant-demo",
        lease_owner="lease-consumer:lms-dry-run-unit",
        now=datetime(2026, 6, 30, 12, 0, 1, tzinfo=UTC),
    )
    assert leased is not None
    assert leased.lease_id is not None

    response = build_lms_package_installation_dry_run_execution_outbox_worker_result_stub_response(
        command=_worker_result_stub_command(
            worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
            lease_id=leased.lease_id,
            worker_receipt_ref="worker-receipt:sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            worker_execution_requested=True,
            dry_run_result_persistence_requested=True,
            business_write_requested=True,
            outbox_state_mutation_requested=True,
        ),
        tenant_id="tenant-demo",
        user_role_ids={"tenant-admin"},
        store=store,
    )

    assert response.worker_result_stub_ready is False
    assert response.worker_result_stub_issued is False
    assert response.worker_receipt_ref_validated is False
    assert response.worker_status_observed is True
    assert response.lease_validated is True
    assert response.summary.result_stub_job_count == 1
    assert response.summary.receipt_ref_validated_job_count == 0
    assert "lms_dry_run_execution_outbox_worker_result_stub_receipt_ref_mismatch" in response.blocking_reasons
    assert (
        "outbox_state_mutation_forbidden_in_lms_dry_run_execution_outbox_worker_result_stub"
        in response.blocking_reasons
    )
    assert "worker_execution_forbidden_in_lms_dry_run_execution_outbox_worker_result_stub" in response.blocking_reasons
    assert (
        "dry_run_result_persistence_forbidden_in_lms_dry_run_execution_outbox_worker_result_stub"
        in response.blocking_reasons
    )
    assert "business_write_forbidden_in_lms_dry_run_execution_outbox_worker_result_stub" in response.blocking_reasons
    persisted = store.get(tenant_id="tenant-demo", worker_idempotency_key_hash=leased.worker_idempotency_key_hash)
    assert persisted.queue_status == LmsPackageInstallationDryRunExecutionJobStatus.LEASED


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
