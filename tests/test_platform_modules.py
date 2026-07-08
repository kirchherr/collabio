import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from suite.persistence.migration_catalog import load_migration_manifest
from suite.persistence.migrator import apply_migrations
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleCatalogEntry,
    ModuleDecommissionBlockCommand,
    ModuleDecommissionCancelCommand,
    ModuleDecommissionCompletionCommand,
    ModuleDecommissionReopenCommand,
    ModuleDecommissionRequestCommand,
    ModuleGateSurface,
    ModuleKind,
    ModuleLifecycleError,
    ModuleMigrationEvidence,
    ModuleStatus,
    ModuleWorkerGate,
    PgModuleRegistry,
    TenantModuleState,
    build_default_module_registry,
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
DECOMMISSION_CANCEL_EVIDENCE_REFS = {
    "cancel_approval_ref": "approval:decommission-cancel",
    "cancel_audit_evidence_ref": "audit:decommission-cancel-evidence-1",
}
DECOMMISSION_REOPEN_EVIDENCE_REFS = {
    "reopen_approval_ref": "approval:decommission-reopen",
    "blocker_remediation_evidence_ref": "decommission-remediation:evidence-1",
    "reopen_audit_evidence_ref": "audit:decommission-reopen-evidence-1",
}
MIGRATION_EVIDENCE = (
    ModuleMigrationEvidence(
        version="0007",
        name="platform_module_registry",
        module_id="core",
        checksum="sha256:module-registry",
        evidence_refs=("adr:platform-module-system", "test:platform-module-registry"),
        blocks_startup=True,
    ),
    ModuleMigrationEvidence(
        version="0011",
        name="tenant_module_migration_evidence",
        module_id="core",
        checksum="sha256:module-migration-evidence",
        evidence_refs=("adr:platform-module-system", "test:module-provisioning-migration-evidence"),
        blocks_startup=True,
    ),
)


class LiveDatabase:
    def __init__(self, *, migration_dsn: str, app_dsn: str, worker_dsn: str) -> None:
        self.migration_dsn = migration_dsn
        self.app_dsn = app_dsn
        self.worker_dsn = worker_dsn


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, worker_dsn=worker_dsn)


