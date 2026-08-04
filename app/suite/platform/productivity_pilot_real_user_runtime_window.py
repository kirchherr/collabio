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
from suite.platform.productivity_pilot_real_user_admission import (
    ProductivityPilotParticipantDirectory,
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserAdmissionConflict,
    ProductivityPilotRealUserAdmissionStore,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    MAX_DESIGNATED_PILOT_PRINCIPALS,
    build_productivity_pilot_principal_observation_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW,
    ProductivityPilotStartAuthorization,
    ProductivityPilotStartAuthorizationStore,
    build_productivity_pilot_start_authorization_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_SCHEMA_VERSION = "productivity_pilot_real_user_runtime_window.v1"
PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_OBSERVATION_SCHEMA_VERSION = "productivity_pilot_real_user_runtime_observation.v1"
PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_CONFIRMATION_STATEMENT = (
    "I explicitly activate this real-user productivity pilot runtime window for only the independently approved "
    "principals, authorized operations, evidence-bound tenant, and submitted time window. I confirm that principal "
    "identifiers are resolved only transiently, persisted evidence is pseudonymized, current IAM roles remain "
    "authoritative, the deployment kill switch remains authoritative, and no additional module, destructive, or "
    "external action is authorized."
)

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
OPERATION_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_./{}-]+$")


