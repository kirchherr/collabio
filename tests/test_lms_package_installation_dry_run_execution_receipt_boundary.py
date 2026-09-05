from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_dry_run_execution_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    LmsPackageInstallationDryRunExecutionBoundaryCommand,
    build_lms_package_installation_dry_run_execution_boundary_response,
)
from suite.platform.lms_package_installation_dry_run_execution_gate import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_GATE_STATEMENT,
    LmsPackageInstallationDryRunExecutionGateCommand,
    build_lms_package_installation_dry_run_execution_gate_response,
)
from suite.platform.lms_package_installation_dry_run_execution_preflight import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PREFLIGHT_STATEMENT,
    LmsPackageInstallationDryRunExecutionPreflightCommand,
    build_lms_package_installation_dry_run_execution_preflight_response,
)
from suite.platform.lms_package_installation_dry_run_execution_receipt_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_SCHEMA_VERSION,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_STATEMENT,
    LmsPackageInstallationDryRunExecutionReceiptBoundaryCommand,
    build_lms_package_installation_dry_run_execution_receipt_boundary_hash,
    build_lms_package_installation_dry_run_execution_receipt_boundary_response,
)
from suite.platform.lms_package_installation_dry_run_execution_request_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_REQUEST_BOUNDARY_STATEMENT,
    LmsPackageInstallationDryRunExecutionRequestBoundaryCommand,
    build_lms_package_installation_dry_run_execution_request_boundary_response,
)
from suite.platform.lms_package_installation_dry_run_execution_skeleton import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_SKELETON_PREPARATION_STATEMENT,
    LmsPackageInstallationDryRunExecutionSkeletonCommand,
    build_lms_package_installation_dry_run_execution_skeleton_response,
)
from suite.platform.lms_package_installation_dry_run_executor_implementation_review import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTOR_IMPLEMENTATION_REVIEW_STATEMENT,
    LmsPackageInstallationDryRunExecutorImplementationReviewCommand,
    build_lms_package_installation_dry_run_executor_implementation_review_response,
)
from suite.platform.lms_package_installation_dry_run_executor_runtime_boundary import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTOR_RUNTIME_BOUNDARY_STATEMENT,
    LmsPackageInstallationDryRunExecutorRuntimeBoundaryCommand,
    build_lms_package_installation_dry_run_executor_runtime_boundary_response,
)
from suite.platform.lms_package_installation_dry_run_plan import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_STATEMENT,
    LmsPackageInstallationDryRunPlanCommand,
    build_lms_package_installation_dry_run_plan_response,
)
from suite.platform.lms_package_installation_dry_run_result_contract import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_RESULT_CONTRACT_STATEMENT,
    LmsPackageInstallationDryRunResultContractCommand,
    build_lms_package_installation_dry_run_result_contract_response,
)
from suite.platform.lms_package_installation_execution_boundary import (
    LMS_PACKAGE_INSTALLATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT,
    LmsPackageInstallationExecutionBoundaryCommand,
    build_lms_package_installation_execution_boundary_response,
)
from suite.platform.lms_package_installation_executor_skeleton import (
    LMS_PACKAGE_INSTALLATION_EXECUTOR_SKELETON_PREPARATION_STATEMENT,
    LmsPackageInstallationExecutorSkeletonCommand,
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
    )


def _dry_run_plan_command(
    *,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationDryRunPlanCommand:
    return LmsPackageInstallationDryRunPlanCommand(
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_plan_ref="lms-dry-run-plan:demo",
        change_request_ref="change:lms-package-install-dry-run-plan-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-plan-demo",
        planned_at_utc=datetime(2026, 6, 30, 8, 15, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-plan-demo",
        dry_run_plan_statement=LMS_PACKAGE_INSTALLATION_DRY_RUN_PLAN_STATEMENT,
    )


def _dry_run_execution_boundary_command(
    *,
    dry_run_plan_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationDryRunExecutionBoundaryCommand:
    return LmsPackageInstallationDryRunExecutionBoundaryCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_boundary_ref="lms-dry-run-execution-boundary:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-boundary-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-boundary-demo",
        reviewed_at_utc=datetime(2026, 6, 30, 8, 20, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-boundary-demo",
        dry_run_execution_boundary_review_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_BOUNDARY_REVIEW_STATEMENT
        ),
    )


def _dry_run_execution_skeleton_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationDryRunExecutionSkeletonCommand:
    return LmsPackageInstallationDryRunExecutionSkeletonCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_skeleton_ref="lms-dry-run-execution-skeleton:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-skeleton-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-skeleton-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 25, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-skeleton-demo",
        dry_run_execution_skeleton_preparation_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_SKELETON_PREPARATION_STATEMENT
        ),
    )