def crm_erp_catalog(
    status: ModuleStatus = ModuleStatus.INSTALLED,
    *,
    required_migration_versions: tuple[str, ...] = (),
) -> ModuleCatalogEntry:
    return ModuleCatalogEntry(
        module_id="crm_erp",
        display_name="CRM/ERP",
        module_version="0.1.0",
        module_kind=ModuleKind.BUSINESS_DOMAIN,
        status=status,
        description="Optional CRM/ERP business module.",
        manifest_hash="sha256:crm-erp-manifest",
        required_migration_versions=required_migration_versions,
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


def test_decommission_cancel_and_reopen_commands_require_namespaced_evidence() -> None:
    cancel_command = ModuleDecommissionCancelCommand(
        approval_reference="approval:decommission-cancel",
        reason="tenant cancels the decommission workflow",
        cancel_approval_ref="approval:decommission-cancel",
        cancel_audit_evidence_ref="audit:decommission-cancel-evidence-1",
    )
    reopen_command = ModuleDecommissionReopenCommand(
        approval_reference="approval:decommission-reopen",
        reason="blocker has remediation evidence",
        reopen_approval_ref="approval:decommission-reopen",
        blocker_remediation_evidence_ref="decommission-remediation:evidence-1",
        reopen_audit_evidence_ref="audit:decommission-reopen-evidence-1",
    )

    assert cancel_command.evidence_refs() == DECOMMISSION_CANCEL_EVIDENCE_REFS
    assert reopen_command.evidence_refs() == DECOMMISSION_REOPEN_EVIDENCE_REFS

    with pytest.raises(ValidationError, match="cancel evidence"):
        ModuleDecommissionCancelCommand(
            approval_reference="approval:decommission-cancel",
            reason="tenant cancels the decommission workflow",
            cancel_approval_ref="missing-namespace",
            cancel_audit_evidence_ref="audit:decommission-cancel-evidence-1",
        )

    with pytest.raises(ValidationError, match="reopen evidence"):
        ModuleDecommissionReopenCommand(
            approval_reference="approval:decommission-reopen",
            reason="blocker has remediation evidence",
            reopen_approval_ref="approval:decommission-reopen",
            blocker_remediation_evidence_ref="missing-namespace",
            reopen_audit_evidence_ref="audit:decommission-reopen-evidence-1",
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


def test_cancelled_and_reopened_decommission_states_require_evidence() -> None:
    cancelled = tenant_module(
        ModuleStatus.DISABLED,
        enabled_features={"crm_erp.crm.accounts": False},
        decommission_requested_at_utc=NOW,
        decommission_cancelled_at_utc=NOW,
        decommission_evidence_refs={
            **DECOMMISSION_EVIDENCE_REFS,
            **DECOMMISSION_CANCEL_EVIDENCE_REFS,
        },
    )
    reopened = tenant_module(
        ModuleStatus.DECOMMISSION_REQUESTED,
        decommission_blocked_at_utc=NOW,
        decommission_reopened_at_utc=NOW,
        decommission_evidence_refs={
            **DECOMMISSION_EVIDENCE_REFS,
            **DECOMMISSION_BLOCKER_EVIDENCE_REFS,
            **DECOMMISSION_REOPEN_EVIDENCE_REFS,
        },
    )

    assert cancelled.decommission_cancelled_at_utc == NOW
    assert reopened.decommission_reopened_at_utc == NOW

    with pytest.raises(ValidationError, match="cancel evidence"):
        tenant_module(
            ModuleStatus.DISABLED,
            enabled_features={"crm_erp.crm.accounts": False},
            decommission_requested_at_utc=NOW,
            decommission_cancelled_at_utc=NOW,
            decommission_evidence_refs=DECOMMISSION_EVIDENCE_REFS,
        )

    with pytest.raises(ValidationError, match="cannot keep enabled features"):
        tenant_module(
            ModuleStatus.DISABLED,
            decommission_requested_at_utc=NOW,
            decommission_cancelled_at_utc=NOW,
            decommission_evidence_refs={
                **DECOMMISSION_EVIDENCE_REFS,
                **DECOMMISSION_CANCEL_EVIDENCE_REFS,
            },
        )

    with pytest.raises(ValidationError, match="reopen evidence"):
        tenant_module(
            ModuleStatus.DECOMMISSION_REQUESTED,
            decommission_blocked_at_utc=NOW,
            decommission_reopened_at_utc=NOW,
            decommission_evidence_refs={
                **DECOMMISSION_EVIDENCE_REFS,
                **DECOMMISSION_BLOCKER_EVIDENCE_REFS,
            },
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


def test_module_registry_server_side_api_gates_require_status_and_feature_flags() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.ENABLED, enabled_features={"crm_erp.crm.accounts": True})],
    )

    decision = registry.require_module_gate(
        tenant_id="tenant-1",
        module_id="crm_erp",
        surface=ModuleGateSurface.NORMAL_API,
        feature_id="crm_erp.crm.accounts",
    )

    assert decision.surface == ModuleGateSurface.NORMAL_API
    assert decision.status == ModuleStatus.ENABLED
    assert decision.feature_id == "crm_erp.crm.accounts"
    assert decision.normal_use_enabled
    assert decision.compliance_access_allowed

    with pytest.raises(ModuleLifecycleError, match="does not belong"):
        registry.require_module_gate(
            tenant_id="tenant-1",
            module_id="crm_erp",
            surface=ModuleGateSurface.NORMAL_API,
            feature_id="knowledge_base.articles",
        )

    registry.upsert_tenant_module(tenant_module(ModuleStatus.ENABLED, enabled_features={"crm_erp.crm.accounts": False}))
    with pytest.raises(ModuleLifecycleError, match="feature"):
        registry.require_module_gate(
            tenant_id="tenant-1",
            module_id="crm_erp",
            surface=ModuleGateSurface.NORMAL_API,
            feature_id="crm_erp.crm.accounts",
        )

    registry.upsert_tenant_module(tenant_module(ModuleStatus.DISABLED, enabled_features={"crm_erp.crm.accounts": True}))
    with pytest.raises(ModuleLifecycleError, match="not enabled"):
        registry.require_module_gate(
            tenant_id="tenant-1",
            module_id="crm_erp",
            surface=ModuleGateSurface.NORMAL_API,
            feature_id="crm_erp.crm.accounts",
        )

    compliance_decision = registry.require_module_gate(
        tenant_id="tenant-1",
        module_id="crm_erp",
        surface=ModuleGateSurface.COMPLIANCE_API,
    )
    assert compliance_decision.surface == ModuleGateSurface.COMPLIANCE_API
    assert not compliance_decision.normal_use_enabled
    assert compliance_decision.compliance_access_allowed


def test_module_worker_gate_stops_feature_workers_but_allows_compliance_workers() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.DISABLED, enabled_features={"crm_erp.crm.accounts": True})],
    )
    gate = ModuleWorkerGate(registry)

    with pytest.raises(ModuleLifecycleError, match="not enabled"):
        gate.require_feature_worker(
            tenant_id="tenant-1",
            module_id="crm_erp",
            feature_id="crm_erp.crm.accounts",
        )

    compliance_decision = gate.require_compliance_worker(tenant_id="tenant-1", module_id="crm_erp")
    assert compliance_decision.surface == ModuleGateSurface.COMPLIANCE_WORKER
    assert compliance_decision.compliance_access_allowed

    registry.upsert_tenant_module(tenant_module(ModuleStatus.DECOMMISSIONED))
    with pytest.raises(ModuleLifecycleError, match="does not allow compliance access"):
        gate.require_compliance_worker(tenant_id="tenant-1", module_id="crm_erp")


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


