from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.tickets_incidents_migration_evidence_gate import (
    TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT,
    build_tickets_incidents_migration_evidence_gate_response,
)
from suite.platform.tickets_incidents_module import (
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
    TICKETS_INCIDENTS_OBJECT_TYPES,
    TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS,
    TICKETS_INCIDENTS_SCHEMA_NAME,
    build_default_tickets_incidents_object_rule_manifest,
    build_default_tickets_incidents_subfeature_registry,
)

TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_SCHEMA_VERSION = "tickets_incidents_storage_migration_evidence.v1"
TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_storage_migration_evidence_no_execution"
)
TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/storage-migration-evidence"
)
TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_NAME = "tickets_incidents_metadata_schema"
TICKETS_INCIDENTS_STORAGE_EVIDENCE_REPAIR_NEXT_ACTION = (
    "repair_tickets_incidents_migration_evidence_gate_before_storage_draft"
)
TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION = (
    "write_tickets_incidents_metadata_schema_migration_after_evidence_review_without_execution"
)


class TicketsIncidentsPlannedStorageTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_name: str
    object_type: str
    primary_key: str
    required_columns: tuple[str, ...]
    planned_rls_policies: tuple[str, ...]
    forbidden_payload_columns_absent: tuple[str, ...]

    @field_validator("table_name", "object_type", "primary_key")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents storage table text fields must not be empty")
        return value

    @field_validator("required_columns", "planned_rls_policies", "forbidden_payload_columns_absent")
    @classmethod
    def require_non_empty_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Tickets & Incidents storage table lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents storage table lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents storage table list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_no_payload_columns(self) -> TicketsIncidentsPlannedStorageTable:
        forbidden = set(self.forbidden_payload_columns_absent)
        if forbidden.intersection(self.required_columns):
            raise ValueError("Tickets & Incidents storage draft must not plan payload columns")
        if "tenant_id" not in self.required_columns:
            raise ValueError("Tickets & Incidents storage draft requires tenant_id")
        if self.primary_key not in self.required_columns:
            raise ValueError("Tickets & Incidents storage primary key must be part of required columns")
        return self


class TicketsIncidentsStorageMigrationEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned_table_count: int
    planned_object_type_count: int
    required_storage_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsStorageMigrationEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    migration_evidence_gate_endpoint: str = TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT
    catalog_status: str | None
    tenant_module_status: str | None
    migration_evidence_gate_ready: bool
    catalog_registration_migration_present: bool
    storage_migration_evidence_ready: bool
    table_design_review_ready: bool
    rls_policy_plan_ready: bool
    tenant_isolation_plan_ready: bool
    retention_legal_hold_plan_ready: bool
    kms_audit_reference_plan_ready: bool
    backup_failover_update_planned: bool
    no_content_payload_columns_planned: bool
    metadata_schema_migration_file_created: bool = False
    metadata_schema_migration_registered: bool = False
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
    planned_migration_name: str = TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_NAME
    planned_tables: tuple[TicketsIncidentsPlannedStorageTable, ...]
    planned_object_types: tuple[str, ...]
    required_storage_migration_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence_hash: str
    summary: TicketsIncidentsStorageMigrationEvidenceSummary
    evidence_refs: tuple[str, ...]
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "migration_evidence_gate_endpoint",
        "planned_schema_name",
        "planned_migration_name",
        "evidence_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents storage migration evidence text fields must not be empty")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def require_hash_reference(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("Tickets & Incidents storage migration evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "planned_object_types",
        "required_storage_migration_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def validate_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents storage migration evidence lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents storage migration evidence list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_storage_evidence(self) -> TicketsIncidentsStorageMigrationEvidenceResponse:
        if self.schema_version != TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents storage migration evidence schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_ENDPOINT:
            raise ValueError("Tickets & Incidents storage migration evidence endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_STORAGE_MIGRATION_EVIDENCE_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents storage migration evidence result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents storage migration evidence only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents storage migration evidence continuity domain is invalid")
        if self.migration_evidence_gate_endpoint != TICKETS_INCIDENTS_MIGRATION_EVIDENCE_GATE_ENDPOINT:
            raise ValueError("Tickets & Incidents storage migration evidence gate endpoint is invalid")
        if self.planned_schema_name != TICKETS_INCIDENTS_SCHEMA_NAME:
            raise ValueError("Tickets & Incidents storage migration evidence schema name is invalid")
        if self.planned_migration_name != TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_NAME:
            raise ValueError("Tickets & Incidents storage migration evidence migration name is invalid")
        planned_table_object_types = tuple(table.object_type for table in self.planned_tables)
        if planned_table_object_types != self.planned_object_types:
            raise ValueError("Tickets & Incidents storage migration evidence table object types must match")
        expected_ready = (
            self.migration_evidence_gate_ready
            and self.catalog_status == "not_installed"
            and self.catalog_registration_migration_present
            and self.table_design_review_ready
            and self.rls_policy_plan_ready
            and self.tenant_isolation_plan_ready
            and self.retention_legal_hold_plan_ready
            and self.kms_audit_reference_plan_ready
            and self.backup_failover_update_planned
            and self.no_content_payload_columns_planned
            and not self.blocking_reasons
        )
        if self.storage_migration_evidence_ready != expected_ready:
            raise ValueError("Tickets & Incidents storage migration evidence readiness must match evidence checks")
        if (
            self.metadata_schema_migration_file_created
            or self.metadata_schema_migration_registered
            or self.storage_migration_execution_allowed
            or self.tenant_provisioning_allowed
            or self.tickets_business_api_allowed
            or self.business_tables_created
            or self.content_included
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets & Incidents storage migration evidence must remain metadata-only")
        if self.summary.planned_table_count != len(self.planned_tables):
            raise ValueError("Tickets & Incidents storage table count must match planned tables")
        if self.summary.planned_object_type_count != len(self.planned_object_types):
            raise ValueError("Tickets & Incidents storage object count must match object types")
        if self.summary.required_storage_evidence_count != len(self.required_storage_migration_evidence):
            raise ValueError("Tickets & Incidents storage evidence count must match required evidence")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets & Incidents storage blocking count must match blocking reasons")
        return self


def build_tickets_incidents_storage_migration_evidence_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> TicketsIncidentsStorageMigrationEvidenceResponse:
    feature_registry = build_default_tickets_incidents_subfeature_registry()
    object_rule_manifest = build_default_tickets_incidents_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)

    gate = build_tickets_incidents_migration_evidence_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    planned_tables = _planned_tables()
    planned_object_types = tuple(table.object_type for table in planned_tables)
    table_design_review_ready = planned_object_types == TICKETS_INCIDENTS_OBJECT_TYPES
    rls_policy_plan_ready = all(table.planned_rls_policies for table in planned_tables)
    tenant_isolation_plan_ready = all("tenant_id" in table.required_columns for table in planned_tables)
    retention_legal_hold_plan_ready = all(
        {"retention_policy_id", "legal_hold_state"}.issubset(table.required_columns) for table in planned_tables
    )
    kms_audit_reference_plan_ready = all(
        {"kms_key_ref", "audit_chain_ref"}.issubset(table.required_columns) for table in planned_tables
    )
    no_content_payload_columns_planned = all(
        set(table.required_columns).isdisjoint(table.forbidden_payload_columns_absent) for table in planned_tables
    )
    required_storage_evidence = (
        "ticket_metadata_schema_design_review",
        "ticket_event_metadata_schema_design_review",
        "tenant_rls_policy_plan",
        "tenant_isolation_policy_plan",
        "retention_legal_hold_columns_plan",
        "kms_audit_reference_columns_plan",
        "no_content_payload_columns_confirmed",
        "backup_restore_ticket_incident_records_update",
        "no_storage_migration_file_created_confirmed",
        "no_storage_migration_execution_confirmed",
        "no_tenant_state_creation_confirmed",
        "no_business_api_or_worker_activation_confirmed",
    )
    backup_failover_update_planned = "backup_restore_ticket_incident_records_update" in required_storage_evidence
    blocking_reasons = _blocking_reasons(
        gate_ready=gate.migration_evidence_gate_ready,
        table_design_review_ready=table_design_review_ready,
        rls_policy_plan_ready=rls_policy_plan_ready,
        tenant_isolation_plan_ready=tenant_isolation_plan_ready,
        retention_legal_hold_plan_ready=retention_legal_hold_plan_ready,
        kms_audit_reference_plan_ready=kms_audit_reference_plan_ready,
        backup_failover_update_planned=backup_failover_update_planned,
        no_content_payload_columns_planned=no_content_payload_columns_planned,
    )
    draft = TicketsIncidentsStorageMigrationEvidenceResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=gate.catalog_status,
        tenant_module_status=gate.tenant_module_status,
        migration_evidence_gate_ready=gate.migration_evidence_gate_ready,
        catalog_registration_migration_present=gate.catalog_registration_migration_present,
        storage_migration_evidence_ready=not blocking_reasons,
        table_design_review_ready=table_design_review_ready,
        rls_policy_plan_ready=rls_policy_plan_ready,
        tenant_isolation_plan_ready=tenant_isolation_plan_ready,
        retention_legal_hold_plan_ready=retention_legal_hold_plan_ready,
        kms_audit_reference_plan_ready=kms_audit_reference_plan_ready,
        backup_failover_update_planned=backup_failover_update_planned,
        no_content_payload_columns_planned=no_content_payload_columns_planned,
        planned_tables=planned_tables,
        planned_object_types=planned_object_types,
        required_storage_migration_evidence=required_storage_evidence,
        blocking_reasons=blocking_reasons,
        evidence_hash="sha256:pending",
        summary=TicketsIncidentsStorageMigrationEvidenceSummary(
            planned_table_count=len(planned_tables),
            planned_object_type_count=len(planned_object_types),
            required_storage_evidence_count=len(required_storage_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "docs/operations/BACKUP_FAILOVER.md",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_migration_evidence_gate.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "tests/test_tickets_incidents_storage_migration_evidence.py",
        ),
        next_action=_next_action(storage_migration_evidence_ready=not blocking_reasons),
    )
    return draft.model_copy(update={"evidence_hash": build_tickets_incidents_storage_migration_evidence_hash(draft)})


def build_tickets_incidents_storage_migration_evidence_hash(
    response: TicketsIncidentsStorageMigrationEvidenceResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _planned_tables() -> tuple[TicketsIncidentsPlannedStorageTable, ...]:
    common_columns = TICKETS_INCIDENTS_REQUIRED_OBJECT_METADATA_FIELDS
    forbidden_payload_columns = (
        "description",
        "body",
        "raw_body",
        "raw_message",
        "attachment_payload",
        "prompt",
        "ai_output",
        "transcript",
        "audio_blob",
    )
    return (
        TicketsIncidentsPlannedStorageTable(
            table_name="tickets.ticket_items",
            object_type="ticket.ticket",
            primary_key="ticket_id",
            required_columns=(
                *common_columns,
                "ticket_id",
                "ticket_number",
                "ticket_status",
                "priority",
                "subject_redacted",
                "sla_state",
            ),
            planned_rls_policies=(
                "tickets_ticket_items_tenant_select",
                "tickets_ticket_items_tenant_insert",
                "tickets_ticket_items_tenant_update",
                "tickets_ticket_items_no_hard_delete",
            ),
            forbidden_payload_columns_absent=forbidden_payload_columns,
        ),
        TicketsIncidentsPlannedStorageTable(
            table_name="tickets.ticket_events",
            object_type="ticket.event",
            primary_key="event_id",
            required_columns=(
                *common_columns,
                "event_id",
                "ticket_id",
                "event_type",
                "event_status",
                "event_summary_redacted",
                "occurred_at_utc",
            ),
            planned_rls_policies=(
                "tickets_ticket_events_tenant_select",
                "tickets_ticket_events_tenant_insert",
                "tickets_ticket_events_no_update",
                "tickets_ticket_events_no_hard_delete",
            ),
            forbidden_payload_columns_absent=forbidden_payload_columns,
        ),
    )


def _blocking_reasons(
    *,
    gate_ready: bool,
    table_design_review_ready: bool,
    rls_policy_plan_ready: bool,
    tenant_isolation_plan_ready: bool,
    retention_legal_hold_plan_ready: bool,
    kms_audit_reference_plan_ready: bool,
    backup_failover_update_planned: bool,
    no_content_payload_columns_planned: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not gate_ready:
        reasons.append("tickets_incidents_migration_evidence_gate_not_ready")
    if not table_design_review_ready:
        reasons.append("tickets_incidents_table_design_review_missing")
    if not rls_policy_plan_ready or not tenant_isolation_plan_ready:
        reasons.append("tickets_incidents_tenant_rls_plan_missing")
    if not retention_legal_hold_plan_ready:
        reasons.append("tickets_incidents_retention_legal_hold_plan_missing")
    if not kms_audit_reference_plan_ready:
        reasons.append("tickets_incidents_kms_audit_reference_plan_missing")
    if not backup_failover_update_planned:
        reasons.append("tickets_incidents_backup_failover_update_missing")
    if not no_content_payload_columns_planned:
        reasons.append("tickets_incidents_content_payload_column_boundary_failed")
    return tuple(reasons)


def _next_action(*, storage_migration_evidence_ready: bool) -> str:
    if not storage_migration_evidence_ready:
        return TICKETS_INCIDENTS_STORAGE_EVIDENCE_REPAIR_NEXT_ACTION
    return TICKETS_INCIDENTS_STORAGE_EVIDENCE_NEXT_ACTION
