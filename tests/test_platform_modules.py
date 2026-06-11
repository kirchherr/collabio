from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleCatalogEntry,
    ModuleDecommissionBlockCommand,
    ModuleDecommissionCompletionCommand,
    ModuleDecommissionRequestCommand,
    ModuleKind,
    ModuleLifecycleError,
    ModuleStatus,
    TenantModuleState,
)

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
DECOMMISSION_EVIDENCE_REFS = {
    "retention_evaluation_ref": "retention:eval-1",
    "legal_hold_check_ref": "legal-hold:check-1",
    "export_archive_decision_ref": "export:decision-1",
    "audit_evidence_ref": "audit:evidence-1",
    "backup_restore_evidence_ref": "backup:restore-1",
}
DECOMMISSION_BLOCKER_EVIDENCE_REFS = {
    "blocker_report_ref": "decommission-blocker:report-1",
    "remediation_plan_ref": "decommission-remediation:plan-1",
}
DECOMMISSION_COMPLETION_EVIDENCE_REFS = {
    "final_retention_disposition_ref": "retention:final-disposition-1",
    "final_legal_hold_clearance_ref": "legal-hold:clearance-1",
    "final_export_archive_manifest_ref": "export:archive-manifest-1",
    "final_audit_closure_ref": "audit:closure-1",
    "final_backup_disposition_ref": "backup:final-disposition-1",
    "final_data_disposition_ref": "data-disposition:final-1",
}


def crm_erp_catalog(status: ModuleStatus = ModuleStatus.INSTALLED) -> ModuleCatalogEntry:
    return ModuleCatalogEntry(
        module_id="crm_erp",
        display_name="CRM/ERP",
        module_version="0.1.0",
        module_kind=ModuleKind.BUSINESS_DOMAIN,
        status=status,
        description="Optional CRM/ERP business module.",
        manifest_hash="sha256:crm-erp-manifest",
        installed_at_utc=NOW,
    )


def tenant_module(status: ModuleStatus, **overrides: object) -> TenantModuleState:
    values: dict[str, object] = {
        "tenant_id": "tenant-1",
        "module_id": "crm_erp",
        "status": status,
        "enabled_features": {"crm_erp.crm.accounts": True},
        "policy_snapshot_hash": "sha256:policy",
        "changed_by": "admin-1",
        "audit_chain_ref": "audit:module-change",
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
    }
    if status == ModuleStatus.ENABLED:
        values["provisioned_at_utc"] = NOW
        values["enabled_at_utc"] = NOW
    if status == ModuleStatus.DISABLED:
        values["provisioned_at_utc"] = NOW
        values["disabled_at_utc"] = NOW
    if status == ModuleStatus.SUSPENDED:
        values["provisioned_at_utc"] = NOW
    if status == ModuleStatus.DECOMMISSION_REQUESTED:
        values["provisioned_at_utc"] = NOW
        values["decommission_requested_at_utc"] = NOW
        values["decommission_evidence_refs"] = DECOMMISSION_EVIDENCE_REFS
        values["enabled_features"] = {"crm_erp.crm.accounts": False}
    if status == ModuleStatus.DECOMMISSION_BLOCKED:
        values["provisioned_at_utc"] = NOW
        values["decommission_requested_at_utc"] = NOW
        values["decommission_blocked_at_utc"] = NOW
        values["decommission_evidence_refs"] = {
            **DECOMMISSION_EVIDENCE_REFS,
            **DECOMMISSION_BLOCKER_EVIDENCE_REFS,
        }
        values["enabled_features"] = {"crm_erp.crm.accounts": False}
    if status == ModuleStatus.DECOMMISSIONED:
        values["provisioned_at_utc"] = NOW
        values["decommission_requested_at_utc"] = NOW
        values["decommissioned_at_utc"] = NOW
        values["decommission_evidence_refs"] = {
            **DECOMMISSION_EVIDENCE_REFS,
            **DECOMMISSION_COMPLETION_EVIDENCE_REFS,
        }
        values["enabled_features"] = {"crm_erp.crm.accounts": False}
    values.update(overrides)
    return TenantModuleState.model_validate(values)


def test_module_catalog_entry_limits_global_statuses_to_deployment_availability() -> None:
    assert crm_erp_catalog().status == ModuleStatus.INSTALLED

    with pytest.raises(ValidationError, match="catalog status"):
        crm_erp_catalog(status=ModuleStatus.ENABLED)


