from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry, get_migration
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.tickets_incidents_module import (
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
    TICKETS_INCIDENTS_OBJECT_TYPES,
    build_default_tickets_incidents_object_rule_manifest,
    build_default_tickets_incidents_subfeature_registry,
)
from suite.platform.tickets_incidents_storage_migration_evidence import (
    TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_VERSION,
    build_tickets_incidents_storage_migration_evidence_response,
)

TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION = "tickets_incidents_restore_drill_evidence.v1"
TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_restore_drill_evidence_no_activation"
)
TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/restore-drill-evidence"
)
TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION = "0051"
TICKETS_INCIDENTS_APPROVAL_RECORD_MIGRATION_VERSION = "0053"
TICKETS_INCIDENTS_CONTROLLED_PILOT_MIGRATION_VERSION = "0054"
TICKETS_INCIDENTS_TENANT_APPROVAL_RECORD_MIGRATION_VERSION = "0074"
TICKETS_INCIDENTS_RESTORE_DRILL_NEXT_ACTION = (
    "prepare_tickets_incidents_tenant_admin_activation_approval_gate_without_runtime_activation"
)


class TicketsIncidentsRestoreDrillEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickets_manifest_migration_count: int
    restored_table_count: int
    restored_object_type_count: int
    required_restore_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsRestoreDrillEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    module_package_installed: bool
    tenant_module_state_present: bool
    storage_migration_evidence_ready: bool
    migration_plan_ready: bool
    catalog_registration_migration_present: bool
    metadata_schema_migration_present: bool
    approval_record_migration_present: bool
    controlled_pilot_migration_present: bool
    tenant_approval_record_migration_present: bool
    approval_record_restore_verified: bool
    controlled_pilot_receipt_restore_verified: bool
    tenant_approval_record_restore_verified: bool
    table_restore_verified: bool
    rls_restore_verified: bool
    tenant_isolation_restore_verified: bool
    retention_restore_verified: bool
    legal_hold_restore_verified: bool
    kms_reference_restore_verified: bool
    audit_reference_restore_verified: bool
    sla_state_restore_verified: bool
    no_content_payload_restore_verified: bool
    restore_evidence_ready: bool
    tenant_provisioning_allowed: bool = False
    tickets_business_api_allowed: bool = False
    worker_activation_allowed: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    existing_tickets_migration_versions: tuple[str, ...]
    restored_tables: tuple[str, ...]
    restored_object_types: tuple[str, ...]
    required_restore_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence_hash: str
    summary: TicketsIncidentsRestoreDrillEvidenceSummary
    evidence_refs: tuple[str, ...]
    next_action: str = TICKETS_INCIDENTS_RESTORE_DRILL_NEXT_ACTION

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "evidence_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents restore drill evidence text fields must not be empty")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def require_hash_reference(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("Tickets & Incidents restore drill evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "existing_tickets_migration_versions",
        "restored_tables",
        "restored_object_types",
        "required_restore_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents restore drill evidence lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents restore drill evidence list items must not be empty")
        return value

    @field_validator("restored_tables", "restored_object_types", "required_restore_evidence", "evidence_refs")
    @classmethod
    def require_non_empty_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Tickets & Incidents restore drill evidence required lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_restore_contract(self) -> TicketsIncidentsRestoreDrillEvidenceResponse:
        if self.schema_version != TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents restore drill evidence schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_ENDPOINT:
            raise ValueError("Tickets & Incidents restore drill evidence endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents restore drill evidence result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents restore drill evidence only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents restore drill evidence continuity domain is invalid")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("Tickets & Incidents package flag must match catalog status")
        expected_ready = (
            self.catalog_status == "not_installed"
            and not self.tenant_module_state_present
            and self.storage_migration_evidence_ready
            and self.migration_plan_ready
            and self.catalog_registration_migration_present
            and self.metadata_schema_migration_present
            and self.approval_record_migration_present
            and self.controlled_pilot_migration_present
            and self.tenant_approval_record_migration_present
            and self.approval_record_restore_verified
            and self.controlled_pilot_receipt_restore_verified
            and self.tenant_approval_record_restore_verified
            and self.table_restore_verified
            and self.rls_restore_verified
            and self.tenant_isolation_restore_verified
            and self.retention_restore_verified
            and self.legal_hold_restore_verified
            and self.kms_reference_restore_verified
            and self.audit_reference_restore_verified
            and self.sla_state_restore_verified
            and self.no_content_payload_restore_verified
            and not self.blocking_reasons
        )
        if self.restore_evidence_ready != expected_ready:
            raise ValueError("Tickets & Incidents restore drill readiness must match restore checks")
        if (
            self.tenant_provisioning_allowed
            or self.tickets_business_api_allowed
            or self.worker_activation_allowed
            or self.module_activation_executed
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets & Incidents restore drill evidence must remain metadata-only and non-executing")
        if self.summary.tickets_manifest_migration_count != len(self.existing_tickets_migration_versions):
            raise ValueError("Tickets & Incidents migration count must match migration versions")
        if self.summary.restored_table_count != len(self.restored_tables):
            raise ValueError("Tickets & Incidents restore table count must match restored tables")
        if self.summary.restored_object_type_count != len(self.restored_object_types):
            raise ValueError("Tickets & Incidents restore object count must match object types")
        if self.summary.required_restore_evidence_count != len(self.required_restore_evidence):
            raise ValueError("Tickets & Incidents restore evidence count must match required evidence")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets & Incidents restore blocking count must match blocking reasons")
        return self


def build_tickets_incidents_restore_drill_evidence_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> TicketsIncidentsRestoreDrillEvidenceResponse:
    feature_registry = build_default_tickets_incidents_subfeature_registry()
    object_rule_manifest = build_default_tickets_incidents_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)
    migration_manifest = tuple(migration_manifest_entries)

    storage_evidence = build_tickets_incidents_storage_migration_evidence_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest,
    )
    catalog_status = _catalog_status(module_registry=module_registry)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=user_context.tenant_id,
        catalog_known=catalog_status is not None,
    )
    tickets_migration_versions = _tickets_incidents_migration_versions(migration_manifest)
    catalog_migration_present = TICKETS_INCIDENTS_CATALOG_REGISTRATION_MIGRATION_VERSION in tickets_migration_versions
    metadata_schema_migration_present = (
        TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_VERSION in tickets_migration_versions
    )
    approval_record_migration_present = (
        TICKETS_INCIDENTS_APPROVAL_RECORD_MIGRATION_VERSION in tickets_migration_versions
    )
    sql_checks = _metadata_schema_sql_checks()
    controlled_pilot_migration_present = (
        TICKETS_INCIDENTS_CONTROLLED_PILOT_MIGRATION_VERSION in tickets_migration_versions
    )
    tenant_approval_record_migration_present = (
        TICKETS_INCIDENTS_TENANT_APPROVAL_RECORD_MIGRATION_VERSION in tickets_migration_versions
    )
    approval_record_restore_verified = _approval_record_sql_restore_verified()
    controlled_pilot_receipt_restore_verified = _controlled_pilot_sql_restore_verified()
    tenant_approval_record_restore_verified = _tenant_approval_record_sql_restore_verified()
    migration_plan_ready = (
        catalog_migration_present
        and metadata_schema_migration_present
        and approval_record_migration_present
        and controlled_pilot_migration_present
        and tenant_approval_record_migration_present
        and storage_evidence.storage_migration_evidence_ready
        and approval_record_restore_verified
        and controlled_pilot_receipt_restore_verified
        and tenant_approval_record_restore_verified
    )
    blocking_reasons = _blocking_reasons(
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        migration_plan_ready=migration_plan_ready,
        storage_migration_evidence_ready=storage_evidence.storage_migration_evidence_ready,
        sql_checks=sql_checks,
        approval_record_restore_verified=approval_record_restore_verified,
        controlled_pilot_receipt_restore_verified=controlled_pilot_receipt_restore_verified,
        tenant_approval_record_restore_verified=tenant_approval_record_restore_verified,
    )
    restored_tables = (
        "tickets.ticket_items",
        "tickets.ticket_events",
        "tickets.activation_dry_run_execution_approval_records",
        "tickets.controlled_pilot_receipts",
        "tickets.tenant_admin_activation_approval_records",
    )
    restored_object_types = TICKETS_INCIDENTS_OBJECT_TYPES
    required_restore_evidence = (
        "tickets_incidents_catalog_registration_migration_0051",
        "tickets_incidents_metadata_schema_migration_0052",
        "tickets_incidents_approval_record_migration_0053",
        "tickets_incidents_controlled_pilot_migration_0054",
        "tickets_incidents_tenant_approval_record_migration_0074",
        "tickets_tenant_activation_approval_record_append_only_restore_check",
        "tickets_activation_approval_record_append_only_restore_check",
        "tickets_controlled_pilot_receipt_append_only_restore_check",
        "tickets_controlled_pilot_scoped_catalog_install_function_restore_check",
        "tickets_items_table_restore_check",
        "tickets_events_table_restore_check",
        "tickets_tenant_rls_restore_check",
        "tickets_retention_legal_hold_restore_check",
        "tickets_kms_audit_reference_restore_check",
        "tickets_sla_state_restore_check",
        "ticket_incident_records_backup_restore_policy_update",
        "no_tickets_content_payload_restore_confirmed",
        "no_tickets_tenant_activation_or_worker_confirmed",
    )
    draft = TicketsIncidentsRestoreDrillEvidenceResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        storage_migration_evidence_ready=storage_evidence.storage_migration_evidence_ready,
        migration_plan_ready=migration_plan_ready,
        catalog_registration_migration_present=catalog_migration_present,
        metadata_schema_migration_present=metadata_schema_migration_present,
        approval_record_migration_present=approval_record_migration_present,
        controlled_pilot_migration_present=controlled_pilot_migration_present,
        tenant_approval_record_migration_present=tenant_approval_record_migration_present,
        approval_record_restore_verified=approval_record_restore_verified,
        controlled_pilot_receipt_restore_verified=controlled_pilot_receipt_restore_verified,
        tenant_approval_record_restore_verified=tenant_approval_record_restore_verified,
        table_restore_verified=sql_checks.table_restore_verified,
        rls_restore_verified=sql_checks.rls_restore_verified,
        tenant_isolation_restore_verified=sql_checks.tenant_isolation_restore_verified,
        retention_restore_verified=sql_checks.retention_restore_verified,
        legal_hold_restore_verified=sql_checks.legal_hold_restore_verified,
        kms_reference_restore_verified=sql_checks.kms_reference_restore_verified,
        audit_reference_restore_verified=sql_checks.audit_reference_restore_verified,
        sla_state_restore_verified=sql_checks.sla_state_restore_verified,
        no_content_payload_restore_verified=sql_checks.no_content_payload_restore_verified,
        restore_evidence_ready=not blocking_reasons,
        existing_tickets_migration_versions=tickets_migration_versions,
        restored_tables=restored_tables,
        restored_object_types=restored_object_types,
        required_restore_evidence=required_restore_evidence,
        blocking_reasons=blocking_reasons,
        evidence_hash="sha256:pending",
        summary=TicketsIncidentsRestoreDrillEvidenceSummary(
            tickets_manifest_migration_count=len(tickets_migration_versions),
            restored_table_count=len(restored_tables),
            restored_object_type_count=len(restored_object_types),
            required_restore_evidence_count=len(required_restore_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "docs/operations/BACKUP_FAILOVER.md",
            "docs/operations/backup_failover_policy.json",
            "app/suite/platform/tickets_incidents_module.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "app/suite/persistence/migrations/0053_tickets_incidents_dry_run_execution_approval_records.sql",
            "app/suite/persistence/migrations/0054_tickets_incidents_controlled_pilot.sql",
            "app/suite/persistence/migrations/0074_tickets_incidents_tenant_activation_approval_records.sql",
            "tests/test_tickets_incidents_restore_drill_evidence.py",
            "tests/test_tickets_incidents_controlled_pilot.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_approval_record.py",
            "tests/test_pgvector_migration.py",
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_tickets_incidents_restore_drill_evidence_hash(draft)})


