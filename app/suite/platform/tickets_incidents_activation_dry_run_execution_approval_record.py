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
from suite.platform.tickets_incidents_tenant_admin_activation_approval_record import (
    TicketsIncidentsTenantAdminActivationApprovalRecordStore,
)

SCHEMA_VERSION = "tickets_incidents_activation_dry_run_execution_approval_record.v1"
ENDPOINT = "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-records"
RESULT_CONTRACT = "metadata_only_tickets_incidents_activation_dry_run_execution_approval_record_no_execution"
CONFIRMATION_STATEMENT = (
    "I explicitly approve the Tickets & Incidents activation dry-run for this tenant. "
    "This records approval metadata only and does not start workers, execute the dry-run, "
    "activate business APIs, or create tenant module state."
)
NEXT_ACTION = "exercise_tickets_incidents_productive_vertical_slice_in_controlled_pilot"
RETRY_ACTION = "record_tickets_incidents_activation_dry_run_execution_approval"
ZERO_HASH = "sha256:" + ("0" * 64)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")


class TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_boundary_evidence_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    change_request_ref: str
    idempotency_key_ref: str
    approved_at_utc: datetime
    audit_chain_ref: str
    approval_record_requested: bool = True
    worker_execution_requested: bool = False
    activation_dry_run_execution_requested: bool = False
    tickets_business_api_activation_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("approval_boundary_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("approval boundary evidence must be a sha256 reference")
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
            raise ValueError("approval references must use typed prefixes")
        return value.strip()

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_statement(cls, value: str) -> str:
        if value.strip() != CONFIRMATION_STATEMENT:
            raise ValueError("exact Tickets dry-run approval confirmation statement required")
        return value.strip()

    @field_validator("approved_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at_utc must include a timezone")
        return value


class TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = ENDPOINT
    result_contract: str = RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    approval_boundary_evidence_hash: str
    tenant_admin_approval_record_hash: str
    tickets_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    confirmation_statement_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    change_request_ref: str
    audit_chain_ref: str
    approved_by: str
    approved_at_utc: datetime
    approval_record_created: bool
    explicit_human_execution_approval_present: bool
    worker_execution_allowed: bool = False
    activation_dry_run_execution_allowed: bool = False
    tickets_business_api_allowed: bool = False
    tenant_module_state_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "approval_boundary_evidence_hash",
        "tenant_admin_approval_record_hash",
        "tickets_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "confirmation_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("approval record hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_record(
        self,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
        if self.schema_version != SCHEMA_VERSION or self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets dry-run approval record identity is invalid")
        expected_created = (
            self.approval_boundary_evidence_hash != ZERO_HASH
            and self.tenant_admin_approval_record_hash != ZERO_HASH
            and not self.blocking_reasons
        )
        if self.approval_record_created != expected_created:
            raise ValueError("Tickets dry-run approval record state is inconsistent")
        if self.explicit_human_execution_approval_present != self.approval_record_created:
            raise ValueError("explicit approval must match record creation")
        if (
            self.worker_execution_allowed
            or self.activation_dry_run_execution_allowed
            or self.tickets_business_api_allowed
            or self.tenant_module_state_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets dry-run approval record must remain metadata-only")
        return self


class TicketsIncidentsActivationDryRunExecutionApprovalRecordStore(Protocol):
    def append(
        self,
        record: TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse: ...

    def latest_for_boundary(
        self, *, tenant_id: str, approval_boundary_evidence_hash: str
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse | None: ...


class InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore:
    def __init__(
        self,
        records: Iterable[TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse] = (),
    ) -> None:
        self._by_boundary: dict[tuple[str, str], TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse] = {}
        self._by_idempotency: dict[
            tuple[str, str], TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse
        ] = {}
        for record in records:
            self.append(record)

    def append(
        self,
        record: TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
        if not record.approval_record_created:
            raise ValueError("blocked approval attempts must not be appended")
        idempotency_key = (record.tenant_id, record.idempotency_key_hash)
        if idempotency_key in self._by_idempotency:
            return self._by_idempotency[idempotency_key]
        boundary_key = (record.tenant_id, record.approval_boundary_evidence_hash)
        if boundary_key in self._by_boundary:
            raise ValueError("approval boundary already has a record")
        self._by_boundary[boundary_key] = record
        self._by_idempotency[idempotency_key] = record
        return record

    def latest_for_boundary(
        self, *, tenant_id: str, approval_boundary_evidence_hash: str
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse | None:
        return self._by_boundary.get((tenant_id, approval_boundary_evidence_hash))


class PgTicketsIncidentsActivationDryRunExecutionApprovalRecordStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(
        self,
        record: TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
        if not record.approval_record_created:
            raise ValueError("blocked approval attempts must not be appended")
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, record.tenant_id)
            existing = connection.execute(
                """
                SELECT approval_record
                FROM tickets.activation_dry_run_execution_approval_records
                WHERE tenant_id = %s AND idempotency_key_hash = %s
                """,
                (record.tenant_id, record.idempotency_key_hash),
            ).fetchone()
            if existing is not None:
                return TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse.model_validate(existing[0])
            try:
                connection.execute(
                    """
                    INSERT INTO tickets.activation_dry_run_execution_approval_records (
                        tenant_id,
                        approval_boundary_evidence_hash,
                        tenant_admin_approval_record_hash,
                        tickets_restore_drill_evidence_hash,
                        command_hash,
                        idempotency_key_hash,
                        confirmation_statement_hash,
                        approval_record_ref,
                        approval_ticket_ref,
                        human_confirmation_reference,
                        change_request_ref,
                        audit_chain_ref,
                        approved_by,
                        approved_at_utc,
                        approval_record,
                        evidence_hash
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.approval_boundary_evidence_hash,
                        record.tenant_admin_approval_record_hash,
                        record.tickets_restore_drill_evidence_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.confirmation_statement_hash,
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
                raise ValueError("approval boundary already has a record") from exc
        return record

    def latest_for_boundary(
        self, *, tenant_id: str, approval_boundary_evidence_hash: str
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT approval_record
                FROM tickets.activation_dry_run_execution_approval_records
                WHERE tenant_id = %s AND approval_boundary_evidence_hash = %s
                """,
                (tenant_id, approval_boundary_evidence_hash),
            ).fetchone()
        if row is None:
            return None
        return TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse.model_validate(row[0])


def build_default_tickets_incidents_activation_dry_run_execution_approval_record_store(
    environ: Mapping[str, str] | None = None,
) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TICKETS_APPROVAL_RECORD_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTicketsIncidentsActivationDryRunExecutionApprovalRecordStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_TICKETS_APPROVAL_RECORD_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL Tickets approval record store requires "
                "SUITE_TICKETS_APPROVAL_RECORD_DSN or SUITE_DATABASE_DSN"
            )
        return PgTicketsIncidentsActivationDryRunExecutionApprovalRecordStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_TICKETS_APPROVAL_RECORD_BACKEND: {backend}")


def build_tickets_incidents_activation_dry_run_execution_approval_record_response(
    *,
    command: TicketsIncidentsActivationDryRunExecutionApprovalRecordCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    tenant_approval_record_store: TicketsIncidentsTenantAdminActivationApprovalRecordStore,
) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
    gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    tenant_approval = (
        tenant_approval_record_store.latest_for_gate(
            tenant_id=user_context.tenant_id,
            approval_gate_evidence_hash=gate.evidence_hash,
        )
        if gate.approval_gate_ready
        else None
    )
    command_hash = stable_hash(
        canonical_json(
            {
                **command.model_dump(
                    mode="json",
                    exclude={"human_confirmation_statement"},
                ),
                "confirmation_statement_hash": stable_hash(command.human_confirmation_statement),
            }
        )
    )
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "tenant_id": user_context.tenant_id,
                "approval_boundary_evidence_hash": command.approval_boundary_evidence_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    reasons: list[str] = []
    if not gate.approval_gate_ready:
        reasons.append("tickets_incidents_activation_approval_gate_not_ready")
    if tenant_approval is None or not tenant_approval.approval_record_created:
        reasons.append("tickets_incidents_tenant_admin_activation_approval_record_missing")
    if command.approval_boundary_evidence_hash == ZERO_HASH:
        reasons.append("activation_dry_run_execution_approval_boundary_hash_missing")
    if user_context.role_ids.isdisjoint({"tenant-admin", "tenant_admin"}):
        reasons.append("tenant_admin_role_required")
    if not command.approval_record_requested:
        reasons.append("approval_record_not_requested")
    forbidden = {
        "worker_execution_request_forbidden": command.worker_execution_requested,
        "activation_dry_run_execution_request_forbidden": command.activation_dry_run_execution_requested,
        "tickets_business_api_activation_request_forbidden": command.tickets_business_api_activation_requested,
        "tenant_module_state_creation_request_forbidden": command.tenant_module_state_creation_requested,
        "content_payload_forbidden": command.content_payload_included,
        "destructive_action_request_forbidden": command.destructive_actions_requested,
        "external_side_effect_request_forbidden": command.external_side_effect_requested,
    }
    reasons.extend(reason for reason, requested in forbidden.items() if requested)
    created = not reasons
    draft = TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse(
        tenant_id=user_context.tenant_id,
        approval_boundary_evidence_hash=command.approval_boundary_evidence_hash,
        tenant_admin_approval_record_hash=tenant_approval.evidence_hash if tenant_approval else ZERO_HASH,
        tickets_restore_drill_evidence_hash=gate.tickets_restore_drill_evidence_hash or ZERO_HASH,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        confirmation_statement_hash=stable_hash(command.human_confirmation_statement),
        approval_record_ref=command.approval_record_ref,
        approval_ticket_ref=command.approval_ticket_ref,
        human_confirmation_reference=command.human_confirmation_reference,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        approved_by=user_context.user_id,
        approved_at_utc=command.approved_at_utc,
        approval_record_created=created,
        explicit_human_execution_approval_present=created,
        blocking_reasons=tuple(reasons),
        evidence_hash=ZERO_HASH,
        next_action=NEXT_ACTION if created else RETRY_ACTION,
    )
    return draft.model_copy(
        update={"evidence_hash": stable_hash(canonical_json(draft.model_dump(mode="json", exclude={"evidence_hash"})))}
    )
