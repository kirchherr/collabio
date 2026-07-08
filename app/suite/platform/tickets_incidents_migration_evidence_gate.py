from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.tickets_incidents_catalog_readiness import TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT
from suite.platform.tickets_incidents_module import (
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
    TICKETS_INCIDENTS_SCHEMA_NAME,
    build_default_tickets_incidents_object_rule_manifest,
    build_default_tickets_incidents_subfeature_registry,
)

TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_SCHEMA_VERSION = "tickets_incidents_migration_evidence_gate.v1"
TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_migration_evidence_gate_no_storage"
)
TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/migration-evidence-gate"
)
TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION = "0051"
TICKETS_INCIDENTS_STORAGE_MIGRATION_DRAFT_NEXT_ACTION = (
    "draft_tickets_incidents_metadata_schema_migration_evidence_without_execution"
)
TICKETS_INCIDENTS_GATE_REPAIR_NEXT_ACTION = "repair_tickets_incidents_catalog_or_manifest_before_storage_evidence"
TICKETS_INCIDENTS_RESTORE_REVIEW_NEXT_ACTION = "review_tickets_incidents_restore_drill_before_storage_execution"


class TicketsIncidentsMigrationEvidenceGateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickets_manifest_migration_count: int
    tickets_storage_migration_count: int
    planned_object_type_count: int
    required_storage_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsMigrationEvidenceGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    catalog_readiness_endpoint: str = TICKETS_INCIDENTS_CATALOG_READINESS_ENDPOINT
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    module_package_installed: bool
    tenant_module_state_present: bool
    catalog_registration_migration_present: bool
    migration_evidence_gate_ready: bool
    storage_migration_evidence_ready: bool
    storage_migration_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    tickets_business_api_allowed: bool = False
    business_tables_created: bool = False
    content_included: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    planned_schema_name: str = TICKETS_INCIDENTS_SCHEMA_NAME
    planned_object_types: tuple[str, ...]
    existing_tickets_migration_versions: tuple[str, ...]
    existing_tickets_storage_migration_versions: tuple[str, ...]
    feature_manifest_hash: str
    object_rule_manifest_hash: str
    required_storage_migration_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: TicketsIncidentsMigrationEvidenceGateSummary
    evidence_refs: tuple[str, ...]
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "catalog_readiness_endpoint",
        "planned_schema_name",
        "feature_manifest_hash",
        "object_rule_manifest_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents migration evidence gate text fields must not be empty")
        return value

    @field_validator(
        "planned_object_types",
        "existing_tickets_migration_versions",
        "existing_tickets_storage_migration_versions",
        "required_storage_migration_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def validate_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents migration evidence gate lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents migration evidence gate list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_gate(self) -> TicketsIncidentsMigrationEvidenceGateResponse:
        if self.schema_version != TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents migration evidence gate schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT:
            raise ValueError("Tickets & Incidents migration evidence gate endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents migration evidence gate result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents migration evidence gate only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents migration evidence gate continuity domain is invalid")
        if self.planned_schema_name != TICKETS_INCIDENTS_SCHEMA_NAME:
            raise ValueError("Tickets & Incidents migration evidence gate schema name is invalid")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("Tickets & Incidents package flag must match catalog status")
        if self.catalog_registration_migration_present != (
            TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION in self.existing_tickets_migration_versions
        ):
            raise ValueError("Tickets & Incidents catalog migration flag must match manifest versions")
        if self.storage_migration_evidence_ready != bool(self.existing_tickets_storage_migration_versions):
            raise ValueError("Tickets & Incidents storage evidence readiness must match storage migration versions")
        expected_gate_ready = (
            self.catalog_status == "not_installed"
            and self.catalog_registration_migration_present
            and not self.tenant_module_state_present
            and not self.module_package_installed
            and not self.blocking_reasons
        )
        if self.migration_evidence_gate_ready != expected_gate_ready:
            raise ValueError("Tickets & Incidents migration evidence gate readiness must match guard conditions")
        if (
            self.storage_migration_execution_allowed
            or self.tenant_provisioning_allowed
            or self.tickets_business_api_allowed
            or self.business_tables_created
            or self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets & Incidents migration evidence gate must remain metadata-only")
        if self.summary.tickets_manifest_migration_count != len(self.existing_tickets_migration_versions):
            raise ValueError("Tickets & Incidents migration count must match manifest versions")
        if self.summary.tickets_storage_migration_count != len(self.existing_tickets_storage_migration_versions):
            raise ValueError("Tickets & Incidents storage migration count must match storage versions")
        if self.summary.planned_object_type_count != len(self.planned_object_types):
            raise ValueError("Tickets & Incidents planned object count must match object types")
        if self.summary.required_storage_evidence_count != len(self.required_storage_migration_evidence):
            raise ValueError("Tickets & Incidents required evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets & Incidents blocking reason count must match blocking reasons")
        return self


def build_tickets_incidents_migration_evidence_gate_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> TicketsIncidentsMigrationEvidenceGateResponse:
    feature_registry = build_default_tickets_incidents_subfeature_registry()
    object_rule_manifest = build_default_tickets_incidents_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)

    catalog_status = _catalog_status(module_registry=module_registry)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=user_context.tenant_id,
        catalog_known=catalog_status is not None,
    )
    migration_versions = _tickets_incidents_migration_versions(migration_manifest_entries)
    storage_migration_versions = tuple(
        version for version in migration_versions if version != TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION
    )
    planned_object_types = tuple(rule.object_type for rule in object_rule_manifest.object_rules)
    required_storage_evidence = (
        "ticket_metadata_schema_design_review",
        "ticket_event_metadata_schema_design_review",
        "tenant_rls_policy_plan",
        "kms_retention_legal_hold_columns_plan",
        "backup_restore_ticket_incident_records_update",
        "migration_forward_only_or_rollback_decision",
        "no_tenant_state_creation_confirmed",
        "no_business_api_or_worker_activation_confirmed",
    )
    catalog_registration_migration_present = (
        TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION in migration_versions
    )
    blocking_reasons = _blocking_reasons(
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        catalog_registration_migration_present=catalog_registration_migration_present,
    )
    return TicketsIncidentsMigrationEvidenceGateResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        catalog_registration_migration_present=catalog_registration_migration_present,
        migration_evidence_gate_ready=not blocking_reasons,
        storage_migration_evidence_ready=bool(storage_migration_versions),
        planned_object_types=planned_object_types,
        existing_tickets_migration_versions=migration_versions,
        existing_tickets_storage_migration_versions=storage_migration_versions,
        feature_manifest_hash=feature_registry.manifest_hash,
        object_rule_manifest_hash=object_rule_manifest.manifest_hash,
        required_storage_migration_evidence=required_storage_evidence,
        blocking_reasons=blocking_reasons,
        summary=TicketsIncidentsMigrationEvidenceGateSummary(
            tickets_manifest_migration_count=len(migration_versions),
            tickets_storage_migration_count=len(storage_migration_versions),
            planned_object_type_count=len(planned_object_types),
            required_storage_evidence_count=len(required_storage_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_catalog_readiness.py",
            "app/suite/platform/tickets_incidents_migration_evidence_gate.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_tickets_incidents_migration_evidence_gate.py",
        ),
        next_action=_next_action(
            gate_ready=not blocking_reasons,
            storage_migration_evidence_ready=bool(storage_migration_versions),
        ),
    )