def test_tenant_module_state_requires_audit_policy_hashes_and_status_evidence() -> None:
    state = tenant_module(ModuleStatus.ENABLED)

    assert state.normal_use_enabled
    assert state.feature_enabled("crm_erp.crm.accounts")
    assert state.compliance_access_allowed

    with pytest.raises(ValidationError, match="enabled_at_utc"):
        tenant_module(ModuleStatus.ENABLED, enabled_at_utc=None)

    with pytest.raises(ValidationError, match="namespaced"):
        tenant_module(ModuleStatus.DISABLED, audit_chain_ref="missing-namespace")


def test_tenant_module_feature_ids_must_belong_to_the_module() -> None:
    with pytest.raises(ValidationError, match="belong to the tenant module"):
        tenant_module(ModuleStatus.ENABLED, enabled_features={"knowledge_base.articles": True})

    with pytest.raises(ValidationError, match="namespaced module features"):
        tenant_module(ModuleStatus.ENABLED, enabled_features={"crm_erp": True})


def test_decommission_request_command_requires_complete_namespaced_evidence() -> None:
    command = ModuleDecommissionRequestCommand(
        approval_reference="approval:decommission",
        reason="tenant requested module decommission",
        retention_evaluation_ref="retention:eval-1",
        legal_hold_check_ref="legal-hold:check-1",
        export_archive_decision_ref="export:decision-1",
        audit_evidence_ref="audit:evidence-1",
        backup_restore_evidence_ref="backup:restore-1",
    )

    assert command.evidence_refs() == DECOMMISSION_EVIDENCE_REFS

    with pytest.raises(ValidationError, match="decommission evidence"):
        ModuleDecommissionRequestCommand(
            approval_reference="approval:decommission",
            reason="tenant requested module decommission",
            retention_evaluation_ref="not-namespaced",
            legal_hold_check_ref="legal-hold:check-1",
            export_archive_decision_ref="export:decision-1",
            audit_evidence_ref="audit:evidence-1",
            backup_restore_evidence_ref="backup:restore-1",
        )


def test_decommission_block_and_completion_commands_require_namespaced_evidence() -> None:
    block_command = ModuleDecommissionBlockCommand(
        approval_reference="approval:decommission-block",
        reason="legal hold still blocks completion",
        blocker_report_ref="decommission-blocker:report-1",
        remediation_plan_ref="decommission-remediation:plan-1",
    )
    completion_command = ModuleDecommissionCompletionCommand(
        approval_reference="approval:decommission-complete",
        reason="all final disposition evidence is complete",
        final_retention_disposition_ref="retention:final-disposition-1",
        final_legal_hold_clearance_ref="legal-hold:clearance-1",
        final_export_archive_manifest_ref="export:archive-manifest-1",
        final_audit_closure_ref="audit:closure-1",
        final_backup_disposition_ref="backup:final-disposition-1",
        final_data_disposition_ref="data-disposition:final-1",
    )

    assert block_command.evidence_refs() == DECOMMISSION_BLOCKER_EVIDENCE_REFS
    assert completion_command.evidence_refs() == DECOMMISSION_COMPLETION_EVIDENCE_REFS

    with pytest.raises(ValidationError, match="blocker evidence"):
        ModuleDecommissionBlockCommand(
            approval_reference="approval:decommission-block",
            reason="legal hold still blocks completion",
            blocker_report_ref="not-namespaced",
            remediation_plan_ref="decommission-remediation:plan-1",
        )

    with pytest.raises(ValidationError, match="completion evidence"):
        ModuleDecommissionCompletionCommand(
            approval_reference="approval:decommission-complete",
            reason="all final disposition evidence is complete",
            final_retention_disposition_ref="retention:final-disposition-1",
            final_legal_hold_clearance_ref="legal-hold:clearance-1",
            final_export_archive_manifest_ref="export:archive-manifest-1",
            final_audit_closure_ref="audit:closure-1",
            final_backup_disposition_ref="backup:final-disposition-1",
            final_data_disposition_ref="missing-namespace",
        )


def test_decommission_requested_state_requires_evidence_and_disabled_features() -> None:
    requested = tenant_module(ModuleStatus.DECOMMISSION_REQUESTED)
    assert requested.decommission_evidence_refs == DECOMMISSION_EVIDENCE_REFS
    assert not requested.normal_use_enabled
    assert requested.compliance_access_allowed

    with pytest.raises(ValidationError, match="complete decommission evidence"):
        tenant_module(ModuleStatus.DECOMMISSION_REQUESTED, decommission_evidence_refs={})

    with pytest.raises(ValidationError, match="cannot keep enabled features"):
        tenant_module(
            ModuleStatus.DECOMMISSION_REQUESTED,
            enabled_features={"crm_erp.crm.accounts": True},
        )


