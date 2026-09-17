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
    TIME_APPROVALS_WRITE_FEATURE_ID,
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
TIME_APPROVAL_DECISION_SCHEMA_VERSION = "time_approval_decision.v1"
TIME_ENTRY_CREATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "time-manager", "time-worker"})
TIME_DELEGATED_CREATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "time-manager"})
TIME_APPROVER_ROLES = frozenset({"tenant-admin", "tenant_admin", "time-manager", "time-approver"})
ZERO_HASH = "sha256:" + "0" * 64
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimeTrackingConflict(ValueError):
    pass


class TimeTrackingAssignmentError(ValueError):
    pass


class TimeTrackingNotFound(LookupError):
    pass


class TimeApprovalState(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTION_REQUESTED = "correction_requested"
    CANCELLED = "cancelled"


class TimeApprovalAction(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CORRECTION = "request_correction"


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


class TransitionTimeApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_reference: str = Field(min_length=3, max_length=300)
    decision_object_id: str = Field(min_length=1, max_length=200)
    expected_state: TimeApprovalState
    target_state: TimeApprovalState
    action: TimeApprovalAction
    human_confirmation_statement: str | None = Field(default=None, max_length=500)
    source_system: str = "native"

    @field_validator("mutation_reference")
    @classmethod
    def require_mutation_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("mutation_reference must be a namespaced reference")
        return normalized

    @field_validator("decision_object_id")
    @classmethod
    def require_decision_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("decision_object_id must be a non-empty single-line value")
        return normalized

    @field_validator("human_confirmation_statement")
    @classmethod
    def normalize_confirmation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("human confirmation must be a non-empty single-line value")
        return normalized

    @field_validator("source_system")
    @classmethod
    def require_source_system(cls, value: str) -> str:
        normalized = value.strip()
        if not SOURCE_SYSTEM_PATTERN.fullmatch(normalized):
            raise ValueError("source_system must be lowercase and non-empty")
        return normalized

    @model_validator(mode="after")
    def require_decision_shape(self) -> TransitionTimeApprovalCommand:
        expected_targets = {
            TimeApprovalAction.SUBMIT: TimeApprovalState.SUBMITTED,
            TimeApprovalAction.APPROVE: TimeApprovalState.APPROVED,
            TimeApprovalAction.REJECT: TimeApprovalState.REJECTED,
            TimeApprovalAction.REQUEST_CORRECTION: TimeApprovalState.CORRECTION_REQUESTED,
        }
        if self.expected_state == self.target_state:
            raise ValueError("time approval transition must change state")
        if expected_targets[self.action] != self.target_state:
            raise ValueError("time approval action and target state do not match")
        return self


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


class TimeApprovalDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    approval_object_id: str
    entry_object_id: str
    mutation_reference: str
    command_hash: str
    sequence_no: int = Field(ge=1)
    previous_decision_hash: str
    from_state: TimeApprovalState
    to_state: TimeApprovalState
    action: TimeApprovalAction
    decided_by: str
    decided_at_utc: datetime
    confirmation_statement_hash: str | None = None
    audit_chain_ref: str
    decision_hash: str
    source_system: str = "native"
    schema_version: str = TIME_APPROVAL_DECISION_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_append_only_evidence(self) -> TimeApprovalDecisionRecord:
        hashes = (self.command_hash, self.previous_decision_hash, self.decision_hash)
        if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in hashes):
            raise ValueError("time approval decision hashes must use sha256")
        if self.action == TimeApprovalAction.SUBMIT:
            if self.confirmation_statement_hash is not None:
                raise ValueError("submission must not carry decision confirmation evidence")
        elif self.confirmation_statement_hash is None or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", self.confirmation_statement_hash
        ):
            raise ValueError("time approval decision requires sha256 confirmation evidence")
        if self.from_state == self.to_state:
            raise ValueError("time approval decision states must differ")
        if not REF_PATTERN.fullmatch(self.audit_chain_ref):
            raise ValueError("time approval decision audit reference must be namespaced")
        return self


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


class TimeApprovalDecisionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    approval_object_id: str
    entry_object_id: str
    mutation_reference: str
    sequence_no: int
    previous_decision_hash: str
    from_state: TimeApprovalState
    to_state: TimeApprovalState
    action: TimeApprovalAction
    decided_by: str
    decided_at_utc: datetime
    confirmation_statement_hash: str | None
    audit_chain_ref: str
    decision_hash: str
    source_system: str
    schema_version: str


class TimeApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TIME_TRACKING_MODULE_ID
    feature_id: str = TIME_APPROVALS_WRITE_FEATURE_ID
    entry: TimeEntryView
    approval: TimeApprovalView
    decision: TimeApprovalDecisionView
    idempotent_replay: bool
    atomic_transaction_committed: bool = True
    decision_content_included: bool = False
    maker_checker_verified: bool
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

    def transition_approval(
        self,
        *,
        tenant_id: str,
        user_id: str,
        approval_object_id: str,
        command: TransitionTimeApprovalCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeApprovalDecisionRecord, bool]: ...


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


TIME_APPROVAL_TRANSITION_GRAPH = frozenset(
    {
        (TimeApprovalState.NOT_SUBMITTED, TimeApprovalAction.SUBMIT, TimeApprovalState.SUBMITTED),
        (TimeApprovalState.SUBMITTED, TimeApprovalAction.APPROVE, TimeApprovalState.APPROVED),
        (TimeApprovalState.SUBMITTED, TimeApprovalAction.REJECT, TimeApprovalState.REJECTED),
        (
            TimeApprovalState.SUBMITTED,
            TimeApprovalAction.REQUEST_CORRECTION,
            TimeApprovalState.CORRECTION_REQUESTED,
        ),
    }
)


def time_approval_confirmation_statement(*, approval_object_id: str, target_state: TimeApprovalState) -> str:
    return f"I explicitly confirm time approval {approval_object_id} decision {target_state.value}."


def _approval_decision_command_hash(
    command: TransitionTimeApprovalCommand,
    *,
    approval_object_id: str,
    user_id: str,
) -> str:
    return _stable_hash(
        {
            "command": command.model_dump(mode="json"),
            "approval_object_id": approval_object_id,
            "decided_by": user_id,
        }
    )


def _require_approval_transition(
    *,
    approval_object_id: str,
    current_state: TimeApprovalState,
    command: TransitionTimeApprovalCommand,
) -> str | None:
    if command.expected_state != current_state:
        raise TimeTrackingConflict(
            f"time approval changed: expected {command.expected_state.value}, current {current_state.value}"
        )
    if (current_state, command.action, command.target_state) not in TIME_APPROVAL_TRANSITION_GRAPH:
        raise TimeTrackingConflict(
            f"time approval transition {current_state.value}->{command.target_state.value} is not allowed"
        )
    if command.action == TimeApprovalAction.SUBMIT:
        if command.human_confirmation_statement is not None:
            raise TimeTrackingConflict("time approval submission must not include decision confirmation")
        return None
    expected_confirmation = time_approval_confirmation_statement(
        approval_object_id=approval_object_id,
        target_state=command.target_state,
    )
    if command.human_confirmation_statement != expected_confirmation:
        raise TimeTrackingConflict("exact human confirmation required for time approval decision")
    return _stable_hash(expected_confirmation)


def _apply_time_approval_decision(
    *,
    entry: TimeEntryRecord,
    approval: TimeApprovalRecord,
    decision: TimeApprovalDecisionRecord,
) -> tuple[TimeEntryRecord, TimeApprovalRecord]:
    lifecycle_state = TimeTrackingLifecycleState(decision.to_state.value)
    final_decision = decision.action != TimeApprovalAction.SUBMIT
    transitioned_entry = entry.model_copy(
        update={
            "lifecycle_state": lifecycle_state,
            "updated_at_utc": decision.decided_at_utc,
        }
    )
    transitioned_approval = approval.model_copy(
        update={
            "approval_state": decision.to_state,
            "lifecycle_state": lifecycle_state,
            "updated_at_utc": decision.decided_at_utc,
            "approver_principal_id": decision.decided_by if final_decision else None,
            "decided_at_utc": decision.decided_at_utc if final_decision else None,
        }
    )
    return transitioned_entry, transitioned_approval


