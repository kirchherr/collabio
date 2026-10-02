from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import (
    API_OPERATION_PATTERN,
    ProductivityPilotPolicy,
    ProductivityPilotPreflightGate,
    build_productivity_pilot_policy_hash,
    build_productivity_pilot_preflight_gate_hash,
)
from suite.platform.productivity_pilot_admission import (
    ADMIN_ROLE_IDS,
    ProductivityPilotAdmissionConflict,
    ProductivityPilotAdmissionRecord,
    ProductivityPilotAdmissionRecordStore,
    ProductivityPilotPreflightStore,
    build_productivity_pilot_admission_record_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_SCHEMA_VERSION = "productivity_pilot_traffic_scope_enforcement.v1"
PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_CONFIRMATION_STATEMENT = (
    "I explicitly enforce tenant and route scope for this controlled productivity pilot. "
    "Default deny remains active; this does not authorize pilot start, business traffic, tenant or module changes, "
    "business writes, destructive actions, or external actions."
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ENFORCEMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


class ProductivityPilotTrafficScopeConflict(ValueError):
    pass


class ProductivityPilotTrafficScopeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enforcement_id: str
    admission_id: str
    admission_evidence_hash: str
    preflight_gate_hash: str
    policy_hash: str
    allowed_api_operations: tuple[str, ...]
    idempotency_key_ref: str
    change_request_ref: str
    ingress_policy_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    audit_chain_ref: str
    enforced_at_utc: datetime
    traffic_scope_enforcement_requested: bool = True
    default_deny_requested: bool = True
    pilot_start_requested: bool = False
    pilot_business_traffic_requested: bool = False
    tenant_state_mutation_requested: bool = False
    module_activation_requested: bool = False
    feature_mutation_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("enforcement_id", "admission_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not ENFORCEMENT_ID_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot traffic scope IDs have an invalid format")
        return value

    @field_validator("admission_evidence_hash", "preflight_gate_hash", "policy_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot traffic scope hashes must use sha256")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "ingress_policy_ref",
        "human_confirmation_reference",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot traffic scope references must be typed")
        return value

    @field_validator("allowed_api_operations")
    @classmethod
    def require_operations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed productivity pilot operations must be present and unique")
        if any(not API_OPERATION_PATTERN.fullmatch(item) for item in value):
            raise ValueError("allowed productivity pilot operations must use METHOD /v1/path format")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_CONFIRMATION_STATEMENT:
            raise ValueError("exact productivity pilot traffic scope confirmation statement required")
        return value

    @field_validator("enforced_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("enforced_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_prestart_default_deny(self) -> Self:
        if (
            not self.traffic_scope_enforcement_requested
            or not self.default_deny_requested
            or self.pilot_start_requested
            or self.pilot_business_traffic_requested
            or self.tenant_state_mutation_requested
            or self.module_activation_requested
            or self.feature_mutation_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError("productivity pilot traffic scope must remain pre-start, default-deny, and metadata-only")
        return self


class ProductivityPilotTrafficScopeEnforcement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    enforcement_id: str
    admission_id: str
    admission_evidence_hash: str
    preflight_gate_hash: str
    policy_hash: str
    allowed_api_operations: tuple[str, ...]
    route_scope_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    ingress_policy_ref: str
    human_confirmation_reference: str
    audit_chain_ref: str
    enforced_by: str
    enforced_at_utc: datetime
    tenant_scope_enforced: bool = True
    route_scope_enforced: bool = True
    default_deny_enabled: bool = True
    pilot_start_authorized: bool = False
    pilot_business_traffic_allowed: bool = False
    tenant_state_changed: bool = False
    module_activation_executed: bool = False
    feature_state_changed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "record_separate_productivity_pilot_start_authorization"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_enforced_prestart_boundary(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_SCHEMA_VERSION
            or not self.tenant_scope_enforced
            or not self.route_scope_enforced
            or not self.default_deny_enabled
            or self.pilot_start_authorized
            or self.pilot_business_traffic_allowed
            or self.tenant_state_changed
            or self.module_activation_executed
            or self.feature_state_changed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("productivity pilot traffic scope enforcement violates the pre-start boundary")
        return self


class ProductivityPilotTrafficDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    operation: str
    pilot_traffic_managed: bool
    operation_in_scope: bool
    tenant_scope_enforced: bool
    route_scope_enforced: bool
    default_deny_enabled: bool
    pilot_start_authorized: bool = False
    runtime_enablement_verified: bool = False
    authorization_allowed: bool
    blocking_reason: str | None = None
    enforcement_evidence_hash: str | None = None
    start_authorization_evidence_hash: str | None = None
    authorization_expires_at_utc: datetime | None = None
    http_status_code: int = Field(ge=200, le=599)
    content_included: bool = False
    schema_version: str = "productivity_pilot_traffic_decision.v1"

    @model_validator(mode="after")
    def require_consistent_decision(self) -> Self:
        if self.content_included:
            raise ValueError("productivity pilot traffic decision must remain metadata-only")
        if self.pilot_traffic_managed:
            if self.authorization_allowed:
                if (
                    not self.operation_in_scope
                    or not self.pilot_start_authorized
                    or not self.runtime_enablement_verified
                    or self.blocking_reason is not None
                    or self.start_authorization_evidence_hash is None
                    or self.authorization_expires_at_utc is None
                    or self.http_status_code != 200
                ):
                    raise ValueError("managed productivity pilot traffic requires an active start authorization")
            elif self.blocking_reason is None or self.http_status_code not in {403, 423}:
                raise ValueError("managed productivity pilot denial must remain fail-closed")
        elif (
            not self.authorization_allowed
            or self.blocking_reason is not None
            or self.pilot_start_authorized
            or self.runtime_enablement_verified
            or self.http_status_code != 200
        ):
            raise ValueError("unmanaged traffic must pass through without a pilot decision")
        return self


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def build_productivity_pilot_traffic_scope_command_hash(command: ProductivityPilotTrafficScopeCommand) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_route_scope_hash(
    *,
    tenant_id: str,
    admission_evidence_hash: str,
    preflight_gate_hash: str,
    policy_hash: str,
    allowed_api_operations: tuple[str, ...],
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_route_scope.v1",
            "tenant_id": tenant_id,
            "admission_evidence_hash": admission_evidence_hash,
            "preflight_gate_hash": preflight_gate_hash,
            "policy_hash": policy_hash,
            "allowed_api_operations": list(allowed_api_operations),
        }
    )


def build_productivity_pilot_traffic_scope_hash(record: ProductivityPilotTrafficScopeEnforcement) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotTrafficScopeStore(Protocol):
    def append(self, record: ProductivityPilotTrafficScopeEnforcement) -> ProductivityPilotTrafficScopeEnforcement: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotTrafficScopeEnforcement | None: ...

    def current(self, *, tenant_id: str) -> ProductivityPilotTrafficScopeEnforcement | None: ...


class InMemoryProductivityPilotTrafficScopeStore:
    def __init__(self, records: Iterable[ProductivityPilotTrafficScopeEnforcement] = ()) -> None:
        self._records: list[ProductivityPilotTrafficScopeEnforcement] = []
        for record in records:
            self.append(record)

    def append(self, record: ProductivityPilotTrafficScopeEnforcement) -> ProductivityPilotTrafficScopeEnforcement:
        if build_productivity_pilot_traffic_scope_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot traffic scope evidence hash is invalid")
        if (
            self.for_idempotency(
                tenant_id=record.tenant_id,
                idempotency_key_hash=record.idempotency_key_hash,
            )
            is not None
        ):
            raise ProductivityPilotTrafficScopeConflict("productivity pilot traffic scope idempotency key exists")
        if self.current(tenant_id=record.tenant_id) is not None:
            raise ProductivityPilotTrafficScopeConflict("productivity pilot traffic scope is already enforced")
        self._records.append(record)
        return record

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotTrafficScopeEnforcement | None:
        return next(
            (
                record
                for record in reversed(self._records)
                if record.tenant_id == tenant_id and record.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def current(self, *, tenant_id: str) -> ProductivityPilotTrafficScopeEnforcement | None:
        return next((record for record in reversed(self._records) if record.tenant_id == tenant_id), None)


class PgProductivityPilotTrafficScopeStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: ProductivityPilotTrafficScopeEnforcement) -> ProductivityPilotTrafficScopeEnforcement:
        if build_productivity_pilot_traffic_scope_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot traffic scope evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_traffic_scope_enforcements (
                        tenant_id, enforcement_id, admission_id, admission_evidence_hash,
                        preflight_gate_hash, policy_hash, route_scope_hash, allowed_api_operations,
                        command_hash, idempotency_key_hash, human_confirmation_statement_hash,
                        change_request_ref, ingress_policy_ref, human_confirmation_reference,
                        audit_chain_ref, enforced_by, enforced_at_utc, enforcement_record,
                        evidence_hash, schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.enforcement_id,
                        record.admission_id,
                        record.admission_evidence_hash,
                        record.preflight_gate_hash,
                        record.policy_hash,
                        record.route_scope_hash,
                        Jsonb(list(record.allowed_api_operations)),
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.change_request_ref,
                        record.ingress_policy_ref,
                        record.human_confirmation_reference,
                        record.audit_chain_ref,
                        record.enforced_by,
                        record.enforced_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotTrafficScopeConflict("productivity pilot traffic scope already exists") from exc
        return record

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotTrafficScopeEnforcement | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            value=idempotency_key_hash,
        )

    def current(self, *, tenant_id: str) -> ProductivityPilotTrafficScopeEnforcement | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotTrafficScopeEnforcement | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT enforcement_record
                FROM collabio.productivity_pilot_traffic_scope_enforcements
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY enforced_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotTrafficScopeEnforcement.model_validate(row[0])
        if build_productivity_pilot_traffic_scope_hash(record) != record.evidence_hash:
            raise ValueError("persisted productivity pilot traffic scope evidence hash is invalid")
        return record


class ProductivityPilotTrafficScopeService:
    def __init__(
        self,
        *,
        policy: ProductivityPilotPolicy,
        preflight_store: ProductivityPilotPreflightStore,
        admission_store: ProductivityPilotAdmissionRecordStore,
        traffic_scope_store: ProductivityPilotTrafficScopeStore,
    ) -> None:
        self.policy = policy
        self.preflight_store = preflight_store
        self.admission_store = admission_store
        self.traffic_scope_store = traffic_scope_store

    def enforce(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotTrafficScopeCommand,
    ) -> ProductivityPilotTrafficScopeEnforcement:
        if user_context.role_ids.isdisjoint(ADMIN_ROLE_IDS):
            raise PermissionError("tenant admin role required")
        gate = self.preflight_store.get(
            tenant_id=user_context.tenant_id,
            gate_hash=command.preflight_gate_hash,
        )
        self._validate_gate(gate)
        admission = self.admission_store.for_preflight(
            tenant_id=user_context.tenant_id,
            preflight_gate_hash=gate.gate_hash,
        )
        if admission is None:
            raise ProductivityPilotTrafficScopeConflict("authoritative productivity pilot admission not found")
        self._validate_admission(admission)
        expected_values = {
            "admission_id": admission.admission_id,
            "admission_evidence_hash": admission.evidence_hash,
            "preflight_gate_hash": admission.preflight_gate_hash,
            "policy_hash": admission.policy_hash,
        }
        for field_name, expected in expected_values.items():
            if getattr(command, field_name) != expected:
                raise ProductivityPilotTrafficScopeConflict(
                    f"{field_name} does not match authoritative productivity pilot admission"
                )
        if command.allowed_api_operations != self.policy.allowed_api_operations:
            raise ProductivityPilotTrafficScopeConflict(
                "allowed_api_operations do not exactly match the authoritative productivity pilot policy"
            )

        command_hash = build_productivity_pilot_traffic_scope_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_traffic_scope_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.traffic_scope_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotTrafficScopeConflict(
                    "productivity pilot traffic scope idempotency key was used for a different command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        if self.traffic_scope_store.current(tenant_id=user_context.tenant_id) is not None:
            raise ProductivityPilotTrafficScopeConflict("productivity pilot traffic scope is already enforced")

        route_scope_hash = build_productivity_pilot_route_scope_hash(
            tenant_id=user_context.tenant_id,
            admission_evidence_hash=admission.evidence_hash,
            preflight_gate_hash=gate.gate_hash,
            policy_hash=self.policy_hash,
            allowed_api_operations=command.allowed_api_operations,
        )
        draft = ProductivityPilotTrafficScopeEnforcement(
            tenant_id=user_context.tenant_id,
            enforcement_id=command.enforcement_id,
            admission_id=admission.admission_id,
            admission_evidence_hash=admission.evidence_hash,
            preflight_gate_hash=gate.gate_hash,
            policy_hash=self.policy_hash,
            allowed_api_operations=command.allowed_api_operations,
            route_scope_hash=route_scope_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            ingress_policy_ref=command.ingress_policy_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            audit_chain_ref=command.audit_chain_ref,
            enforced_by=user_context.user_id,
            enforced_at_utc=command.enforced_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_traffic_scope_hash(draft)})
        return self.traffic_scope_store.append(record)

    @property
    def policy_hash(self) -> str:
        return build_productivity_pilot_policy_hash(self.policy)

    def authorize_operation(self, *, tenant_id: str, operation: str) -> ProductivityPilotTrafficDecision:
        record = self.traffic_scope_store.current(tenant_id=tenant_id)
        if record is None:
            return ProductivityPilotTrafficDecision(
                tenant_id=tenant_id,
                operation=operation,
                pilot_traffic_managed=False,
                operation_in_scope=False,
                tenant_scope_enforced=False,
                route_scope_enforced=False,
                default_deny_enabled=False,
                authorization_allowed=True,
                http_status_code=200,
            )
        if build_productivity_pilot_traffic_scope_hash(record) != record.evidence_hash:
            raise ProductivityPilotTrafficScopeConflict(
                "persisted productivity pilot traffic scope evidence hash is invalid"
            )
        operation_in_scope = operation in record.allowed_api_operations
        return ProductivityPilotTrafficDecision(
            tenant_id=tenant_id,
            operation=operation,
            pilot_traffic_managed=True,
            operation_in_scope=operation_in_scope,
            tenant_scope_enforced=record.tenant_scope_enforced,
            route_scope_enforced=record.route_scope_enforced,
            default_deny_enabled=record.default_deny_enabled,
            authorization_allowed=False,
            blocking_reason=(
                "productivity_pilot_start_authorization_required"
                if operation_in_scope
                else "operation_outside_productivity_pilot_route_scope"
            ),
            enforcement_evidence_hash=record.evidence_hash,
            http_status_code=423 if operation_in_scope else 403,
        )

    def _validate_gate(self, gate: ProductivityPilotPreflightGate) -> None:
        if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
            raise ProductivityPilotTrafficScopeConflict("authoritative productivity pilot preflight hash is invalid")
        if not gate.preflight_ready or not gate.route_scope_contract_verified:
            raise ProductivityPilotTrafficScopeConflict(
                "authoritative productivity pilot preflight route scope is not ready"
            )
        if gate.policy_hash != self.policy_hash:
            raise ProductivityPilotTrafficScopeConflict(
                "authoritative productivity pilot policy hash does not match runtime policy"
            )

    @staticmethod
    def _validate_admission(admission: ProductivityPilotAdmissionRecord) -> None:
        if build_productivity_pilot_admission_record_hash(admission) != admission.evidence_hash:
            raise ProductivityPilotAdmissionConflict("authoritative productivity pilot admission hash is invalid")
        if not admission.admission_recorded or admission.pilot_start_allowed or admission.traffic_scope_enforced:
            raise ProductivityPilotTrafficScopeConflict(
                "authoritative productivity pilot admission is not at the traffic scope boundary"
            )


def build_default_productivity_pilot_traffic_scope_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotTrafficScopeStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotTrafficScopeStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot traffic scope store requires a database DSN")
        return PgProductivityPilotTrafficScopeStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot traffic scope store backend: {backend}")