def _catalog_status(*, module_registry: InMemoryModuleRegistry | PgModuleRegistry) -> str | None:
    try:
        return module_registry.get_catalog_entry(TICKETS_INCIDENTS_MODULE_ID).status.value
    except LookupError:
        return None


def _tenant_module_status(
    *,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    tenant_id: str,
    catalog_known: bool,
) -> str | None:
    if not catalog_known:
        return None
    state = module_registry.get_tenant_module_or_none(tenant_id=tenant_id, module_id=TICKETS_INCIDENTS_MODULE_ID)
    return state.status.value if state is not None else None


def _tickets_incidents_migration_versions(
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> tuple[str, ...]:
    return tuple(
        sorted(entry.version for entry in migration_manifest_entries if entry.module_id == TICKETS_INCIDENTS_MODULE_ID)
    )


def _blocking_reasons(
    *,
    catalog_status: str | None,
    tenant_module_status: str | None,
    catalog_registration_migration_present: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalog_status is None:
        reasons.append("tickets_incidents_catalog_entry_missing")
    elif catalog_status != "not_installed":
        reasons.append("tickets_incidents_catalog_status_not_storage_gate_eligible")
    if tenant_module_status is not None:
        reasons.append("tenant_module_state_already_exists")
    if not catalog_registration_migration_present:
        reasons.append("tickets_incidents_catalog_registration_migration_missing")
    return tuple(reasons)


def _next_action(*, gate_ready: bool, storage_migration_evidence_ready: bool) -> str:
    if not gate_ready:
        return TICKETS_INCIDENTS_GATE_REPAIR_NEXT_ACTION
    if not storage_migration_evidence_ready:
        return TICKETS_INCIDENTS_STORAGE_MIGRATION_DRAFT_NEXT_ACTION
    return TICKETS_INCIDENTS_RESTORE_REVIEW_NEXT_ACTION
