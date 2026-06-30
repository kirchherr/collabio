from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_execution_boundary import (
    LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    LmsPackageInstallationExecutionBoundaryCommand,
    build_lms_package_installation_execution_boundary_response,
)
from suite.platform.lms_package_installation_executor_skeleton import (
    LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_PREPARATION_STATEMENT,
    LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_SCHEMA_VERSION,
    LmsPackageInstallationExecutorSkeletonCommand,
    build_lms_package_installation_executor_skeleton_hash,
    build_lms_package_installation_executor_skeleton_response,
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


def _approval_command(approval_gate_evidence_hash: str) -> LmsTenantAdminPackageApprovalRecordCommand:
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


def _boundary_command(
    *,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationExecutionBoundaryCommand:
    return LmsPackageInstallationExecutionBoundaryCommand(
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        execution_boundary_ref="lms-execution-boundary:review-demo",
        change_request_ref="change:lms-package-install-execution-demo",
        idempotency_key_ref="idempotency:lms-package-install-execution-demo",
        reviewed_at_utc=datetime(2026, 6, 30, 8, 5, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-execution-demo",
        execution_boundary_review_statement=LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    )


def _skeleton_command(
    *,
    execution_boundary_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_execution_requested: bool = False,
) -> LmsPackageInstallationExecutorSkeletonCommand:
    return LmsPackageInstallationExecutorSkeletonCommand(
        execution_boundary_evidence_hash=execution_boundary_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        executor_skeleton_ref="lms-executor-skeleton:demo",
        change_request_ref="change:lms-package-install-skeleton-demo",
        idempotency_key_ref="idempotency:lms-package-install-skeleton-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 10, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-skeleton-demo",
        executor_skeleton_preparation_statement=LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_PREPARATION_STATEMENT,
        package_installation_execution_requested=package_installation_execution_requested,
    )


def test_lms_package_installation_executor_skeleton_is_metadata_only_after_boundary_review() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    migration_manifest = load_migration_manifest()
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record = build_lms_tenant_admin_package_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    approval_record_store = InMemoryLmsTenantAdminPackageApprovalRecordStore(records=(approval_record,))
    execution_boundary = build_lms_package_installation_execution_boundary_response(
        command=_boundary_command(
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    response = build_lms_package_installation_executor_skeleton_response(
        command=_skeleton_command(
            execution_boundary_hash=execution_boundary.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.package_installation_ready is True
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.human_approval_ready is True
    assert response.execution_boundary_evidence_hash == execution_boundary.evidence_hash
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.lms_restore_drill_evidence_hash == approval_record.lms_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.executor_skeleton_preparation_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.executor_skeleton_prepared is True
    assert response.package_installation_executor_implementation_required is True
    assert response.package_installation_dry_run_required is True
    assert response.package_installation_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.lms_business_api_allowed is False
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.content_included is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "bind_package_installation_execution_boundary_hash" in response.skeleton_steps
    assert "future_dry_run_required" in response.required_executor_skeleton_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_package_installation_executor_skeleton_hash(response)
    assert response.next_action == "prepare_lms_package_installation_dry_run_without_tenant_activation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_executor_skeleton_blocks_missing_admin_and_execution_request_without_side_effects() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_lms_package_installation_executor_skeleton_response(
        command=_skeleton_command(
            execution_boundary_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            approval_gate_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            approval_record_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            package_installation_execution_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryLmsTenantAdminPackageApprovalRecordStore(),
    )

    assert response.executor_skeleton_prepared is False
    assert "lms_package_installation_readiness_not_ready" in response.blocking_reasons
    assert "package_installation_execution_boundary_hash_missing" in response.blocking_reasons
    assert "tenant_admin_package_install_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "package_installation_execution_request_forbidden" in response.blocking_reasons
    assert response.package_installation_execution_allowed is False
    assert response.package_installation_executed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == "prepare_lms_package_installation_executor_without_business_api_activation"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None
