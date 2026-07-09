from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

MODULE_FAMILY_BACKLOG_SCHEMA_VERSION = "platform_module_family_backlog.v1"
MODULE_FAMILY_BACKLOG_RESULT_CONTRACT = "metadata_only_future_module_backlog_no_activation"
MODULE_FAMILY_BACKLOG_ENDPOINT = "/v1/platform/modules/families/backlog"
MODULE_FAMILY_NEXT_SLICE_SELECTION_SCHEMA_VERSION = "platform_module_family_next_slice_selection.v1"
MODULE_FAMILY_NEXT_SLICE_SELECTION_RESULT_CONTRACT = "metadata_only_module_family_next_slice_selection_no_activation"
MODULE_FAMILY_NEXT_SLICE_SELECTION_ENDPOINT = "/v1/platform/modules/families/next-slice-selection"
MODULE_IMPLEMENTATION_CONTRACT_SCHEMA_VERSION = "module_implementation_contract.v1"
MODULE_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

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
CATALOG_REGISTERED_NEXT_ACTION = "resume_cross_module_backend_slices_without_lms_depth"
TASKS_ACTIVITIES_CATALOG_READY_NEXT_ACTION = (
    "register_tasks_activities_catalog_entry_as_not_installed_after_catalog_readiness_review"
)
TASKS_ACTIVITIES_MIGRATION_EVIDENCE_NEXT_ACTION = "add_tasks_activities_migration_evidence_before_storage_or_api"
TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION = (
    "prepare_tickets_incidents_activation_dry_run_executor_runtime_boundary_without_execution"
)
NEXT_SLICE_SELECTED_NEXT_ACTION = (
    "register_tickets_incidents_catalog_entry_as_not_installed_after_catalog_readiness_review"
)
CATALOG_READY_NEXT_ACTIONS = {
    "lms": CATALOG_PREPARED_NEXT_ACTION,
    "tasks_activities": TASKS_ACTIVITIES_CATALOG_READY_NEXT_ACTION,
    "tickets_incidents": NEXT_SLICE_SELECTED_NEXT_ACTION,
}
CATALOG_REGISTERED_NEXT_ACTIONS = {
    "lms": CATALOG_REGISTERED_NEXT_ACTION,
    "tasks_activities": TASKS_ACTIVITIES_MIGRATION_EVIDENCE_NEXT_ACTION,
    "tickets_incidents": TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION,
}
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
    "tasks_activities": {
        "module_charter_ready": True,
        "feature_registry_ready": True,
        "object_rules_ready": True,
    },
    "tickets_incidents": {
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
    catalog_entry_present: bool
    module_package_installed: bool
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
        if self.first_slice_foundation_ready and not self.module_package_installed:
            raise ValueError("first slice cannot be foundation-ready without an installed module package")
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


class ModuleFamilyNextSliceSelectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_family: str
    module_id: str
    display_name: str
    first_objects: tuple[str, ...]
    first_slice: str
    default_feature_gate: str
    continuity_domain: str
    backlog_status: ModuleFamilyBacklogStatus
    selection_rank: int
    selection_status: str
    selection_reason: str
    required_foundation_gates: tuple[str, ...]
    next_action: str
    catalog_entry_present: bool
    module_package_installed: bool
    runtime_activation_allowed: bool = False
    content_included: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator(
        "module_family",
        "module_id",
        "display_name",
        "first_slice",
        "default_feature_gate",
        "continuity_domain",
        "selection_status",
        "selection_reason",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module family next-slice candidate text fields must not be empty")
        return value

    @field_validator("first_objects", "required_foundation_gates")
    @classmethod
    def validate_non_empty_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("module family next-slice candidate lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("module family next-slice candidate lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("module family next-slice candidate list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_candidate(self) -> ModuleFamilyNextSliceSelectionCandidate:
        if self.selection_rank < 1:
            raise ValueError("module family next-slice candidate rank must be positive")
        if self.selection_status not in {"selected_next", "queued_next"}:
            raise ValueError("module family next-slice candidate status is invalid")
        if self.backlog_status != ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED:
            raise ValueError("module family next-slice candidates must be planned modules")
        if self.catalog_entry_present or self.module_package_installed:
            raise ValueError("module family next-slice candidates must not already be catalog-installed")
        if (
            self.runtime_activation_allowed
            or self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("module family next-slice candidates must remain metadata-only")
        return self


class ModuleFamilyNextSliceSelectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_family_count: int
    active_foundation_count: int
    catalog_registered_count: int
    planned_candidate_count: int
    selected_candidate_count: int
    queued_candidate_count: int
    lms_depth_deferred_count: int
    runtime_activation_allowed_count: int = 0
    blocking_reason_count: int


class ModuleFamilyNextSliceSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MODULE_FAMILY_NEXT_SLICE_SELECTION_SCHEMA_VERSION
    tenant_id: str
    contract_schema_version: str
    contract_id: str
    result_contract: str = MODULE_FAMILY_NEXT_SLICE_SELECTION_RESULT_CONTRACT
    endpoint: str = MODULE_FAMILY_NEXT_SLICE_SELECTION_ENDPOINT
    backlog_endpoint: str = MODULE_FAMILY_BACKLOG_ENDPOINT
    selection_ready: bool
    selected_module_family: str
    selected_module_id: str
    selected_next_action: str
    lms_depth_deferred: bool
    candidates: tuple[ModuleFamilyNextSliceSelectionCandidate, ...]
    deferred_module_families: tuple[str, ...]
    required_controls: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    content_included: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    summary: ModuleFamilyNextSliceSelectionSummary
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "contract_schema_version",
        "contract_id",
        "result_contract",
        "endpoint",
        "backlog_endpoint",
        "selected_module_family",
        "selected_module_id",
        "selected_next_action",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("module family next-slice response text fields must not be empty")
        return value

    @field_validator("deferred_module_families", "required_controls", "evidence_refs", "blocking_reasons")
    @classmethod
    def validate_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("module family next-slice response lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("module family next-slice response list items must not be empty")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("module family next-slice response evidence_hash must be a sha256 reference")
        return value

    @model_validator(mode="after")
    def require_metadata_only_selection(self) -> ModuleFamilyNextSliceSelectionResponse:
        if self.schema_version != MODULE_FAMILY_NEXT_SLICE_SELECTION_SCHEMA_VERSION:
            raise ValueError("module family next-slice schema version is invalid")
        if self.result_contract != MODULE_FAMILY_NEXT_SLICE_SELECTION_RESULT_CONTRACT:
            raise ValueError("module family next-slice result contract is invalid")
        if self.endpoint != MODULE_FAMILY_NEXT_SLICE_SELECTION_ENDPOINT:
            raise ValueError("module family next-slice endpoint is invalid")
        if self.backlog_endpoint != MODULE_FAMILY_BACKLOG_ENDPOINT:
            raise ValueError("module family next-slice backlog endpoint is invalid")
        selected = tuple(candidate for candidate in self.candidates if candidate.selection_status == "selected_next")
        if self.selection_ready != (len(selected) == 1 and not self.blocking_reasons):
            raise ValueError("module family next-slice readiness must match selected candidate")
        if self.selection_ready:
            if selected[0].module_family != self.selected_module_family:
                raise ValueError("module family next-slice selected family must match selected candidate")
            if selected[0].module_id != self.selected_module_id:
                raise ValueError("module family next-slice selected module must match selected candidate")
            if selected[0].next_action != self.selected_next_action:
                raise ValueError("module family next-slice selected action must match selected candidate")
        if (
            self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("module family next-slice selection must remain metadata-only and non-executing")
        if self.summary.total_family_count < len(self.candidates):
            raise ValueError("module family next-slice family count must cover candidates")
        if self.summary.planned_candidate_count != len(self.candidates):
            raise ValueError("module family next-slice candidate count must match candidates")
        if self.summary.selected_candidate_count != len(selected):
            raise ValueError("module family next-slice selected count must match candidates")
        if self.summary.queued_candidate_count != len(self.candidates) - len(selected):
            raise ValueError("module family next-slice queued count must match candidates")
        if self.summary.runtime_activation_allowed_count != 0:
            raise ValueError("module family next-slice must not allow runtime activation")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("module family next-slice blocking count must match reasons")
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
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "app/suite/platform/lms_module.py",
            "app/suite/platform/lms_catalog_readiness.py",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_catalog_readiness.py",
            "app/suite/platform/tickets_incidents_migration_evidence_gate.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
            "app/suite/platform/tickets_incidents_activation_execution_boundary.py",
            "app/suite/platform/tickets_incidents_activation_executor_skeleton.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_plan.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_boundary.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_skeleton.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_executor_implementation_review.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_result_contract.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_gate.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_request_boundary.py",
            "app/suite/platform/lms_restore_drill_evidence.py",
            "app/suite/platform/lms_tenant_admin_package_approval_gate.py",
            "app/suite/platform/lms_tenant_admin_package_approval_record.py",
            "app/suite/platform/lms_package_installation_execution_boundary.py",
            "app/suite/platform/lms_package_installation_executor_skeleton.py",
            "app/suite/platform/lms_package_installation_dry_run_plan.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_skeleton.py",
            "app/suite/platform/lms_package_installation_dry_run_executor_implementation_review.py",
            "app/suite/platform/lms_package_installation_dry_run_result_contract.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_gate.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_request_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_executor_runtime_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_preflight.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_receipt_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_result_persistence_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_activation_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_start_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_dispatch_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_worker_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_final_readiness_gate.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_approval_record.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_admission_gate.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_runbook.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_plan.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_plan_review.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_scheduler_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_worker_image_boundary.py",
            "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
            "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
            "app/suite/persistence/migrations/0048_lms_dry_run_execution_approval_records.sql",
            "app/suite/persistence/migrations/0049_lms_dry_run_execution_job_outbox.sql",
            "app/suite/persistence/migrations/0050_tasks_activities_catalog_registration.sql",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_module_family_backlog.py",
            "tests/test_lms_module_foundation.py",
            "tests/test_tickets_incidents_module_foundation.py",
            "tests/test_tickets_incidents_catalog_readiness.py",
            "tests/test_tickets_incidents_migration_evidence_gate.py",
            "tests/test_tickets_incidents_storage_migration_evidence.py",
            "tests/test_tickets_incidents_restore_drill_evidence.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_gate.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_record.py",
            "tests/test_tickets_incidents_activation_execution_boundary.py",
            "tests/test_tickets_incidents_activation_executor_skeleton.py",
            "tests/test_tickets_incidents_activation_dry_run_plan.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_boundary.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_skeleton.py",
            "tests/test_tickets_incidents_activation_dry_run_executor_implementation_review.py",
            "tests/test_tickets_incidents_activation_dry_run_result_contract.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_gate.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_request_boundary.py",
            "tests/test_lms_catalog_readiness.py",
            "tests/test_lms_restore_drill_evidence.py",
            "tests/test_lms_tenant_admin_package_approval_gate.py",
            "tests/test_lms_tenant_admin_package_approval_record.py",
            "tests/test_lms_package_installation_execution_boundary.py",
            "tests/test_lms_package_installation_executor_skeleton.py",
            "tests/test_lms_package_installation_dry_run_plan.py",
            "tests/test_lms_package_installation_dry_run_execution_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_skeleton.py",
            "tests/test_lms_package_installation_dry_run_executor_implementation_review.py",
            "tests/test_lms_package_installation_dry_run_result_contract.py",
            "tests/test_lms_package_installation_dry_run_execution_gate.py",
            "tests/test_lms_package_installation_dry_run_execution_request_boundary.py",
            "tests/test_lms_package_installation_dry_run_executor_runtime_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_preflight.py",
            "tests/test_lms_package_installation_dry_run_execution_receipt_boundary.py",
            "tests/test_lms_package_installation_dry_run_result_persistence_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_activation_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_start_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_dispatch_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_worker_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_final_readiness_gate.py",
            "tests/test_lms_package_installation_dry_run_execution_approval_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_approval_record.py",
            "tests/test_lms_package_installation_dry_run_execution_admission_gate.py",
            "tests/test_lms_package_installation_dry_run_execution_runbook.py",
            "tests/test_lms_package_installation_dry_run_execution_plan.py",
            "tests/test_lms_package_installation_dry_run_execution_plan_review.py",
            "tests/test_lms_package_installation_dry_run_execution_scheduler_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_worker_image_boundary.py",
            "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
        ),
    )


def build_module_family_next_slice_selection_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    contract: ModuleImplementationContract | None = None,
) -> ModuleFamilyNextSliceSelectionResponse:
    backlog = build_module_family_backlog_response(
        user_context=user_context,
        module_registry=module_registry,
        contract=contract,
    )
    planned_families = tuple(
        family
        for family in backlog.module_families
        if family.backlog_status == ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED
    )
    candidates = tuple(
        _module_family_next_slice_candidate(family=family, selection_rank=index + 1)
        for index, family in enumerate(planned_families)
    )
    selected = candidates[0] if candidates else None
    lms_depth_deferred = any(
        family.module_family == "lms"
        and family.backlog_status == ModuleFamilyBacklogStatus.CATALOG_REGISTERED
        and family.next_action == CATALOG_REGISTERED_NEXT_ACTION
        for family in backlog.module_families
    )
    blocking_reasons: list[str] = []
    if selected is None:
        blocking_reasons.append("module_family_next_slice_selection_requires_planned_candidate")
    if not lms_depth_deferred:
        blocking_reasons.append("module_family_next_slice_selection_requires_lms_depth_deferred")
    selection_ready = selected is not None and lms_depth_deferred and not blocking_reasons
    deferred_module_families = tuple(
        family.module_family
        for family in backlog.module_families
        if family.backlog_status != ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED
    )
    draft = ModuleFamilyNextSliceSelectionResponse(
        tenant_id=user_context.tenant_id,
        contract_schema_version=backlog.contract_schema_version,
        contract_id=backlog.contract_id,
        selection_ready=selection_ready,
        selected_module_family=selected.module_family if selected is not None else "none",
        selected_module_id=selected.module_id if selected is not None else "none",
        selected_next_action=selected.next_action if selected is not None else "wait_for_planned_module_candidate",
        lms_depth_deferred=lms_depth_deferred,
        candidates=candidates,
        deferred_module_families=deferred_module_families,
        required_controls=backlog.required_controls,
        evidence_refs=(
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "docs/modules/module_implementation_contract.json",
            "docs/modules/TASKS_ACTIVITIES_MODULE_CHARTER.md",
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "app/suite/platform/module_family_backlog.py",
            "app/suite/platform/tasks_activities_module.py",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_catalog_readiness.py",
            "app/suite/platform/tickets_incidents_migration_evidence_gate.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
            "app/suite/platform/tickets_incidents_activation_execution_boundary.py",
            "app/suite/platform/tickets_incidents_activation_executor_skeleton.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_plan.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_boundary.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_skeleton.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_executor_implementation_review.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_result_contract.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_gate.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_request_boundary.py",
            "app/suite/persistence/migrations/0050_tasks_activities_catalog_registration.sql",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "tests/test_module_family_backlog.py",
            "tests/test_tasks_activities_module_foundation.py",
            "tests/test_tickets_incidents_module_foundation.py",
            "tests/test_tickets_incidents_catalog_readiness.py",
            "tests/test_tickets_incidents_migration_evidence_gate.py",
            "tests/test_tickets_incidents_storage_migration_evidence.py",
            "tests/test_tickets_incidents_restore_drill_evidence.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_gate.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_record.py",
            "tests/test_tickets_incidents_activation_execution_boundary.py",
            "tests/test_tickets_incidents_activation_executor_skeleton.py",
            "tests/test_tickets_incidents_activation_dry_run_plan.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_boundary.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_skeleton.py",
            "tests/test_tickets_incidents_activation_dry_run_executor_implementation_review.py",
            "tests/test_tickets_incidents_activation_dry_run_result_contract.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_gate.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_request_boundary.py",
            "tests/test_api.py",
        ),
        blocking_reasons=tuple(blocking_reasons),
        summary=ModuleFamilyNextSliceSelectionSummary(
            total_family_count=backlog.summary.total_family_count,
            active_foundation_count=backlog.summary.first_slice_foundation_ready_count,
            catalog_registered_count=backlog.summary.catalog_registered_count,
            planned_candidate_count=len(candidates),
            selected_candidate_count=int(selected is not None),
            queued_candidate_count=max(0, len(candidates) - int(selected is not None)),
            lms_depth_deferred_count=int(lms_depth_deferred),
            runtime_activation_allowed_count=backlog.summary.runtime_activation_allowed_count,
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_hash=ZERO_SHA256,
        next_action=selected.next_action
        if selection_ready and selected is not None
        else "repair_module_family_next_slice_selection",
    )
    return draft.model_copy(update={"evidence_hash": build_module_family_next_slice_selection_hash(draft)})


def build_module_family_next_slice_selection_hash(response: ModuleFamilyNextSliceSelectionResponse) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _module_family_next_slice_candidate(
    *,
    family: ModuleFamilyBacklogEntry,
    selection_rank: int,
) -> ModuleFamilyNextSliceSelectionCandidate:
    selected = selection_rank == 1
    return ModuleFamilyNextSliceSelectionCandidate(
        module_family=family.module_family,
        module_id=family.module_id,
        display_name=family.display_name,
        first_objects=family.first_objects,
        first_slice=family.first_slice,
        default_feature_gate=family.default_feature_gate,
        continuity_domain=family.continuity_domain,
        backlog_status=family.backlog_status,
        selection_rank=selection_rank,
        selection_status="selected_next" if selected else "queued_next",
        selection_reason=(
            "first_planned_module_family_after_lms_foundation_seal"
            if selected
            else "queued_after_selected_module_family_contract"
        ),
        required_foundation_gates=family.required_foundation_gates,
        next_action=family.next_action,
        catalog_entry_present=family.catalog_entry_present,
        module_package_installed=family.module_package_installed,
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
    catalog_entry_present = catalog_status is not None
    module_package_installed = catalog_status in {"available", "installed"}
    first_slice_foundation_ready = definition.module_family == "knowledge_base" and module_package_installed
    pre_catalog_foundation_ready = (
        not catalog_entry_present
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
            catalog_entry_present=catalog_entry_present,
            first_slice_foundation_ready=first_slice_foundation_ready,
        ),
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        catalog_entry_present=catalog_entry_present,
        module_package_installed=module_package_installed,
        installed_in_catalog=module_package_installed,
        tenant_state_known=tenant_module_status is not None,
        module_charter_ready=bool(artifact_readiness.get("module_charter_ready", False)),
        feature_registry_ready=bool(artifact_readiness.get("feature_registry_ready", False)),
        object_rules_ready=bool(artifact_readiness.get("object_rules_ready", False)),
        pre_catalog_foundation_ready=pre_catalog_foundation_ready,
        first_slice_foundation_ready=first_slice_foundation_ready,
        required_foundation_gates=_required_foundation_gates(definition),
        next_action=_next_action(
            module_family=definition.module_family,
            first_slice_foundation_ready=first_slice_foundation_ready,
            pre_catalog_foundation_ready=pre_catalog_foundation_ready,
            catalog_entry_present=catalog_entry_present,
            module_package_installed=module_package_installed,
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
    catalog_entry_present: bool,
    first_slice_foundation_ready: bool,
) -> ModuleFamilyBacklogStatus:
    if first_slice_foundation_ready:
        return ModuleFamilyBacklogStatus.ACTIVE_FOUNDATION
    if catalog_entry_present:
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
    module_family: str,
    first_slice_foundation_ready: bool,
    pre_catalog_foundation_ready: bool,
    catalog_entry_present: bool,
    module_package_installed: bool,
) -> str:
    if first_slice_foundation_ready:
        return ACTIVE_FOUNDATION_NEXT_ACTION
    if catalog_entry_present and not module_package_installed:
        return CATALOG_REGISTERED_NEXT_ACTIONS.get(module_family, CATALOG_REGISTERED_NEXT_ACTION)
    if pre_catalog_foundation_ready:
        return CATALOG_READY_NEXT_ACTIONS.get(
            module_family,
            f"review_{module_family}_catalog_readiness_before_catalog_registration",
        )
    return f"create_{module_family}_module_charter_then_catalog_entry_before_storage_or_api"


def _module_family_backlog_summary(
    module_families: tuple[ModuleFamilyBacklogEntry, ...],
) -> ModuleFamilyBacklogSummary:
    return ModuleFamilyBacklogSummary(
        total_family_count=len(module_families),
        catalog_registered_count=sum(1 for family in module_families if family.catalog_entry_present),
        planned_not_installed_count=sum(
            1 for family in module_families if family.backlog_status == ModuleFamilyBacklogStatus.PLANNED_NOT_INSTALLED
        ),
        pre_catalog_foundation_ready_count=sum(1 for family in module_families if family.pre_catalog_foundation_ready),
        first_slice_foundation_ready_count=sum(1 for family in module_families if family.first_slice_foundation_ready),
    )
