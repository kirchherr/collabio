from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

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

TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_SCHEMA_VERSION = "tickets_incidents_activation_execution_boundary.v1"
TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_activation_execution_boundary_no_activation"
)
TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/activation-execution-boundary"
)
TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT = (
    "I request Tickets & Incidents activation execution boundary review without executing activation."
)
TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_READY_NEXT_ACTION = (
    "prepare_tickets_incidents_activation_executor_without_business_api_activation"
)
TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RETRY_NEXT_ACTION = (
    "review_tickets_incidents_activation_execution_boundary"
)

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class TicketsIncidentsActivationExecutionBoundaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    activation_execution_boundary_ref: str
    change_request_ref: str
    idempotency_key_ref: str
    reviewed_at_utc: datetime
    audit_chain_ref: str
    activation_execution_boundary_review_statement: str
    activation_execution_boundary_review_requested: bool = True
    activation_execution_requested: bool = False
    tenant_provisioning_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    tickets_business_api_activation_requested: bool = False
    worker_activation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("tenant_admin_approval_gate_hash", "tenant_admin_approval_record_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents activation execution boundary hashes must be sha256 references")
        return value

    @field_validator(
        "activation_execution_boundary_ref",
        "change_request_ref",
        "idempotency_key_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("Tickets & Incidents activation execution boundary references must use a typed ref prefix")
        return value.strip()

    @field_validator("activation_execution_boundary_review_statement")
    @classmethod
    def require_exact_review_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_REVIEW_STATEMENT:
            raise ValueError("Tickets & Incidents activation execution boundary requires the exact review statement")
        return normalized

    @field_validator("reviewed_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Tickets & Incidents activation execution boundary reviewed_at_utc needs a timezone")
        return value


class TicketsIncidentsActivationExecutionBoundarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_execution_boundary_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsActivationExecutionBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    approval_gate_ready: bool
    human_approval_ready: bool
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    tickets_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    activation_execution_boundary_review_statement_hash: str
    activation_execution_boundary_ref: str
    change_request_ref: str
    audit_chain_ref: str
    reviewed_by: str
    reviewed_at_utc: datetime
    approver_role_allowed: bool
    activation_execution_boundary_review_requested: bool
    activation_execution_boundary_review_ready: bool
    tickets_incidents_activation_execution_boundary_ready: bool
    future_activation_executor_required: bool = True
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
    required_execution_boundary_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: TicketsIncidentsActivationExecutionBoundarySummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "activation_execution_boundary_ref",
        "change_request_ref",
        "audit_chain_ref",
        "reviewed_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets & Incidents activation execution boundary text fields must not be empty")
        return value

    @field_validator(
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "tickets_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "activation_execution_boundary_review_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets & Incidents activation execution boundary hashes must be sha256 references")
        return value

    @field_validator("required_execution_boundary_evidence", "blocking_reasons", "evidence_refs")
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets & Incidents activation execution boundary lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets & Incidents activation execution boundary list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_boundary_contract(self) -> TicketsIncidentsActivationExecutionBoundaryResponse:
        if self.schema_version != TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_SCHEMA_VERSION:
            raise ValueError("Tickets & Incidents activation execution boundary schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_ENDPOINT:
            raise ValueError("Tickets & Incidents activation execution boundary endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RESULT_CONTRACT:
            raise ValueError("Tickets & Incidents activation execution boundary result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets & Incidents activation execution boundary only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets & Incidents activation execution boundary continuity domain is invalid")
        expected_ready = (
            self.approval_gate_ready
            and self.human_approval_ready
            and self.approver_role_allowed
            and self.activation_execution_boundary_review_requested
            and not self.blocking_reasons
        )
        if self.activation_execution_boundary_review_ready != expected_ready:
            raise ValueError("Tickets & Incidents activation execution boundary review readiness is inconsistent")
        if self.tickets_incidents_activation_execution_boundary_ready != expected_ready:
            raise ValueError("Tickets & Incidents activation execution boundary readiness is inconsistent")
        if not self.future_activation_executor_required:
            raise ValueError("Tickets & Incidents activation execution boundary must still require a future executor")
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
            raise ValueError("Tickets & Incidents activation execution boundary must remain metadata-only")
        if self.summary.required_execution_boundary_evidence_count != len(self.required_execution_boundary_evidence):
            raise ValueError("Tickets & Incidents activation execution boundary evidence count mismatch")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets & Incidents activation execution boundary blocking count mismatch")
        return self


def build_tickets_incidents_activation_execution_boundary_response(
    *,
    command: TicketsIncidentsActivationExecutionBoundaryCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    approval_record_store: TicketsIncidentsTenantAdminActivationApprovalRecordStore | None,
) -> TicketsIncidentsActivationExecutionBoundaryResponse:
    approval_gate = build_tickets_incidents_tenant_admin_activation_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    approval_record = (
        approval_record_store.latest_for_gate(
            tenant_id=user_context.tenant_id,
            approval_gate_evidence_hash=approval_gate.evidence_hash,
        )
        if approval_record_store is not None and approval_gate.approval_gate_ready
        else None
    )
    command_hash = build_tickets_incidents_activation_execution_boundary_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "tickets_incidents_activation_execution_boundary_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "tenant_admin_approval_gate_hash": command.tenant_admin_approval_gate_hash,
                "tenant_admin_approval_record_hash": command.tenant_admin_approval_record_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    review_statement_hash = stable_hash(command.activation_execution_boundary_review_statement)
    approver_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    human_approval_ready = approval_record is not None and approval_record.approval_record_created
    blocking_reasons = _activation_execution_boundary_blocking_reasons(
        command=command,
        approval_gate_ready=approval_gate.approval_gate_ready,
        expected_approval_gate_hash=approval_gate.evidence_hash,
        approval_record_hash=approval_record.evidence_hash if approval_record is not None else None,
        approver_role_allowed=approver_role_allowed,
    )
    boundary_ready = not blocking_reasons
    required_execution_boundary_evidence = (
        "tenant_admin_role",
        "activation_approval_gate_hash",
        "tenant_admin_activation_approval_record_hash",
        "tickets_restore_drill_evidence_hash",
        "exact_activation_execution_boundary_review_statement_hash",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_activation_executor_required",
        "no_tickets_activation_execution_confirmation",
        "no_tickets_business_api_activation_confirmation",
        "no_worker_activation_confirmation",
    )
    draft = TicketsIncidentsActivationExecutionBoundaryResponse(
        tenant_id=user_context.tenant_id,
        approval_gate_ready=approval_gate.approval_gate_ready,
        human_approval_ready=human_approval_ready,
        tenant_admin_approval_gate_hash=command.tenant_admin_approval_gate_hash,
        tenant_admin_approval_record_hash=command.tenant_admin_approval_record_hash,
        tickets_restore_drill_evidence_hash=approval_gate.tickets_restore_drill_evidence_hash
        or "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        activation_execution_boundary_review_statement_hash=review_statement_hash,
        activation_execution_boundary_ref=command.activation_execution_boundary_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        reviewed_by=user_context.user_id,
        reviewed_at_utc=command.reviewed_at_utc,
        approver_role_allowed=approver_role_allowed,
        activation_execution_boundary_review_requested=command.activation_execution_boundary_review_requested,
        activation_execution_boundary_review_ready=boundary_ready,
        tickets_incidents_activation_execution_boundary_ready=boundary_ready,
        required_execution_boundary_evidence=required_execution_boundary_evidence,
        blocking_reasons=blocking_reasons,
        summary=TicketsIncidentsActivationExecutionBoundarySummary(
            required_execution_boundary_evidence_count=len(required_execution_boundary_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "docs/operations/BACKUP_FAILOVER.md",
            "app/suite/platform/tickets_incidents_activation_execution_boundary.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "tests/test_tickets_incidents_activation_execution_boundary.py",
        ),
        evidence_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        next_action=(
            TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_READY_NEXT_ACTION
            if boundary_ready
            else TICKETS_INCIDENTS_ACTIVATION_EXECUTION_BOUNDARY_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_tickets_incidents_activation_execution_boundary_hash(draft)})


def build_tickets_incidents_activation_execution_boundary_command_hash(
    command: TicketsIncidentsActivationExecutionBoundaryCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"activation_execution_boundary_review_statement"})
    payload["activation_execution_boundary_review_statement_hash"] = stable_hash(
        command.activation_execution_boundary_review_statement
    )
    return stable_hash(canonical_json(payload))


def build_tickets_incidents_activation_execution_boundary_hash(
    response: TicketsIncidentsActivationExecutionBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _activation_execution_boundary_blocking_reasons(
    *,
    command: TicketsIncidentsActivationExecutionBoundaryCommand,
    approval_gate_ready: bool,
    expected_approval_gate_hash: str,
    approval_record_hash: str | None,
    approver_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not approval_gate_ready:
        reasons.append("tickets_incidents_activation_approval_gate_not_ready")
    if command.tenant_admin_approval_gate_hash != expected_approval_gate_hash:
        reasons.append("tenant_admin_activation_approval_gate_hash_mismatch")
    if approval_record_hash is None:
        reasons.append("tickets_incidents_tenant_admin_activation_approval_record_missing")
    elif command.tenant_admin_approval_record_hash != approval_record_hash:
        reasons.append("tickets_incidents_tenant_admin_activation_approval_record_hash_mismatch")
    if not approver_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.activation_execution_boundary_review_requested:
        reasons.append("activation_execution_boundary_review_not_requested")
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
