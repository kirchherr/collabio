import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.time_tracking_service import (
    CreateTimeEntryCommand,
    InMemoryTimeTrackingStore,
    PgTimeTrackingStore,
    TimeApprovalState,
    TimeTrackingConflict,
    TimeTrackingService,
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
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, authz_admin_dsn=authz_admin_dsn)


def entry_command(suffix: str, *, mutation_reference: str | None = None) -> CreateTimeEntryCommand:
    return CreateTimeEntryCommand(
        mutation_reference=mutation_reference or f"request:time-entry-{suffix}",
        entry_object_id=f"time-entry-{suffix}",
        entry_number=f"TIME-{suffix}",
        work_date=date(2026, 7, 30),
        started_at_utc=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        ended_at_utc=datetime(2026, 7, 30, 12, 30, tzinfo=UTC),
        project_reference="project:customer-review",
        cost_center_reference="cost-center:delivery",
        approval_object_id=f"time-approval-{suffix}",
        approval_number=f"TIME-APPROVAL-{suffix}",
    )


def first_int(row: tuple[Any, ...] | None) -> int:
    assert row is not None
    return int(row[0])


def test_time_entry_creation_enforces_role_idempotency_and_authoritative_reads() -> None:
    audit_logger = InMemoryAuditLogger()
    service = TimeTrackingService(store=InMemoryTimeTrackingStore(), audit_logger=audit_logger)
    command = entry_command("memory")
    reader = UserContext(tenant_id="tenant-memory", user_id="reader", role_ids={"knowledge-worker"})

    with pytest.raises(PermissionError, match="creator role required"):
        service.create_entry(user_context=reader, command=command)

    worker = UserContext(tenant_id="tenant-memory", user_id="worker", role_ids={"time-worker"})
    created = service.create_entry(user_context=worker, command=command)
    replay = service.create_entry(user_context=worker, command=command)

    assert created.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.receipt.receipt_hash == created.receipt.receipt_hash
    assert created.entry.duration_minutes == 270
    assert created.approval.approval_state == TimeApprovalState.NOT_SUBMITTED
    assert created.approval.approver_principal_id is None
    assert created.acl_grant_count == 2
    assert created.receipt_content_included is False
    assert "project_reference" not in created.receipt.model_dump_json()
    assert audit_logger.events[-1].event_type == "time_tracking.entry.creation.replayed"

    with pytest.raises(TimeTrackingConflict, match="different time entry command"):
        service.create_entry(
            user_context=worker,
            command=command.model_copy(update={"cost_center_reference": "cost-center:changed"}),
        )

    fully_authorized = worker.model_copy(
        update={"readable_object_ids": {command.entry_object_id, command.approval_object_id}}
    )
    approval_only = worker.model_copy(update={"readable_object_ids": {command.approval_object_id}})
    assert len(service.list_entries(user_context=fully_authorized).entries) == 1
    assert len(service.list_approvals(user_context=fully_authorized).approvals) == 1
    assert service.list_approvals(user_context=approval_only).approvals == []


def test_postgres_time_entry_creation_commits_all_surfaces_atomically(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-time-{suffix}"
    user_id = f"worker-{suffix}"
    command = entry_command(suffix)
    store = PgTimeTrackingStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )

    entry, approval, receipt, replayed = store.create_entry(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )
    replay_entry, replay_approval, replay_receipt, replayed_again = store.create_entry(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )

    with psycopg.connect(live_database.migration_dsn) as connection:
        counts = tuple(
            first_int(
                connection.execute(
                    f"SELECT count(*) FROM {table} WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()
            )
            for table in (
                "time_tracking.entries",
                "time_tracking.approvals",
                "time_tracking.entry_creation_receipts",
            )
        )
        acl_count = first_int(
            connection.execute(
                "SELECT count(*) FROM collabio.object_acl_entries WHERE tenant_id = %s AND audit_chain_ref = %s",
                (tenant_id, receipt.audit_chain_ref),
            ).fetchone()
        )

    assert replayed is False
    assert replayed_again is True
    assert replay_entry.object_id == entry.object_id
    assert replay_approval.object_id == approval.object_id
    assert replay_receipt.receipt_hash == receipt.receipt_hash
    assert counts == (1, 1, 1)
    assert acl_count == 2
    assert len(store.list_entries(tenant_id=tenant_id)) == 1
    assert len(store.list_approvals(tenant_id=tenant_id)) == 1


def test_postgres_time_entry_creation_rolls_back_on_approval_collision(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-time-rollback-{suffix}"
    user_id = f"worker-{suffix}"
    store = PgTimeTrackingStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )
    first = entry_command(f"first-{suffix}")
    store.create_entry(tenant_id=tenant_id, user_id=user_id, command=first)
    second = entry_command(f"second-{suffix}").model_copy(update={"approval_object_id": first.approval_object_id})

    with pytest.raises(TimeTrackingConflict, match="already exist"):
        store.create_entry(tenant_id=tenant_id, user_id=user_id, command=second)

    with psycopg.connect(live_database.migration_dsn) as connection:
        entry_count = first_int(
            connection.execute(
                "SELECT count(*) FROM time_tracking.entries WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, second.entry_object_id),
            ).fetchone()
        )
        acl_count = first_int(
            connection.execute(
                "SELECT count(*) FROM collabio.object_acl_entries WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, second.entry_object_id),
            ).fetchone()
        )
        receipt_count = first_int(
            connection.execute(
                "SELECT count(*) FROM time_tracking.entry_creation_receipts "
                "WHERE tenant_id = %s AND mutation_reference = %s",
                (tenant_id, second.mutation_reference),
            ).fetchone()
        )

    assert (entry_count, acl_count, receipt_count) == (0, 0, 0)
