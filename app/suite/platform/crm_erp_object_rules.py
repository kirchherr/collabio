from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import (
    CRM_ERP_MODULE_ID,
    OBJECT_TYPE_PATTERN,
    RETENTION_POLICY_PATTERN,
    CrmErpTargetObjectProfile,
    default_crm_erp_target_profiles,
)
from suite.platform.crm_erp_subfeatures import CrmErpSubfeatureRegistryManifest

SCHEMA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
TABLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
FEATURE_ID_PATTERN = re.compile(r"^crm_erp\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
CRM_ERP_SCHEMA_NAMES = ("crm_erp", "crm", "erp", "crm_erp_legacy")
REQUIRED_OBJECT_METADATA_FIELDS = (
    "tenant_id",
    "object_id",
    "object_type",
    "owner_principal_id",
    "created_by",
    "created_at_utc",
    "updated_at_utc",
    "data_classification",
    "retention_policy_id",
    "legal_hold_state",
    "lifecycle_state",
    "kms_key_ref",
    "audit_chain_ref",
    "source_system",
    "schema_version",
)


class CrmErpObjectRuleError(ValueError):
    pass


class CrmErpSchemaPurpose(StrEnum):
    MODULE_CONTROL = "module_control"
    CRM_DOMAIN = "crm_domain"
    ERP_DOMAIN = "erp_domain"
    LEGACY_STAGING = "legacy_staging"


class CrmErpLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RECORD = "record"
    RESTRICTED = "restricted"
    QUARANTINED = "quarantined"
    DISPOSITION_PENDING = "disposition_pending"


EXPECTED_SCHEMA_PURPOSES = {
    "crm_erp": CrmErpSchemaPurpose.MODULE_CONTROL,
    "crm": CrmErpSchemaPurpose.CRM_DOMAIN,
    "erp": CrmErpSchemaPurpose.ERP_DOMAIN,
    "crm_erp_legacy": CrmErpSchemaPurpose.LEGACY_STAGING,
}


class CrmErpSchemaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str
    purpose: CrmErpSchemaPurpose
    owns_object_types: tuple[str, ...] = ()
    rls_required: bool = True
    audit_required: bool = True
    backup_domain_id: str = "crm_erp_business_records"
    raw_legacy_payload_allowed: bool = False
    schema_version: str = "crm_erp_schema_definition.v1"

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        if not SCHEMA_NAME_PATTERN.fullmatch(value):
            raise ValueError("schema_name must be lowercase snake_case")
        return value

    @field_validator("owns_object_types")
    @classmethod
    def validate_owns_object_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("schema object types must be unique")
        for object_type in value:
            if not OBJECT_TYPE_PATTERN.fullmatch(object_type):
                raise ValueError("schema object types must be namespaced")
        return value

    @model_validator(mode="after")
    def require_schema_contract(self) -> Self:
        expected_purpose = EXPECTED_SCHEMA_PURPOSES.get(self.schema_name)
        if expected_purpose is None:
            raise ValueError("schema_name is not part of the CRM/ERP schema plan")
        if self.purpose != expected_purpose:
            raise ValueError("schema purpose does not match canonical CRM/ERP schema plan")
        if not self.rls_required or not self.audit_required:
            raise ValueError("CRM/ERP schemas require RLS and audit by default")
        if self.raw_legacy_payload_allowed:
            raise ValueError("CRM/ERP schema plan must not allow raw legacy payload storage yet")
        return self


class CrmErpObjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    schema_name: str
    table_name: str
    feature_id: str
    classification: DataClass
    retention_policy_id: str
    lifecycle_states: tuple[CrmErpLifecycleState, ...]
    legal_hold_supported: bool = True
    kms_key_ref_required: bool = True
    audit_required: bool = True
    rls_required: bool = True
    source_system_required: bool = True
    search_candidate_only: bool = True
    rag_indexing_default_enabled: bool = False
    source_resolver_required: bool = True
    raw_import_payload_allowed: bool = False
    destructive_actions_require_approval: bool = True
    backup_domain_id: str = "crm_erp_business_records"
    gobd_relevant: bool = False
    worm_candidate: bool = False
    required_metadata_fields: tuple[str, ...] = Field(default=REQUIRED_OBJECT_METADATA_FIELDS)
    schema_version: str = "crm_erp_object_rule.v1"

    @field_validator("object_type")
    @classmethod
    def validate_object_type(cls, value: str) -> str:
        if not OBJECT_TYPE_PATTERN.fullmatch(value):
            raise ValueError("object_type must be namespaced")
        return value

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        if value not in CRM_ERP_SCHEMA_NAMES:
            raise ValueError("schema_name must be one of the CRM/ERP planned schemas")
        return value

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, value: str) -> str:
        if not TABLE_NAME_PATTERN.fullmatch(value):
            raise ValueError("table_name must be lowercase snake_case")
        return value

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("feature_id must be fully qualified with crm_erp")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def validate_retention_policy_id(cls, value: str) -> str:
        if not RETENTION_POLICY_PATTERN.fullmatch(value):
            raise ValueError("retention_policy_id must be a policy-style reference")
        return value

    @field_validator("lifecycle_states")
    @classmethod
    def validate_lifecycle_states(
        cls,
        value: tuple[CrmErpLifecycleState, ...],
    ) -> tuple[CrmErpLifecycleState, ...]:
        if not value:
            raise ValueError("object rule must declare lifecycle states")
        if len(set(value)) != len(value):
            raise ValueError("object rule lifecycle states must be unique")
        return value

    @field_validator("required_metadata_fields")
    @classmethod
    def validate_required_metadata_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required metadata fields must be unique")
        missing = set(REQUIRED_OBJECT_METADATA_FIELDS) - set(value)
        if missing:
            raise ValueError(f"object rule misses required metadata fields: {', '.join(sorted(missing))}")
        return value

    @model_validator(mode="after")
    def require_object_rule_contract(self) -> Self:
        expected_schema = schema_for_object_type(self.object_type)
        if self.schema_name != expected_schema:
            raise ValueError("object rule schema does not match object type namespace")
        if not self.legal_hold_supported:
            raise ValueError("CRM/ERP object rules must support Legal Hold from the start")
        if not all(
            [
                self.kms_key_ref_required,
                self.audit_required,
                self.rls_required,
                self.source_system_required,
                self.search_candidate_only,
                self.source_resolver_required,
                self.destructive_actions_require_approval,
            ]
        ):
            raise ValueError("CRM/ERP object rules must keep core compliance gates enabled")
        if self.rag_indexing_default_enabled:
            raise ValueError("CRM/ERP RAG indexing must remain default-off")
        if self.raw_import_payload_allowed:
            raise ValueError("CRM/ERP object rules must not allow raw import payload storage yet")
        if self.classification == DataClass.GOBD:
            if self.retention_policy_id != "rp-gobd-10y":
                raise ValueError("GoBD CRM/ERP objects must use rp-gobd-10y")
            if not self.gobd_relevant or not self.worm_candidate:
                raise ValueError("GoBD CRM/ERP objects must be marked GoBD-relevant and WORM candidates")
            if CrmErpLifecycleState.RECORD not in self.lifecycle_states:
                raise ValueError("GoBD CRM/ERP objects require a record lifecycle state")
        if self.object_type == "legacy.row":
            if self.schema_name != "crm_erp_legacy":
                raise ValueError("legacy.row must stay in crm_erp_legacy")
            if CrmErpLifecycleState.QUARANTINED not in self.lifecycle_states:
                raise ValueError("legacy.row requires a quarantined lifecycle state")
        return self


class CrmErpObjectRuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = CRM_ERP_MODULE_ID
    registry_version: str = "crm_erp_object_rules.v1"
    schemas: tuple[CrmErpSchemaDefinition, ...]
    object_rules: tuple[CrmErpObjectRule, ...]
    manifest_hash: str
    schema_version: str = "crm_erp_object_rule_manifest.v1"

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("CRM/ERP object rules only apply to crm_erp")
        return value

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("manifest_hash must be sha256 namespaced")
        return value

    @model_validator(mode="after")
    def require_complete_manifest(self) -> Self:
        schema_names = [schema.schema_name for schema in self.schemas]
        if tuple(schema_names) != CRM_ERP_SCHEMA_NAMES:
            raise ValueError("CRM/ERP object rule manifest must declare canonical schemas in order")
        object_types = [rule.object_type for rule in self.object_rules]
        if len(set(object_types)) != len(object_types):
            raise ValueError("CRM/ERP object rules must be unique per object type")

        for schema in self.schemas:
            expected_object_types = tuple(
                sorted(rule.object_type for rule in self.object_rules if rule.schema_name == schema.schema_name)
            )
            if tuple(sorted(schema.owns_object_types)) != expected_object_types:
                raise ValueError("schema owns_object_types must match object rules")
        return self

    def schema_definition(self, schema_name: str) -> CrmErpSchemaDefinition:
        for schema in self.schemas:
            if schema.schema_name == schema_name:
                return schema
        raise LookupError(f"Unknown CRM/ERP schema: {schema_name}")

    def rule(self, object_type: str) -> CrmErpObjectRule:
        for rule in self.object_rules:
            if rule.object_type == object_type:
                return rule
        raise LookupError(f"Unknown CRM/ERP object type: {object_type}")

    def validate_target_profiles(self, target_profiles: dict[str, CrmErpTargetObjectProfile]) -> None:
        if set(target_profiles) != {rule.object_type for rule in self.object_rules}:
            raise CrmErpObjectRuleError("target profiles and object rules must cover the same object types")
        for object_type, profile in target_profiles.items():
            rule = self.rule(object_type)
            if rule.feature_id != profile.feature_id:
                raise CrmErpObjectRuleError(f"feature drift for object type: {object_type}")
            if rule.classification != profile.classification:
                raise CrmErpObjectRuleError(f"classification drift for object type: {object_type}")
            if rule.retention_policy_id != profile.retention_policy_id:
                raise CrmErpObjectRuleError(f"retention drift for object type: {object_type}")
            if rule.legal_hold_supported != profile.legal_hold_supported:
                raise CrmErpObjectRuleError(f"Legal Hold support drift for object type: {object_type}")
            if rule.gobd_relevant != profile.gobd_relevant:
                raise CrmErpObjectRuleError(f"GoBD relevance drift for object type: {object_type}")

    def validate_subfeature_registry(self, registry: CrmErpSubfeatureRegistryManifest) -> None:
        if registry.module_id != self.module_id:
            raise CrmErpObjectRuleError("subfeature registry module does not match object rule manifest")
        for rule in self.object_rules:
            feature = registry.feature(rule.feature_id)
            if rule.object_type not in feature.object_types:
                raise CrmErpObjectRuleError(f"subfeature does not cover object type: {rule.object_type}")
            if rule.classification not in feature.data_classes:
                raise CrmErpObjectRuleError(f"subfeature does not cover class for object type: {rule.object_type}")
            if rule.retention_policy_id not in feature.retention_policy_ids:
                raise CrmErpObjectRuleError(f"subfeature does not cover retention for object type: {rule.object_type}")


