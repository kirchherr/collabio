import pytest

from suite.ai_control_plane.models import UserContext
from suite.platform.modules import default_module_registry
from suite.platform.tickets_incidents_catalog_readiness import (
    TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT,
    TICKETS_INCIDENTS_CATALOG_READINESS_RESULT_CONTRACT,
    TICKETS_INCIDENTS_CATALOG_READINESS_SCHEMA_VERSION,
    build_tickets_incidents_catalog_readiness_response,
)


def test_tickets_incidents_catalog_readiness_declares_metadata_only_registration_boundary() -> None:
    module_registry = default_module_registry()
    response = build_tickets_incidents_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-demo", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
    )

    assert response.schema_version == TICKETS_INCIDENTS_CATALOG_READINESS_SCHEMA_VERSION
    assert response.endpoint == TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT
    assert response.result_contract == TICKETS_INCIDENTS_CATALOG_READINESS_RESULT_CONTRACT
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "tickets_incidents"
    assert response.continuity_domain == "ticket_incident_records"
    assert response.catalog_status is None
    assert response.tenant_module_status is None
    assert response.module_catalog_entry_present is False
    assert response.tenant_module_state_present is False
    assert response.catalog_registration_ready is True
    assert response.module_package_installed is False
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
    assert response.summary.feature_count == 5
    assert response.summary.default_enabled_feature_count == 2
    assert response.summary.approval_required_feature_count == 3
    assert response.summary.compliance_relevant_feature_count == 1
    assert response.summary.object_type_count == 2
    assert response.summary.personal_object_type_count == 2
    assert response.summary.required_catalog_evidence_count == len(response.required_catalog_evidence)
    assert "catalog_registration_status_absent_confirmed" in response.required_catalog_evidence
    assert "migration_plan_or_no_table_decision_recorded" in response.required_catalog_evidence
    assert "no_runtime_activation_confirmed" in response.required_catalog_evidence
    assert "app/suite/platform/tickets_incidents_catalog_readiness.py" in response.evidence_refs
    assert "app/suite/platform/tickets_incidents_module.py" in response.evidence_refs
    assert "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md" in response.evidence_refs
    assert (
        response.next_action
        == "register_tickets_incidents_catalog_entry_as_not_installed_after_catalog_readiness_review"
    )

    with pytest.raises(LookupError):
        module_registry.get_catalog_entry("tickets_incidents")


def test_tickets_incidents_catalog_readiness_is_tenant_scoped_without_catalog_side_effects() -> None:
    module_registry = default_module_registry()

    first = build_tickets_incidents_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-a", user_id="u-1", role_ids={"admin"}),
        module_registry=module_registry,
    )
    second = build_tickets_incidents_catalog_readiness_response(
        user_context=UserContext(tenant_id="tenant-b", user_id="u-2", role_ids={"admin"}),
        module_registry=module_registry,
    )

    assert first.tenant_id == "tenant-a"
    assert second.tenant_id == "tenant-b"
    assert first.feature_manifest_hash == second.feature_manifest_hash
    assert first.object_rule_manifest_hash == second.object_rule_manifest_hash
    assert first.catalog_registration_ready is True
    assert second.catalog_registration_ready is True
    assert first.module_catalog_entry_present is False
    assert second.module_catalog_entry_present is False
    with pytest.raises(LookupError):
        module_registry.get_catalog_entry("tickets_incidents")
