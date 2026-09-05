from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.tasks_activities_module import (
    TASKS_ACTIVITIES_MODULE_ID,
    TASKS_ACTIVITY_READ_FEATURE_ID,
    TASKS_ITEMS_READ_FEATURE_ID,
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
    TasksActivitiesLifecycleState,
)

TASK_OBJECT_TYPE = "task.task"
TASK_ACTIVITY_OBJECT_TYPE = "task.activity"
TASK_ITEM_SCHEMA_VERSION = "task_item.v1"
TASK_ACTIVITY_SCHEMA_VERSION = "task_activity.v1"
TASK_CREATION_RECEIPT_SCHEMA_VERSION = "task_creation_receipt.v1"
TASKS_OPERATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "task-manager", "task-operator"})
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TasksActivitiesConflict(ValueError):
    pass


class TasksActivitiesAssignmentError(ValueError):
    pass


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskActivityType(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    DUE_DATE_CHANGED = "due_date_changed"
    COMPLETED = "completed"


class CreateTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_reference: str = Field(min_length=3, max_length=300)
    task_object_id: str = Field(min_length=1, max_length=200)
    task_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    due_at_utc: datetime | None = None
    activity_object_id: str = Field(min_length=1, max_length=200)
    activity_number: str = Field(min_length=1, max_length=100)
    activity_summary: str = Field(default="Task created", min_length=1, max_length=400)
    source_system: str = "native"

    @field_validator("mutation_reference")
    @classmethod
    def require_mutation_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not REF_PATTERN.fullmatch(normalized):
            raise ValueError("mutation_reference must be a namespaced reference")
        return normalized

    @field_validator(
        "task_object_id",
        "task_number",
        "title",
        "activity_object_id",
        "activity_number",
        "activity_summary",
    )
    @classmethod
    def require_single_line_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("task create fields must be non-empty single-line values")
        return normalized

    @field_validator("assigned_principal_id")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("assigned_principal_id must not be empty")
        return normalized

    @field_validator("source_system")
    @classmethod
    def require_source_system(cls, value: str) -> str:
        normalized = value.strip()
        if not SOURCE_SYSTEM_PATTERN.fullmatch(normalized):
            raise ValueError("source_system must be lowercase and non-empty")
        return normalized

    @field_validator("due_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_unique_object_ids(self) -> CreateTaskCommand:
        if self.task_object_id == self.activity_object_id:
            raise ValueError("task and activity object IDs must differ")
        return self


class TaskItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TASK_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: TasksActivitiesLifecycleState = TasksActivitiesLifecycleState.ASSIGNED
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TASK_ITEM_SCHEMA_VERSION
    task_number: str
    title: str
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_principal_id: str
    due_at_utc: datetime | None = None

    @model_validator(mode="after")
    def require_governed_metadata(self) -> TaskItemRecord:
        if self.object_type != TASK_OBJECT_TYPE or self.schema_version != TASK_ITEM_SCHEMA_VERSION:
            raise ValueError("task identity metadata is inconsistent")
        if self.data_classification != DataClass.PERSONAL:
            raise ValueError("task classification must be personal")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("task retention policy is invalid")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("task Legal Hold state is invalid")
        if self.legal_hold_state == "active" and self.retention_policy_id != "rp-legal-hold":
            raise ValueError("active task Legal Hold requires rp-legal-hold")
        if not REF_PATTERN.fullmatch(self.kms_key_ref) or not REF_PATTERN.fullmatch(self.audit_chain_ref):
            raise ValueError("task security references must be namespaced")
        return self


class TaskActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TASK_ACTIVITY_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: TasksActivitiesLifecycleState = TasksActivitiesLifecycleState.OPEN
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TASK_ACTIVITY_SCHEMA_VERSION
    task_object_id: str
    activity_number: str
    activity_type: TaskActivityType = TaskActivityType.CREATED
    summary: str
    occurred_at_utc: datetime

    @model_validator(mode="after")
    def require_governed_metadata(self) -> TaskActivityRecord:
        if self.object_type != TASK_ACTIVITY_OBJECT_TYPE or self.schema_version != TASK_ACTIVITY_SCHEMA_VERSION:
            raise ValueError("task activity identity metadata is inconsistent")
        if self.data_classification != DataClass.PERSONAL:
            raise ValueError("task activity classification must be personal")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("task activity retention policy is invalid")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("task activity Legal Hold state is invalid")
        if not REF_PATTERN.fullmatch(self.kms_key_ref) or not REF_PATTERN.fullmatch(self.audit_chain_ref):
            raise ValueError("task activity security references must be namespaced")
        return self


class TaskCreationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    mutation_reference: str
    command_hash: str
    created_by: str
    assigned_principal_id: str
    task_object_id: str
    activity_object_id: str
    acl_manifest: tuple[str, ...]
    audit_chain_ref: str
    receipt_hash: str
    created_at_utc: datetime
    schema_version: str = TASK_CREATION_RECEIPT_SCHEMA_VERSION


class TaskItemView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    task_number: str
    title: str
    priority: TaskPriority
    assigned_principal_id: str
    due_at_utc: datetime | None
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: TasksActivitiesLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class TaskActivityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    task_object_id: str
    activity_number: str
    activity_type: TaskActivityType
    summary: str
    occurred_at_utc: datetime
    created_by: str
    created_at_utc: datetime
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: TasksActivitiesLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_task_access_checked: bool = True


class TaskItemsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TASKS_ACTIVITIES_MODULE_ID
    feature_id: str = TASKS_ITEMS_READ_FEATURE_ID
    items: list[TaskItemView]
    audit_event_id: str


class TaskActivitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TASKS_ACTIVITIES_MODULE_ID
    feature_id: str = TASKS_ACTIVITY_READ_FEATURE_ID
    activities: list[TaskActivityView]
    audit_event_id: str


class TaskCreationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = TASKS_ACTIVITIES_MODULE_ID
    feature_id: str = TASKS_WORKFLOW_WRITE_FEATURE_ID
    task: TaskItemView
    activity: TaskActivityView
    receipt: TaskCreationReceipt
    acl_grant_count: int
    idempotent_replay: bool
    atomic_transaction_committed: bool = True
    receipt_content_included: bool = False
    audit_event_id: str


class TasksActivitiesStore(Protocol):
    def list_items(self, *, tenant_id: str) -> Sequence[TaskItemRecord]: ...

    def list_activities(self, *, tenant_id: str) -> Sequence[TaskActivityRecord]: ...

    def create_task(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTaskCommand,
    ) -> tuple[TaskItemRecord, TaskActivityRecord, TaskCreationReceipt, bool]: ...


TaskRecord = TypeVar("TaskRecord", TaskItemRecord, TaskActivityRecord)


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _command_hash(command: CreateTaskCommand, *, user_id: str, assignee_id: str) -> str:
    return _stable_hash(
        {
            "command": command.model_dump(mode="json"),
            "created_by": user_id,
            "resolved_assignee": assignee_id,
        }
    )


def _acl_manifest(
    *,
    task_object_id: str,
    activity_object_id: str,
    creator_id: str,
    assignee_id: str,
) -> tuple[str, ...]:
    grants = [
        f"{TASK_OBJECT_TYPE}:{task_object_id}:user:{creator_id}:admin:1",
        f"{TASK_ACTIVITY_OBJECT_TYPE}:{activity_object_id}:user:{creator_id}:admin:1",
    ]
    if assignee_id != creator_id:
        grants.extend(
            (
                f"{TASK_OBJECT_TYPE}:{task_object_id}:user:{assignee_id}:write:1",
                f"{TASK_ACTIVITY_OBJECT_TYPE}:{activity_object_id}:user:{assignee_id}:read:1",
            )
        )
    return tuple(grants)


def _build_records_and_receipt(
    *,
    tenant_id: str,
    user_id: str,
    command: CreateTaskCommand,
    created_at_utc: datetime,
) -> tuple[TaskItemRecord, TaskActivityRecord, TaskCreationReceipt]:
    assignee_id = command.assigned_principal_id or user_id
    digest = _command_hash(command, user_id=user_id, assignee_id=assignee_id)
    audit_chain_ref = f"audit:task-create:{digest.removeprefix('sha256:')}"
    kms_key_ref = f"kms:{tenant_id}:tasks"
    task = TaskItemRecord(
        tenant_id=tenant_id,
        object_id=command.task_object_id,
        owner_principal_id=user_id,
        created_by=user_id,
        created_at_utc=created_at_utc,
        updated_at_utc=created_at_utc,
        kms_key_ref=kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=command.source_system,
        task_number=command.task_number,
        title=command.title,
        priority=command.priority,
        assigned_principal_id=assignee_id,
        due_at_utc=command.due_at_utc,
    )
    activity = TaskActivityRecord(
        tenant_id=tenant_id,
        object_id=command.activity_object_id,
        owner_principal_id=user_id,
        created_by=user_id,
        created_at_utc=created_at_utc,
        updated_at_utc=created_at_utc,
        kms_key_ref=kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=command.source_system,
        task_object_id=command.task_object_id,
        activity_number=command.activity_number,
        summary=command.activity_summary,
        occurred_at_utc=created_at_utc,
    )
    acl_manifest = _acl_manifest(
        task_object_id=task.object_id,
        activity_object_id=activity.object_id,
        creator_id=user_id,
        assignee_id=assignee_id,
    )
    receipt_hash = _stable_hash(
        {
            "tenant_id": tenant_id,
            "mutation_reference": command.mutation_reference,
            "command_hash": digest,
            "created_by": user_id,
            "assigned_principal_id": assignee_id,
            "task_object_id": task.object_id,
            "activity_object_id": activity.object_id,
            "acl_manifest": acl_manifest,
            "audit_chain_ref": audit_chain_ref,
            "schema_version": TASK_CREATION_RECEIPT_SCHEMA_VERSION,
        }
    )
    receipt = TaskCreationReceipt(
        tenant_id=tenant_id,
        mutation_reference=command.mutation_reference,
        command_hash=digest,
        created_by=user_id,
        assigned_principal_id=assignee_id,
        task_object_id=task.object_id,
        activity_object_id=activity.object_id,
        acl_manifest=acl_manifest,
        audit_chain_ref=audit_chain_ref,
        receipt_hash=receipt_hash,
        created_at_utc=created_at_utc,
    )
    return task, activity, receipt


class InMemoryTasksActivitiesStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], TaskItemRecord] = {}
        self._activities: dict[tuple[str, str], TaskActivityRecord] = {}
        self._receipts: dict[tuple[str, str], TaskCreationReceipt] = {}

    def list_items(self, *, tenant_id: str) -> Sequence[TaskItemRecord]:
        return tuple(item for (stored_tenant, _), item in self._items.items() if stored_tenant == tenant_id)

    def list_activities(self, *, tenant_id: str) -> Sequence[TaskActivityRecord]:
        return tuple(
            activity for (stored_tenant, _), activity in self._activities.items() if stored_tenant == tenant_id
        )

    def create_task(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTaskCommand,
    ) -> tuple[TaskItemRecord, TaskActivityRecord, TaskCreationReceipt, bool]:
        key = (tenant_id, command.mutation_reference)
        assignee_id = command.assigned_principal_id or user_id
        existing = self._receipts.get(key)
        if existing is not None:
            if existing.command_hash != _command_hash(command, user_id=user_id, assignee_id=assignee_id):
                raise TasksActivitiesConflict("mutation_reference already belongs to a different task command")
            return (
                self._items[(tenant_id, existing.task_object_id)],
                self._activities[(tenant_id, existing.activity_object_id)],
                existing,
                True,
            )
        if (tenant_id, command.task_object_id) in self._items:
            raise TasksActivitiesConflict("task object already exists")
        if (tenant_id, command.activity_object_id) in self._activities:
            raise TasksActivitiesConflict("task activity object already exists")
        task, activity, receipt = _build_records_and_receipt(
            tenant_id=tenant_id,
            user_id=user_id,
            command=command,
            created_at_utc=utc_now(),
        )
        self._items[(tenant_id, task.object_id)] = task
        self._activities[(tenant_id, activity.object_id)] = activity
        self._receipts[key] = receipt
        return task, activity, receipt, False