def test_module_provisioning_requires_startup_migration_manifest_evidence() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog(required_migration_versions=("0007", "0011"))],
        tenant_modules=[tenant_module(ModuleStatus.AVAILABLE, enabled_features={"crm_erp.crm.accounts": False})],
    )

    with pytest.raises(ModuleLifecycleError, match="Missing startup migrations"):
        registry.provision_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:provision",
            changed_at_utc=NOW,
        )

    with pytest.raises(ModuleLifecycleError, match="0011"):
        registry.provision_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:provision",
            migration_manifest_entries=MIGRATION_EVIDENCE[:1],
            changed_at_utc=NOW,
        )

    provisioned = registry.provision_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:provision",
        migration_manifest_entries=MIGRATION_EVIDENCE,
        changed_at_utc=NOW,
    )

    assert provisioned.status == ModuleStatus.DISABLED
    assert [evidence.version for evidence in provisioned.migration_evidence] == ["0007", "0011"]
    assert provisioned.migration_evidence[0].evidence_refs

    stale_registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog(required_migration_versions=("0007", "0011"))],
        tenant_modules=[tenant_module(ModuleStatus.DISABLED, enabled_features={"crm_erp.crm.accounts": False})],
    )
    with pytest.raises(ModuleLifecycleError, match="missing evidence"):
        stale_registry.enable_tenant_module(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:enable",
        )


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


def test_decommission_cancel_returns_to_disabled_and_allows_explicit_reenable() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.DECOMMISSION_REQUESTED)],
    )

    cancelled = registry.cancel_decommission(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:decommission-cancel",
        cancel_evidence_refs=DECOMMISSION_CANCEL_EVIDENCE_REFS,
        changed_at_utc=NOW,
    )

    assert cancelled.status == ModuleStatus.DISABLED
    assert cancelled.decommission_cancelled_at_utc == NOW
    assert cancelled.compliance_access_allowed
    assert not cancelled.normal_use_enabled
    assert cancelled.enabled_features == {"crm_erp.crm.accounts": False}
    assert cancelled.decommission_evidence_refs["cancel_approval_ref"] == "approval:decommission-cancel"

    reenabled = registry.enable_tenant_module(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:enable-after-cancel",
        enabled_features={"crm_erp.crm.accounts": True},
        changed_at_utc=NOW,
    )

    assert reenabled.status == ModuleStatus.ENABLED
    assert reenabled.feature_enabled("crm_erp.crm.accounts")
    assert reenabled.decommission_cancelled_at_utc == NOW


def test_decommission_reopen_moves_blocked_workflow_back_to_requested() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[tenant_module(ModuleStatus.DECOMMISSION_BLOCKED)],
    )

    with pytest.raises(ModuleLifecycleError, match="Missing decommission reopen evidence"):
        registry.reopen_decommission(
            tenant_id="tenant-1",
            module_id="crm_erp",
            policy_snapshot_hash="sha256:policy",
            changed_by="admin-1",
            audit_chain_ref="audit:decommission-reopen",
            reopen_evidence_refs={},
            changed_at_utc=NOW,
        )

    reopened = registry.reopen_decommission(
        tenant_id="tenant-1",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:decommission-reopen",
        reopen_evidence_refs=DECOMMISSION_REOPEN_EVIDENCE_REFS,
        changed_at_utc=NOW,
    )

    assert reopened.status == ModuleStatus.DECOMMISSION_REQUESTED
    assert reopened.decommission_reopened_at_utc == NOW
    assert reopened.compliance_access_allowed
    assert not reopened.normal_use_enabled
    assert reopened.decommission_evidence_refs["blocker_remediation_evidence_ref"] == (
        "decommission-remediation:evidence-1"
    )
    assert reopened.decommission_evidence_refs["blocker_report_ref"] == "decommission-blocker:report-1"

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
    assert completed.decommission_reopened_at_utc == NOW
    assert completed.decommission_evidence_refs["reopen_audit_evidence_ref"] == "audit:decommission-reopen-evidence-1"


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


def test_module_registry_lists_tenant_modules_for_worker_selection() -> None:
    registry = InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog()],
        tenant_modules=[
            tenant_module(ModuleStatus.DISABLED, tenant_id="tenant-b", disabled_at_utc=NOW),
            tenant_module(ModuleStatus.ENABLED, tenant_id="tenant-a"),
        ],
    )

    states = registry.list_tenant_modules_for_module("crm_erp")

    assert [state.tenant_id for state in states] == ["tenant-a", "tenant-b"]
    with pytest.raises(LookupError, match="Unknown module catalog entry"):
        registry.list_tenant_modules_for_module("knowledge_base")


