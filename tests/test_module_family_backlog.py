from suite.ai_control_plane.models import UserContext
from suite.platform.module_family_backlog import (
    MODULE_FAMILY_BACKLOG_ENDPOINT,
    MODULE_FAMILY_BACKLOG_RESULT_CONTRACT,
    MODULE_FAMILY_BACKLOG_SCHEMA_VERSION,
    build_module_family_backlog_response,
    load_module_implementation_contract,
)
from suite.platform.modules import default_module_registry


def test_module_family_backlog_loads_canonical_contract() -> None:
    contract = load_module_implementation_contract()

    assert contract.schema_version == "module_implementation_contract.v1"
    assert contract.contract_id == "module_vertical_slice_contract"
    assert contract.backlog_endpoint == MODULE_FAMILY_BACKLOG_ENDPOINT
    assert contract.result_contract == MODULE_FAMILY_BACKLOG_RESULT_CONTRACT
    assert "tenant_context" in contract.required_controls
    assert "backup_restore_domain" in contract.required_controls
    assert "tenant_id" in contract.required_metadata_fields
    assert "legal_hold_state" in contract.required_metadata_fields
    assert {family.module_family for family in contract.future_module_families} == {
        "knowledge_base",
        "lms",
        "tasks_activities",
        "tickets_incidents",
        "time_tracking",
    }


def test_module_family_backlog_is_tenant_scoped_metadata_only_without_activation() -> None:
    response = build_module_family_backlog_response(
        user_context=UserContext(
            tenant_id="tenant-demo",
            user_id="user-demo",
            role_ids={"knowledge-worker"},
            readable_object_ids={"doc-1"},
        ),
        module_registry=default_module_registry(),
    )

    assert response.schema_version == MODULE_FAMILY_BACKLOG_SCHEMA_VERSION
    assert response.tenant_id == "tenant-demo"
    assert response.result_contract == MODULE_FAMILY_BACKLOG_RESULT_CONTRACT
    assert response.endpoint == MODULE_FAMILY_BACKLOG_ENDPOINT
    assert response.content_included is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.summary.total_family_count == 5
    assert response.summary.catalog_registered_count == 2
    assert response.summary.planned_not_installed_count == 3
    assert response.summary.pre_catalog_foundation_ready_count == 0
    assert response.summary.first_slice_foundation_ready_count == 1
    assert response.summary.runtime_activation_allowed_count == 0

    families = {family.module_family: family for family in response.module_families}
    knowledge_base = families["knowledge_base"]
    assert knowledge_base.module_id == "knowledge_base"
    assert knowledge_base.backlog_status == "active_foundation"
    assert knowledge_base.catalog_status == "installed"
    assert knowledge_base.tenant_module_status == "available"
    assert knowledge_base.catalog_entry_present is True
    assert knowledge_base.module_package_installed is True
    assert knowledge_base.installed_in_catalog is True
    assert knowledge_base.module_charter_ready is True
    assert knowledge_base.feature_registry_ready is True
    assert knowledge_base.object_rules_ready is True
    assert knowledge_base.pre_catalog_foundation_ready is False
    assert knowledge_base.first_slice_foundation_ready is True
    assert knowledge_base.runtime_activation_allowed is False
    assert "default_feature_gate:knowledge_base.articles.read" in knowledge_base.required_foundation_gates
    assert "continuity_domain:knowledge_base_content" in knowledge_base.required_foundation_gates

    lms = families["lms"]
    assert lms.backlog_status == "catalog_registered"
    assert lms.catalog_status == "not_installed"
    assert lms.tenant_module_status is None
    assert lms.catalog_entry_present is True
    assert lms.module_package_installed is False
    assert lms.installed_in_catalog is False
    assert lms.module_charter_ready is True
    assert lms.feature_registry_ready is True
    assert lms.object_rules_ready is True
    assert lms.pre_catalog_foundation_ready is False
    assert lms.first_slice_foundation_ready is False
    assert lms.runtime_activation_allowed is False
    assert lms.next_action == "resume_cross_module_backend_slices_without_lms_depth"
    assert "module_catalog_entry_required" in lms.required_foundation_gates
    assert "backup_restore_evidence_required" in lms.required_foundation_gates

    for planned_family_id in {"tasks_activities", "tickets_incidents", "time_tracking"}:
        planned_family = families[planned_family_id]
        assert planned_family.backlog_status == "planned_not_installed"
        assert planned_family.catalog_status is None
        assert planned_family.tenant_module_status is None
        assert planned_family.catalog_entry_present is False
        assert planned_family.module_package_installed is False
        assert planned_family.installed_in_catalog is False
        assert planned_family.module_charter_ready is False
        assert planned_family.feature_registry_ready is False
        assert planned_family.object_rules_ready is False
        assert planned_family.pre_catalog_foundation_ready is False
        assert planned_family.first_slice_foundation_ready is False
        assert planned_family.runtime_activation_allowed is False
        assert "module_catalog_entry_required" in planned_family.required_foundation_gates
        assert "backup_restore_evidence_required" in planned_family.required_foundation_gates
