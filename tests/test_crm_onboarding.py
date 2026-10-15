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
from suite.platform.crm_activities import CrmActivityType
from suite.platform.crm_onboarding import (
    CRM_ONBOARDING_ROLE_IDS,
    CrmAccountCreate,
    CrmAccountOnboardingCommand,
    CrmAccountOnboardingService,
    CrmActivityCreate,
    CrmContactCreate,
    CrmNoteCreate,
    CrmOnboardingConflict,
    InMemoryCrmAccountOnboardingStore,
    PgCrmAccountOnboardingStore,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    authz_admin_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    authz_admin_dsn = env_or_skip("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, authz_admin_dsn=authz_admin_dsn)


def onboarding_command(suffix: str, *, mutation_reference: str | None = None) -> CrmAccountOnboardingCommand:
    return CrmAccountOnboardingCommand(
        mutation_reference=mutation_reference or f"request:crm-onboarding-{suffix}",
        account=CrmAccountCreate(
            object_id=f"crm-account-{suffix}",
            account_number=f"ACCT-{suffix}",
            display_name="Atomic Customer GmbH",
        ),
        contact=CrmContactCreate(
            object_id=f"crm-contact-{suffix}",
            contact_number=f"CONT-{suffix}",
            display_name="Alex Example",
            given_name="Alex",
            family_name="Example",
            primary_email="alex@example.test",
            role_label="Buyer",
        ),
        activity=CrmActivityCreate(
            object_id=f"crm-activity-{suffix}",
            activity_number=f"ACT-{suffix}",
            activity_type=CrmActivityType.FOLLOW_UP,
            subject="Initial follow-up",
            due_at_utc=datetime(2026, 8, 3, 9, tzinfo=UTC),
        ),
        note=CrmNoteCreate(
            object_id=f"crm-note-{suffix}",
            note_number=f"NOTE-{suffix}",
            title="Onboarding metadata",
        ),
    )


def first_int(row: tuple[Any, ...] | None) -> int:
    assert row is not None
    return int(row[0])


def test_in_memory_onboarding_enforces_role_and_actor_bound_idempotency() -> None:
    audit_logger = InMemoryAuditLogger()
    service = CrmAccountOnboardingService(
        store=InMemoryCrmAccountOnboardingStore(),
        audit_logger=audit_logger,
    )
    command = onboarding_command("memory")

    with pytest.raises(PermissionError, match="CRM operator role required"):
        service.create(
            user_context=UserContext(
                tenant_id="tenant-memory",
                user_id="reader",
                role_ids={"knowledge-worker"},
            ),
            command=command,
        )

    context = UserContext(
        tenant_id="tenant-memory",
        user_id="operator",
        role_ids={next(iter(CRM_ONBOARDING_ROLE_IDS))},
    )
    first = service.create(user_context=context, command=command)
    replay = service.create(user_context=context, command=command)

    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.receipt.receipt_hash == first.receipt.receipt_hash
    assert first.acl_grant_count == 4
    assert first.content_included is False
    assert audit_logger.events[-1].event_type == "crm.account.onboarding.replayed"
    assert "primary_email" not in audit_logger.events[-1].metadata

    with pytest.raises(CrmOnboardingConflict, match="different command"):
        service.create(
            user_context=context,
            command=command.model_copy(update={"note": command.note.model_copy(update={"title": "Changed title"})}),
        )

    with pytest.raises(CrmOnboardingConflict, match="different command"):
        service.create(
            user_context=context.model_copy(update={"user_id": "different-operator"}),
            command=command,
        )


def test_postgres_onboarding_commits_business_rows_acls_and_receipt_atomically(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-crm-onboarding-{suffix}"
    user_id = f"operator-{suffix}"
    command = onboarding_command(suffix)
    store = PgCrmAccountOnboardingStore(database_dsn=live_database.authz_admin_dsn)

    receipt, replayed = store.create(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )
    replay, replayed_again = store.create(
        tenant_id=tenant_id,
        user_id=user_id,
        command=command,
    )

    with psycopg.connect(live_database.migration_dsn) as connection:
        business_counts = tuple(
            first_int(
                connection.execute(
                    f"SELECT count(*) FROM crm.{table} WHERE tenant_id = %s AND audit_chain_ref = %s",
                    (tenant_id, receipt.audit_chain_ref),
                ).fetchone()
            )
            for table in ("accounts", "contacts", "activities", "notes")
        )
        acl_rows = connection.execute(
            """
            SELECT object_type, object_id, acl_subject_id, permission, acl_version, audit_chain_ref
            FROM collabio.object_acl_entries
            WHERE tenant_id = %s AND audit_chain_ref = %s
            ORDER BY object_type
            """,
            (tenant_id, receipt.audit_chain_ref),
        ).fetchall()
        receipt_count = first_int(
            connection.execute(
                """
            SELECT count(*) FROM crm.account_onboarding_receipts
            WHERE tenant_id = %s AND mutation_reference = %s
            """,
                (tenant_id, command.mutation_reference),
            ).fetchone()
        )

    assert replayed is False
    assert replayed_again is True
    assert replay.receipt_hash == receipt.receipt_hash
    assert business_counts == (1, 1, 1, 1)
    assert len(acl_rows) == 4
    assert all(row[2:] == (user_id, "admin", 1, receipt.audit_chain_ref) for row in acl_rows)
    assert receipt_count == 1


def test_postgres_onboarding_rolls_back_every_surface_on_partial_collision(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-crm-rollback-{suffix}"
    user_id = f"operator-{suffix}"
    store = PgCrmAccountOnboardingStore(database_dsn=live_database.authz_admin_dsn)
    first = onboarding_command(f"first-{suffix}")
    store.create(tenant_id=tenant_id, user_id=user_id, command=first)

    second = onboarding_command(f"second-{suffix}")
    second = second.model_copy(
        update={
            "contact": second.contact.model_copy(update={"object_id": first.contact.object_id}),
        }
    )
    with pytest.raises(CrmOnboardingConflict, match="already exist"):
        store.create(tenant_id=tenant_id, user_id=user_id, command=second)

    with psycopg.connect(live_database.migration_dsn) as connection:
        rolled_back_account = first_int(
            connection.execute(
                "SELECT count(*) FROM crm.accounts WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, second.account.object_id),
            ).fetchone()
        )
        rolled_back_acl = first_int(
            connection.execute(
                "SELECT count(*) FROM collabio.object_acl_entries WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, second.account.object_id),
            ).fetchone()
        )
        rolled_back_receipt = first_int(
            connection.execute(
                """
            SELECT count(*) FROM crm.account_onboarding_receipts
            WHERE tenant_id = %s AND mutation_reference = %s
            """,
                (tenant_id, second.mutation_reference),
            ).fetchone()
        )

    assert rolled_back_account == 0
    assert rolled_back_acl == 0
    assert rolled_back_receipt == 0
