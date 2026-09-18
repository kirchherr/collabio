from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_closure_report import (
    ProductivityPilotDomainReceiptEvidence,
    ProductivityPilotDomainReceiptStore,
)
from suite.platform.productivity_pilot_real_user_admission import (
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserAdmissionStore,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_real_user_runtime_window import (
    ProductivityPilotRealUserRuntimeObservation,
    ProductivityPilotRealUserRuntimeWindow,
    ProductivityPilotRealUserRuntimeWindowStore,
    build_productivity_pilot_real_user_designated_principal_manifest_hash,
    build_productivity_pilot_real_user_runtime_observation_hash,
    build_productivity_pilot_real_user_runtime_window_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    build_productivity_pilot_principal_observation_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotStartAuthorization,
    ProductivityPilotStartAuthorizationStore,
    build_productivity_pilot_start_authorization_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT_SCHEMA_VERSION = "productivity_pilot_real_user_closure_report.v1"
PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_CONFIRMATION_STATEMENT = (
    "I explicitly close this real-user productivity pilot window. I confirm that the deployment kill switch is "
    "closed, the complete hash-only observation and domain receipt manifests are bound, refreshed backup and "
    "restore evidence is attached, all records are preserved, and no business, audit, destructive, external, "
    "module, or feature action is requested by this closure."
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
OPERATION_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_./{}-]+$")


class ProductivityPilotRealUserClosureConflict(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProductivityPilotRealUserClosureConflict(
            "real-user productivity pilot closure timestamps must include a timezone"
        )
    return value.astimezone(UTC)


class ProductivityPilotRealUserRecoveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_sha256: str
    postgres_restore_drill_report_hash: str
    backend_foundation_gate_hash: str
    business_backend_release_gate_hash: str
    observed_at_utc: datetime
    restored_runtime_window_count: int = Field(ge=1)
    restored_observation_count: int = Field(ge=0)
    restored_domain_receipt_count: int = Field(ge=0)
    ready: bool = True
    content_included: bool = False

    @field_validator(
        "backup_sha256",
        "postgres_restore_drill_report_hash",
        "backend_foundation_gate_hash",
        "business_backend_release_gate_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot recovery evidence must use sha256")
        return value

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("real-user productivity pilot recovery evidence timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def require_ready_metadata_only_recovery(self) -> Self:
        if not self.ready or self.content_included:
            raise ValueError("real-user productivity pilot recovery evidence must be ready and metadata-only")
        return self


class ProductivityPilotRealUserClosureCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closure_id: str
    window_id: str
    runtime_window_evidence_hash: str
    recovery_evidence: ProductivityPilotRealUserRecoveryEvidence
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    recovery_owner_ref: str
    audit_chain_ref: str
    human_confirmation_statement: str
    closed_at_utc: datetime
    closure_requested: bool = True
    runtime_switch_closed: bool = True
    record_mutation_requested: bool = False
    record_deletion_requested: bool = False
    module_activation_requested: bool = False
    feature_mutation_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("closure_id", "window_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot closure IDs have an invalid format")
        return value

    @field_validator("runtime_window_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot closure window evidence must use sha256")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "operations_owner_ref",
        "recovery_owner_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot closure references must be typed")
        return value

    @field_validator("operations_owner_ref", "recovery_owner_ref")
    @classmethod
    def reject_raw_principal_owner_reference(cls, value: str) -> str:
        if value.lower().startswith(("principal:", "user:", "subject:")):
            raise ValueError("real-user productivity pilot owner references must not contain raw principal identifiers")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_CONFIRMATION_STATEMENT:
            raise ValueError("exact real-user productivity pilot closure confirmation statement required")
        return value

    @field_validator("closed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("closed_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_non_mutating_closure(self) -> Self:
        if (
            not self.closure_requested
            or not self.runtime_switch_closed
            or self.record_mutation_requested
            or self.record_deletion_requested
            or self.module_activation_requested
            or self.feature_mutation_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError(
                "real-user productivity pilot closure must be explicit, closed, metadata-only, and non-mutating"
            )
        return self


class ProductivityPilotRealUserOperationObservationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    observation_count: int = Field(ge=1)

    @field_validator("operation")
    @classmethod
    def require_operation(cls, value: str) -> str:
        if not OPERATION_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot closure operation has an invalid format")
        return value


class ProductivityPilotRealUserClosureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    closure_id: str
    window_id: str
    admission_id: str
    real_user_admission_evidence_hash: str
    nomination_id: str
    nomination_evidence_hash: str
    authorization_id: str
    runtime_window_evidence_hash: str
    start_authorization_evidence_hash: str
    designated_principal_manifest_hash: str
    participant_role_snapshot_hash: str
    route_scope_hash: str
    observation_manifest_hash: str
    observation_count: int = Field(ge=0)
    observed_principal_hashes: tuple[str, ...]
    operation_summaries: tuple[ProductivityPilotRealUserOperationObservationSummary, ...]
    domain_receipt_manifest_hash: str
    domain_receipts: tuple[ProductivityPilotDomainReceiptEvidence, ...]
    recovery_evidence: ProductivityPilotRealUserRecoveryEvidence
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    recovery_owner_ref: str
    audit_chain_ref: str
    closed_by_principal_hash: str
    closed_at_utc: datetime
    runtime_switch_closed: bool = True
    window_evidence_verified: bool = True
    admission_chain_verified: bool = True
    complete_observation_manifest_verified: bool = True
    designated_principals_verified: bool = True
    domain_receipts_verified: bool = True
    recovery_evidence_verified: bool = True
    records_preserved: bool = True
    pilot_activity_observed: bool
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "retain_closed_real_user_pilot_evidence_and_require_new_admission_for_expansion"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT_SCHEMA_VERSION

    @field_validator(
        "real_user_admission_evidence_hash",
        "nomination_evidence_hash",
        "runtime_window_evidence_hash",
        "start_authorization_evidence_hash",
        "designated_principal_manifest_hash",
        "participant_role_snapshot_hash",
        "route_scope_hash",
        "observation_manifest_hash",
        "domain_receipt_manifest_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "closed_by_principal_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user productivity pilot closure report hashes must use sha256")
        return value

    @field_validator("observed_principal_hashes")
    @classmethod
    def require_principal_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not SHA256_PATTERN.fullmatch(item) for item in value):
            raise ValueError("real-user productivity pilot closure principal hashes must be unique sha256 values")
        return value

    @model_validator(mode="after")
    def require_closed_hash_only_report(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT_SCHEMA_VERSION
            or sum(item.observation_count for item in self.operation_summaries) != self.observation_count
            or self.pilot_activity_observed != (self.observation_count > 0)
            or not self.runtime_switch_closed
            or not self.window_evidence_verified
            or not self.admission_chain_verified
            or not self.complete_observation_manifest_verified
            or not self.designated_principals_verified
            or not self.domain_receipts_verified
            or not self.recovery_evidence_verified
            or not self.records_preserved
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("real-user productivity pilot closure violates the closed hash-only boundary")
        return self


ProductivityPilotRealUserClosureReportResult = ProductivityPilotRealUserClosureReport | None


class ProductivityPilotRealUserClosureReportStore(Protocol):
    def append(self, record: ProductivityPilotRealUserClosureReport) -> ProductivityPilotRealUserClosureReport: ...

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserClosureReport | None: ...

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserClosureReportResult: ...


class InMemoryProductivityPilotRealUserClosureReportStore:
    def __init__(self, records: Iterable[ProductivityPilotRealUserClosureReport] = ()) -> None:
        self.records: list[ProductivityPilotRealUserClosureReport] = []
        for record in records:
            self.append(record)

    def append(self, record: ProductivityPilotRealUserClosureReport) -> ProductivityPilotRealUserClosureReport:
        if build_productivity_pilot_real_user_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot closure report evidence hash is invalid")
        if self.for_idempotency(tenant_id=record.tenant_id, idempotency_key_hash=record.idempotency_key_hash):
            raise ProductivityPilotRealUserClosureConflict(
                "real-user productivity pilot closure idempotency key exists"
            )
        if any(
            item.tenant_id == record.tenant_id
            and (item.closure_id == record.closure_id or item.window_id == record.window_id)
            for item in self.records
        ):
            raise ProductivityPilotRealUserClosureConflict("real-user productivity pilot closure report already exists")
        self.records.append(record)
        return record

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserClosureReport | None:
        return next((item for item in reversed(self.records) if item.tenant_id == tenant_id), None)

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserClosureReport | None:
        return next(
            (
                item
                for item in reversed(self.records)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )


class PgProductivityPilotRealUserClosureReportStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: ProductivityPilotRealUserClosureReport) -> ProductivityPilotRealUserClosureReport:
        if build_productivity_pilot_real_user_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("real-user productivity pilot closure report evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_real_user_closure_reports (
                        tenant_id, closure_id, window_id, admission_id, nomination_id, authorization_id,
                        runtime_window_evidence_hash, real_user_admission_evidence_hash,
                        observation_manifest_hash, observation_count, domain_receipt_manifest_hash,
                        domain_receipt_count, command_hash, idempotency_key_hash,
                        closed_by_principal_hash, closed_at_utc, recovery_observed_at_utc,
                        closure_record, evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.closure_id,
                        record.window_id,
                        record.admission_id,
                        record.nomination_id,
                        record.authorization_id,
                        record.runtime_window_evidence_hash,
                        record.real_user_admission_evidence_hash,
                        record.observation_manifest_hash,
                        record.observation_count,
                        record.domain_receipt_manifest_hash,
                        len(record.domain_receipts),
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.closed_by_principal_hash,
                        record.closed_at_utc,
                        record.recovery_evidence.observed_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRealUserClosureConflict(
                "real-user productivity pilot closure report already exists"
            ) from exc
        return record

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserClosureReport | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserClosureReport | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            value=idempotency_key_hash,
        )

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotRealUserClosureReport | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT closure_record
                FROM collabio.productivity_pilot_real_user_closure_reports
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY closed_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotRealUserClosureReport.model_validate(row[0])
        if build_productivity_pilot_real_user_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("persisted real-user productivity pilot closure report evidence hash is invalid")
        return record


def build_productivity_pilot_real_user_closure_command_hash(
    command: ProductivityPilotRealUserClosureCommand,
) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_real_user_observation_manifest_hash(
    *,
    tenant_id: str,
    window_id: str,
    observations: tuple[ProductivityPilotRealUserRuntimeObservation, ...],
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_real_user_observation_manifest.v1",
            "tenant_id": tenant_id,
            "window_id": window_id,
            "observation_evidence_hashes": sorted(item.evidence_hash for item in observations),
        }
    )


def build_productivity_pilot_real_user_domain_receipt_manifest_hash(
    *, tenant_id: str, window_id: str, receipts: tuple[ProductivityPilotDomainReceiptEvidence, ...]
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_real_user_domain_receipt_manifest.v1",
            "tenant_id": tenant_id,
            "window_id": window_id,
            "receipts": [
                item.model_dump(mode="json")
                for item in sorted(
                    receipts,
                    key=lambda item: (item.operation, item.committed_at_utc, item.receipt_hash),
                )
            ],
        }
    )


def build_productivity_pilot_real_user_closure_report_hash(
    record: ProductivityPilotRealUserClosureReport,
) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotRealUserClosureService:
    def __init__(
        self,
        *,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        real_user_admission_store: ProductivityPilotRealUserAdmissionStore,
        runtime_window_store: ProductivityPilotRealUserRuntimeWindowStore,
        domain_receipt_store: ProductivityPilotDomainReceiptStore,
        closure_report_store: ProductivityPilotRealUserClosureReportStore,
        runtime_enabled: bool,
    ) -> None:
        self.start_authorization_store = start_authorization_store
        self.real_user_admission_store = real_user_admission_store
        self.runtime_window_store = runtime_window_store
        self.domain_receipt_store = domain_receipt_store
        self.closure_report_store = closure_report_store
        self.runtime_enabled = runtime_enabled

    def close(
        self, *, user_context: UserContext, command: ProductivityPilotRealUserClosureCommand
    ) -> ProductivityPilotRealUserClosureReport:
        if "security-admin" not in user_context.role_ids:
            raise PermissionError("security admin role required")
        if self.runtime_enabled:
            raise ProductivityPilotRealUserClosureConflict(
                "real-user productivity pilot runtime kill switch must be closed"
            )
        window = self.runtime_window_store.current_window(tenant_id=user_context.tenant_id)
        if window is None:
            raise ProductivityPilotRealUserClosureConflict(
                "authoritative real-user productivity pilot runtime window not found"
            )
        self._validate_window_binding(command=command, window=window)
        admission, nomination, start = self._current_chain(tenant_id=user_context.tenant_id)
        self._validate_chain(window=window, admission=admission, nomination=nomination, start=start)
        actor_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=user_context.user_id,
        )
        start_authorizer_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=start.authorized_by,
        )
        if actor_hash in {
            admission.approved_by_principal_hash,
            nomination.nominated_by_principal_hash,
            start_authorizer_hash,
            window.activated_by_principal_hash,
            *window.designated_principal_hashes,
        }:
            raise ProductivityPilotRealUserClosureConflict(
                "four-eyes control requires a closure actor distinct from nomination, admission, start, "
                "runtime activation, and participants"
            )

        closed_at = _utc(command.closed_at_utc)
        if closed_at < _utc(window.effective_at_utc):
            raise ProductivityPilotRealUserClosureConflict(
                "real-user productivity pilot closure cannot predate the runtime window"
            )
        if _utc(command.recovery_evidence.observed_at_utc) < closed_at:
            raise ProductivityPilotRealUserClosureConflict(
                "recovery evidence must be observed after real-user runtime closure"
            )

        command_hash = build_productivity_pilot_real_user_closure_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_closure_idempotency.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.closure_report_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user productivity pilot closure idempotency key was used for another command"
                )
            return existing.model_copy(update={"idempotent_replay": True})

        observations = self.runtime_window_store.observations_for_window(
            tenant_id=user_context.tenant_id,
            window_id=window.window_id,
        )
        operation_summaries, principal_hashes, observed_pairs = self._validate_observations(
            window=window,
            observations=observations,
            closed_at=closed_at,
        )
        receipt_evidence = self._load_and_validate_receipts(
            tenant_id=user_context.tenant_id,
            window=window,
            closed_at=closed_at,
            observed_pairs=observed_pairs,
        )
        self._validate_recovery_counts(
            evidence=command.recovery_evidence,
            observation_count=len(observations),
            domain_receipt_count=len(receipt_evidence),
        )

        draft = ProductivityPilotRealUserClosureReport(
            tenant_id=user_context.tenant_id,
            closure_id=command.closure_id,
            window_id=window.window_id,
            admission_id=admission.admission_id,
            real_user_admission_evidence_hash=admission.evidence_hash,
            nomination_id=nomination.nomination_id,
            nomination_evidence_hash=nomination.evidence_hash,
            authorization_id=start.authorization_id,
            runtime_window_evidence_hash=window.evidence_hash,
            start_authorization_evidence_hash=start.evidence_hash,
            designated_principal_manifest_hash=window.designated_principal_manifest_hash,
            participant_role_snapshot_hash=window.participant_role_snapshot_hash,
            route_scope_hash=window.route_scope_hash,
            observation_manifest_hash=build_productivity_pilot_real_user_observation_manifest_hash(
                tenant_id=user_context.tenant_id,
                window_id=window.window_id,
                observations=observations,
            ),
            observation_count=len(observations),
            observed_principal_hashes=tuple(sorted(principal_hashes)),
            operation_summaries=operation_summaries,
            domain_receipt_manifest_hash=build_productivity_pilot_real_user_domain_receipt_manifest_hash(
                tenant_id=user_context.tenant_id,
                window_id=window.window_id,
                receipts=receipt_evidence,
            ),
            domain_receipts=receipt_evidence,
            recovery_evidence=command.recovery_evidence,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            operations_owner_ref=command.operations_owner_ref,
            recovery_owner_ref=command.recovery_owner_ref,
            audit_chain_ref=command.audit_chain_ref,
            closed_by_principal_hash=actor_hash,
            closed_at_utc=command.closed_at_utc,
            pilot_activity_observed=bool(observations),
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(
            update={"evidence_hash": build_productivity_pilot_real_user_closure_report_hash(draft)}
        )
        return self.closure_report_store.append(record)

    def current(self, *, tenant_id: str) -> ProductivityPilotRealUserClosureReport | None:
        record = self.closure_report_store.current(tenant_id=tenant_id)
        if record is not None and (
            build_productivity_pilot_real_user_closure_report_hash(record) != record.evidence_hash
        ):
            raise ProductivityPilotRealUserClosureConflict(
                "authoritative real-user productivity pilot closure report is invalid"
            )
        return record

    @staticmethod
    def _validate_window_binding(
        *, command: ProductivityPilotRealUserClosureCommand, window: ProductivityPilotRealUserRuntimeWindow
    ) -> None:
        if build_productivity_pilot_real_user_runtime_window_hash(window) != window.evidence_hash:
            raise ProductivityPilotRealUserClosureConflict(
                "authoritative real-user productivity pilot runtime window is invalid"
            )
        if (
            build_productivity_pilot_real_user_designated_principal_manifest_hash(
                tenant_id=window.tenant_id,
                designated_principal_hashes=window.designated_principal_hashes,
            )
            != window.designated_principal_manifest_hash
        ):
            raise ProductivityPilotRealUserClosureConflict(
                "authoritative real-user productivity pilot principal manifest is invalid"
            )
        if command.window_id != window.window_id or command.runtime_window_evidence_hash != window.evidence_hash:
            raise ProductivityPilotRealUserClosureConflict(
                "real-user closure command does not match the authoritative runtime window"
            )

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
            raise ProductivityPilotRealUserClosureConflict(
                "authoritative real-user admission, nomination, and start chain are required"
            )
        if build_productivity_pilot_real_user_admission_hash(admission) != admission.evidence_hash:
            raise ProductivityPilotRealUserClosureConflict("authoritative real-user admission hash is invalid")
        if build_productivity_pilot_real_user_nomination_hash(nomination) != nomination.evidence_hash:
            raise ProductivityPilotRealUserClosureConflict("authoritative real-user nomination hash is invalid")
        if build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash:
            raise ProductivityPilotRealUserClosureConflict("authoritative pilot start hash is invalid")
        return admission, nomination, start

    @staticmethod
    def _validate_chain(
        *,
        window: ProductivityPilotRealUserRuntimeWindow,
        admission: ProductivityPilotRealUserAdmission,
        nomination: ProductivityPilotRealUserNomination,
        start: ProductivityPilotStartAuthorization,
    ) -> None:
        if (
            window.admission_id != admission.admission_id
            or window.real_user_admission_evidence_hash != admission.evidence_hash
            or window.nomination_id != nomination.nomination_id
            or window.nomination_evidence_hash != nomination.evidence_hash
            or admission.nomination_id != nomination.nomination_id
            or admission.nomination_evidence_hash != nomination.evidence_hash
            or window.authorization_id != start.authorization_id
            or window.start_authorization_evidence_hash != start.evidence_hash
            or start.preflight_gate_hash != admission.preflight_gate_hash
        ):
            raise ProductivityPilotRealUserClosureConflict(
                "real-user runtime window no longer matches the authoritative admission and start chain"
            )

    @staticmethod
    def _validate_observations(
        *,
        window: ProductivityPilotRealUserRuntimeWindow,
        observations: tuple[ProductivityPilotRealUserRuntimeObservation, ...],
        closed_at: datetime,
    ) -> tuple[
        tuple[ProductivityPilotRealUserOperationObservationSummary, ...],
        set[str],
        dict[tuple[str, str], tuple[datetime, ...]],
    ]:
        operation_counts: Counter[str] = Counter()
        observed_times: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        principal_hashes: set[str] = set()
        for observation in observations:
            if build_productivity_pilot_real_user_runtime_observation_hash(observation) != observation.evidence_hash:
                raise ProductivityPilotRealUserClosureConflict("real-user runtime observation evidence hash is invalid")
            if (
                observation.tenant_id != window.tenant_id
                or observation.window_id != window.window_id
                or observation.admission_id != window.admission_id
                or observation.real_user_admission_evidence_hash != window.real_user_admission_evidence_hash
                or observation.authorization_id != window.authorization_id
                or observation.start_authorization_evidence_hash != window.start_authorization_evidence_hash
                or observation.window_evidence_hash != window.evidence_hash
            ):
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user runtime observation is not bound to the closure window"
                )
            observed_at = _utc(observation.observed_at_utc)
            if (
                observed_at < _utc(window.effective_at_utc)
                or observed_at >= _utc(window.expires_at_utc)
                or observed_at > closed_at
            ):
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user runtime observation is outside the closed interval"
                )
            if (
                observation.operation not in window.allowed_api_operations
                or observation.principal_id_hash not in window.designated_principal_hashes
            ):
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user runtime observation is outside the designated route or principal scope"
                )
            operation_counts[observation.operation] += 1
            observed_times[(observation.operation, observation.principal_id_hash)].append(observed_at)
            principal_hashes.add(observation.principal_id_hash)
        summaries = tuple(
            ProductivityPilotRealUserOperationObservationSummary(
                operation=operation,
                observation_count=count,
            )
            for operation, count in sorted(operation_counts.items())
        )
        return (
            summaries,
            principal_hashes,
            {pair: tuple(sorted(times)) for pair, times in observed_times.items()},
        )

    def _load_and_validate_receipts(
        self,
        *,
        tenant_id: str,
        window: ProductivityPilotRealUserRuntimeWindow,
        closed_at: datetime,
        observed_pairs: Mapping[tuple[str, str], tuple[datetime, ...]],
    ) -> tuple[ProductivityPilotDomainReceiptEvidence, ...]:
        receipts = self.domain_receipt_store.for_interval(
            tenant_id=tenant_id,
            effective_at_utc=window.effective_at_utc,
            closed_at_utc=closed_at,
        )
        evidence: list[ProductivityPilotDomainReceiptEvidence] = []
        receipt_pairs: Counter[tuple[str, str]] = Counter()
        receipt_hashes: set[str] = set()
        allowed_write_operations = {
            item for item in window.allowed_api_operations if item.startswith(("POST ", "PUT ", "PATCH ", "DELETE "))
        }
        for receipt in sorted(
            receipts,
            key=lambda item: (item.committed_at_utc, item.operation, item.receipt_hash),
        ):
            principal_hash = build_productivity_pilot_principal_observation_hash(
                tenant_id=tenant_id,
                principal_id=receipt.created_by,
            )
            if receipt.operation not in allowed_write_operations or (
                principal_hash not in window.designated_principal_hashes
            ):
                continue
            committed_at = _utc(receipt.committed_at_utc)
            if (
                committed_at < _utc(window.effective_at_utc)
                or committed_at >= _utc(window.expires_at_utc)
                or committed_at > closed_at
            ):
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user domain receipt is outside the closed interval"
                )
            pair = (receipt.operation, principal_hash)
            observation_times = observed_pairs.get(pair, ())
            receipt_index = receipt_pairs[pair]
            if receipt_index >= len(observation_times) or observation_times[receipt_index] > committed_at:
                raise ProductivityPilotRealUserClosureConflict(
                    "real-user domain receipt is not covered by an earlier authoritative runtime observation"
                )
            receipt_pairs[pair] += 1
            if not SHA256_PATTERN.fullmatch(receipt.receipt_hash) or receipt.receipt_hash in receipt_hashes:
                raise ProductivityPilotRealUserClosureConflict("real-user domain receipt hash is invalid or duplicated")
            receipt_hashes.add(receipt.receipt_hash)
            evidence.append(
                ProductivityPilotDomainReceiptEvidence(
                    operation=receipt.operation,
                    receipt_hash=receipt.receipt_hash,
                    principal_id_hash=principal_hash,
                    committed_at_utc=receipt.committed_at_utc,
                )
            )
        return tuple(
            sorted(
                evidence,
                key=lambda item: (item.operation, item.committed_at_utc, item.receipt_hash),
            )
        )

    @staticmethod
    def _validate_recovery_counts(
        *,
        evidence: ProductivityPilotRealUserRecoveryEvidence,
        observation_count: int,
        domain_receipt_count: int,
    ) -> None:
        if (
            evidence.restored_runtime_window_count != 1
            or evidence.restored_observation_count != observation_count
            or evidence.restored_domain_receipt_count != domain_receipt_count
        ):
            raise ProductivityPilotRealUserClosureConflict(
                "real-user recovery evidence counts do not match the authoritative closed pilot records"
            )


def build_default_productivity_pilot_real_user_closure_report_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotRealUserClosureReportStore:
    env = os.environ if environ is None else environ
    backend = (
        env.get(
            "SUITE_PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT_STORE_BACKEND",
            "memory",
        )
        .strip()
        .lower()
    )
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotRealUserClosureReportStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL real-user productivity pilot closure report store requires a database DSN")
        return PgProductivityPilotRealUserClosureReportStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported real-user productivity pilot closure report store backend: {backend}")
