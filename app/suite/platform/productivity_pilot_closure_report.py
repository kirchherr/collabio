from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_runtime_window import (
    ProductivityPilotRuntimeObservation,
    ProductivityPilotRuntimeWindow,
    ProductivityPilotRuntimeWindowStore,
    build_productivity_pilot_principal_observation_hash,
    build_productivity_pilot_runtime_observation_hash,
    build_productivity_pilot_runtime_window_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotStartAuthorizationStore,
    build_productivity_pilot_start_authorization_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_CLOSURE_REPORT_SCHEMA_VERSION = "productivity_pilot_closure_report.v1"
PRODUCTIVITY_PILOT_CLOSURE_CONFIRMATION_STATEMENT = (
    "I explicitly close this controlled productivity pilot window. I confirm that the deployment kill switch is "
    "closed, the authoritative observations and domain receipts are complete, refreshed backup and restore evidence "
    "is bound, and no pilot, business, audit, destructive, external, module, or feature record is deleted or changed."
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
OPERATION_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_./{}-]+$")


class ProductivityPilotClosureConflict(ValueError):
    pass


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProductivityPilotClosureConflict("productivity pilot closure timestamps must include a timezone")
    return value.astimezone(UTC)


class ProductivityPilotRecoveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_sha256: str
    postgres_restore_drill_report_hash: str
    backend_foundation_gate_hash: str
    business_backend_release_gate_hash: str
    observed_at_utc: datetime
    restored_runtime_window_count: int = Field(ge=1)
    restored_observation_count: int = Field(ge=1)
    restored_domain_receipt_count: int = Field(ge=1)
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
            raise ValueError("productivity pilot recovery evidence must use sha256")
        return value

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("productivity pilot recovery evidence timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def require_ready_metadata_only_recovery(self) -> Self:
        if not self.ready or self.content_included:
            raise ValueError("productivity pilot recovery evidence must be ready and metadata-only")
        return self


class ProductivityPilotClosureCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closure_id: str
    window_id: str
    runtime_window_evidence_hash: str
    recovery_evidence: ProductivityPilotRecoveryEvidence
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
            raise ValueError("productivity pilot closure IDs have an invalid format")
        return value

    @field_validator("runtime_window_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot closure window evidence must use sha256")
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
            raise ValueError("productivity pilot closure references must be typed")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_CLOSURE_CONFIRMATION_STATEMENT:
            raise ValueError("exact productivity pilot closure confirmation statement required")
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
            raise ValueError("productivity pilot closure must be explicit, closed, metadata-only, and non-mutating")
        return self


class ProductivityPilotOperationObservationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    observation_count: int = Field(ge=1)

    @field_validator("operation")
    @classmethod
    def require_operation(cls, value: str) -> str:
        if not OPERATION_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot closure operation has an invalid format")
        return value


class ProductivityPilotDomainReceiptEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    receipt_hash: str
    principal_id_hash: str
    committed_at_utc: datetime

    @field_validator("operation")
    @classmethod
    def require_operation(cls, value: str) -> str:
        if not OPERATION_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot domain receipt operation has an invalid format")
        return value

    @field_validator("receipt_hash", "principal_id_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot domain receipt evidence must use sha256")
        return value

    @field_validator("committed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("productivity pilot domain receipt timestamp must include a timezone")
        return value


class ProductivityPilotClosureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    closure_id: str
    window_id: str
    authorization_id: str
    runtime_window_evidence_hash: str
    start_authorization_evidence_hash: str
    route_scope_hash: str
    observation_manifest_hash: str
    observation_count: int = Field(ge=1)
    distinct_principal_hash_count: int = Field(ge=1)
    operation_summaries: tuple[ProductivityPilotOperationObservationSummary, ...]
    domain_receipt_manifest_hash: str
    domain_receipts: tuple[ProductivityPilotDomainReceiptEvidence, ...]
    recovery_evidence: ProductivityPilotRecoveryEvidence
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    operations_owner_ref: str
    recovery_owner_ref: str
    audit_chain_ref: str
    closed_by: str
    closed_at_utc: datetime
    runtime_switch_closed: bool = True
    exact_route_observations_verified: bool = True
    designated_principals_verified: bool = True
    domain_receipts_verified: bool = True
    recovery_evidence_verified: bool = True
    records_preserved: bool = True
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "admit_separately_approved_real_user_productivity_pilot"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_CLOSURE_REPORT_SCHEMA_VERSION

    @field_validator(
        "runtime_window_evidence_hash",
        "start_authorization_evidence_hash",
        "route_scope_hash",
        "observation_manifest_hash",
        "domain_receipt_manifest_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("productivity pilot closure report hashes must use sha256")
        return value

    @model_validator(mode="after")
    def require_closed_metadata_only_report(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_CLOSURE_REPORT_SCHEMA_VERSION
            or not self.operation_summaries
            or not self.domain_receipts
            or not self.runtime_switch_closed
            or not self.exact_route_observations_verified
            or not self.designated_principals_verified
            or not self.domain_receipts_verified
            or not self.recovery_evidence_verified
            or not self.records_preserved
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("productivity pilot closure report violates the closed metadata-only boundary")
        return self


@dataclass(frozen=True)
class ProductivityPilotDomainReceipt:
    operation: str
    receipt_hash: str
    created_by: str
    committed_at_utc: datetime


class ProductivityPilotDomainReceiptStore(Protocol):
    def for_interval(
        self,
        *,
        tenant_id: str,
        effective_at_utc: datetime,
        closed_at_utc: datetime,
    ) -> tuple[ProductivityPilotDomainReceipt, ...]: ...


class InMemoryProductivityPilotDomainReceiptStore:
    def __init__(self, receipts: Iterable[ProductivityPilotDomainReceipt] = ()) -> None:
        self.receipts = tuple(receipts)

    def for_interval(
        self,
        *,
        tenant_id: str,
        effective_at_utc: datetime,
        closed_at_utc: datetime,
    ) -> tuple[ProductivityPilotDomainReceipt, ...]:
        del tenant_id
        effective = _utc(effective_at_utc)
        closed = _utc(closed_at_utc)
        return tuple(item for item in self.receipts if effective <= _utc(item.committed_at_utc) <= closed)


class PgProductivityPilotDomainReceiptStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def for_interval(
        self,
        *,
        tenant_id: str,
        effective_at_utc: datetime,
        closed_at_utc: datetime,
    ) -> tuple[ProductivityPilotDomainReceipt, ...]:
        effective = _utc(effective_at_utc)
        closed = _utc(closed_at_utc)
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            rows = connection.execute(
                """
                SELECT 'POST /v1/crm/account-onboardings', receipt_hash, created_by, created_at_utc
                FROM crm.account_onboarding_receipts
                WHERE tenant_id = %s AND created_at_utc BETWEEN %s AND %s
                UNION ALL
                SELECT 'POST /v1/tasks/items', receipt_hash, created_by, created_at_utc
                FROM tasks.creation_receipts
                WHERE tenant_id = %s AND created_at_utc BETWEEN %s AND %s
                UNION ALL
                SELECT 'POST /v1/time-tracking/entries', receipt_hash, created_by, created_at_utc
                FROM time_tracking.entry_creation_receipts
                WHERE tenant_id = %s AND created_at_utc BETWEEN %s AND %s
                ORDER BY 4, 1, 2
                """,
                (
                    tenant_id,
                    effective,
                    closed,
                    tenant_id,
                    effective,
                    closed,
                    tenant_id,
                    effective,
                    closed,
                ),
            ).fetchall()
        return tuple(
            ProductivityPilotDomainReceipt(
                operation=str(row[0]),
                receipt_hash=str(row[1]),
                created_by=str(row[2]),
                committed_at_utc=_utc(row[3]),
            )
            for row in rows
        )


class ProductivityPilotClosureReportStore(Protocol):
    def append(self, record: ProductivityPilotClosureReport) -> ProductivityPilotClosureReport: ...

    def current(self, *, tenant_id: str) -> ProductivityPilotClosureReport | None: ...

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotClosureReport | None: ...  # noqa: E501


class InMemoryProductivityPilotClosureReportStore:
    def __init__(self, records: Iterable[ProductivityPilotClosureReport] = ()) -> None:
        self.records: list[ProductivityPilotClosureReport] = []
        for record in records:
            self.append(record)

    def append(self, record: ProductivityPilotClosureReport) -> ProductivityPilotClosureReport:
        if build_productivity_pilot_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot closure report evidence hash is invalid")
        if self.for_idempotency(tenant_id=record.tenant_id, idempotency_key_hash=record.idempotency_key_hash):
            raise ProductivityPilotClosureConflict("productivity pilot closure idempotency key exists")
        if any(item.tenant_id == record.tenant_id and item.closure_id == record.closure_id for item in self.records):
            raise ProductivityPilotClosureConflict("productivity pilot closure report already exists")
        self.records.append(record)
        return record

    def current(self, *, tenant_id: str) -> ProductivityPilotClosureReport | None:
        return next((item for item in reversed(self.records) if item.tenant_id == tenant_id), None)

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotClosureReport | None:
        return next(
            (
                item
                for item in reversed(self.records)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )


class PgProductivityPilotClosureReportStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, record: ProductivityPilotClosureReport) -> ProductivityPilotClosureReport:
        if build_productivity_pilot_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("productivity pilot closure report evidence hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_closure_reports (
                        tenant_id, closure_id, window_id, authorization_id,
                        runtime_window_evidence_hash, start_authorization_evidence_hash,
                        route_scope_hash, observation_manifest_hash, observation_count,
                        distinct_principal_hash_count, domain_receipt_manifest_hash,
                        domain_receipt_count, backup_sha256, postgres_restore_drill_report_hash,
                        backend_foundation_gate_hash, business_backend_release_gate_hash,
                        command_hash, idempotency_key_hash, human_confirmation_statement_hash,
                        change_request_ref, human_confirmation_reference, operations_owner_ref,
                        recovery_owner_ref, audit_chain_ref, closed_by, closed_at_utc,
                        recovery_observed_at_utc, closure_record, evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.closure_id,
                        record.window_id,
                        record.authorization_id,
                        record.runtime_window_evidence_hash,
                        record.start_authorization_evidence_hash,
                        record.route_scope_hash,
                        record.observation_manifest_hash,
                        record.observation_count,
                        record.distinct_principal_hash_count,
                        record.domain_receipt_manifest_hash,
                        len(record.domain_receipts),
                        record.recovery_evidence.backup_sha256,
                        record.recovery_evidence.postgres_restore_drill_report_hash,
                        record.recovery_evidence.backend_foundation_gate_hash,
                        record.recovery_evidence.business_backend_release_gate_hash,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.change_request_ref,
                        record.human_confirmation_reference,
                        record.operations_owner_ref,
                        record.recovery_owner_ref,
                        record.audit_chain_ref,
                        record.closed_by,
                        record.closed_at_utc,
                        record.recovery_evidence.observed_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotClosureConflict("productivity pilot closure report already exists") from exc
        return record

    def current(self, *, tenant_id: str) -> ProductivityPilotClosureReport | None:
        return self._one(tenant_id=tenant_id, where_sql="tenant_id = %s", value=tenant_id)

    def for_idempotency(self, *, tenant_id: str, idempotency_key_hash: str) -> ProductivityPilotClosureReport | None:
        return self._one(tenant_id=tenant_id, where_sql="idempotency_key_hash = %s", value=idempotency_key_hash)

    def _one(self, *, tenant_id: str, where_sql: str, value: str) -> ProductivityPilotClosureReport | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT closure_record
                FROM collabio.productivity_pilot_closure_reports
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY closed_at_utc DESC, evidence_hash DESC
                LIMIT 1
                """,
                (tenant_id, value),
            ).fetchone()
        if row is None:
            return None
        record = ProductivityPilotClosureReport.model_validate(row[0])
        if build_productivity_pilot_closure_report_hash(record) != record.evidence_hash:
            raise ValueError("persisted productivity pilot closure report evidence hash is invalid")
        return record


def build_productivity_pilot_closure_command_hash(command: ProductivityPilotClosureCommand) -> str:
    return _canonical_hash(command.model_dump(mode="json"))


def build_productivity_pilot_observation_manifest_hash(
    *, tenant_id: str, window_id: str, observations: tuple[ProductivityPilotRuntimeObservation, ...]
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_observation_manifest.v1",
            "tenant_id": tenant_id,
            "window_id": window_id,
            "observation_evidence_hashes": sorted(item.evidence_hash for item in observations),
        }
    )


def build_productivity_pilot_domain_receipt_manifest_hash(
    *, tenant_id: str, window_id: str, receipts: tuple[ProductivityPilotDomainReceiptEvidence, ...]
) -> str:
    return _canonical_hash(
        {
            "schema_version": "productivity_pilot_domain_receipt_manifest.v1",
            "tenant_id": tenant_id,
            "window_id": window_id,
            "receipts": [item.model_dump(mode="json") for item in sorted(receipts, key=lambda item: item.operation)],
        }
    )


def build_productivity_pilot_closure_report_hash(record: ProductivityPilotClosureReport) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotClosureService:
    def __init__(
        self,
        *,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        runtime_window_store: ProductivityPilotRuntimeWindowStore,
        domain_receipt_store: ProductivityPilotDomainReceiptStore,
        closure_report_store: ProductivityPilotClosureReportStore,
        runtime_enabled: bool,
    ) -> None:
        self.start_authorization_store = start_authorization_store
        self.runtime_window_store = runtime_window_store
        self.domain_receipt_store = domain_receipt_store
        self.closure_report_store = closure_report_store
        self.runtime_enabled = runtime_enabled

    def close(
        self, *, user_context: UserContext, command: ProductivityPilotClosureCommand
    ) -> ProductivityPilotClosureReport:
        if "security-admin" not in user_context.role_ids:
            raise PermissionError("security admin role required")
        if self.runtime_enabled:
            raise ProductivityPilotClosureConflict("productivity pilot runtime kill switch must be closed")
        window = self.runtime_window_store.current_window(tenant_id=user_context.tenant_id)
        if window is None:
            raise ProductivityPilotClosureConflict("authoritative productivity pilot runtime window not found")
        self._validate_window_binding(command=command, window=window)
        start = self.start_authorization_store.current(tenant_id=user_context.tenant_id)
        if start is None or build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash:
            raise ProductivityPilotClosureConflict("authoritative productivity pilot start authorization is invalid")
        if start.evidence_hash != window.start_authorization_evidence_hash:
            raise ProductivityPilotClosureConflict("runtime window no longer matches the start authorization")
        if user_context.user_id in {start.authorized_by, window.activated_by}:
            raise ProductivityPilotClosureConflict(
                "closure four-eyes control requires an actor distinct from start authorization and runtime activation"
            )
        if user_context.user_id in window.designated_principal_ids:
            raise ProductivityPilotClosureConflict("designated pilot principals cannot close their own runtime window")

        closed_at = _utc(command.closed_at_utc)
        if closed_at < _utc(window.effective_at_utc):
            raise ProductivityPilotClosureConflict("productivity pilot closure cannot predate the runtime window")
        recovery_observed_at = _utc(command.recovery_evidence.observed_at_utc)
        if recovery_observed_at < closed_at:
            raise ProductivityPilotClosureConflict("recovery evidence must be observed after runtime closure")

        command_hash = build_productivity_pilot_closure_command_hash(command)
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_closure_idempotency_key.v1",
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
                raise ProductivityPilotClosureConflict(
                    "productivity pilot closure idempotency key was used for a different command"
                )
            return existing.model_copy(update={"idempotent_replay": True})

        observations = self.runtime_window_store.observations_for_window(
            tenant_id=user_context.tenant_id,
            window_id=window.window_id,
        )
        operation_summaries, principal_hashes = self._validate_observations(
            window=window,
            observations=observations,
            closed_at=closed_at,
        )
        receipt_evidence = self._load_and_validate_receipts(
            tenant_id=user_context.tenant_id,
            window=window,
            closed_at=closed_at,
            expected_principal_hashes=principal_hashes,
        )
        self._validate_recovery_counts(
            evidence=command.recovery_evidence,
            observation_count=len(observations),
            domain_receipt_count=len(receipt_evidence),
        )

        draft = ProductivityPilotClosureReport(
            tenant_id=user_context.tenant_id,
            closure_id=command.closure_id,
            window_id=window.window_id,
            authorization_id=window.authorization_id,
            runtime_window_evidence_hash=window.evidence_hash,
            start_authorization_evidence_hash=start.evidence_hash,
            route_scope_hash=window.route_scope_hash,
            observation_manifest_hash=build_productivity_pilot_observation_manifest_hash(
                tenant_id=user_context.tenant_id,
                window_id=window.window_id,
                observations=observations,
            ),
            observation_count=len(observations),
            distinct_principal_hash_count=len(principal_hashes),
            operation_summaries=operation_summaries,
            domain_receipt_manifest_hash=build_productivity_pilot_domain_receipt_manifest_hash(
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
            closed_by=user_context.user_id,
            closed_at_utc=command.closed_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_closure_report_hash(draft)})
        return self.closure_report_store.append(record)

    def current(self, *, tenant_id: str) -> ProductivityPilotClosureReport | None:
        record = self.closure_report_store.current(tenant_id=tenant_id)
        if record is not None and build_productivity_pilot_closure_report_hash(record) != record.evidence_hash:
            raise ProductivityPilotClosureConflict("authoritative productivity pilot closure report is invalid")
        return record

    @staticmethod
    def _validate_window_binding(
        *, command: ProductivityPilotClosureCommand, window: ProductivityPilotRuntimeWindow
    ) -> None:
        if build_productivity_pilot_runtime_window_hash(window) != window.evidence_hash:
            raise ProductivityPilotClosureConflict("authoritative productivity pilot runtime window is invalid")
        if command.window_id != window.window_id or command.runtime_window_evidence_hash != window.evidence_hash:
            raise ProductivityPilotClosureConflict("closure command does not match the authoritative runtime window")

    @staticmethod
    def _validate_observations(
        *,
        window: ProductivityPilotRuntimeWindow,
        observations: tuple[ProductivityPilotRuntimeObservation, ...],
        closed_at: datetime,
    ) -> tuple[tuple[ProductivityPilotOperationObservationSummary, ...], set[str]]:
        if not observations:
            raise ProductivityPilotClosureConflict("productivity pilot closure requires runtime observations")
        operation_counts: Counter[str] = Counter()
        principal_hashes: set[str] = set()
        allowed_principal_hashes = {
            build_productivity_pilot_principal_observation_hash(
                tenant_id=window.tenant_id,
                principal_id=principal_id,
            )
            for principal_id in window.designated_principal_ids
        }
        for observation in observations:
            if build_productivity_pilot_runtime_observation_hash(observation) != observation.evidence_hash:
                raise ProductivityPilotClosureConflict("runtime observation evidence hash is invalid")
            if (
                observation.tenant_id != window.tenant_id
                or observation.window_id != window.window_id
                or observation.window_evidence_hash != window.evidence_hash
                or observation.start_authorization_evidence_hash != window.start_authorization_evidence_hash
            ):
                raise ProductivityPilotClosureConflict("runtime observation is not bound to the closure window")
            observed_at = _utc(observation.observed_at_utc)
            if observed_at < _utc(window.effective_at_utc) or observed_at > closed_at:
                raise ProductivityPilotClosureConflict("runtime observation is outside the closed interval")
            operation_counts[observation.operation] += 1
            principal_hashes.add(observation.principal_id_hash)
        if set(operation_counts) != set(window.allowed_api_operations) or any(
            count != 1 for count in operation_counts.values()
        ):
            raise ProductivityPilotClosureConflict(
                "closure requires exactly one observation for every authorized pilot operation"
            )
        if not principal_hashes or not principal_hashes.issubset(allowed_principal_hashes):
            raise ProductivityPilotClosureConflict("runtime observations include a non-designated principal")
        summaries = tuple(
            ProductivityPilotOperationObservationSummary(operation=operation, observation_count=count)
            for operation, count in sorted(operation_counts.items())
        )
        return summaries, principal_hashes

    def _load_and_validate_receipts(
        self,
        *,
        tenant_id: str,
        window: ProductivityPilotRuntimeWindow,
        closed_at: datetime,
        expected_principal_hashes: set[str],
    ) -> tuple[ProductivityPilotDomainReceiptEvidence, ...]:
        receipts = self.domain_receipt_store.for_interval(
            tenant_id=tenant_id,
            effective_at_utc=window.effective_at_utc,
            closed_at_utc=closed_at,
        )
        expected_write_operations = {item for item in window.allowed_api_operations if item.startswith("POST ")}
        operation_counts = Counter(item.operation for item in receipts)
        if set(operation_counts) != expected_write_operations or any(count != 1 for count in operation_counts.values()):
            raise ProductivityPilotClosureConflict(
                "closure requires exactly one authoritative domain receipt for every pilot write operation"
            )
        evidence: list[ProductivityPilotDomainReceiptEvidence] = []
        for receipt in receipts:
            if not SHA256_PATTERN.fullmatch(receipt.receipt_hash):
                raise ProductivityPilotClosureConflict("domain receipt hash is invalid")
            principal_hash = build_productivity_pilot_principal_observation_hash(
                tenant_id=tenant_id,
                principal_id=receipt.created_by,
            )
            if principal_hash not in expected_principal_hashes:
                raise ProductivityPilotClosureConflict("domain receipt actor was not observed in the runtime window")
            committed_at = _utc(receipt.committed_at_utc)
            if committed_at < _utc(window.effective_at_utc) or committed_at > closed_at:
                raise ProductivityPilotClosureConflict("domain receipt is outside the closed interval")
            evidence.append(
                ProductivityPilotDomainReceiptEvidence(
                    operation=receipt.operation,
                    receipt_hash=receipt.receipt_hash,
                    principal_id_hash=principal_hash,
                    committed_at_utc=receipt.committed_at_utc,
                )
            )
        return tuple(sorted(evidence, key=lambda item: item.operation))

    @staticmethod
    def _validate_recovery_counts(
        *,
        evidence: ProductivityPilotRecoveryEvidence,
        observation_count: int,
        domain_receipt_count: int,
    ) -> None:
        if (
            evidence.restored_runtime_window_count != 1
            or evidence.restored_observation_count != observation_count
            or evidence.restored_domain_receipt_count != domain_receipt_count
        ):
            raise ProductivityPilotClosureConflict(
                "recovery evidence counts do not match the authoritative closed pilot records"
            )


def build_default_productivity_pilot_domain_receipt_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotDomainReceiptStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_DOMAIN_RECEIPT_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotDomainReceiptStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_PRODUCTIVITY_PILOT_DOMAIN_RECEIPT_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot domain receipt store requires a database DSN")
        return PgProductivityPilotDomainReceiptStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot domain receipt store backend: {backend}")


def build_default_productivity_pilot_closure_report_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotClosureReportStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PRODUCTIVITY_PILOT_CLOSURE_REPORT_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotClosureReportStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_CLOSURE_REPORT_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL productivity pilot closure report store requires a database DSN")
        return PgProductivityPilotClosureReportStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported productivity pilot closure report store backend: {backend}")
