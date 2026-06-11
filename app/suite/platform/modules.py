from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


NORMAL_USE_STATUS = ModuleStatus.ENABLED
COMPLIANCE_ACCESS_STATUSES = {
    ModuleStatus.ENABLED,
    ModuleStatus.DISABLED,
    ModuleStatus.SUSPENDED,
    ModuleStatus.DECOMMISSION_REQUESTED,
    ModuleStatus.DECOMMISSION_BLOCKED,
}


class ModuleLifecycleError(ValueError):
    pass


class ModuleCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    display_name: str
    module_version: str
    module_kind: ModuleKind
    status: ModuleStatus
    description: str
    manifest_hash: str
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


class TenantModuleState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    status: ModuleStatus
    policy_snapshot_hash: str
    changed_by: str
    audit_chain_ref: str
    enabled_features: dict[str, bool] = Field(default_factory=dict)
    provisioned_at_utc: datetime | None = None
    enabled_at_utc: datetime | None = None
    disabled_at_utc: datetime | None = None
    decommission_requested_at_utc: datetime | None = None
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

        if self.status == ModuleStatus.ENABLED and self.enabled_at_utc is None:
            raise ValueError("enabled module state requires enabled_at_utc")
        if self.status == ModuleStatus.DISABLED and self.disabled_at_utc is None:
            raise ValueError("disabled module state requires disabled_at_utc")
        if self.status == ModuleStatus.DECOMMISSION_REQUESTED and self.decommission_requested_at_utc is None:
            raise ValueError("decommission_requested module state requires decommission_requested_at_utc")
        if self.status == ModuleStatus.DECOMMISSIONED:
            if self.decommissioned_at_utc is None:
                raise ValueError("decommissioned module state requires decommissioned_at_utc")
            if any(self.enabled_features.values()):
                raise ValueError("decommissioned module cannot keep enabled features")
        return self

    @property
    def normal_use_enabled(self) -> bool:
        return self.status == NORMAL_USE_STATUS

    @property
    def compliance_access_allowed(self) -> bool:
        return self.status in COMPLIANCE_ACCESS_STATUSES

    def feature_enabled(self, feature_id: str) -> bool:
        return self.normal_use_enabled and self.enabled_features.get(feature_id, False)


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