class ProductivityPilotRealUserRuntimeWindowConflict(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProductivityPilotRealUserRuntimeWindowConflict(
            "real-user productivity pilot timestamp must include a timezone"
        )
    return value.astimezone(UTC)


def _validate_principal_id(value: str) -> str:
    if not value or value != value.strip() or len(value) > 255 or any(ord(character) < 32 for character in value):
        raise ValueError("real-user productivity pilot principal ID has an invalid format")
    return value


class ProductivityPilotRealUserRuntimeWindowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    admission_id: str
    real_user_admission_evidence_hash: str
    nomination_id: str
    nomination_evidence_hash: str
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

    @field_validator("window_id", "admission_id", "nomination_id", "authorization_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot runtime IDs have an invalid format")
        return value

    @field_validator(
        "real_user_admission_evidence_hash",
        "nomination_evidence_hash",
        "start_authorization_evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot runtime evidence must use sha256")
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
            raise ValueError("real-user productivity pilot runtime references must be typed")
        return value

    @field_validator("designated_principal_ids")
    @classmethod
    def require_designated_principals(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > MAX_DESIGNATED_PILOT_PRINCIPALS or len(value) != len(set(value)):
            raise ValueError("real-user productivity pilot principals must be present, unique, and bounded")
        for principal_id in value:
            _validate_principal_id(principal_id)
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_CONFIRMATION_STATEMENT:
            raise ValueError("exact real-user productivity pilot runtime confirmation statement required")
        return value

    @field_validator("activated_at_utc", "effective_at_utc", "expires_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("real-user productivity pilot runtime timestamps must include a timezone")
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
            raise ValueError("real-user productivity pilot runtime request must remain bounded and metadata-only")
        return self


class ProductivityPilotRealUserRuntimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    window_id: str
    admission_id: str
    real_user_admission_evidence_hash: str
    nomination_id: str
    nomination_evidence_hash: str
    authorization_id: str
    start_authorization_evidence_hash: str
    designated_principal_hashes: tuple[str, ...]
    designated_principal_manifest_hash: str
    participant_role_snapshot_hash: str
    allowed_api_operations: tuple[str, ...]
    route_scope_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    audit_chain_ref: str
    activated_by_principal_hash: str
    activated_at_utc: datetime
    effective_at_utc: datetime
    expires_at_utc: datetime
    authoritative_principals_verified: bool = True
    current_roles_verified: bool = True
    real_user_admission_verified: bool = True
    fresh_start_chain_verified: bool = True
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
    next_action: str = "observe_approved_real_users_then_close_switch_and_record_real_user_closure"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_SCHEMA_VERSION

    @field_validator(
        "real_user_admission_evidence_hash",
        "nomination_evidence_hash",
        "start_authorization_evidence_hash",
        "designated_principal_manifest_hash",
        "participant_role_snapshot_hash",
        "route_scope_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "activated_by_principal_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot runtime record hashes must use sha256")
        return value

    @field_validator("designated_principal_hashes")
    @classmethod
    def require_principal_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)) or any(not SHA256_PATTERN.fullmatch(item) for item in value):
            raise ValueError("real-user productivity pilot principal hashes must be present and unique")
        return value

    @model_validator(mode="after")
    def require_safe_runtime_window(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_SCHEMA_VERSION
            or not self.allowed_api_operations
            or not self.authoritative_principals_verified
            or not self.current_roles_verified
            or not self.real_user_admission_verified
            or not self.fresh_start_chain_verified
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
            raise ValueError("real-user productivity pilot runtime violates the controlled boundary")
        return self


class ProductivityPilotRealUserRuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    observation_id: str
    window_id: str
    admission_id: str
    real_user_admission_evidence_hash: str
    authorization_id: str
    start_authorization_evidence_hash: str
    window_evidence_hash: str
    principal_id_hash: str
    operation: str
    observed_at_utc: datetime
    authorization_allowed: bool = True
    active_principal_verified: bool = True
    current_roles_verified: bool = True
    designated_principal_verified: bool = True
    route_scope_verified: bool = True
    response_payload_observed: bool = False
    business_payload_persisted: bool = False
    content_included: bool = False
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_OBSERVATION_SCHEMA_VERSION

    @field_validator(
        "real_user_admission_evidence_hash",
        "start_authorization_evidence_hash",
        "window_evidence_hash",
        "principal_id_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot observation hashes must use sha256")
        return value

    @field_validator("operation")
    @classmethod
    def require_operation(cls, value: str) -> str:
        if not OPERATION_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot observation operation has an invalid format")
        return value

    @model_validator(mode="after")
    def require_metadata_only_observation(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_OBSERVATION_SCHEMA_VERSION
            or not self.authorization_allowed
            or not self.active_principal_verified
            or not self.current_roles_verified
            or not self.designated_principal_verified
            or not self.route_scope_verified
            or self.response_payload_observed
            or self.business_payload_persisted
            or self.content_included
        ):
            raise ValueError("real-user productivity pilot observation must be authorized and metadata-only")
        return self


class ProductivityPilotRealUserRuntimeAccessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    operation: str
    authorization_allowed: bool
    active_principal_verified: bool = False
    current_roles_verified: bool = False
    designated_principal_verified: bool = False
    runtime_window_verified: bool = False
    blocking_reason: str | None = None
    http_status_code: int
    window_evidence_hash: str | None = None
    admission_evidence_hash: str | None = None
    observation_evidence_hash: str | None = None
    content_included: bool = False


def build_productivity_pilot_real_user_designated_principal_manifest_hash(
    *, tenant_id: str, designated_principal_hashes: tuple[str, ...]
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_real_user_designated_principal_manifest.v1",
            "tenant_id": tenant_id,
            "designated_principal_hashes": sorted(designated_principal_hashes),
        }
    )


def build_productivity_pilot_real_user_runtime_window_command_hash(
    command: ProductivityPilotRealUserRuntimeWindowCommand,
) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_real_user_runtime_window_hash(
    record: ProductivityPilotRealUserRuntimeWindow,
) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


def build_productivity_pilot_real_user_runtime_observation_hash(
    record: ProductivityPilotRealUserRuntimeObservation,
) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash"}))


class ProductivityPilotRealUserRuntimeWindowStore(Protocol):
    def append_window(
        self, record: ProductivityPilotRealUserRuntimeWindow
    ) -> ProductivityPilotRealUserRuntimeWindow: ...

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRealUserRuntimeWindow | None: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserRuntimeWindow | None: ...

    def append_observation(
        self, record: ProductivityPilotRealUserRuntimeObservation
    ) -> ProductivityPilotRealUserRuntimeObservation: ...

    def observations_for_window(
        self, *, tenant_id: str, window_id: str
    ) -> tuple[ProductivityPilotRealUserRuntimeObservation, ...]: ...


class InMemoryProductivityPilotRealUserRuntimeWindowStore:
    def __init__(
        self,
        windows: Iterable[ProductivityPilotRealUserRuntimeWindow] = (),
        observations: Iterable[ProductivityPilotRealUserRuntimeObservation] = (),
    ) -> None:
        self.windows: list[ProductivityPilotRealUserRuntimeWindow] = []
        self.observations: list[ProductivityPilotRealUserRuntimeObservation] = []
        for window in windows:
            self.append_window(window)
        for observation in observations:
            self.append_observation(observation)

    def append_window(self, record: ProductivityPilotRealUserRuntimeWindow) -> ProductivityPilotRealUserRuntimeWindow:
        if build_productivity_pilot_real_user_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot runtime window evidence hash is invalid")
        if self.for_idempotency(tenant_id=record.tenant_id, idempotency_key_hash=record.idempotency_key_hash):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime idempotency key exists"
            )
        if any(item.tenant_id == record.tenant_id and item.window_id == record.window_id for item in self.windows):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime window already exists"
            )
        self.windows.append(record)
        return record

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRealUserRuntimeWindow | None:
        return next((item for item in reversed(self.windows) if item.tenant_id == tenant_id), None)

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserRuntimeWindow | None:
        return next(
            (
                item
                for item in reversed(self.windows)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def append_observation(
        self, record: ProductivityPilotRealUserRuntimeObservation
    ) -> ProductivityPilotRealUserRuntimeObservation:
        if build_productivity_pilot_real_user_runtime_observation_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot runtime observation evidence hash is invalid")
        if any(
            item.tenant_id == record.tenant_id and item.observation_id == record.observation_id
            for item in self.observations
        ):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime observation already exists"
            )
        self.observations.append(record)
        return record

    def observations_for_window(
        self, *, tenant_id: str, window_id: str
    ) -> tuple[ProductivityPilotRealUserRuntimeObservation, ...]:
        return tuple(
            sorted(
                (item for item in self.observations if item.tenant_id == tenant_id and item.window_id == window_id),
                key=lambda item: (item.observed_at_utc, item.evidence_hash),
            )
        )


class PgProductivityPilotRealUserRuntimeWindowStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append_window(self, record: ProductivityPilotRealUserRuntimeWindow) -> ProductivityPilotRealUserRuntimeWindow:
        if build_productivity_pilot_real_user_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot runtime window evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_real_user_runtime_windows (
                        tenant_id, window_id, admission_id, real_user_admission_evidence_hash,
                        nomination_id, nomination_evidence_hash, authorization_id,
                        start_authorization_evidence_hash, designated_principal_hashes,
                        designated_principal_manifest_hash, participant_role_snapshot_hash,
                        allowed_api_operations, route_scope_hash, command_hash,
                        idempotency_key_hash, human_confirmation_statement_hash,
                        activated_by_principal_hash, activated_at_utc, effective_at_utc,
                        expires_at_utc, window_record, evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.window_id,
                        record.admission_id,
                        record.real_user_admission_evidence_hash,
                        record.nomination_id,
                        record.nomination_evidence_hash,
                        record.authorization_id,
                        record.start_authorization_evidence_hash,
                        Jsonb(list(record.designated_principal_hashes)),
                        record.designated_principal_manifest_hash,
                        record.participant_role_snapshot_hash,
                        Jsonb(list(record.allowed_api_operations)),
                        record.route_scope_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.activated_by_principal_hash,
                        record.activated_at_utc,
                        record.effective_at_utc,
                        record.expires_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime window already exists"
            ) from exc
        return record

    def current_window(self, *, tenant_id: str) -> ProductivityPilotRealUserRuntimeWindow | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserRuntimeWindow | None:
        return self._one(tenant_id=tenant_id, where_sql="idempotency_key_hash = %s", value=idempotency_key_hash)

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotRealUserRuntimeWindow | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT window_record
                FROM collabio.productivity_pilot_real_user_runtime_windows
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY activated_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotRealUserRuntimeWindow.model_validate(row[0])
        if build_productivity_pilot_real_user_runtime_window_hash(record) != record.evidence_hash:
            raise ValueError("persisted real-user productivity pilot runtime window hash is invalid")
        return record

    def append_observation(
        self, record: ProductivityPilotRealUserRuntimeObservation
    ) -> ProductivityPilotRealUserRuntimeObservation:
        if build_productivity_pilot_real_user_runtime_observation_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot runtime observation evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_real_user_runtime_observations (
                        tenant_id, observation_id, window_id, admission_id,
                        real_user_admission_evidence_hash, authorization_id,
                        start_authorization_evidence_hash, window_evidence_hash,
                        principal_id_hash, operation, observed_at_utc,
                        observation_record, evidence_hash, schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.tenant_id,
                        record.observation_id,
                        record.window_id,
                        record.admission_id,
                        record.real_user_admission_evidence_hash,
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
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime observation already exists"
            ) from exc
        return record

    def observations_for_window(
        self, *, tenant_id: str, window_id: str
    ) -> tuple[ProductivityPilotRealUserRuntimeObservation, ...]:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT observation_record
                FROM collabio.productivity_pilot_real_user_runtime_observations
                WHERE tenant_id = %s AND window_id = %s
                ORDER BY observed_at_utc, evidence_hash
                """,
                (tenant_id, window_id),
            ).fetchall()
        records = tuple(ProductivityPilotRealUserRuntimeObservation.model_validate(row[0]) for row in rows)
        if any(
            build_productivity_pilot_real_user_runtime_observation_hash(item) != item.evidence_hash for item in records
        ):
            raise ValueError("persisted real-user productivity pilot runtime observation hash is invalid")
        return records


class ProductivityPilotRealUserRuntimeWindowService:
    def __init__(
        self,
        *,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        real_user_admission_store: ProductivityPilotRealUserAdmissionStore,
        participant_directory: ProductivityPilotParticipantDirectory,
        runtime_window_store: ProductivityPilotRealUserRuntimeWindowStore,
        runtime_enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.start_authorization_store = start_authorization_store
        self.real_user_admission_store = real_user_admission_store
        self.participant_directory = participant_directory
        self.runtime_window_store = runtime_window_store
        self.runtime_enabled = runtime_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    def activate(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotRealUserRuntimeWindowCommand,
    ) -> ProductivityPilotRealUserRuntimeWindow:
        if "tenant-admin" not in user_context.role_ids:
            raise PermissionError("tenant admin role required")
        if not self.runtime_enabled:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime kill switch is closed"
            )
        now = _utc(self.clock())
        admission, nomination, start = self._current_chain(tenant_id=user_context.tenant_id)
        self._validate_command_binding(
            command=command,
            admission=admission,
            nomination=nomination,
            start=start,
            now=now,
        )
        principal_hashes, role_snapshot_hash = self._resolve_designated_principals(
            tenant_id=user_context.tenant_id,
            principal_ids=command.designated_principal_ids,
            nomination=nomination,
        )
        if principal_hashes != tuple(sorted(admission.approved_principal_hashes)):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "designated principals do not exactly match the real-user admission"
            )
        actor_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=user_context.user_id,
        )
        start_authorizer_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=start.authorized_by,
        )
        separated_actor_hashes = {
            admission.approved_by_principal_hash,
            nomination.nominated_by_principal_hash,
            start_authorizer_hash,
            *principal_hashes,
        }
        if actor_hash in separated_actor_hashes:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "four-eyes control requires a runtime operator distinct from nomination, admission, "
                "start, and participants"
            )

        command_hash = build_productivity_pilot_real_user_runtime_window_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_runtime_window_idempotency.v1",
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
                raise ProductivityPilotRealUserRuntimeWindowConflict(
                    "real-user productivity pilot runtime idempotency key was used for another command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        current = self.runtime_window_store.current_window(tenant_id=user_context.tenant_id)
        if current is not None and _utc(current.expires_at_utc) > now:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "an active real-user productivity pilot runtime window already exists"
            )

        draft = ProductivityPilotRealUserRuntimeWindow(
            tenant_id=user_context.tenant_id,
            window_id=command.window_id,
            admission_id=admission.admission_id,
            real_user_admission_evidence_hash=admission.evidence_hash,
            nomination_id=nomination.nomination_id,
            nomination_evidence_hash=nomination.evidence_hash,
            authorization_id=start.authorization_id,
            start_authorization_evidence_hash=start.evidence_hash,
            designated_principal_hashes=principal_hashes,
            designated_principal_manifest_hash=(
                build_productivity_pilot_real_user_designated_principal_manifest_hash(
                    tenant_id=user_context.tenant_id,
                    designated_principal_hashes=principal_hashes,
                )
            ),
            participant_role_snapshot_hash=role_snapshot_hash,
            allowed_api_operations=start.allowed_api_operations,
            route_scope_hash=start.route_scope_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            operations_owner_ref=command.operations_owner_ref,
            audit_chain_ref=command.audit_chain_ref,
            activated_by_principal_hash=actor_hash,
            activated_at_utc=command.activated_at_utc,
            effective_at_utc=command.effective_at_utc,
            expires_at_utc=command.expires_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(
            update={"evidence_hash": build_productivity_pilot_real_user_runtime_window_hash(draft)}
        )
        return self.runtime_window_store.append_window(record)

    def authorize_operation(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        operation: str,
        start_authorization_evidence_hash: str,
    ) -> ProductivityPilotRealUserRuntimeAccessDecision:
        window = self.runtime_window_store.current_window(tenant_id=tenant_id)
        if window is None:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="real_user_productivity_pilot_runtime_window_required",
                status_code=423,
            )
        self._validate_window(window)
        admission, nomination, start = self._current_chain(tenant_id=tenant_id)
        if (
            start.evidence_hash != start_authorization_evidence_hash
            or window.start_authorization_evidence_hash != start.evidence_hash
            or window.authorization_id != start.authorization_id
            or window.admission_id != admission.admission_id
            or window.real_user_admission_evidence_hash != admission.evidence_hash
            or window.nomination_id != nomination.nomination_id
            or window.nomination_evidence_hash != nomination.evidence_hash
        ):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user runtime window no longer matches the authoritative admission and start chain"
            )
        now = _utc(self.clock())
        if not self.runtime_enabled:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="productivity_pilot_runtime_disabled",
                status_code=423,
                window=window,
            )
        if now < _utc(window.effective_at_utc):
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="real_user_productivity_pilot_runtime_window_not_effective",
                status_code=423,
                window=window,
            )
        if now >= min(_utc(window.expires_at_utc), _utc(admission.scheduled_end_at_utc)):
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="real_user_productivity_pilot_runtime_window_expired",
                status_code=423,
                window=window,
            )
        if operation not in window.allowed_api_operations:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="operation_outside_real_user_productivity_pilot_runtime_window",
                status_code=403,
                window=window,
            )
        try:
            snapshot = self.participant_directory.active_principal(
                tenant_id=tenant_id,
                principal_id=principal_id,
            )
        except ProductivityPilotRealUserAdmissionConflict:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="principal_not_active_for_real_user_productivity_pilot",
                status_code=403,
                window=window,
            )
        principal_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=tenant_id,
            principal_id=snapshot.principal_id,
        )
        if principal_hash not in window.designated_principal_hashes:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="principal_not_designated_for_real_user_productivity_pilot",
                status_code=403,
                window=window,
            )
        participant = next(
            (item for item in nomination.participants if item.principal_id_hash == principal_hash),
            None,
        )
        current_roles = tuple(sorted(set(snapshot.role_ids)))
        if participant is None or current_roles != participant.authoritative_role_ids:
            return self._denied(
                tenant_id=tenant_id,
                operation=operation,
                reason="principal_role_drift_for_real_user_productivity_pilot",
                status_code=403,
                window=window,
            )

        draft = ProductivityPilotRealUserRuntimeObservation(
            tenant_id=tenant_id,
            observation_id=f"real-user-pilot-observation-{uuid4().hex}",
            window_id=window.window_id,
            admission_id=admission.admission_id,
            real_user_admission_evidence_hash=admission.evidence_hash,
            authorization_id=start.authorization_id,
            start_authorization_evidence_hash=start.evidence_hash,
            window_evidence_hash=window.evidence_hash,
            principal_id_hash=principal_hash,
            operation=operation,
            observed_at_utc=now,
            evidence_hash="sha256:" + "0" * 64,
        )
        observation = draft.model_copy(
            update={"evidence_hash": build_productivity_pilot_real_user_runtime_observation_hash(draft)}
        )
        observation = self.runtime_window_store.append_observation(observation)
        return ProductivityPilotRealUserRuntimeAccessDecision(
            tenant_id=tenant_id,
            operation=operation,
            authorization_allowed=True,
            active_principal_verified=True,
            current_roles_verified=True,
            designated_principal_verified=True,
            runtime_window_verified=True,
            http_status_code=200,
            window_evidence_hash=window.evidence_hash,
            admission_evidence_hash=admission.evidence_hash,
            observation_evidence_hash=observation.evidence_hash,
        )

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserRuntimeWindow | None:
        window = self.runtime_window_store.current_window(tenant_id=tenant_id)
        if window is not None:
            self._validate_window(window)
        return window

    def _current_chain(
        self, *, tenant_id: str
    ) -> tuple[
        ProductivityPilotRealUserAdmission,
        ProductivityPilotRealUserNomination,
        ProductivityPilotStartAuthorization,
    ]:
        admission = self.real_user_admission_store.current_admission(tenant_id=tenant_id)
        nomination = self.real_user_admission_store.current_nomination(tenant_id=tenant_id)
        start = self.start_authorization_store.current(tenant_id=tenant_id)
        if admission is None or nomination is None or start is None:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "authoritative real-user admission, nomination, and fresh start chain are required"
            )
        if build_productivity_pilot_real_user_admission_hash(admission) != admission.evidence_hash:
            raise ProductivityPilotRealUserRuntimeWindowConflict("authoritative real-user admission hash is invalid")
        if build_productivity_pilot_real_user_nomination_hash(nomination) != nomination.evidence_hash:
            raise ProductivityPilotRealUserRuntimeWindowConflict("authoritative real-user nomination hash is invalid")
        if build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash:
            raise ProductivityPilotRealUserRuntimeWindowConflict("authoritative pilot start hash is invalid")
        if (
            admission.nomination_id != nomination.nomination_id
            or admission.nomination_evidence_hash != nomination.evidence_hash
            or start.preflight_gate_hash != admission.preflight_gate_hash
            or _utc(start.authorized_at_utc) < _utc(admission.approved_at_utc)
            or _utc(start.effective_at_utc) < _utc(admission.scheduled_start_at_utc)
            or _utc(start.expires_at_utc) > _utc(admission.scheduled_end_at_utc)
        ):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "pilot start is not a fresh chain bound to the authoritative real-user admission"
            )
        return admission, nomination, start

    def _validate_command_binding(
        self,
        *,
        command: ProductivityPilotRealUserRuntimeWindowCommand,
        admission: ProductivityPilotRealUserAdmission,
        nomination: ProductivityPilotRealUserNomination,
        start: ProductivityPilotStartAuthorization,
        now: datetime,
    ) -> None:
        expected_values = {
            "admission_id": admission.admission_id,
            "real_user_admission_evidence_hash": admission.evidence_hash,
            "nomination_id": nomination.nomination_id,
            "nomination_evidence_hash": nomination.evidence_hash,
            "authorization_id": start.authorization_id,
            "start_authorization_evidence_hash": start.evidence_hash,
        }
        for field_name, expected in expected_values.items():
            if getattr(command, field_name) != expected:
                raise ProductivityPilotRealUserRuntimeWindowConflict(
                    f"{field_name} does not match authoritative real-user pilot evidence"
                )
        activated_at = _utc(command.activated_at_utc)
        effective_at = _utc(command.effective_at_utc)
        expires_at = _utc(command.expires_at_utc)
        if abs(now - activated_at) > MAX_PRODUCTIVITY_PILOT_CLOCK_SKEW:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime timestamp is outside the allowed clock skew"
            )
        if effective_at < max(_utc(start.effective_at_utc), _utc(admission.scheduled_start_at_utc)) or expires_at > min(
            _utc(start.expires_at_utc), _utc(admission.scheduled_end_at_utc)
        ):
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user runtime window must remain inside admission and start windows"
            )
        if expires_at <= now:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "real-user productivity pilot runtime window is already expired"
            )

    def _resolve_designated_principals(
        self,
        *,
        tenant_id: str,
        principal_ids: tuple[str, ...],
        nomination: ProductivityPilotRealUserNomination,
    ) -> tuple[tuple[str, ...], str]:
        role_snapshots: list[dict[str, object]] = []
        for principal_id in principal_ids:
            try:
                snapshot = self.participant_directory.active_principal(
                    tenant_id=tenant_id,
                    principal_id=principal_id,
                )
            except ProductivityPilotRealUserAdmissionConflict as exc:
                raise ProductivityPilotRealUserRuntimeWindowConflict(str(exc)) from exc
            principal_hash = build_productivity_pilot_principal_observation_hash(
                tenant_id=tenant_id,
                principal_id=snapshot.principal_id,
            )
            participant = next(
                (item for item in nomination.participants if item.principal_id_hash == principal_hash),
                None,
            )
            current_roles = tuple(sorted(set(snapshot.role_ids)))
            if participant is None or current_roles != participant.authoritative_role_ids:
                raise ProductivityPilotRealUserRuntimeWindowConflict(
                    "real-user productivity pilot participant roles changed after admission"
                )
            role_snapshots.append(
                {
                    "principal_id_hash": principal_hash,
                    "authoritative_role_ids": current_roles,
                }
            )
        role_snapshots.sort(key=lambda item: str(item["principal_id_hash"]))
        hashes = tuple(str(item["principal_id_hash"]) for item in role_snapshots)
        return hashes, _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_runtime_role_snapshot.v1",
                "tenant_id": tenant_id,
                "participants": role_snapshots,
            }
        )

    @staticmethod
    def _validate_window(window: ProductivityPilotRealUserRuntimeWindow) -> None:
        if build_productivity_pilot_real_user_runtime_window_hash(window) != window.evidence_hash:
            raise ProductivityPilotRealUserRuntimeWindowConflict(
                "authoritative real-user productivity pilot runtime window hash is invalid"
            )

    @staticmethod
    def _denied(
        *,
        tenant_id: str,
        operation: str,
        reason: str,
        status_code: int,
        window: ProductivityPilotRealUserRuntimeWindow | None = None,
    ) -> ProductivityPilotRealUserRuntimeAccessDecision:
        return ProductivityPilotRealUserRuntimeAccessDecision(
            tenant_id=tenant_id,
            operation=operation,
            authorization_allowed=False,
            blocking_reason=reason,
            http_status_code=status_code,
            window_evidence_hash=window.evidence_hash if window else None,
            admission_evidence_hash=(window.real_user_admission_evidence_hash if window else None),
        )


def build_default_productivity_pilot_real_user_runtime_window_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotRealUserRuntimeWindowStore:
    env = os.environ if environ is None else environ
    backend = (
        env.get(
            "SUITE_PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_STORE_BACKEND",
            "memory",
        )
        .strip()
        .lower()
    )
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotRealUserRuntimeWindowStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL real-user productivity pilot runtime store requires a database DSN")
        return PgProductivityPilotRealUserRuntimeWindowStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported real-user productivity pilot runtime store backend: {backend}")
