from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from suite.ai_control_plane.models import DataClass
from suite.rag.models import ChunkMetadata, VectorEmbeddingRecord
from suite.rag.source_indexing import DeterministicHashEmbeddingProvider, sha256_text


@dataclass(frozen=True)
class ExactSearchBenchmarkQuery:
    query_id: str
    tenant_id: str
    embedding: tuple[float, ...]
    expected_chunk_id: str


@dataclass(frozen=True)
class ExactSearchRankedChunk:
    chunk_id: str
    score: float


@dataclass(frozen=True)
class ExactSearchBenchmarkFixture:
    tenant_id: str
    embedding_model_id: str
    embedding_model_version: str
    dimensions: int
    records: tuple[VectorEmbeddingRecord, ...]
    queries: tuple[ExactSearchBenchmarkQuery, ...]


def build_exact_search_benchmark_fixture(
    *,
    tenant_id: str,
    embedding_model_id: str,
    embedding_model_version: str = "1",
    record_count: int = 32,
    query_count: int = 8,
    dimensions: int = 3,
) -> ExactSearchBenchmarkFixture:
    if record_count < 1:
        raise ValueError("record_count must be greater than or equal to 1")
    if query_count < 1:
        raise ValueError("query_count must be greater than or equal to 1")
    if query_count > record_count:
        raise ValueError("query_count must be less than or equal to record_count")
    if dimensions < 1:
        raise ValueError("dimensions must be greater than or equal to 1")

    embedder = DeterministicHashEmbeddingProvider(dimensions=dimensions)
    records: list[VectorEmbeddingRecord] = []
    for index in range(record_count):
        source_object_id = f"benchmark-doc-{index:04d}"
        chunk_id = f"benchmark-chunk-{index:04d}"
        seed_text = f"{tenant_id}:{embedding_model_id}:{embedding_model_version}:{index}"
        records.append(
            VectorEmbeddingRecord(
                metadata=ChunkMetadata(
                    tenant_id=tenant_id,
                    source_object_id=source_object_id,
                    source_object_type="document",
                    source_version_id="v1",
                    chunk_id=chunk_id,
                    classification=DataClass.INTERNAL,
                    retention_policy_id="rp-benchmark",
                    legal_hold_state="none",
                    acl_hash=sha256_text(f"{tenant_id}:{source_object_id}:acl"),
                    acl_version=1,
                    created_at_utc="2026-06-10T00:00:00Z",
                    embedding_model_id=embedding_model_id,
                    embedding_model_version=embedding_model_version,
                    content_hash=sha256_text(seed_text),
                ),
                embedding=embedder.embed(seed_text),
                embedding_dimensions=dimensions,
                content_byte_length=len(seed_text.encode("utf-8")),
                indexed_at_utc="2026-06-10T00:00:00Z",
                audit_event_id="benchmark-fixture",
            )
        )

    queries = tuple(
        ExactSearchBenchmarkQuery(
            query_id=f"benchmark-query-{index:04d}",
            tenant_id=tenant_id,
            embedding=tuple(records[index].embedding),
            expected_chunk_id=records[index].metadata.chunk_id,
        )
        for index in range(query_count)
    )
    fixture = ExactSearchBenchmarkFixture(
        tenant_id=tenant_id,
        embedding_model_id=embedding_model_id,
        embedding_model_version=embedding_model_version,
        dimensions=dimensions,
        records=tuple(records),
        queries=queries,
    )
    assert_exact_search_fixture_consistency(fixture)
    return fixture


def assert_exact_search_fixture_consistency(fixture: ExactSearchBenchmarkFixture) -> None:
    if not fixture.records:
        raise ValueError("benchmark fixture must contain records")
    if not fixture.queries:
        raise ValueError("benchmark fixture must contain queries")

    chunk_ids: set[str] = set()
    for record in fixture.records:
        if record.metadata.tenant_id != fixture.tenant_id:
            raise ValueError("record tenant_id must match fixture tenant_id")
        if record.metadata.embedding_model_id != fixture.embedding_model_id:
            raise ValueError("record embedding_model_id must match fixture embedding_model_id")
        if record.metadata.embedding_model_version != fixture.embedding_model_version:
            raise ValueError("record embedding_model_version must match fixture embedding_model_version")
        if record.embedding_dimensions != fixture.dimensions:
            raise ValueError("record embedding_dimensions must match fixture dimensions")
        if len(record.embedding) != fixture.dimensions:
            raise ValueError("record embedding length must match fixture dimensions")
        if record.metadata.chunk_id in chunk_ids:
            raise ValueError("benchmark fixture contains duplicate chunk ids")
        chunk_ids.add(record.metadata.chunk_id)

    for query in fixture.queries:
        if query.tenant_id != fixture.tenant_id:
            raise ValueError("query tenant_id must match fixture tenant_id")
        if len(query.embedding) != fixture.dimensions:
            raise ValueError("query embedding length must match fixture dimensions")
        if query.expected_chunk_id not in chunk_ids:
            raise ValueError("query expected_chunk_id must reference a fixture record")
        top_chunk = rank_exact_vectors(fixture.records, query.embedding, top_k=1)[0]
        if top_chunk.chunk_id != query.expected_chunk_id:
            raise ValueError("query expected_chunk_id must be the exact-search top result")


def rank_exact_vectors(
    records: Sequence[VectorEmbeddingRecord],
    query_embedding: Sequence[float],
    *,
    top_k: int,
) -> tuple[ExactSearchRankedChunk, ...]:
    if top_k < 1:
        raise ValueError("top_k must be greater than or equal to 1")
    if not records:
        return ()

    ranked = [
        ExactSearchRankedChunk(
            chunk_id=record.metadata.chunk_id,
            score=cosine_similarity(record.embedding, query_embedding),
        )
        for record in records
    ]
    return tuple(sorted(ranked, key=lambda candidate: candidate.score, reverse=True)[:top_k])


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    left_magnitude = sqrt(sum(value * value for value in left))
    right_magnitude = sqrt(sum(value * value for value in right))
    if left_magnitude == 0 or right_magnitude == 0:
        raise ValueError("vectors must not be zero vectors")
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    return dot_product / (left_magnitude * right_magnitude)