def _dry_run_executor_implementation_review_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_dry_run_execution_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutorImplementationReviewCommand:
    return LmsPackageInstallationDryRunExecutorImplementationReviewCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_executor_implementation_review_ref="lms-dry-run-executor-implementation-review:demo",
        change_request_ref="change:lms-package-install-dry-run-executor-implementation-review-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-executor-implementation-review-demo",
        reviewed_at_utc=datetime(2026, 6, 30, 8, 30, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-executor-implementation-review-demo",
        dry_run_executor_implementation_review_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTOR_IMPLEMENTATION_REVIEW_STATEMENT
        ),
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
    )


def _dry_run_result_contract_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> LmsPackageInstallationDryRunResultContractCommand:
    return LmsPackageInstallationDryRunResultContractCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_result_contract_ref="lms-dry-run-result-contract:demo",
        change_request_ref="change:lms-package-install-dry-run-result-contract-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-result-contract-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 35, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-result-contract-demo",
        dry_run_result_contract_statement=LMS_PACKAGE_INSTALLATION_DRY_RUN_RESULT_CONTRACT_STATEMENT,
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def _dry_run_execution_gate_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    dry_run_result_contract_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutionGateCommand:
    return LmsPackageInstallationDryRunExecutionGateCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        dry_run_result_contract_evidence_hash=dry_run_result_contract_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_gate_ref="lms-dry-run-execution-gate:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-gate-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-gate-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 40, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-gate-demo",
        dry_run_execution_gate_statement=LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_GATE_STATEMENT,
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def _dry_run_execution_request_boundary_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    dry_run_result_contract_hash: str,
    dry_run_execution_gate_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutionRequestBoundaryCommand:
    return LmsPackageInstallationDryRunExecutionRequestBoundaryCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        dry_run_result_contract_evidence_hash=dry_run_result_contract_hash,
        dry_run_execution_gate_evidence_hash=dry_run_execution_gate_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_request_boundary_ref="lms-dry-run-execution-request-boundary:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-request-boundary-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-request-boundary-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 45, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-request-boundary-demo",
        dry_run_execution_request_boundary_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_REQUEST_BOUNDARY_STATEMENT
        ),
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def _dry_run_executor_runtime_boundary_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    dry_run_result_contract_hash: str,
    dry_run_execution_gate_hash: str,
    dry_run_execution_request_boundary_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationDryRunExecutorRuntimeBoundaryCommand:
    return LmsPackageInstallationDryRunExecutorRuntimeBoundaryCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        dry_run_result_contract_evidence_hash=dry_run_result_contract_hash,
        dry_run_execution_gate_evidence_hash=dry_run_execution_gate_hash,
        dry_run_execution_request_boundary_evidence_hash=dry_run_execution_request_boundary_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_executor_runtime_boundary_ref="lms-dry-run-executor-runtime-boundary:demo",
        change_request_ref="change:lms-package-install-dry-run-executor-runtime-boundary-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-executor-runtime-boundary-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 50, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-executor-runtime-boundary-demo",
        dry_run_executor_runtime_boundary_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTOR_RUNTIME_BOUNDARY_STATEMENT
        ),
    )


