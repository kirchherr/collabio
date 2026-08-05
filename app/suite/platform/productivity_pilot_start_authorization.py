from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.operations.backup_failover import load_backup_failover_policy
from suite.operations.production_continuity_deployment_gate import (
    load_production_continuity_deployment_gate,
    production_continuity_deployment_gate_runtime_ready,
)
from suite.operations.productivity_pilot_preflight import (
    API_OPERATION_PATTERN,
    ProductivityPilotPolicy,
    ProductivityPilotPreflightGate,
    build_productivity_pilot_policy_hash,
    build_productivity_pilot_preflight_gate_hash,
)
from suite.platform.productivity_pilot_admission import (
    ProductivityPilotAdmissionRecord,
    ProductivityPilotAdmissionRecordStore,
    ProductivityPilotPreflightStore,
    build_productivity_pilot_admission_record_hash,
)
from suite.platform.productivity_pilot_traffic_scope import (
    ProductivityPilotTrafficDecision,
    ProductivityPilotTrafficScopeEnforcement,
    ProductivityPilotTrafficScopeStore,
    build_productivity_pilot_traffic_scope_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_START_AUTHORIZATION_SCHEMA_VERSION = "productivity_pilot_start_authorization.v1"
PRODUCTIVITY_PILOT_START_AUTHORIZATION_CONFIRMATION_STATEMENT = (
    "I explicitly authorize this controlled productivity pilot to start for the exact tenant, route scope, "
    "evidence set, and time window submitted. I confirm the monitoring and non-destructive rollback controls, "
    "accept automatic expiry and the deployment kill switch, and do not authorize routes outside scope, module or "
    "tenant mutation, destructive actions, or external actions."
)
MAX_PRODUCTIVITY_PILOT_START_DURATION = timedelta(hours=8)
MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW = timedelta(minutes=5)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
CONTROL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


class ProductivityPilotStartAuthorizationConflict(ValueError):
    pass


class ProductivityPilotControlEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    evidence_hash: str
    observed_at_utc: datetime
    valid_until_utc: datetime
    ready: bool = True
    content_included: bool = False

    @field_validator("control_id")
    @classmethod
    def require_control_id(cls, value: str) -> str:
        if not CONTROL_ID_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot control_id has an invalid format")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot control evidence must use sha256")
        return value

    @field_validator("observed_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("productivity pilot control evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_ready_metadata_only_evidence(self) -> Self:
        if not self.ready or self.content_included or self.valid_until_utc <= self.observed_at_utc:
            raise ValueError("productivity pilot control evidence must be ready, current, and metadata-only")
        return self


class ProductivityPilotStartAuthorizationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_id: str
    enforcement_id: str
    traffic_scope_evidence_hash: str
    route_scope_hash: str
    admission_evidence_hash: str
    preflight_gate_hash: str
    policy_hash: str
    allowed_api_operations: tuple[str, ...]
    monitoring_evidence: tuple[ProductivityPilotControlEvidence, ...]
    rollback_evidence: tuple[ProductivityPilotControlEvidence, ...]
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    security_approval_ref: str
    audit_chain_ref: str
    human_confirmation_statement: str
    authorized_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    start_authorization_requested: bool = True
    pilot_business_traffic_requested: bool = True
    runtime_enablement_required: bool = True
    tenant_state_mutation_requested: bool = False
    module_activation_requested: bool = False
    feature_mutation_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("authorization_id", "enforcement_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot start authorization IDs have an invalid format")
        return value

    @field_validator(
        "traffic_scope_evidence_hash",
        "route_scope_hash",
        "admission_evidence_hash",
        "preflight_gate_hash",
        "policy_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot start authorization hashes must use sha256")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "security_approval_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot start authorization references must be typed")
        return value

    @field_validator("allowed_api_operations")
    @classmethod
    def require_operations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed productivity pilot operations must be present and unique")
        if any(not API_OPERATION_PATTERN.fullmatch(item) for item in value):
            raise ValueError("allowed productivity pilot operations must use METHOD /v1/path format")
        return value

    @field_validator("monitoring_evidence", "rollback_evidence")
    @classmethod
    def require_unique_control_evidence(
        cls, value: tuple[ProductivityPilotControlEvidence, ...]
    ) -> tuple[ProductivityPilotControlEvidence, ...]:
        control_ids = [item.control_id for item in value]
        if not value or len(control_ids) != len(set(control_ids)):
            raise ValueError("productivity pilot control evidence must be present and unique")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_START_AUTHORIZATION_CONFIRMATION_STATEMENT:
            raise ValueError("exact productivity pilot start authorization confirmation statement required")
        return value

    @field_validator("authorized_at_utc", "effective_at_utc", "expires_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("productivity pilot start authorization timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_bounded_start_authorization(self) -> Self:
        duration = self.expires_at_utc - self.effective_at_utc
        if (
            not self.start_authorization_requested
            or not self.pilot_business_traffic_requested
            or not self.runtime_enablement_required
            or self.tenant_state_mutation_requested
            or self.module_activation_requested
            or self.feature_mutation_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
            or self.effective_at_utc < self.authorized_at_utc
            or duration <= timedelta(0)
            or duration > MAX_PRODUCTIVITY_PILOT_START_DURATION
        ):
            raise ValueError("productivity pilot start authorization must be bounded, explicit, and metadata-only")
        return self


class ProductivityPilotStartAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    authorization_id: str
    enforcement_id: str
    traffic_scope_evidence_hash: str
    route_scope_hash: str
    admission_evidence_hash: str
    preflight_gate_hash: str
    policy_hash: str
    allowed_api_operations: tuple[str, ...]
    monitoring_evidence: tuple[ProductivityPilotControlEvidence, ...]
    rollback_evidence: tuple[ProductivityPilotControlEvidence, ...]
    monitoring_evidence_manifest_hash: str
    rollback_evidence_manifest_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    security_approval_ref: str
    audit_chain_ref: str
    authorized_by: str
    authorized_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    four_eyes_verified: bool = True
    monitoring_controls_verified: bool = True
    rollback_controls_verified: bool = True
    runtime_enablement_verified: bool = True
    pilot_start_authorized: bool = True
    pilot_business_traffic_allowed: bool = True
    tenant_state_changed: bool = False
    module_activation_executed: bool = False
    feature_state_changed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "run_controlled_productivity_pilot_with_continuous_monitoring_and_automatic_expiry"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_START_AUTHORIZATION_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_safe_start_boundary(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_START_AUTHORIZATION_SCHEMA_VERSION
            or not self.four_eyes_verified
            or not self.monitoring_controls_verified
            or not self.rollback_controls_verified
            or not self.runtime_enablement_verified
            or not self.pilot_start_authorized
            or not self.pilot_business_traffic_allowed
            or self.tenant_state_changed
            or self.module_activation_executed
            or self.feature_state_changed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
            or self.expires_at_utc <= self.effective_at_utc
        ):
            raise ValueError("productivity pilot start authorization violates the controlled start boundary")
        return self


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def build_productivity_pilot_control_evidence_manifest_hash(
    evidence: tuple[ProductivityPilotControlEvidence, ...],
) -> str:
    return _canonical_hash(
        [item.model_dump(mode="json") for item in sorted(evidence, key=lambda item: item.control_id)]
    )


def build_productivity_pilot_start_authorization_command_hash(
    command: ProductivityPilotStartAuthorizationCommand,
) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_start_authorization_hash(record: ProductivityPilotStartAuthorization) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotStartAuthorizationStore(Protocol):
    def append(self, record: ProductivityPilotStartAuthorization) -> ProductivityPilotStartAuthorization: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotStartAuthorization | None: ...

    def current(self, *, tenant_id: str) -> ProductivityPilotStartAuthorization | None: ...


class InMemoryProductivityPilotStartAuthorizationStore:
    def __init__(self, records: Iterable[ProductivityPilotStartAuthorization] = ()) -> None:
        self._records: list[ProductivityPilotStartAuthorization] = []
        for record in records:
            self.append(record)

    def append(self, record: ProductivityPilotStartAuthorization) -> ProductivityPilotStartAuthorization:
        if build_productivity_pilot_start_authorization_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot start authorization evidence hash is invalid")
        if self.for_idempotency(tenant_id=record.tenant_id, idempotency_key_hash=record.idempotency_key_hash):
            raise ProductivityPilotStartAuthorizationConflict(
                "productivity pilot start authorization idempotency key already exists"
            )
        if any(
            item.tenant_id == record.tenant_id and item.authorization_id == record.authorization_id
            for item in self._records
        ):
            raise ProductivityPilotStartAuthorizationConflict("productivity pilot start authorization already exists")
        self._records.append(record)
        return record

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotStartAuthorization | None:
        return next(
            (
                record
                for record in reversed(self._records)
                if record.tenant_id == tenant_id and record.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def current(self, *, tenant_id: str) -> ProductivityPilotStartAuthorization | None:
        return next((record for record in reversed(self._records) if record.tenant_id == tenant_id), None)


class PgProductivityPilotStartAuthorizationStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: ProductivityPilotStartAuthorization) -> ProductivityPilotStartAuthorization:
        if build_productivity_pilot_start_authorization_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot start authorization evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_start_authorizations (
                        tenant_id, authorization_id, enforcement_id, traffic_scope_evidence_hash,
                        route_scope_hash, admission_evidence_hash, preflight_gate_hash, policy_hash,
                        allowed_api_operations, monitoring_evidence_manifest_hash,
                        rollback_evidence_manifest_hash, command_hash, idempotency_key_hash,
                        human_confirmation_statement_hash, change_request_ref,
                        human_confirmation_reference, security_approval_ref, audit_chain_ref,
                        authorized_by, authorized_at_utc, effective_at_utc, expires_at_utc,
                        authorization_record, evidence_hash, schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.authorization_id,
                        record.enforcement_id,
                        record.traffic_scope_evidence_hash,
                        record.route_scope_hash,
                        record.admission_evidence_hash,
                        record.preflight_gate_hash,
                        record.policy_hash,
                        Jsonb(list(record.allowed_api_operations)),
                        record.monitoring_evidence_manifest_hash,
                        record.rollback_evidence_manifest_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.change_request_ref,
                        record.human_confirmation_reference,
                        record.security_approval_ref,
                        record.audit_chain_ref,
                        record.authorized_by,
                        record.authorized_at_utc,
                        record.effective_at_utc,
                        record.expires_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotStartAuthorizationConflict(
                "productivity pilot start authorization already exists"
            ) from exc
        return record

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotStartAuthorization | None:
        return self._one(tenant_id=tenant_id, where_sql="idempotency_key_hash = %s", value=idempotency_key_hash)

    def current(self, *, tenant_id: str) -> ProductivityPilotStartAuthorization | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotStartAuthorization | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT authorization_record
                FROM collabio.productivity_pilot_start_authorizations
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY authorized_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotStartAuthorization.model_validate(row[0])
        if build_productivity_pilot_start_authorization_hash(record) != record.evidence_hash:
            raise ValueError("persisted productivity pilot start authorization evidence hash is invalid")
        return record


class ProductivityPilotStartAuthorizationService:
    def __init__(
        self,
        *,
        policy: ProductivityPilotPolicy,
        preflight_store: ProductivityPilotPreflightStore,
        admission_store: ProductivityPilotAdmissionRecordStore,
        traffic_scope_store: ProductivityPilotTrafficScopeStore,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        runtime_enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy
        self.preflight_store = preflight_store
        self.admission_store = admission_store
        self.traffic_scope_store = traffic_scope_store
        self.start_authorization_store = start_authorization_store
        self.runtime_enabled = runtime_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    @property
    def policy_hash(self) -> str:
        return build_productivity_pilot_policy_hash(self.policy)

    def authorize(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotStartAuthorizationCommand,
    ) -> ProductivityPilotStartAuthorization:
        if "security-admin" not in user_context.role_ids:
            raise PermissionError("security admin role required")
        if not self.runtime_enabled:
            raise ProductivityPilotStartAuthorizationConflict("productivity pilot runtime kill switch is closed")

        now = self._utc(self.clock())
        self._validate_window(command=command, now=now)
        traffic_scope = self.traffic_scope_store.current(tenant_id=user_context.tenant_id)
        if traffic_scope is None:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot traffic scope not found"
            )
        self._validate_traffic_scope(traffic_scope)
        gate = self.preflight_store.get(
            tenant_id=user_context.tenant_id,
            gate_hash=traffic_scope.preflight_gate_hash,
        )
        self._validate_gate(gate)
        admission = self.admission_store.for_preflight(
            tenant_id=user_context.tenant_id,
            preflight_gate_hash=gate.gate_hash,
        )
        if admission is None:
            raise ProductivityPilotStartAuthorizationConflict("authoritative productivity pilot admission not found")
        self._validate_admission(admission)
        self._validate_binding(command=command, traffic_scope=traffic_scope, gate=gate, admission=admission)
        if user_context.user_id in {admission.admitted_by, traffic_scope.enforced_by}:
            raise ProductivityPilotStartAuthorizationConflict(
                "four-eyes control requires a security admin distinct from admission and traffic enforcement actors"
            )
        self._validate_control_evidence(command)

        command_hash = build_productivity_pilot_start_authorization_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_start_authorization_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.start_authorization_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotStartAuthorizationConflict(
                    "productivity pilot start authorization idempotency key was used for a different command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        current = self.start_authorization_store.current(tenant_id=user_context.tenant_id)
        if current is not None and self._utc(current.expires_at_utc) > now:
            raise ProductivityPilotStartAuthorizationConflict(
                "an active productivity pilot start authorization already exists"
            )

        draft = ProductivityPilotStartAuthorization(
            tenant_id=user_context.tenant_id,
            authorization_id=command.authorization_id,
            enforcement_id=traffic_scope.enforcement_id,
            traffic_scope_evidence_hash=traffic_scope.evidence_hash,
            route_scope_hash=traffic_scope.route_scope_hash,
            admission_evidence_hash=admission.evidence_hash,
            preflight_gate_hash=gate.gate_hash,
            policy_hash=self.policy_hash,
            allowed_api_operations=command.allowed_api_operations,
            monitoring_evidence=command.monitoring_evidence,
            rollback_evidence=command.rollback_evidence,
            monitoring_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(
                command.monitoring_evidence
            ),
            rollback_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(
                command.rollback_evidence
            ),
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            security_approval_ref=command.security_approval_ref,
            audit_chain_ref=command.audit_chain_ref,
            authorized_by=user_context.user_id,
            authorized_at_utc=command.authorized_at_utc,
            effective_at_utc=command.effective_at_utc,
            expires_at_utc=command.expires_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_start_authorization_hash(draft)})
        return self.start_authorization_store.append(record)

    def authorize_operation(self, *, tenant_id: str, operation: str) -> ProductivityPilotTrafficDecision:
        traffic_scope = self.traffic_scope_store.current(tenant_id=tenant_id)
        if traffic_scope is None:
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
        self._validate_traffic_scope(traffic_scope)
        operation_in_scope = operation in traffic_scope.allowed_api_operations
        if not operation_in_scope:
            return self._denied_decision(
                traffic_scope=traffic_scope,
                operation=operation,
                blocking_reason="operation_outside_productivity_pilot_route_scope",
                status_code=403,
            )
        start = self.start_authorization_store.current(tenant_id=tenant_id)
        if start is None:
            return self._denied_decision(
                traffic_scope=traffic_scope,
                operation=operation,
                blocking_reason="productivity_pilot_start_authorization_required",
                status_code=423,
            )
        self._validate_start_authorization(start=start, traffic_scope=traffic_scope)
        now = self._utc(self.clock())
        if not self.runtime_enabled:
            return self._denied_decision(
                traffic_scope=traffic_scope,
                operation=operation,
                blocking_reason="productivity_pilot_runtime_disabled",
                status_code=423,
                start=start,
            )
        if now < self._utc(start.effective_at_utc):
            return self._denied_decision(
                traffic_scope=traffic_scope,
                operation=operation,
                blocking_reason="productivity_pilot_start_authorization_not_effective",
                status_code=423,
                start=start,
            )
        if now >= self._utc(start.expires_at_utc):
            return self._denied_decision(
                traffic_scope=traffic_scope,
                operation=operation,
                blocking_reason="productivity_pilot_start_authorization_expired",
                status_code=423,
                start=start,
            )
        return ProductivityPilotTrafficDecision(
            tenant_id=tenant_id,
            operation=operation,
            pilot_traffic_managed=True,
            operation_in_scope=True,
            tenant_scope_enforced=True,
            route_scope_enforced=True,
            default_deny_enabled=True,
            pilot_start_authorized=True,
            runtime_enablement_verified=True,
            authorization_allowed=True,
            enforcement_evidence_hash=traffic_scope.evidence_hash,
            start_authorization_evidence_hash=start.evidence_hash,
            authorization_expires_at_utc=start.expires_at_utc,
            http_status_code=200,
        )

    def _validate_binding(
        self,
        *,
        command: ProductivityPilotStartAuthorizationCommand,
        traffic_scope: ProductivityPilotTrafficScopeEnforcement,
        gate: ProductivityPilotPreflightGate,
        admission: ProductivityPilotAdmissionRecord,
    ) -> None:
        expected_values = {
            "enforcement_id": traffic_scope.enforcement_id,
            "traffic_scope_evidence_hash": traffic_scope.evidence_hash,
            "route_scope_hash": traffic_scope.route_scope_hash,
            "admission_evidence_hash": admission.evidence_hash,
            "preflight_gate_hash": gate.gate_hash,
            "policy_hash": self.policy_hash,
            "allowed_api_operations": self.policy.allowed_api_operations,
        }
        for field_name, expected in expected_values.items():
            if getattr(command, field_name) != expected:
                raise ProductivityPilotStartAuthorizationConflict(
                    f"{field_name} does not match authoritative productivity pilot evidence"
                )

    def _validate_control_evidence(self, command: ProductivityPilotStartAuthorizationCommand) -> None:
        expected_monitoring = {item.control_id for item in self.policy.monitoring_controls}
        expected_rollback = {item.control_id for item in self.policy.rollback_controls}
        provided_monitoring = {item.control_id for item in command.monitoring_evidence}
        provided_rollback = {item.control_id for item in command.rollback_evidence}
        if provided_monitoring != expected_monitoring:
            raise ProductivityPilotStartAuthorizationConflict(
                "monitoring evidence does not exactly match the authoritative productivity pilot policy"
            )
        if provided_rollback != expected_rollback:
            raise ProductivityPilotStartAuthorizationConflict(
                "rollback evidence does not exactly match the authoritative productivity pilot policy"
            )
        for evidence in (*command.monitoring_evidence, *command.rollback_evidence):
            if self._utc(evidence.observed_at_utc) > self._utc(command.authorized_at_utc):
                raise ProductivityPilotStartAuthorizationConflict(
                    "productivity pilot control evidence was observed after authorization"
                )
            if self._utc(evidence.valid_until_utc) < self._utc(command.expires_at_utc):
                raise ProductivityPilotStartAuthorizationConflict(
                    "productivity pilot control evidence does not cover the full authorization window"
                )

    def _validate_window(self, *, command: ProductivityPilotStartAuthorizationCommand, now: datetime) -> None:
        authorized_at = self._utc(command.authorized_at_utc)
        effective_at = self._utc(command.effective_at_utc)
        expires_at = self._utc(command.expires_at_utc)
        if abs(now - authorized_at) > MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW:
            raise ProductivityPilotStartAuthorizationConflict(
                "productivity pilot start authorization timestamp is outside the allowed clock skew"
            )
        if effective_at > now + MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW or expires_at <= now:
            raise ProductivityPilotStartAuthorizationConflict(
                "productivity pilot start authorization window is not currently admissible"
            )

    def _validate_gate(self, gate: ProductivityPilotPreflightGate) -> None:
        if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot preflight hash is invalid"
            )
        if (
            not gate.preflight_ready
            or not gate.route_scope_contract_verified
            or not gate.monitoring_contract_verified
            or not gate.rollback_contract_verified
            or gate.policy_hash != self.policy_hash
        ):
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot preflight is not start-ready"
            )

    @staticmethod
    def _validate_admission(admission: ProductivityPilotAdmissionRecord) -> None:
        if build_productivity_pilot_admission_record_hash(admission) != admission.evidence_hash:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot admission hash is invalid"
            )
        if not admission.admission_recorded or admission.pilot_start_allowed:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot admission is not at the start authorization boundary"
            )

    def _validate_traffic_scope(self, traffic_scope: ProductivityPilotTrafficScopeEnforcement) -> None:
        if build_productivity_pilot_traffic_scope_hash(traffic_scope) != traffic_scope.evidence_hash:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot traffic scope hash is invalid"
            )
        if (
            traffic_scope.policy_hash != self.policy_hash
            or traffic_scope.allowed_api_operations != self.policy.allowed_api_operations
            or not traffic_scope.default_deny_enabled
            or traffic_scope.pilot_start_authorized
        ):
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot traffic scope is not at the start authorization boundary"
            )

    @staticmethod
    def _validate_start_authorization(
        *,
        start: ProductivityPilotStartAuthorization,
        traffic_scope: ProductivityPilotTrafficScopeEnforcement,
    ) -> None:
        if build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash:
            raise ProductivityPilotStartAuthorizationConflict(
                "authoritative productivity pilot start authorization hash is invalid"
            )
        if (
            start.traffic_scope_evidence_hash != traffic_scope.evidence_hash
            or start.route_scope_hash != traffic_scope.route_scope_hash
            or start.allowed_api_operations != traffic_scope.allowed_api_operations
        ):
            raise ProductivityPilotStartAuthorizationConflict(
                "productivity pilot start authorization no longer matches the traffic scope"
            )

    @staticmethod
    def _denied_decision(
        *,
        traffic_scope: ProductivityPilotTrafficScopeEnforcement,
        operation: str,
        blocking_reason: str,
        status_code: int,
        start: ProductivityPilotStartAuthorization | None = None,
    ) -> ProductivityPilotTrafficDecision:
        return ProductivityPilotTrafficDecision(
            tenant_id=traffic_scope.tenant_id,
            operation=operation,
            pilot_traffic_managed=True,
            operation_in_scope=operation in traffic_scope.allowed_api_operations,
            tenant_scope_enforced=traffic_scope.tenant_scope_enforced,
            route_scope_enforced=traffic_scope.route_scope_enforced,
            default_deny_enabled=traffic_scope.default_deny_enabled,
            pilot_start_authorized=start is not None,
            runtime_enablement_verified=False,
            authorization_allowed=False,
            blocking_reason=blocking_reason,
            enforcement_evidence_hash=traffic_scope.evidence_hash,
            start_authorization_evidence_hash=start.evidence_hash if start else None,
            authorization_expires_at_utc=start.expires_at_utc if start else None,
            http_status_code=status_code,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProductivityPilotStartAuthorizationConflict("productivity pilot timestamp must include a timezone")
        return value.astimezone(UTC)


def build_default_productivity_pilot_start_authorization_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotStartAuthorizationStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotStartAuthorizationStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot start authorization store requires a database DSN")
        return PgProductivityPilotStartAuthorizationStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot start authorization store backend: {backend}")


def productivity_pilot_runtime_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    requested = env.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not requested:
        return False
    report_path = env.get("SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH", "").strip()
    if not report_path:
        return False
    policy_path = env.get(
        "SUITE_BACKUP_FAILOVER_POLICY_PATH",
        "/workspace/docs/operations/backup_failover_policy.json",
    ).strip()
    try:
        gate = load_production_continuity_deployment_gate(Path(report_path))
        policy = load_backup_failover_policy(Path(policy_path))
    except (OSError, ValueError):
        return False
    return production_continuity_deployment_gate_runtime_ready(gate=gate, policy=policy)
