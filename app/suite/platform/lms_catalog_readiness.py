from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.lms_module import (
    LMS_CONTINUITY_DOMAIN,
    LMS_MODULE_ID,
    build_default_lms_object_rule_manifest,
    build_default_lms_subfeature_registry,
)
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_CATALOG_READINESS_SCHEMA_VERSION = "lms_catalog_readiness.v1"
LMS_CATALOG_READINESS_RESULT_CONTRACT = "metadata_only_lms_catalog_readiness_no_activation"
LMS_CATALOG_READINESS_ENDPOINT = "/v1/platform/modules/families/lms/catalog-readiness"
LMS_CATALOG_READINESS_NEXT_ACTION = "review_lms_catalog_readiness_before_catalog_registration"


class LmsCatalogReadinessSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_count: int
    default_enabled_feature_count: int
    approval_required_feature_count: int
    compliance_relevant_feature_count: int
    object_type_count: int
    personal_object_type_count: int
    required_catalog_evidence_count: int


class LmsCatalogReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_CATALOG_READINESS_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_CATALOG_READINESS_ENDPOINT
    result_contract: str = LMS_CATALOG_READINESS_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
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
    summary: LmsCatalogReadinessSummary
    required_catalog_evidence: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    next_action: str = LMS_CATALOG_READINESS_NEXT_ACTION

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
            raise ValueError("LMS catalog readiness text fields must not be empty")
        return value

    @field_validator("required_catalog_evidence", "evidence_refs")
    @classmethod
    def require_non_empty_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("LMS catalog readiness lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("LMS catalog readiness lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS catalog readiness list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_contract(self) -> LmsCatalogReadinessResponse:
        if self.schema_version != LMS_CATALOG_READINESS_SCHEMA_VERSION:
            raise ValueError("LMS catalog readiness schema version is invalid")
        if self.endpoint != LMS_CATALOG_READINESS_ENDPOINT:
            raise ValueError("LMS catalog readiness endpoint is invalid")
        if self.result_contract != LMS_CATALOG_READINESS_RESULT_CONTRACT:
            raise ValueError("LMS catalog readiness result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS catalog readiness only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS catalog readiness continuity domain is invalid")
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
            raise ValueError("LMS catalog readiness must remain metadata-only and non-executing")
        if self.catalog_registration_ready != (
            not self.module_catalog_entry_present and not self.tenant_module_state_present
        ):
            raise ValueError("LMS catalog readiness must only be ready before catalog or tenant state exists")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("LMS catalog readiness package flag must match catalog status")
        if self.summary.required_catalog_evidence_count != len(self.required_catalog_evidence):
            raise ValueError("LMS catalog readiness evidence count must match evidence list")
        return self


def build_lms_catalog_readiness_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
) -> LmsCatalogReadinessResponse:
    feature_registry = build_default_lms_subfeature_registry()
    object_rule_manifest = build_default_lms_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)

    catalog_status = _catalog_status(module_registry=module_registry)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=user_context.tenant_id,
        catalog_known=catalog_status is not None,
    )
    required_catalog_evidence = (
        "module_charter_reviewed",
        "subfeature_manifest_hash_recorded",
        "object_rule_manifest_hash_recorded",
        "backup_continuity_domain_recorded",
        "migration_plan_or_no_table_decision_recorded",
        "no_runtime_activation_confirmed",
    )
    return LmsCatalogReadinessResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        catalog_registration_ready=catalog_status is None and tenant_module_status is None,
        feature_manifest_hash=feature_registry.manifest_hash,
        object_rule_manifest_hash=object_rule_manifest.manifest_hash,
        summary=LmsCatalogReadinessSummary(
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
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "app/suite/platform/lms_module.py",
            "app/suite/platform/lms_catalog_readiness.py",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_lms_catalog_readiness.py",
        ),
    )


def _catalog_status(*, module_registry: InMemoryModuleRegistry | PgModuleRegistry) -> str | None:
    try:
        return module_registry.get_catalog_entry(LMS_MODULE_ID).status.value
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
    state = module_registry.get_tenant_module_or_none(tenant_id=tenant_id, module_id=LMS_MODULE_ID)
    return state.status.value if state is not None else None
