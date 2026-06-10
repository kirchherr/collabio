from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from suite.ai_control_plane.models import DataClass
from suite.rag.models import ChunkMetadata, VectorCandidate, VectorEmbeddingRecord, VectorLifecycleState


def vector_literal(values: Sequence[float]) -> str:
    if not values:
        raise ValueError("embedding vector must not be empty")
    return "[" + ",".join(format(float(value), ".17g") for value in values) + "]"


def iso_utc(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value
        if normalized.tzinfo is not None:
            normalized = normalized.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
    return str(value)


class PgvectorVectorStore:
    def __init__(
        self,
        *,
        database_dsn: str,
        embedding_model_id: str,
        embedding_model_version: str,
        query_embedder: Callable[[str], Sequence[float]],
        lifecycle_database_dsn: str | None = None,
    ) -> None:
        self.database_dsn = database_dsn
        self.lifecycle_database_dsn = lifecycle_database_dsn or database_dsn
        self.embedding_model_id = embedding_model_id
        self.embedding_model_version = embedding_model_version
        self.query_embedder = query_embedder

    def search(self, *, tenant_id: str, query: str, top_k: int) -> list[VectorCandidate]:
        return self.search_by_embedding(
            tenant_id=tenant_id,
            embedding=self.query_embedder(query),
            top_k=top_k,
        )

    def search_by_embedding(
        self,
        *,
        tenant_id: str,
        embedding: Sequence[float],
        top_k: int,
    ) -> list[VectorCandidate]:
        query_vector = vector_literal(embedding)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT
                    chunk_id,
                    1 - (embedding <=> %s::vector) AS score,
                    tenant_id,
                    source_object_id,
                    source_object_type,
                    source_version_id,
                    classification,
                    retention_policy_id,
                    legal_hold_state,
                    acl_hash,
                    acl_version,
                    created_at_utc,
                    embedding_model_id,
                    embedding_model_version,
                    content_hash
                FROM collabio.vector_embedding_chunks
                WHERE tenant_id = %s
                  AND lifecycle_state = 'active'
                  AND embedding_model_id = %s
                  AND embedding_model_version = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    query_vector,
                    tenant_id,
                    self.embedding_model_id,
                    self.embedding_model_version,
                    query_vector,
                    top_k,
                ),
            ).fetchall()

        return [
            VectorCandidate(
                chunk_id=str(row[0]),
                score=float(row[1]),
                metadata=ChunkMetadata(
                    tenant_id=str(row[2]),
                    source_object_id=str(row[3]),
                    source_object_type=str(row[4]),
                    source_version_id=str(row[5]),
                    chunk_id=str(row[0]),
                    classification=DataClass(str(row[6])),
                    retention_policy_id=str(row[7]),
                    legal_hold_state=str(row[8]),
                    acl_hash=str(row[9]),
                    acl_version=int(row[10]),
                    created_at_utc=iso_utc(row[11]),
                    embedding_model_id=str(row[12]),
                    embedding_model_version=str(row[13]),
                    content_hash=str(row[14]),
                ),
            )
            for row in rows
        ]

    def upsert_embedding(self, record: VectorEmbeddingRecord) -> None:
        if record.metadata.embedding_model_id != self.embedding_model_id:
            raise ValueError("record embedding_model_id does not match this pgvector store")
        if record.metadata.embedding_model_version != self.embedding_model_version:
            raise ValueError("record embedding_model_version does not match this pgvector store")

        metadata = record.metadata
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, metadata.tenant_id)
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
                    expires_at_utc,
                    audit_event_id,
                    created_at_utc
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::vector, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (
                    tenant_id,
                    source_object_id,
                    source_version_id,
                    chunk_id,
                    embedding_model_id,
                    embedding_model_version
                )
                DO UPDATE SET
                    source_object_type = EXCLUDED.source_object_type,
                    classification = EXCLUDED.classification,
                    retention_policy_id = EXCLUDED.retention_policy_id,
                    legal_hold_state = EXCLUDED.legal_hold_state,
                    acl_hash = EXCLUDED.acl_hash,
                    acl_version = EXCLUDED.acl_version,
                    embedding_dimensions = EXCLUDED.embedding_dimensions,
                    embedding = EXCLUDED.embedding,
                    content_hash = EXCLUDED.content_hash,
                    content_byte_length = EXCLUDED.content_byte_length,
                    lifecycle_state = EXCLUDED.lifecycle_state,
                    indexed_at_utc = EXCLUDED.indexed_at_utc,
                    expires_at_utc = EXCLUDED.expires_at_utc,
                    audit_event_id = EXCLUDED.audit_event_id,
                    last_reindexed_at_utc = now()
                """,
                (
                    metadata.tenant_id,
                    metadata.source_object_id,
                    metadata.source_object_type,
                    metadata.source_version_id,
                    metadata.chunk_id,
                    metadata.classification.value,
                    metadata.retention_policy_id,
                    metadata.legal_hold_state,
                    metadata.acl_hash,
                    metadata.acl_version,
                    metadata.embedding_model_id,
                    metadata.embedding_model_version,
                    record.embedding_dimensions,
                    vector_literal(record.embedding),
                    metadata.content_hash,
                    record.content_byte_length,
                    record.lifecycle_state.value,
                    record.indexed_at_utc,
                    record.expires_at_utc,
                    record.audit_event_id,
                    metadata.created_at_utc,
                ),
            )
            connection.commit()

    def transition_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        chunk_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> bool:
        set_clauses = [
            "lifecycle_state = %s::collabio.vector_lifecycle_state",
            "audit_event_id = COALESCE(%s, audit_event_id)",
        ]
        parameters: list[Any] = [lifecycle_state.value, audit_event_id]

        if lifecycle_state == VectorLifecycleState.RESTRICTED:
            set_clauses.append("restricted_at_utc = COALESCE(restricted_at_utc, now())")
        elif lifecycle_state == VectorLifecycleState.DELETED:
            set_clauses.extend(
                [
                    "deletion_requested_at_utc = COALESCE(deletion_requested_at_utc, now())",
                    "deleted_at_utc = COALESCE(deleted_at_utc, now())",
                ]
            )
        elif lifecycle_state == VectorLifecycleState.CRYPTOSHREDDED:
            set_clauses.extend(
                [
                    "deletion_requested_at_utc = COALESCE(deletion_requested_at_utc, now())",
                    "deleted_at_utc = COALESCE(deleted_at_utc, now())",
                    "cryptoshredded_at_utc = COALESCE(cryptoshredded_at_utc, now())",
                ]
            )
        elif lifecycle_state == VectorLifecycleState.ACTIVE:
            set_clauses.append("last_reindexed_at_utc = now()")

        with psycopg.connect(self.lifecycle_database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            cursor = connection.execute(
                f"""
                UPDATE collabio.vector_embedding_chunks
                SET {", ".join(set_clauses)}
                WHERE tenant_id = %s
                  AND source_object_id = %s
                  AND source_version_id = %s
                  AND chunk_id = %s
                  AND embedding_model_id = %s
                  AND embedding_model_version = %s
                """,
                (
                    *parameters,
                    tenant_id,
                    source_object_id,
                    source_version_id,
                    chunk_id,
                    self.embedding_model_id,
                    self.embedding_model_version,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