def build_default_crm_erp_object_rule_manifest() -> CrmErpObjectRuleManifest:
    target_profiles = default_crm_erp_target_profiles()
    object_rules = tuple(build_object_rule(profile) for profile in target_profiles.values())
    schemas = tuple(
        CrmErpSchemaDefinition(
            schema_name=schema_name,
            purpose=EXPECTED_SCHEMA_PURPOSES[schema_name],
            owns_object_types=tuple(
                sorted(rule.object_type for rule in object_rules if rule.schema_name == schema_name)
            ),
        )
        for schema_name in CRM_ERP_SCHEMA_NAMES
    )
    draft = CrmErpObjectRuleManifest(
        schemas=schemas,
        object_rules=object_rules,
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_object_rule_manifest(draft, exclude_manifest_hash=True)})


def build_object_rule(profile: CrmErpTargetObjectProfile) -> CrmErpObjectRule:
    return CrmErpObjectRule(
        object_type=profile.object_type,
        schema_name=schema_for_object_type(profile.object_type),
        table_name=table_name_for_object_type(profile.object_type),
        feature_id=profile.feature_id,
        classification=profile.classification,
        retention_policy_id=profile.retention_policy_id,
        lifecycle_states=lifecycle_states_for_profile(profile),
        legal_hold_supported=profile.legal_hold_supported,
        gobd_relevant=profile.gobd_relevant,
        worm_candidate=profile.gobd_relevant,
    )


