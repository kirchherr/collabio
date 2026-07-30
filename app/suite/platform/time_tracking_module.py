from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass

TIME_TRACKING_MODULE_ID = "time_tracking"
TIME_ENTRIES_READ_FEATURE_ID = "time_tracking.entries.read"
TIME_APPROVALS_READ_FEATURE_ID = "time_tracking.approvals.read"
TIME_ENTRIES_WRITE_FEATURE_ID = "time_tracking.entries.write"
TIME_COMPLIANCE_EVIDENCE_FEATURE_ID = "time_tracking.compliance_evidence.read"
TIME_EXPORT_FEATURE_ID = "time_tracking.exports.execute"
TIME_TRACKING_CONTINUITY_DOMAIN = "time_tracking_records"
TIME_TRACKING_SCHEMA_NAME = "time_tracking"
TIME_TRACKING_OBJECT_TYPES = ("time.entry", "time.approval")
TIME_TRACKING_REQUIRED_OBJECT_METADATA_FIELDS = (
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

FEATURE_ID_PATTERN = re.compile(r"^time_tracking\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
OBJECT_TYPE_PATTERN = re.compile(r"^time\.[a-z][a-z0-9_]*$")
RETENTION_POLICY_PATTERN = re.compile(r"^rp-[a-z0-9-]+$")
WORKER_SURFACES = frozenset({"normal_api", "compliance_api", "feature_worker", "compliance_worker"})


class TimeTrackingRegistryError(ValueError):
    pass


class TimeTrackingSubfeatureArea(StrEnum):
    ENTRIES = "entries"
    APPROVALS = "approvals"
    COMPLIANCE = "compliance"
    EXPORT = "export"


class TimeTrackingLifecycleState(StrEnum):
    DRAFT = "draft"
    RECORDED = "recorded"
    NOT_SUBMITTED = "not_submitted"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTION_REQUESTED = "correction_requested"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    DISPOSITION_PENDING = "disposition_pending"


class TimeTrackingSubfeatureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    display_name: str
    area: TimeTrackingSubfeatureArea
    default_enabled: bool
    requires_approval: bool
    compliance_relevant: bool = False
    object_types: tuple[str, ...]
    data_classes: tuple[DataClass, ...]
    retention_policy_ids: tuple[str, ...]
    worker_surfaces: tuple[str, ...]
    dependency_feature_ids: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    schema_version: str = "time_tracking_subfeature.v1"

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("Time Tracking feature IDs must be fully qualified")
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
        if not value or len(set(value)) != len(value):
            raise ValueError("Time Tracking object types must be non-empty and unique")
        if any(not OBJECT_TYPE_PATTERN.fullmatch(object_type) for object_type in value):
            raise ValueError("Time Tracking object types must be namespaced")
        return value

    @field_validator("data_classes", "retention_policy_ids", "worker_surfaces")
    @classmethod
    def require_unique_values(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("Time Tracking feature values must be non-empty and unique")
        return value

    @field_validator("retention_policy_ids")
    @classmethod
    def validate_retention_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not RETENTION_POLICY_PATTERN.fullmatch(item) for item in value):
            raise ValueError("Time Tracking retention IDs must be policy references")
        return value

    @field_validator("worker_surfaces")
    @classmethod
    def validate_worker_surfaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - WORKER_SURFACES)
        if unknown:
            raise ValueError(f"unknown Time Tracking worker surfaces: {', '.join(unknown)}")
        return value

    @field_validator("dependency_feature_ids")
    @classmethod
    def validate_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Time Tracking dependencies must be unique")
        if any(not FEATURE_ID_PATTERN.fullmatch(item) for item in value):
            raise ValueError("Time Tracking dependencies must be fully qualified")
        return value

    @model_validator(mode="after")
    def require_high_risk_controls(self) -> Self:
        if self.compliance_relevant and not self.requires_approval:
            raise ValueError("compliance-relevant Time Tracking features require approval")
        if self.compliance_relevant and "compliance_worker" not in self.worker_surfaces:
            raise ValueError("compliance-relevant Time Tracking features require compliance_worker")
        if self.feature_id in self.dependency_feature_ids:
            raise ValueError("Time Tracking feature cannot depend on itself")
        return self


class TimeTrackingSubfeatureRegistryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = TIME_TRACKING_MODULE_ID
    registry_version: str = "time_tracking_subfeatures.v1"
    features: tuple[TimeTrackingSubfeatureDefinition, ...]
    manifest_hash: str
    schema_version: str = "time_tracking_subfeature_registry.v1"

    @model_validator(mode="after")
    def require_complete_registry(self) -> Self:
        if self.module_id != TIME_TRACKING_MODULE_ID or not self.features:
            raise ValueError("Time Tracking registry identity is invalid")
        feature_ids = [feature.feature_id for feature in self.features]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("Time Tracking feature IDs must be unique")
        known = set(feature_ids)
        for feature in self.features:
            unknown = sorted(set(feature.dependency_feature_ids) - known)
            if unknown:
                raise ValueError(f"unknown Time Tracking dependencies: {', '.join(unknown)}")
        return self

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(feature.feature_id for feature in self.features)

    @property
    def enabled_feature_defaults(self) -> dict[str, bool]:
        return {feature.feature_id: feature.default_enabled for feature in self.features}

    def feature(self, feature_id: str) -> TimeTrackingSubfeatureDefinition:
        for feature in self.features:
            if feature.feature_id == feature_id:
                return feature
        raise LookupError(f"Unknown Time Tracking feature: {feature_id}")


class TimeTrackingObjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    schema_name: str = TIME_TRACKING_SCHEMA_NAME
    feature_id: str
    classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    lifecycle_states: tuple[TimeTrackingLifecycleState, ...]
    required_metadata_fields: tuple[str, ...] = TIME_TRACKING_REQUIRED_OBJECT_METADATA_FIELDS
    rls_required: bool = True
    audit_required: bool = True
    kms_key_ref_required: bool = True
    legal_hold_supported: bool = True
    source_system_required: bool = True
    search_candidate_only: bool = True
    destructive_actions_require_approval: bool = True
    backup_domain_id: str = TIME_TRACKING_CONTINUITY_DOMAIN
    schema_version: str = "time_tracking_object_rule.v1"

    @model_validator(mode="after")
    def require_controls(self) -> Self:
        if not OBJECT_TYPE_PATTERN.fullmatch(self.object_type):
            raise ValueError("Time Tracking object type is invalid")
        if self.schema_name != TIME_TRACKING_SCHEMA_NAME:
            raise ValueError("Time Tracking objects must use the time_tracking schema")
        if not FEATURE_ID_PATTERN.fullmatch(self.feature_id):
            raise ValueError("Time Tracking object feature is invalid")
        if not RETENTION_POLICY_PATTERN.fullmatch(self.retention_policy_id):
            raise ValueError("Time Tracking retention policy is invalid")
        if not set(TIME_TRACKING_REQUIRED_OBJECT_METADATA_FIELDS).issubset(self.required_metadata_fields):
            raise ValueError("Time Tracking object rule misses required metadata")
        if not all(
            (
                self.rls_required,
                self.audit_required,
                self.kms_key_ref_required,
                self.legal_hold_supported,
                self.source_system_required,
                self.search_candidate_only,
                self.destructive_actions_require_approval,
            )
        ):
            raise ValueError("Time Tracking object controls must remain enabled")
        if self.backup_domain_id != TIME_TRACKING_CONTINUITY_DOMAIN:
            raise ValueError("Time Tracking objects must bind to time_tracking_records")
        return self


class TimeTrackingObjectRuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = TIME_TRACKING_MODULE_ID
    registry_version: str = "time_tracking_object_rules.v1"
    object_rules: tuple[TimeTrackingObjectRule, ...]
    manifest_hash: str
    schema_version: str = "time_tracking_object_rule_manifest.v1"

    @model_validator(mode="after")
    def require_complete_manifest(self) -> Self:
        if self.module_id != TIME_TRACKING_MODULE_ID or not self.object_rules:
            raise ValueError("Time Tracking object rule manifest identity is invalid")
        object_types = [rule.object_type for rule in self.object_rules]
        if len(set(object_types)) != len(object_types):
            raise ValueError("Time Tracking object rules must be unique")
        return self

    def validate_subfeature_registry(self, registry: TimeTrackingSubfeatureRegistryManifest) -> None:
        for rule in self.object_rules:
            try:
                feature = registry.feature(rule.feature_id)
            except LookupError as exc:
                raise TimeTrackingRegistryError(str(exc)) from exc
            if rule.object_type not in feature.object_types or rule.classification not in feature.data_classes:
                raise TimeTrackingRegistryError(f"Time Tracking object {rule.object_type} is not covered")
            if rule.retention_policy_id not in feature.retention_policy_ids:
                raise TimeTrackingRegistryError(f"Time Tracking retention for {rule.object_type} is not covered")


def build_default_time_tracking_subfeature_registry() -> TimeTrackingSubfeatureRegistryManifest:
    retention_ids = ("rp-standard", "rp-restricted", "rp-legal-hold")
    draft = TimeTrackingSubfeatureRegistryManifest(
        features=(
            TimeTrackingSubfeatureDefinition(
                feature_id=TIME_ENTRIES_READ_FEATURE_ID,
                display_name="Own time entries read",
                area=TimeTrackingSubfeatureArea.ENTRIES,
                default_enabled=True,
                requires_approval=False,
                object_types=("time.entry",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=retention_ids,
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            TimeTrackingSubfeatureDefinition(
                feature_id=TIME_APPROVALS_READ_FEATURE_ID,
                display_name="Time approval state read",
                area=TimeTrackingSubfeatureArea.APPROVALS,
                default_enabled=True,
                requires_approval=False,
                object_types=("time.approval",),
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=retention_ids,
                worker_surfaces=("normal_api", "feature_worker"),
            ),
            TimeTrackingSubfeatureDefinition(
                feature_id=TIME_ENTRIES_WRITE_FEATURE_ID,
                display_name="Time entry write",
                area=TimeTrackingSubfeatureArea.ENTRIES,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=TIME_TRACKING_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL,),
                retention_policy_ids=retention_ids,
                worker_surfaces=("normal_api", "compliance_worker"),
                dependency_feature_ids=(TIME_ENTRIES_READ_FEATURE_ID, TIME_APPROVALS_READ_FEATURE_ID),
                evidence_required=(
                    "atomic_entry_approval_acl_receipt_write",
                    "worker_principal_validation",
                    "duration_validation",
                    "backup_restore_evidence",
                ),
            ),
            TimeTrackingSubfeatureDefinition(
                feature_id=TIME_COMPLIANCE_EVIDENCE_FEATURE_ID,
                display_name="Time compliance evidence read",
                area=TimeTrackingSubfeatureArea.COMPLIANCE,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=TIME_TRACKING_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL, DataClass.LEGAL_HOLD),
                retention_policy_ids=retention_ids,
                worker_surfaces=("compliance_api", "compliance_worker"),
                evidence_required=("retention_evaluation", "legal_hold_check", "audit_evidence"),
            ),
            TimeTrackingSubfeatureDefinition(
                feature_id=TIME_EXPORT_FEATURE_ID,
                display_name="Time record export",
                area=TimeTrackingSubfeatureArea.EXPORT,
                default_enabled=False,
                requires_approval=True,
                compliance_relevant=True,
                object_types=TIME_TRACKING_OBJECT_TYPES,
                data_classes=(DataClass.PERSONAL, DataClass.LEGAL_HOLD),
                retention_policy_ids=retention_ids,
                worker_surfaces=("compliance_api", "compliance_worker"),
                dependency_feature_ids=(TIME_ENTRIES_READ_FEATURE_ID, TIME_APPROVALS_READ_FEATURE_ID),
                evidence_required=("explicit_human_confirmation", "export_manifest", "audit_evidence"),
            ),
        ),
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_model(draft)})


