from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass

TICKETS_INCIDENTS_MODULE_ID = "tickets_incidents"
TICKETS_ITEMS_READ_FEATURE_ID = "tickets_incidents.items.read"
TICKETS_ITEMS_WRITE_FEATURE_ID = "tickets_incidents.items.write"
TICKETS_EVENTS_READ_FEATURE_ID = "tickets_incidents.events.read"
TICKETS_EVENTS_WRITE_FEATURE_ID = "tickets_incidents.events.write"
TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID = "tickets_incidents.compliance_evidence.read"
TICKETS_RAG_INDEXING_FEATURE_ID = "tickets_incidents.rag_indexing"
TICKETS_AI_ASSIST_FEATURE_ID = "tickets_incidents.ai_assist"
TICKETS_INCIDENTS_CONTINUITY_DOMAIN = "ticket_incident_records"
TICKETS_INCIDENTS_SCHEMA_NAME = "tickets"
TICKETS_INCIDENTS_OBJECT_TYPES = ("ticket.ticket", "ticket.event")
TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS = (
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

FEATURE_ID_PATTERN = re.compile(r"^tickets_incidents\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
OBJECT_TYPE_PATTERN = re.compile(r"^ticket\.[a-z][a-z0-9_]*$")
RETENTION_POLICY_PATTERN = re.compile(r"^rp-[a-z0-9-]+$")
WORKER_SURFACES = frozenset({"normal_api", "compliance_api", "feature_worker", "compliance_worker"})


class TicketsIncidentsRegistryError(ValueError):
    pass


class TicketsIncidentsSubfeatureArea(StrEnum):
    TICKETS = "tickets"
    EVENT_LOG = "event_log"
    COMPLIANCE = "compliance"
    SEARCH_AI = "search_ai"


class TicketsIncidentsLifecycleState(StrEnum):
    NEW = "new"
    OPEN = "open"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    DISPOSITION_PENDING = "disposition_pending"


class TicketsIncidentsSubfeatureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    display_name: str
    area: TicketsIncidentsSubfeatureArea
    default_enabled: bool
    requires_approval: bool
    compliance_relevant: bool = False
    object_types: tuple[str, ...]
    data_classes: tuple[DataClass, ...]
    retention_policy_ids: tuple[str, ...]
    worker_surfaces: tuple[str, ...]
    dependency_feature_ids: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    schema_version: str = "tickets_incidents_subfeature.v1"

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents subfeature IDs must be fully qualified with tickets")
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
            raise ValueError("Tickets & Incidents subfeature must declare at least one object type")
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents subfeature object types must be unique")
        for object_type in value:
            if not OBJECT_TYPE_PATTERN.fullmatch(object_type):
                raise ValueError("Tickets & Incidents subfeature object types must be namespaced")
        return value

    @field_validator("data_classes")
    @classmethod
    def validate_data_classes(cls, value: tuple[DataClass, ...]) -> tuple[DataClass, ...]:
        if not value:
            raise ValueError("Tickets & Incidents subfeature must declare at least one data class")
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents subfeature data classes must be unique")
        return value

    @field_validator("retention_policy_ids")
    @classmethod
    def validate_retention_policy_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Tickets & Incidents subfeature must declare at least one retention policy")
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents subfeature retention policies must be unique")
        for retention_policy_id in value:
            if not RETENTION_POLICY_PATTERN.fullmatch(retention_policy_id):
                raise ValueError("Tickets & Incidents retention IDs must be policy-style references")
        return value

    @field_validator("worker_surfaces")
    @classmethod
    def validate_worker_surfaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Tickets & Incidents subfeature must declare at least one worker/API surface")
        unknown_surfaces = sorted(set(value) - WORKER_SURFACES)
        if unknown_surfaces:
            raise ValueError(f"unknown Tickets & Incidents worker surfaces: {', '.join(unknown_surfaces)}")
        return value

    @field_validator("dependency_feature_ids")
    @classmethod
    def validate_dependency_feature_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("dependency feature IDs must be unique")
        for feature_id in value:
            if not FEATURE_ID_PATTERN.fullmatch(feature_id):
                raise ValueError("dependency feature IDs must be fully qualified with tickets")
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
        if self.area == TicketsIncidentsSubfeatureArea.SEARCH_AI and not self.requires_approval:
            raise ValueError("Tickets & Incidents AI/search subfeatures require approval")
        if self.compliance_relevant and "compliance_worker" not in self.worker_surfaces:
            raise ValueError("compliance-relevant Tickets & Incidents subfeatures need compliance_worker")
        if self.feature_id in self.dependency_feature_ids:
            raise ValueError("Tickets & Incidents subfeature cannot depend on itself")
        return self


class TicketsIncidentsSubfeatureRegistryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    registry_version: str = "tickets_incidents_subfeatures.v1"
    features: tuple[TicketsIncidentsSubfeatureDefinition, ...]
    manifest_hash: str
    schema_version: str = "tickets_incidents_subfeature_registry.v1"

    @field_validator("module_id")
    @classmethod
    def require_tickets_incidents_module(cls, value: str) -> str:
        if value != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents subfeature registry only applies to tickets_incidents")
        return value

    @model_validator(mode="after")
    def require_complete_registry(self) -> Self:
        if not self.features:
            raise ValueError("Tickets & Incidents subfeature registry requires features")
        feature_ids = [feature.feature_id for feature in self.features]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("Tickets & Incidents subfeature IDs must be unique")
        feature_id_set = set(feature_ids)
        for feature in self.features:
            unknown_dependencies = sorted(set(feature.dependency_feature_ids) - feature_id_set)
            if unknown_dependencies:
                raise ValueError(f"unknown Tickets & Incidents dependencies: {', '.join(unknown_dependencies)}")
        return self

    @property
    def enabled_feature_defaults(self) -> dict[str, bool]:
        return {feature.feature_id: feature.default_enabled for feature in self.features}

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(feature.feature_id for feature in self.features)

    def feature(self, feature_id: str) -> TicketsIncidentsSubfeatureDefinition:
        for feature in self.features:
            if feature.feature_id == feature_id:
                return feature
        raise LookupError(f"Unknown Tickets & Incidents subfeature: {feature_id}")


class TicketsIncidentsObjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    schema_name: str = TICKETS_INCIDENTS_SCHEMA_NAME
    feature_id: str
    classification: DataClass
    retention_policy_id: str
    lifecycle_states: tuple[TicketsIncidentsLifecycleState, ...]
    required_metadata_fields: tuple[str, ...] = TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS
    rls_required: bool = True
    audit_required: bool = True
    kms_key_ref_required: bool = True
    legal_hold_supported: bool = True
    source_system_required: bool = True
    search_candidate_only: bool = True
    rag_indexing_default_enabled: bool = False
    destructive_actions_require_approval: bool = True
    backup_domain_id: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    schema_version: str = "tickets_incidents_object_rule.v1"

    @field_validator("object_type")
    @classmethod
    def validate_object_type(cls, value: str) -> str:
        if not OBJECT_TYPE_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents object types must be namespaced")
        return value

    @field_validator("schema_name")
    @classmethod
    def require_tickets_schema(cls, value: str) -> str:
        if value != TICKETS_INCIDENTS_SCHEMA_NAME:
            raise ValueError("Tickets & Incidents object rules must use the tickets schema")
        return value

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents object rule feature IDs must be fully qualified with tickets")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def validate_retention_policy_id(cls, value: str) -> str:
        if not RETENTION_POLICY_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents object rules need policy-style retention IDs")
        return value

    @model_validator(mode="after")
    def require_compliance_boundaries(self) -> Self:
        if not set(TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS).issubset(self.required_metadata_fields):
            raise ValueError("Tickets & Incidents object rule misses required metadata fields")
        if not (
            self.rls_required
            and self.audit_required
            and self.kms_key_ref_required
            and self.legal_hold_supported
            and self.source_system_required
            and self.search_candidate_only
            and self.destructive_actions_require_approval
        ):
            raise ValueError("Tickets & Incidents object rules must keep core compliance boundaries enabled")
        if self.rag_indexing_default_enabled:
            raise ValueError("Tickets & Incidents object rules must not enable RAG indexing by default")
        if self.backup_domain_id != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents object rules must bind to ticket_incident_records")
        return self


class TicketsIncidentsObjectRuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    registry_version: str = "tickets_incidents_object_rules.v1"
    object_rules: tuple[TicketsIncidentsObjectRule, ...]
    manifest_hash: str
    schema_version: str = "tickets_incidents_object_rule_manifest.v1"

    @field_validator("module_id")
    @classmethod
    def require_tickets_incidents_module(cls, value: str) -> str:
        if value != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents object rule manifest only applies to tickets_incidents")
        return value

    @model_validator(mode="after")
    def require_complete_object_rules(self) -> Self:
        if not self.object_rules:
            raise ValueError("Tickets & Incidents object rule manifest requires object rules")
        object_types = [rule.object_type for rule in self.object_rules]
        if len(set(object_types)) != len(object_types):
            raise ValueError("Tickets & Incidents object types must be unique")
        return self

    def rule(self, object_type: str) -> TicketsIncidentsObjectRule:
        for rule in self.object_rules:
            if rule.object_type == object_type:
                return rule
        raise LookupError(f"Unknown Tickets & Incidents object rule: {object_type}")

    def validate_subfeature_registry(self, registry: TicketsIncidentsSubfeatureRegistryManifest) -> None:
        feature_ids = set(registry.feature_ids)
        for rule in self.object_rules:
            if rule.feature_id not in feature_ids:
                raise TicketsIncidentsRegistryError(
                    f"Tickets & Incidents object rule references unknown feature: {rule.feature_id}"
                )
            feature = registry.feature(rule.feature_id)
            if rule.object_type not in feature.object_types:
                raise TicketsIncidentsRegistryError(
                    f"Tickets & Incidents object {rule.object_type} is not covered by {rule.feature_id}"
                )
            if rule.classification not in feature.data_classes:
                raise TicketsIncidentsRegistryError(
                    f"Tickets & Incidents object class {rule.classification} is not covered by {rule.feature_id}"
                )
            if rule.retention_policy_id not in feature.retention_policy_ids:
                raise TicketsIncidentsRegistryError(
                    "Tickets & Incidents object retention "
                    f"{rule.retention_policy_id} is not covered by {rule.feature_id}"
                )


def build_default_tickets_incidents_subfeature_registry() -> TicketsIncidentsSubfeatureRegistryManifest:
    draft = TicketsIncidentsSubfeatureRegistryManifest(
        features=(
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_ITEMS_READ_FEATURE_ID,
                display_name="Ticket summary and SLA state read",
                area=TicketsIncidentsSubfeatureArea.TICKETS,
                default_enabled=True,
                requires_approval=False,
                object_types=("ticket.ticket",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_ITEMS_WRITE_FEATURE_ID,
                display_name="Create and transition governed ticket metadata",
                area=TicketsIncidentsSubfeatureArea.TICKETS,
                default_enabled=False,
                requires_approval=True,
                object_types=("ticket.ticket",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api",),
                dependency_feature_ids=(TICKETS_ITEMS_READ_FEATURE_ID,),
                evidence_required=("explicit_module_enablement", "append_only_ticket_event"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_EVENTS_READ_FEATURE_ID,
                display_name="Ticket event log read",
                area=TicketsIncidentsSubfeatureArea.EVENT_LOG,
                default_enabled=True,
                requires_approval=False,
                object_types=("ticket.event",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_EVENTS_WRITE_FEATURE_ID,
                display_name="Append governed ticket lifecycle events",
                area=TicketsIncidentsSubfeatureArea.EVENT_LOG,
                default_enabled=False,
                requires_approval=True,
                object_types=("ticket.event",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api",),
                dependency_feature_ids=(TICKETS_ITEMS_READ_FEATURE_ID, TICKETS_EVENTS_READ_FEATURE_ID),
                evidence_required=("explicit_module_enablement", "append_only_ticket_event"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID,
                display_name="Tickets and incidents compliance evidence read",
                area=TicketsIncidentsSubfeatureArea.COMPLIANCE,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=TICKETS_INCIDENTS_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL, DataClass.LEGAL_HOLD),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("compliance_api", "compliance_worker"),
                evidence_required=("retention_evaluation", "legal_hold_check", "audit_evidence"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_RAG_INDEXING_FEATURE_ID,
                display_name="Tickets and incidents RAG indexing",
                area=TicketsIncidentsSubfeatureArea.SEARCH_AI,
                default_enabled=False,
                requires_approval=True,
                object_types=TICKETS_INCIDENTS_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL, DataClass.LEGAL_HOLD),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("feature_worker",),
                dependency_feature_ids=(TICKETS_ITEMS_READ_FEATURE_ID, TICKETS_EVENTS_READ_FEATURE_ID),
                evidence_required=("candidate_only_search", "authoritative_acl_validation", "source_citations"),
            ),
            TicketsIncidentsSubfeatureDefinition(
                feature_id=TICKETS_AI_ASSIST_FEATURE_ID,
                display_name="Tickets and incidents AI assist",
                area=TicketsIncidentsSubfeatureArea.SEARCH_AI,
                default_enabled=False,
                requires_approval=True,
                object_types=TICKETS_INCIDENTS_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL, DataClass.LEGAL_HOLD),
                retention_policy_ids=("rp-standard", "rp-restricted", "rp-legal-hold"),
                worker_surfaces=("normal_api", "feature_worker"),
                dependency_feature_ids=(TICKETS_RAG_INDEXING_FEATURE_ID,),
                evidence_required=("tenant_ai_policy", "local_llm_gateway_audit", "human_approval_policy"),
            ),
        ),
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_model(draft, exclude_manifest_hash=True)})


def build_default_tickets_incidents_object_rule_manifest() -> TicketsIncidentsObjectRuleManifest:
    draft = TicketsIncidentsObjectRuleManifest(
        object_rules=(
            TicketsIncidentsObjectRule(
                object_type="ticket.ticket",
                feature_id=TICKETS_ITEMS_READ_FEATURE_ID,
                classification=DataClass.PERSONAL,
                retention_policy_id="rp-standard",
                lifecycle_states=(
                    TicketsIncidentsLifecycleState.NEW,
                    TicketsIncidentsLifecycleState.OPEN,
                    TicketsIncidentsLifecycleState.TRIAGED,
                    TicketsIncidentsLifecycleState.IN_PROGRESS,
                    TicketsIncidentsLifecycleState.WAITING,
                    TicketsIncidentsLifecycleState.RESOLVED,
                    TicketsIncidentsLifecycleState.CANCELLED,
                    TicketsIncidentsLifecycleState.ARCHIVED,
                    TicketsIncidentsLifecycleState.DISPOSITION_PENDING,
                ),
            ),
            TicketsIncidentsObjectRule(
                object_type="ticket.event",
                feature_id=TICKETS_EVENTS_READ_FEATURE_ID,
                classification=DataClass.PERSONAL,
                retention_policy_id="rp-standard",
                lifecycle_states=(
                    TicketsIncidentsLifecycleState.OPEN,
                    TicketsIncidentsLifecycleState.IN_PROGRESS,
                    TicketsIncidentsLifecycleState.WAITING,
                    TicketsIncidentsLifecycleState.RESOLVED,
                    TicketsIncidentsLifecycleState.CANCELLED,
                    TicketsIncidentsLifecycleState.DISPOSITION_PENDING,
                ),
            ),
        ),
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_model(draft, exclude_manifest_hash=True)})


def default_tickets_incidents_enabled_features() -> dict[str, bool]:
    return build_default_tickets_incidents_subfeature_registry().enabled_feature_defaults


def tickets_incidents_subfeature_registry_summary(
    registry: TicketsIncidentsSubfeatureRegistryManifest,
) -> dict[str, object]:
    return {
        "module_id": registry.module_id,
        "registry_version": registry.registry_version,
        "feature_count": len(registry.features),
        "default_enabled_count": sum(1 for feature in registry.features if feature.default_enabled),
        "approval_required_count": sum(1 for feature in registry.features if feature.requires_approval),
        "compliance_relevant_count": sum(1 for feature in registry.features if feature.compliance_relevant),
        "manifest_hash": registry.manifest_hash,
    }


def tickets_incidents_object_rule_registry_summary(
    manifest: TicketsIncidentsObjectRuleManifest,
) -> dict[str, object]:
    return {
        "module_id": manifest.module_id,
        "registry_version": manifest.registry_version,
        "object_type_count": len(manifest.object_rules),
        "personal_object_type_count": sum(
            1 for rule in manifest.object_rules if rule.classification == DataClass.PERSONAL
        ),
        "manifest_hash": manifest.manifest_hash,
    }


def _hash_model(model: BaseModel, *, exclude_manifest_hash: bool = False) -> str:
    if exclude_manifest_hash:
        payload = model.model_dump(mode="json", exclude={"manifest_hash"})
    else:
        payload = model.model_dump(mode="json")
    return stable_hash(canonical_json(payload))
