import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migrator import apply_migrations
from suite.rag.models import ChunkMetadata, SourceDocument, VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.pgvector_store import PgvectorVectorStore
from suite.rag.repositories import InMemorySourceRepository
from suite.rag.source_indexing import (
    DeterministicHashEmbeddingProvider,
    FixedSizeTextChunker,
    PlainTextExtractor,
    RepositorySourceResolver,
    SourceIndexCommand,
    SourceIndexingPipeline,
)
from suite.rag.vector_worker import DeletionPropagationCommand, ReindexSourceCommand, VectorIndexWorker


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str
    worker_dsn: str


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
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
                    CREATE ROLE collabio_worker LOGIN PASSWORD 'collabio_worker';
                END IF;
            END
            $$;
            """
        )
        connection.execute("ALTER ROLE collabio_app WITH LOGIN PASSWORD 'collabio_app'")
        connection.execute("ALTER ROLE collabio_worker WITH LOGIN PASSWORD 'collabio_worker'")
        connection.execute("GRANT USAGE ON SCHEMA collabio TO collabio_app")
        connection.execute("GRANT SELECT, REFERENCES ON TABLE collabio.embedding_models TO collabio_app")
        connection.execute("GRANT SELECT ON TABLE collabio.vector_embedding_chunks TO collabio_app")
        connection.execute("GRANT USAGE ON SCHEMA collabio TO collabio_worker")
        connection.execute("GRANT SELECT, REFERENCES ON TABLE collabio.embedding_models TO collabio_worker")
        connection.execute("GRANT SELECT, INSERT, UPDATE ON TABLE collabio.vector_embedding_chunks TO collabio_worker")


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")

    apply_migrations(migration_dsn)
    ensure_app_role_and_grants(migration_dsn)

    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, worker_dsn=worker_dsn)


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


def chunk_metadata(
    *,
    tenant_id: str,
    source_object_id: str,
    chunk_id: str,
    model_id: str,
    content_hash: str = "sha256:content",
) -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_object_type="document",
        source_version_id="v1",
        chunk_id=chunk_id,
        classification=DataClass.EMBEDDING,
        retention_policy_id="rp-standard",
        legal_hold_state="none",
        acl_hash="sha256:acl",
        acl_version=1,
        created_at_utc="2026-06-10T00:00:00Z",
        embedding_model_id=model_id,
        embedding_model_version="1",
        content_hash=content_hash,
    )


def embedding_record(
    *,
    tenant_id: str,
    source_object_id: str,
    chunk_id: str,
    model_id: str,
    embedding: list[float],
    content_hash: str = "sha256:content",
) -> VectorEmbeddingRecord:
    return VectorEmbeddingRecord(
        metadata=chunk_metadata(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            chunk_id=chunk_id,
            model_id=model_id,
            content_hash=content_hash,
        ),
        embedding=embedding,
        embedding_dimensions=len(embedding),
        content_byte_length=42,
        indexed_at_utc="2026-06-10T00:01:00Z",
        audit_event_id="audit-test",
    )


def pgvector_store(
    *,
    app_dsn: str,
    worker_dsn: str,
    model_id: str,
    query_embedding: list[float],
) -> PgvectorVectorStore:
    return PgvectorVectorStore(
        database_dsn=app_dsn,
        lifecycle_database_dsn=worker_dsn,
        embedding_model_id=model_id,
        embedding_model_version="1",
        query_embedder=lambda _query: query_embedding,
    )


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


def test_pgvector_runtime_app_role_cannot_write_or_hard_delete(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    model_id = f"embedding-model-{suffix}"
    own_chunk_id = f"chunk-own-{suffix}"

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        insert_chunk(
            owner_connection,
            tenant_id=tenant_a,
            source_object_id=f"doc-own-{suffix}",
            chunk_id=own_chunk_id,
            model_id=model_id,
        )
        owner_connection.commit()

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            insert_chunk(
                app_connection,
                tenant_id=tenant_a,
                source_object_id=f"doc-new-{suffix}",
                chunk_id=f"chunk-new-{suffix}",
                model_id=model_id,
            )
        app_connection.rollback()

        set_tenant(app_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            app_connection.execute(
                """
                DELETE FROM collabio.vector_embedding_chunks
                WHERE tenant_id = %s AND chunk_id = %s AND embedding_model_id = %s
                """,
                (tenant_a, own_chunk_id, model_id),
            )

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


def test_pgvector_store_upserts_and_returns_candidate_metadata_only(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-adapter-{suffix}"
    other_tenant_id = f"tenant-other-{suffix}"
    model_id = f"embedding-model-{suffix}"
    store = pgvector_store(
        app_dsn=live_database.app_dsn,
        worker_dsn=live_database.worker_dsn,
        model_id=model_id,
        query_embedding=[1.0, 0.0, 0.0],
    )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=f"doc-{suffix}",
            chunk_id=f"chunk-{suffix}",
            model_id=model_id,
            embedding=[1.0, 0.0, 0.0],
        )
    )

    candidates = store.search(tenant_id=tenant_id, query="find matching vector", top_k=5)
    other_tenant_candidates = store.search(tenant_id=other_tenant_id, query="find matching vector", top_k=5)

    assert len(candidates) == 1
    assert candidates[0].score == pytest.approx(1.0)
    assert candidates[0].metadata.tenant_id == tenant_id
    assert candidates[0].metadata.source_object_id == f"doc-{suffix}"
    assert candidates[0].metadata.chunk_id == f"chunk-{suffix}"
    assert not hasattr(candidates[0].metadata, "source_text")
    assert other_tenant_candidates == []


def test_pgvector_store_upsert_updates_existing_vector_metadata(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-adapter-{suffix}"
    model_id = f"embedding-model-{suffix}"
    store = pgvector_store(
        app_dsn=live_database.app_dsn,
        worker_dsn=live_database.worker_dsn,
        model_id=model_id,
        query_embedding=[0.0, 1.0, 0.0],
    )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=f"doc-{suffix}",
            chunk_id=f"chunk-{suffix}",
            model_id=model_id,
            embedding=[1.0, 0.0, 0.0],
            content_hash="sha256:old-content",
        )
    )
    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=f"doc-{suffix}",
            chunk_id=f"chunk-{suffix}",
            model_id=model_id,
            embedding=[0.0, 1.0, 0.0],
            content_hash="sha256:new-content",
        )
    )

    candidates = store.search_by_embedding(tenant_id=tenant_id, embedding=[0.0, 1.0, 0.0], top_k=5)

    assert len(candidates) == 1
    assert candidates[0].score == pytest.approx(1.0)
    assert candidates[0].metadata.content_hash == "sha256:new-content"


def test_pgvector_store_lifecycle_transition_hides_candidate(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-adapter-{suffix}"
    model_id = f"embedding-model-{suffix}"
    source_object_id = f"doc-{suffix}"
    chunk_id = f"chunk-{suffix}"
    store = pgvector_store(
        app_dsn=live_database.app_dsn,
        worker_dsn=live_database.worker_dsn,
        model_id=model_id,
        query_embedding=[1.0, 0.0, 0.0],
    )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            chunk_id=chunk_id,
            model_id=model_id,
            embedding=[1.0, 0.0, 0.0],
        )
    )

    assert store.search(tenant_id=tenant_id, query="visible before restriction", top_k=5)

    updated = store.transition_lifecycle(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id="v1",
        chunk_id=chunk_id,
        lifecycle_state=VectorLifecycleState.RESTRICTED,
        audit_event_id="audit-restricted",
    )

    assert updated
    assert store.search(tenant_id=tenant_id, query="hidden after restriction", top_k=5) == []

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        row = owner_connection.execute(
            """
            SELECT lifecycle_state, restricted_at_utc, audit_event_id
            FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s AND chunk_id = %s AND embedding_model_id = %s
            """,
            (tenant_id, chunk_id, model_id),
        ).fetchone()

    assert row is not None
    assert row[0] == VectorLifecycleState.RESTRICTED.value
    assert row[1] is not None
    assert row[2] == "audit-restricted"


def test_vector_worker_reindexes_source_and_deletes_stale_chunks(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-worker-{suffix}"
    model_id = f"embedding-model-{suffix}"
    source_object_id = f"doc-{suffix}"
    stale_chunk_id = f"chunk-stale-{suffix}"
    kept_chunk_id = f"chunk-kept-{suffix}"
    new_chunk_id = f"chunk-new-{suffix}"
    store = pgvector_store(
        app_dsn=live_database.app_dsn,
        worker_dsn=live_database.worker_dsn,
        model_id=model_id,
        query_embedding=[1.0, 0.0, 0.0],
    )
    worker = VectorIndexWorker(store)

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            chunk_id=kept_chunk_id,
            model_id=model_id,
            embedding=[0.0, 1.0, 0.0],
            content_hash="sha256:old-kept",
        )
    )
    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            chunk_id=stale_chunk_id,
            model_id=model_id,
            embedding=[0.0, 0.0, 1.0],
            content_hash="sha256:stale",
        )
    )

    result = worker.reindex_source(
        ReindexSourceCommand(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            source_version_id="v1",
            chunks=(
                embedding_record(
                    tenant_id=tenant_id,
                    source_object_id=source_object_id,
                    chunk_id=kept_chunk_id,
                    model_id=model_id,
                    embedding=[1.0, 0.0, 0.0],
                    content_hash="sha256:new-kept",
                ),
                embedding_record(
                    tenant_id=tenant_id,
                    source_object_id=source_object_id,
                    chunk_id=new_chunk_id,
                    model_id=model_id,
                    embedding=[0.9, 0.1, 0.0],
                    content_hash="sha256:new",
                ),
            ),
            audit_event_id="audit-reindex",
        )
    )

    candidates = store.search_by_embedding(tenant_id=tenant_id, embedding=[1.0, 0.0, 0.0], top_k=10)
    candidate_chunk_ids = {candidate.chunk_id for candidate in candidates}

    assert result.marked_reindex_pending == 2
    assert result.upserted_chunks == 2
    assert result.deleted_stale_chunks == 1
    assert candidate_chunk_ids == {kept_chunk_id, new_chunk_id}

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        rows = owner_connection.execute(
            """
            SELECT chunk_id, lifecycle_state, content_hash, deleted_at_utc
            FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s
              AND source_object_id = %s
              AND embedding_model_id = %s
            ORDER BY chunk_id
            """,
            (tenant_id, source_object_id, model_id),
        ).fetchall()

    rows_by_chunk = {str(row[0]): row for row in rows}
    assert rows_by_chunk[kept_chunk_id][1] == VectorLifecycleState.ACTIVE.value
    assert rows_by_chunk[kept_chunk_id][2] == "sha256:new-kept"
    assert rows_by_chunk[new_chunk_id][1] == VectorLifecycleState.ACTIVE.value
    assert rows_by_chunk[stale_chunk_id][1] == VectorLifecycleState.DELETED.value
    assert rows_by_chunk[stale_chunk_id][3] is not None


def test_vector_worker_propagates_source_deletion_and_blocks_app_reactivation(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-worker-{suffix}"
    model_id = f"embedding-model-{suffix}"
    source_object_id = f"doc-{suffix}"
    chunk_id = f"chunk-delete-{suffix}"
    store = pgvector_store(
        app_dsn=live_database.app_dsn,
        worker_dsn=live_database.worker_dsn,
        model_id=model_id,
        query_embedding=[1.0, 0.0, 0.0],
    )
    worker = VectorIndexWorker(store)

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    deleted_record = embedding_record(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        chunk_id=chunk_id,
        model_id=model_id,
        embedding=[1.0, 0.0, 0.0],
        content_hash="sha256:before-delete",
    )
    store.upsert_embedding(deleted_record)

    result = worker.propagate_deletion(
        DeletionPropagationCommand(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            source_version_id="v1",
            lifecycle_state=VectorLifecycleState.DELETED,
            audit_event_id="audit-delete",
        )
    )

    assert result.transitioned_chunks == 1
    assert store.search(tenant_id=tenant_id, query="hidden after deletion", top_k=5) == []

    store.upsert_embedding(
        embedding_record(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            chunk_id=chunk_id,
            model_id=model_id,
            embedding=[1.0, 0.0, 0.0],
            content_hash="sha256:worker-after-delete",
        )
    )

    app_write_store = PgvectorVectorStore(
        database_dsn=live_database.app_dsn,
        lifecycle_database_dsn=live_database.app_dsn,
        embedding_model_id=model_id,
        embedding_model_version="1",
        query_embedder=lambda _query: [1.0, 0.0, 0.0],
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
        app_write_store.upsert_embedding(
            embedding_record(
                tenant_id=tenant_id,
                source_object_id=source_object_id,
                chunk_id=chunk_id,
                model_id=model_id,
                embedding=[1.0, 0.0, 0.0],
                content_hash="sha256:after-delete",
            )
        )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        row = owner_connection.execute(
            """
            SELECT lifecycle_state, deleted_at_utc, content_hash, audit_event_id
            FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s
              AND source_object_id = %s
              AND chunk_id = %s
              AND embedding_model_id = %s
            """,
            (tenant_id, source_object_id, chunk_id, model_id),
        ).fetchone()

    assert row is not None
    assert row[0] == VectorLifecycleState.DELETED.value
    assert row[1] is not None
    assert row[2] == "sha256:before-delete"
    assert row[3] == "audit-delete"


def test_source_indexing_pipeline_feeds_pgvector_worker_and_deletes_stale_chunks(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-source-{suffix}"
    model_id = f"embedding-model-{suffix}"
    source_object_id = f"doc-{suffix}"
    embedder = DeterministicHashEmbeddingProvider(dimensions=3)
    store = PgvectorVectorStore(
        database_dsn=live_database.app_dsn,
        lifecycle_database_dsn=live_database.worker_dsn,
        embedding_model_id=model_id,
        embedding_model_version="1",
        query_embedder=embedder.embed,
    )
    worker = VectorIndexWorker(store)

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_embedding_model(owner_connection, model_id)
        owner_connection.commit()

    first_pipeline = SourceIndexingPipeline(
        resolver=RepositorySourceResolver(
            InMemorySourceRepository(
                documents={
                    source_object_id: SourceDocument(
                        object_id=source_object_id,
                        version_id="v1",
                        title="Indexable source",
                        text=(
                            "First policy paragraph requires citation. "
                            "Second policy paragraph requires approval. "
                            "Third policy paragraph requires retention."
                        ),
                        classification=DataClass.INTERNAL,
                    )
                }
            ),
            created_at_clock=lambda: "2026-06-10T00:00:00Z",
        ),
        text_extractor=PlainTextExtractor(),
        chunker=FixedSizeTextChunker(max_characters=48),
        embedding_provider=embedder,
        worker=worker,
        embedding_model_id=model_id,
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:01:00Z",
    )
    first_result = first_pipeline.index_source(
        SourceIndexCommand(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            source_version_id="v1",
            audit_event_id="audit-first-index",
        )
    )

    second_text = "Replacement policy paragraph requires citation."
    second_pipeline = SourceIndexingPipeline(
        resolver=RepositorySourceResolver(
            InMemorySourceRepository(
                documents={
                    source_object_id: SourceDocument(
                        object_id=source_object_id,
                        version_id="v1",
                        title="Indexable source",
                        text=second_text,
                        classification=DataClass.INTERNAL,
                    )
                }
            ),
            created_at_clock=lambda: "2026-06-10T00:00:00Z",
        ),
        text_extractor=PlainTextExtractor(),
        chunker=FixedSizeTextChunker(max_characters=48),
        embedding_provider=embedder,
        worker=worker,
        embedding_model_id=model_id,
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:02:00Z",
    )
    second_result = second_pipeline.index_source(
        SourceIndexCommand(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            source_version_id="v1",
            audit_event_id="audit-second-index",
        )
    )

    candidates = store.search_by_embedding(tenant_id=tenant_id, embedding=embedder.embed(second_text), top_k=10)

    assert first_result.chunk_count == 3
    assert second_result.chunk_count == 1
    assert second_result.reindex_result.marked_reindex_pending == 3
    assert second_result.reindex_result.deleted_stale_chunks == 2
    assert {candidate.chunk_id for candidate in candidates} == {"chunk-0000"}
    assert candidates[0].metadata.classification == DataClass.INTERNAL

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        rows = owner_connection.execute(
            """
            SELECT chunk_id, lifecycle_state, audit_event_id
            FROM collabio.vector_embedding_chunks
            WHERE tenant_id = %s
              AND source_object_id = %s
              AND embedding_model_id = %s
            ORDER BY chunk_id
            """,
            (tenant_id, source_object_id, model_id),
        ).fetchall()

    rows_by_chunk = {str(row[0]): row for row in rows}
    assert rows_by_chunk["chunk-0000"][1] == VectorLifecycleState.ACTIVE.value
    assert rows_by_chunk["chunk-0000"][2] == "audit-second-index"
    assert rows_by_chunk["chunk-0001"][1] == VectorLifecycleState.DELETED.value
    assert rows_by_chunk["chunk-0002"][1] == VectorLifecycleState.DELETED.value
