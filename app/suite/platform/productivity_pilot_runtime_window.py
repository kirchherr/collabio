from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, Self
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_start_authorization import (
    MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW,
    ProductivityPilotStartAuthorization,
    ProductivityPilotStartAuthorizationStore,
    build_productivity_pilot_start_authorization_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_RUNTIME_WINDOW_SCHEMA_VERSION = "productivity_pilot_runtime_window.v1"
PRODUCTIVITY_PILOT_RUNTIME_OBSERVATION_SCHEMA_VERSION = "productivity_pilot_runtime_observation.v1"
PRODUCTIVITY_PILOT_RUNTIME_WINDOW_CONFIRMATION_STATEMENT = (
    "I explicitly activate this controlled productivity pilot runtime window for only the designated principals, "
    "authorized operations, evidence-bound tenant, and submitted time window. I confirm that all other principals "
    "remain blocked, observations are metadata-only, the deployment kill switch remains authoritative, and no "
    "additional module, destructive, or external action is authorized."
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
OPERATION_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_./{}-]+$")
MAX_DESIGNATED_PILOT_PRINCIPALS = 25


class ProductivityPilotRuntimeWindowConflict(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _validate_principal_id(value: str) -> str:
    if not value or value != value.strip() or len(value) > 255 or any(ord(character) < 32 for character in value):
        raise ValueError("designated productivity pilot principal ID has an invalid format")
    return value


class ProductivityPilotRuntimeWindowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    authorization_id: str
    start_authorization_evidence_hash: str
    designated_principal_ids: tuple[str, ...]
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    audit_chain_ref: str
    human_confirmation_statement: str
    activated_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    runtime_window_requested: bool = True
    business_write_requested: bool = False
    module_activation_requested: bool = False
    feature_mutation_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("window_id", "authorization_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot runtime window IDs have an invalid format")
        return value

    @field_validator("start_authorization_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot runtime window hash must use sha256")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "operations_owner_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot runtime window references must be typed")
        return value

    @field_validator("designated_principal_ids")
    @classmethod
    def require_designated_principals(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > MAX_DESIGNATED_PILOT_PRINCIPALS or len(value) != len(set(value)):
            raise ValueError("designated productivity pilot principals must be present, unique, and bounded")
        for principal_id in value:
            _validate_principal_id(principal_id)
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_RUNTIME_WINDOW_CONFIRMATION_STATEMENT:
            raise ValueError("exact productivity pilot runtime window confirmation statement required")
        return value

    @field_validator("activated_at_utc", "effective_at_utc", "expires_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("productivity pilot runtime window timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_safe_activation_request(self) -> Self:
        if (
            not self.runtime_window_requested
            or self.business_write_requested
            or self.module_activation_requested
            or self.feature_mutation_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
            or self.effective_at_utc < self.activated_at_utc
            or self.expires_at_utc <= self.effective_at_utc
        ):
            raise ValueError("productivity pilot runtime window request must remain bounded and metadata-only")
        return self


class ProductivityPilotRuntimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    window_id: str
    authorization_id: str
    start_authorization_evidence_hash: str
    designated_principal_ids: tuple[str, ...]
    designated_principal_manifest_hash: str
    allowed_api_operations: tuple[str, ...]
    route_scope_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    audit_chain_ref: str
    activated_by: str
    activated_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    designated_principals_enforced: bool = True
    route_scope_enforced: bool = True
    observation_ledger_enabled: bool = True
    runtime_window_active: bool = True
    business_write_executed: bool = False
    module_activation_executed: bool = False
    feature_state_changed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "observe_designated_pilot_principals_and_close_kill_switch_after_window"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_RUNTIME_WINDOW_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_safe_runtime_window(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_RUNTIME_WINDOW_SCHEMA_VERSION
            or not self.designated_principal_ids
            or not self.allowed_api_operations
            or not self.designated_principals_enforced
            or not self.route_scope_enforced
            or not self.observation_ledger_enabled
            or not self.runtime_window_active
            or self.business_write_executed
            or self.module_activation_executed
            or self.feature_state_changed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
            or self.expires_at_utc <= self.effective_at_utc
        ):
            raise ValueError("productivity pilot runtime window violates the controlled observation boundary")
        return self


class ProductivityPilotRuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    observation_id: str
    window_id: str
    authorization_id: str
    start_authorization_evidence_hash: str
    window_evidence_hash: str
    principal_id_hash: str
    operation: str
    observed_at_utc: datetime
    authorization_allowed: bool = True
    designated_principal_verified: bool = True
    route_scope_verified: bool = True
    response_payload_observed: bool = False
    business_payload_persisted: bool = False
    content_included: bool = False
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_RUNTIME_OBSERVATION_SCHEMA_VERSION

    @field_validator("start_authorization_evidence_hash", "window_evidence_hash", "principal_id_hash", "evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot runtime observation hashes must use sha256")
        return value

    @field_validator("operation")
    @classmethod
    def require_operation(cls, value: str) -> str:
        if not OPERATION_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot runtime observation operation has an invalid format")
        return value

    @model_validator(mode="after")
    def require_metadata_only_authorization_observation(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_RUNTIME_OBSERVATION_SCHEMA_VERSION
            or not self.authorization_allowed
            or not self.designated_principal_verified
            or not self.route_scope_verified
            or self.response_payload_observed
            or self.business_payload_persisted
            or self.content_included
        ):
            raise ValueError("productivity pilot runtime observation must be authorized and metadata-only")
        return self


class ProductivityPilotRuntimeAccessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    operation: str
    authorization_allowed: bool
    designated_principal_verified: bool = False
    runtime_window_verified: bool = False
    blocking_reason: str | None = None
    http_status_code: int
    window_evidence_hash: str | None = None
    observation_evidence_hash: str | None = None
    content_included: bool = False


def build_productivity_pilot_designated_principal_manifest_hash(
    *, tenant_id: str, designated_principal_ids: tuple[str, ...]
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_designated_principal_manifest.v1",
            "tenant_id": tenant_id,
            "designated_principal_ids": sorted(designated_principal_ids),
        }
    )


def build_productivity_pilot_runtime_window_command_hash(command: ProductivityPilotRuntimeWindowCommand) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_runtime_window_hash(record: ProductivityPilotRuntimeWindow) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


def build_productivity_pilot_runtime_observation_hash(record: ProductivityPilotRuntimeObservation) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash"}))


class ProductivityPilotRuntimeWindowStore(Protocol):
    def append_window(self, record: ProductivityPilotRuntimeWindow) -> ProductivityPilotRuntimeWindow: ...

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRuntimeWindow | None: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRuntimeWindow | None: ...

    def append_observation(
        self, record: ProductivityPilotRuntimeObservation
    ) -> ProductivityPilotRuntimeObservation: ...


class InMemoryProductivityPilotRuntimeWindowStore:
    def __init__(
        self,
        windows: Iterable[ProductivityPilotRuntimeWindow] = (),
        observations: Iterable[ProductivityPilotRuntimeObservation] = (),
    ) -> None:
        self.windows: list[ProductivityPilotRuntimeWindow] = []
        self.observations: list[ProductivityPilotRuntimeObservation] = []
        for window in windows:
            self.append_window(window)
        for observation in observations:
            self.append_observation(observation)

    def append_window(self, record: ProductivityPilotRuntimeWindow) -> ProductivityPilotRuntimeWindow:
        if build_productivity_pilot_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot runtime window evidence hash is invalid")
        if self.for_idempotency(tenant_id=record.tenant_id, idempotency_key_hash=record.idempotency_key_hash):
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime window idempotency key exists")
        if any(item.tenant_id == record.tenant_id and item.window_id == record.window_id for item in self.windows):
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime window already exists")
        self.windows.append(record)
        return record

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRuntimeWindow | None:
        return next((item for item in reversed(self.windows) if item.tenant_id == tenant_id), None)

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotRuntimeWindow | None:
        return next(
            (
                item
                for item in reversed(self.windows)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def append_observation(self, record: ProductivityPilotRuntimeObservation) -> ProductivityPilotRuntimeObservation:
        if build_productivity_pilot_runtime_observation_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot runtime observation evidence hash is invalid")
        if any(
            item.tenant_id == record.tenant_id and item.observation_id == record.observation_id
            for item in self.observations
        ):
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime observation already exists")
        self.observations.append(record)
        return record


class PgProductivityPilotRuntimeWindowStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append_window(self, record: ProductivityPilotRuntimeWindow) -> ProductivityPilotRuntimeWindow:
        if build_productivity_pilot_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot runtime window evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_runtime_windows (
                        tenant_id, window_id, authorization_id, start_authorization_evidence_hash,
                        designated_principal_ids, designated_principal_manifest_hash,
                        allowed_api_operations, route_scope_hash, command_hash, idempotency_key_hash,
                        human_confirmation_statement_hash, change_request_ref,
                        human_confirmation_reference, operations_owner_ref, audit_chain_ref,
                        activated_by, activated_at_utc, effective_at_utc, expires_at_utc,
                        window_record, evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.window_id,
                        record.authorization_id,
                        record.start_authorization_evidence_hash,
                        Jsonb(list(record.designated_principal_ids)),
                        record.designated_principal_manifest_hash,
                        Jsonb(list(record.allowed_api_operations)),
                        record.route_scope_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.change_request_ref,
                        record.human_confirmation_reference,
                        record.operations_owner_ref,
                        record.audit_chain_ref,
                        record.activated_by,
                        record.activated_at_utc,
                        record.effective_at_utc,
                        record.expires_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime window already exists") from exc
        return record

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRuntimeWindow | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotRuntimeWindow | None:
        return self._one(tenant_id=tenant_id, where_sql="idempotency_key_hash = %s", value=idempotency_key_hash)

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotRuntimeWindow | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT window_record
                FROM collabio.productivity_pilot_runtime_windows
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY activated_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotRuntimeWindow.model_validate(row[0])
        if build_productivity_pilot_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("persisted productivity pilot runtime window evidence hash is invalid")
        return record

    def append_observation(self, record: ProductivityPilotRuntimeObservation) -> ProductivityPilotRuntimeObservation:
        if build_productivity_pilot_runtime_observation_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot runtime observation evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_runtime_observations (
                        tenant_id, observation_id, window_id, authorization_id,
                        start_authorization_evidence_hash, window_evidence_hash,
                        principal_id_hash, operation, observed_at_utc,
                        observation_record, evidence_hash, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.tenant_id,
                        record.observation_id,
                        record.window_id,
                        record.authorization_id,
                        record.start_authorization_evidence_hash,
                        record.window_evidence_hash,
                        record.principal_id_hash,
                        record.operation,
                        record.observed_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRuntimeWindowConflict(
                "productivity pilot runtime observation already exists"
            ) from exc
        return record


class ProductivityPilotRuntimeWindowService:
    def __init__(
        self,
        *,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        runtime_window_store: ProductivityPilotRuntimeWindowStore,
        runtime_enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.start_authorization_store = start_authorization_store
        self.runtime_window_store = runtime_window_store
        self.runtime_enabled = runtime_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    def activate(
        self, *, user_context: UserContext, command: ProductivityPilotRuntimeWindowCommand
    ) -> ProductivityPilotRuntimeWindow:
        if "tenant-admin" not in user_context.role_ids:
            raise PermissionError("tenant admin role required")
        if not self.runtime_enabled:
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime kill switch is closed")
        now = self._utc(self.clock())
        start = self.start_authorization_store.current(tenant_id=user_context.tenant_id)
        if start is None:
            raise ProductivityPilotRuntimeWindowConflict(
                "authoritative productivity pilot start authorization not found"
            )
        self._validate_start(start)
        self._validate_command_binding(command=command, start=start, now=now)
        if user_context.user_id == start.authorized_by:
            raise ProductivityPilotRuntimeWindowConflict(
                "four-eyes control requires a runtime operator distinct from the security authorizer"
            )
        if user_context.user_id in command.designated_principal_ids:
            raise ProductivityPilotRuntimeWindowConflict("runtime operator cannot be a designated pilot principal")

        command_hash = build_productivity_pilot_runtime_window_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_runtime_window_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.runtime_window_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotRuntimeWindowConflict(
                    "productivity pilot runtime window idempotency key was used for a different command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        current = self.runtime_window_store.current_window(tenant_id=user_context.tenant_id)
        if current is not None and self._utc(current.expires_at_utc) > now:
            raise ProductivityPilotRuntimeWindowConflict("an active productivity pilot runtime window already exists")

        draft = ProductivityPilotRuntimeWindow(
            tenant_id=user_context.tenant_id,
            window_id=command.window_id,
            authorization_id=start.authorization_id,
            start_authorization_evidence_hash=start.evidence_hash,
            designated_principal_ids=command.designated_principal_ids,
            designated_principal_manifest_hash=build_productivity_pilot_designated_principal_manifest_hash(
                tenant_id=user_context.tenant_id,
                designated_principal_ids=command.designated_principal_ids,
            ),
            allowed_api_operations=start.allowed_api_operations,
            route_scope_hash=start.route_scope_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            operations_owner_ref=command.operations_owner_ref,
            audit_chain_ref=command.audit_chain_ref,
            activated_by=user_context.user_id,
            activated_at_utc=command.activated_at_utc,
            effective_at_utc=command.effective_at_utc,
            expires_at_utc=command.expires_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_runtime_window_hash(draft)})
        return self.runtime_window_store.append_window(record)

    def authorize_operation(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        operation: str,
        start_authorization_evidence_hash: str,
    ) -> ProductivityPilotRuntimeAccessDecision:
        window = self.runtime_window_store.current_window(tenant_id=tenant_id)
        if window is None:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="productivity_pilot_runtime_window_required",
                status_code=423,
            )
        self._validate_window(window)
        start = self.start_authorization_store.current(tenant_id=tenant_id)
        if start is None:
            raise ProductivityPilotRuntimeWindowConflict(
                "authoritative productivity pilot start authorization not found"
            )
        self._validate_start(start)
        if (
            start.evidence_hash != start_authorization_evidence_hash
            or window.start_authorization_evidence_hash != start.evidence_hash
            or window.authorization_id != start.authorization_id
        ):
            raise ProductivityPilotRuntimeWindowConflict(
                "productivity pilot runtime window no longer matches the start authorization"
            )
        now = self._utc(self.clock())
        if not self.runtime_enabled:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="productivity_pilot_runtime_disabled",
                status_code=423,
                window=window,
            )
        if now < self._utc(window.effective_at_utc):
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="productivity_pilot_runtime_window_not_effective",
                status_code=423,
                window=window,
            )
        if now >= self._utc(window.expires_at_utc):
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="productivity_pilot_runtime_window_expired",
                status_code=423,
                window=window,
            )
        if operation not in window.allowed_api_operations:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="operation_outside_productivity_pilot_runtime_window",
                status_code=403,
                window=window,
            )
        if principal_id not in window.designated_principal_ids:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="principal_not_designated_for_productivity_pilot",
                status_code=403,
                window=window,
            )
        principal_id_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_principal_observation.v1",
                "tenant_id": tenant_id,
                "principal_id": principal_id,
            }
        )
        draft = ProductivityPilotRuntimeObservation(
            tenant_id=tenant_id,
            observation_id=f"pilot-observation-{uuid4().hex}",
            window_id=window.window_id,
            authorization_id=start.authorization_id,
            start_authorization_evidence_hash=start.evidence_hash,
            window_evidence_hash=window.evidence_hash,
            principal_id_hash=principal_id_hash,
            operation=operation,
            observed_at_utc=now,
            evidence_hash="sha256:" + "0" * 64,
        )
        observation = draft.model_copy(
            update={"evidence_hash": build_productivity_pilot_runtime_observation_hash(draft)}
        )
        observation = self.runtime_window_store.append_observation(observation)
        return ProductivityPilotRuntimeAccessDecision(
            tenant_id=tenant_id,
            operation=operation,
            authorization_allowed=True,
            designated_principal_verified=True,
            runtime_window_verified=True,
            http_status_code=200,
            window_evidence_hash=window.evidence_hash,
            observation_evidence_hash=observation.evidence_hash,
        )

    def current(self, *, tenant_id: str) -> ProductivityPilotRuntimeWindow | None:
        window = self.runtime_window_store.current_window(tenant_id=tenant_id)
        if window is not None:
            self._validate_window(window)
        return window

    def _validate_command_binding(
        self,
        *,
        command: ProductivityPilotRuntimeWindowCommand,
        start: ProductivityPilotStartAuthorization,
        now: datetime,
    ) -> None:
        if command.authorization_id != start.authorization_id:
            raise ProductivityPilotRuntimeWindowConflict(
                "authorization_id does not match authoritative productivity pilot start authorization"
            )
        if command.start_authorization_evidence_hash != start.evidence_hash:
            raise ProductivityPilotRuntimeWindowConflict(
                "start_authorization_evidence_hash does not match authoritative productivity pilot evidence"
            )
        activated_at = self._utc(command.activated_at_utc)
        effective_at = self._utc(command.effective_at_utc)
        expires_at = self._utc(command.expires_at_utc)
        if abs(now - activated_at) > MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW:
            raise ProductivityPilotRuntimeWindowConflict(
                "productivity pilot runtime window timestamp is outside the allowed clock skew"
            )
        if effective_at < self._utc(start.effective_at_utc) or expires_at > self._utc(start.expires_at_utc):
            raise ProductivityPilotRuntimeWindowConflict(
                "productivity pilot runtime window must remain inside the start authorization window"
            )
        if expires_at <= now:
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot runtime window is already expired")

    @staticmethod
    def _validate_start(start: ProductivityPilotStartAuthorization) -> None:
        if build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash:
            raise ProductivityPilotRuntimeWindowConflict(
                "authoritative productivity pilot start authorization hash is invalid"
            )

    @staticmethod
    def _validate_window(window: ProductivityPilotRuntimeWindow) -> None:
        if build_productivity_pilot_runtime_window_hash(window) != window.evidence_hash:
            raise ProductivityPilotRuntimeWindowConflict(
                "authoritative productivity pilot runtime window hash is invalid"
            )

    @staticmethod
    def _denied(
        *,
        tenant_id: str,
        operation: str,
        reason: str,
        status_code: int,
        window: ProductivityPilotRuntimeWindow | None = None,
    ) -> ProductivityPilotRuntimeAccessDecision:
        return ProductivityPilotRuntimeAccessDecision(
            tenant_id=tenant_id,
            operation=operation,
            authorization_allowed=False,
            blocking_reason=reason,
            http_status_code=status_code,
            window_evidence_hash=window.evidence_hash if window else None,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProductivityPilotRuntimeWindowConflict("productivity pilot timestamp must include a timezone")
        return value.astimezone(UTC)


def build_default_productivity_pilot_runtime_window_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotRuntimeWindowStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_WINDOW_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotRuntimeWindowStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_WINDOW_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot runtime window store requires a database DSN")
        return PgProductivityPilotRuntimeWindowStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot runtime window store backend: {backend}")
