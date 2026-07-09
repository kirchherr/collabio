from suite.ai_control_plane.models import UserContext
from suite.platform.module_family_backlog import (
    MODULE_FAMILY_BACKLOG_ENDPOINT,
    MODULE_FAMILY_BACKLOG_RESULT_CONTRACT,
    MODULE_FAMILY_BACKLOG_SCHEMA_VERSION,
    MODULE_FAMILY_NEXT_SLICE_SELECTION_ENDPOINT,
    MODULE_FAMILY_NEXT_SLICE_SELECTION_RESULT_CONTRACT,
    MODULE_FAMILY_NEXT_SLICE_SELECTION_SCHEMA_VERSION,
    build_module_family_backlog_response,
    build_module_family_next_slice_selection_response,
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
    assert response.summary.catalog_registered_count == 4
    assert response.summary.planned_not_installed_count == 1
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

    tasks = families["tasks_activities"]
    assert tasks.backlog_status == "catalog_registered"
    assert tasks.catalog_status == "not_installed"
    assert tasks.tenant_module_status is None
    assert tasks.catalog_entry_present is True
    assert tasks.module_package_installed is False
    assert tasks.installed_in_catalog is False
    assert tasks.module_charter_ready is True
    assert tasks.feature_registry_ready is True
    assert tasks.object_rules_ready is True
    assert tasks.pre_catalog_foundation_ready is False
    assert tasks.first_slice_foundation_ready is False
    assert tasks.runtime_activation_allowed is False
    assert tasks.next_action == "add_tasks_activities_migration_evidence_before_storage_or_api"
    assert "module_catalog_entry_required" in tasks.required_foundation_gates
    assert "backup_restore_evidence_required" in tasks.required_foundation_gates

    tickets = families["tickets_incidents"]
    assert tickets.backlog_status == "catalog_registered"
    assert tickets.catalog_status == "not_installed"
    assert tickets.tenant_module_status is None
    assert tickets.catalog_entry_present is True
    assert tickets.module_package_installed is False
    assert tickets.installed_in_catalog is False
    assert tickets.module_charter_ready is True
    assert tickets.feature_registry_ready is True
    assert tickets.object_rules_ready is True
    assert tickets.pre_catalog_foundation_ready is False
    assert tickets.first_slice_foundation_ready is False
    assert tickets.runtime_activation_allowed is False
    assert tickets.next_action == "prepare_tickets_incidents_activation_dry_run_execution_preflight_without_execution"
    assert "module_catalog_entry_required" in tickets.required_foundation_gates
    assert "backup_restore_evidence_required" in tickets.required_foundation_gates

    planned_family = families["time_tracking"]
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


def test_module_family_next_slice_selection_moves_to_time_tracking_after_ticket_catalog_registration() -> None:
    response = build_module_family_next_slice_selection_response(
        user_context=UserContext(
            tenant_id="tenant-demo",
            user_id="user-demo",
            role_ids={"knowledge-worker"},
            readable_object_ids={"doc-1"},
        ),
        module_registry=default_module_registry(),
    )

    assert response.schema_version == MODULE_FAMILY_NEXT_SLICE_SELECTION_SCHEMA_VERSION
    assert response.tenant_id == "tenant-demo"
    assert response.result_contract == MODULE_FAMILY_NEXT_SLICE_SELECTION_RESULT_CONTRACT
    assert response.endpoint == MODULE_FAMILY_NEXT_SLICE_SELECTION_ENDPOINT
    assert response.backlog_endpoint == MODULE_FAMILY_BACKLOG_ENDPOINT
    assert response.selection_ready is True
    assert response.selected_module_family == "time_tracking"
    assert response.selected_module_id == "time_tracking"
    assert (
        response.selected_next_action == "create_time_tracking_module_charter_then_catalog_entry_before_storage_or_api"
    )
    assert response.next_action == response.selected_next_action
    assert response.lms_depth_deferred is True
    assert response.deferred_module_families == ("knowledge_base", "lms", "tasks_activities", "tickets_incidents")
    assert response.content_included is False
    assert response.module_activation_executed is False
    assert response.persistent_task_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert response.summary.total_family_count == 5
    assert response.summary.active_foundation_count == 1
    assert response.summary.catalog_registered_count == 4
    assert response.summary.planned_candidate_count == 1
    assert response.summary.selected_candidate_count == 1
    assert response.summary.queued_candidate_count == 0
    assert response.summary.lms_depth_deferred_count == 1
    assert response.summary.runtime_activation_allowed_count == 0
    assert response.summary.blocking_reason_count == 0
    assert response.evidence_hash.startswith("sha256:")

    candidates = {candidate.module_family: candidate for candidate in response.candidates}
    assert tuple(candidates) == ("time_tracking",)
    selected = candidates["time_tracking"]
    assert selected.selection_rank == 1
    assert selected.selection_status == "selected_next"
    assert selected.selection_reason == "first_planned_module_family_after_lms_foundation_seal"
    assert selected.next_action == "create_time_tracking_module_charter_then_catalog_entry_before_storage_or_api"
    assert selected.default_feature_gate == "time_tracking.entries.read"
    assert selected.continuity_domain == "time_tracking_records"
    assert selected.runtime_activation_allowed is False
    assert selected.module_activation_executed is False
    assert selected.selection_rank == 1
