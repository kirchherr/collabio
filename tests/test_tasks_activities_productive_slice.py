import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.tasks_activities_service import (
    CreateTaskCommand,
    InMemoryTasksActivitiesStore,
    PgTasksActivitiesStore,
    TaskPriority,
    TasksActivitiesConflict,
    TasksActivitiesService,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str
    authz_admin_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    authz_admin_dsn = env_or_skip("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(
        migration_dsn=migration_dsn,
        app_dsn=app_dsn,
        authz_admin_dsn=authz_admin_dsn,
    )


def task_command(suffix: str, *, mutation_reference: str | None = None) -> CreateTaskCommand:
    return CreateTaskCommand(
        mutation_reference=mutation_reference or f"request:task-create-{suffix}",
        task_object_id=f"task-{suffix}",
        task_number=f"TASK-{suffix}",
        title="Prepare customer review",
        priority=TaskPriority.HIGH,
        due_at_utc=datetime(2026, 8, 5, 10, tzinfo=UTC),
        activity_object_id=f"task-activity-{suffix}",
        activity_number=f"TASK-ACT-{suffix}",
        activity_summary="Task created for customer review",
    )


def first_int(row: tuple[Any, ...] | None) -> int:
    assert row is not None
    return int(row[0])


def test_task_creation_enforces_role_idempotency_and_authoritative_read_filter() -> None:
    audit_logger = InMemoryAuditLogger()
    store = InMemoryTasksActivitiesStore()
    service = TasksActivitiesService(store=store, audit_logger=audit_logger)
    command = task_command("memory")
    reader = UserContext(
        tenant_id="tenant-memory",
        user_id="reader",
        role_ids={"knowledge-worker"},
    )

    with pytest.raises(PermissionError, match="operator role required"):
        service.create_task(user_context=reader, command=command)

    operator = UserContext(
        tenant_id="tenant-memory",
        user_id="operator",
        role_ids={"task-operator"},
    )
    created = service.create_task(user_context=operator, command=command)
    replay = service.create_task(user_context=operator, command=command)

    assert created.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.receipt.receipt_hash == created.receipt.receipt_hash
    assert created.acl_grant_count == 2
    assert created.receipt_content_included is False
    assert command.title not in created.receipt.model_dump_json()
    assert command.activity_summary not in created.receipt.model_dump_json()
    assert audit_logger.events[-1].event_type == "tasks.task.creation.replayed"

    with pytest.raises(TasksActivitiesConflict, match="different task command"):
        service.create_task(
            user_context=operator,
            command=command.model_copy(update={"title": "Changed title"}),
        )

    fully_authorized = operator.model_copy(
        update={"readable_object_ids": {command.task_object_id, command.activity_object_id}}
    )
    activity_only = operator.model_copy(update={"readable_object_ids": {command.activity_object_id}})
    assert len(service.list_items(user_context=fully_authorized).items) == 1
    assert len(service.list_activities(user_context=fully_authorized).activities) == 1
    assert service.list_activities(user_context=activity_only).activities == []


def test_postgres_task_creation_commits_task_activity_acls_and_receipt_atomically(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-tasks-{suffix}"
    user_id = f"operator-{suffix}"
    command = task_command(suffix)
    store = PgTasksActivitiesStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )

    task, activity, receipt, replayed = store.create_task(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )
    replay_task, replay_activity, replay_receipt, replayed_again = store.create_task(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )

    with psycopg.connect(live_database.migration_dsn) as connection:
        task_count = first_int(
            connection.execute(
                "SELECT count(*) FROM tasks.items WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, command.task_object_id),
            ).fetchone()
        )
        activity_count = first_int(
            connection.execute(
                "SELECT count(*) FROM tasks.activities WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, command.activity_object_id),
            ).fetchone()
        )
        acl_count = first_int(
            connection.execute(
                """
                SELECT count(*) FROM collabio.object_acl_entries
                WHERE tenant_id = %s AND audit_chain_ref = %s
                """,
                (tenant_id, receipt.audit_chain_ref),
            ).fetchone()
        )
        receipt_count = first_int(
            connection.execute(
                """
                SELECT count(*) FROM tasks.creation_receipts
                WHERE tenant_id = %s AND mutation_reference = %s
                """,
                (tenant_id, command.mutation_reference),
            ).fetchone()
        )

    assert replayed is False
    assert replayed_again is True
    assert replay_task.object_id == task.object_id
    assert replay_activity.object_id == activity.object_id
    assert replay_receipt.receipt_hash == receipt.receipt_hash
    assert (task_count, activity_count, acl_count, receipt_count) == (1, 1, 2, 1)
    assert len(store.list_items(tenant_id=tenant_id)) == 1
    assert len(store.list_activities(tenant_id=tenant_id)) == 1


def test_postgres_task_creation_rolls_back_all_surfaces_on_activity_collision(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-tasks-rollback-{suffix}"
    user_id = f"operator-{suffix}"
    store = PgTasksActivitiesStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )
    first = task_command(f"first-{suffix}")
    store.create_task(tenant_id=tenant_id, user_id=user_id, command=first)
    second = task_command(f"second-{suffix}").model_copy(update={"activity_object_id": first.activity_object_id})

    with pytest.raises(TasksActivitiesConflict, match="already exist"):
        store.create_task(tenant_id=tenant_id, user_id=user_id, command=second)

    with psycopg.connect(live_database.migration_dsn) as connection:
        task_count = first_int(
            connection.execute(
                "SELECT count(*) FROM tasks.items WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, second.task_object_id),
            ).fetchone()
        )
        acl_count = first_int(
            connection.execute(
                """
                SELECT count(*) FROM collabio.object_acl_entries
                WHERE tenant_id = %s AND object_id = %s
                """,
                (tenant_id, second.task_object_id),
            ).fetchone()
        )
        receipt_count = first_int(
            connection.execute(
                """
                SELECT count(*) FROM tasks.creation_receipts
                WHERE tenant_id = %s AND mutation_reference = %s
                """,
                (tenant_id, second.mutation_reference),
            ).fetchone()
        )

    assert (task_count, acl_count, receipt_count) == (0, 0, 0)
