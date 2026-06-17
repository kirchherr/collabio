from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.module_registry_operations import (
    MODULE_REGISTRY_CONTINUITY_DOMAIN,
    REQUIRED_BACKUP_EVIDENCE_ARTIFACTS,
    build_module_registry_operations_report,
    build_module_registry_operations_report_hash,
    exit_code_for_report,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    default_module_catalog_entries,
    default_module_registry,
    default_tenant_module_seed_states,
)


def test_module_registry_operations_report_covers_seed_worker_audit_and_backup_evidence() -> None:
    registry = default_module_registry()

    report = build_module_registry_operations_report(
        app_registry=registry,
        worker_registry=registry,
        migration_manifest_entries=load_migration_manifest(),
    )

    assert report.schema_version == "module_registry_operations_report.v1"
    assert report.continuity_domain == MODULE_REGISTRY_CONTINUITY_DOMAIN
    assert "tenant_module.enabled" in report.required_lifecycle_audit_event_types
    assert "worker discovery drill report hash" in report.required_backup_evidence_artifacts
    assert "persistent module registry seed/backfill evidence" in REQUIRED_BACKUP_EVIDENCE_ARTIFACTS
    assert report.worker_discovery_ok
    assert report.backfill_required_count == 0
    assert report.repair_required_count == 0
    assert report.evidence_hash == build_module_registry_operations_report_hash(report)
    assert exit_code_for_report(report) == 0

    modules_by_id = {module.module_id: module for module in report.modules}
    assert set(modules_by_id) >= {"crm_erp", "knowledge_base"}
    assert modules_by_id["knowledge_base"].expected_seed_tenants == ("tenant-demo",)
    assert modules_by_id["knowledge_base"].worker_visible_tenants == ("tenant-demo",)
    assert modules_by_id["knowledge_base"].worker_status_counts == {"available": 1}


def test_module_registry_operations_report_flags_missing_seed_backfill() -> None:
    registry_without_seed = InMemoryModuleRegistry(catalog_entries=list(default_module_catalog_entries()))

    report = build_module_registry_operations_report(
        app_registry=registry_without_seed,
        worker_registry=registry_without_seed,
        migration_manifest_entries=load_migration_manifest(),
        expected_seed_states=default_tenant_module_seed_states(),
    )

    assert report.backfill_required_count == 2
    assert report.repair_required_count == 2
    assert exit_code_for_report(report) == 1
    assert any("backfill expected tenant module seed rows" in action for action in report.recommended_actions)

    modules_by_id = {module.module_id: module for module in report.modules}
    assert modules_by_id["crm_erp"].missing_seed_tenants == ("tenant-demo",)
    assert modules_by_id["knowledge_base"].missing_seed_tenants == ("tenant-demo",)