def test_decommission_blocked_and_completed_states_require_final_evidence() -> None:
    blocked = tenant_module(ModuleStatus.DECOMMISSION_BLOCKED)
    assert blocked.compliance_access_allowed
    assert blocked.decommission_evidence_refs["blocker_report_ref"] == "decommission-blocker:report-1"

    completed = tenant_module(ModuleStatus.DECOMMISSIONED)
    assert not completed.normal_use_enabled
    assert not completed.compliance_access_allowed
    assert completed.decommission_evidence_refs["final_data_disposition_ref"] == "data-disposition:final-1"

    with pytest.raises(ValidationError, match="blocker evidence"):
        tenant_module(ModuleStatus.DECOMMISSION_BLOCKED, decommission_evidence_refs=DECOMMISSION_EVIDENCE_REFS)

    with pytest.raises(ValidationError, match="final disposition evidence"):
        tenant_module(ModuleStatus.DECOMMISSIONED, decommission_evidence_refs=DECOMMISSION_EVIDENCE_REFS)

    with pytest.raises(ValidationError, match="cannot keep enabled features"):
        tenant_module(
            ModuleStatus.DECOMMISSION_BLOCKED,
            enabled_features={"crm_erp.crm.accounts": True},
        )


def test_module_registry_blocks_unknown_or_not_installed_modules() -> None:
    registry = InMemoryModuleRegistry(catalog_entries=[crm_erp_catalog(status=ModuleStatus.NOT_INSTALLED)])

    with pytest.raises(ModuleLifecycleError, match="not installed"):
        registry.upsert_tenant_module(tenant_module(ModuleStatus.DISABLED))

    empty_registry = InMemoryModuleRegistry()
    with pytest.raises(LookupError, match="Unknown module catalog entry"):
        empty_registry.upsert_tenant_module(tenant_module(ModuleStatus.DISABLED))


def test_module_registry_gates_normal_and_compliance_access() -> None:
    disabled_state = tenant_module(ModuleStatus.DISABLED, enabled_features={"crm_erp.crm.accounts": True})
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[disabled_state],
    )

    with pytest.raises(ModuleLifecycleError, match="not enabled"):
        registry.require_normal_use(tenant_id="tenant-1", module_id="crm_erp", feature_id="crm_erp.crm.accounts")

    compliance_state = registry.require_compliance_access(tenant_id="tenant-1", module_id="crm_erp")
    assert compliance_state.status == ModuleStatus.DISABLED

    enabled_state = tenant_module(ModuleStatus.ENABLED, enabled_features={"crm_erp.crm.accounts": False})
    registry.upsert_tenant_module(enabled_state)

    with pytest.raises(ModuleLifecycleError, match="feature"):
        registry.require_normal_use(tenant_id="tenant-1", module_id="crm_erp", feature_id="crm_erp.crm.accounts")

    registry.upsert_tenant_module(tenant_module(ModuleStatus.ENABLED))
    assert registry.require_normal_use(
        tenant_id="tenant-1",
        module_id="crm_erp",
        feature_id="crm_erp.crm.accounts",
    ).feature_enabled("crm_erp.crm.accounts")


def test_module_registry_lifecycle_transitions_keep_disable_compliance_access() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.AVAILABLE, enabled_features={"crm_erp.crm.accounts": False})],
    )

    with pytest.raises(ModuleLifecycleError, match="provisioned"):
        registry.enable_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:enable-before-provision",
        )

    provisioned = registry.provision_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:provision",
        changed_at_utc=NOW,
    )
    assert provisioned.status == ModuleStatus.DISABLED
    assert not provisioned.normal_use_enabled
    assert provisioned.compliance_access_allowed

    enabled = registry.enable_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:enable",
        enabled_features={"crm_erp.crm.accounts": True},
        changed_at_utc=NOW,
    )
    assert enabled.status == ModuleStatus.ENABLED
    assert enabled.feature_enabled("crm_erp.crm.accounts")

    disabled = registry.disable_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:disable",
        changed_at_utc=NOW,
    )
    assert disabled.status == ModuleStatus.DISABLED
    assert not disabled.normal_use_enabled
    assert disabled.compliance_access_allowed

    suspended = registry.suspend_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:suspend",
        changed_at_utc=NOW,
    )
    assert suspended.status == ModuleStatus.SUSPENDED
    assert suspended.compliance_access_allowed


