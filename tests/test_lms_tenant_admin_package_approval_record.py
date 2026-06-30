from datetime import UTC, datetime

import pytest

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.lms_package_installation_readiness import build_lms_package_installation_readiness_response
from suite.platform.lms_tenant_admin_package_approval_gate import (
    build_lms_tenant_admin_package_approval_gate_response,
)
from suite.platform.lms_tenant_admin_package_approval_record import (
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT,
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_ENDPOINT,
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RESULT_CONTRACT,
    LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_SCHEMA_VERSION,
    InMemoryLmsTenantAdminPackageApprovalRecordStore,
    LmsTenantAdminPackageApprovalRecordCommand,
    build_lms_tenant_admin_package_approval_record_hash,
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


def test_lms_tenant_admin_package_approval_record_is_metadata_only_and_non_executing() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    response = build_lms_tenant_admin_package_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.schema_version == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_SCHEMA_VERSION
    assert response.endpoint == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_ENDPOINT
    assert response.result_contract == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "lms"
    assert response.continuity_domain == "lms_training_records"
    assert response.approval_gate_ready is True
    assert response.approval_gate_evidence_hash == approval_gate.evidence_hash
    assert response.lms_restore_drill_evidence_hash == approval_gate.lms_restore_drill_evidence_hash
    assert response.command_hash.startswith("sha256:")
    assert response.idempotency_key_hash.startswith("sha256:")
    assert response.human_confirmation_statement_hash.startswith("sha256:")
    assert response.approver_role_allowed is True
    assert response.record_status == "approved_for_package_installation_execution_gate"
    assert response.approval_record_created is True
    assert response.human_confirmation_captured is True
    assert response.human_confirmation_statement_matched is True
    assert response.future_package_installation_execution_gate_required is True
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
    assert "exact_human_confirmation_statement_hash" in response.required_approval_evidence
    assert "future_package_installation_execution_gate_required" in response.required_approval_evidence
    assert response.blocking_reasons == ()
    assert response.evidence_hash == build_lms_tenant_admin_package_approval_record_hash(response)
    assert response.next_action == "review_lms_package_installation_execution_boundary"
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_approval_record_store_is_idempotent_and_unlocks_readiness_without_execution() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="tenant-admin-1", role_ids={"tenant-admin"})
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    record = build_lms_tenant_admin_package_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )
    store = InMemoryLmsTenantAdminPackageApprovalRecordStore()

    assert store.append(record) == record
    assert store.append(record) == record
    assert (
        store.latest_for_gate(tenant_id="tenant-demo", approval_gate_evidence_hash=approval_gate.evidence_hash)
        == record
    )

    readiness = build_lms_package_installation_readiness_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
        approval_record_store=store,
    )

    assert readiness.human_approval_ready is True
    assert readiness.tenant_admin_approval_record_hash == record.evidence_hash
    assert readiness.package_installation_ready is True
    assert readiness.blocking_reasons == ()
    assert readiness.next_action == "review_lms_package_installation_execution_boundary"
    assert readiness.package_installation_executed is False
    assert readiness.module_activation_executed is False
    assert readiness.tenant_provisioning_allowed is False
    assert readiness.lms_business_api_allowed is False
    assert module_registry.get_tenant_module_or_none(tenant_id="tenant-demo", module_id="lms") is None


def test_lms_approval_record_blocks_non_tenant_admin_without_persistence() -> None:
    module_registry = default_module_registry()
    user_context = UserContext(tenant_id="tenant-demo", user_id="reader-1", role_ids={"knowledge-worker"})
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    response = build_lms_tenant_admin_package_approval_record_response(
        command=_approval_command(approval_gate.evidence_hash),
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert response.approval_record_created is False
    assert response.record_status == "blocked"
    assert "tenant_admin_role_required" in response.blocking_reasons
    with pytest.raises(ValueError, match="blocked"):
        InMemoryLmsTenantAdminPackageApprovalRecordStore().append(response)