def _dry_run_execution_preflight_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    dry_run_result_contract_hash: str,
    dry_run_execution_gate_hash: str,
    dry_run_execution_request_boundary_hash: str,
    dry_run_executor_runtime_boundary_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
) -> LmsPackageInstallationDryRunExecutionPreflightCommand:
    return LmsPackageInstallationDryRunExecutionPreflightCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        dry_run_result_contract_evidence_hash=dry_run_result_contract_hash,
        dry_run_execution_gate_evidence_hash=dry_run_execution_gate_hash,
        dry_run_execution_request_boundary_evidence_hash=dry_run_execution_request_boundary_hash,
        dry_run_executor_runtime_boundary_evidence_hash=dry_run_executor_runtime_boundary_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_preflight_ref="lms-dry-run-execution-preflight:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-preflight-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-preflight-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 55, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-preflight-demo",
        dry_run_execution_preflight_statement=LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_PREFLIGHT_STATEMENT,
    )


def _dry_run_execution_receipt_boundary_command(
    *,
    dry_run_plan_hash: str,
    dry_run_execution_boundary_hash: str,
    dry_run_execution_skeleton_hash: str,
    dry_run_executor_implementation_review_hash: str,
    dry_run_result_contract_hash: str,
    dry_run_execution_gate_hash: str,
    dry_run_execution_request_boundary_hash: str,
    dry_run_executor_runtime_boundary_hash: str,
    dry_run_execution_preflight_hash: str,
    execution_boundary_hash: str,
    executor_skeleton_hash: str,
    approval_gate_hash: str,
    approval_record_hash: str,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutionReceiptBoundaryCommand:
    return LmsPackageInstallationDryRunExecutionReceiptBoundaryCommand(
        dry_run_plan_evidence_hash=dry_run_plan_hash,
        dry_run_execution_boundary_evidence_hash=dry_run_execution_boundary_hash,
        dry_run_execution_skeleton_evidence_hash=dry_run_execution_skeleton_hash,
        dry_run_executor_implementation_review_evidence_hash=dry_run_executor_implementation_review_hash,
        dry_run_result_contract_evidence_hash=dry_run_result_contract_hash,
        dry_run_execution_gate_evidence_hash=dry_run_execution_gate_hash,
        dry_run_execution_request_boundary_evidence_hash=dry_run_execution_request_boundary_hash,
        dry_run_executor_runtime_boundary_evidence_hash=dry_run_executor_runtime_boundary_hash,
        dry_run_execution_preflight_evidence_hash=dry_run_execution_preflight_hash,
        execution_boundary_evidence_hash=execution_boundary_hash,
        executor_skeleton_evidence_hash=executor_skeleton_hash,
        tenant_admin_approval_gate_hash=approval_gate_hash,
        tenant_admin_approval_record_hash=approval_record_hash,
        dry_run_execution_receipt_boundary_ref="lms-dry-run-execution-receipt-boundary:demo",
        change_request_ref="change:lms-package-install-dry-run-execution-receipt-boundary-demo",
        idempotency_key_ref="idempotency:lms-package-install-dry-run-execution-receipt-boundary-demo",
        prepared_at_utc=datetime(2026, 6, 30, 8, 50, tzinfo=UTC),
        audit_chain_ref="audit:lms-package-install-dry-run-execution-receipt-boundary-demo",
        dry_run_execution_receipt_boundary_statement=(
            LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_STATEMENT
        ),
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
    )


def test_lms_package_installation_dry_run_execution_receipt_boundary_is_metadata_only_after_request_boundary() -> None:
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
    executor_skeleton = build_lms_package_installation_executor_skeleton_response(
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
    dry_run_plan = build_lms_package_installation_dry_run_plan_response(
        command=_dry_run_plan_command(
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )
    dry_run_execution_boundary = build_lms_package_installation_dry_run_execution_boundary_response(
        command=_dry_run_execution_boundary_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )
    dry_run_execution_skeleton = build_lms_package_installation_dry_run_execution_skeleton_response(
        command=_dry_run_execution_skeleton_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    dry_run_executor_implementation_review = (
        build_lms_package_installation_dry_run_executor_implementation_review_response(
            command=_dry_run_executor_implementation_review_command(
                dry_run_plan_hash=dry_run_plan.evidence_hash,
                dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
                dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
                execution_boundary_hash=execution_boundary.evidence_hash,
                executor_skeleton_hash=executor_skeleton.evidence_hash,
                approval_gate_hash=approval_gate.evidence_hash,
                approval_record_hash=approval_record.evidence_hash,
            ),
            user_context=user_context,
            module_registry=module_registry,
            migration_manifest_entries=migration_manifest,
            approval_record_store=approval_record_store,
        )
    )

    dry_run_result_contract = build_lms_package_installation_dry_run_result_contract_response(
        command=_dry_run_result_contract_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    dry_run_execution_gate = build_lms_package_installation_dry_run_execution_gate_response(
        command=_dry_run_execution_gate_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            dry_run_result_contract_hash=dry_run_result_contract.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    dry_run_execution_request_boundary = build_lms_package_installation_dry_run_execution_request_boundary_response(
        command=_dry_run_execution_request_boundary_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            dry_run_result_contract_hash=dry_run_result_contract.evidence_hash,
            dry_run_execution_gate_hash=dry_run_execution_gate.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    dry_run_executor_runtime_boundary = build_lms_package_installation_dry_run_executor_runtime_boundary_response(
        command=_dry_run_executor_runtime_boundary_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            dry_run_result_contract_hash=dry_run_result_contract.evidence_hash,
            dry_run_execution_gate_hash=dry_run_execution_gate.evidence_hash,
            dry_run_execution_request_boundary_hash=dry_run_execution_request_boundary.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    dry_run_execution_preflight = build_lms_package_installation_dry_run_execution_preflight_response(
        command=_dry_run_execution_preflight_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            dry_run_result_contract_hash=dry_run_result_contract.evidence_hash,
            dry_run_execution_gate_hash=dry_run_execution_gate.evidence_hash,
            dry_run_execution_request_boundary_hash=dry_run_execution_request_boundary.evidence_hash,
            dry_run_executor_runtime_boundary_hash=dry_run_executor_runtime_boundary.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    response = build_lms_package_installation_dry_run_execution_receipt_boundary_response(
        command=_dry_run_execution_receipt_boundary_command(
            dry_run_plan_hash=dry_run_plan.evidence_hash,
            dry_run_execution_boundary_hash=dry_run_execution_boundary.evidence_hash,
            dry_run_execution_skeleton_hash=dry_run_execution_skeleton.evidence_hash,
            dry_run_executor_implementation_review_hash=dry_run_executor_implementation_review.evidence_hash,
            dry_run_result_contract_hash=dry_run_result_contract.evidence_hash,
            dry_run_execution_gate_hash=dry_run_execution_gate.evidence_hash,
            dry_run_execution_request_boundary_hash=dry_run_execution_request_boundary.evidence_hash,
            dry_run_executor_runtime_boundary_hash=dry_run_executor_runtime_boundary.evidence_hash,
            dry_run_execution_preflight_hash=dry_run_execution_preflight.evidence_hash,
            execution_boundary_hash=execution_boundary.evidence_hash,
            executor_skeleton_hash=executor_skeleton.evidence_hash,
            approval_gate_hash=approval_gate.evidence_hash,
            approval_record_hash=approval_record.evidence_hash,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=approval_record_store,
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RECEIPT_BOUNDARY_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.package_installation_ready is True
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.human_approval_ready is True
    assert response.dry_run_plan_evidence_hash == dry_run_plan.evidence_hash
    assert response.dry_run_execution_boundary_evidence_hash == dry_run_execution_boundary.evidence_hash
    assert response.dry_run_execution_skeleton_evidence_hash == dry_run_execution_skeleton.evidence_hash
    assert (
        response.dry_run_executor_implementation_review_evidence_hash
        == dry_run_executor_implementation_review.evidence_hash
    )
    assert response.dry_run_result_contract_evidence_hash == dry_run_result_contract.evidence_hash
    assert response.dry_run_execution_gate_evidence_hash == dry_run_execution_gate.evidence_hash
    assert response.dry_run_execution_request_boundary_evidence_hash == dry_run_execution_request_boundary.evidence_hash
    assert response.dry_run_executor_runtime_boundary_evidence_hash == dry_run_executor_runtime_boundary.evidence_hash
    assert response.dry_run_execution_preflight_evidence_hash == dry_run_execution_preflight.evidence_hash
    assert response.execution_boundary_evidence_hash == execution_boundary.evidence_hash
    assert response.executor_skeleton_evidence_hash == executor_skeleton.evidence_hash
    assert response.tenant_admin_approval_gate_hash == approval_gate.evidence_hash
    assert response.tenant_admin_approval_record_hash == approval_record.evidence_hash
    assert response.lms_restore_drill_evidence_hash == approval_record.lms_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.dry_run_execution_receipt_boundary_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.dry_run_execution_receipt_boundary_ready is True
    assert response.future_dry_run_result_persistence_boundary_required is True
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.package_installation_execution_allowed is False
    assert response.tenant_provisioning_allowed is False
    assert response.migration_execution_allowed is False
    assert response.lms_business_api_allowed is False
    assert response.package_installation_executed is False
    assert response.module_activation_executed is False
    assert response.tenant_module_state_created is False
    assert response.content_included is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert (
        "define_receipt_boundary_idempotency_and_readiness_checks" in response.dry_run_execution_receipt_boundary_steps
    )
    assert "define_no_worker_or_scheduler_activation_flags" in response.dry_run_execution_receipt_boundary_steps
    assert (
        "future_dry_run_result_persistence_boundary_required"
        in response.required_dry_run_execution_receipt_boundary_evidence
    )
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_package_installation_dry_run_execution_receipt_boundary_hash(response)
    assert response.next_action == (
        "prepare_lms_package_installation_dry_run_result_persistence_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_dry_run_execution_receipt_boundary_blocks_execution_request_without_side_effects() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    migration_manifest = load_migration_manifest()

    response = build_lms_package_installation_dry_run_execution_receipt_boundary_response(
        command=_dry_run_execution_receipt_boundary_command(
            dry_run_plan_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            dry_run_execution_boundary_hash=("sha256:0000000000000000000000000000000000000000000000000000000000000000"),
            dry_run_execution_skeleton_hash=("sha256:0000000000000000000000000000000000000000000000000000000000000000"),
            dry_run_executor_implementation_review_hash=(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            dry_run_result_contract_hash=("sha256:0000000000000000000000000000000000000000000000000000000000000000"),
            dry_run_execution_gate_hash=("sha256:0000000000000000000000000000000000000000000000000000000000000000"),
            dry_run_execution_request_boundary_hash=(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            dry_run_executor_runtime_boundary_hash=(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            dry_run_execution_preflight_hash=(
                "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            ),
            execution_boundary_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            executor_skeleton_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            approval_gate_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            approval_record_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            package_installation_dry_run_execution_requested=True,
            dry_run_result_persistence_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        approval_record_store=InMemoryLmsTenantAdminPackageApprovalRecordStore(),
    )

    assert response.dry_run_execution_receipt_boundary_ready is False
    assert "lms_package_installation_readiness_not_ready" in response.blocking_reasons
    assert "package_installation_dry_run_plan_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_boundary_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_skeleton_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_executor_implementation_review_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_result_contract_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_gate_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_request_boundary_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_executor_runtime_boundary_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_preflight_hash_missing" in response.blocking_reasons
    assert "package_installation_execution_boundary_hash_missing" in response.blocking_reasons
    assert "package_installation_executor_skeleton_hash_missing" in response.blocking_reasons
    assert "tenant_admin_package_install_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "package_installation_dry_run_execution_request_forbidden" in response.blocking_reasons
    assert "dry_run_result_persistence_request_forbidden" in response.blocking_reasons
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.package_installation_executed is False
    assert response.tenant_module_state_created is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.destructive_actions_allowed is False
    assert (
        response.next_action == "prepare_lms_package_installation_dry_run_execution_receipt_boundary_without_execution"
    )
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None
