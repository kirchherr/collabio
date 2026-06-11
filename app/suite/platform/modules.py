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
REQUIRED_DECOMMISSION_EVIDENCE_KEYS = {
    "retention_evaluation_ref",
    "legal_hold_check_ref",
    "export_archive_decision_ref",
    "audit_evidence_ref",
    "backup_restore_evidence_ref",
}


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
    decommission_evidence_refs: dict[str, str] = Field(default_factory=dict)
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

        for evidence_key, evidence_ref in self.decommission_evidence_refs.items():
            if evidence_key not in REQUIRED_DECOMMISSION_EVIDENCE_KEYS:
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
    normal_use_enabled: bool
    compliance_access_allowed: bool
    provisioned_at_utc: datetime | None = None
    enabled_at_utc: datetime | None = None
    disabled_at_utc: datetime | None = None
    decommission_requested_at_utc: datetime | None = None
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
        normal_use_enabled=state.normal_use_enabled,
        compliance_access_allowed=state.compliance_access_allowed,
        provisioned_at_utc=state.provisioned_at_utc,
        enabled_at_utc=state.enabled_at_utc,
        disabled_at_utc=state.disabled_at_utc,
        decommission_requested_at_utc=state.decommission_requested_at_utc,
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
        changed_at_utc: datetime | None = None,
    ) -> TenantModuleState:
        self.get_catalog_entry(module_id)
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

        state = TenantModuleState(
            tenant_id=tenant_id,
            module_id=module_id,
            status=ModuleStatus.DISABLED,
            enabled_features=next_enabled_features,
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
        if existing.provisioned_at_utc is None:
            raise ModuleLifecycleError(f"Module must be provisioned before enablement: {module_id}")
        if existing.status in {
            ModuleStatus.DECOMMISSION_REQUESTED,
            ModuleStatus.DECOMMISSION_BLOCKED,
            ModuleStatus.DECOMMISSIONED,
        }:
            raise ModuleLifecycleError(f"Module cannot be enabled from state {existing.status}: {module_id}")

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
        if existing.status == ModuleStatus.DECOMMISSIONED:
            raise ModuleLifecycleError(f"Module is decommissioned: {module_id}")

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
        if existing.status == ModuleStatus.DECOMMISSIONED:
            raise ModuleLifecycleError(f"Module is decommissioned: {module_id}")

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

        missing_evidence = REQUIRED_DECOMMISSION_EVIDENCE_KEYS - set(decommission_evidence_refs)
        if missing_evidence:
            raise ModuleLifecycleError(f"Missing decommission evidence: {', '.join(sorted(missing_evidence))}")

        now = changed_at_utc or utc_now()
        disabled_features = {feature_id: False for feature_id in existing.enabled_features}
        state = existing.model_copy(
            update={
                "status": ModuleStatus.DECOMMISSION_REQUESTED,
                "enabled_features": disabled_features,
                "decommission_evidence_refs": dict(sorted(decommission_evidence_refs.items())),
                "policy_snapshot_hash": policy_snapshot_hash,
                "decommission_requested_at_utc": now,
                "changed_by": changed_by,
                "audit_chain_ref": audit_chain_ref,
                "updated_at_utc": now,
            }
        )
        return self.upsert_tenant_module(TenantModuleState.model_validate(state.model_dump()))


def default_module_registry() -> InMemoryModuleRegistry:
    crm_erp_catalog = ModuleCatalogEntry(
        module_id="crm_erp",
        display_name="CRM/ERP",
        module_version="0.1.0",
        module_kind=ModuleKind.BUSINESS_DOMAIN,
        status=ModuleStatus.INSTALLED,
        description="Optional CRM/ERP business module.",
        manifest_hash="sha256:crm-erp-module-manifest",
    )
    crm_erp_demo_state = TenantModuleState(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        status=ModuleStatus.AVAILABLE,
        enabled_features={
            "crm_erp.crm.accounts": False,
            "crm_erp.crm.activities": False,
            "crm_erp.crm.contacts": False,
            "crm_erp.erp.invoices": False,
            "crm_erp.erp.orders": False,
            "crm_erp.erp.products": False,
            "crm_erp.erp.suppliers": False,
            "crm_erp.gobd_export": False,
            "crm_erp.legal_hold": False,
            "crm_erp.legacy_import.sqlserver": False,
            "crm_erp.rag_indexing": False,
            "crm_erp.ai_assist": False,
        },
        policy_snapshot_hash="sha256:demo-module-policy",
        changed_by="system",
        audit_chain_ref="audit:module-seed",
    )
    return InMemoryModuleRegistry(
        catalog_entries=[crm_erp_catalog],
        tenant_modules=[crm_erp_demo_state],
    )
