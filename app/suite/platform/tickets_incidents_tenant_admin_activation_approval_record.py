from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.tickets_incidents_module import (
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
)
from suite.platform.tickets_incidents_tenant_admin_activation_approval_gate import (
    build_tickets_incidents_tenant_admin_activation_approval_gate_response,
)

TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_SCHEMA_VERSION = (
    "tickets_incidents_tenant_admin_activation_approval_record.v1"
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_tenant_admin_activation_approval_record_no_activation"
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-records"
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT = (
    "I explicitly approve the Tickets & Incidents tenant activation readiness gate "
    "for this tenant without executing activation."
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CREATED_NEXT_ACTION = (
    "review_tickets_incidents_activation_execution_boundary"
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RETRY_NEXT_ACTION = (
    "record_tickets_incidents_tenant_admin_activation_approval_with_explicit_human_confirmation"
)
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_APPROVED = "approved_for_activation_execution_gate"
TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_BLOCKED = "blocked"

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class TicketsIncidentsTenantAdminActivationApprovalRecordCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_gate_evidence_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    change_request_ref: str
    idempotency_key_ref: str
    approved_at_utc: datetime
    audit_chain_ref: str
    approval_record_requested: bool = True
    activation_execution_requested: bool = False
    tenant_provisioning_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    tickets_business_api_activation_requested: bool = False
    worker_activation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("approval_gate_evidence_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents approval gate evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "idempotency_key_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("Tickets & Incidents approval record references must use a typed ref prefix")
        return value.strip()

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT:
            raise ValueError("Tickets & Incidents approval record requires the exact human confirmation statement")
        return normalized

    @field_validator("approved_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Tickets & Incidents approval record approved_at_utc must include a timezone")
        return value


class TicketsIncidentsTenantAdminActivationApprovalRecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_approval_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsTenantAdminActivationApprovalRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    approval_gate_ready: bool
    approval_gate_evidence_hash: str
    tickets_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    change_request_ref: str
    audit_chain_ref: str
    approved_by: str
    approved_at_utc: datetime
    approver_role_allowed: bool
    record_status: str
    approval_record_created: bool
    human_confirmation_captured: bool
    human_confirmation_statement_matched: bool
    future_activation_execution_gate_required: bool = True
    activation_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    tickets_business_api_allowed: bool = False
    worker_activation_allowed: bool = False
    module_activation_executed: bool = False
    tenant_module_state_created: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    required_approval_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: TicketsIncidentsTenantAdminActivationApprovalRecordSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "audit_chain_ref",
        "approved_by",
        "record_status",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents approval record text fields must not be empty")
        return value

    @field_validator(
        "approval_gate_evidence_hash",
        "tickets_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents approval record hashes must be sha256 references")
        return value

    @field_validator("required_approval_evidence", "blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents approval record lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents approval record list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_record_contract(self) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse:
        if self.schema_version != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents approval record schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_ENDPOINT:
            raise ValueError("Tickets & Incidents approval record endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents approval record result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents approval record only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents approval record continuity domain is invalid")
        expected_created = (
            self.approval_gate_ready
            and self.approver_role_allowed
            and self.human_confirmation_captured
            and self.human_confirmation_statement_matched
            and not self.blocking_reasons
        )
        if self.approval_record_created != expected_created:
            raise ValueError("Tickets & Incidents approval record creation flag must match prerequisites")
        if (
            self.approval_record_created
            and self.record_status != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_APPROVED
        ):
            raise ValueError("created Tickets & Incidents approval records must approve the next execution gate")
        if (
            not self.approval_record_created
            and self.record_status != TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_BLOCKED
        ):
            raise ValueError("blocked Tickets & Incidents approval record attempts must use blocked status")
        if not self.future_activation_execution_gate_required:
            raise ValueError("Tickets & Incidents approval record must require a future activation execution gate")
        if (
            self.activation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.tickets_business_api_allowed
            or self.worker_activation_allowed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets & Incidents approval record must remain metadata-only and non-executing")
        if self.summary.required_approval_evidence_count != len(self.required_approval_evidence):
            raise ValueError("Tickets & Incidents approval record evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets & Incidents approval record blocking count must match blocking reasons")
        return self


class TicketsIncidentsTenantAdminActivationApprovalRecordStore(Protocol):
    def append(
        self,
        record: TicketsIncidentsTenantAdminActivationApprovalRecordResponse,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse: ...

    def latest_for_gate(
        self,
        *,
        tenant_id: str,
        approval_gate_evidence_hash: str,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse | None: ...


class InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore:
    def __init__(
        self,
        records: Iterable[TicketsIncidentsTenantAdminActivationApprovalRecordResponse] = (),
    ) -> None:
        self._by_tenant_gate: dict[tuple[str, str], TicketsIncidentsTenantAdminActivationApprovalRecordResponse] = {}
        self._by_tenant_idempotency: dict[
            tuple[str, str], TicketsIncidentsTenantAdminActivationApprovalRecordResponse
        ] = {}
        for record in records:
            self.append(record)

    def append(
        self,
        record: TicketsIncidentsTenantAdminActivationApprovalRecordResponse,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse:
        if not record.approval_record_created:
            raise ValueError("blocked Tickets & Incidents approval record attempts must not be appended")
        gate_key = (record.tenant_id, record.approval_gate_evidence_hash)
        idempotency_key = (record.tenant_id, record.idempotency_key_hash)
        existing_for_idempotency = self._by_tenant_idempotency.get(idempotency_key)
        if existing_for_idempotency is not None:
            return existing_for_idempotency
        existing_for_gate = self._by_tenant_gate.get(gate_key)
        if existing_for_gate is not None:
            raise ValueError("Tickets & Incidents approval gate already has an approval record for this tenant")
        self._by_tenant_gate[gate_key] = record
        self._by_tenant_idempotency[idempotency_key] = record
        return record

    def latest_for_gate(
        self,
        *,
        tenant_id: str,
        approval_gate_evidence_hash: str,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse | None:
        return self._by_tenant_gate.get((tenant_id, approval_gate_evidence_hash))


class PgTicketsIncidentsTenantAdminActivationApprovalRecordStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(
        self,
        record: TicketsIncidentsTenantAdminActivationApprovalRecordResponse,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse:
        if not record.approval_record_created:
            raise ValueError("blocked Tickets & Incidents approval record attempts must not be appended")
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, record.tenant_id)
            existing = connection.execute(
                """
                SELECT approval_record
                FROM tickets.tenant_admin_activation_approval_records
                WHERE tenant_id = %s AND idempotency_key_hash = %s
                """,
                (record.tenant_id, record.idempotency_key_hash),
            ).fetchone()
            if existing is not None:
                return TicketsIncidentsTenantAdminActivationApprovalRecordResponse.model_validate(existing[0])
            try:
                connection.execute(
                    """
                    INSERT INTO tickets.tenant_admin_activation_approval_records (
                        tenant_id, approval_gate_evidence_hash,
                        tickets_restore_drill_evidence_hash, command_hash,
                        idempotency_key_hash, human_confirmation_statement_hash,
                        approval_record_ref, approval_ticket_ref,
                        human_confirmation_reference, change_request_ref,
                        audit_chain_ref, approved_by, approved_at_utc,
                        approval_record, evidence_hash
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.approval_gate_evidence_hash,
                        record.tickets_restore_drill_evidence_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.approval_record_ref,
                        record.approval_ticket_ref,
                        record.human_confirmation_reference,
                        record.change_request_ref,
                        record.audit_chain_ref,
                        record.approved_by,
                        record.approved_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError(
                    "Tickets & Incidents approval gate already has an approval record for this tenant"
                ) from exc
        return record

    def latest_for_gate(
        self,
        *,
        tenant_id: str,
        approval_gate_evidence_hash: str,
    ) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT approval_record
                FROM tickets.tenant_admin_activation_approval_records
                WHERE tenant_id = %s AND approval_gate_evidence_hash = %s
                """,
                (tenant_id, approval_gate_evidence_hash),
            ).fetchone()
        if row is None:
            return None
        return TicketsIncidentsTenantAdminActivationApprovalRecordResponse.model_validate(row[0])


def build_default_tickets_incidents_tenant_admin_activation_approval_record_store(
    environ: Mapping[str, str] | None = None,
) -> (
    TicketsIncidentsTenantAdminActivationApprovalRecordStore
):
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TICKETS_TENANT_APPROVAL_RECORD_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTicketsIncidentsTenantAdminActivationApprovalRecordStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_TICKETS_TENANT_APPROVAL_RECORD_DSN") or env.get(
            "SUITE_DATABASE_DSN"
        )
        if not database_dsn:
            raise ValueError(
                "PostgreSQL Tickets tenant approval record store requires "
                "SUITE_TICKETS_TENANT_APPROVAL_RECORD_DSN or SUITE_DATABASE_DSN"
            )
        return PgTicketsIncidentsTenantAdminActivationApprovalRecordStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_TICKETS_TENANT_APPROVAL_RECORD_BACKEND: {backend}")


def build_tickets_incidents_tenant_admin_activation_approval_record_response(
    *,
    command: TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> TicketsIncidentsTenantAdminActivationApprovalRecordResponse:
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    command_hash = build_tickets_incidents_tenant_admin_activation_approval_record_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "tickets_incidents_tenant_admin_activation_approval_record_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "approval_gate_evidence_hash": command.approval_gate_evidence_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    human_confirmation_statement_hash = stable_hash(command.human_confirmation_statement)
    approver_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    human_confirmation_statement_matched = (
        command.human_confirmation_statement
        == TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CONFIRMATION_STATEMENT
    )
    blocking_reasons = _approval_record_blocking_reasons(
        command=command,
        approval_gate_ready=approval_gate.approval_gate_ready,
        expected_approval_gate_evidence_hash=approval_gate.evidence_hash,
        approver_role_allowed=approver_role_allowed,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
    )
    approval_record_created = not blocking_reasons
    required_approval_evidence = (
        "tenant_admin_role",
        "approval_gate_evidence_hash",
        "tickets_restore_drill_evidence_hash",
        "exact_human_confirmation_statement_hash",
        "approval_ticket_ref",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_activation_execution_gate_required",
        "no_tickets_activation_execution_confirmation",
    )
    draft = TicketsIncidentsTenantAdminActivationApprovalRecordResponse(
        tenant_id=user_context.tenant_id,
        approval_gate_ready=approval_gate.approval_gate_ready,
        approval_gate_evidence_hash=command.approval_gate_evidence_hash,
        tickets_restore_drill_evidence_hash=approval_gate.tickets_restore_drill_evidence_hash
        or "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        human_confirmation_statement_hash=human_confirmation_statement_hash,
        approval_record_ref=command.approval_record_ref,
        approval_ticket_ref=command.approval_ticket_ref,
        human_confirmation_reference=command.human_confirmation_reference,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        approved_by=user_context.user_id,
        approved_at_utc=command.approved_at_utc,
        approver_role_allowed=approver_role_allowed,
        record_status=(
            TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_APPROVED
            if approval_record_created
            else TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_STATUS_BLOCKED
        ),
        approval_record_created=approval_record_created,
        human_confirmation_captured=True,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
        required_approval_evidence=required_approval_evidence,
        blocking_reasons=blocking_reasons,
        summary=TicketsIncidentsTenantAdminActivationApprovalRecordSummary(
            required_approval_evidence_count=len(required_approval_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_record.py",
        ),
        evidence_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        next_action=(
            TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_CREATED_NEXT_ACTION
            if approval_record_created
            else TICKETS_INCIDENTS_TENANT_ADMIN_ACTIVATION_APPROVAL_RECORD_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_tickets_incidents_tenant_admin_activation_approval_record_hash(draft)}
    )


def build_tickets_incidents_tenant_admin_activation_approval_record_command_hash(
    command: TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"human_confirmation_statement"})
    payload["human_confirmation_statement_hash"] = stable_hash(command.human_confirmation_statement)
    return stable_hash(canonical_json(payload))


def build_tickets_incidents_tenant_admin_activation_approval_record_hash(
    response: TicketsIncidentsTenantAdminActivationApprovalRecordResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _approval_record_blocking_reasons(
    *,
    command: TicketsIncidentsTenantAdminActivationApprovalRecordCommand,
    approval_gate_ready: bool,
    expected_approval_gate_evidence_hash: str,
    approver_role_allowed: bool,
    human_confirmation_statement_matched: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not approval_gate_ready:
        reasons.append("tickets_incidents_activation_approval_gate_not_ready")
    if command.approval_gate_evidence_hash != expected_approval_gate_evidence_hash:
        reasons.append("approval_gate_evidence_hash_mismatch")
    if not approver_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.approval_record_requested:
        reasons.append("approval_record_not_requested")
    if not human_confirmation_statement_matched:
        reasons.append("human_confirmation_statement_mismatch")
    if command.activation_execution_requested:
        reasons.append("activation_execution_request_forbidden")
    if command.tenant_provisioning_requested:
        reasons.append("tenant_provisioning_request_forbidden")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_request_forbidden")
    if command.migration_execution_requested:
        reasons.append("migration_execution_request_forbidden")
    if command.tickets_business_api_activation_requested:
        reasons.append("tickets_business_api_activation_request_forbidden")
    if command.worker_activation_requested:
        reasons.append("worker_activation_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