def _build_time_approval_decision(
    *,
    tenant_id: str,
    user_id: str,
    entry: TimeEntryRecord,
    approval: TimeApprovalRecord,
    command: TransitionTimeApprovalCommand,
    previous: TimeApprovalDecisionRecord | None,
    decided_at_utc: datetime,
) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeApprovalDecisionRecord]:
    if command.action != TimeApprovalAction.SUBMIT and user_id in {
        approval.worker_principal_id,
        approval.created_by,
    }:
        raise TimeTrackingConflict("time approval maker-checker separation required")
    current_state = previous.to_state if previous is not None else approval.approval_state
    confirmation_hash = _require_approval_transition(
        approval_object_id=approval.object_id,
        current_state=current_state,
        command=command,
    )
    command_hash = _approval_decision_command_hash(
        command,
        approval_object_id=approval.object_id,
        user_id=user_id,
    )
    decision_payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "object_id": command.decision_object_id,
        "approval_object_id": approval.object_id,
        "entry_object_id": entry.object_id,
        "mutation_reference": command.mutation_reference,
        "command_hash": command_hash,
        "sequence_no": 1 if previous is None else previous.sequence_no + 1,
        "previous_decision_hash": ZERO_HASH if previous is None else previous.decision_hash,
        "from_state": current_state,
        "to_state": command.target_state,
        "action": command.action,
        "decided_by": user_id,
        "decided_at_utc": decided_at_utc,
        "confirmation_statement_hash": confirmation_hash,
        "audit_chain_ref": approval.audit_chain_ref,
        "source_system": command.source_system,
        "schema_version": TIME_APPROVAL_DECISION_SCHEMA_VERSION,
    }
    decision = TimeApprovalDecisionRecord(
        **decision_payload,
        decision_hash=_stable_hash(decision_payload),
    )
    transitioned_entry, transitioned_approval = _apply_time_approval_decision(
        entry=entry,
        approval=approval,
        decision=decision,
    )
    return transitioned_entry, transitioned_approval, decision


class InMemoryTimeTrackingStore:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], TimeEntryRecord] = {}
        self._approvals: dict[tuple[str, str], TimeApprovalRecord] = {}
        self._receipts: dict[tuple[str, str], TimeEntryCreationReceipt] = {}
        self._decisions: dict[tuple[str, str], TimeApprovalDecisionRecord] = {}
        self._decision_mutations: dict[tuple[str, str], TimeApprovalDecisionRecord] = {}

    def list_entries(self, *, tenant_id: str) -> Sequence[TimeEntryRecord]:
        entries: list[TimeEntryRecord] = []
        for (stored_tenant, _), entry in self._entries.items():
            if stored_tenant != tenant_id:
                continue
            latest = self._latest_decision(tenant_id=tenant_id, entry_object_id=entry.object_id)
            if latest is not None:
                approval = next(
                    approval
                    for (approval_tenant, _), approval in self._approvals.items()
                    if approval_tenant == tenant_id and approval.entry_object_id == entry.object_id
                )
                entry, _ = _apply_time_approval_decision(entry=entry, approval=approval, decision=latest)
            entries.append(entry)
        return tuple(entries)

    def list_approvals(self, *, tenant_id: str) -> Sequence[TimeApprovalRecord]:
        approvals: list[TimeApprovalRecord] = []
        for (stored_tenant, _), approval in self._approvals.items():
            if stored_tenant != tenant_id:
                continue
            latest = self._latest_decision(tenant_id=tenant_id, approval_object_id=approval.object_id)
            if latest is not None:
                entry = self._entries[(tenant_id, approval.entry_object_id)]
                _, approval = _apply_time_approval_decision(entry=entry, approval=approval, decision=latest)
            approvals.append(approval)
        return tuple(approvals)

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

    def transition_approval(
        self,
        *,
        tenant_id: str,
        user_id: str,
        approval_object_id: str,
        command: TransitionTimeApprovalCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeApprovalDecisionRecord, bool]:
        mutation_key = (tenant_id, command.mutation_reference)
        existing = self._decision_mutations.get(mutation_key)
        if existing is not None:
            command_hash = _approval_decision_command_hash(
                command,
                approval_object_id=approval_object_id,
                user_id=user_id,
            )
            if existing.command_hash != command_hash:
                raise TimeTrackingConflict("mutation_reference already belongs to a different time approval decision")
            replayed_entry = self._entries[(tenant_id, existing.entry_object_id)]
            replayed_approval = self._approvals[(tenant_id, existing.approval_object_id)]
            replayed_entry, replayed_approval = _apply_time_approval_decision(
                entry=replayed_entry,
                approval=replayed_approval,
                decision=existing,
            )
            return replayed_entry, replayed_approval, existing, True
        approval = self._approvals.get((tenant_id, approval_object_id))
        if approval is None:
            raise TimeTrackingNotFound("time approval not found")
        entry = self._entries[(tenant_id, approval.entry_object_id)]
        if (tenant_id, command.decision_object_id) in self._decisions:
            raise TimeTrackingConflict("time approval decision object already exists")
        previous = self._latest_decision(tenant_id=tenant_id, approval_object_id=approval_object_id)
        entry, approval, decision = _build_time_approval_decision(
            tenant_id=tenant_id,
            user_id=user_id,
            entry=entry,
            approval=approval,
            command=command,
            previous=previous,
            decided_at_utc=utc_now(),
        )
        self._decisions[(tenant_id, decision.object_id)] = decision
        self._decision_mutations[mutation_key] = decision
        return entry, approval, decision, False

    def _latest_decision(
        self,
        *,
        tenant_id: str,
        approval_object_id: str | None = None,
        entry_object_id: str | None = None,
    ) -> TimeApprovalDecisionRecord | None:
        matches = [
            decision
            for (stored_tenant, _), decision in self._decisions.items()
            if stored_tenant == tenant_id
            and (approval_object_id is None or decision.approval_object_id == approval_object_id)
            and (entry_object_id is None or decision.entry_object_id == entry_object_id)
        ]
        return max(matches, key=lambda item: item.sequence_no, default=None)


