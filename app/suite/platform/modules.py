from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.platform.crm_erp_subfeatures import default_crm_erp_subfeature_enabled_features

MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
FEATURE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModuleKind(StrEnum):
    BUSINESS_DOMAIN = "business_domain"
    PLATFORM_EXTENSION = "platform_extension"
    INTEGRATION = "integration"
    AI_EXTENSION = "ai_extension"


class ModuleStatus(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    AVAILABLE = "available"
    PROVISIONING = "provisioning"
    ENABLED = "enabled"
    DISABLED = "disabled"
    SUSPENDED = "suspended"
    DECOMMISSION_REQUESTED = "decommission_requested"
    DECOMMISSION_BLOCKED = "decommission_blocked"
    DECOMMISSIONED = "decommissioned"


class ModuleGateSurface(StrEnum):
    NORMAL_API = "normal_api"
    COMPLIANCE_API = "compliance_api"
    FEATURE_WORKER = "feature_worker"
    COMPLIANCE_WORKER = "compliance_worker"


NORMAL_USE_STATUS = ModuleStatus.ENABLED
COMPLIANCE_ACCESS_STATUSES = {
    ModuleStatus.ENABLED,
    ModuleStatus.DISABLED,
    ModuleStatus.SUSPENDED,
    ModuleStatus.DECOMMISSION_REQUESTED,
    ModuleStatus.DECOMMISSION_BLOCKED,
}
REQUIRED_DECOMMISSION_EVIDENCE_KEYS = {
    "retention_evaluation_ref",
    "legal_hold_check_ref",
    "export_archive_decision_ref",
    "audit_evidence_ref",
    "backup_restore_evidence_ref",
}
REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS = {
    "blocker_report_ref",
    "remediation_plan_ref",
}
REQUIRED_DECOMMISSION_COMPLETION_EVIDENCE_KEYS = {
    "final_retention_disposition_ref",
    "final_legal_hold_clearance_ref",
    "final_export_archive_manifest_ref",
    "final_audit_closure_ref",
    "final_backup_disposition_ref",
    "final_data_disposition_ref",
}
REQUIRED_DECOMMISSION_CANCEL_EVIDENCE_KEYS = {
    "cancel_approval_ref",
    "cancel_audit_evidence_ref",
}
REQUIRED_DECOMMISSION_REOPEN_EVIDENCE_KEYS = {
    "reopen_approval_ref",
    "blocker_remediation_evidence_ref",
    "reopen_audit_evidence_ref",
}
ALLOWED_DECOMMISSION_EVIDENCE_KEYS = (
    REQUIRED_DECOMMISSION_EVIDENCE_KEYS
    | REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS
    | REQUIRED_DECOMMISSION_COMPLETION_EVIDENCE_KEYS
    | REQUIRED_DECOMMISSION_CANCEL_EVIDENCE_KEYS
    | REQUIRED_DECOMMISSION_REOPEN_EVIDENCE_KEYS
)


class ModuleLifecycleError(ValueError):
    pass


class ModuleDecommissionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    status: ModuleStatus
    can_decommission: bool
    blocking_reasons: list[str]
    required_evidence: list[str]
    checked_at_utc: datetime = Field(default_factory=utc_now)


class ModuleGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    surface: ModuleGateSurface
    status: ModuleStatus
    feature_id: str | None = None
    normal_use_enabled: bool
    compliance_access_allowed: bool


class ModuleLifecycleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_reference: str
    reason: str
    enabled_features: dict[str, bool] | None = None

    @field_validator("approval_reference")
    @classmethod
    def validate_approval_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("approval_reference must be a namespaced reference")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be empty")
        return value


class ModuleDecommissionRequestCommand(ModuleLifecycleCommand):
    retention_evaluation_ref: str
    legal_hold_check_ref: str
    export_archive_decision_ref: str
    audit_evidence_ref: str
    backup_restore_evidence_ref: str

    @field_validator(
        "retention_evaluation_ref",
        "legal_hold_check_ref",
        "export_archive_decision_ref",
        "audit_evidence_ref",
        "backup_restore_evidence_ref",
    )
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("decommission evidence references must be namespaced references")
        return value

    def evidence_refs(self) -> dict[str, str]:
        return {
            "retention_evaluation_ref": self.retention_evaluation_ref,
            "legal_hold_check_ref": self.legal_hold_check_ref,
            "export_archive_decision_ref": self.export_archive_decision_ref,
            "audit_evidence_ref": self.audit_evidence_ref,
            "backup_restore_evidence_ref": self.backup_restore_evidence_ref,
        }


class ModuleDecommissionBlockCommand(ModuleLifecycleCommand):
    blocker_report_ref: str
    remediation_plan_ref: str

    @field_validator("blocker_report_ref", "remediation_plan_ref")
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("decommission blocker evidence references must be namespaced references")
        return value

    def evidence_refs(self) -> dict[str, str]:
        return {
            "blocker_report_ref": self.blocker_report_ref,
            "remediation_plan_ref": self.remediation_plan_ref,
        }


class ModuleDecommissionCompletionCommand(ModuleLifecycleCommand):
    final_retention_disposition_ref: str
    final_legal_hold_clearance_ref: str
    final_export_archive_manifest_ref: str
    final_audit_closure_ref: str
    final_backup_disposition_ref: str
    final_data_disposition_ref: str

    @field_validator(
        "final_retention_disposition_ref",
        "final_legal_hold_clearance_ref",
        "final_export_archive_manifest_ref",
        "final_audit_closure_ref",
        "final_backup_disposition_ref",
        "final_data_disposition_ref",
    )
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("decommission completion evidence references must be namespaced references")
        return value

    def evidence_refs(self) -> dict[str, str]:
        return {
            "final_retention_disposition_ref": self.final_retention_disposition_ref,
            "final_legal_hold_clearance_ref": self.final_legal_hold_clearance_ref,
            "final_export_archive_manifest_ref": self.final_export_archive_manifest_ref,
            "final_audit_closure_ref": self.final_audit_closure_ref,
            "final_backup_disposition_ref": self.final_backup_disposition_ref,
            "final_data_disposition_ref": self.final_data_disposition_ref,
        }


class ModuleDecommissionCancelCommand(ModuleLifecycleCommand):
    cancel_approval_ref: str
    cancel_audit_evidence_ref: str

    @field_validator("cancel_approval_ref", "cancel_audit_evidence_ref")
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("decommission cancel evidence references must be namespaced references")
        return value

    def evidence_refs(self) -> dict[str, str]:
        return {
            "cancel_approval_ref": self.cancel_approval_ref,
            "cancel_audit_evidence_ref": self.cancel_audit_evidence_ref,
        }


class ModuleDecommissionReopenCommand(ModuleLifecycleCommand):
    reopen_approval_ref: str
    blocker_remediation_evidence_ref: str
    reopen_audit_evidence_ref: str

    @field_validator("reopen_approval_ref", "blocker_remediation_evidence_ref", "reopen_audit_evidence_ref")
    @classmethod
    def validate_evidence_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("decommission reopen evidence references must be namespaced references")
        return value

    def evidence_refs(self) -> dict[str, str]:
        return {
            "reopen_approval_ref": self.reopen_approval_ref,
            "blocker_remediation_evidence_ref": self.blocker_remediation_evidence_ref,
            "reopen_audit_evidence_ref": self.reopen_audit_evidence_ref,
        }


class ModuleCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    display_name: str
    module_version: str
    module_kind: ModuleKind
    status: ModuleStatus
    description: str
    manifest_hash: str
    required_migration_versions: tuple[str, ...] = Field(default_factory=tuple)
    min_core_version: str | None = None
    installed_at_utc: datetime = Field(default_factory=utc_now)
    schema_version: str = "module_catalog.v1"

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("module_id must be lowercase snake_case")
        return value

    @field_validator("display_name", "module_version", "description")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("manifest_hash must be a namespaced hash reference")
        return value

    @field_validator("required_migration_versions")
    @classmethod
    def validate_required_migration_versions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("required_migration_versions must not contain duplicates")
        for version in value:
            if not version.isdigit() or len(version) != 4:
                raise ValueError("required_migration_versions must contain four digit migration versions")
        return value

    @model_validator(mode="after")
    def require_deployable_catalog_status(self) -> ModuleCatalogEntry:
        if self.status in {
            ModuleStatus.PROVISIONING,
            ModuleStatus.ENABLED,
            ModuleStatus.DISABLED,
            ModuleStatus.SUSPENDED,
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ValueError("catalog status must describe deployment availability, not tenant lifecycle")
        return self


class ModuleMigrationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    version: str
    name: str
    module_id: str
    checksum: str
    evidence_refs: tuple[str, ...]
    blocks_startup: bool

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 4:
            raise ValueError("migration version must be a four digit string")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("migration name must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("migration module_id must be lowercase snake_case")
        return value

    @field_validator("checksum")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("migration checksum must be a namespaced reference")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("migration evidence_refs must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("migration evidence_refs must not contain duplicates")
        for evidence_ref in value:
            if not NAMESPACED_REF_PATTERN.fullmatch(evidence_ref):
                raise ValueError("migration evidence_refs must be namespaced references")
        return value


class TenantModuleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    status: ModuleStatus
    policy_snapshot_hash: str
    changed_by: str
    audit_chain_ref: str
    enabled_features: dict[str, bool] = Field(default_factory=dict)
    migration_evidence: tuple[ModuleMigrationEvidence, ...] = Field(default_factory=tuple)
    decommission_evidence_refs: dict[str, str] = Field(default_factory=dict)
    provisioned_at_utc: datetime | None = None
    enabled_at_utc: datetime | None = None
    disabled_at_utc: datetime | None = None
    decommission_requested_at_utc: datetime | None = None
    decommission_blocked_at_utc: datetime | None = None
    decommission_cancelled_at_utc: datetime | None = None
    decommission_reopened_at_utc: datetime | None = None
    decommissioned_at_utc: datetime | None = None
    created_at_utc: datetime = Field(default_factory=utc_now)
    updated_at_utc: datetime = Field(default_factory=utc_now)
    schema_version: str = "tenant_module.v1"

    @field_validator("tenant_id", "changed_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("module_id must be lowercase snake_case")
        return value

    @field_validator("policy_snapshot_hash", "audit_chain_ref")
    @classmethod
    def validate_namespaced_reference(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("value must be a namespaced reference")
        return value

    @model_validator(mode="after")
    def require_status_evidence_and_feature_scope(self) -> TenantModuleState:
        for feature_id in self.enabled_features:
            if not FEATURE_ID_PATTERN.fullmatch(feature_id):
                raise ValueError("feature IDs must be namespaced module features")
            if not feature_id.startswith(f"{self.module_id}."):
                raise ValueError("feature IDs must belong to the tenant module")

        migration_versions: set[str] = set()
        for migration_evidence in self.migration_evidence:
            if migration_evidence.version in migration_versions:
                raise ValueError("migration evidence versions must be unique")
            migration_versions.add(migration_evidence.version)
            if migration_evidence.module_id not in {"core", self.module_id}:
                raise ValueError("migration evidence must belong to core or the tenant module")

        for evidence_key, evidence_ref in self.decommission_evidence_refs.items():
            if evidence_key not in ALLOWED_DECOMMISSION_EVIDENCE_KEYS:
                raise ValueError("unknown decommission evidence key")
            if not NAMESPACED_REF_PATTERN.fullmatch(evidence_ref):
                raise ValueError("decommission evidence references must be namespaced references")

        if self.status == ModuleStatus.ENABLED and self.enabled_at_utc is None:
            raise ValueError("enabled module state requires enabled_at_utc")
        if self.status == ModuleStatus.DISABLED and self.disabled_at_utc is None:
            raise ValueError("disabled module state requires disabled_at_utc")
        if self.status == ModuleStatus.DECOMMISSION_REQUESTED and self.decommission_requested_at_utc is None:
            raise ValueError("decommission_requested module state requires decommission_requested_at_utc")
        if self.status == ModuleStatus.DECOMMISSION_REQUESTED:
            missing_evidence = REQUIRED_DECOMMISSION_EVIDENCE_KEYS - set(self.decommission_evidence_refs)
            if missing_evidence:
                raise ValueError("decommission_requested module state requires complete decommission evidence")
            if any(self.enabled_features.values()):
                raise ValueError("decommission_requested module cannot keep enabled features")
        if self.status == ModuleStatus.DECOMMISSION_BLOCKED:
            if self.decommission_requested_at_utc is None:
                raise ValueError("decommission_blocked module state requires decommission_requested_at_utc")
            if self.decommission_blocked_at_utc is None:
                raise ValueError("decommission_blocked module state requires decommission_blocked_at_utc")
            missing_evidence = (
                REQUIRED_DECOMMISSION_EVIDENCE_KEYS | REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS
            ) - set(self.decommission_evidence_refs)
            if missing_evidence:
                raise ValueError("decommission_blocked module state requires blocker evidence")
            if any(self.enabled_features.values()):
                raise ValueError("decommission_blocked module cannot keep enabled features")
        if self.status == ModuleStatus.DECOMMISSIONED:
            if self.decommission_requested_at_utc is None:
                raise ValueError("decommissioned module state requires decommission_requested_at_utc")
            if self.decommissioned_at_utc is None:
                raise ValueError("decommissioned module state requires decommissioned_at_utc")
            missing_evidence = (
                REQUIRED_DECOMMISSION_EVIDENCE_KEYS | REQUIRED_DECOMMISSION_COMPLETION_EVIDENCE_KEYS
            ) - set(self.decommission_evidence_refs)
            if missing_evidence:
                raise ValueError("decommissioned module state requires final disposition evidence")
            if any(self.enabled_features.values()):
                raise ValueError("decommissioned module cannot keep enabled features")
        if self.decommission_cancelled_at_utc is not None:
            missing_evidence = REQUIRED_DECOMMISSION_CANCEL_EVIDENCE_KEYS - set(self.decommission_evidence_refs)
            if missing_evidence:
                raise ValueError("cancelled decommission module state requires cancel evidence")
            if self.status == ModuleStatus.DISABLED and any(self.enabled_features.values()):
                raise ValueError("cancelled decommission module cannot keep enabled features while disabled")
        if self.decommission_reopened_at_utc is not None:
            if self.decommission_requested_at_utc is None:
                raise ValueError("reopened decommission module state requires decommission_requested_at_utc")
            if self.decommission_blocked_at_utc is None:
                raise ValueError("reopened decommission module state requires decommission_blocked_at_utc")
            missing_evidence = (
                REQUIRED_DECOMMISSION_EVIDENCE_KEYS
                | REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS
                | REQUIRED_DECOMMISSION_REOPEN_EVIDENCE_KEYS
            ) - set(self.decommission_evidence_refs)
            if missing_evidence:
                raise ValueError("reopened decommission module state requires reopen evidence")
        return self

    @property
    def normal_use_enabled(self) -> bool:
        return self.status == NORMAL_USE_STATUS

    @property
    def compliance_access_allowed(self) -> bool:
        return self.status in COMPLIANCE_ACCESS_STATUSES

    def feature_enabled(self, feature_id: str) -> bool:
        return self.normal_use_enabled and self.enabled_features.get(feature_id, False)


class PlatformModuleView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    display_name: str
    module_version: str
    module_kind: ModuleKind
    status: ModuleStatus
    enabled_features: dict[str, bool]
    normal_use_enabled: bool
    compliance_access_allowed: bool


class PlatformModulesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    modules: list[PlatformModuleView]


class TenantModuleAdminView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    status: ModuleStatus
    enabled_features: dict[str, bool]
    migration_evidence: tuple[ModuleMigrationEvidence, ...]
    normal_use_enabled: bool
    compliance_access_allowed: bool
    provisioned_at_utc: datetime | None = None
    enabled_at_utc: datetime | None = None
    disabled_at_utc: datetime | None = None
    decommission_requested_at_utc: datetime | None = None
    decommission_blocked_at_utc: datetime | None = None
    decommission_cancelled_at_utc: datetime | None = None
    decommission_reopened_at_utc: datetime | None = None
    decommissioned_at_utc: datetime | None = None
    decommission_evidence_refs: dict[str, str]
    updated_at_utc: datetime
    audit_chain_ref: str


def tenant_module_admin_view(state: TenantModuleState) -> TenantModuleAdminView:
    return TenantModuleAdminView(
        tenant_id=state.tenant_id,
        module_id=state.module_id,
        status=state.status,
        enabled_features=dict(sorted(state.enabled_features.items())),
        migration_evidence=tuple(sorted(state.migration_evidence, key=lambda evidence: evidence.version)),
        normal_use_enabled=state.normal_use_enabled,
        compliance_access_allowed=state.compliance_access_allowed,
        provisioned_at_utc=state.provisioned_at_utc,
        enabled_at_utc=state.enabled_at_utc,
        disabled_at_utc=state.disabled_at_utc,
        decommission_requested_at_utc=state.decommission_requested_at_utc,
        decommission_blocked_at_utc=state.decommission_blocked_at_utc,
        decommission_cancelled_at_utc=state.decommission_cancelled_at_utc,
        decommission_reopened_at_utc=state.decommission_reopened_at_utc,
        decommissioned_at_utc=state.decommissioned_at_utc,
        decommission_evidence_refs=dict(sorted(state.decommission_evidence_refs.items())),
        updated_at_utc=state.updated_at_utc,
        audit_chain_ref=state.audit_chain_ref,
    )


class InMemoryModuleRegistry:
    def __init__(
        self,
        *,
        catalog_entries: list[ModuleCatalogEntry] | None = None,
        tenant_modules: list[TenantModuleState] | None = None,
    ) -> None:
        self._catalog: dict[str, ModuleCatalogEntry] = {}
        self._tenant_modules: dict[tuple[str, str], TenantModuleState] = {}

        for entry in catalog_entries or []:
            self.add_catalog_entry(entry)
        for tenant_module in tenant_modules or []:
            self.upsert_tenant_module(tenant_module)

    def add_catalog_entry(self, entry: ModuleCatalogEntry) -> ModuleCatalogEntry:
        if entry.module_id in self._catalog:
            raise ModuleLifecycleError(f"Module already exists in catalog: {entry.module_id}")
        self._catalog[entry.module_id] = entry
        return entry

    def get_catalog_entry(self, module_id: str) -> ModuleCatalogEntry:
        try:
            return self._catalog[module_id]
        except KeyError as exc:
            raise LookupError(f"Unknown module catalog entry: {module_id}") from exc

    def list_catalog_entries(self) -> tuple[ModuleCatalogEntry, ...]:
        return tuple(sorted(self._catalog.values(), key=lambda entry: entry.module_id))

    def upsert_tenant_module(self, state: TenantModuleState) -> TenantModuleState:
        catalog_entry = self.get_catalog_entry(state.module_id)
        if catalog_entry.status == ModuleStatus.NOT_INSTALLED:
            raise ModuleLifecycleError(f"Module is not installed: {state.module_id}")
        self._tenant_modules[(state.tenant_id, state.module_id)] = state
        return state

    def get_tenant_module(self, tenant_id: str, module_id: str) -> TenantModuleState:
        try:
            return self._tenant_modules[(tenant_id, module_id)]
        except KeyError as exc:
            raise LookupError(f"Unknown tenant module: {tenant_id}/{module_id}") from exc

    def list_tenant_modules(self, tenant_id: str) -> tuple[TenantModuleState, ...]:
        states = [state for (state_tenant_id, _), state in self._tenant_modules.items() if state_tenant_id == tenant_id]
        return tuple(sorted(states, key=lambda state: state.module_id))

    def require_normal_use(self, *, tenant_id: str, module_id: str, feature_id: str | None = None) -> TenantModuleState:
        state = self.get_tenant_module(tenant_id, module_id)
        if not state.normal_use_enabled:
            raise ModuleLifecycleError(f"Module is not enabled for normal use: {module_id}")
        if feature_id is not None and not state.feature_enabled(feature_id):
            raise ModuleLifecycleError(f"Module feature is not enabled: {feature_id}")
        return state

    def require_compliance_access(self, *, tenant_id: str, module_id: str) -> TenantModuleState:
        state = self.get_tenant_module(tenant_id, module_id)
        if not state.compliance_access_allowed:
            raise ModuleLifecycleError(f"Module state does not allow compliance access: {module_id}")
        return state

    @staticmethod
    def _migration_evidence_by_version(
        migration_manifest_entries: Iterable[object] | None,
    ) -> dict[str, ModuleMigrationEvidence]:
        if migration_manifest_entries is None:
            return {}

        evidence_by_version: dict[str, ModuleMigrationEvidence] = {}
        for entry in migration_manifest_entries:
            evidence = ModuleMigrationEvidence.model_validate(entry)
            if evidence.version in evidence_by_version:
                raise ModuleLifecycleError(f"Duplicate migration manifest evidence: {evidence.version}")
            evidence_by_version[evidence.version] = evidence
        return evidence_by_version

    @staticmethod
    def _required_versions(catalog_entry: ModuleCatalogEntry) -> set[str]:
        return set(catalog_entry.required_migration_versions)

    def migration_evidence_for_module(
        self,
        *,
        module_id: str,
        migration_manifest_entries: Iterable[object] | None,
    ) -> tuple[ModuleMigrationEvidence, ...]:
        catalog_entry = self.get_catalog_entry(module_id)
        required_versions = self._required_versions(catalog_entry)
        if not required_versions:
            return ()

        evidence_by_version = self._migration_evidence_by_version(migration_manifest_entries)
        missing_versions = sorted(required_versions - set(evidence_by_version))
        if missing_versions:
            raise ModuleLifecycleError(
                f"Missing startup migrations for module {module_id}: {', '.join(missing_versions)}"
            )

        migration_evidence: list[ModuleMigrationEvidence] = []
        for version in sorted(required_versions):
            evidence = evidence_by_version[version]
            if not evidence.blocks_startup:
                raise ModuleLifecycleError(f"Required migration does not block startup: {version}")
            if evidence.module_id not in {"core", module_id}:
                raise ModuleLifecycleError(
                    f"Migration {version} belongs to {evidence.module_id}, not core or module {module_id}"
                )
            migration_evidence.append(evidence)
        return tuple(migration_evidence)

    def _require_state_migration_evidence(
        self,
        *,
        catalog_entry: ModuleCatalogEntry,
        state: TenantModuleState,
    ) -> None:
        required_versions = self._required_versions(catalog_entry)
        if not required_versions:
            return

        available_versions = {evidence.version for evidence in state.migration_evidence if evidence.blocks_startup}
        missing_versions = sorted(required_versions - available_versions)
        if missing_versions:
            raise ModuleLifecycleError(f"Module startup migrations are missing evidence: {', '.join(missing_versions)}")

    @staticmethod
    def _validate_gate_feature_id(*, module_id: str, feature_id: str) -> None:
        if not FEATURE_ID_PATTERN.fullmatch(feature_id):
            raise ModuleLifecycleError(f"Module feature ID is not namespaced: {feature_id}")
        if not feature_id.startswith(f"{module_id}."):
            raise ModuleLifecycleError(f"Module feature does not belong to module {module_id}: {feature_id}")

    def require_module_gate(
        self,
        *,
        tenant_id: str,
        module_id: str,
        surface: ModuleGateSurface,
        feature_id: str | None = None,
    ) -> ModuleGateDecision:
        state = self.get_tenant_module(tenant_id, module_id)
        if feature_id is not None:
            self._validate_gate_feature_id(module_id=module_id, feature_id=feature_id)

        if surface in {ModuleGateSurface.NORMAL_API, ModuleGateSurface.FEATURE_WORKER}:
            self.require_normal_use(tenant_id=tenant_id, module_id=module_id, feature_id=feature_id)
            self._require_state_migration_evidence(catalog_entry=self.get_catalog_entry(module_id), state=state)
        if surface in {ModuleGateSurface.COMPLIANCE_API, ModuleGateSurface.COMPLIANCE_WORKER}:
            self.require_compliance_access(tenant_id=tenant_id, module_id=module_id)

        return ModuleGateDecision(
            tenant_id=tenant_id,
            module_id=module_id,
            surface=surface,
            status=state.status,
            feature_id=feature_id,
            normal_use_enabled=state.normal_use_enabled,
            compliance_access_allowed=state.compliance_access_allowed,
        )

    def discover_tenant_modules(self, tenant_id: str) -> PlatformModulesResponse:
        modules = []
        for state in self.list_tenant_modules(tenant_id):
            catalog_entry = self.get_catalog_entry(state.module_id)
            modules.append(
                PlatformModuleView(
                    module_id=state.module_id,
                    display_name=catalog_entry.display_name,
                    module_version=catalog_entry.module_version,
                    module_kind=catalog_entry.module_kind,
                    status=state.status,
                    enabled_features=dict(sorted(state.enabled_features.items())),
                    normal_use_enabled=state.normal_use_enabled,
                    compliance_access_allowed=state.compliance_access_allowed,
                )
            )
        return PlatformModulesResponse(tenant_id=tenant_id, modules=modules)

    def provision_tenant_module(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        enabled_features: dict[str, bool] | None = None,
        migration_manifest_entries: Iterable[object] | None = None,
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        catalog_entry = self.get_catalog_entry(module_id)
        now = changed_at_utc or utc_now()
        existing = self._tenant_modules.get((tenant_id, module_id))
        if existing is not None and existing.status in {
            ModuleStatus.ENABLED,
            ModuleStatus.DISABLED,
            ModuleStatus.SUSPENDED,
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ModuleLifecycleError(f"Module is already provisioned or not provisionable: {module_id}")

        next_enabled_features = enabled_features if enabled_features is not None else {}
        if enabled_features is None and existing is not None:
            next_enabled_features = existing.enabled_features
        migration_evidence = self.migration_evidence_for_module(
            module_id=module_id,
            migration_manifest_entries=migration_manifest_entries,
        )
        if not migration_evidence and existing is not None:
            migration_evidence = existing.migration_evidence

        if self._required_versions(catalog_entry) and not migration_evidence:
            raise ModuleLifecycleError(f"Missing migration evidence for module provision: {module_id}")

        state = TenantModuleState(
            tenant_id=tenant_id,
            module_id=module_id,
            status=ModuleStatus.DISABLED,
            enabled_features=next_enabled_features,
            migration_evidence=migration_evidence,
            policy_snapshot_hash=policy_snapshot_hash,
            provisioned_at_utc=now,
            disabled_at_utc=now,
            changed_by=changed_by,
            audit_chain_ref=audit_chain_ref,
            created_at_utc=existing.created_at_utc if existing else now,
            updated_at_utc=now,
        )
        return self.upsert_tenant_module(state)

    def enable_tenant_module(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        enabled_features: dict[str, bool] | None = None,
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        catalog_entry = self.get_catalog_entry(module_id)
        if existing.provisioned_at_utc is None:
            raise ModuleLifecycleError(f"Module must be provisioned before enablement: {module_id}")
        if existing.status in {
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ModuleLifecycleError(f"Module cannot be enabled from state {existing.status}: {module_id}")
        self._require_state_migration_evidence(catalog_entry=catalog_entry, state=existing)

        now = changed_at_utc or utc_now()
        state = existing.model_copy(
            update={
                "status": ModuleStatus.ENABLED,
                "enabled_features": enabled_features if enabled_features is not None else existing.enabled_features,
                "policy_snapshot_hash": policy_snapshot_hash,
                "enabled_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def disable_tenant_module(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status in {
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ModuleLifecycleError(f"Module is in decommission workflow: {module_id}")

        now = changed_at_utc or utc_now()
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DISABLED,
                "policy_snapshot_hash": policy_snapshot_hash,
                "disabled_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def suspend_tenant_module(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status in {
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ModuleLifecycleError(f"Module is in decommission workflow: {module_id}")

        now = changed_at_utc or utc_now()
        state = existing.model_copy(
            update={
                "status": ModuleStatus.SUSPENDED,
                "policy_snapshot_hash": policy_snapshot_hash,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def decommission_check(self, *, tenant_id: str, module_id: str) -> ModuleDecommissionCheck:
        state = self.get_tenant_module(tenant_id, module_id)
        blocking_reasons: list[str] = []
        if state.status == ModuleStatus.ENABLED:
            blocking_reasons.append("module must be disabled or suspended before decommission")
        if state.status == ModuleStatus.PROVISIONING:
            blocking_reasons.append("module provisioning must complete before decommission")
        if state.status == ModuleStatus.DECOMMISSIONED:
            blocking_reasons.append("module is already decommissioned")

        required_evidence = [
            "retention evaluation",
            "Legal Hold check",
            "export/archive decision",
            "audit evidence check",
            "backup/restore evidence check",
            "human approval reference",
        ]
        return ModuleDecommissionCheck(
            tenant_id=tenant_id,
            module_id=module_id,
            status=state.status,
            can_decommission=False,
            blocking_reasons=blocking_reasons,
            required_evidence=required_evidence,
        )

    @staticmethod
    def _require_decommission_evidence(
        evidence_refs: dict[str, str],
        required_keys: set[str],
        workflow_name: str,
    ) -> None:
        missing_evidence = required_keys - set(evidence_refs)
        if missing_evidence:
            raise ModuleLifecycleError(
                f"Missing decommission {workflow_name} evidence: {', '.join(sorted(missing_evidence))}"
            )

    def request_decommission(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        decommission_evidence_refs: dict[str, str],
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        check = self.decommission_check(tenant_id=tenant_id, module_id=module_id)
        if existing.provisioned_at_utc is None:
            raise ModuleLifecycleError(f"Module must be provisioned before decommission request: {module_id}")
        if existing.status not in {ModuleStatus.DISABLED, ModuleStatus.SUSPENDED}:
            raise ModuleLifecycleError(f"Module must be disabled or suspended before decommission request: {module_id}")
        if check.blocking_reasons:
            raise ModuleLifecycleError(f"Module cannot request decommission: {'; '.join(check.blocking_reasons)}")

        self._require_decommission_evidence(
            decommission_evidence_refs,
            REQUIRED_DECOMMISSION_EVIDENCE_KEYS,
            "request",
        )

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DECOMMISSION_REQUESTED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(
                    sorted({**existing.decommission_evidence_refs, **decommission_evidence_refs}.items())
                ),
                "policy_snapshot_hash": policy_snapshot_hash,
                "decommission_requested_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def block_decommission(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        blocker_evidence_refs: dict[str, str],
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status not in {ModuleStatus.DECOMMISSION_REQUESTED, ModuleStatus.DECOMMISSION_BLOCKED}:
            raise ModuleLifecycleError(f"Module must have a decommission request before blocking: {module_id}")
        if existing.decommission_requested_at_utc is None:
            raise ModuleLifecycleError(f"Module must have request timestamp before blocking: {module_id}")
        self._require_decommission_evidence(
            existing.decommission_evidence_refs,
            REQUIRED_DECOMMISSION_EVIDENCE_KEYS,
            "request",
        )
        self._require_decommission_evidence(
            blocker_evidence_refs,
            REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS,
            "blocker",
        )

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DECOMMISSION_BLOCKED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(
                    sorted({**existing.decommission_evidence_refs, **blocker_evidence_refs}.items())
                ),
                "policy_snapshot_hash": policy_snapshot_hash,
                "decommission_blocked_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def cancel_decommission(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        cancel_evidence_refs: dict[str, str],
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status not in {ModuleStatus.DECOMMISSION_REQUESTED, ModuleStatus.DECOMMISSION_BLOCKED}:
            raise ModuleLifecycleError(
                f"Module must have an active decommission workflow before cancellation: {module_id}"
            )
        if existing.decommission_requested_at_utc is None:
            raise ModuleLifecycleError(f"Module must have request timestamp before cancellation: {module_id}")
        self._require_decommission_evidence(
            existing.decommission_evidence_refs,
            REQUIRED_DECOMMISSION_EVIDENCE_KEYS,
            "request",
        )
        self._require_decommission_evidence(
            cancel_evidence_refs,
            REQUIRED_DECOMMISSION_CANCEL_EVIDENCE_KEYS,
            "cancel",
        )

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DISABLED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(
                    sorted({**existing.decommission_evidence_refs, **cancel_evidence_refs}.items())
                ),
                "policy_snapshot_hash": policy_snapshot_hash,
                "disabled_at_utc": now,
                "decommission_cancelled_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def reopen_decommission(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        reopen_evidence_refs: dict[str, str],
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status != ModuleStatus.DECOMMISSION_BLOCKED:
            raise ModuleLifecycleError(f"Module must have a blocked decommission workflow before reopen: {module_id}")
        if existing.decommission_requested_at_utc is None or existing.decommission_blocked_at_utc is None:
            raise ModuleLifecycleError(f"Module must have request and blocked timestamps before reopen: {module_id}")
        self._require_decommission_evidence(
            existing.decommission_evidence_refs,
            REQUIRED_DECOMMISSION_EVIDENCE_KEYS | REQUIRED_DECOMMISSION_BLOCKER_EVIDENCE_KEYS,
            "blocked",
        )
        self._require_decommission_evidence(
            reopen_evidence_refs,
            REQUIRED_DECOMMISSION_REOPEN_EVIDENCE_KEYS,
            "reopen",
        )

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DECOMMISSION_REQUESTED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(
                    sorted({**existing.decommission_evidence_refs, **reopen_evidence_refs}.items())
                ),
                "policy_snapshot_hash": policy_snapshot_hash,
                "decommission_reopened_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))

    def complete_decommission(
        self,
        *,
        tenant_id: str,
        module_id: str,
        policy_snapshot_hash: str,
        changed_by: str,
        audit_chain_ref: str,
        completion_evidence_refs: dict[str, str],
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        existing = self.get_tenant_module(tenant_id, module_id)
        if existing.status not in {ModuleStatus.DECOMMISSION_REQUESTED, ModuleStatus.DECOMMISSION_BLOCKED}:
            raise ModuleLifecycleError(f"Module must have a decommission request before completion: {module_id}")
        if existing.decommission_requested_at_utc is None:
            raise ModuleLifecycleError(f"Module must have request timestamp before completion: {module_id}")
        self._require_decommission_evidence(
            existing.decommission_evidence_refs,
            REQUIRED_DECOMMISSION_EVIDENCE_KEYS,
            "request",
        )
        self._require_decommission_evidence(
            completion_evidence_refs,
            REQUIRED_DECOMMISSION_COMPLETION_EVIDENCE_KEYS,
            "completion",
        )

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DECOMMISSIONED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(
                    sorted({**existing.decommission_evidence_refs, **completion_evidence_refs}.items())
                ),
                "policy_snapshot_hash": policy_snapshot_hash,
                "decommissioned_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))


class ModuleWorkerGate:
    def __init__(self, registry: InMemoryModuleRegistry) -> None:
        self.registry = registry

    def require_feature_worker(
        self,
        *,
        tenant_id: str,
        module_id: str,
        feature_id: str,
    ) -> ModuleGateDecision:
        return self.registry.require_module_gate(
            tenant_id=tenant_id,
            module_id=module_id,
            surface=ModuleGateSurface.FEATURE_WORKER,
            feature_id=feature_id,
        )

    def require_compliance_worker(
        self,
        *,
        tenant_id: str,
        module_id: str,
    ) -> ModuleGateDecision:
        return self.registry.require_module_gate(
            tenant_id=tenant_id,
            module_id=module_id,
            surface=ModuleGateSurface.COMPLIANCE_WORKER,
        )


def default_module_registry() -> InMemoryModuleRegistry:
    crm_erp_catalog = ModuleCatalogEntry(
        module_id="crm_erp",
        display_name="CRM/ERP",
        module_version="0.1.0",
        module_kind=ModuleKind.BUSINESS_DOMAIN,
        status=ModuleStatus.INSTALLED,
        description="Optional CRM/ERP business module.",
        manifest_hash="sha256:crm-erp-module-manifest",
        required_migration_versions=("0007", "0008", "0009", "0010", "0011"),
    )
    crm_erp_demo_state = TenantModuleState(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        status=ModuleStatus.AVAILABLE,
        enabled_features=default_crm_erp_subfeature_enabled_features(),
        policy_snapshot_hash="sha256:demo-module-policy",
        changed_by="system",
        audit_chain_ref="audit:module-seed",
    )
    return InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog],
        tenant_modules=[crm_erp_demo_state],
    )