def test_decommission_check_is_conservative_until_evidence_exists() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.ENABLED)],
    )

    check = registry.decommission_check(tenant_id="tenant-1", module_id="crm_erp")

    assert check.status == ModuleStatus.ENABLED
    assert not check.can_decommission
    assert "module must be disabled or suspended before decommission" in check.blocking_reasons
    assert "Legal Hold check" in check.required_evidence
    assert "backup/restore evidence check" in check.required_evidence


def test_decommission_request_requires_disabled_or_suspended_module_and_complete_evidence() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.ENABLED)],
    )

    with pytest.raises(ModuleLifecycleError, match="disabled or suspended"):
        registry.request_decommission(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:decommission-request",
            decommission_evidence_refs=DECOMMISSION_EVIDENCE_REFS,
            changed_at_utc=NOW,
        )

    registry.upsert_tenant_module(
        tenant_module(
            ModuleStatus.DISABLED,
            provisioned_at_utc=NOW,
            enabled_features={"crm_erp.crm.accounts": True},
        )
    )
    requested = registry.request_decommission(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:decommission-request",
        decommission_evidence_refs=DECOMMISSION_EVIDENCE_REFS,
        changed_at_utc=NOW,
    )

    assert requested.status == ModuleStatus.DECOMMISSION_REQUESTED
    assert requested.decommission_evidence_refs == DECOMMISSION_EVIDENCE_REFS
    assert requested.compliance_access_allowed
    assert requested.enabled_features == {"crm_erp.crm.accounts": False}
    with pytest.raises(ModuleLifecycleError, match="cannot be enabled"):
        registry.enable_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:enable-after-request",
        )
    with pytest.raises(ModuleLifecycleError, match="decommission workflow"):
        registry.disable_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:disable-after-request",
        )


def test_decommission_block_and_complete_workflow_preserves_final_evidence() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.DECOMMISSION_REQUESTED)],
    )

    blocked = registry.block_decommission(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:decommission-block",
        blocker_evidence_refs=DECOMMISSION_BLOCKER_EVIDENCE_REFS,
        changed_at_utc=NOW,
    )

    assert blocked.status == ModuleStatus.DECOMMISSION_BLOCKED
    assert blocked.compliance_access_allowed
    assert not blocked.normal_use_enabled
    assert blocked.decommission_blocked_at_utc == NOW
    assert blocked.decommission_evidence_refs["retention_evaluation_ref"] == "retention:eval-1"
    assert blocked.decommission_evidence_refs["remediation_plan_ref"] == "decommission-remediation:plan-1"

    with pytest.raises(ModuleLifecycleError, match="Missing decommission completion evidence"):
        registry.complete_decommission(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:decommission-complete",
            completion_evidence_refs={},
            changed_at_utc=NOW,
        )

    completed = registry.complete_decommission(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:decommission-complete",
        completion_evidence_refs=DECOMMISSION_COMPLETION_EVIDENCE_REFS,
        changed_at_utc=NOW,
    )

    assert completed.status == ModuleStatus.DECOMMISSIONED
    assert not completed.compliance_access_allowed
    assert completed.decommissioned_at_utc == NOW
    assert completed.decommission_evidence_refs["final_data_disposition_ref"] == "data-disposition:final-1"
    assert completed.decommission_evidence_refs["blocker_report_ref"] == "decommission-blocker:report-1"
    with pytest.raises(ModuleLifecycleError, match="does not allow compliance access"):
        registry.require_compliance_access(tenant_id="tenant-1", module_id="crm_erp")


def test_module_registry_discovery_returns_public_tenant_module_view_only() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[
            tenant_module(ModuleStatus.ENABLED),
            tenant_module(
                ModuleStatus.DISABLED,
                tenant_id="tenant-2",
                disabled_at_utc=NOW,
                enabled_features={"crm_erp.crm.accounts": True},
            ),
        ],
    )

    response = registry.discover_tenant_modules("tenant-1")

    assert response.tenant_id == "tenant-1"
    assert len(response.modules) == 1
    view = response.modules[0]
    assert view.module_id == "crm_erp"
    assert view.display_name == "CRM/ERP"
    assert view.status == ModuleStatus.ENABLED
    assert view.normal_use_enabled
    assert view.compliance_access_allowed
    serialized = view.model_dump(mode="json")
    assert "audit_chain_ref" not in serialized
    assert "policy_snapshot_hash" not in serialized
    assert "changed_by" not in serialized
