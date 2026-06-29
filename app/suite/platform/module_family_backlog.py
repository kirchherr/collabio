from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

MODULE_FAMILY_BACKLOG_SCHEMA_VERSION = "platform_module_family_backlog.v1"
MODULE_FAMILY_BACKLOG_RESULT_CONTRACT = "metadata_only_future_module_backlog_no_activation"
MODULE_FAMILY_BACKLOG_ENDPOINT = "/v1/platform/modules/families/backlog"
MODULE_IMPLEMENTATION_CONTRACT_SCHEMA_VERSION = "module_implementation_contract.v1"
MODULE_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

MODULE_FAMILY_DISPLAY_NAMES = {
    "knowledge_base": "Knowledge Base",
    "lms": "Learning Management",
    "tasks_activities": "Tasks and Activities",
    "tickets_incidents": "Tickets and Incidents",
    "time_tracking": "Time Tracking",
}
MODULE_FAMILY_MODULE_IDS = {
    "knowledge_base": "knowledge_base",
    "lms": "lms",
    "tasks_activities": "tasks_activities",
    "tickets_incidents": "tickets_incidents",
    "time_tracking": "time_tracking",
}
PLANNED_MODULE_NEXT_ACTION = "create_module_charter_then_catalog_entry_before_storage_or_api"
ACTIVE_FOUNDATION_NEXT_ACTION = "continue_existing_slice_hardening_without_broadening_scope"
CATALOG_PREPARED_NEXT_ACTION = "review_lms_catalog_readiness_before_catalog_registration"
MODULE_FAMILY_FOUNDATION_ARTIFACTS = {
    "knowledge_base": {
        "module_charter_ready": True,
        "feature_registry_ready": True,
        "object_rules_ready": True,
    },
    "lms": {
        "module_charter_ready": True,
        "feature_registry_ready": True,
        "object_rules_ready": True,
    },
}


class ModuleFamilyBacklogStatus(StrEnum):
    ACTIVE_FOUNDATION = "active_foundation"
    CATALOG_REGISTERED = "catalog_registered"
    PLANNED_NOT_INSTALLED = "planned_not_installed"


class ModuleFamilyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_family: str
    first_objects: tuple[str, ...]
    first_slice: str
    default_feature_gate: str
    continuity_domain: str

    @field_validator("module_family", "first_slice", "default_feature_gate", "continuity_domain")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module family contract text fields must not be empty")
        return value

    @field_validator("module_family")
    @classmethod
    def validate_module_family(cls, value: str) -> str:
        if not MODULE_FAMILY_PATTERN.fullmatch(value):
            raise ValueError("module_family must be lowercase snake_case")
        return value

    @field_validator("first_objects")
    @classmethod
    def validate_first_objects(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("first_objects must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("first_objects must not contain duplicates")
        for object_type in value:
            if "." not in object_type or not object_type.strip():
                raise ValueError("first_objects must use namespaced object types")
        return value


class ModuleImplementationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    contract_id: str
    required_metadata_fields: tuple[str, ...]
    required_controls: tuple[str, ...]
    slice_steps: tuple[str, ...]
    future_module_families: tuple[ModuleFamilyDefinition, ...]
    backlog_endpoint: str = MODULE_FAMILY_BACKLOG_ENDPOINT
    result_contract: str = MODULE_FAMILY_BACKLOG_RESULT_CONTRACT

    @field_validator(
        "schema_version",
        "contract_id",
        "backlog_endpoint",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module implementation contract text fields must not be empty")
        return value

    @field_validator("required_metadata_fields", "required_controls", "slice_steps")
    @classmethod
    def validate_contract_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("module implementation contract lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("module implementation contract lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("module implementation contract list items must not be empty")
        return value

    @model_validator(mode="after")
    def validate_contract_shape(self) -> ModuleImplementationContract:
        if self.schema_version != MODULE_IMPLEMENTATION_CONTRACT_SCHEMA_VERSION:
            raise ValueError("unsupported module implementation contract schema version")
        if self.backlog_endpoint != MODULE_FAMILY_BACKLOG_ENDPOINT:
            raise ValueError("module family backlog endpoint is not canonical")
        if self.result_contract != MODULE_FAMILY_BACKLOG_RESULT_CONTRACT:
            raise ValueError("module family backlog result contract is not canonical")
        families = [family.module_family for family in self.future_module_families]
        if len(set(families)) != len(families):
            raise ValueError("future module families must not contain duplicates")
        return self


class ModuleFamilyBacklogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_family: str
    module_id: str
    display_name: str
    first_objects: tuple[str, ...]
    first_slice: str
    default_feature_gate: str
    continuity_domain: str
    backlog_status: ModuleFamilyBacklogStatus
    catalog_status: str | None
    tenant_module_status: str | None
    installed_in_catalog: bool
    tenant_state_known: bool
    module_charter_ready: bool
    feature_registry_ready: bool
    object_rules_ready: bool
    pre_catalog_foundation_ready: bool
    first_slice_foundation_ready: bool
    runtime_activation_allowed: bool = False
    required_foundation_gates: tuple[str, ...]
    next_action: str

    @field_validator("module_family", "module_id", "display_name", "first_slice", "default_feature_gate")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module family backlog text fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_entry(self) -> ModuleFamilyBacklogEntry:
        if self.runtime_activation_allowed:
            raise ValueError("module family backlog entries must not allow runtime activation")
        if self.first_slice_foundation_ready and not self.installed_in_catalog:
            raise ValueError("first slice cannot be foundation-ready without catalog registration")
        if self.pre_catalog_foundation_ready and not (
            self.module_charter_ready and self.feature_registry_ready and self.object_rules_ready
        ):
            raise ValueError("pre-catalog foundation requires charter, feature registry, and object rules")
        return self


class ModuleFamilyBacklogSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_family_count: int
    catalog_registered_count: int
    planned_not_installed_count: int
    pre_catalog_foundation_ready_count: int
    first_slice_foundation_ready_count: int
    runtime_activation_allowed_count: int = 0


class ModuleFamilyBacklogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MODULE_FAMILY_BACKLOG_SCHEMA_VERSION
    tenant_id: str
    contract_schema_version: str
    contract_id: str
    result_contract: str = MODULE_FAMILY_BACKLOG_RESULT_CONTRACT
    endpoint: str = MODULE_FAMILY_BACKLOG_ENDPOINT
    required_metadata_fields: tuple[str, ...]
    required_controls: tuple[str, ...]
    slice_steps: tuple[str, ...]
    module_families: tuple[ModuleFamilyBacklogEntry, ...]
    summary: ModuleFamilyBacklogSummary
    evidence_refs: tuple[str, ...]
    content_included: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator("tenant_id", "contract_schema_version", "contract_id", "result_contract", "endpoint")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module family backlog response text fields must not be empty")
        return value

    @field_validator("required_metadata_fields", "required_controls", "slice_steps", "evidence_refs")
    @classmethod
    def validate_non_empty_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("module family backlog response lists must not be empty")
        for item in value:
            if not item.strip():
                raise ValueError("module family backlog response list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_response(self) -> ModuleFamilyBacklogResponse:
        if self.schema_version != MODULE_FAMILY_BACKLOG_SCHEMA_VERSION:
            raise ValueError("module family backlog schema version is invalid")
        if self.result_contract != MODULE_FAMILY_BACKLOG_RESULT_CONTRACT:
            raise ValueError("module family backlog result contract is invalid")
        if self.endpoint != MODULE_FAMILY_BACKLOG_ENDPOINT:
            raise ValueError("module family backlog endpoint is invalid")
        if (
            self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("module family backlog must remain metadata-only and non-executing")
        if self.summary.total_family_count != len(self.module_families):
            raise ValueError("module family backlog summary count must match family count")
        if self.summary.runtime_activation_allowed_count != 0:
            raise ValueError("module family backlog must not allow runtime activation")
        return self


def default_module_implementation_contract_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "modules" / "module_implementation_contract.json"


def load_module_implementation_contract(path: Path | None = None) -> ModuleImplementationContract:
    contract_path = path or default_module_implementation_contract_path()
    return ModuleImplementationContract.model_validate(json.loads(contract_path.read_text(encoding="utf-8")))


def build_module_family_backlog_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    contract: ModuleImplementationContract | None = None,
) -> ModuleFamilyBacklogResponse:
    effective_contract = contract or load_module_implementation_contract()
    module_families = tuple(
        _module_family_backlog_entry(
            tenant_id=user_context.tenant_id,
            module_registry=module_registry,
            definition=definition,
        )
        for definition in effective_contract.future_module_families
    )
    return ModuleFamilyBacklogResponse(
        tenant_id=user_context.tenant_id,
        contract_schema_version=effective_contract.schema_version,
        contract_id=effective_contract.contract_id,
        required_metadata_fields=effective_contract.required_metadata_fields,
        required_controls=effective_contract.required_controls,
        slice_steps=effective_contract.slice_steps,
        module_families=module_families,
        summary=_module_family_backlog_summary(module_families),
        evidence_refs=(
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "docs/modules/module_implementation_contract.json",
            "docs/modules/LMS_MODULE_CHARTER.md",
            "app/suite/platform/lms_module.py",
            "app/suite/platform/lms_catalog_readiness.py",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_module_family_backlog.py",
            "tests/test_lms_module_foundation.py",
            "tests/test_lms_catalog_readiness.py",
        ),
    )


def _module_family_backlog_entry(
    *,
    tenant_id: str,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    definition: ModuleFamilyDefinition,
) -> ModuleFamilyBacklogEntry:
    module_id = MODULE_FAMILY_MODULE_IDS.get(definition.module_family, definition.module_family)
    catalog_status = _catalog_status(module_registry=module_registry, module_id=module_id)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=tenant_id,
        module_id=module_id,
        catalog_known=catalog_status is not None,
    )
    artifact_readiness = MODULE_FAMILY_FOUNDATION_ARTIFACTS.get(definition.module_family, {})
    installed_in_catalog = catalog_status is not None
    first_slice_foundation_ready = definition.module_family == "knowledge_base" and installed_in_catalog
    pre_catalog_foundation_ready = (
        not installed_in_catalog
        and bool(artifact_readiness.get("module_charter_ready", False))
        and bool(artifact_readiness.get("feature_registry_ready", False))
        and bool(artifact_readiness.get("object_rules_ready", False))
    )
    return ModuleFamilyBacklogEntry(
        module_family=definition.module_family,
        module_id=module_id,
        display_name=MODULE_FAMILY_DISPLAY_NAMES.get(definition.module_family, definition.module_family),
        first_objects=definition.first_objects,
        first_slice=definition.first_slice,
        default_feature_gate=definition.default_feature_gate,
        continuity_domain=definition.continuity_domain,
        backlog_status=_backlog_status(
            installed_in_catalog=installed_in_catalog,
            first_slice_foundation_ready=first_slice_foundation_ready,
        ),
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        installed_in_catalog=installed_in_catalog,
        tenant_state_known=tenant_module_status is not None,
        module_charter_ready=bool(artifact_readiness.get("module_charter_ready", False)),
        feature_registry_ready=bool(artifact_readiness.get("feature_registry_ready", False)),
        object_rules_ready=bool(artifact_readiness.get("object_rules_ready", False)),
        pre_catalog_foundation_ready=pre_catalog_foundation_ready,
        first_slice_foundation_ready=first_slice_foundation_ready,
        required_foundation_gates=_required_foundation_gates(definition),
        next_action=_next_action(
            first_slice_foundation_ready=first_slice_foundation_ready,
            pre_catalog_foundation_ready=pre_catalog_foundation_ready,
        ),
    )


def _catalog_status(
    *,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    module_id: str,
) -> str | None:
    try:
        return module_registry.get_catalog_entry(module_id).status.value
    except LookupError:
        return None


def _tenant_module_status(
    *,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    tenant_id: str,
    module_id: str,
    catalog_known: bool,
) -> str | None:
    if not catalog_known:
        return None
    state = module_registry.get_tenant_module_or_none(tenant_id=tenant_id, module_id=module_id)
    return state.status.value if state is not None else None


def _backlog_status(
    *,
    installed_in_catalog: bool,
    first_slice_foundation_ready: bool,
) -> ModuleFamilyBacklogStatus:
    if first_slice_foundation_ready:
        return ModuleFamilyBacklogStatus.ACTIVE_FOUNDATION
    if installed_in_catalog:
        return ModuleFamilyBacklogStatus.CATALOG_REGISTERED
    return ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED


def _required_foundation_gates(definition: ModuleFamilyDefinition) -> tuple[str, ...]:
    return (
        "module_charter_required",
        "feature_registry_required",
        f"default_feature_gate:{definition.default_feature_gate}",
        "module_catalog_entry_required",
        "tenant_module_lifecycle_required",
        f"continuity_domain:{definition.continuity_domain}",
        "backup_restore_evidence_required",
        "object_authorization_required",
        "metadata_only_audit_required",
    )


def _next_action(
    *,
    first_slice_foundation_ready: bool,
    pre_catalog_foundation_ready: bool,
) -> str:
    if first_slice_foundation_ready:
        return ACTIVE_FOUNDATION_NEXT_ACTION
    if pre_catalog_foundation_ready:
        return CATALOG_PREPARED_NEXT_ACTION
    return PLANNED_MODULE_NEXT_ACTION


def _module_family_backlog_summary(
    module_families: tuple[ModuleFamilyBacklogEntry, ...],
) -> ModuleFamilyBacklogSummary:
    return ModuleFamilyBacklogSummary(
        total_family_count=len(module_families),
        catalog_registered_count=sum(1 for family in module_families if family.installed_in_catalog),
        planned_not_installed_count=sum(
            1 for family in module_families if family.backlog_status == ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED
        ),
        pre_catalog_foundation_ready_count=sum(1 for family in module_families if family.pre_catalog_foundation_ready),
        first_slice_foundation_ready_count=sum(1 for family in module_families if family.first_slice_foundation_ready),
    )
