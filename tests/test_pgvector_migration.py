import re

import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migration_catalog import get_migration, load_migrations
from suite.rag.models import ChunkMetadata, VectorEmbeddingRecord, VectorLifecycleState


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower())


def table_body(sql: str, table_name: str) -> str:
    pattern = rf"create table if not exists {re.escape(table_name)}\s*\((.*?)\);"
    match = re.search(pattern, sql, flags=re.IGNORECASE | re.DOTALL)
    assert match is not None, f"{table_name} table definition not found"
    return match.group(1).lower()


def pgvector_sql() -> str:
    return get_migration("0001").sql()


def test_migration_catalog_is_ordered_and_loads_pgvector_schema() -> None:
    migrations = load_migrations()

    assert [migration.version for migration in migrations] == sorted(migration.version for migration in migrations)
    assert migrations[0].version == "0001"
    assert migrations[0].name == "pgvector_embeddings"
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in migrations[0].sql()


def test_pgvector_embedding_schema_declares_required_compliance_metadata() -> None:
    body = table_body(pgvector_sql(), "collabio.vector_embedding_chunks")

    for column in [
        "tenant_id",
        "source_object_id",
        "source_object_type",
        "source_version_id",
        "chunk_id",
        "classification",
        "retention_policy_id",
        "legal_hold_state",
        "acl_hash",
        "acl_version",
        "embedding_model_id",
        "embedding_model_version",
        "embedding_dimensions",
        "embedding",
        "content_hash",
        "content_byte_length",
        "lifecycle_state",
        "audit_event_id",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from vector embedding schema"

    for data_class in DataClass:
        assert f"'{data_class.value}'" in body


def test_pgvector_embedding_schema_enforces_lifecycle_and_dimension_guardrails() -> None:
    sql = normalized(pgvector_sql())

    for state in VectorLifecycleState:
        assert f"'{state.value}'" in sql

    assert "check (embedding_dimensions = vector_dims(embedding))" in sql
    assert "lifecycle_state <> 'restricted' or restricted_at_utc is not null" in sql
    assert "lifecycle_state <> 'deleted' or deleted_at_utc is not null" in sql
    assert "lifecycle_state <> 'cryptoshredded' or cryptoshredded_at_utc is not null" in sql
    assert "source text must be fetched only after authoritative acl validation" in sql


def test_pgvector_embedding_schema_enables_rls_with_null_safe_tenant_setting() -> None:
    sql = normalized(pgvector_sql())

    assert "nullif(current_setting('app.tenant_id', true), '')" in sql
    assert "alter table collabio.vector_embedding_chunks enable row level security" in sql
    assert "alter table collabio.vector_embedding_chunks force row level security" in sql
    assert "for select" in sql
    assert "for insert" in sql
    assert "for update" in sql
    assert "for delete" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "lifecycle_state = 'active'" in sql
    assert "create policy vector_embedding_chunks_no_hard_delete" in sql
    assert "using (false)" in sql
    assert "grant select, insert, update, delete on table collabio.vector_embedding_chunks to collabio_app" in sql


def test_pgvector_embedding_schema_does_not_store_source_text_or_generated_answers() -> None:
    body = table_body(pgvector_sql(), "collabio.vector_embedding_chunks")

    forbidden_columns = ["source_text", "chunk_text", "document_text", "prompt_text", "answer_text", "output_text"]
    for column in forbidden_columns:
        assert re.search(rf"\b{column}\b", body) is None


def test_vector_embedding_record_requires_declared_dimensions_to_match_embedding() -> None:
    metadata = ChunkMetadata(
        tenant_id="tenant-1",
        source_object_id="doc-1",
        source_object_type="document",
        source_version_id="v1",
        chunk_id="chunk-1",
        classification=DataClass.EMBEDDING,
        retention_policy_id="rp-standard",
        legal_hold_state="none",
        acl_hash="sha256:acl",
        acl_version=1,
        created_at_utc="2026-06-10T00:00:00Z",
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        content_hash="sha256:content",
    )

    record = VectorEmbeddingRecord(
        metadata=metadata,
        embedding=[0.1, 0.2, 0.3],
        embedding_dimensions=3,
        content_byte_length=42,
        indexed_at_utc="2026-06-10T00:01:00Z",
    )

    assert record.lifecycle_state == VectorLifecycleState.ACTIVE

    with pytest.raises(ValueError, match="embedding_dimensions"):
        VectorEmbeddingRecord(
            metadata=metadata,
            embedding=[0.1, 0.2, 0.3],
            embedding_dimensions=2,
            content_byte_length=42,
            indexed_at_utc="2026-06-10T00:01:00Z",
        )
