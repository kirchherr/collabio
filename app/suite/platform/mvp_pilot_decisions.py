from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.product_cockpit import ProductCockpitMvpSnapshotResponse
from suite.storage.source_objects import sha256_bytes

MVP_PILOT_DECISION_CONTEXT_SCHEMA_VERSION = "mvp_pilot_decision_context.v1"
MVP_PILOT_DECISION_RECORD_SCHEMA_VERSION = "mvp_pilot_decision_record.v1"
MVP_PILOT_DECISION_SUBMIT_CONTRACT_ID = "mvp_pilot_decision_capture_submit_contract.v1"
MVP_PILOT_DECISION_CONFIRMATION_STATEMENT = (
    "I explicitly record this tenant-scoped MVP pilot decision against the supplied evidence context. "
    "This stores decision evidence only; it does not admit users, activate modules, authorize traffic, "
    "start the pilot, or execute external or destructive actions."
)

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ADMIN_ROLE_IDS = {"tenant-admin", "security-admin"}


class MvpPilotDecisionValue(StrEnum):
    GO = "go"
    NO_GO = "no_go"
    DEFER = "defer"


class MvpPilotDecisionConflict(ValueError):
    pass


class MvpPilotDecisionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    checked_by: str
    decision_scope: str = "metadata_only_workspace_pilot"
    decision_options: tuple[MvpPilotDecisionValue, ...] = tuple(MvpPilotDecisionValue)
    mvp_readiness_decision: str
    metadata_only_productive_path: bool
    role_gate_status: str
    audit_gate_status: str
    backup_failover_gate_status: str
    module_gate_status: str
    content_gate_status: str
    foundation_gap_status: str
    active_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    required_roles: tuple[str, ...]
    module_count: int = Field(ge=0)
    source_object_flow_count: int = Field(ge=0)
    work_item_count: int = Field(ge=0)
    module_manifest_hash: str
    source_object_flow_manifest_hash: str
    work_item_manifest_hash: str
    foundation_gap_manifest_hash: str
    go_decision_allowed: bool
    content_included: bool = False
    persistent_task_created: bool = False
    automation_created: bool = False
    pilot_admission_allowed: bool = False
    pilot_start_allowed: bool = False
    module_activation_executed: bool = False
    traffic_authorized: bool = False
    external_side_effect_executed: bool = False
    context_hash: str
    schema_version: str = MVP_PILOT_DECISION_CONTEXT_SCHEMA_VERSION

    @field_validator(
        "module_manifest_hash",
        "source_object_flow_manifest_hash",
        "work_item_manifest_hash",
        "foundation_gap_manifest_hash",
        "context_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("MVP pilot decision context hashes must use sha256")
        return value

    @model_validator(mode="after")
    def require_non_executing_context(self) -> Self:
        expected_go_allowed = (
            self.metadata_only_productive_path
            and self.audit_gate_status == "audit_visible"
            and self.backup_failover_gate_status == "metadata_only_no_state_change"
            and self.content_gate_status == "deferred_metadata_only_ready"
            and not self.content_included
            and not self.persistent_task_created
            and not self.automation_created
        )
        if (
            self.schema_version != MVP_PILOT_DECISION_CONTEXT_SCHEMA_VERSION
            or self.decision_scope != "metadata_only_workspace_pilot"
            or self.go_decision_allowed != expected_go_allowed
            or self.pilot_admission_allowed
            or self.pilot_start_allowed
            or self.module_activation_executed
            or self.traffic_authorized
            or self.external_side_effect_executed
        ):
            raise ValueError("MVP pilot decision context violates the non-executing boundary")
        return self


def _canonical_hash(value: object) -> str:
    return stable_hash(canonical_json(value))


def _model_manifest_hash(values: tuple[BaseModel, ...], *, excluded_fields: set[str] | None = None) -> str:
    excluded = excluded_fields or set()
    manifest = []
    for value in values:
        item = value.model_dump(mode="json")
        for field_name in excluded:
            item.pop(field_name, None)
        manifest.append(item)
    return _canonical_hash(manifest)


def build_mvp_pilot_decision_context_hash(context: MvpPilotDecisionContext) -> str:
    return _canonical_hash(context.model_dump(mode="json", exclude={"checked_by", "context_hash"}))


def build_mvp_pilot_decision_context(
    *,
    user_context: UserContext,
    snapshot: ProductCockpitMvpSnapshotResponse,
) -> MvpPilotDecisionContext:
    if snapshot.tenant_id != user_context.tenant_id:
        raise ValueError("MVP pilot snapshot tenant does not match request context")
    readiness = snapshot.mvp_readiness_decision
    go_decision_allowed = (
        readiness.metadata_only_productive_path
        and readiness.audit_gate_status == "audit_visible"
        and readiness.backup_failover_gate_status == "metadata_only_no_state_change"
        and readiness.content_gate_status == "deferred_metadata_only_ready"
        and not readiness.content_included
        and not readiness.persistent_task_created
        and not readiness.automation_created
        and not snapshot.content_included
        and not snapshot.persistent_task_created
        and not snapshot.automation_created
    )
    draft = MvpPilotDecisionContext(
        tenant_id=user_context.tenant_id,
        checked_by=user_context.user_id,
        mvp_readiness_decision=readiness.decision,
        metadata_only_productive_path=readiness.metadata_only_productive_path,
        role_gate_status=readiness.role_gate_status,
        audit_gate_status=readiness.audit_gate_status,
        backup_failover_gate_status=readiness.backup_failover_gate_status,
        module_gate_status=readiness.module_gate_status,
        content_gate_status=readiness.content_gate_status,
        foundation_gap_status=readiness.foundation_gap_status,
        active_foundation_gap_ids=readiness.active_foundation_gap_ids,
        ready_foundation_gap_ids=readiness.ready_foundation_gap_ids,
        deferred_foundation_gap_ids=readiness.deferred_foundation_gap_ids,
        next_foundation_action=readiness.next_foundation_action,
        required_roles=readiness.required_roles,
        module_count=len(snapshot.module_refs),
        source_object_flow_count=len(snapshot.source_object_flow_refs),
        work_item_count=len(snapshot.work_item_refs),
        module_manifest_hash=_model_manifest_hash(snapshot.module_refs),
        source_object_flow_manifest_hash=_model_manifest_hash(
            snapshot.source_object_flow_refs,
            excluded_fields={"cockpit_audit_event_id"},
        ),
        work_item_manifest_hash=_model_manifest_hash(snapshot.work_item_refs),
        foundation_gap_manifest_hash=_model_manifest_hash(snapshot.foundation_gap_actions),
        go_decision_allowed=go_decision_allowed,
        context_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"context_hash": build_mvp_pilot_decision_context_hash(draft)})


class MvpPilotDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    decision_id: str
    decision_capture_submit_contract_id: str = MVP_PILOT_DECISION_SUBMIT_CONTRACT_ID
    decision_context_hash: str
    go_no_go_decision: MvpPilotDecisionValue
    decision_reason: str = Field(min_length=3, max_length=1000)
    human_confirmation_statement: str
    human_confirmation_reference: str = Field(min_length=3, max_length=256)
    change_request_ref: str = Field(min_length=3, max_length=256)
    confirmed_by: str = Field(min_length=1, max_length=128)
    confirmed_at: datetime
    confirmation_role_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=3, max_length=256)
    decision_record_requested: bool = True
    pilot_admission_requested: bool = False
    pilot_start_requested: bool = False
    module_activation_requested: bool = False
    traffic_authorization_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("decision_id")
    @classmethod
    def require_decision_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("MVP pilot decision ID has an invalid format")
        return value

    @field_validator("decision_context_hash")
    @classmethod
    def require_context_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("MVP pilot decision context hash must use sha256")
        return value

    @field_validator("human_confirmation_reference", "change_request_ref", "idempotency_key")
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("MVP pilot decision references must be typed")
        return value

    @field_validator("decision_reason")
    @classmethod
    def normalize_decision_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("MVP pilot decision reason must contain at least three characters")
        return normalized

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != MVP_PILOT_DECISION_CONFIRMATION_STATEMENT:
            raise ValueError("exact MVP pilot decision confirmation statement required")
        return value

    @field_validator("confirmed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("confirmed_at must include a timezone")
        return value

    @field_validator("confirmation_role_ids")
    @classmethod
    def normalize_confirmation_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(value)))
        if not normalized or set(normalized).isdisjoint(ADMIN_ROLE_IDS):
            raise ValueError("tenant-admin or security-admin confirmation role required")
        return normalized

    @model_validator(mode="after")
    def require_non_executing_decision(self) -> Self:
        if (
            self.decision_capture_submit_contract_id != MVP_PILOT_DECISION_SUBMIT_CONTRACT_ID
            or not self.decision_record_requested
            or self.pilot_admission_requested
            or self.pilot_start_requested
            or self.module_activation_requested
            or self.traffic_authorization_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError("MVP pilot decision capture must remain non-executing and metadata-only")
        return self


class MvpPilotDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    decision_id: str
    decision_scope: str
    decision_context_hash: str
    go_no_go_decision: MvpPilotDecisionValue
    decision_reason_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    human_confirmation_reference: str
    change_request_ref: str
    decided_by: str
    decided_at: datetime
    confirmation_role_ids: tuple[str, ...]
    audit_event_id: str
    audit_chain_ref: str
    mvp_readiness_decision: str
    module_gate_status: str
    content_gate_status: str
    backup_failover_gate_status: str
    active_foundation_gap_ids: tuple[str, ...]
    ready_foundation_gap_ids: tuple[str, ...]
    deferred_foundation_gap_ids: tuple[str, ...]
    next_foundation_action: str
    module_manifest_hash: str
    source_object_flow_manifest_hash: str
    work_item_manifest_hash: str
    foundation_gap_manifest_hash: str
    go_decision_allowed_at_capture: bool
    decision_record_created: bool = True
    human_confirmation_captured: bool = True
    pilot_admission_allowed: bool = False
    pilot_start_allowed: bool = False
    module_activation_executed: bool = False
    traffic_authorized: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str
    evidence_hash: str
    schema_version: str = MVP_PILOT_DECISION_RECORD_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_non_executing_record(self) -> Self:
        if (
            self.schema_version != MVP_PILOT_DECISION_RECORD_SCHEMA_VERSION
            or not self.decision_record_created
            or not self.human_confirmation_captured
            or self.pilot_admission_allowed
            or self.pilot_start_allowed
            or self.module_activation_executed
            or self.traffic_authorized
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("MVP pilot decision record violates the non-executing boundary")
        return self


def build_mvp_pilot_decision_command_hash(command: MvpPilotDecisionCommand) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_mvp_pilot_decision_record_hash(record: MvpPilotDecisionRecord) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class MvpPilotDecisionStore(Protocol):
    def append(self, record: MvpPilotDecisionRecord) -> MvpPilotDecisionRecord: ...

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> MvpPilotDecisionRecord | None: ...

    def latest(self, *, tenant_id: str) -> MvpPilotDecisionRecord | None: ...


class InMemoryMvpPilotDecisionStore:
    def __init__(self) -> None:
        self._records: list[MvpPilotDecisionRecord] = []

    def append(self, record: MvpPilotDecisionRecord) -> MvpPilotDecisionRecord:
        if build_mvp_pilot_decision_record_hash(record) != record.evidence_hash:
            raise ValueError("MVP pilot decision record hash is invalid")
        if any(
            existing.tenant_id == record.tenant_id
            and (
                existing.decision_id == record.decision_id
                or existing.idempotency_key_hash == record.idempotency_key_hash
            )
            for existing in self._records
        ):
            raise MvpPilotDecisionConflict("MVP pilot decision already exists")
        self._records.append(record)
        return record

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> MvpPilotDecisionRecord | None:
        return next(
            (
                record
                for record in reversed(self._records)
                if record.tenant_id == tenant_id and record.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def latest(self, *, tenant_id: str) -> MvpPilotDecisionRecord | None:
        return next((record for record in reversed(self._records) if record.tenant_id == tenant_id), None)


class PgMvpPilotDecisionStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: MvpPilotDecisionRecord) -> MvpPilotDecisionRecord:
        if build_mvp_pilot_decision_record_hash(record) != record.evidence_hash:
            raise ValueError("MVP pilot decision record hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.mvp_pilot_decision_records (
                        tenant_id, decision_id, decision_context_hash, go_no_go_decision,
                        decision_reason_hash, command_hash, idempotency_key_hash,
                        human_confirmation_statement_hash, human_confirmation_reference,
                        change_request_ref, decided_by, decided_at, confirmation_role_ids,
                        audit_event_id, audit_chain_ref, decision_record, evidence_hash, schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.decision_id,
                        record.decision_context_hash,
                        record.go_no_go_decision.value,
                        record.decision_reason_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.human_confirmation_reference,
                        record.change_request_ref,
                        record.decided_by,
                        record.decided_at,
                        Jsonb(list(record.confirmation_role_ids)),
                        record.audit_event_id,
                        record.audit_chain_ref,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise MvpPilotDecisionConflict("MVP pilot decision already exists") from exc
        return record

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        idempotency_key_hash: str,
    ) -> MvpPilotDecisionRecord | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            values=(idempotency_key_hash,),
        )

    def latest(self, *, tenant_id: str) -> MvpPilotDecisionRecord | None:
        return self._one(tenant_id=tenant_id, where_sql="TRUE", values=())

    def _one(
        self,
        *,
        tenant_id: str,
        where_sql: str,
        values: tuple[str, ...],
    ) -> MvpPilotDecisionRecord | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT decision_record
                FROM collabio.mvp_pilot_decision_records
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY decided_at DESC, created_at_utc DESC
                LIMIT 1
                """,
                (tenant_id, *values),
            ).fetchone()
        if row is None:
            return None
        record = MvpPilotDecisionRecord.model_validate(row[0])
        if build_mvp_pilot_decision_record_hash(record) != record.evidence_hash:
            raise ValueError("persisted MVP pilot decision record hash is invalid")
        return record


class MvpPilotDecisionService:
    def __init__(self, *, store: MvpPilotDecisionStore, audit_logger: InMemoryAuditLogger) -> None:
        self.store = store
        self.audit_logger = audit_logger

    def capture(
        self,
        *,
        user_context: UserContext,
        command: MvpPilotDecisionCommand,
        decision_context: MvpPilotDecisionContext,
    ) -> MvpPilotDecisionRecord:
        if user_context.role_ids.isdisjoint(ADMIN_ROLE_IDS):
            raise PermissionError("tenant admin role required")
        if command.tenant_id != user_context.tenant_id or decision_context.tenant_id != user_context.tenant_id:
            raise MvpPilotDecisionConflict("MVP pilot decision tenant does not match request context")
        if command.confirmed_by != user_context.user_id or decision_context.checked_by != user_context.user_id:
            raise PermissionError("MVP pilot decision actor does not match authenticated principal")
        submitted_roles = set(command.confirmation_role_ids)
        if not submitted_roles.issubset(user_context.role_ids) or submitted_roles.isdisjoint(ADMIN_ROLE_IDS):
            raise PermissionError("MVP pilot decision confirmation roles are not authorized")

        command_hash = build_mvp_pilot_decision_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "mvp_pilot_decision_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key": command.idempotency_key,
            }
        )
        existing = self.store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise MvpPilotDecisionConflict("MVP pilot decision idempotency key was used for another command")
            return existing.model_copy(update={"idempotent_replay": True})

        if build_mvp_pilot_decision_context_hash(decision_context) != decision_context.context_hash:
            raise MvpPilotDecisionConflict("authoritative MVP pilot decision context hash is invalid")
        if command.decision_context_hash != decision_context.context_hash:
            raise MvpPilotDecisionConflict("MVP pilot decision context changed; refresh before deciding")
        if command.go_no_go_decision is MvpPilotDecisionValue.GO and not decision_context.go_decision_allowed:
            raise MvpPilotDecisionConflict("GO is blocked by the authoritative MVP pilot decision context")

        decision_reason_hash = sha256_bytes(command.decision_reason.encode("utf-8"))
        confirmation_hash = sha256_bytes(command.human_confirmation_statement.encode("utf-8"))
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="platform.mvp_pilot_decision.capture_requested",
            metadata={
                "surface": "platform_api",
                "decision_id": command.decision_id,
                "decision_context_hash": decision_context.context_hash,
                "go_no_go_decision": command.go_no_go_decision.value,
                "decision_reason_hash": decision_reason_hash,
                "command_hash": command_hash,
                "idempotency_key_hash": idempotency_key_hash,
                "human_confirmation_statement_hash": confirmation_hash,
                "confirmation_role_ids": command.confirmation_role_ids,
                "go_decision_allowed": decision_context.go_decision_allowed,
                "pilot_start_allowed": False,
                "module_activation_executed": False,
                "external_side_effect_executed": False,
                "content_included": False,
            },
        )
        next_action = {
            MvpPilotDecisionValue.GO: "record_separate_productivity_pilot_admission_before_any_start",
            MvpPilotDecisionValue.NO_GO: "resolve_blockers_and_create_a_new_decision_context",
            MvpPilotDecisionValue.DEFER: "review_foundation_gaps_before_a_new_decision",
        }[command.go_no_go_decision]
        draft = MvpPilotDecisionRecord(
            tenant_id=user_context.tenant_id,
            decision_id=command.decision_id,
            decision_scope=decision_context.decision_scope,
            decision_context_hash=decision_context.context_hash,
            go_no_go_decision=command.go_no_go_decision,
            decision_reason_hash=decision_reason_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=confirmation_hash,
            human_confirmation_reference=command.human_confirmation_reference,
            change_request_ref=command.change_request_ref,
            decided_by=user_context.user_id,
            decided_at=datetime.now(UTC),
            confirmation_role_ids=command.confirmation_role_ids,
            audit_event_id=event.event_id,
            audit_chain_ref=f"audit:{event.event_id}",
            mvp_readiness_decision=decision_context.mvp_readiness_decision,
            module_gate_status=decision_context.module_gate_status,
            content_gate_status=decision_context.content_gate_status,
            backup_failover_gate_status=decision_context.backup_failover_gate_status,
            active_foundation_gap_ids=decision_context.active_foundation_gap_ids,
            ready_foundation_gap_ids=decision_context.ready_foundation_gap_ids,
            deferred_foundation_gap_ids=decision_context.deferred_foundation_gap_ids,
            next_foundation_action=decision_context.next_foundation_action,
            module_manifest_hash=decision_context.module_manifest_hash,
            source_object_flow_manifest_hash=decision_context.source_object_flow_manifest_hash,
            work_item_manifest_hash=decision_context.work_item_manifest_hash,
            foundation_gap_manifest_hash=decision_context.foundation_gap_manifest_hash,
            go_decision_allowed_at_capture=decision_context.go_decision_allowed,
            next_action=next_action,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_mvp_pilot_decision_record_hash(draft)})
        return self.store.append(record)

    def latest(self, *, tenant_id: str) -> MvpPilotDecisionRecord | None:
        return self.store.latest(tenant_id=tenant_id)


def build_default_mvp_pilot_decision_store(
    environ: Mapping[str, str] | None = None,
) -> MvpPilotDecisionStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_MVP_PILOT_DECISION_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryMvpPilotDecisionStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_MVP_PILOT_DECISION_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL MVP pilot decision store requires a database DSN")
        return PgMvpPilotDecisionStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported MVP pilot decision store backend: {backend}")
