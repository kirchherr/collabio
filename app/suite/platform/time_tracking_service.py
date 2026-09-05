from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.time_tracking_module import (
    TIME_APPROVALS_READ_FEATURE_ID,
    TIME_ENTRIES_READ_FEATURE_ID,
    TIME_ENTRIES_WRITE_FEATURE_ID,
    TIME_TRACKING_MODULE_ID,
    TimeTrackingLifecycleState,
)

TIME_ENTRY_OBJECT_TYPE = "time.entry"
TIME_APPROVAL_OBJECT_TYPE = "time.approval"
TIME_ENTRY_SCHEMA_VERSION = "time_entry.v1"
TIME_APPROVAL_SCHEMA_VERSION = "time_approval.v1"
TIME_ENTRY_CREATION_RECEIPT_SCHEMA_VERSION = "time_entry_creation_receipt.v1"
TIME_ENTRY_CREATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "time-manager", "time-worker"})
TIME_DELEGATED_CREATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "time-manager"})
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimeTrackingConflict(ValueError):
    pass


class TimeTrackingAssignmentError(ValueError):
    pass


class TimeApprovalState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTION_REQUESTED = "correction_requested"
    CANCELLED = "cancelled"


class CreateTimeEntryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_reference: str = Field(min_length=3, max_length=300)
    entry_object_id: str = Field(min_length=1, max_length=200)
    entry_number: str = Field(min_length=1, max_length=100)
    worker_principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    work_date: date
    started_at_utc: datetime
    ended_at_utc: datetime
    project_reference: str | None = Field(default=None, max_length=300)
    cost_center_reference: str | None = Field(default=None, max_length=300)
    approval_object_id: str = Field(min_length=1, max_length=200)
    approval_number: str = Field(min_length=1, max_length=100)
    source_system: str = "native"

    @field_validator("mutation_reference")
    @classmethod
    def require_mutation_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("mutation_reference must be a namespaced reference")
        return normalized

    @field_validator("entry_object_id", "entry_number", "approval_object_id", "approval_number")
    @classmethod
    def require_single_line_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("Time Tracking identifiers must be non-empty single-line values")
        return normalized

    @field_validator("worker_principal_id")
    @classmethod
    def normalize_worker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("worker_principal_id must not be empty")
        return normalized

    @field_validator("project_reference", "cost_center_reference")
    @classmethod
    def validate_optional_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("Time Tracking link references must be namespaced")
        return normalized

    @field_validator("started_at_utc", "ended_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Time Tracking timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("source_system")
    @classmethod
    def require_source_system(cls, value: str) -> str:
        normalized = value.strip()
        if not SOURCE_SYSTEM_PATTERN.fullmatch(normalized):
            raise ValueError("source_system must be lowercase and non-empty")
        return normalized

    @model_validator(mode="after")
    def require_valid_interval_and_ids(self) -> CreateTimeEntryCommand:
        if self.entry_object_id == self.approval_object_id:
            raise ValueError("entry and approval object IDs must differ")
        duration_seconds = (self.ended_at_utc - self.started_at_utc).total_seconds()
        if duration_seconds <= 0 or duration_seconds > 24 * 60 * 60:
            raise ValueError("Time entry duration must be greater than zero and no longer than 24 hours")
        if duration_seconds % 60 != 0:
            raise ValueError("Time entry duration must resolve to complete minutes")
        return self

    @property
    def duration_minutes(self) -> int:
        return int((self.ended_at_utc - self.started_at_utc).total_seconds() // 60)


class TimeEntryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TIME_ENTRY_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: TimeTrackingLifecycleState = TimeTrackingLifecycleState.RECORDED
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TIME_ENTRY_SCHEMA_VERSION
    entry_number: str
    worker_principal_id: str
    work_date: date
    started_at_utc: datetime
    ended_at_utc: datetime
    duration_minutes: int = Field(gt=0, le=1440)
    project_reference: str | None = None
    cost_center_reference: str | None = None

    @model_validator(mode="after")
    def require_governed_metadata(self) -> TimeEntryRecord:
        if self.object_type != TIME_ENTRY_OBJECT_TYPE or self.schema_version != TIME_ENTRY_SCHEMA_VERSION:
            raise ValueError("Time entry identity metadata is inconsistent")
        if self.data_classification != DataClass.PERSONAL:
            raise ValueError("Time entry classification must be personal")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("Time entry retention policy is invalid")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("Time entry Legal Hold state is invalid")
        if self.legal_hold_state == "active" and self.retention_policy_id != "rp-legal-hold":
            raise ValueError("active Time entry Legal Hold requires rp-legal-hold")
        if not REF_PATTERN.fullmatch(self.kms_key_ref) or not REF_PATTERN.fullmatch(self.audit_chain_ref):
            raise ValueError("Time entry security references must be namespaced")
        if self.ended_at_utc <= self.started_at_utc:
            raise ValueError("Time entry end must be after start")
        expected_minutes = int((self.ended_at_utc - self.started_at_utc).total_seconds() // 60)
        if expected_minutes != self.duration_minutes:
            raise ValueError("Time entry duration must match timestamps")
        return self


class TimeApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TIME_APPROVAL_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: TimeTrackingLifecycleState = TimeTrackingLifecycleState.NOT_SUBMITTED
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TIME_APPROVAL_SCHEMA_VERSION
    entry_object_id: str
    approval_number: str
    approval_state: TimeApprovalState = TimeApprovalState.NOT_SUBMITTED
    worker_principal_id: str
    approver_principal_id: str | None = None
    decided_at_utc: datetime | None = None

    @model_validator(mode="after")
    def require_initial_state(self) -> TimeApprovalRecord:
        if self.object_type != TIME_APPROVAL_OBJECT_TYPE or self.schema_version != TIME_APPROVAL_SCHEMA_VERSION:
            raise ValueError("Time approval identity metadata is inconsistent")
        if self.data_classification != DataClass.PERSONAL:
            raise ValueError("Time approval classification must be personal")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("Time approval retention policy is invalid")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("Time approval Legal Hold state is invalid")
        if self.legal_hold_state == "active" and self.retention_policy_id != "rp-legal-hold":
            raise ValueError("active Time approval Legal Hold requires rp-legal-hold")
        if self.approval_state != TimeApprovalState.NOT_SUBMITTED:
            raise ValueError("First-slice Time approval must be not_submitted")
        if self.lifecycle_state != TimeTrackingLifecycleState.NOT_SUBMITTED:
            raise ValueError("Time approval lifecycle must match initial state")
        if self.approver_principal_id is not None or self.decided_at_utc is not None:
            raise ValueError("not_submitted Time approval must not contain a decision")
        if not REF_PATTERN.fullmatch(self.kms_key_ref) or not REF_PATTERN.fullmatch(self.audit_chain_ref):
            raise ValueError("Time approval security references must be namespaced")
        return self


class TimeEntryCreationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    mutation_reference: str
    command_hash: str
    created_by: str
    worker_principal_id: str
    entry_object_id: str
    approval_object_id: str
    duration_minutes: int = Field(gt=0, le=1440)
    acl_manifest: tuple[str, ...]
    audit_chain_ref: str
    receipt_hash: str
    created_at_utc: datetime
    schema_version: str = TIME_ENTRY_CREATION_RECEIPT_SCHEMA_VERSION


class TimeEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    entry_number: str
    worker_principal_id: str
    work_date: date
    started_at_utc: datetime
    ended_at_utc: datetime
    duration_minutes: int
    project_reference: str | None
    cost_center_reference: str | None
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: TimeTrackingLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class TimeApprovalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    entry_object_id: str
    approval_number: str
    approval_state: TimeApprovalState
    worker_principal_id: str
    approver_principal_id: str | None
    decided_at_utc: datetime | None
    created_by: str
    created_at_utc: datetime
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: TimeTrackingLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_entry_access_checked: bool = True


class TimeEntriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TIME_TRACKING_MODULE_ID
    feature_id: str = TIME_ENTRIES_READ_FEATURE_ID
    entries: list[TimeEntryView]
    audit_event_id: str


class TimeApprovalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TIME_TRACKING_MODULE_ID
    feature_id: str = TIME_APPROVALS_READ_FEATURE_ID
    approvals: list[TimeApprovalView]
    audit_event_id: str


class TimeEntryCreationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TIME_TRACKING_MODULE_ID
    feature_id: str = TIME_ENTRIES_WRITE_FEATURE_ID
    entry: TimeEntryView
    approval: TimeApprovalView
    receipt: TimeEntryCreationReceipt
    acl_grant_count: int
    idempotent_replay: bool
    atomic_transaction_committed: bool = True
    receipt_content_included: bool = False
    audit_event_id: str


class TimeTrackingStore(Protocol):
    def list_entries(self, *, tenant_id: str) -> Sequence[TimeEntryRecord]: ...

    def list_approvals(self, *, tenant_id: str) -> Sequence[TimeApprovalRecord]: ...

    def create_entry(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTimeEntryCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeEntryCreationReceipt, bool]: ...


TimeRecord = TypeVar("TimeRecord", TimeEntryRecord, TimeApprovalRecord)


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _command_hash(command: CreateTimeEntryCommand, *, user_id: str, worker_id: str) -> str:
    return _stable_hash(
        {
            "command": command.model_dump(mode="json"),
            "created_by": user_id,
            "resolved_worker": worker_id,
        }
    )


def _acl_manifest(
    *,
    entry_object_id: str,
    approval_object_id: str,
    creator_id: str,
    worker_id: str,
) -> tuple[str, ...]:
    grants = [
        f"{TIME_ENTRY_OBJECT_TYPE}:{entry_object_id}:user:{creator_id}:admin:1",
        f"{TIME_APPROVAL_OBJECT_TYPE}:{approval_object_id}:user:{creator_id}:admin:1",
    ]
    if worker_id != creator_id:
        grants.extend(
            (
                f"{TIME_ENTRY_OBJECT_TYPE}:{entry_object_id}:user:{worker_id}:write:1",
                f"{TIME_APPROVAL_OBJECT_TYPE}:{approval_object_id}:user:{worker_id}:read:1",
            )
        )
    return tuple(grants)


def _build_records_and_receipt(
    *,
    tenant_id: str,
    user_id: str,
    command: CreateTimeEntryCommand,
    created_at_utc: datetime,
) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeEntryCreationReceipt]:
    worker_id = command.worker_principal_id or user_id
    command_hash = _command_hash(command, user_id=user_id, worker_id=worker_id)
    audit_chain_ref = f"audit:time-entry-create:{command_hash.removeprefix('sha256:')}"
    kms_key_ref = f"kms:{tenant_id}:time-tracking"
    entry = TimeEntryRecord(
        tenant_id=tenant_id,
        object_id=command.entry_object_id,
        owner_principal_id=worker_id,
        created_by=user_id,
        created_at_utc=created_at_utc,
        updated_at_utc=created_at_utc,
        kms_key_ref=kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=command.source_system,
        entry_number=command.entry_number,
        worker_principal_id=worker_id,
        work_date=command.work_date,
        started_at_utc=command.started_at_utc,
        ended_at_utc=command.ended_at_utc,
        duration_minutes=command.duration_minutes,
        project_reference=command.project_reference,
        cost_center_reference=command.cost_center_reference,
    )
    approval = TimeApprovalRecord(
        tenant_id=tenant_id,
        object_id=command.approval_object_id,
        owner_principal_id=worker_id,
        created_by=user_id,
        created_at_utc=created_at_utc,
        updated_at_utc=created_at_utc,
        kms_key_ref=kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=command.source_system,
        entry_object_id=entry.object_id,
        approval_number=command.approval_number,
        worker_principal_id=worker_id,
    )
    acl_manifest = _acl_manifest(
        entry_object_id=entry.object_id,
        approval_object_id=approval.object_id,
        creator_id=user_id,
        worker_id=worker_id,
    )
    receipt_hash = _stable_hash(
        {
            "tenant_id": tenant_id,
            "mutation_reference": command.mutation_reference,
            "command_hash": command_hash,
            "created_by": user_id,
            "worker_principal_id": worker_id,
            "entry_object_id": entry.object_id,
            "approval_object_id": approval.object_id,
            "duration_minutes": entry.duration_minutes,
            "acl_manifest": acl_manifest,
            "audit_chain_ref": audit_chain_ref,
            "schema_version": TIME_ENTRY_CREATION_RECEIPT_SCHEMA_VERSION,
        }
    )
    receipt = TimeEntryCreationReceipt(
        tenant_id=tenant_id,
        mutation_reference=command.mutation_reference,
        command_hash=command_hash,
        created_by=user_id,
        worker_principal_id=worker_id,
        entry_object_id=entry.object_id,
        approval_object_id=approval.object_id,
        duration_minutes=entry.duration_minutes,
        acl_manifest=acl_manifest,
        audit_chain_ref=audit_chain_ref,
        receipt_hash=receipt_hash,
        created_at_utc=created_at_utc,
    )
    return entry, approval, receipt


class InMemoryTimeTrackingStore:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], TimeEntryRecord] = {}
        self._approvals: dict[tuple[str, str], TimeApprovalRecord] = {}
        self._receipts: dict[tuple[str, str], TimeEntryCreationReceipt] = {}

    def list_entries(self, *, tenant_id: str) -> Sequence[TimeEntryRecord]:
        return tuple(record for (stored_tenant, _), record in self._entries.items() if stored_tenant == tenant_id)

    def list_approvals(self, *, tenant_id: str) -> Sequence[TimeApprovalRecord]:
        return tuple(record for (stored_tenant, _), record in self._approvals.items() if stored_tenant == tenant_id)

    def create_entry(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTimeEntryCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeEntryCreationReceipt, bool]:
        key = (tenant_id, command.mutation_reference)
        worker_id = command.worker_principal_id or user_id
        existing = self._receipts.get(key)
        if existing is not None:
            if existing.command_hash != _command_hash(command, user_id=user_id, worker_id=worker_id):
                raise TimeTrackingConflict("mutation_reference already belongs to a different time entry command")
            return (
                self._entries[(tenant_id, existing.entry_object_id)],
                self._approvals[(tenant_id, existing.approval_object_id)],
                existing,
                True,
            )
        if (tenant_id, command.entry_object_id) in self._entries:
            raise TimeTrackingConflict("time entry object already exists")
        if (tenant_id, command.approval_object_id) in self._approvals:
            raise TimeTrackingConflict("time approval object already exists")
        entry, approval, receipt = _build_records_and_receipt(
            tenant_id=tenant_id,
            user_id=user_id,
            command=command,
            created_at_utc=utc_now(),
        )
        self._entries[(tenant_id, entry.object_id)] = entry
        self._approvals[(tenant_id, approval.object_id)] = approval
        self._receipts[key] = receipt
        return entry, approval, receipt, False


