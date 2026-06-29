from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import (
    CRM_ERP_MODULE_ID,
    OBJECT_TYPE_PATTERN,
    RETENTION_POLICY_PATTERN,
    CrmErpLegacyMappingManifest,
    default_crm_erp_target_profiles,
)

FEATURE_ID_PATTERN = re.compile(r"^crm_erp\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
WORKER_SURFACES = frozenset({"normal_api", "compliance_api", "feature_worker", "compliance_worker"})


class CrmErpSubfeatureRegistryError(ValueError):
    pass


class CrmErpSubfeatureArea(StrEnum):
    CRM = "crm"
    ERP = "erp"
    LEGACY_IMPORT = "legacy_import"
    COMPLIANCE = "compliance"
    SEARCH = "search"
    SEARCH_AI = "search_ai"


class CrmErpSubfeatureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    display_name: str
    area: CrmErpSubfeatureArea
    default_enabled: bool
    requires_approval: bool
    compliance_relevant: bool = False
    object_types: tuple[str, ...]
    data_classes: tuple[DataClass, ...]
    retention_policy_ids: tuple[str, ...]
    worker_surfaces: tuple[str, ...]
    dependency_feature_ids: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    schema_version: str = "crm_erp_subfeature.v1"

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("CRM/ERP subfeature IDs must be fully qualified with crm_erp")
        return value

    @field_validator("display_name")
    @classmethod
    def require_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be empty")
        return value

    @field_validator("object_types")
    @classmethod
    def validate_object_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("subfeature must declare at least one object type")
        if len(set(value)) != len(value):
            raise ValueError("subfeature object types must be unique")
        for object_type in value:
            if not OBJECT_TYPE_PATTERN.fullmatch(object_type):
                raise ValueError("subfeature object types must be namespaced")
        return value

    @field_validator("data_classes")
    @classmethod
    def validate_data_classes(cls, value: tuple[DataClass, ...]) -> tuple[DataClass, ...]:
        if not value:
            raise ValueError("subfeature must declare at least one data class")
        if len(set(value)) != len(value):
            raise ValueError("subfeature data classes must be unique")
        return value

    @field_validator("retention_policy_ids")
    @classmethod
    def validate_retention_policy_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("subfeature must declare at least one retention policy")
        if len(set(value)) != len(value):
            raise ValueError("subfeature retention policies must be unique")
        for retention_policy_id in value:
            if not RETENTION_POLICY_PATTERN.fullmatch(retention_policy_id):
                raise ValueError("subfeature retention policies must be policy-style references")
        return value

    @field_validator("worker_surfaces")
    @classmethod
    def validate_worker_surfaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("subfeature must declare at least one worker/API surface")
        unknown_surfaces = sorted(set(value) - WORKER_SURFACES)
        if unknown_surfaces:
            raise ValueError(f"unknown subfeature worker surfaces: {', '.join(unknown_surfaces)}")
        return value

    @field_validator("dependency_feature_ids")
    @classmethod
    def validate_dependency_feature_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("dependency feature IDs must be unique")
        for feature_id in value:
            if not FEATURE_ID_PATTERN.fullmatch(feature_id):
                raise ValueError("dependency feature IDs must be fully qualified with crm_erp")
        return value

    @field_validator("evidence_required")
    @classmethod
    def validate_evidence_required(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("evidence requirements must be unique")
        for evidence in value:
            if not evidence.strip():
                raise ValueError("evidence requirements must not be empty")
        return value

    @model_validator(mode="after")
    def require_approval_for_high_risk_features(self) -> Self:
        high_risk_area = self.area in {CrmErpSubfeatureArea.LEGACY_IMPORT, CrmErpSubfeatureArea.SEARCH_AI}
        if high_risk_area and not self.requires_approval:
            raise ValueError("legacy import and AI subfeatures require approval")
        if self.compliance_relevant and "compliance_worker" not in self.worker_surfaces:
            raise ValueError("compliance-relevant subfeatures must declare compliance_worker surface")
        if self.feature_id in self.dependency_feature_ids:
            raise ValueError("subfeature cannot depend on itself")
        return self


class CrmErpSubfeatureRegistryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = CRM_ERP_MODULE_ID
    registry_version: str = "crm_erp_subfeatures.v1"
    features: tuple[CrmErpSubfeatureDefinition, ...]
    manifest_hash: str
    schema_version: str = "crm_erp_subfeature_registry.v1"

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("CRM/ERP subfeature registry only applies to crm_erp")
        return value

    @field_validator("registry_version")
    @classmethod
    def require_registry_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("registry_version must not be empty")
        return value

    @model_validator(mode="after")
    def require_complete_registry(self) -> Self:
        if not self.features:
            raise ValueError("CRM/ERP subfeature registry requires features")
        feature_ids = [feature.feature_id for feature in self.features]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("CRM/ERP subfeature IDs must be unique")
        feature_id_set = set(feature_ids)
        for feature in self.features:
            unknown_dependencies = sorted(set(feature.dependency_feature_ids) - feature_id_set)
            if unknown_dependencies:
                raise ValueError(f"unknown CRM/ERP subfeature dependencies: {', '.join(unknown_dependencies)}")
        return self

    @property
    def enabled_feature_defaults(self) -> dict[str, bool]:
        return {feature.feature_id: feature.default_enabled for feature in self.features}

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(feature.feature_id for feature in self.features)

    def feature(self, feature_id: str) -> CrmErpSubfeatureDefinition:
        for feature in self.features:
            if feature.feature_id == feature_id:
                return feature
        raise LookupError(f"Unknown CRM/ERP subfeature: {feature_id}")

    def feature_for_object_type(self, object_type: str) -> CrmErpSubfeatureDefinition:
        for feature in self.features:
            if object_type in feature.object_types:
                return feature
        raise LookupError(f"No CRM/ERP subfeature covers object type: {object_type}")

    def validate_mapping_manifest(self, mapping_manifest: CrmErpLegacyMappingManifest) -> None:
        if mapping_manifest.module_id != self.module_id:
            raise CrmErpSubfeatureRegistryError("mapping manifest module does not match subfeature registry")
        feature_ids = set(self.feature_ids)
        for decision in mapping_manifest.decisions:
            if decision.feature_id not in feature_ids:
                raise CrmErpSubfeatureRegistryError(
                    f"mapping decision references unknown subfeature: {decision.feature_id}"
                )
            feature = self.feature(decision.feature_id)
            if decision.target_object_type not in feature.object_types:
                raise CrmErpSubfeatureRegistryError(
                    f"mapping decision target {decision.target_object_type} is not covered by {decision.feature_id}"
                )
            if decision.classification not in feature.data_classes:
                raise CrmErpSubfeatureRegistryError(
                    f"mapping decision class {decision.classification} is not covered by {decision.feature_id}"
                )
            if decision.retention_policy_id not in feature.retention_policy_ids:
                raise CrmErpSubfeatureRegistryError(
                    f"mapping decision retention {decision.retention_policy_id} is not covered by {decision.feature_id}"
                )


def build_default_crm_erp_subfeature_registry() -> CrmErpSubfeatureRegistryManifest:
    draft = CrmErpSubfeatureRegistryManifest(
        features=(
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.crm.accounts",
                display_name="CRM accounts",
                area=CrmErpSubfeatureArea.CRM,
                default_enabled=True,
                requires_approval=False,
                object_types=("crm.account",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.crm.contacts",
                display_name="CRM contacts",
                area=CrmErpSubfeatureArea.CRM,
                default_enabled=True,
                requires_approval=False,
                object_types=("crm.contact",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.crm.activities",
                display_name="CRM activities",
                area=CrmErpSubfeatureArea.CRM,
                default_enabled=True,
                requires_approval=False,
                object_types=("crm.activity", "crm.note"),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.erp.products",
                display_name="ERP products",
                area=CrmErpSubfeatureArea.ERP,
                default_enabled=True,
                requires_approval=False,
                object_types=("erp.product",),
                data_classes=(DataClass.INTERNAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.erp.suppliers",
                display_name="ERP suppliers",
                area=CrmErpSubfeatureArea.ERP,
                default_enabled=True,
                requires_approval=False,
                object_types=("erp.supplier",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.erp.orders",
                display_name="ERP orders",
                area=CrmErpSubfeatureArea.ERP,
                default_enabled=True,
                requires_approval=False,
                object_types=("erp.order", "erp.order_item", "erp.delivery_note", "erp.contract"),
                data_classes=(DataClass.GOBD,),
                retention_policy_ids=("rp-gobd-10y", "rp-legal-hold", "rp-export-10y"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.erp.invoices",
                display_name="ERP invoices",
                area=CrmErpSubfeatureArea.ERP,
                default_enabled=True,
                requires_approval=False,
                object_types=("erp.invoice", "erp.invoice_item"),
                data_classes=(DataClass.GOBD,),
                retention_policy_ids=("rp-gobd-10y", "rp-legal-hold", "rp-export-10y"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.legacy_import.sqlserver",
                display_name="SQL Server legacy import",
                area=CrmErpSubfeatureArea.LEGACY_IMPORT,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=("legacy.row",),
                data_classes=(DataClass.CONFIDENTIAL,),
                retention_policy_ids=("rp-restricted", "rp-legal-hold"),
                worker_surfaces=("compliance_api", "compliance_worker"),
                evidence_required=(
                    "legacy_sql_discovery_manifest",
                    "legacy_sql_mapping_manifest",
                    "legacy_sql_import_evidence_plan",
                ),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.gobd_export",
                display_name="GoBD export",
                area=CrmErpSubfeatureArea.COMPLIANCE,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=(
                    "erp.order",
                    "erp.order_item",
                    "erp.invoice",
                    "erp.invoice_item",
                    "erp.delivery_note",
                    "erp.contract",
                ),
                data_classes=(DataClass.GOBD, DataClass.LEGAL_HOLD),
                retention_policy_ids=("rp-export-10y", "rp-gobd-10y", "rp-legal-hold"),
                worker_surfaces=("compliance_api", "compliance_worker"),
                evidence_required=("export_archive_decision", "audit_evidence"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.legal_hold",
                display_name="CRM/ERP legal hold",
                area=CrmErpSubfeatureArea.COMPLIANCE,
                default_enabled=True,
                requires_approval=True,
                compliance_relevant=True,
                object_types=tuple(sorted(default_crm_erp_target_profiles())),
                data_classes=(DataClass.PERSONAL, DataClass.CONFIDENTIAL, DataClass.GOBD, DataClass.LEGAL_HOLD),
                retention_policy_ids=("rp-legal-hold", "rp-gobd-10y", "rp-restricted", "rp-standard"),
                worker_surfaces=("compliance_api", "compliance_worker"),
                evidence_required=("legal_hold_check", "audit_evidence"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.search.keyword",
                display_name="CRM/ERP keyword search",
                area=CrmErpSubfeatureArea.SEARCH,
                default_enabled=True,
                requires_approval=False,
                object_types=(
                    "crm.account",
                    "crm.contact",
                    "crm.activity",
                    "crm.note",
                    "erp.product",
                    "erp.order",
                    "erp.invoice",
                ),
                data_classes=(DataClass.PERSONAL, DataClass.INTERNAL, DataClass.GOBD),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-gobd-10y", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
                dependency_feature_ids=(
                    "crm_erp.crm.accounts",
                    "crm_erp.crm.contacts",
                    "crm_erp.crm.activities",
                    "crm_erp.erp.products",
                    "crm_erp.erp.orders",
                    "crm_erp.erp.invoices",
                ),
                evidence_required=(
                    "authoritative_acl_validation",
                    "search_audit_event",
                    "metadata_only_result_contract",
                ),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.rag_indexing",
                display_name="CRM/ERP RAG indexing",
                area=CrmErpSubfeatureArea.SEARCH_AI,
                default_enabled=False,
                requires_approval=True,
                object_types=tuple(sorted(default_crm_erp_target_profiles())),
                data_classes=(DataClass.PERSONAL, DataClass.CONFIDENTIAL, DataClass.GOBD, DataClass.INTERNAL),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-gobd-10y", "rp-legal-hold"),
                worker_surfaces=("feature_worker",),
                dependency_feature_ids=(
                    "crm_erp.crm.accounts",
                    "crm_erp.crm.contacts",
                    "crm_erp.crm.activities",
                    "crm_erp.erp.products",
                    "crm_erp.erp.suppliers",
                    "crm_erp.erp.orders",
                    "crm_erp.erp.invoices",
                ),
                evidence_required=("source_resolver_acl_trace", "search_audit_event"),
            ),
            CrmErpSubfeatureDefinition(
                feature_id="crm_erp.ai_assist",
                display_name="CRM/ERP AI assist",
                area=CrmErpSubfeatureArea.SEARCH_AI,
                default_enabled=False,
                requires_approval=True,
                object_types=tuple(sorted(default_crm_erp_target_profiles())),
                data_classes=(DataClass.PERSONAL, DataClass.CONFIDENTIAL, DataClass.GOBD, DataClass.INTERNAL),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-gobd-10y", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
                dependency_feature_ids=("crm_erp.rag_indexing",),
                evidence_required=("tenant_ai_policy", "local_llm_gateway_audit", "human_approval_policy"),
            ),
        ),
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_subfeature_registry(draft, exclude_manifest_hash=True)})


def default_crm_erp_subfeature_enabled_features() -> dict[str, bool]:
    return build_default_crm_erp_subfeature_registry().enabled_feature_defaults


def crm_erp_subfeature_registry_summary(registry: CrmErpSubfeatureRegistryManifest) -> dict[str, object]:
    approval_required_count = sum(1 for feature in registry.features if feature.requires_approval)
    default_enabled_count = sum(1 for feature in registry.features if feature.default_enabled)
    compliance_relevant_count = sum(1 for feature in registry.features if feature.compliance_relevant)
    return {
        "module_id": registry.module_id,
        "registry_version": registry.registry_version,
        "feature_count": len(registry.features),
        "default_enabled_count": default_enabled_count,
        "approval_required_count": approval_required_count,
        "compliance_relevant_count": compliance_relevant_count,
        "manifest_hash": registry.manifest_hash,
    }


def _hash_subfeature_registry(model: BaseModel, *, exclude_manifest_hash: bool = False) -> str:
    if exclude_manifest_hash:
        payload = model.model_dump(mode="json", exclude={"manifest_hash"})
    else:
        payload = model.model_dump(mode="json")
    return stable_hash(canonical_json(payload))
