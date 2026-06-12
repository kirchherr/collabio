import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import GENESIS_HASH, PgAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations


@dataclass(frozen=True)
class LiveAuditDatabase:
    migration_dsn: str
    app_dsn: str
    audit_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveAuditDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    audit_dsn = env_or_skip("SUITE_AUDIT_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveAuditDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, audit_dsn=audit_dsn)


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def demo_user(*, tenant_id: str, user_id: str = "user-audit") -> UserContext:
    return UserContext(user_id=user_id, tenant_id=tenant_id, role_ids={"security-admin"})


def test_pg_audit_logger_records_hash_chain_without_plaintext_payloads(live_database: LiveAuditDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-audit-{suffix}"
    logger = PgAuditLogger(database_dsn=live_database.audit_dsn)

    first = logger.record(
        user_context=demo_user(tenant_id=tenant_id),
        event_type="ai.inference",
        model_id="mock-summarizer",
        prompt_template_id="document_summary_v1",
        source_object_ids=["doc-1"],
        input_text="sensitive prompt",
        output_text="sensitive output",
        metadata={"purpose": "summarization"},
    )
    second = logger.record(
        user_context=demo_user(tenant_id=tenant_id),
        event_type="rag.retrieval",
        source_object_ids=["doc-1"],
        input_text="question",
        metadata={"candidate_count": 1},
    )

    assert first.sequence_number == 1
    assert first.previous_event_hash == GENESIS_HASH
    assert first.input_hash != "sensitive prompt"
    assert first.output_hash != "sensitive output"
    assert second.sequence_number == 2
    assert second.previous_event_hash == first.event_hash
    assert logger.verify_tenant(tenant_id).ok

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        rows = owner_connection.execute(
            """
            SELECT sequence_number, input_hash, output_hash, metadata::text, previous_event_hash, event_hash
            FROM collabio.audit_events
            WHERE tenant_id = %s
            ORDER BY sequence_number
            """,
            (tenant_id,),
        ).fetchall()

    assert len(rows) == 2
    assert rows[0][0] == 1
    assert rows[0][1] == first.input_hash
    assert rows[0][2] == first.output_hash
    assert "sensitive prompt" not in str(rows)
    assert "sensitive output" not in str(rows)
    assert rows[1][4] == first.event_hash


def test_pg_audit_store_enforces_tenant_rls_and_runtime_role_permissions(
    live_database: LiveAuditDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-audit-a-{suffix}"
    tenant_b = f"tenant-audit-b-{suffix}"
    logger = PgAuditLogger(database_dsn=live_database.audit_dsn)
    event_a = logger.record(user_context=demo_user(tenant_id=tenant_a), event_type="tenant.a")
    event_b = logger.record(user_context=demo_user(tenant_id=tenant_b), event_type="tenant.b")

    with psycopg.connect(live_database.audit_dsn) as audit_connection:
        set_tenant(audit_connection, tenant_a)
        rows = audit_connection.execute(
            """
            SELECT tenant_id, event_type
            FROM collabio.audit_events
            WHERE event_hash IN (%s, %s)
            ORDER BY tenant_id
            """,
            (event_a.event_hash, event_b.event_hash),
        ).fetchall()

    assert rows == [(tenant_a, "tenant.a")]

    with psycopg.connect(live_database.audit_dsn) as audit_connection:
        set_tenant(audit_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            audit_connection.execute(
                """
                UPDATE collabio.audit_events
                SET event_type = 'changed'
                WHERE tenant_id = %s
                """,
                (tenant_a,),
            )

    with psycopg.connect(live_database.audit_dsn) as audit_connection:
        set_tenant(audit_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            audit_connection.execute(
                """
                DELETE FROM collabio.audit_events
                WHERE tenant_id = %s
                """,
                (tenant_a,),
            )

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            app_connection.execute(
                """
                SELECT event_id
                FROM collabio.audit_events
                WHERE tenant_id = %s
                """,
                (tenant_a,),
            )


def test_pg_audit_logger_creates_hmac_checkpoint_and_worm_export_evidence(
    live_database: LiveAuditDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-audit-checkpoint-{suffix}"
    logger = PgAuditLogger(database_dsn=live_database.audit_dsn)
    first = logger.record(user_context=demo_user(tenant_id=tenant_id), event_type="checkpoint.first")
    second = logger.record(user_context=demo_user(tenant_id=tenant_id), event_type="checkpoint.second")

    checkpoint = logger.create_checkpoint(
        tenant_id=tenant_id,
        created_by="security-admin",
        signature_key_ref=f"kms://{tenant_id}/audit/hmac/v1",
        signing_secret="test-only-checkpoint-secret",
    )
    export = logger.record_worm_export(
        tenant_id=tenant_id,
        checkpoint_id=checkpoint.checkpoint_id,
        export_manifest_hash="sha256:" + ("a" * 64),
        storage_uri=f"s3://audit-worm/{tenant_id}/{checkpoint.checkpoint_id}.jsonl",
        created_by="security-admin",
    )

    assert checkpoint.through_sequence_number == 2
    assert checkpoint.event_count == 2
    assert checkpoint.first_event_hash == first.event_hash
    assert checkpoint.last_event_hash == second.event_hash
    assert checkpoint.checkpoint_hash.startswith("hmac-sha256:")
    assert checkpoint.audit_chain_ref.startswith("audit:")
    assert export.checkpoint_id == checkpoint.checkpoint_id
    assert export.through_sequence_number == 2
    assert export.event_count == 2
    assert export.first_event_hash == first.event_hash
    assert export.last_event_hash == second.event_hash
    assert export.checkpoint_hash == checkpoint.checkpoint_hash
    assert export.object_lock_mode == "compliance"
    assert export.audit_chain_ref.startswith("audit:")

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        checkpoint_row = owner_connection.execute(
            """
            SELECT through_sequence_number, event_count, checkpoint_hash, signature_algorithm, signature_key_ref
            FROM collabio.audit_checkpoints
            WHERE tenant_id = %s
              AND checkpoint_id = %s
            """,
            (tenant_id, checkpoint.checkpoint_id),
        ).fetchone()
        export_row = owner_connection.execute(
            """
            SELECT through_sequence_number, event_count, checkpoint_hash, export_manifest_hash, object_lock_mode
            FROM collabio.audit_worm_exports
            WHERE tenant_id = %s
              AND export_id = %s
            """,
            (tenant_id, export.export_id),
        ).fetchone()

    assert checkpoint_row == (
        2,
        2,
        checkpoint.checkpoint_hash,
        "hmac-sha256",
        checkpoint.signature_key_ref,
    )
    assert export_row == (
        2,
        2,
        checkpoint.checkpoint_hash,
        export.export_manifest_hash,
        "compliance",
    )
