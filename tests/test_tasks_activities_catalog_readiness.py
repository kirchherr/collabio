from suite.ai_control_plane.models import UserContext
from suite.platform.modules import InMemoryModuleRegistry, default_module_registry
from suite.platform.tasks_activities_catalog_readiness import (
    TASKS_ACTIVITIES_CATALOG_READINESS_ENDPOINT,
    TASKS_ACTIVITIES_CATALOG_READINESS_RESULT_CONTRACT,
    TASKS_ACTIVITIES_CATALOG_READINESS_SCHEMA_VERSION,
    build_tasks_activities_catalog_readiness_response,
)


def test_tasks_activities_catalog_readiness_declares_metadata_only_registration_boundary() -> None:
    response = build_tasks_activities_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=default_module_registry(),
    )

    assert response.schema_version == TASKS_ACTIVITIES_CATALOG_READINESS_SCHEMA_VERSION
    assert response.endpoint == TASKS_ACTIVITIES_CATALOG_READINESS_ENDPOINT
    assert response.result_contract == TASKS_ACTIVITIES_CATALOG_READINESS_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tasks_activities"
    assert response.continuity_domain == "task_activity_records"
    assert response.catalog_status == "installed"
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is True
    assert response.tenant_module_state_present is False
    assert response.catalog_registration_ready is False
    assert response.module_package_installed is True
    assert response.migration_executed is False
    assert response.api_routes_registered is False
    assert response.business_tables_created is False
    assert response.content_included is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.feature_manifest_hash.startswith("sha256:")
    assert response.object_rule_manifest_hash.startswith("sha256:")
    assert response.summary.feature_count == 6
    assert response.summary.default_enabled_feature_count == 2
    assert response.summary.approval_required_feature_count == 4
    assert response.summary.compliance_relevant_feature_count == 2
    assert response.summary.object_type_count == 2
    assert response.summary.personal_object_type_count == 2
    assert response.summary.required_catalog_evidence_count == len(response.required_catalog_evidence)
    assert "catalog_package_status_installed_confirmed" in response.required_catalog_evidence
    assert "catalog_registration_migration_0050_recorded" in response.required_catalog_evidence
    assert "productive_storage_migration_0059_recorded" in response.required_catalog_evidence
    assert "no_runtime_activation_confirmed" in response.required_catalog_evidence
    assert "app/suite/platform/tasks_activities_catalog_readiness.py" in response.evidence_refs
    assert response.next_action == "provision_tasks_activities_for_tenant_before_runtime_use"


def test_tasks_activities_catalog_readiness_keeps_pre_registration_boundary_for_empty_registry() -> None:
    response = build_tasks_activities_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=InMemoryModuleRegistry(),
    )

    assert response.catalog_status is None
    assert response.module_catalog_entry_present is False
    assert response.catalog_registration_ready is True
    assert "catalog_registration_status_absent_confirmed" in response.required_catalog_evidence
    assert "migration_plan_or_no_table_decision_recorded" in response.required_catalog_evidence
    assert (
        response.next_action
        == "register_tasks_activities_catalog_entry_as_not_installed_after_catalog_readiness_review"
    )


def test_tasks_activities_catalog_readiness_is_tenant_scoped_without_catalog_side_effects() -> None:
    module_registry = default_module_registry()

    first = build_tasks_activities_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
    )
    second = build_tasks_activities_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.feature_manifest_hash == second.feature_manifest_hash
    assert first.object_rule_manifest_hash == second.object_rule_manifest_hash
    assert first.catalog_registration_ready is False
    assert second.catalog_registration_ready is False
    assert first.module_catalog_entry_present is True
    assert second.module_catalog_entry_present is True
    assert module_registry.get_catalog_entry("tasks_activities").status.value == "installed"
