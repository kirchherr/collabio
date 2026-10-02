from datetime import UTC, datetime

import pytest

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_dry_run_execution_approval_record import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_SCHEMA_VERSION,
    InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore,
    LmsPackageInstallationDryRunExecutionApprovalRecordCommand,
    build_lms_package_installation_dry_run_execution_approval_record_hash,
    build_lms_package_installation_dry_run_execution_approval_record_response,
)
from suite.platform.lms_tenant_admin_package_approval_gate import (
    build_lms_tenant_admin_package_approval_gate_response,
)
from suite.platform.lms_tenant_admin_package_approval_record import (
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    InMemoryLmsTenantAdminPackageApprovalRecordStore,
    LmsTenantAdminPackageApprovalRecordCommand,
    build_lms_tenant_admin_package_approval_record_response,
)
from suite.platform.modules import default_module_registry

ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
APPROVAL_BOUNDARY_HASH = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SCHEDULER_BOUNDARY_HASH = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
WORKER_IMAGE_BOUNDARY_HASH = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def _package_approval_command(approval_gate_evidence_hash: str) -> LmsTenantAdminPackageApprovalRecordCommand:
    return LmsTenantAdminPackageApprovalRecordCommand(
        approval_gate_evidence_hash=approval_gate_evidence_hash,
        approval_record_ref="lms-approval:record-demo",
        approval_ticket_ref="ticket:lms-package-install-demo",
        human_confirmation_reference="confirmation:lms-package-install-demo",
        human_confirmation_statement=LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
        change_request_ref="change:lms-package-install-demo",
        idempotency_key_ref="idempotency:lms-package-install-demo",
        approved_at_utc=datetime(2026, 6, 30, 8, 0, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-demo",
    )


def _execution_approval_command(
    *,
    approval_boundary_hash: str = APPROVAL_BOUNDARY_HASH,
    scheduler_boundary_hash: str = ZERO_SHA256,
    worker_image_boundary_hash: str = ZERO_SHA256,
    scheduler_activation_requested: bool = False,
    scheduler_job_creation_requested: bool = False,
    worker_image_resolution_requested: bool = False,
    worker_image_pull_requested: bool = False,
    worker_image_digest_lookup_requested: bool = False,
    worker_dispatch_requested: bool = False,
    worker_queue_enqueue_requested: bool = False,
    worker_execution_requested: bool = False,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutionApprovalRecordCommand:
    return LmsPackageInstallationDryRunExecutionApprovalRecordCommand(
        dry_run_execution_approval_boundary_evidence_hash=approval_boundary_hash,
        dry_run_execution_scheduler_boundary_evidence_hash=scheduler_boundary_hash,
        dry_run_execution_worker_image_boundary_evidence_hash=worker_image_boundary_hash,
        dry_run_execution_approval_record_ref="lms-dry-run-execution-approval-record:demo",
        approval_ticket_ref="ticket:lms-dry-run-execution-demo",
        human_confirmation_reference="confirmation:lms-dry-run-execution-demo",
        human_confirmation_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
        ),
        change_request_ref="change:lms-dry-run-execution-approval-record-demo",
        idempotency_key_ref="idempotency:lms-dry-run-execution-approval-record-demo",
        approved_at_utc=datetime(2026, 6, 30, 9, 40, tzinfo=UTC),
        audit_chain_ref="audit:lms-dry-run-execution-approval-record-demo",
        scheduler_activation_requested=scheduler_activation_requested,
        scheduler_job_creation_requested=scheduler_job_creation_requested,
        worker_image_resolution_requested=worker_image_resolution_requested,
        worker_image_pull_requested=worker_image_pull_requested,
        worker_image_digest_lookup_requested=worker_image_digest_lookup_requested,
        worker_dispatch_requested=worker_dispatch_requested,
        worker_queue_enqueue_requested=worker_queue_enqueue_requested,
        worker_execution_requested=worker_execution_requested,
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def _package_approval_store(
    *,
    user_context: UserContext,
) -> tuple[InMemoryLmsTenantAdminPackageApprovalRecordStore, str]:
    module_registry = default_module_registry()
    migration_manifest = load_migration_manifest()
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record = build_lms_tenant_admin_package_approval_record_response(
        command=_package_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    return InMemoryLmsTenantAdminPackageApprovalRecordStore(records=(approval_record,)), approval_record.evidence_hash


def test_lms_dry_run_execution_approval_record_is_metadata_only_and_non_executing() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    package_approval_store, package_approval_record_hash = _package_approval_store(user_context=user_context)

    response = build_lms_package_installation_dry_run_execution_approval_record_response(
        command=_execution_approval_command(
            scheduler_boundary_hash=SCHEDULER_BOUNDARY_HASH,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        package_approval_record_store=package_approval_store,
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.package_installation_ready is True
    assert response.dry_run_execution_approval_boundary_evidence_hash == APPROVAL_BOUNDARY_HASH
    assert response.dry_run_execution_scheduler_boundary_evidence_hash == SCHEDULER_BOUNDARY_HASH
    assert response.dry_run_execution_worker_image_boundary_evidence_hash == WORKER_IMAGE_BOUNDARY_HASH
    assert response.worker_image_boundary_evidence_bound is True
    assert response.tenant_admin_approval_record_hash == package_approval_record_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.human_confirmation_statement_hash.startswith("sha256:")
    assert response.approver_role_allowed is True
    assert response.record_status == "approved_for_dry_run_execution_admission_gate"
    assert response.dry_run_execution_approval_record_created is True
    assert response.human_confirmation_captured is True
    assert response.human_confirmation_statement_matched is True
    assert response.explicit_human_execution_approval_present is True
    assert response.worker_image_boundary_evidence_bound is True
    assert response.future_dry_run_execution_admission_gate_required is True
    assert response.scheduler_activation_allowed is False
    assert response.scheduler_job_creation_allowed is False
    assert response.scheduler_job_created is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_image_resolved is False
    assert response.worker_image_pull_allowed is False
    assert response.worker_image_pulled is False
    assert response.worker_image_digest_lookup_allowed is False
    assert response.worker_image_digest_looked_up is False
    assert response.worker_image_boundary_evidence_bound is True
    assert response.scheduler_activation_allowed is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.worker_executed is False
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "dry_run_execution_approval_boundary_evidence_hash" in response.required_approval_record_evidence
    assert "worker_image_boundary_chain_hashes_when_present" in response.required_approval_record_evidence
    assert "future_dry_run_execution_admission_gate_required" in response.required_approval_record_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_package_installation_dry_run_execution_approval_record_hash(response)
    assert response.next_action == "prepare_lms_dry_run_execution_admission_gate_without_execution"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_dry_run_execution_approval_record_store_is_idempotent() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    package_approval_store, _ = _package_approval_store(user_context=user_context)
    record = build_lms_package_installation_dry_run_execution_approval_record_response(
        command=_execution_approval_command(),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        package_approval_record_store=package_approval_store,
    )
    store = InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore()

    assert store.append(record) == record
    assert store.append(record) == record
    assert (
        store.latest_for_boundary(
            tenant_id="tenant-demo",
            dry_run_execution_approval_boundary_evidence_hash=APPROVAL_BOUNDARY_HASH,
        )
        == record
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_dry_run_execution_approval_record_blocks_execution_request_without_persistence() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})

    response = build_lms_package_installation_dry_run_execution_approval_record_response(
        command=_execution_approval_command(
            approval_boundary_hash=ZERO_SHA256,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
            scheduler_activation_requested=True,
            scheduler_job_creation_requested=True,
            worker_image_resolution_requested=True,
            worker_image_pull_requested=True,
            worker_image_digest_lookup_requested=True,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            package_installation_dry_run_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        package_approval_record_store=InMemoryLmsTenantAdminPackageApprovalRecordStore(),
    )

    assert response.dry_run_execution_approval_record_created is False
    assert response.record_status == "blocked"
    assert response.explicit_human_execution_approval_present is False
    assert "lms_package_installation_readiness_not_ready" in response.blocking_reasons
    assert "package_installation_dry_run_execution_approval_boundary_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_scheduler_boundary_hash_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "scheduler_activation_request_forbidden" in response.blocking_reasons
    assert "scheduler_job_creation_request_forbidden" in response.blocking_reasons
    assert "worker_image_resolution_request_forbidden" in response.blocking_reasons
    assert "worker_image_pull_request_forbidden" in response.blocking_reasons
    assert "worker_image_digest_lookup_request_forbidden" in response.blocking_reasons
    assert "worker_dispatch_request_forbidden" in response.blocking_reasons
    assert "worker_queue_enqueue_request_forbidden" in response.blocking_reasons
    assert "worker_execution_request_forbidden" in response.blocking_reasons
    assert "package_installation_dry_run_execution_request_forbidden" in response.blocking_reasons
    assert "dry_run_result_persistence_request_forbidden" in response.blocking_reasons
    assert response.worker_image_boundary_evidence_bound is True
    assert response.scheduler_activation_allowed is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.tenant_module_state_created is False
    assert response.next_action == "record_lms_dry_run_execution_approval_with_explicit_human_confirmation"
    with pytest.raises(ValueError, match="blocked"):
        InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore().append(response)
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None
