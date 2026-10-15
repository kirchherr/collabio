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

TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION = (
    "tickets_incidents_activation_dry_run_execution_approval_boundary.v1"
)
TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT = (
    "metadata_only_tickets_incidents_activation_dry_run_execution_approval_boundary_no_execution"
)
TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT = (
    "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-boundary"
)
TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT = (
    "I prepare the Tickets & Incidents activation dry-run execution approval boundary without recording "
    "execution approval, enqueuing workers, dispatching workers, or starting dry-run execution."
)
TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_READY_NEXT_ACTION = (
    "record_tickets_incidents_activation_dry_run_execution_approval_with_explicit_human_confirmation"
)
TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RETRY_NEXT_ACTION = (
    "prepare_tickets_incidents_activation_dry_run_execution_approval_boundary_without_execution"
)

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_SHA256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


class TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activation_dry_run_execution_final_readiness_gate_evidence_hash: str
    activation_dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    activation_dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    activation_dry_run_execution_approval_boundary_ref: str
    change_request_ref: str
    idempotency_key_ref: str
    prepared_at_utc: datetime
    audit_chain_ref: str
    activation_dry_run_execution_approval_boundary_statement: str
    activation_dry_run_execution_approval_boundary_requested: bool = True
    explicit_human_execution_approval_requested: bool = False
    scheduler_activation_requested: bool = False
    scheduler_job_creation_requested: bool = False
    worker_image_resolution_requested: bool = False
    worker_image_pull_requested: bool = False
    worker_image_digest_lookup_requested: bool = False
    worker_dispatch_requested: bool = False
    worker_queue_enqueue_requested: bool = False
    worker_execution_requested: bool = False
    activation_dry_run_execution_requested: bool = False
    dry_run_result_persistence_requested: bool = False
    activation_execution_requested: bool = False
    tenant_provisioning_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    tickets_business_api_activation_requested: bool = False
    worker_activation_requested: bool = False
    persistent_task_creation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator(
        "activation_dry_run_execution_final_readiness_gate_evidence_hash",
        "activation_dry_run_execution_scheduler_boundary_evidence_hash",
        "activation_dry_run_execution_worker_image_boundary_evidence_hash",
    )
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets dry-run execution approval boundary hashes must be sha256 references")
        return value

    @field_validator(
        "activation_dry_run_execution_approval_boundary_ref",
        "change_request_ref",
        "idempotency_key_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("Tickets dry-run execution approval boundary refs need typed prefixes")
        return value.strip()

    @field_validator("activation_dry_run_execution_approval_boundary_statement")
    @classmethod
    def require_exact_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_STATEMENT:
            raise ValueError("Tickets dry-run execution approval boundary requires the exact statement")
        return normalized

    @field_validator("prepared_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Tickets dry-run execution approval boundary prepared_at_utc needs a timezone")
        return value


class TicketsIncidentsActivationDryRunExecutionApprovalBoundarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activation_dry_run_execution_approval_boundary_step_count: int
    required_activation_dry_run_execution_approval_boundary_evidence_count: int
    blocking_reason_count: int


class TicketsIncidentsActivationDryRunExecutionApprovalBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str = TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT
    result_contract: str = TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    approval_gate_ready: bool
    human_approval_ready: bool
    activation_dry_run_execution_final_readiness_gate_evidence_hash: str
    activation_dry_run_execution_scheduler_boundary_evidence_hash: str = ZERO_SHA256
    activation_dry_run_execution_worker_image_boundary_evidence_hash: str = ZERO_SHA256
    tenant_admin_approval_gate_hash: str
    tenant_admin_approval_record_hash: str
    tickets_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    activation_dry_run_execution_approval_boundary_statement_hash: str
    activation_dry_run_execution_approval_boundary_ref: str
    change_request_ref: str
    audit_chain_ref: str
    prepared_by: str
    prepared_at_utc: datetime
    preparer_role_allowed: bool
    activation_dry_run_execution_approval_boundary_requested: bool
    activation_dry_run_execution_approval_boundary_ready: bool
    worker_image_boundary_evidence_bound: bool = False
    future_activation_dry_run_execution_approval_record_required: bool = True
    explicit_human_execution_approval_present: bool = False
    scheduler_activation_allowed: bool = False
    scheduler_job_creation_allowed: bool = False
    scheduler_job_created: bool = False
    worker_image_resolution_allowed: bool = False
    worker_image_resolved: bool = False
    worker_image_pull_allowed: bool = False
    worker_image_pulled: bool = False
    worker_image_digest_lookup_allowed: bool = False
    worker_image_digest_looked_up: bool = False
    worker_dispatch_allowed: bool = False
    worker_queue_enqueued: bool = False
    worker_execution_allowed: bool = False
    worker_executed: bool = False
    activation_dry_run_execution_allowed: bool = False
    activation_dry_run_executed: bool = False
    activation_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    tickets_business_api_allowed: bool = False
    worker_activation_allowed: bool = False
    module_activation_executed: bool = False
    tenant_module_state_created: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    dry_run_result_persistence_allowed: bool = False
    dry_run_result_persisted: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    activation_dry_run_execution_approval_boundary_steps: tuple[str, ...]
    required_activation_dry_run_execution_approval_boundary_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: TicketsIncidentsActivationDryRunExecutionApprovalBoundarySummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "activation_dry_run_execution_approval_boundary_ref",
        "change_request_ref",
        "audit_chain_ref",
        "prepared_by",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tickets dry-run execution approval boundary text fields must not be empty")
        return value

    @field_validator(
        "activation_dry_run_execution_final_readiness_gate_evidence_hash",
        "activation_dry_run_execution_scheduler_boundary_evidence_hash",
        "activation_dry_run_execution_worker_image_boundary_evidence_hash",
        "tenant_admin_approval_gate_hash",
        "tenant_admin_approval_record_hash",
        "tickets_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "activation_dry_run_execution_approval_boundary_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("Tickets dry-run execution approval boundary hashes must be sha256 references")
        return value

    @field_validator(
        "activation_dry_run_execution_approval_boundary_steps",
        "required_activation_dry_run_execution_approval_boundary_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Tickets dry-run execution approval boundary lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("Tickets dry-run execution approval boundary list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_approval_boundary(
        self,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalBoundaryResponse:
        if self.schema_version != TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_SCHEMA_VERSION:
            raise ValueError("Tickets dry-run execution approval boundary schema version is invalid")
        if self.endpoint != TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_ENDPOINT:
            raise ValueError("Tickets dry-run execution approval boundary endpoint is invalid")
        if self.result_contract != TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RESULT_CONTRACT:
            raise ValueError("Tickets dry-run execution approval boundary result contract is invalid")
        if self.module_id != TICKETS_INCIDENTS_MODULE_ID:
            raise ValueError("Tickets dry-run execution approval boundary only applies to tickets_incidents")
        if self.continuity_domain != TICKETS_INCIDENTS_CONTINUITY_DOMAIN:
            raise ValueError("Tickets dry-run execution approval boundary continuity domain is invalid")
        expected_ready = (
            self.approval_gate_ready
            and self.human_approval_ready
            and self.preparer_role_allowed
            and self.activation_dry_run_execution_approval_boundary_requested
            and not self.blocking_reasons
        )
        if self.activation_dry_run_execution_approval_boundary_ready != expected_ready:
            raise ValueError("Tickets dry-run execution approval boundary readiness is inconsistent")
        if not self.future_activation_dry_run_execution_approval_record_required:
            raise ValueError("Tickets dry-run execution approval boundary must require a future approval record")
        if self.explicit_human_execution_approval_present:
            raise ValueError("Tickets dry-run execution approval boundary must not record execution approval")
        expected_worker_image_bound = (
            self.activation_dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
            or self.activation_dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
        )
        if self.worker_image_boundary_evidence_bound != expected_worker_image_bound:
            raise ValueError("Tickets dry-run execution approval boundary worker-image binding is invalid")
        if (
            self.explicit_human_execution_approval_present
            or self.scheduler_activation_allowed
            or self.scheduler_job_creation_allowed
            or self.scheduler_job_created
            or self.worker_image_resolution_allowed
            or self.worker_image_resolved
            or self.worker_image_pull_allowed
            or self.worker_image_pulled
            or self.worker_image_digest_lookup_allowed
            or self.worker_image_digest_looked_up
            or self.worker_dispatch_allowed
            or self.worker_queue_enqueued
            or self.worker_execution_allowed
            or self.worker_executed
            or self.activation_dry_run_execution_allowed
            or self.activation_dry_run_executed
            or self.activation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.tickets_business_api_allowed
            or self.worker_activation_allowed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.content_included
            or self.dry_run_result_persistence_allowed
            or self.dry_run_result_persisted
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("Tickets dry-run execution approval boundary must remain metadata-only")
        if self.summary.activation_dry_run_execution_approval_boundary_step_count != len(
            self.activation_dry_run_execution_approval_boundary_steps
        ):
            raise ValueError("Tickets dry-run execution approval boundary step count mismatch")
        if self.summary.required_activation_dry_run_execution_approval_boundary_evidence_count != len(
            self.required_activation_dry_run_execution_approval_boundary_evidence
        ):
            raise ValueError("Tickets dry-run execution approval boundary evidence count mismatch")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("Tickets dry-run execution approval boundary blocking count mismatch")
        return self


def build_tickets_incidents_activation_dry_run_execution_approval_boundary_response(
    *,
    command: TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    approval_record_store: TicketsIncidentsTenantAdminActivationApprovalRecordStore | None,
) -> TicketsIncidentsActivationDryRunExecutionApprovalBoundaryResponse:
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
    command_hash = build_tickets_incidents_activation_dry_run_execution_approval_boundary_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "tickets_incidents_activation_dry_run_execution_approval_boundary_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "activation_dry_run_execution_final_readiness_gate_evidence_hash": (
                    command.activation_dry_run_execution_final_readiness_gate_evidence_hash
                ),
                "activation_dry_run_execution_scheduler_boundary_evidence_hash": (
                    command.activation_dry_run_execution_scheduler_boundary_evidence_hash
                ),
                "activation_dry_run_execution_worker_image_boundary_evidence_hash": (
                    command.activation_dry_run_execution_worker_image_boundary_evidence_hash
                ),
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    statement_hash = stable_hash(command.activation_dry_run_execution_approval_boundary_statement)
    preparer_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    human_approval_ready = approval_record is not None and approval_record.approval_record_created
    blocking_reasons = _activation_dry_run_execution_approval_boundary_blocking_reasons(
        command=command,
        approval_gate_ready=approval_gate.approval_gate_ready,
        expected_approval_record_hash=approval_record.evidence_hash if approval_record is not None else None,
        preparer_role_allowed=preparer_role_allowed,
    )
    boundary_ready = not blocking_reasons
    worker_image_boundary_evidence_bound = (
        command.activation_dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
        or command.activation_dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
    )
    boundary_steps = (
        "verify_tickets_catalog_status_not_installed",
        "bind_tickets_activation_dry_run_execution_final_readiness_gate_hash",
        "bind_tickets_activation_dry_run_execution_scheduler_boundary_hash_when_present",
        "bind_tickets_activation_dry_run_execution_worker_image_boundary_hash_when_present",
        "verify_activation_dry_run_execution_final_readiness_gate_schema_bound",
        "confirm_worker_image_boundary_chain_preserved_at_approval_boundary_when_present",
        "define_approval_boundary_idempotency_and_hash_closure",
        "define_approval_boundary_requires_separate_explicit_human_approval_record",
        "confirm_no_execution_approval_recorded_at_approval_boundary",
        "confirm_scheduler_no_activation_no_job_creation_flags",
        "confirm_worker_image_no_resolution_no_pull_no_digest_lookup_flags",
        "confirm_worker_no_enqueue_no_dispatch_no_execution_flags",
        "defer_activation_dry_run_execution_start",
        "defer_activation_dry_run_result_persistence",
        "confirm_no_tenant_module_state_creation",
        "confirm_no_tickets_business_api_activation",
        "confirm_no_ticket_worker_activation",
        "emit_audit_hashes_without_prompt_or_confirmation_text",
    )
    required_evidence = (
        "tenant_admin_role",
        "activation_approval_gate_ready",
        "activation_dry_run_execution_final_readiness_gate_hash",
        "optional_activation_dry_run_execution_scheduler_boundary_hash",
        "optional_activation_dry_run_execution_worker_image_boundary_hash",
        "worker_image_boundary_chain_hashes_when_present",
        "tenant_admin_activation_approval_gate_hash",
        "tenant_admin_activation_approval_record_hash",
        "tickets_restore_drill_evidence_hash",
        "exact_activation_dry_run_execution_approval_boundary_statement_hash",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "activation_dry_run_execution_approval_boundary_schema_version",
        "activation_dry_run_execution_final_readiness_gate_schema_version",
        "approval_boundary_idempotency_and_hash_closure",
        "scheduler_activation_disabled",
        "scheduler_job_creation_disabled",
        "worker_image_resolution_disabled",
        "worker_image_pull_disabled",
        "worker_image_digest_lookup_disabled",
        "separate_explicit_execution_approval_record_required",
        "future_activation_dry_run_execution_approval_record_required",
        "no_tickets_dry_run_execution_confirmation",
        "no_dry_run_result_persistence_confirmation",
    )
    draft = TicketsIncidentsActivationDryRunExecutionApprovalBoundaryResponse(
        tenant_id=user_context.tenant_id,
        approval_gate_ready=approval_gate.approval_gate_ready,
        human_approval_ready=human_approval_ready,
        activation_dry_run_execution_final_readiness_gate_evidence_hash=(
            command.activation_dry_run_execution_final_readiness_gate_evidence_hash
        ),
        activation_dry_run_execution_scheduler_boundary_evidence_hash=(
            command.activation_dry_run_execution_scheduler_boundary_evidence_hash
        ),
        activation_dry_run_execution_worker_image_boundary_evidence_hash=(
            command.activation_dry_run_execution_worker_image_boundary_evidence_hash
        ),
        tenant_admin_approval_gate_hash=approval_gate.evidence_hash,
        tenant_admin_approval_record_hash=(
            approval_record.evidence_hash if approval_record is not None else ZERO_SHA256
        ),
        tickets_restore_drill_evidence_hash=approval_gate.tickets_restore_drill_evidence_hash or ZERO_SHA256,
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        activation_dry_run_execution_approval_boundary_statement_hash=statement_hash,
        activation_dry_run_execution_approval_boundary_ref=command.activation_dry_run_execution_approval_boundary_ref,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        prepared_by=user_context.user_id,
        prepared_at_utc=command.prepared_at_utc,
        preparer_role_allowed=preparer_role_allowed,
        activation_dry_run_execution_approval_boundary_requested=(
            command.activation_dry_run_execution_approval_boundary_requested
        ),
        activation_dry_run_execution_approval_boundary_ready=boundary_ready,
        worker_image_boundary_evidence_bound=worker_image_boundary_evidence_bound,
        activation_dry_run_execution_approval_boundary_steps=boundary_steps,
        required_activation_dry_run_execution_approval_boundary_evidence=required_evidence,
        blocking_reasons=blocking_reasons,
        summary=TicketsIncidentsActivationDryRunExecutionApprovalBoundarySummary(
            activation_dry_run_execution_approval_boundary_step_count=len(boundary_steps),
            required_activation_dry_run_execution_approval_boundary_evidence_count=len(required_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "docs/operations/BACKUP_FAILOVER.md",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_final_readiness_gate.py",
            "app/suite/platform/tickets_incidents_activation_dry_run_execution_approval_boundary.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
            "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
            "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
            "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
            "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
            "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
            "tests/test_tickets_incidents_activation_dry_run_execution_final_readiness_gate.py",
            "tests/test_tickets_incidents_activation_dry_run_execution_approval_boundary.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_gate.py",
            "tests/test_tickets_incidents_tenant_admin_activation_approval_record.py",
        ),
        evidence_hash=ZERO_SHA256,
        next_action=(
            TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_READY_NEXT_ACTION
            if boundary_ready
            else TICKETS_INCIDENTS_ACTIVATION_DRY_RUN_EXECUTION_APPROVAL_BOUNDARY_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(
        update={"evidence_hash": build_tickets_incidents_activation_dry_run_execution_approval_boundary_hash(draft)}
    )


def build_tickets_incidents_activation_dry_run_execution_approval_boundary_command_hash(
    command: TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand,
) -> str:
    payload = command.model_dump(
        mode="json",
        exclude={"activation_dry_run_execution_approval_boundary_statement"},
    )
    payload["activation_dry_run_execution_approval_boundary_statement_hash"] = stable_hash(
        command.activation_dry_run_execution_approval_boundary_statement
    )
    return stable_hash(canonical_json(payload))


def build_tickets_incidents_activation_dry_run_execution_approval_boundary_hash(
    response: TicketsIncidentsActivationDryRunExecutionApprovalBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _activation_dry_run_execution_approval_boundary_blocking_reasons(
    *,
    command: TicketsIncidentsActivationDryRunExecutionApprovalBoundaryCommand,
    approval_gate_ready: bool,
    expected_approval_record_hash: str | None,
    preparer_role_allowed: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not approval_gate_ready:
        reasons.append("tickets_incidents_activation_approval_gate_not_ready")
    if command.activation_dry_run_execution_final_readiness_gate_evidence_hash == ZERO_SHA256:
        reasons.append("tickets_incidents_activation_dry_run_execution_final_readiness_gate_hash_missing")
    worker_image_chain_requested = (
        command.activation_dry_run_execution_scheduler_boundary_evidence_hash != ZERO_SHA256
        or command.activation_dry_run_execution_worker_image_boundary_evidence_hash != ZERO_SHA256
    )
    if (
        worker_image_chain_requested
        and command.activation_dry_run_execution_scheduler_boundary_evidence_hash == ZERO_SHA256
    ):
        reasons.append("tickets_incidents_activation_dry_run_execution_scheduler_boundary_hash_missing")
    if (
        worker_image_chain_requested
        and command.activation_dry_run_execution_worker_image_boundary_evidence_hash == ZERO_SHA256
    ):
        reasons.append("tickets_incidents_activation_dry_run_execution_worker_image_boundary_hash_missing")
    if expected_approval_record_hash is None:
        reasons.append("tickets_incidents_tenant_admin_activation_approval_record_missing")
    if not preparer_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.activation_dry_run_execution_approval_boundary_requested:
        reasons.append("activation_dry_run_execution_approval_boundary_not_requested")
    if command.explicit_human_execution_approval_requested:
        reasons.append("explicit_human_execution_approval_requires_separate_record")
    if command.scheduler_activation_requested:
        reasons.append("scheduler_activation_request_forbidden")
    if command.scheduler_job_creation_requested:
        reasons.append("scheduler_job_creation_request_forbidden")
    if command.worker_image_resolution_requested:
        reasons.append("worker_image_resolution_request_forbidden")
    if command.worker_image_pull_requested:
        reasons.append("worker_image_pull_request_forbidden")
    if command.worker_image_digest_lookup_requested:
        reasons.append("worker_image_digest_lookup_request_forbidden")
    if command.worker_dispatch_requested:
        reasons.append("worker_dispatch_request_forbidden")
    if command.worker_queue_enqueue_requested:
        reasons.append("worker_queue_enqueue_request_forbidden")
    if command.worker_execution_requested:
        reasons.append("worker_execution_request_forbidden")
    if command.activation_dry_run_execution_requested:
        reasons.append("activation_dry_run_execution_request_forbidden")
    if command.dry_run_result_persistence_requested:
        reasons.append("dry_run_result_persistence_request_forbidden")
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
    if command.persistent_task_creation_requested:
        reasons.append("persistent_task_creation_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