def test_build_default_module_registry_selects_backend_from_env() -> None:
    assert isinstance(build_default_module_registry({}), InMemoryModuleRegistry)

    registry = build_default_module_registry(
        {
            "SUITE_MODULE_REGISTRY_BACKEND": "postgres",
            "SUITE_MODULE_REGISTRY_DSN": "postgresql://example",
        }
    )

    assert isinstance(registry, PgModuleRegistry)
    with pytest.raises(ValueError, match="PostgreSQL module registry"):
        build_default_module_registry({"SUITE_MODULE_REGISTRY_BACKEND": "postgres"})


def test_pg_module_registry_reads_seeded_catalog_and_demo_tenant_state(live_database: LiveDatabase) -> None:
    registry = PgModuleRegistry(database_dsn=live_database.app_dsn)

    crm_erp_catalog_entry = registry.get_catalog_entry("crm_erp")
    knowledge_base_catalog = registry.get_catalog_entry("knowledge_base")
    lms_catalog = registry.get_catalog_entry("lms")
    tasks_catalog = registry.get_catalog_entry("tasks_activities")
    tickets_catalog = registry.get_catalog_entry("tickets_incidents")
    response = registry.discover_tenant_modules("tenant-demo")
    module_ids = {module.module_id for module in response.modules}

    assert crm_erp_catalog_entry.required_migration_versions[-11:] == (
        "0034",
        "0035",
        "0036",
        "0037",
        "0038",
        "0039",
        "0040",
        "0041",
        "0042",
        "0043",
        "0044",
    )
    assert knowledge_base_catalog.required_migration_versions[-5:] == ("0025", "0026", "0027", "0028", "0029")
    assert lms_catalog.status == ModuleStatus.NOT_INSTALLED
    assert lms_catalog.required_migration_versions == ("0045", "0046", "0047", "0048", "0049")
    assert tasks_catalog.status == ModuleStatus.NOT_INSTALLED
    assert tasks_catalog.required_migration_versions == ("0050",)
    assert tickets_catalog.status == ModuleStatus.NOT_INSTALLED
    assert tickets_catalog.required_migration_versions == ("0051",)
    assert module_ids >= {"crm_erp", "knowledge_base"}
    assert "lms" not in module_ids
    assert "tasks_activities" not in module_ids
    assert "tickets_incidents" not in module_ids
    assert all(module.status == ModuleStatus.AVAILABLE for module in response.modules)


def test_pg_module_registry_lifecycle_and_worker_gate_share_persistent_state(
    live_database: LiveDatabase,
) -> None:
    tenant_id = f"tenant-pg-module-registry-{uuid4().hex}"
    app_registry = PgModuleRegistry(database_dsn=live_database.app_dsn)
    worker_registry = PgModuleRegistry(database_dsn=live_database.worker_dsn)

    provisioned = app_registry.provision_tenant_module(
        tenant_id=tenant_id,
        module_id="knowledge_base",
        policy_snapshot_hash="sha256:pg-module-policy",
        changed_by="tenant-admin",
        audit_chain_ref="audit:pg-module-provision",
        enabled_features={"knowledge_base.articles.read": True},
        migration_manifest_entries=load_migration_manifest(),
        changed_at_utc=NOW,
    )
    compliance_decision = ModuleWorkerGate(worker_registry).require_compliance_worker(
        tenant_id=tenant_id,
        module_id="knowledge_base",
    )
    enabled = app_registry.enable_tenant_module(
        tenant_id=tenant_id,
        module_id="knowledge_base",
        policy_snapshot_hash="sha256:pg-module-policy",
        changed_by="tenant-admin",
        audit_chain_ref="audit:pg-module-enable",
        enabled_features={"knowledge_base.articles.read": True},
        changed_at_utc=NOW,
    )
    feature_decision = app_registry.require_module_gate(
        tenant_id=tenant_id,
        module_id="knowledge_base",
        surface=ModuleGateSurface.NORMAL_API,
        feature_id="knowledge_base.articles.read",
    )
    worker_candidates = worker_registry.list_tenant_modules_for_module("knowledge_base")

    assert provisioned.status == ModuleStatus.DISABLED
    assert {evidence.version for evidence in provisioned.migration_evidence} >= {"0026", "0027", "0028", "0029"}
    assert compliance_decision.surface == ModuleGateSurface.COMPLIANCE_WORKER
    assert compliance_decision.status == ModuleStatus.DISABLED
    assert enabled.status == ModuleStatus.ENABLED
    assert feature_decision.normal_use_enabled
    assert any(state.tenant_id == tenant_id and state.status == ModuleStatus.ENABLED for state in worker_candidates)
