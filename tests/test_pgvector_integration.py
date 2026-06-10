import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def ensure_app_role_and_grants(migration_dsn: str) -> None:
    with psycopg.connect(migration_dsn, autocommit=True) as connection:
        connection.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
                    CREATE ROLE collabio_app LOGIN PASSWORD 'collabio_app';
                END IF;
            END
            $$;
            """
        )
        connection.execute("ALTER ROLE collabio_app WITH LOGIN PASSWORD 'collabio_app'")
        connection.execute("GRANT USAGE ON SCHEMA collabio TO collabio_app")
        connection.execute("GRANT SELECT, REFERENCES ON TABLE collabio.embedding_models TO collabio_app")
        connection.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE collabio.vector_embedding_chunks TO collabio_app"
        )


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")

    apply_migrations(migration_dsn)
    ensure_app_role_and_grants(migration_dsn)

    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def seed_embedding_model(connection: psycopg.Connection[Any], model_id: str) -> None:
    connection.execute(
        """
        INSERT INTO collabio.embedding_models (
            embedding_model_id,
            embedding_model_version,
            provider,
            deployment,
            dimensions,
            distance_metric,
            checksum,
            approved_for_data_classes
        )
        VALUES (%s, '1', 'test', 'local', 3, 'cosine', 'sha256:test', ARRAY['embedding'])
        ON CONFLICT (embedding_model_id, embedding_model_version) DO NOTHING
        """,
        (model_id,),
    )


def insert_chunk(
    connection: psycopg.Connection[Any],
    *,
    tenant_id: str,
    source_object_id: str,
    chunk_id: str,
    model_id: str,
    lifecycle_state: str = "active",
    restricted_at_utc: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO collabio.vector_embedding_chunks (
            tenant_id,
            source_object_id,
            source_object_type,
            source_version_id,
            chunk_id,
            classification,
            retention_policy_id,
            legal_hold_state,
            acl_hash,
            acl_version,
            embedding_model_id,
            embedding_model_version,
            embedding_dimensions,
            embedding,
            content_hash,
            content_byte_length,
            lifecycle_state,
            indexed_at_utc,
            restricted_at_utc,
            audit_event_id
        )
        VALUES (
            %s, %s, 'document', 'v1', %s, 'embedding', 'rp-standard', 'none',
            'sha256:acl', 1, %s, '1', 3, %s::vector, 'sha256:content', 42,
            %s, now(), %s, 'audit-test'
        )
        """,
        (
            tenant_id,
            source_object_id,
            chunk_id,
            model_id,
            vector_literal([0.1, 0.2, 0.3]),
            lifecycle_state,
            restricted_at_utc,
        ),
    )


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def test_migrator_applies_pgvector_extension_and_records_version(live_database: LiveDatabase) -> None:
    first_result = apply_migrations(live_database.migration_dsn)
    second_result = apply_migrations(live_database.migration_dsn)

    assert "0001" in first_result.applied_versions + first_result.skipped_versions
    assert "0001" in second_result.skipped_versions

    with psycopg.connect(live_database.migration_dsn) as connection:
        extension_row = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
        migration_row = connection.execute(
            "SELECT version FROM collabio.schema_migrations WHERE version = '0001'"
        ).fetchone()

    assert extension_row is not None
    assert migration_row == ("0001",)


def test_pgvector_rls_returns_only_active_candidates_for_current_tenant(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    model_id = f"embedding-model-{suffix}"

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        insert_chunk(
            owner_connection,
            tenant_id=tenant_a,
            source_object_id=f"doc-active-{suffix}",
            chunk_id=f"chunk-active-{suffix}",
            model_id=model_id,
        )
        insert_chunk(
            owner_connection,
            tenant_id=tenant_a,
            source_object_id=f"doc-restricted-{suffix}",
            chunk_id=f"chunk-restricted-{suffix}",
            model_id=model_id,
            lifecycle_state="restricted",
            restricted_at_utc="2026-06-10T00:00:00Z",
        )
        insert_chunk(
            owner_connection,
            tenant_id=tenant_b,
            source_object_id=f"doc-other-{suffix}",
            chunk_id=f"chunk-other-{suffix}",
            model_id=model_id,
        )
        owner_connection.commit()

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        rows = app_connection.execute(
            """
            SELECT tenant_id, chunk_id
            FROM collabio.vector_embedding_chunks
            WHERE embedding_model_id = %s
            ORDER BY chunk_id
            """,
            (model_id,),
        ).fetchall()

    assert rows == [(tenant_a, f"chunk-active-{suffix}")]


def test_pgvector_rls_blocks_cross_tenant_insert_and_hard_delete(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    model_id = f"embedding-model-{suffix}"
    own_chunk_id = f"chunk-own-{suffix}"

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        insert_chunk(
            app_connection,
            tenant_id=tenant_a,
            source_object_id=f"doc-own-{suffix}",
            chunk_id=own_chunk_id,
            model_id=model_id,
        )
        app_connection.commit()

        set_tenant(app_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            insert_chunk(
                app_connection,
                tenant_id=tenant_b,
                source_object_id=f"doc-cross-{suffix}",
                chunk_id=f"chunk-cross-{suffix}",
                model_id=model_id,
            )
        app_connection.rollback()

        set_tenant(app_connection, tenant_a)
        delete_cursor = app_connection.execute(
            """
            DELETE FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s AND chunk_id = %s AND embedding_model_id = %s
            """,
            (tenant_a, own_chunk_id, model_id),
        )
        app_connection.commit()

    assert delete_cursor.rowcount == 0

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        row = owner_connection.execute(
            """
            SELECT lifecycle_state
            FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s AND chunk_id = %s AND embedding_model_id = %s
            """,
            (tenant_a, own_chunk_id, model_id),
        ).fetchone()

    assert row == ("active",)