class PgTasksActivitiesStore:
    def __init__(self, *, read_database_dsn: str, write_database_dsn: str) -> None:
        if not read_database_dsn.strip() or not write_database_dsn.strip():
            raise ValueError("Tasks & Activities PostgreSQL DSNs must not be empty")
        self.read_database_dsn = read_database_dsn
        self.write_database_dsn = write_database_dsn

    def list_items(self, *, tenant_id: str) -> Sequence[TaskItemRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="tasks.items",
            order_by="due_at_utc NULLS LAST, created_at_utc DESC, object_id",
            record_type=TaskItemRecord,
        )

    def list_activities(self, *, tenant_id: str) -> Sequence[TaskActivityRecord]:
        return self._list_records(
            tenant_id=tenant_id,
            table="tasks.activities",
            order_by="occurred_at_utc DESC, object_id",
            record_type=TaskActivityRecord,
        )

    def create_task(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CreateTaskCommand,
    ) -> tuple[TaskItemRecord, TaskActivityRecord, TaskCreationReceipt, bool]:
        assignee_id = command.assigned_principal_id or user_id
        digest = _command_hash(command, user_id=user_id, assignee_id=assignee_id)
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
                    if existing.command_hash != digest:
                        raise TasksActivitiesConflict("mutation_reference already belongs to a different task command")
                    return (
                        self._load_task(connection, tenant_id=tenant_id, object_id=existing.task_object_id),
                        self._load_activity(
                            connection,
                            tenant_id=tenant_id,
                            object_id=existing.activity_object_id,
                        ),
                        existing,
                        True,
                    )
                if assignee_id != user_id and not self._active_tenant_principal_exists(
                    connection,
                    tenant_id=tenant_id,
                    user_id=assignee_id,
                ):
                    raise TasksActivitiesAssignmentError("assigned principal is not an active tenant member")

                task, activity, receipt = _build_records_and_receipt(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    command=command,
                    created_at_utc=utc_now(),
                )
                self._insert_task(connection, task)
                self._insert_activity(connection, activity)
                self._insert_acls(connection, task=task, activity=activity, receipt=receipt)
                self._insert_receipt(connection, receipt)
                return task, activity, receipt, False
        except psycopg.errors.UniqueViolation as exc:
            raise TasksActivitiesConflict("task IDs, numbers or ACL entries already exist") from exc

    def _list_records(
        self,
        *,
        tenant_id: str,
        table: str,
        order_by: str,
        record_type: type[TaskRecord],
    ) -> tuple[TaskRecord, ...]:
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
    def _insert_task(connection: psycopg.Connection[dict[str, Any]], task: TaskItemRecord) -> None:
        connection.execute(
            """
            INSERT INTO tasks.items (
                tenant_id, object_id, owner_principal_id, created_by, created_at_utc, updated_at_utc,
                kms_key_ref, audit_chain_ref, source_system, task_number, title, priority,
                assigned_principal_id, due_at_utc
            ) VALUES (
                %(tenant_id)s, %(object_id)s, %(owner_principal_id)s, %(created_by)s,
                %(created_at_utc)s, %(updated_at_utc)s, %(kms_key_ref)s, %(audit_chain_ref)s,
                %(source_system)s, %(task_number)s, %(title)s, %(priority)s,
                %(assigned_principal_id)s, %(due_at_utc)s
            )
            """,
            task.model_dump(),
        )

    @staticmethod
    def _insert_activity(
        connection: psycopg.Connection[dict[str, Any]],
        activity: TaskActivityRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO tasks.activities (
                tenant_id, object_id, owner_principal_id, created_by, created_at_utc, updated_at_utc,
                kms_key_ref, audit_chain_ref, source_system, task_object_id, activity_number,
                activity_type, summary, occurred_at_utc
            ) VALUES (
                %(tenant_id)s, %(object_id)s, %(owner_principal_id)s, %(created_by)s,
                %(created_at_utc)s, %(updated_at_utc)s, %(kms_key_ref)s, %(audit_chain_ref)s,
                %(source_system)s, %(task_object_id)s, %(activity_number)s, %(activity_type)s,
                %(summary)s, %(occurred_at_utc)s
            )
            """,
            activity.model_dump(),
        )

    @staticmethod
    def _insert_acls(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        task: TaskItemRecord,
        activity: TaskActivityRecord,
        receipt: TaskCreationReceipt,
    ) -> None:
        grants = [
            (task.object_id, task.object_type, receipt.created_by, "admin"),
            (activity.object_id, activity.object_type, receipt.created_by, "admin"),
        ]
        if receipt.assigned_principal_id != receipt.created_by:
            grants.extend(
                (
                    (task.object_id, task.object_type, receipt.assigned_principal_id, "write"),
                    (activity.object_id, activity.object_type, receipt.assigned_principal_id, "read"),
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
                    task.tenant_id,
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
        receipt: TaskCreationReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO tasks.creation_receipts (
                tenant_id, mutation_reference, command_hash, created_by, assigned_principal_id,
                task_object_id, activity_object_id, acl_manifest, audit_chain_ref, receipt_hash,
                created_at_utc
            ) VALUES (
                %(tenant_id)s, %(mutation_reference)s, %(command_hash)s, %(created_by)s,
                %(assigned_principal_id)s, %(task_object_id)s, %(activity_object_id)s,
                %(acl_manifest)s, %(audit_chain_ref)s, %(receipt_hash)s, %(created_at_utc)s
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
    ) -> TaskCreationReceipt | None:
        row = connection.execute(
            """
            SELECT *
            FROM tasks.creation_receipts
            WHERE tenant_id = %s AND mutation_reference = %s
            """,
            (tenant_id, mutation_reference),
        ).fetchone()
        if row is None:
            return None
        return TaskCreationReceipt.model_validate(
            {
                **row,
                "acl_manifest": tuple(str(item) for item in row["acl_manifest"]),
            }
        )

    @staticmethod
    def _load_task(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        object_id: str,
    ) -> TaskItemRecord:
        row = connection.execute(
            "SELECT * FROM tasks.items WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, object_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("task creation receipt points to a missing task")
        return TaskItemRecord.model_validate(row)

    @staticmethod
    def _load_activity(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        tenant_id: str,
        object_id: str,
    ) -> TaskActivityRecord:
        row = connection.execute(
            "SELECT * FROM tasks.activities WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, object_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("task creation receipt points to a missing activity")
        return TaskActivityRecord.model_validate(row)


def task_item_view(record: TaskItemRecord) -> TaskItemView:
    return TaskItemView(**record.model_dump(exclude={"tenant_id", "kms_key_ref"}))


def task_activity_view(record: TaskActivityRecord) -> TaskActivityView:
    return TaskActivityView(
        **record.model_dump(
            exclude={
                "tenant_id",
                "owner_principal_id",
                "updated_at_utc",
                "kms_key_ref",
            }
        )
    )


class TasksActivitiesService:
    def __init__(self, *, store: TasksActivitiesStore, audit_logger: InMemoryAuditLogger) -> None:
        self.store = store
        self.audit_logger = audit_logger

    def create_task(
        self,
        *,
        user_context: UserContext,
        command: CreateTaskCommand,
    ) -> TaskCreationResponse:
        if user_context.role_ids.isdisjoint(TASKS_OPERATOR_ROLES):
            raise PermissionError("Tasks & Activities operator role required")
        task, activity, receipt, replayed = self.store.create_task(
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            command=command,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="tasks.task.creation.replayed" if replayed else "tasks.task.creation.committed",
            source_object_ids=[task.object_id, activity.object_id],
            metadata={
                "module_id": TASKS_ACTIVITIES_MODULE_ID,
                "feature_id": TASKS_WORKFLOW_WRITE_FEATURE_ID,
                "mutation_reference": receipt.mutation_reference,
                "command_hash": receipt.command_hash,
                "receipt_hash": receipt.receipt_hash,
                "acl_grant_count": len(receipt.acl_manifest),
                "atomic_transaction_committed": True,
                "idempotent_replay": replayed,
                "result_contract": "governed_task_creation_with_metadata_only_receipt",
                "receipt_content_included": False,
            },
        )
        return TaskCreationResponse(
            tenant_id=user_context.tenant_id,
            task=task_item_view(task),
            activity=task_activity_view(activity),
            receipt=receipt,
            acl_grant_count=len(receipt.acl_manifest),
            idempotent_replay=replayed,
            audit_event_id=event.event_id,
        )

    def list_items(self, *, user_context: UserContext) -> TaskItemsResponse:
        candidates = tuple(self.store.list_items(tenant_id=user_context.tenant_id))
        authorized = sorted(
            (item for item in candidates if item.object_id in user_context.readable_object_ids),
            key=lambda item: (item.due_at_utc is None, item.due_at_utc or item.created_at_utc, item.object_id),
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="tasks.items.read",
            source_object_ids=[item.object_id for item in authorized],
            metadata={
                "module_id": TASKS_ACTIVITIES_MODULE_ID,
                "feature_id": TASKS_ITEMS_READ_FEATURE_ID,
                "candidate_count": len(candidates),
                "result_count": len(authorized),
                "acl_filtered_count": len(candidates) - len(authorized),
                "result_contract": "authorized_governed_task_metadata",
            },
        )
        return TaskItemsResponse(
            tenant_id=user_context.tenant_id,
            items=[task_item_view(item) for item in authorized],
            audit_event_id=event.event_id,
        )

    def list_activities(self, *, user_context: UserContext) -> TaskActivitiesResponse:
        candidates = tuple(self.store.list_activities(tenant_id=user_context.tenant_id))
        authorized = sorted(
            (
                activity
                for activity in candidates
                if activity.object_id in user_context.readable_object_ids
                and activity.task_object_id in user_context.readable_object_ids
            ),
            key=lambda activity: (activity.occurred_at_utc, activity.object_id),
            reverse=True,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="tasks.activities.read",
            source_object_ids=[activity.object_id for activity in authorized],
            metadata={
                "module_id": TASKS_ACTIVITIES_MODULE_ID,
                "feature_id": TASKS_ACTIVITY_READ_FEATURE_ID,
                "candidate_count": len(candidates),
                "result_count": len(authorized),
                "acl_filtered_count": len(candidates) - len(authorized),
                "linked_task_acl_required": True,
                "result_contract": "authorized_governed_task_activity_metadata",
            },
        )
        return TaskActivitiesResponse(
            tenant_id=user_context.tenant_id,
            activities=[task_activity_view(activity) for activity in authorized],
            audit_event_id=event.event_id,
        )


def build_default_tasks_activities_store(
    environ: Mapping[str, str] | None = None,
) -> TasksActivitiesStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TASKS_ACTIVITIES_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTasksActivitiesStore()
    if backend in {"postgres", "postgresql", "pg"}:
        read_dsn = env.get("SUITE_TASKS_ACTIVITIES_READ_DSN") or env.get("SUITE_DATABASE_DSN")
        write_dsn = env.get("SUITE_TASKS_ACTIVITIES_WRITE_DSN") or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
        if not read_dsn or not write_dsn:
            raise ValueError(
                "PostgreSQL Tasks & Activities requires read and write DSNs through suite database settings"
            )
        return PgTasksActivitiesStore(
            read_database_dsn=read_dsn,
            write_database_dsn=write_dsn,
        )
    raise ValueError(f"Unsupported SUITE_TASKS_ACTIVITIES_BACKEND: {backend}")
