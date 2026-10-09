from datetime import UTC, datetime

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_dry_run_execution_approval_record import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore,
    LmsPackageInstallationDryRunExecutionApprovalRecordCommand,
    build_lms_package_installation_dry_run_execution_approval_record_response,
)
from suite.platform.lms_package_installation_dry_run_execution_runbook import (
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_ENDPOINT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_RESULT_CONTRACT,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_SCHEMA_VERSION,
    LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_STATEMENT,
    LmsPackageInstallationDryRunExecutionRunbookCommand,
    build_lms_package_installation_dry_run_execution_runbook_hash,
    build_lms_package_installation_dry_run_execution_runbook_response,
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
ADMISSION_GATE_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
APPROVAL_BOUNDARY_HASH = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


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


def _execution_approval_command() -> LmsPackageInstallationDryRunExecutionApprovalRecordCommand:
    return LmsPackageInstallationDryRunExecutionApprovalRecordCommand(
        dry_run_execution_approval_boundary_evidence_hash=APPROVAL_BOUNDARY_HASH,
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
    )


def _runbook_command(
    *,
    admission_gate_hash: str = ADMISSION_GATE_HASH,
    approval_boundary_hash: str = APPROVAL_BOUNDARY_HASH,
    approval_record_hash: str,
    worker_dispatch_requested: bool = False,
    worker_queue_enqueue_requested: bool = False,
    worker_execution_requested: bool = False,
    package_installation_dry_run_execution_requested: bool = False,
    dry_run_result_persistence_requested: bool = False,
    rollback_execution_requested: bool = False,
    failover_execution_requested: bool = False,
) -> LmsPackageInstallationDryRunExecutionRunbookCommand:
    return LmsPackageInstallationDryRunExecutionRunbookCommand(
        dry_run_execution_admission_gate_evidence_hash=admission_gate_hash,
        dry_run_execution_approval_boundary_evidence_hash=approval_boundary_hash,
        dry_run_execution_approval_record_hash=approval_record_hash,
        dry_run_execution_runbook_ref="lms-dry-run-execution-runbook:demo",
        backup_restore_runbook_ref="runbook:lms-dry-run-backup-restore-demo",
        rollback_runbook_ref="runbook:lms-dry-run-rollback-demo",
        operator_handoff_ref="handoff:lms-dry-run-operator-demo",
        change_request_ref="change:lms-dry-run-execution-runbook-demo",
        idempotency_key_ref="idempotency:lms-dry-run-execution-runbook-demo",
        prepared_at_utc=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
        audit_chain_ref="audit:lms-dry-run-execution-runbook-demo",
        dry_run_execution_runbook_statement=LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_STATEMENT,
        worker_dispatch_requested=worker_dispatch_requested,
        worker_queue_enqueue_requested=worker_queue_enqueue_requested,
        worker_execution_requested=worker_execution_requested,
        package_installation_dry_run_execution_requested=package_installation_dry_run_execution_requested,
        dry_run_result_persistence_requested=dry_run_result_persistence_requested,
        rollback_execution_requested=rollback_execution_requested,
        failover_execution_requested=failover_execution_requested,
    )


def _stores(
    *,
    user_context: UserContext,
) -> tuple[
    InMemoryLmsTenantAdminPackageApprovalRecordStore,
    InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore,
    str,
]:
    module_registry = default_module_registry()
    migration_manifest = load_migration_manifest()
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    package_approval_record = build_lms_tenant_admin_package_approval_record_response(
        command=_package_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    package_approval_store = InMemoryLmsTenantAdminPackageApprovalRecordStore(records=(package_approval_record,))
    execution_approval_record = build_lms_package_installation_dry_run_execution_approval_record_response(
        command=_execution_approval_command(),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
        package_approval_record_store=package_approval_store,
    )
    execution_approval_store = InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore(
        records=(execution_approval_record,)
    )
    return package_approval_store, execution_approval_store, execution_approval_record.evidence_hash


def test_lms_dry_run_execution_runbook_is_metadata_only_and_binds_backup_refs() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    package_approval_store, execution_approval_store, execution_approval_record_hash = _stores(
        user_context=user_context
    )

    response = build_lms_package_installation_dry_run_execution_runbook_response(
        command=_runbook_command(approval_record_hash=execution_approval_record_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        package_approval_record_store=package_approval_store,
        dry_run_execution_approval_record_store=execution_approval_store,
    )

    assert response.schema_version == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_SCHEMA_VERSION
    assert response.endpoint == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_ENDPOINT
    assert response.result_contract == LMS_PACKAGE_INSTALLATION_DRY_RUN_EXECUTION_RUNBOOK_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.package_installation_ready is True
    assert response.migration_plan_ready is True
    assert response.restore_evidence_ready is True
    assert response.human_approval_ready is True
    assert response.dry_run_execution_admission_gate_evidence_hash == ADMISSION_GATE_HASH
    assert response.dry_run_execution_approval_boundary_evidence_hash == APPROVAL_BOUNDARY_HASH
    assert response.dry_run_execution_approval_record_hash == execution_approval_record_hash
    assert response.stored_dry_run_execution_approval_record_hash == execution_approval_record_hash
    assert response.backup_restore_runbook_ref == "runbook:lms-dry-run-backup-restore-demo"
    assert response.rollback_runbook_ref == "runbook:lms-dry-run-rollback-demo"
    assert response.operator_handoff_ref == "handoff:lms-dry-run-operator-demo"
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.dry_run_execution_runbook_statement_hash.startswith("sha256:")
    assert response.preparer_role_allowed is True
    assert response.dry_run_execution_runbook_requested is True
    assert response.dry_run_execution_runbook_ready is True
    assert response.explicit_human_execution_approval_present is True
    assert response.approval_record_tenant_match is True
    assert response.approval_record_hash_match is True
    assert response.future_dry_run_execution_plan_required is True
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.worker_executed is False
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.package_installation_dry_run_executed is False
    assert response.dry_run_result_persistence_allowed is False
    assert response.dry_run_result_persisted is False
    assert response.rollback_execution_allowed is False
    assert response.failover_execution_allowed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "bind_backup_restore_runbook_ref" in response.dry_run_execution_runbook_steps
    assert "future_dry_run_execution_plan_required" in response.required_dry_run_execution_runbook_evidence
    assert "no_rollback_or_failover_execution" in response.required_dry_run_execution_runbook_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_package_installation_dry_run_execution_runbook_hash(response)
    assert response.next_action == "prepare_lms_dry_run_execution_plan_without_execution"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_dry_run_execution_runbook_blocks_missing_evidence_and_side_effect_flags() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})

    response = build_lms_package_installation_dry_run_execution_runbook_response(
        command=_runbook_command(
            admission_gate_hash=ZERO_SHA256,
            approval_boundary_hash=ZERO_SHA256,
            approval_record_hash=ZERO_SHA256,
            worker_dispatch_requested=True,
            worker_queue_enqueue_requested=True,
            worker_execution_requested=True,
            package_installation_dry_run_execution_requested=True,
            dry_run_result_persistence_requested=True,
            rollback_execution_requested=True,
            failover_execution_requested=True,
        ),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        package_approval_record_store=InMemoryLmsTenantAdminPackageApprovalRecordStore(),
        dry_run_execution_approval_record_store=InMemoryLmsPackageInstallationDryRunExecutionApprovalRecordStore(),
    )

    assert response.dry_run_execution_runbook_ready is False
    assert response.explicit_human_execution_approval_present is False
    assert response.approval_record_tenant_match is False
    assert response.approval_record_hash_match is False
    assert response.stored_dry_run_execution_approval_record_hash == ZERO_SHA256
    assert "lms_package_installation_readiness_not_ready" in response.blocking_reasons
    assert "package_installation_dry_run_execution_admission_gate_hash_missing" in response.blocking_reasons
    assert "package_installation_dry_run_execution_approval_boundary_hash_missing" in response.blocking_reasons
    assert "lms_dry_run_execution_approval_record_hash_missing" in response.blocking_reasons
    assert "lms_dry_run_execution_approval_record_missing" in response.blocking_reasons
    assert "tenant_admin_role_required" in response.blocking_reasons
    assert "worker_dispatch_request_forbidden" in response.blocking_reasons
    assert "worker_queue_enqueue_request_forbidden" in response.blocking_reasons
    assert "worker_execution_request_forbidden" in response.blocking_reasons
    assert "package_installation_dry_run_execution_request_forbidden" in response.blocking_reasons
    assert "dry_run_result_persistence_request_forbidden" in response.blocking_reasons
    assert "rollback_execution_request_forbidden" in response.blocking_reasons
    assert "failover_execution_request_forbidden" in response.blocking_reasons
    assert response.worker_dispatch_allowed is False
    assert response.worker_queue_enqueued is False
    assert response.worker_execution_allowed is False
    assert response.package_installation_dry_run_execution_allowed is False
    assert response.rollback_execution_allowed is False
    assert response.failover_execution_allowed is False
    assert response.tenant_module_state_created is False
    assert response.destructive_actions_allowed is False
    assert response.next_action == "prepare_lms_dry_run_execution_runbook_without_execution"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None
