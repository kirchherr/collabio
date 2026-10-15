from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_dry_run_execution_approval_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT,
    LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand,
    build_lms_package_installation_dry_run_execution_approval_boundary_hash,
    build_lms_package_installation_dry_run_execution_approval_boundary_response,
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
FINAL_READINESS_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SCHEDULER_BOUNDARY_HASH = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
WORKER_IMAGE_BOUNDARY_HASH = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


def _approval_record_command(approval_gate_evidence_hash: str) -> LmsTenantAdminPackageApprovalRecordCommand:
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


def _approval_boundary_command(
    *,
    final_readiness_hash: str = FINAL_READINESS_HASH,
    scheduler_boundary_hash: str = ZERO_SHA256,
    worker_image_boundary_hash: str = ZERO_SHA256,
    explicit_human_execution_approval_requested: bool = False,
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
) -> LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand:
    return LmsPackageInstallationDryRunExecutionApprovalBoundaryCommand(
        dry_run_execution_final_readiness_gate_evidence_hash=final_readiness_hash,
        dry_run_execution_scheduler_boundary_evidence_hash=scheduler_boundary_hash,
        dry_run_execution_worker_image_boundary_evidence_hash=worker_image_boundary_hash,
        dry_run_execution_approval_boundary_ref="lms-dry-run-execution-approval-boundary:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-approval-boundary-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-approval-boundary-demo",
        prepared_at_utc=datetime(2026, 6, 30, 9, 35, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-approval-boundary-demo",
        dry_run_execution_approval_boundary_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT
        ),
        explicit_human_execution_approval_requested=explicit_human_execution_approval_requested,
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


def test_lms_package_installation_dry_run_execution_approval_boundary_is_metadata_only() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="admin-1", role_ids={"tenant-admin"})
    migration_manifest = load_migration_manifest()
    approval_record_store = InMemoryLmsTenantAdminPackageApprovalRecordStore()
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record = build_lms_tenant_admin_package_approval_record_response(
        command=_approval_record_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record_store.append(approval_record)

    response = build_lms_package_installation_dry_run_execution_approval_boundary_response(
        command=_approval_boundary_command(
            scheduler_boundary_hash=SCHEDULER_BOUNDARY_HASH,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.package_installation_ready is True
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.human_approval_ready is True
    assert response.dry_run_execution_final_readiness_gate_evidence_hash == FINAL_READINESS_HASH
    assert response.dry_run_execution_scheduler_boundary_evidence_hash == SCHEDULER_BOUNDARY_HASH
    assert response.dry_run_execution_worker_image_boundary_evidence_hash == WORKER_IMAGE_BOUNDARY_HASH
    assert response.worker_image_boundary_evidence_bound is True
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.lms_restore_drill_evidence_hash == approval_record.lms_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.dry_run_execution_approval_boundary_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.dry_run_execution_approval_boundary_ready is True
    assert response.future_dry_run_execution_approval_record_required is True
    assert response.explicit_human_execution_approval_present is False
    assert response.scheduler_activation_allowed is False
    assert response.scheduler_job_creation_allowed is False
    assert response.scheduler_job_created is False
    assert response.worker_image_resolution_allowed is False
    assert response.worker_image_resolved is False
    assert response.worker_image_pull_allowed is False
    assert response.worker_image_pulled is False
    assert response.worker_image_digest_lookup_allowed is False
    assert response.worker_image_digest_looked_up is False
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.worker_executed is False
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.package_installation_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.lms_business_api_allowed is False
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.persistent_task_created is False
    assert response.content_included is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "define_approval_boundary_idempotency_and_hash_closure" in response.dry_run_execution_approval_boundary_steps
    assert (
        "confirm_worker_image_boundary_chain_preserved_at_approval_boundary_when_present"
        in response.dry_run_execution_approval_boundary_steps
    )
    assert (
        "worker_image_boundary_chain_hashes_when_present"
        in response.required_dry_run_execution_approval_boundary_evidence
    )
    assert (
        "future_dry_run_execution_approval_record_required"
        in response.required_dry_run_execution_approval_boundary_evidence
    )
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_package_installation_dry_run_execution_approval_boundary_hash(response)
    assert response.next_action == "record_lms_dry_run_execution_approval_with_explicit_human_confirmation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_dry_run_execution_approval_boundary_blocks_execution_request_without_side_effects() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_lms_package_installation_dry_run_execution_approval_boundary_response(
        command=_approval_boundary_command(
            final_readiness_hash=ZERO_SHA256,
            worker_image_boundary_hash=WORKER_IMAGE_BOUNDARY_HASH,
            explicit_human_execution_approval_requested=True,
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
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryLmsTenantAdminPackageApprovalRecordStore(),
    )

    assert response.dry_run_execution_approval_boundary_ready is False
    assert "lms_package_installation_readiness_not_ready" in response.blocking_reasons
    assert "package_installation_dry_run_execution_final_readiness_gate_hash_missing" in response.blocking_reasons
    assert "tenant_admin_package_install_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "explicit_human_execution_approval_requires_separate_record" in response.blocking_reasons
    assert "package_installation_dry_run_execution_scheduler_boundary_hash_missing" in response.blocking_reasons
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
    assert response.explicit_human_execution_approval_present is False
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
    assert response.destructive_actions_allowed is False
    assert (
        response.next_action == "prepare_lms_package_installation_dry_run_execution_approval_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None
