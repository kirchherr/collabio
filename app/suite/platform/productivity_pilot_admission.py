from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import (
    ProductivityPilotPreflightGate,
    build_productivity_pilot_preflight_gate_hash,
    load_productivity_pilot_preflight_gate,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_ADMISSION_SCHEMA_VERSION = "productivity_pilot_admission_record.v1"
PRODUCTIVITY_PILOT_ADMISSION_CONFIRMATION_STATEMENT = (
    "I explicitly admit this tenant to the controlled productivity pilot pre-start boundary. "
    "This records approval only; it does not activate modules, enforce traffic scope, start the pilot, "
    "execute business writes, or permit destructive or external actions."
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ADMISSION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
ADMIN_ROLE_IDS = {"tenant-admin", "security-admin"}


class ProductivityPilotAdmissionConflict(ValueError):
    pass


class ProductivityPilotPreflightNotFound(LookupError):
    pass


class ProductivityPilotAdmissionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_id: str
    preflight_gate_hash: str
    policy_hash: str
    business_backend_release_gate_hash: str
    tenant_module_state_manifest_hash: str
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    monitoring_owner_ref: str
    rollback_owner_ref: str
    audit_chain_ref: str
    admitted_at_utc: datetime
    admission_requested: bool = True
    pilot_start_requested: bool = False
    tenant_state_mutation_requested: bool = False
    module_activation_requested: bool = False
    feature_mutation_requested: bool = False
    traffic_scope_enforcement_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("admission_id")
    @classmethod
    def require_admission_id(cls, value: str) -> str:
        if not ADMISSION_ID_PATTERN.fullmatch(value):
            raise ValueError("admission ID has an invalid format")
        return value

    @field_validator(
        "preflight_gate_hash",
        "policy_hash",
        "business_backend_release_gate_hash",
        "tenant_module_state_manifest_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot evidence hashes must use sha256")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "monitoring_owner_ref",
        "rollback_owner_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot admission references must be typed")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_ADMISSION_CONFIRMATION_STATEMENT:
            raise ValueError("exact productivity pilot admission confirmation statement required")
        return value

    @field_validator("admitted_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("admitted_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_non_executing_admission(self) -> Self:
        if (
            not self.admission_requested
            or self.pilot_start_requested
            or self.tenant_state_mutation_requested
            or self.module_activation_requested
            or self.feature_mutation_requested
            or self.traffic_scope_enforcement_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError("productivity pilot admission must remain non-executing and metadata-only")
        return self


class ProductivityPilotAdmissionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    admission_id: str
    preflight_gate_hash: str
    policy_hash: str
    business_backend_release_gate_hash: str
    tenant_module_state_manifest_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    monitoring_owner_ref: str
    rollback_owner_ref: str
    audit_chain_ref: str
    admitted_by: str
    admitted_at_utc: datetime
    preflight_ready: bool = True
    tenant_selected: bool = True
    human_confirmation_captured: bool = True
    admission_recorded: bool = True
    pilot_start_allowed: bool = False
    traffic_scope_enforced: bool = False
    tenant_state_changed: bool = False
    module_activation_executed: bool = False
    feature_state_changed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "enforce_pilot_traffic_scope_and_record_separate_start_authorization"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_ADMISSION_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_closed_record(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_ADMISSION_SCHEMA_VERSION
            or not self.preflight_ready
            or not self.tenant_selected
            or not self.human_confirmation_captured
            or not self.admission_recorded
            or self.pilot_start_allowed
            or self.traffic_scope_enforced
            or self.tenant_state_changed
            or self.module_activation_executed
            or self.feature_state_changed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("productivity pilot admission record violates the non-executing boundary")
        return self


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def build_productivity_pilot_admission_command_hash(command: ProductivityPilotAdmissionCommand) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_admission_record_hash(record: ProductivityPilotAdmissionRecord) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotPreflightStore(Protocol):
    def get(self, *, tenant_id: str, gate_hash: str) -> ProductivityPilotPreflightGate: ...


class InMemoryProductivityPilotPreflightStore:
    def __init__(self, gates: Iterable[ProductivityPilotPreflightGate] = ()) -> None:
        self._gates: dict[str, ProductivityPilotPreflightGate] = {}
        for gate in gates:
            self.add(gate)

    def add(self, gate: ProductivityPilotPreflightGate) -> ProductivityPilotPreflightGate:
        if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
            raise ValueError("productivity pilot preflight gate hash is invalid")
        self._gates[gate.gate_hash] = gate
        return gate

    def get(self, *, tenant_id: str, gate_hash: str) -> ProductivityPilotPreflightGate:
        gate = self._gates.get(gate_hash)
        if gate is None or tenant_id not in gate.candidate_tenant_ids:
            raise ProductivityPilotPreflightNotFound("authoritative productivity pilot preflight evidence not found")
        return gate


class PgProductivityPilotPreflightStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def get(self, *, tenant_id: str, gate_hash: str) -> ProductivityPilotPreflightGate:
        try:
            return load_productivity_pilot_preflight_gate(
                database_dsn=self.database_dsn,
                tenant_id=tenant_id,
                gate_hash=gate_hash,
            )
        except KeyError as exc:
            raise ProductivityPilotPreflightNotFound(str(exc)) from exc


class ProductivityPilotAdmissionRecordStore(Protocol):
    def append(self, record: ProductivityPilotAdmissionRecord) -> ProductivityPilotAdmissionRecord: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotAdmissionRecord | None: ...

    def for_preflight(self, *, tenant_id: str, preflight_gate_hash: str) -> ProductivityPilotAdmissionRecord | None: ...


class InMemoryProductivityPilotAdmissionRecordStore:
    def __init__(self, records: Iterable[ProductivityPilotAdmissionRecord] = ()) -> None:
        self._records: list[ProductivityPilotAdmissionRecord] = []
        for record in records:
            self.append(record)

    def append(self, record: ProductivityPilotAdmissionRecord) -> ProductivityPilotAdmissionRecord:
        if build_productivity_pilot_admission_record_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot admission record hash is invalid")
        if (
            self.for_idempotency(
                tenant_id=record.tenant_id,
                idempotency_key_hash=record.idempotency_key_hash,
            )
            is not None
        ):
            raise ProductivityPilotAdmissionConflict("productivity pilot admission idempotency key already exists")
        if (
            self.for_preflight(
                tenant_id=record.tenant_id,
                preflight_gate_hash=record.preflight_gate_hash,
            )
            is not None
        ):
            raise ProductivityPilotAdmissionConflict("tenant is already admitted for this productivity pilot preflight")
        self._records.append(record)
        return record

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotAdmissionRecord | None:
        return next(
            (
                record
                for record in reversed(self._records)
                if record.tenant_id == tenant_id and record.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def for_preflight(self, *, tenant_id: str, preflight_gate_hash: str) -> ProductivityPilotAdmissionRecord | None:
        return next(
            (
                record
                for record in reversed(self._records)
                if record.tenant_id == tenant_id and record.preflight_gate_hash == preflight_gate_hash
            ),
            None,
        )


class PgProductivityPilotAdmissionRecordStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: ProductivityPilotAdmissionRecord) -> ProductivityPilotAdmissionRecord:
        if build_productivity_pilot_admission_record_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot admission record hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_admission_records (
                        tenant_id, admission_id, preflight_gate_hash, policy_hash,
                        business_backend_release_gate_hash, tenant_module_state_manifest_hash,
                        command_hash, idempotency_key_hash, human_confirmation_statement_hash,
                        change_request_ref, human_confirmation_reference, monitoring_owner_ref,
                        rollback_owner_ref, audit_chain_ref, admitted_by, admitted_at_utc,
                        admission_record, evidence_hash, schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.admission_id,
                        record.preflight_gate_hash,
                        record.policy_hash,
                        record.business_backend_release_gate_hash,
                        record.tenant_module_state_manifest_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.change_request_ref,
                        record.human_confirmation_reference,
                        record.monitoring_owner_ref,
                        record.rollback_owner_ref,
                        record.audit_chain_ref,
                        record.admitted_by,
                        record.admitted_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotAdmissionConflict("productivity pilot admission already exists") from exc
        return record

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotAdmissionRecord | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            value=idempotency_key_hash,
        )

    def for_preflight(self, *, tenant_id: str, preflight_gate_hash: str) -> ProductivityPilotAdmissionRecord | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="preflight_gate_hash = %s",
            value=preflight_gate_hash,
        )

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotAdmissionRecord | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT admission_record
                FROM collabio.productivity_pilot_admission_records
                WHERE tenant_id = %s AND {where_sql}
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotAdmissionRecord.model_validate(row[0])
        if build_productivity_pilot_admission_record_hash(record) != record.evidence_hash:
            raise ValueError("persisted productivity pilot admission record hash is invalid")
        return record


class ProductivityPilotAdmissionService:
    def __init__(
        self,
        *,
        preflight_store: ProductivityPilotPreflightStore,
        record_store: ProductivityPilotAdmissionRecordStore,
    ) -> None:
        self.preflight_store = preflight_store
        self.record_store = record_store

    def admit(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotAdmissionCommand,
    ) -> ProductivityPilotAdmissionRecord:
        if user_context.role_ids.isdisjoint(ADMIN_ROLE_IDS):
            raise PermissionError("tenant admin role required")
        gate = self.preflight_store.get(
            tenant_id=user_context.tenant_id,
            gate_hash=command.preflight_gate_hash,
        )
        if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
            raise ProductivityPilotAdmissionConflict("authoritative productivity pilot preflight hash is invalid")
        if not gate.preflight_ready or user_context.tenant_id not in gate.candidate_tenant_ids:
            raise ProductivityPilotAdmissionConflict(
                "tenant is not ready in the authoritative productivity pilot preflight"
            )
        expected_hashes = {
            "policy_hash": gate.policy_hash,
            "business_backend_release_gate_hash": gate.business_backend_release_gate_hash,
            "tenant_module_state_manifest_hash": gate.tenant_module_state_manifest_hash,
        }
        for field_name, expected in expected_hashes.items():
            if getattr(command, field_name) != expected:
                raise ProductivityPilotAdmissionConflict(f"{field_name} does not match authoritative preflight")

        command_hash = build_productivity_pilot_admission_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_admission_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.record_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotAdmissionConflict(
                    "productivity pilot admission idempotency key was used for a different command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        if (
            self.record_store.for_preflight(
                tenant_id=user_context.tenant_id,
                preflight_gate_hash=gate.gate_hash,
            )
            is not None
        ):
            raise ProductivityPilotAdmissionConflict("tenant is already admitted for this productivity pilot preflight")

        draft = ProductivityPilotAdmissionRecord(
            tenant_id=user_context.tenant_id,
            admission_id=command.admission_id,
            preflight_gate_hash=gate.gate_hash,
            policy_hash=gate.policy_hash,
            business_backend_release_gate_hash=gate.business_backend_release_gate_hash,
            tenant_module_state_manifest_hash=gate.tenant_module_state_manifest_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            monitoring_owner_ref=command.monitoring_owner_ref,
            rollback_owner_ref=command.rollback_owner_ref,
            audit_chain_ref=command.audit_chain_ref,
            admitted_by=user_context.user_id,
            admitted_at_utc=command.admitted_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_admission_record_hash(draft)})
        return self.record_store.append(record)


def build_default_productivity_pilot_preflight_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotPreflightStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_PREFLIGHT_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotPreflightStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_PREFLIGHT_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot preflight store requires a database DSN")
        return PgProductivityPilotPreflightStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot preflight store backend: {backend}")


def build_default_productivity_pilot_admission_record_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotAdmissionRecordStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_ADMISSION_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotAdmissionRecordStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_ADMISSION_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot admission store requires a database DSN")
        return PgProductivityPilotAdmissionRecordStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot admission store backend: {backend}")