class PgTimeTrackingStore:
    def __init__(self, *, read_database_dsn: str, write_database_dsn: str) -> None:
        if not read_database_dsn.strip() or not write_database_dsn.strip():
            raise ValueError("Time Tracking PostgreSQL DSNs must not be empty")
        self.read_database_dsn = read_database_dsn
        self.write_database_dsn = write_database_dsn

    def list_entries(self, *, tenant_id: str) -> Sequence[TimeEntryRecord]:
        entries = self._list_records(
            tenant_id=tenant_id,
            table="time_tracking.entries",
            order_by="work_date DESC, started_at_utc DESC, object_id",
            record_type=TimeEntryRecord,
        )
        latest = {item.entry_object_id: item for item in self._list_latest_decisions(tenant_id=tenant_id)}
        return tuple(
            entry.model_copy(
                update={
                    "lifecycle_state": TimeTrackingLifecycleState(latest[entry.object_id].to_state.value),
                    "updated_at_utc": latest[entry.object_id].decided_at_utc,
                }
            )
            if entry.object_id in latest
            else entry
            for entry in entries
        )

    def list_approvals(self, *, tenant_id: str) -> Sequence[TimeApprovalRecord]:
        approvals = self._list_records(
            tenant_id=tenant_id,
            table="time_tracking.approvals",
            order_by="created_at_utc DESC, object_id",
            record_type=TimeApprovalRecord,
        )
        latest = {item.approval_object_id: item for item in self._list_latest_decisions(tenant_id=tenant_id)}
        return tuple(
            approval.model_copy(
                update={
                    "approval_state": latest[approval.object_id].to_state,
                    "lifecycle_state": TimeTrackingLifecycleState(latest[approval.object_id].to_state.value),
                    "updated_at_utc": latest[approval.object_id].decided_at_utc,
                    "approver_principal_id": (
                        None
                        if latest[approval.object_id].action == TimeApprovalAction.SUBMIT
                        else latest[approval.object_id].decided_by
                    ),
                    "decided_at_utc": (
                        None
                        if latest[approval.object_id].action == TimeApprovalAction.SUBMIT
                        else latest[approval.object_id].decided_at_utc
                    ),
                }
            )
            if approval.object_id in latest
            else approval
            for approval in approvals
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

    def transition_approval(
        self,
        *,
        tenant_id: str,
        user_id: str,
        approval_object_id: str,
        command: TransitionTimeApprovalCommand,
    ) -> tuple[TimeEntryRecord, TimeApprovalRecord, TimeApprovalDecisionRecord, bool]:
        command_hash = _approval_decision_command_hash(
            command,
            approval_object_id=approval_object_id,
            user_id=user_id,
        )
        try:
            with psycopg.connect(self.write_database_dsn, row_factory=dict_row) as connection:
                connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{tenant_id}:time-approval-decision:{approval_object_id}",),
                )
                existing = self._load_decision_by_mutation(
                    connection,
                    tenant_id=tenant_id,
                    mutation_reference=command.mutation_reference,
                )
                if existing is not None:
                    if existing.command_hash != command_hash:
                        raise TimeTrackingConflict(
                            "mutation_reference already belongs to a different time approval decision"
                        )
                    replayed_entry = self._load_entry(
                        connection,
                        tenant_id=tenant_id,
                        object_id=existing.entry_object_id,
                    )
                    replayed_approval = self._load_approval(
                        connection,
                        tenant_id=tenant_id,
                        object_id=existing.approval_object_id,
                    )
                    replayed_entry, replayed_approval = _apply_time_approval_decision(
                        entry=replayed_entry,
                        approval=replayed_approval,
                        decision=existing,
                    )
                    return replayed_entry, replayed_approval, existing, True
                approval = self._load_approval_optional(
                    connection,
                    tenant_id=tenant_id,
                    object_id=approval_object_id,
                )
                if approval is None:
                    raise TimeTrackingNotFound("time approval not found")
                entry = self._load_entry(
                    connection,
                    tenant_id=tenant_id,
                    object_id=approval.entry_object_id,
                )
                previous = self._load_latest_decision(
                    connection,
                    tenant_id=tenant_id,
                    approval_object_id=approval_object_id,
                )
                entry, approval, decision = _build_time_approval_decision(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    entry=entry,
                    approval=approval,
                    command=command,
                    previous=previous,
                    decided_at_utc=utc_now(),
                )
                self._insert_decision(connection, decision)
                return entry, approval, decision, False
        except psycopg.errors.UniqueViolation as exc:
            raise TimeTrackingConflict("time approval decision ID or sequence already exists") from exc

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

    def _list_latest_decisions(self, *, tenant_id: str) -> tuple[TimeApprovalDecisionRecord, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be empty")
        with psycopg.connect(self.read_database_dsn, row_factory=dict_row) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
            rows = connection.execute(
                """
                SELECT DISTINCT ON (approval_object_id) *
                FROM time_tracking.approval_decisions
                WHERE tenant_id = %s
                ORDER BY approval_object_id, sequence_no DESC
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(TimeApprovalDecisionRecord.model_validate(row) for row in rows)

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
    def _insert_decision(
        connection: psycopg.Connection[dict[str, Any]],
        decision: TimeApprovalDecisionRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO time_tracking.approval_decisions (
                tenant_id, object_id, approval_object_id, entry_object_id, mutation_reference,
                command_hash, sequence_no, previous_decision_hash, from_state, to_state,
                action, decided_by, decided_at_utc, confirmation_statement_hash,
                audit_chain_ref, decision_hash, source_system
            ) VALUES (
                %(tenant_id)s, %(object_id)s, %(approval_object_id)s, %(entry_object_id)s,
                %(mutation_reference)s, %(command_hash)s, %(sequence_no)s,
                %(previous_decision_hash)s, %(from_state)s, %(to_state)s, %(action)s,
                %(decided_by)s, %(decided_at_utc)s, %(confirmation_statement_hash)s,
                %(audit_chain_ref)s, %(decision_hash)s, %(source_system)s
            )
            """,
            decision.model_dump(exclude={"schema_version"}),
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

    @staticmethod
    def _load_approval_optional(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        object_id: str,
    ) -> TimeApprovalRecord | None:
        row = connection.execute(
            "SELECT * FROM time_tracking.approvals WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, object_id),
        ).fetchone()
        return None if row is None else TimeApprovalRecord.model_validate(row)

    @staticmethod
    def _load_decision_by_mutation(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        mutation_reference: str,
    ) -> TimeApprovalDecisionRecord | None:
        row = connection.execute(
            """
            SELECT * FROM time_tracking.approval_decisions
            WHERE tenant_id = %s AND mutation_reference = %s
            """,
            (tenant_id, mutation_reference),
        ).fetchone()
        return None if row is None else TimeApprovalDecisionRecord.model_validate(row)

    @staticmethod
    def _load_latest_decision(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        approval_object_id: str,
    ) -> TimeApprovalDecisionRecord | None:
        row = connection.execute(
            """
            SELECT * FROM time_tracking.approval_decisions
            WHERE tenant_id = %s AND approval_object_id = %s
            ORDER BY sequence_no DESC
            LIMIT 1
            """,
            (tenant_id, approval_object_id),
        ).fetchone()
        return None if row is None else TimeApprovalDecisionRecord.model_validate(row)


def time_entry_view(record: TimeEntryRecord) -> TimeEntryView:
    return TimeEntryView(**record.model_dump(exclude={"tenant_id", "kms_key_ref"}))


def time_approval_view(record: TimeApprovalRecord) -> TimeApprovalView:
    return TimeApprovalView(
        **record.model_dump(exclude={"tenant_id", "owner_principal_id", "updated_at_utc", "kms_key_ref"})
    )


def time_approval_decision_view(record: TimeApprovalDecisionRecord) -> TimeApprovalDecisionView:
    return TimeApprovalDecisionView(**record.model_dump(exclude={"tenant_id", "command_hash"}))


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

    def transition_approval(
        self,
        *,
        user_context: UserContext,
        approval_object_id: str,
        command: TransitionTimeApprovalCommand,
    ) -> TimeApprovalDecisionResponse:
        if approval_object_id not in user_context.readable_object_ids:
            raise PermissionError("Time approval object write access required")
        approval = next(
            (
                item
                for item in self.store.list_approvals(tenant_id=user_context.tenant_id)
                if item.object_id == approval_object_id
            ),
            None,
        )
        if approval is None:
            raise TimeTrackingNotFound("time approval not found")
        if approval.entry_object_id not in user_context.readable_object_ids:
            raise PermissionError("Linked time entry write access required")
        if command.action == TimeApprovalAction.SUBMIT:
            if user_context.role_ids.isdisjoint(TIME_ENTRY_CREATOR_ROLES):
                raise PermissionError("Time Tracking creator role required for submission")
            if user_context.user_id != approval.worker_principal_id and user_context.role_ids.isdisjoint(
                TIME_DELEGATED_CREATOR_ROLES
            ):
                raise PermissionError("Time Tracking delegated submission role required")
        else:
            if user_context.role_ids.isdisjoint(TIME_APPROVER_ROLES):
                raise PermissionError("Time Tracking approver role required")
            if user_context.user_id in {approval.worker_principal_id, approval.created_by}:
                raise PermissionError("Time approval maker-checker separation required")
        entry, transitioned_approval, decision, replayed = self.store.transition_approval(
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            approval_object_id=approval_object_id,
            command=command,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type=(
                "time_tracking.approval.decision.replayed" if replayed else "time_tracking.approval.decision.committed"
            ),
            source_object_ids=[entry.object_id, transitioned_approval.object_id, decision.object_id],
            metadata={
                "module_id": TIME_TRACKING_MODULE_ID,
                "feature_id": TIME_APPROVALS_WRITE_FEATURE_ID,
                "mutation_reference": decision.mutation_reference,
                "command_hash": decision.command_hash,
                "decision_hash": decision.decision_hash,
                "sequence_no": decision.sequence_no,
                "from_state": decision.from_state,
                "to_state": decision.to_state,
                "action": decision.action,
                "confirmation_evidence_present": decision.confirmation_statement_hash is not None,
                "maker_checker_verified": True,
                "atomic_transaction_committed": True,
                "idempotent_replay": replayed,
                "result_contract": "append_only_time_approval_decision",
                "decision_content_included": False,
            },
        )
        return TimeApprovalDecisionResponse(
            tenant_id=user_context.tenant_id,
            entry=time_entry_view(entry),
            approval=time_approval_view(transitioned_approval),
            decision=time_approval_decision_view(decision),
            idempotent_replay=replayed,
            maker_checker_verified=True,
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
