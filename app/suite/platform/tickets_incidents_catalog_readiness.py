from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.tickets_incidents_module import (
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
    build_default_tickets_incidents_object_rule_manifest,
    build_default_tickets_incidents_subfeature_registry,
)

TICKETS_INCIDENTS_CATALOG_READINESS_SCHEMA_VERSION = "tickets_incidents_catalog_readiness.v1"
TICKETS_INCIDENTS_CATALOG_READINESS_RESULT_CONTRACT = "metadata_only_tickets_incidents_catalog_readiness_no_activation"
TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT = "/v1/platform/modules/families/tickets-incidents/catalog-readiness"
TICKETS_INCIDENTS_CATALOG_REGISTRATION_NEXT_ACTION = (
    "register_tickets_incidents_catalog_entry_as_not_installed_after_catalog_readiness_review"
)
TICKETS_INCIDENTS_MIGRATION_EVIDENCE_NEXT_ACTION = "add_tickets_incidents_migration_evidence_before_storage_or_api"
TICKETS_INCIDENTS_TENANT_STATE_REVIEW_NEXT_ACTION = "review_tickets_incidents_tenant_state_before_runtime_activation"


class TicketsIncidentsCatalogReadinessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_count: int
    default_enabled_feature_count: int
    approval_required_feature_count: int
    compliance_relevant_feature_count: int
    object_type_count: int
    personal_object_type_count: int
    required_catalog_evidence_count: int


class TicketsIncidentsCatalogReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_CATALOG_READINESS_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_CATALOG_READINESS_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    module_family_backlog_endpoint: str = "/v1/platform/modules/families/backlog"
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    tenant_module_state_present: bool
    catalog_registration_ready: bool
    module_package_installed: bool
    migration_executed: bool = False
    api_routes_registered: bool = False
    business_tables_created: bool = False
    content_included: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    feature_manifest_hash: str
    object_rule_manifest_hash: str
    summary: TicketsIncidentsCatalogReadinessSummary
    required_catalog_evidence: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "module_family_backlog_endpoint",
        "feature_manifest_hash",
        "object_rule_manifest_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents catalog readiness text fields must not be empty")
        return value

    @field_validator("required_catalog_evidence", "evidence_refs")
    @classmethod
    def require_non_empty_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Tickets & Incidents catalog readiness lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents catalog readiness lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents catalog readiness list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_contract(self) -> TicketsIncidentsCatalogReadinessResponse:
        if self.schema_version != TICKETS_INCIDENTS_CATALOG_READINESS_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents catalog readiness schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT:
            raise ValueError("Tickets & Incidents catalog readiness endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_CATALOG_READINESS_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents catalog readiness result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents catalog readiness only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents catalog readiness continuity domain is invalid")
        if (
            self.migration_executed
            or self.api_routes_registered
            or self.business_tables_created
            or self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets & Incidents catalog readiness must remain metadata-only and non-executing")
        if self.catalog_registration_ready != (
            not self.module_catalog_entry_present and not self.tenant_module_state_present
        ):
            raise ValueError(
                "Tickets & Incidents catalog readiness must only be ready before catalog or tenant state exists"
            )
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("Tickets & Incidents catalog readiness package flag must match catalog status")
        if self.summary.required_catalog_evidence_count != len(self.required_catalog_evidence):
            raise ValueError("Tickets & Incidents catalog readiness evidence count must match evidence list")
        return self


def build_tickets_incidents_catalog_readiness_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
) -> TicketsIncidentsCatalogReadinessResponse:
    feature_registry = build_default_tickets_incidents_subfeature_registry()
    object_rule_manifest = build_default_tickets_incidents_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)

    catalog_status = _catalog_status(module_registry=module_registry)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=user_context.tenant_id,
        catalog_known=catalog_status is not None,
    )
    catalog_registration_evidence = (
        (
            "catalog_registration_status_absent_confirmed",
            "migration_plan_or_no_table_decision_recorded",
        )
        if catalog_status is None
        else (
            "catalog_registration_status_not_installed_confirmed",
            "catalog_registration_migration_0051_recorded",
        )
    )
    required_catalog_evidence = (
        "module_charter_reviewed",
        "subfeature_manifest_hash_recorded",
        "object_rule_manifest_hash_recorded",
        "backup_continuity_domain_recorded",
        *catalog_registration_evidence,
        "no_runtime_activation_confirmed",
    )
    return TicketsIncidentsCatalogReadinessResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        catalog_registration_ready=catalog_status is None and tenant_module_status is None,
        feature_manifest_hash=feature_registry.manifest_hash,
        object_rule_manifest_hash=object_rule_manifest.manifest_hash,
        summary=TicketsIncidentsCatalogReadinessSummary(
            feature_count=len(feature_registry.features),
            default_enabled_feature_count=sum(1 for feature in feature_registry.features if feature.default_enabled),
            approval_required_feature_count=sum(
                1 for feature in feature_registry.features if feature.requires_approval
            ),
            compliance_relevant_feature_count=sum(
                1 for feature in feature_registry.features if feature.compliance_relevant
            ),
            object_type_count=len(object_rule_manifest.object_rules),
            personal_object_type_count=sum(
                1 for rule in object_rule_manifest.object_rules if rule.classification.value == "personal"
            ),
            required_catalog_evidence_count=len(required_catalog_evidence),
        ),
        required_catalog_evidence=required_catalog_evidence,
        next_action=_next_action(catalog_status=catalog_status, tenant_module_status=tenant_module_status),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_catalog_readiness.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_tickets_incidents_catalog_readiness.py",
        ),
    )


def _catalog_status(*, module_registry: InMemoryModuleRegistry | PgModuleRegistry) -> str | None:
    try:
        return module_registry.get_catalog_entry(TICKETS_INCIDENTS_MODULE_ID).status.value
    except LookupError:
        return None


def _tenant_module_status(
    *,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    tenant_id: str,
    catalog_known: bool,
) -> str | None:
    if not catalog_known:
        return None
    state = module_registry.get_tenant_module_or_none(tenant_id=tenant_id, module_id=TICKETS_INCIDENTS_MODULE_ID)
    return state.status.value if state is not None else None


def _next_action(*, catalog_status: str | None, tenant_module_status: str | None) -> str:
    if catalog_status is None:
        return TICKETS_INCIDENTS_CATALOG_REGISTRATION_NEXT_ACTION
    if tenant_module_status is not None:
        return TICKETS_INCIDENTS_TENANT_STATE_REVIEW_NEXT_ACTION
    return TICKETS_INCIDENTS_MIGRATION_EVIDENCE_NEXT_ACTION