class PgTimeTrackingStore:
    def __init__(self, *, read_database_dsn: str, write_database_dsn: str) -> None:
        if not read_database_dsn.strip() or not write_database_dsn.strip():
            raise ValueError("Time Tracking PostgreSQL DSNs must not be empty")
        self.read_database_dsn = read_database_dsn
        self.write_database_dsn = write_database_dsn

    def list_entries(self, *, tenant_id: str) -> Sequence[TimeEntryRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="time_tracking.entries",
            order_by="work_date DESC, started_at_utc DESC, object_id",
            record_type=TimeEntryRecord,
        )

    def list_approvals(self, *, tenant_id: str) -> Sequence[TimeApprovalRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="time_tracking.approvals",
            order_by="created_at_utc DESC, object_id",
            record_type=TimeApprovalRecord,
        )

    def create_entry(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTimeEntryCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeEntryCreationReceipt, bool]:
        worker_id = command.worker_principal_id or user_id
        command_hash = _command_hash(command, user_id=user_id, worker_id=worker_id)
        try:
            with psycopg.connect(self.write_database_dsn, row_factory=dict_row) as connection:
                connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{tenant_id}:{command.mutation_reference}",),
                )
                existing = self._load_receipt(
                    connection,
                    tenant_id=tenant_id,
                    mutation_reference=command.mutation_reference,
                )
                if existing is not None:
                    if existing.command_hash != command_hash:
                        raise TimeTrackingConflict(
                            "mutation_reference already belongs to a different time entry command"
                        )
                    return (
                        self._load_entry(connection, tenant_id=tenant_id, object_id=existing.entry_object_id),
                        self._load_approval(
                            connection,
                            tenant_id=tenant_id,
                            object_id=existing.approval_object_id,
                        ),
                        existing,
                        True,
                    )
                if worker_id != user_id and not self._active_tenant_principal_exists(
                    connection,
                    tenant_id=tenant_id,
                    user_id=worker_id,
                ):
                    raise TimeTrackingAssignmentError("worker principal is not an active tenant member")

                entry, approval, receipt = _build_records_and_receipt(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    command=command,
                    created_at_utc=utc_now(),
                )
                self._insert_entry(connection, entry)
                self._insert_approval(connection, approval)
                self._insert_acls(connection, entry=entry, approval=approval, receipt=receipt)
                self._insert_receipt(connection, receipt)
                return entry, approval, receipt, False
        except psycopg.errors.UniqueViolation as exc:
            raise TimeTrackingConflict("time entry IDs, numbers, approval IDs, or ACL entries already exist") from exc

    def _list_records(
        self,
        *,
        tenant_id: str,
        table: str,
        order_by: str,
        record_type: type[TimeRecord],
    ) -> tuple[TimeRecord, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        with psycopg.connect(self.read_database_dsn, row_factory=dict_row) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE tenant_id = %s ORDER BY {order_by}",
                (tenant_id,),
            ).fetchall()
        return tuple(record_type.model_validate(row) for row in rows)

    @staticmethod
    def _active_tenant_principal_exists(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM collabio.tenant_principals AS principal
            JOIN collabio.tenant_principal_memberships AS membership
              ON membership.tenant_id = principal.tenant_id
             AND membership.issuer = principal.issuer
             AND membership.subject = principal.subject
            WHERE principal.tenant_id = %s
              AND principal.user_id = %s
              AND principal.status = 'active'
              AND membership.status = 'active'
            """,
            (tenant_id, user_id),
        ).fetchone()
        return row is not None

    @staticmethod
    def _insert_entry(connection: psycopg.Connection[dict[str, Any]], entry: TimeEntryRecord) -> None:
        connection.execute(
            """
            INSERT INTO time_tracking.entries (
                tenant_id, object_id, owner_principal_id, created_by, created_at_utc, updated_at_utc,
                kms_key_ref, audit_chain_ref, source_system, entry_number, worker_principal_id,
                work_date, started_at_utc, ended_at_utc, duration_minutes,
                project_reference, cost_center_reference
            ) VALUES (
                %(tenant_id)s, %(object_id)s, %(owner_principal_id)s, %(created_by)s,
                %(created_at_utc)s, %(updated_at_utc)s, %(kms_key_ref)s, %(audit_chain_ref)s,
                %(source_system)s, %(entry_number)s, %(worker_principal_id)s,
                %(work_date)s, %(started_at_utc)s, %(ended_at_utc)s, %(duration_minutes)s,
                %(project_reference)s, %(cost_center_reference)s
            )
            """,
            entry.model_dump(),
        )

    @staticmethod
    def _insert_approval(
        connection: psycopg.Connection[dict[str, Any]],
        approval: TimeApprovalRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO time_tracking.approvals (
                tenant_id, object_id, owner_principal_id, created_by, created_at_utc, updated_at_utc,
                kms_key_ref, audit_chain_ref, source_system, entry_object_id, approval_number,
                approval_state, worker_principal_id, approver_principal_id, decided_at_utc
            ) VALUES (
                %(tenant_id)s, %(object_id)s, %(owner_principal_id)s, %(created_by)s,
                %(created_at_utc)s, %(updated_at_utc)s, %(kms_key_ref)s, %(audit_chain_ref)s,
                %(source_system)s, %(entry_object_id)s, %(approval_number)s,
                %(approval_state)s, %(worker_principal_id)s, %(approver_principal_id)s,
                %(decided_at_utc)s
            )
            """,
            approval.model_dump(),
        )

    @staticmethod
    def _insert_acls(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        entry: TimeEntryRecord,
        approval: TimeApprovalRecord,
        receipt: TimeEntryCreationReceipt,
    ) -> None:
        grants = [
            (entry.object_id, entry.object_type, receipt.created_by, "admin"),
            (approval.object_id, approval.object_type, receipt.created_by, "admin"),
        ]
        if receipt.worker_principal_id != receipt.created_by:
            grants.extend(
                (
                    (entry.object_id, entry.object_type, receipt.worker_principal_id, "write"),
                    (approval.object_id, approval.object_type, receipt.worker_principal_id, "read"),
                )
            )
        for object_id, object_type, subject_id, permission in grants:
            connection.execute(
                """
                INSERT INTO collabio.object_acl_entries (
                    tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                    permission, acl_version, status, audit_chain_ref
                ) VALUES (%s, %s, %s, 'user', %s, %s, 1, 'active', %s)
                """,
                (
                    entry.tenant_id,
                    object_id,
                    object_type,
                    subject_id,
                    permission,
                    receipt.audit_chain_ref,
                ),
            )

    @staticmethod
    def _insert_receipt(
        connection: psycopg.Connection[dict[str, Any]],
        receipt: TimeEntryCreationReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO time_tracking.entry_creation_receipts (
                tenant_id, mutation_reference, command_hash, created_by, worker_principal_id,
                entry_object_id, approval_object_id, duration_minutes, acl_manifest,
                audit_chain_ref, receipt_hash, created_at_utc
            ) VALUES (
                %(tenant_id)s, %(mutation_reference)s, %(command_hash)s, %(created_by)s,
                %(worker_principal_id)s, %(entry_object_id)s, %(approval_object_id)s,
                %(duration_minutes)s, %(acl_manifest)s, %(audit_chain_ref)s,
                %(receipt_hash)s, %(created_at_utc)s
            )
            """,
            {
                **receipt.model_dump(exclude={"acl_manifest", "schema_version"}),
                "acl_manifest": Jsonb(list(receipt.acl_manifest)),
            },
        )

    @staticmethod
    def _load_receipt(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        mutation_reference: str,
    ) -> TimeEntryCreationReceipt | None:
        row = connection.execute(
            """
            SELECT * FROM time_tracking.entry_creation_receipts
            WHERE tenant_id = %s AND mutation_reference = %s
            """,
            (tenant_id, mutation_reference),
        ).fetchone()
        if row is None:
            return None
        return TimeEntryCreationReceipt.model_validate(
            {**row, "acl_manifest": tuple(str(item) for item in row["acl_manifest"])}
        )

    @staticmethod
    def _load_entry(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        object_id: str,
    ) -> TimeEntryRecord:
        row = connection.execute(
            "SELECT * FROM time_tracking.entries WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, object_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("time entry creation receipt points to a missing entry")
        return TimeEntryRecord.model_validate(row)

    @staticmethod
    def _load_approval(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        object_id: str,
    ) -> TimeApprovalRecord:
        row = connection.execute(
            "SELECT * FROM time_tracking.approvals WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, object_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("time entry creation receipt points to a missing approval")
        return TimeApprovalRecord.model_validate(row)


def time_entry_view(record: TimeEntryRecord) -> TimeEntryView:
    return TimeEntryView(**record.model_dump(exclude={"tenant_id", "kms_key_ref"}))


def time_approval_view(record: TimeApprovalRecord) -> TimeApprovalView:
    return TimeApprovalView(
        **record.model_dump(exclude={"tenant_id", "owner_principal_id", "updated_at_utc", "kms_key_ref"})
    )


class TimeTrackingService:
    def __init__(self, *, store: TimeTrackingStore, audit_logger: InMemoryAuditLogger) -> None:
        self.store = store
        self.audit_logger = audit_logger

    def create_entry(
        self,
        *,
        user_context: UserContext,
        command: CreateTimeEntryCommand,
    ) -> TimeEntryCreationResponse:
        if user_context.role_ids.isdisjoint(TIME_ENTRY_CREATOR_ROLES):
            raise PermissionError("Time Tracking creator role required")
        worker_id = command.worker_principal_id or user_context.user_id
        if worker_id != user_context.user_id and user_context.role_ids.isdisjoint(TIME_DELEGATED_CREATOR_ROLES):
            raise PermissionError("Time Tracking delegated entry role required")
        entry, approval, receipt, replayed = self.store.create_entry(
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            command=command,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type=(
                "time_tracking.entry.creation.replayed" if replayed else "time_tracking.entry.creation.committed"
            ),
            source_object_ids=[entry.object_id, approval.object_id],
            metadata={
                "module_id": TIME_TRACKING_MODULE_ID,
                "feature_id": TIME_ENTRIES_WRITE_FEATURE_ID,
                "mutation_reference": receipt.mutation_reference,
                "command_hash": receipt.command_hash,
                "receipt_hash": receipt.receipt_hash,
                "duration_minutes": receipt.duration_minutes,
                "acl_grant_count": len(receipt.acl_manifest),
                "atomic_transaction_committed": True,
                "idempotent_replay": replayed,
                "approval_state": approval.approval_state,
                "result_contract": "governed_time_entry_creation_with_initial_approval",
                "receipt_content_included": False,
            },
        )
        return TimeEntryCreationResponse(
            tenant_id=user_context.tenant_id,
            entry=time_entry_view(entry),
            approval=time_approval_view(approval),
            receipt=receipt,
            acl_grant_count=len(receipt.acl_manifest),
            idempotent_replay=replayed,
            audit_event_id=event.event_id,
        )

    def list_entries(self, *, user_context: UserContext) -> TimeEntriesResponse:
        candidates = tuple(self.store.list_entries(tenant_id=user_context.tenant_id))
        authorized = sorted(
            (entry for entry in candidates if entry.object_id in user_context.readable_object_ids),
            key=lambda entry: (entry.work_date, entry.started_at_utc, entry.object_id),
            reverse=True,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="time_tracking.entries.read",
            source_object_ids=[entry.object_id for entry in authorized],
            metadata={
                "module_id": TIME_TRACKING_MODULE_ID,
                "feature_id": TIME_ENTRIES_READ_FEATURE_ID,
                "candidate_count": len(candidates),
                "result_count": len(authorized),
                "acl_filtered_count": len(candidates) - len(authorized),
                "result_contract": "authorized_governed_time_entry_metadata",
            },
        )
        return TimeEntriesResponse(
            tenant_id=user_context.tenant_id,
            entries=[time_entry_view(entry) for entry in authorized],
            audit_event_id=event.event_id,
        )

    def list_approvals(self, *, user_context: UserContext) -> TimeApprovalsResponse:
        candidates = tuple(self.store.list_approvals(tenant_id=user_context.tenant_id))
        authorized = sorted(
            (
                approval
                for approval in candidates
                if approval.object_id in user_context.readable_object_ids
                and approval.entry_object_id in user_context.readable_object_ids
            ),
            key=lambda approval: (approval.created_at_utc, approval.object_id),
            reverse=True,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="time_tracking.approvals.read",
            source_object_ids=[approval.object_id for approval in authorized],
            metadata={
                "module_id": TIME_TRACKING_MODULE_ID,
                "feature_id": TIME_APPROVALS_READ_FEATURE_ID,
                "candidate_count": len(candidates),
                "result_count": len(authorized),
                "acl_filtered_count": len(candidates) - len(authorized),
                "linked_entry_acl_required": True,
                "result_contract": "authorized_time_approval_state_metadata",
            },
        )
        return TimeApprovalsResponse(
            tenant_id=user_context.tenant_id,
            approvals=[time_approval_view(approval) for approval in authorized],
            audit_event_id=event.event_id,
        )


def build_default_time_tracking_store(environ: Mapping[str, str] | None = None) -> TimeTrackingStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TIME_TRACKING_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTimeTrackingStore()
    if backend in {"postgres", "postgresql", "pg"}:
        read_dsn = env.get("SUITE_TIME_TRACKING_READ_DSN") or env.get("SUITE_DATABASE_DSN")
        write_dsn = env.get("SUITE_TIME_TRACKING_WRITE_DSN") or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
        if not read_dsn or not write_dsn:
            raise ValueError("PostgreSQL Time Tracking requires read and write DSNs")
        return PgTimeTrackingStore(read_database_dsn=read_dsn, write_database_dsn=write_dsn)
    raise ValueError(f"Unsupported SUITE_TIME_TRACKING_BACKEND: {backend}")
