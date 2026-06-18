from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass
from suite.platform.legacy_sql_discovery import (
    IDENTIFIER_PATTERN,
    NAMESPACED_REF_PATTERN,
    LegacySqlCandidateConfidence,
    LegacySqlDiscoveryManifest,
    LegacySqlImportEvidencePlan,
    LegacySqlObjectCandidate,
)

CRM_ERP_MODULE_ID = "crm_erp"
OBJECT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
FEATURE_ID_PATTERN = re.compile(r"^crm_erp\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
RETENTION_POLICY_PATTERN = re.compile(r"^rp-[a-z0-9][a-z0-9_-]*$")


class CrmErpLegacyMappingEvidenceError(ValueError):
    pass


class CrmErpLegacyMappingAction(StrEnum):
    MAP_TO_TARGET = "map_to_target"
    MAP_TO_LEGACY_ROW = "map_to_legacy_row"
    QUARANTINE = "quarantine"
    DEFER = "defer"


class CrmErpLegacyImportReadinessStatus(StrEnum):
    READY_FOR_DRY_RUN = "ready_for_dry_run"
    MANUAL_MAPPING_REQUIRED = "manual_mapping_required"
    BLOCKED = "blocked"


class CrmErpTargetObjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    feature_id: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_supported: bool = True
    gobd_relevant: bool = False

    @field_validator("object_type")
    @classmethod
    def validate_object_type(cls, value: str) -> str:
        if not OBJECT_TYPE_PATTERN.fullmatch(value):
            raise ValueError("target object type must be namespaced")
        return value

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("CRM/ERP target feature ID must start with crm_erp")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def validate_retention_policy_id(cls, value: str) -> str:
        if not RETENTION_POLICY_PATTERN.fullmatch(value):
            raise ValueError("retention_policy_id must be a known policy-style reference")
        return value

    @model_validator(mode="after")
    def require_gobd_profile_consistency(self) -> Self:
        if self.gobd_relevant and self.classification != DataClass.GOBD:
            raise ValueError("GoBD-relevant CRM/ERP targets must use DataClass.GOBD")
        if self.classification == DataClass.GOBD and self.retention_policy_id != "rp-gobd-10y":
            raise ValueError("GoBD CRM/ERP targets must use rp-gobd-10y")
        return self


class CrmErpLegacyMappingOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_table_ref: str
    action: CrmErpLegacyMappingAction
    mapping_reason: str
    target_object_type: str | None = None
    approval_reference: str | None = None

    @field_validator("source_table_ref")
    @classmethod
    def validate_source_table_ref(cls, value: str) -> str:
        validate_table_ref(value)
        return value

    @field_validator("target_object_type")
    @classmethod
    def validate_target_object_type(cls, value: str | None) -> str | None:
        if value is not None and not OBJECT_TYPE_PATTERN.fullmatch(value):
            raise ValueError("target_object_type must be namespaced")
        return value

    @field_validator("mapping_reason")
    @classmethod
    def require_mapping_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("mapping_reason must not be empty")
        return value

    @field_validator("approval_reference")
    @classmethod
    def validate_approval_reference(cls, value: str | None) -> str | None:
        if value is not None and not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("approval_reference must be namespaced")
        return value


class CrmErpLegacyTableMappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_table_ref: str
    source_candidate_object_type: str
    source_candidate_confidence: LegacySqlCandidateConfidence
    action: CrmErpLegacyMappingAction
    target_object_type: str
    feature_id: str
    classification: DataClass
    retention_policy_id: str
    quarantine_required: bool
    operator_review_required: bool = True
    approval_reference: str | None = None
    mapping_reasons: tuple[str, ...]
    dry_run_required: bool = True
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False

    @field_validator("source_table_ref")
    @classmethod
    def validate_source_table_ref(cls, value: str) -> str:
        validate_table_ref(value)
        return value

    @field_validator("source_candidate_object_type", "target_object_type")
    @classmethod
    def validate_object_type(cls, value: str) -> str:
        if not OBJECT_TYPE_PATTERN.fullmatch(value):
            raise ValueError("mapping object types must be namespaced")
        return value

    @field_validator("feature_id")
    @classmethod
    def validate_feature_id(cls, value: str) -> str:
        if not FEATURE_ID_PATTERN.fullmatch(value):
            raise ValueError("mapping feature ID must start with crm_erp")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def validate_retention_policy_id(cls, value: str) -> str:
        if not RETENTION_POLICY_PATTERN.fullmatch(value):
            raise ValueError("retention_policy_id must be a known policy-style reference")
        return value

    @field_validator("approval_reference")
    @classmethod
    def validate_approval_reference(cls, value: str | None) -> str | None:
        if value is not None and not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("approval_reference must be namespaced")
        return value

    @field_validator("mapping_reasons")
    @classmethod
    def require_mapping_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("mapping decision requires at least one reason")
        for reason in value:
            if not reason.strip():
                raise ValueError("mapping reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_action_consistency(self) -> Self:
        if self.action == CrmErpLegacyMappingAction.MAP_TO_TARGET and self.target_object_type == "legacy.row":
            raise ValueError("map_to_target cannot target legacy.row")
        if (
            self.action
            in {
                CrmErpLegacyMappingAction.MAP_TO_LEGACY_ROW,
                CrmErpLegacyMappingAction.QUARANTINE,
                CrmErpLegacyMappingAction.DEFER,
            }
            and self.target_object_type != "legacy.row"
        ):
            raise ValueError("non-target mapping decisions must target legacy.row")
        if self.classification == DataClass.GOBD and self.retention_policy_id != "rp-gobd-10y":
            raise ValueError("GoBD mappings must use rp-gobd-10y")
        if self.raw_data_import_allowed or self.destructive_actions_allowed:
            raise ValueError("mapping evidence must never allow raw import or destructive actions")
        return self


class CrmErpLegacyMappingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    discovery_manifest_hash: str
    import_evidence_plan_hash: str
    mapping_version: str
    decisions: tuple[CrmErpLegacyTableMappingDecision, ...]
    target_object_counts: dict[str, int]
    quarantine_table_refs: tuple[str, ...]
    legacy_row_table_refs: tuple[str, ...]
    mapping_approval_required: bool = True
    dry_run_required: bool = True
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    manifest_hash: str
    schema_version: str = "crm_erp_legacy_mapping.v1"

    @field_validator("tenant_id")
    @classmethod
    def require_tenant_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tenant_id must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("CRM/ERP mapping evidence only applies to module crm_erp")
        return value

    @field_validator("source_system_ref", "discovery_manifest_hash", "import_evidence_plan_hash")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("mapping manifest references must be namespaced")
        return value

    @field_validator("mapping_version")
    @classmethod
    def require_mapping_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("mapping_version must not be empty")
        return value

    @model_validator(mode="after")
    def require_complete_mapping_manifest(self) -> Self:
        if not self.decisions:
            raise ValueError("mapping manifest requires at least one decision")
        source_refs = [decision.source_table_ref.lower() for decision in self.decisions]
        if len(set(source_refs)) != len(source_refs):
            raise ValueError("mapping manifest decisions must be unique per source table")
        if self.raw_data_import_allowed or self.destructive_actions_allowed:
            raise ValueError("mapping manifest must never allow raw import or destructive actions")
        expected_target_counts: dict[str, int] = {}
        for decision in self.decisions:
            expected_target_counts[decision.target_object_type] = (
                expected_target_counts.get(decision.target_object_type, 0) + 1
            )
        if self.target_object_counts != dict(sorted(expected_target_counts.items())):
            raise ValueError("target_object_counts must match mapping decisions")
        return self


class CrmErpLegacyImportReadinessEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    discovery_manifest_hash: str
    import_evidence_plan_hash: str
    mapping_manifest_hash: str
    table_count: int
    candidate_count: int
    target_mapping_count: int
    quarantine_table_count: int
    legacy_row_table_count: int
    manual_review_required: bool
    dry_run_required: bool = True
    dry_run_allowed: bool
    import_write_allowed: bool = False
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    next_actions: tuple[str, ...]
    status: CrmErpLegacyImportReadinessStatus
    evidence_hash: str
    schema_version: str = "crm_erp_legacy_import_readiness.v1"

    @field_validator("tenant_id")
    @classmethod
    def require_tenant_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tenant_id must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("CRM/ERP legacy import readiness only applies to module crm_erp")
        return value

    @field_validator(
        "source_system_ref",
        "discovery_manifest_hash",
        "import_evidence_plan_hash",
        "mapping_manifest_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("readiness evidence references must be namespaced")
        return value

    @field_validator(
        "table_count",
        "candidate_count",
        "target_mapping_count",
        "quarantine_table_count",
        "legacy_row_table_count",
    )
    @classmethod
    def validate_counts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("readiness counts must not be negative")
        return value

    @field_validator("blocking_reasons", "next_actions")
    @classmethod
    def validate_reason_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("readiness reason lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("readiness reason lists must not contain empty entries")
        return value

    @model_validator(mode="after")
    def require_readiness_consistency(self) -> Self:
        if self.import_write_allowed or self.raw_data_import_allowed or self.destructive_actions_allowed:
            raise ValueError("legacy import readiness evidence must not allow import writes or destructive actions")
        if self.dry_run_allowed and self.blocking_reasons:
            raise ValueError("dry-run cannot be allowed while readiness has blocking reasons")
        if self.status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN and not self.dry_run_allowed:
            raise ValueError("ready_for_dry_run status must allow dry-run")
        if self.status != CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN and self.dry_run_allowed:
            raise ValueError("blocked readiness status must not allow dry-run")
        if self.table_count < 1:
            raise ValueError("readiness evidence requires at least one source table")
        if self.target_mapping_count + self.legacy_row_table_count != self.candidate_count:
            raise ValueError("readiness mapping counts must match candidate count")
        return self


class CrmErpLegacyMappingEvidenceService:
    def __init__(
        self,
        *,
        target_profiles: Mapping[str, CrmErpTargetObjectProfile] | None = None,
    ) -> None:
        self.target_profiles = dict(target_profiles or default_crm_erp_target_profiles())

    def build_mapping_manifest(
        self,
        *,
        discovery_manifest: LegacySqlDiscoveryManifest,
        import_evidence_plan: LegacySqlImportEvidencePlan,
        mapping_version: str = "crm_erp_legacy_mapping.v1",
        overrides: Sequence[CrmErpLegacyMappingOverride] = (),
    ) -> CrmErpLegacyMappingManifest:
        self._validate_inputs(discovery_manifest=discovery_manifest, import_evidence_plan=import_evidence_plan)
        overrides_by_table = self._overrides_by_table(overrides)
        candidate_by_table = {
            candidate.source_table_ref: candidate for candidate in discovery_manifest.object_candidates
        }
        unknown_overrides = sorted(set(overrides_by_table) - set(candidate_by_table))
        if unknown_overrides:
            raise CrmErpLegacyMappingEvidenceError(
                f"mapping override references unknown tables: {', '.join(unknown_overrides)}"
            )

        quarantine_table_refs = set(import_evidence_plan.quarantine_table_refs)
        decisions = tuple(
            self._build_decision(
                candidate=candidate,
                quarantine_required=candidate.source_table_ref in quarantine_table_refs,
                override=overrides_by_table.get(candidate.source_table_ref),
            )
            for candidate in discovery_manifest.object_candidates
        )
        target_object_counts = _target_object_counts(decisions)
        manifest_quarantine_refs = tuple(
            sorted(decision.source_table_ref for decision in decisions if decision.quarantine_required)
        )
        legacy_row_table_refs = tuple(
            sorted(decision.source_table_ref for decision in decisions if decision.target_object_type == "legacy.row")
        )
        draft = CrmErpLegacyMappingManifest(
            tenant_id=discovery_manifest.tenant_id,
            module_id=discovery_manifest.module_id,
            source_system_ref=discovery_manifest.source_system_ref,
            discovery_manifest_hash=discovery_manifest.manifest_hash,
            import_evidence_plan_hash=import_evidence_plan.manifest_hash,
            mapping_version=mapping_version,
            decisions=decisions,
            target_object_counts=target_object_counts,
            quarantine_table_refs=manifest_quarantine_refs,
            legacy_row_table_refs=legacy_row_table_refs,
            manifest_hash="sha256:pending",
        )
        return draft.model_copy(update={"manifest_hash": _hash_mapping_model(draft, exclude_manifest_hash=True)})

    def _validate_inputs(
        self,
        *,
        discovery_manifest: LegacySqlDiscoveryManifest,
        import_evidence_plan: LegacySqlImportEvidencePlan,
    ) -> None:
        if discovery_manifest.module_id != CRM_ERP_MODULE_ID:
            raise CrmErpLegacyMappingEvidenceError("CRM/ERP mapping evidence requires discovery module crm_erp")
        if import_evidence_plan.tenant_id != discovery_manifest.tenant_id:
            raise CrmErpLegacyMappingEvidenceError("import evidence tenant does not match discovery manifest")
        if import_evidence_plan.module_id != discovery_manifest.module_id:
            raise CrmErpLegacyMappingEvidenceError("import evidence module does not match discovery manifest")
        if import_evidence_plan.source_system_ref != discovery_manifest.source_system_ref:
            raise CrmErpLegacyMappingEvidenceError("import evidence source system does not match discovery manifest")
        if import_evidence_plan.discovery_manifest_hash != discovery_manifest.manifest_hash:
            raise CrmErpLegacyMappingEvidenceError("import evidence does not reference the discovery manifest")
        candidate_refs = {candidate.source_table_ref for candidate in discovery_manifest.object_candidates}
        missing_quarantine_refs = sorted(set(import_evidence_plan.quarantine_table_refs) - candidate_refs)
        if missing_quarantine_refs:
            raise CrmErpLegacyMappingEvidenceError(
                f"import evidence quarantines unknown tables: {', '.join(missing_quarantine_refs)}"
            )

    def _overrides_by_table(
        self,
        overrides: Sequence[CrmErpLegacyMappingOverride],
    ) -> dict[str, CrmErpLegacyMappingOverride]:
        overrides_by_table: dict[str, CrmErpLegacyMappingOverride] = {}
        for override in overrides:
            if override.source_table_ref in overrides_by_table:
                raise CrmErpLegacyMappingEvidenceError(
                    f"duplicate mapping override for table: {override.source_table_ref}"
                )
            overrides_by_table[override.source_table_ref] = override
        return overrides_by_table

    def _build_decision(
        self,
        *,
        candidate: LegacySqlObjectCandidate,
        quarantine_required: bool,
        override: CrmErpLegacyMappingOverride | None,
    ) -> CrmErpLegacyTableMappingDecision:
        if override is not None:
            return self._build_override_decision(
                candidate=candidate,
                quarantine_required=quarantine_required,
                override=override,
            )
        if (
            candidate.candidate_object_type != "legacy.row"
            and candidate.confidence in {LegacySqlCandidateConfidence.HIGH, LegacySqlCandidateConfidence.MEDIUM}
            and not quarantine_required
        ):
            target_object_type = candidate.candidate_object_type
            action = CrmErpLegacyMappingAction.MAP_TO_TARGET
            decision_quarantine_required = False
            reasons = (
                *candidate.reasons,
                "candidate confidence allows draft target mapping",
                "operator approval still required before import",
            )
        else:
            target_object_type = "legacy.row"
            action = CrmErpLegacyMappingAction.MAP_TO_LEGACY_ROW
            decision_quarantine_required = True
            reasons = (
                *candidate.reasons,
                "safe fallback to legacy.row until manual mapping approval exists",
                "quarantine required before business-object import",
            )
        return self._decision_from_profile(
            candidate=candidate,
            action=action,
            target_object_type=target_object_type,
            quarantine_required=decision_quarantine_required,
            approval_reference=None,
            reasons=reasons,
        )

    def _build_override_decision(
        self,
        *,
        candidate: LegacySqlObjectCandidate,
        quarantine_required: bool,
        override: CrmErpLegacyMappingOverride,
    ) -> CrmErpLegacyTableMappingDecision:
        if override.action == CrmErpLegacyMappingAction.MAP_TO_TARGET:
            target_object_type = override.target_object_type or candidate.candidate_object_type
            if target_object_type == "legacy.row":
                raise CrmErpLegacyMappingEvidenceError("map_to_target override cannot target legacy.row")
            if quarantine_required and override.approval_reference is None:
                raise CrmErpLegacyMappingEvidenceError("quarantined table target mapping requires approval_reference")
            if target_object_type != candidate.candidate_object_type and override.approval_reference is None:
                raise CrmErpLegacyMappingEvidenceError("target override requires approval_reference")
            decision_quarantine_required = False
        elif override.action in {
            CrmErpLegacyMappingAction.MAP_TO_LEGACY_ROW,
            CrmErpLegacyMappingAction.QUARANTINE,
            CrmErpLegacyMappingAction.DEFER,
        }:
            target_object_type = "legacy.row"
            decision_quarantine_required = True
        else:
            raise CrmErpLegacyMappingEvidenceError(f"unsupported mapping action: {override.action}")

        reasons = (
            *candidate.reasons,
            f"manual mapping override: {override.mapping_reason}",
            "operator approval still required before import",
        )
        return self._decision_from_profile(
            candidate=candidate,
            action=override.action,
            target_object_type=target_object_type,
            quarantine_required=decision_quarantine_required,
            approval_reference=override.approval_reference,
            reasons=reasons,
        )

    def _decision_from_profile(
        self,
        *,
        candidate: LegacySqlObjectCandidate,
        action: CrmErpLegacyMappingAction,
        target_object_type: str,
        quarantine_required: bool,
        approval_reference: str | None,
        reasons: tuple[str, ...],
    ) -> CrmErpLegacyTableMappingDecision:
        profile = self._target_profile(target_object_type)
        return CrmErpLegacyTableMappingDecision(
            source_table_ref=candidate.source_table_ref,
            source_candidate_object_type=candidate.candidate_object_type,
            source_candidate_confidence=candidate.confidence,
            action=action,
            target_object_type=profile.object_type,
            feature_id=profile.feature_id,
            classification=profile.classification,
            retention_policy_id=profile.retention_policy_id,
            quarantine_required=quarantine_required,
            approval_reference=approval_reference,
            mapping_reasons=reasons,
        )

    def _target_profile(self, object_type: str) -> CrmErpTargetObjectProfile:
        try:
            return self.target_profiles[object_type]
        except KeyError as exc:
            raise CrmErpLegacyMappingEvidenceError(f"unknown CRM/ERP target object type: {object_type}") from exc


def build_crm_erp_legacy_import_readiness_evidence(
    *,
    discovery_manifest: LegacySqlDiscoveryManifest,
    import_evidence_plan: LegacySqlImportEvidencePlan,
    mapping_manifest: CrmErpLegacyMappingManifest,
) -> CrmErpLegacyImportReadinessEvidence:
    hard_blocking_reasons: list[str] = []
    blocking_reasons: list[str] = []

    if discovery_manifest.module_id != CRM_ERP_MODULE_ID:
        hard_blocking_reasons.append("discovery_manifest_module_mismatch")
    if import_evidence_plan.tenant_id != discovery_manifest.tenant_id:
        hard_blocking_reasons.append("import_evidence_plan_tenant_mismatch")
    if import_evidence_plan.module_id != discovery_manifest.module_id:
        hard_blocking_reasons.append("import_evidence_plan_module_mismatch")
    if import_evidence_plan.source_system_ref != discovery_manifest.source_system_ref:
        hard_blocking_reasons.append("import_evidence_plan_source_system_mismatch")
    if import_evidence_plan.discovery_manifest_hash != discovery_manifest.manifest_hash:
        hard_blocking_reasons.append("import_evidence_plan_discovery_hash_mismatch")
    if mapping_manifest.tenant_id != discovery_manifest.tenant_id:
        hard_blocking_reasons.append("mapping_manifest_tenant_mismatch")
    if mapping_manifest.module_id != discovery_manifest.module_id:
        hard_blocking_reasons.append("mapping_manifest_module_mismatch")
    if mapping_manifest.source_system_ref != discovery_manifest.source_system_ref:
        hard_blocking_reasons.append("mapping_manifest_source_system_mismatch")
    if mapping_manifest.discovery_manifest_hash != discovery_manifest.manifest_hash:
        hard_blocking_reasons.append("mapping_manifest_discovery_hash_mismatch")
    if mapping_manifest.import_evidence_plan_hash != import_evidence_plan.manifest_hash:
        hard_blocking_reasons.append("mapping_manifest_import_plan_hash_mismatch")
    if _hash_mapping_model(mapping_manifest, exclude_manifest_hash=True) != mapping_manifest.manifest_hash:
        hard_blocking_reasons.append("mapping_manifest_hash_invalid")
    if import_evidence_plan.raw_data_import_allowed or mapping_manifest.raw_data_import_allowed:
        hard_blocking_reasons.append("raw_data_import_not_allowed")
    if import_evidence_plan.destructive_actions_allowed or mapping_manifest.destructive_actions_allowed:
        hard_blocking_reasons.append("destructive_actions_not_allowed")

    if mapping_manifest.quarantine_table_refs:
        blocking_reasons.append("quarantine_tables_require_manual_mapping")
    if mapping_manifest.legacy_row_table_refs:
        blocking_reasons.append("legacy_row_fallbacks_require_mapping_review")

    target_mapping_count = sum(
        1 for decision in mapping_manifest.decisions if decision.target_object_type != "legacy.row"
    )
    legacy_row_table_count = len(mapping_manifest.legacy_row_table_refs)
    all_blocking_reasons = tuple(sorted(set(hard_blocking_reasons + blocking_reasons)))
    if hard_blocking_reasons:
        status = CrmErpLegacyImportReadinessStatus.BLOCKED
    elif blocking_reasons:
        status = CrmErpLegacyImportReadinessStatus.MANUAL_MAPPING_REQUIRED
    else:
        status = CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN

    dry_run_allowed = status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN
    draft = CrmErpLegacyImportReadinessEvidence(
        tenant_id=discovery_manifest.tenant_id,
        source_system_ref=discovery_manifest.source_system_ref,
        discovery_manifest_hash=discovery_manifest.manifest_hash,
        import_evidence_plan_hash=import_evidence_plan.manifest_hash,
        mapping_manifest_hash=mapping_manifest.manifest_hash,
        table_count=discovery_manifest.table_count,
        candidate_count=len(discovery_manifest.object_candidates),
        target_mapping_count=target_mapping_count,
        quarantine_table_count=len(mapping_manifest.quarantine_table_refs),
        legacy_row_table_count=legacy_row_table_count,
        manual_review_required=(
            mapping_manifest.mapping_approval_required
            or any(decision.operator_review_required for decision in mapping_manifest.decisions)
        ),
        dry_run_allowed=dry_run_allowed,
        blocking_reasons=all_blocking_reasons,
        next_actions=_legacy_import_readiness_next_actions(status),
        status=status,
        evidence_hash="sha256:pending",
    )
    return draft.model_copy(update={"evidence_hash": _hash_readiness_model(draft)})


def default_crm_erp_target_profiles() -> dict[str, CrmErpTargetObjectProfile]:
    return {
        "crm.account": CrmErpTargetObjectProfile(
            object_type="crm.account",
            feature_id="crm_erp.crm.accounts",
            classification=DataClass.PERSONAL,
            retention_policy_id="rp-standard",
        ),
        "crm.contact": CrmErpTargetObjectProfile(
            object_type="crm.contact",
            feature_id="crm_erp.crm.contacts",
            classification=DataClass.PERSONAL,
            retention_policy_id="rp-standard",
        ),
        "crm.activity": CrmErpTargetObjectProfile(
            object_type="crm.activity",
            feature_id="crm_erp.crm.activities",
            classification=DataClass.PERSONAL,
            retention_policy_id="rp-standard",
        ),
        "crm.note": CrmErpTargetObjectProfile(
            object_type="crm.note",
            feature_id="crm_erp.crm.activities",
            classification=DataClass.PERSONAL,
            retention_policy_id="rp-standard",
        ),
        "erp.product": CrmErpTargetObjectProfile(
            object_type="erp.product",
            feature_id="crm_erp.erp.products",
            classification=DataClass.INTERNAL,
            retention_policy_id="rp-standard",
        ),
        "erp.supplier": CrmErpTargetObjectProfile(
            object_type="erp.supplier",
            feature_id="crm_erp.erp.suppliers",
            classification=DataClass.PERSONAL,
            retention_policy_id="rp-standard",
        ),
        "erp.order": CrmErpTargetObjectProfile(
            object_type="erp.order",
            feature_id="crm_erp.erp.orders",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "erp.order_item": CrmErpTargetObjectProfile(
            object_type="erp.order_item",
            feature_id="crm_erp.erp.orders",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "erp.invoice": CrmErpTargetObjectProfile(
            object_type="erp.invoice",
            feature_id="crm_erp.erp.invoices",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "erp.invoice_item": CrmErpTargetObjectProfile(
            object_type="erp.invoice_item",
            feature_id="crm_erp.erp.invoices",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "erp.delivery_note": CrmErpTargetObjectProfile(
            object_type="erp.delivery_note",
            feature_id="crm_erp.erp.orders",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "erp.contract": CrmErpTargetObjectProfile(
            object_type="erp.contract",
            feature_id="crm_erp.erp.orders",
            classification=DataClass.GOBD,
            retention_policy_id="rp-gobd-10y",
            gobd_relevant=True,
        ),
        "legacy.row": CrmErpTargetObjectProfile(
            object_type="legacy.row",
            feature_id="crm_erp.legacy_import.sqlserver",
            classification=DataClass.CONFIDENTIAL,
            retention_policy_id="rp-restricted",
        ),
    }


def validate_table_ref(value: str) -> None:
    parts = value.split(".")
    if len(parts) != 2 or not all(IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError("source_table_ref must use schema.table identifiers")


def _target_object_counts(decisions: Sequence[CrmErpLegacyTableMappingDecision]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.target_object_type] = counts.get(decision.target_object_type, 0) + 1
    return dict(sorted(counts.items()))


def _hash_mapping_model(model: BaseModel, *, exclude_manifest_hash: bool = False) -> str:
    if exclude_manifest_hash:
        payload = model.model_dump(mode="json", exclude={"manifest_hash"})
    else:
        payload = model.model_dump(mode="json")
    return stable_hash(canonical_json(payload))


def _hash_readiness_model(model: CrmErpLegacyImportReadinessEvidence) -> str:
    payload = model.model_dump(mode="json", exclude={"evidence_hash"})
    return stable_hash(canonical_json(payload))


def _legacy_import_readiness_next_actions(status: CrmErpLegacyImportReadinessStatus) -> tuple[str, ...]:
    if status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN:
        return (
            "run metadata-only legacy import dry-run validation",
            "collect operator approval before any import write",
        )
    if status == CrmErpLegacyImportReadinessStatus.MANUAL_MAPPING_REQUIRED:
        return (
            "review quarantined or legacy.row tables before dry-run",
            "add approved mapping overrides or keep tables deferred",
        )
    return ("repair legacy SQL evidence chain before dry-run",)