def build_tickets_incidents_restore_drill_evidence_hash(
    response: TicketsIncidentsRestoreDrillEvidenceResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


@dataclass(frozen=True)
class _MetadataSchemaSqlChecks:
    table_restore_verified: bool
    rls_restore_verified: bool
    tenant_isolation_restore_verified: bool
    retention_restore_verified: bool
    legal_hold_restore_verified: bool
    kms_reference_restore_verified: bool
    audit_reference_restore_verified: bool
    sla_state_restore_verified: bool
    no_content_payload_restore_verified: bool


def _metadata_schema_sql_checks() -> _MetadataSchemaSqlChecks:
    try:
        sql = " ".join(get_migration(TICKETS_INCIDENTS_METADATA_SCHEMA_MIGRATION_VERSION).sql().lower().split())
    except (FileNotFoundError, LookupError):
        return _MetadataSchemaSqlChecks(
            table_restore_verified=False,
            rls_restore_verified=False,
            tenant_isolation_restore_verified=False,
            retention_restore_verified=False,
            legal_hold_restore_verified=False,
            kms_reference_restore_verified=False,
            audit_reference_restore_verified=False,
            sla_state_restore_verified=False,
            no_content_payload_restore_verified=False,
        )

    table_restore_verified = all(
        marker in sql
        for marker in (
            "create table if not exists tickets.ticket_items",
            "create table if not exists tickets.ticket_events",
            "primary key (tenant_id, ticket_id)",
            "primary key (tenant_id, event_id)",
            "foreign key (tenant_id, ticket_id)",
            "references tickets.ticket_items (tenant_id, ticket_id)",
        )
    )
    rls_restore_verified = all(
        marker in sql
        for marker in (
            "alter table tickets.ticket_items enable row level security",
            "alter table tickets.ticket_items force row level security",
            "alter table tickets.ticket_events enable row level security",
            "alter table tickets.ticket_events force row level security",
            "create policy tickets_ticket_items_tenant_select",
            "create policy tickets_ticket_items_tenant_insert",
            "create policy tickets_ticket_items_tenant_update",
            "create policy tickets_ticket_items_no_hard_delete",
            "create policy tickets_ticket_events_tenant_select",
            "create policy tickets_ticket_events_tenant_insert",
            "create policy tickets_ticket_events_no_update",
            "create policy tickets_ticket_events_no_hard_delete",
        )
    )
    tenant_isolation_restore_verified = "tenant_id = collabio.current_tenant_id()" in sql
    retention_restore_verified = "retention_policy_id text not null default 'rp-standard'" in sql
    legal_hold_restore_verified = "legal_hold_state text not null default 'none'" in sql
    kms_reference_restore_verified = "kms_key_ref text not null check" in sql
    audit_reference_restore_verified = "audit_chain_ref text not null check" in sql
    sla_state_restore_verified = all(
        marker in sql
        for marker in (
            "sla_state text not null default 'not_started'",
            "create index if not exists tickets_ticket_items_sla_idx",
        )
    )
    no_content_payload_restore_verified = not any(
        forbidden in sql
        for forbidden in (
            "raw_message text",
            "attachment_payload",
            "prompt",
            "ai_output",
            "transcript",
            "audio_blob",
            "description text",
            "body text",
            "comment text",
            "message_body",
        )
    )
    return _MetadataSchemaSqlChecks(
        table_restore_verified=table_restore_verified,
        rls_restore_verified=rls_restore_verified,
        tenant_isolation_restore_verified=tenant_isolation_restore_verified,
        retention_restore_verified=retention_restore_verified,
        legal_hold_restore_verified=legal_hold_restore_verified,
        kms_reference_restore_verified=kms_reference_restore_verified,
        audit_reference_restore_verified=audit_reference_restore_verified,
        sla_state_restore_verified=sla_state_restore_verified,
        no_content_payload_restore_verified=no_content_payload_restore_verified,
    )


def _approval_record_sql_restore_verified() -> bool:
    try:
        sql = " ".join(get_migration(TICKETS_INCIDENTS_APPROVAL_RECORD_MIGRATION_VERSION).sql().lower().split())
    except (FileNotFoundError, LookupError):
        return False

    required_markers = (
        "create table if not exists tickets.activation_dry_run_execution_approval_records",
        "alter table tickets.activation_dry_run_execution_approval_records enable row level security",
        "alter table tickets.activation_dry_run_execution_approval_records force row level security",
        "create policy tickets_activation_dry_run_approval_records_tenant_select",
        "create policy tickets_activation_dry_run_approval_records_tenant_insert",
        "create policy tickets_activation_dry_run_approval_records_no_update",
        "create policy tickets_activation_dry_run_approval_records_no_hard_delete",
        "tenant_id = collabio.current_tenant_id()",
        "using (false)",
        'required_migration_versions = \'["0051", "0052", "0053"]\'::jsonb',
    )
    forbidden_payloads = (
        "human_confirmation_statement text",
        "ticket_content text",
        "raw_payload text",
        "password text",
    )
    return all(marker in sql for marker in required_markers) and not any(
        payload in sql for payload in forbidden_payloads
    )


def _controlled_pilot_sql_restore_verified() -> bool:
    try:
        sql = " ".join(get_migration(TICKETS_INCIDENTS_CONTROLLED_PILOT_MIGRATION_VERSION).sql().lower().split())
    except (FileNotFoundError, LookupError):
        return False

    required_markers = (
        "create table if not exists tickets.controlled_pilot_receipts",
        "alter table tickets.controlled_pilot_receipts enable row level security",
        "alter table tickets.controlled_pilot_receipts force row level security",
        "create policy tickets_controlled_pilot_receipts_tenant_select",
        "create policy tickets_controlled_pilot_receipts_tenant_insert",
        "create policy tickets_controlled_pilot_receipts_no_update",
        "create policy tickets_controlled_pilot_receipts_no_hard_delete",
        "tenant_id = collabio.current_tenant_id()",
        "using (false)",
        "security definer",
        "persisted explicit tickets pilot approval not found",
        "revoke all on function collabio.install_tickets_incidents_catalog_for_pilot",
        'required_migration_versions = \'["0051", "0052", "0053", "0054"]\'::jsonb',
    )
    forbidden_payloads = (
        "human_confirmation_statement text",
        "ticket_content text",
        "raw_payload text",
        "password text",
        "grant update on table collabio.module_catalog",
    )
    return all(marker in sql for marker in required_markers) and not any(
        payload in sql for payload in forbidden_payloads
    )


def _tenant_approval_record_sql_restore_verified() -> bool:
    try:
        sql = " ".join(get_migration(TICKETS_INCIDENTS_TENANT_APPROVAL_RECORD_MIGRATION_VERSION).sql().lower().split())
    except (FileNotFoundError, LookupError):
        return False

    required_markers = (
        "create table if not exists tickets.tenant_admin_activation_approval_records",
        "alter table tickets.tenant_admin_activation_approval_records enable row level security",
        "alter table tickets.tenant_admin_activation_approval_records force row level security",
        "create policy tickets_tenant_activation_approval_records_tenant_select",
        "create policy tickets_tenant_activation_approval_records_tenant_insert",
        "create policy tickets_tenant_activation_approval_records_no_update",
        "create policy tickets_tenant_activation_approval_records_no_hard_delete",
        "tenant_id = collabio.current_tenant_id()",
        "using (false)",
        'required_migration_versions = \'["0051", "0052", "0053", "0054", "0074"]\'::jsonb',
    )
    forbidden_payloads = (
        "human_confirmation_statement text",
        "ticket_content text",
        "raw_payload text",
        "password text",
    )
    return all(marker in sql for marker in required_markers) and not any(
        payload in sql for payload in forbidden_payloads
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
    migration_plan_ready: bool,
    storage_migration_evidence_ready: bool,
    sql_checks: _MetadataSchemaSqlChecks,
    approval_record_restore_verified: bool,
    controlled_pilot_receipt_restore_verified: bool,
    tenant_approval_record_restore_verified: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalog_status is None:
        reasons.append("tickets_incidents_catalog_entry_missing")
    elif catalog_status != "not_installed":
        reasons.append("tickets_incidents_catalog_status_not_restore_drill_eligible")
    if tenant_module_status is not None:
        reasons.append("tenant_module_state_already_exists")
    if not storage_migration_evidence_ready:
        reasons.append("tickets_incidents_storage_migration_evidence_not_ready")
    if not migration_plan_ready:
        reasons.append("tickets_incidents_restore_migration_plan_missing")
    if not approval_record_restore_verified:
        reasons.append("tickets_incidents_activation_approval_record_restore_unverified")
    if not controlled_pilot_receipt_restore_verified:
        reasons.append("tickets_incidents_controlled_pilot_receipt_restore_unverified")
    if not tenant_approval_record_restore_verified:
        reasons.append("tickets_incidents_tenant_approval_record_restore_unverified")
    if not sql_checks.table_restore_verified:
        reasons.append("tickets_incidents_ticket_event_table_restore_unverified")
    if not sql_checks.rls_restore_verified or not sql_checks.tenant_isolation_restore_verified:
        reasons.append("tickets_incidents_tenant_rls_restore_unverified")
    if not sql_checks.retention_restore_verified or not sql_checks.legal_hold_restore_verified:
        reasons.append("tickets_incidents_retention_legal_hold_restore_unverified")
    if not sql_checks.kms_reference_restore_verified or not sql_checks.audit_reference_restore_verified:
        reasons.append("tickets_incidents_kms_audit_restore_unverified")
    if not sql_checks.sla_state_restore_verified:
        reasons.append("tickets_incidents_sla_state_restore_unverified")
    if not sql_checks.no_content_payload_restore_verified:
        reasons.append("tickets_incidents_content_payload_restore_boundary_failed")
    return tuple(reasons)