def schema_for_object_type(object_type: str) -> str:
    if object_type.startswith("crm."):
        return "crm"
    if object_type.startswith("erp."):
        return "erp"
    if object_type == "legacy.row":
        return "crm_erp_legacy"
    raise CrmErpObjectRuleError(f"unknown CRM/ERP object type namespace: {object_type}")


def table_name_for_object_type(object_type: str) -> str:
    table_names = {
        "crm.account": "accounts",
        "crm.contact": "contacts",
        "crm.activity": "activities",
        "crm.note": "notes",
        "erp.product": "products",
        "erp.supplier": "suppliers",
        "erp.order": "orders",
        "erp.order_item": "order_items",
        "erp.invoice": "invoices",
        "erp.invoice_item": "invoice_items",
        "erp.delivery_note": "delivery_notes",
        "erp.contract": "contracts",
        "legacy.row": "legacy_rows",
    }
    try:
        return table_names[object_type]
    except KeyError as exc:
        raise CrmErpObjectRuleError(f"unknown CRM/ERP object type: {object_type}") from exc


def lifecycle_states_for_profile(profile: CrmErpTargetObjectProfile) -> tuple[CrmErpLifecycleState, ...]:
    if profile.object_type == "legacy.row":
        return (
            CrmErpLifecycleState.QUARANTINED,
            CrmErpLifecycleState.RESTRICTED,
            CrmErpLifecycleState.DISPOSITION_PENDING,
        )
    if profile.gobd_relevant:
        return (
            CrmErpLifecycleState.WORKING,
            CrmErpLifecycleState.RECORD,
            CrmErpLifecycleState.RESTRICTED,
            CrmErpLifecycleState.DISPOSITION_PENDING,
        )
    return (
        CrmErpLifecycleState.WORKING,
        CrmErpLifecycleState.ACTIVE,
        CrmErpLifecycleState.RESTRICTED,
        CrmErpLifecycleState.DISPOSITION_PENDING,
    )


def crm_erp_object_rule_registry_summary(manifest: CrmErpObjectRuleManifest) -> dict[str, object]:
    return {
        "module_id": manifest.module_id,
        "registry_version": manifest.registry_version,
        "schema_count": len(manifest.schemas),
        "object_type_count": len(manifest.object_rules),
        "gobd_object_type_count": sum(1 for rule in manifest.object_rules if rule.gobd_relevant),
        "legacy_object_type_count": sum(1 for rule in manifest.object_rules if rule.schema_name == "crm_erp_legacy"),
        "manifest_hash": manifest.manifest_hash,
    }


def _hash_object_rule_manifest(model: BaseModel, *, exclude_manifest_hash: bool = False) -> str:
    if exclude_manifest_hash:
        payload = model.model_dump(mode="json", exclude={"manifest_hash"})
    else:
        payload = model.model_dump(mode="json")
    return stable_hash(canonical_json(payload))
