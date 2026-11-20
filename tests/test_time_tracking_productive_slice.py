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
    CorrectTimeEntryCommand,
    CreateTimeEntryCommand,
    InMemoryTimeTrackingStore,
    PgTimeTrackingStore,
    TimeApprovalAction,
    TimeApprovalState,
    TimeTrackingConflict,
    TimeTrackingService,
    TransitionTimeApprovalCommand,
    time_approval_confirmation_statement,
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


def decision_command(
    suffix: str,
    *,
    expected_state: TimeApprovalState,
    target_state: TimeApprovalState,
    action: TimeApprovalAction,
    approval_object_id: str,
) -> TransitionTimeApprovalCommand:
    return TransitionTimeApprovalCommand(
        mutation_reference=f"request:time-decision-{suffix}",
        decision_object_id=f"time-decision-{suffix}",
        expected_state=expected_state,
        target_state=target_state,
        action=action,
        human_confirmation_statement=(
            None
            if action == TimeApprovalAction.SUBMIT
            else time_approval_confirmation_statement(
                approval_object_id=approval_object_id,
                target_state=target_state,
            )
        ),
    )


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


def test_postgres_time_approval_decisions_are_derived_from_append_only_chain(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-time-decisions-{suffix}"
    worker_id = f"worker-{suffix}"
    approver_id = f"approver-{suffix}"
    command = entry_command(suffix)
    store = PgTimeTrackingStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )
    store.create_entry(tenant_id=tenant_id, user_id=worker_id, command=command)
    submit = decision_command(
        f"submit-{suffix}",
        expected_state=TimeApprovalState.NOT_SUBMITTED,
        target_state=TimeApprovalState.SUBMITTED,
        action=TimeApprovalAction.SUBMIT,
        approval_object_id=command.approval_object_id,
    )
    _, submitted, first_decision, first_replay = store.transition_approval(
        tenant_id=tenant_id,
        user_id=worker_id,
        approval_object_id=command.approval_object_id,
        command=submit,
    )
    _, _, replayed_decision, replayed = store.transition_approval(
        tenant_id=tenant_id,
        user_id=worker_id,
        approval_object_id=command.approval_object_id,
        command=submit,
    )
    approve = decision_command(
        f"approve-{suffix}",
        expected_state=TimeApprovalState.SUBMITTED,
        target_state=TimeApprovalState.APPROVED,
        action=TimeApprovalAction.APPROVE,
        approval_object_id=command.approval_object_id,
    )
    approved_entry, approved, second_decision, second_replay = store.transition_approval(
        tenant_id=tenant_id,
        user_id=approver_id,
        approval_object_id=command.approval_object_id,
        command=approve,
    )

    with psycopg.connect(live_database.migration_dsn) as connection:
        decision_count = first_int(
            connection.execute(
                "SELECT count(*) FROM time_tracking.approval_decisions WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        )
        stored_state = connection.execute(
            """
            SELECT entry.lifecycle_state, approval.approval_state
            FROM time_tracking.entries AS entry
            JOIN time_tracking.approvals AS approval
              ON approval.tenant_id = entry.tenant_id
             AND approval.entry_object_id = entry.object_id
            WHERE entry.tenant_id = %s AND entry.object_id = %s
            """,
            (tenant_id, command.entry_object_id),
        ).fetchone()

    assert first_replay is False
    assert replayed is True
    assert second_replay is False
    assert submitted.approval_state == TimeApprovalState.SUBMITTED
    assert first_decision.sequence_no == 1
    assert replayed_decision.decision_hash == first_decision.decision_hash
    assert second_decision.sequence_no == 2
    assert second_decision.previous_decision_hash == first_decision.decision_hash
    assert second_decision.confirmation_statement_hash is not None
    assert approved.approval_state == TimeApprovalState.APPROVED
    assert approved.approver_principal_id == approver_id
    assert approved_entry.lifecycle_state.value == "approved"
    assert decision_count == 2
    assert stored_state == ("recorded", "not_submitted")
    assert store.list_entries(tenant_id=tenant_id)[0].lifecycle_state.value == "approved"
    assert store.list_approvals(tenant_id=tenant_id)[0].approval_state == TimeApprovalState.APPROVED


def test_postgres_time_correction_is_versioned_and_bound_to_resubmission(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-time-correction-{suffix}"
    worker_id = f"worker-{suffix}"
    approver_id = f"approver-{suffix}"
    command = entry_command(suffix)
    store = PgTimeTrackingStore(
        read_database_dsn=live_database.app_dsn,
        write_database_dsn=live_database.authz_admin_dsn,
    )
    store.create_entry(tenant_id=tenant_id, user_id=worker_id, command=command)
    submit = decision_command(
        f"submit-{suffix}",
        expected_state=TimeApprovalState.NOT_SUBMITTED,
        target_state=TimeApprovalState.SUBMITTED,
        action=TimeApprovalAction.SUBMIT,
        approval_object_id=command.approval_object_id,
    )
    store.transition_approval(
        tenant_id=tenant_id,
        user_id=worker_id,
        approval_object_id=command.approval_object_id,
        command=submit,
    )
    request_correction = decision_command(
        f"request-correction-{suffix}",
        expected_state=TimeApprovalState.SUBMITTED,
        target_state=TimeApprovalState.CORRECTION_REQUESTED,
        action=TimeApprovalAction.REQUEST_CORRECTION,
        approval_object_id=command.approval_object_id,
    )
    _, requested, request_decision, _ = store.transition_approval(
        tenant_id=tenant_id,
        user_id=approver_id,
        approval_object_id=command.approval_object_id,
        command=request_correction,
    )
    resubmit = decision_command(
        f"resubmit-{suffix}",
        expected_state=TimeApprovalState.CORRECTION_REQUESTED,
        target_state=TimeApprovalState.SUBMITTED,
        action=TimeApprovalAction.SUBMIT,
        approval_object_id=command.approval_object_id,
    )
    with pytest.raises(TimeTrackingConflict, match="requires a newer bound correction"):
        store.transition_approval(
            tenant_id=tenant_id,
            user_id=worker_id,
            approval_object_id=command.approval_object_id,
            command=resubmit,
        )

    correction_command = CorrectTimeEntryCommand(
        mutation_reference=f"request:time-correction-{suffix}",
        correction_object_id=f"time-correction-{suffix}",
        expected_revision_no=0,
        expected_approval_state=TimeApprovalState.CORRECTION_REQUESTED,
        work_date=date(2026, 7, 30),
        started_at_utc=datetime(2026, 7, 30, 8, 15, tzinfo=UTC),
        ended_at_utc=datetime(2026, 7, 30, 13, 0, tzinfo=UTC),
        project_reference="project:customer-review",
        cost_center_reference="cost-center:delivery",
    )
    corrected, correction_approval, correction, replayed = store.correct_entry(
        tenant_id=tenant_id,
        user_id=worker_id,
        entry_object_id=command.entry_object_id,
        command=correction_command,
    )
    _, _, replayed_correction, replayed_again = store.correct_entry(
        tenant_id=tenant_id,
        user_id=worker_id,
        entry_object_id=command.entry_object_id,
        command=correction_command,
    )
    resubmitted_entry, resubmitted, resubmit_decision, resubmitted_replay = store.transition_approval(
        tenant_id=tenant_id,
        user_id=worker_id,
        approval_object_id=command.approval_object_id,
        command=resubmit,
    )

    with psycopg.connect(live_database.migration_dsn) as connection:
        correction_count = first_int(
            connection.execute(
                "SELECT count(*) FROM time_tracking.entry_corrections WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        )
        decision_count = first_int(
            connection.execute(
                "SELECT count(*) FROM time_tracking.approval_decisions WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()
        )
        stored_binding = connection.execute(
            """
            SELECT correction_revision_no, correction_hash, schema_version
            FROM time_tracking.approval_decisions
            WHERE tenant_id = %s AND object_id = %s
            """,
            (tenant_id, resubmit.decision_object_id),
        ).fetchone()
        immutable_base = connection.execute(
            """
            SELECT entry.started_at_utc, entry.ended_at_utc, approval.approval_state
            FROM time_tracking.entries AS entry
            JOIN time_tracking.approvals AS approval
              ON approval.tenant_id = entry.tenant_id
             AND approval.entry_object_id = entry.object_id
            WHERE entry.tenant_id = %s AND entry.object_id = %s
            """,
            (tenant_id, command.entry_object_id),
        ).fetchone()

    assert requested.approval_state == TimeApprovalState.CORRECTION_REQUESTED
    assert replayed is False
    assert replayed_again is True
    assert corrected.revision_no == 1
    assert corrected.duration_minutes == 285
    assert correction_approval.approval_state == TimeApprovalState.CORRECTION_REQUESTED
    assert correction.correction_request_decision_hash == request_decision.decision_hash
    assert replayed_correction.correction_hash == correction.correction_hash
    assert resubmitted_replay is False
    assert resubmitted.approval_state == TimeApprovalState.SUBMITTED
    assert resubmitted_entry.revision_no == 1
    assert resubmit_decision.correction_revision_no == 1
    assert resubmit_decision.correction_hash == correction.correction_hash
    assert correction_count == 1
    assert decision_count == 3
    assert stored_binding == (1, correction.correction_hash, "time_approval_decision.v2")
    assert immutable_base == (
        datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        datetime(2026, 7, 30, 12, 30, tzinfo=UTC),
        "not_submitted",
    )
    projected = store.list_entries(tenant_id=tenant_id)[0]
    assert projected.revision_no == 1
    assert projected.duration_minutes == 285
    assert projected.lifecycle_state.value == "submitted"