def build_default_time_tracking_object_rule_manifest() -> TimeTrackingObjectRuleManifest:
    draft = TimeTrackingObjectRuleManifest(
        object_rules=(
            TimeTrackingObjectRule(
                object_type="time.entry",
                feature_id=TIME_ENTRIES_READ_FEATURE_ID,
                lifecycle_states=(
                    TimeTrackingLifecycleState.DRAFT,
                    TimeTrackingLifecycleState.RECORDED,
                    TimeTrackingLifecycleState.SUBMITTED,
                    TimeTrackingLifecycleState.APPROVED,
                    TimeTrackingLifecycleState.REJECTED,
                    TimeTrackingLifecycleState.CORRECTION_REQUESTED,
                    TimeTrackingLifecycleState.CANCELLED,
                    TimeTrackingLifecycleState.ARCHIVED,
                    TimeTrackingLifecycleState.DISPOSITION_PENDING,
                ),
            ),
            TimeTrackingObjectRule(
                object_type="time.approval",
                feature_id=TIME_APPROVALS_READ_FEATURE_ID,
                lifecycle_states=(
                    TimeTrackingLifecycleState.NOT_SUBMITTED,
                    TimeTrackingLifecycleState.SUBMITTED,
                    TimeTrackingLifecycleState.APPROVED,
                    TimeTrackingLifecycleState.REJECTED,
                    TimeTrackingLifecycleState.CORRECTION_REQUESTED,
                    TimeTrackingLifecycleState.CANCELLED,
                    TimeTrackingLifecycleState.DISPOSITION_PENDING,
                ),
            ),
        ),
        manifest_hash="sha256:pending",
    )
    return draft.model_copy(update={"manifest_hash": _hash_model(draft)})


def default_time_tracking_enabled_features() -> dict[str, bool]:
    return build_default_time_tracking_subfeature_registry().enabled_feature_defaults


def _hash_model(model: BaseModel) -> str:
    return stable_hash(canonical_json(model.model_dump(mode="json", exclude={"manifest_hash"})))
