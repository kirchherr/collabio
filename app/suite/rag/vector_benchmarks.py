from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import ceil, sqrt
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.rag.models import ChunkMetadata, VectorEmbeddingRecord
from suite.rag.source_indexing import DeterministicHashEmbeddingProvider, sha256_text
from suite.storage.content_hash import compute_content_hash

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


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


class VectorBenchmarkIndexProfile(StrEnum):
    EXACT_PGVECTOR = "exact_pgvector"
    HNSW_CANDIDATE = "hnsw_candidate"
    IVFFLAT_CANDIDATE = "ivfflat_candidate"


class VectorBenchmarkDecision(StrEnum):
    EXACT_BASELINE_ONLY = "exact_baseline_only"
    ANN_CANDIDATE_PASSED = "ann_candidate_passed"
    ANN_CANDIDATE_REJECTED = "ann_candidate_rejected"


class VectorBenchmarkThresholds(BaseModel):
    schema_version: str = "vector_benchmark_thresholds.v1"
    min_record_count: int = Field(default=32, ge=1)
    min_query_count: int = Field(default=8, ge=1)
    min_recall_at_1: float = Field(default=1.0, ge=0.0, le=1.0)
    min_recall_at_k: float = Field(default=1.0, ge=0.0, le=1.0)
    max_p95_latency_ms: float = Field(default=250.0, gt=0.0)
    max_p99_latency_ms: float = Field(default=500.0, gt=0.0)
    top_k: int = Field(default=3, ge=1)


class VectorBenchmarkObservation(BaseModel):
    query_id: str
    returned_chunk_ids: tuple[str, ...] = Field(min_length=1)
    latency_ms: float = Field(ge=0.0)

    @field_validator("query_id")
    @classmethod
    def require_query_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query_id must not be empty")
        return normalized


class VectorBenchmarkReport(BaseModel):
    schema_version: str = "vector_benchmark_report.v1"
    benchmark_id: str
    index_profile: VectorBenchmarkIndexProfile
    decision: VectorBenchmarkDecision
    passed: bool
    tenant_id: str
    embedding_model_id: str
    embedding_model_version: str
    dimensions: int = Field(ge=1)
    record_count: int = Field(ge=1)
    query_count: int = Field(ge=1)
    top_k: int = Field(ge=1)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    p95_latency_ms: float = Field(ge=0.0)
    p99_latency_ms: float = Field(ge=0.0)
    max_latency_ms: float = Field(ge=0.0)
    thresholds: VectorBenchmarkThresholds
    failed_checks: tuple[str, ...]
    observations_hash: str
    measured_at_utc: str
    report_hash: str

    @field_validator("benchmark_id", "tenant_id", "embedding_model_id", "embedding_model_version")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("observations_hash", "report_hash")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("measured_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)

    @model_validator(mode="after")
    def require_consistent_decision(self) -> Self:
        if self.index_profile == VectorBenchmarkIndexProfile.EXACT_PGVECTOR:
            if self.decision != VectorBenchmarkDecision.EXACT_BASELINE_ONLY:
                raise ValueError("exact pgvector benchmarks can only record an exact baseline decision")
        elif self.passed and self.decision != VectorBenchmarkDecision.ANN_CANDIDATE_PASSED:
            raise ValueError("passing ANN candidate benchmarks must use ann_candidate_passed")
        elif not self.passed and self.decision != VectorBenchmarkDecision.ANN_CANDIDATE_REJECTED:
            raise ValueError("failing ANN candidate benchmarks must use ann_candidate_rejected")
        return self


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


def build_vector_benchmark_report(
    *,
    fixture: ExactSearchBenchmarkFixture,
    observations: Sequence[VectorBenchmarkObservation],
    thresholds: VectorBenchmarkThresholds,
    benchmark_id: str,
    index_profile: VectorBenchmarkIndexProfile = VectorBenchmarkIndexProfile.EXACT_PGVECTOR,
    measured_at_utc: str,
) -> VectorBenchmarkReport:
    assert_exact_search_fixture_consistency(fixture)
    observation_by_query = _observations_by_query(fixture=fixture, observations=observations)
    recall_at_1_hits = 0
    recall_at_k_hits = 0
    latencies = []
    for query in fixture.queries:
        observation = observation_by_query[query.query_id]
        returned = observation.returned_chunk_ids[: thresholds.top_k]
        if returned[0] == query.expected_chunk_id:
            recall_at_1_hits += 1
        if query.expected_chunk_id in returned:
            recall_at_k_hits += 1
        latencies.append(observation.latency_ms)

    query_count = len(fixture.queries)
    recall_at_1 = recall_at_1_hits / query_count
    recall_at_k = recall_at_k_hits / query_count
    p95_latency_ms = percentile(latencies, 0.95)
    p99_latency_ms = percentile(latencies, 0.99)
    max_latency_ms = max(latencies)
    failed_checks = tuple(
        check
        for check, passed in {
            "min_record_count": len(fixture.records) >= thresholds.min_record_count,
            "min_query_count": query_count >= thresholds.min_query_count,
            "recall_at_1": recall_at_1 >= thresholds.min_recall_at_1,
            "recall_at_k": recall_at_k >= thresholds.min_recall_at_k,
            "p95_latency_ms": p95_latency_ms <= thresholds.max_p95_latency_ms,
            "p99_latency_ms": p99_latency_ms <= thresholds.max_p99_latency_ms,
        }.items()
        if not passed
    )
    passed = not failed_checks
    decision = _benchmark_decision(index_profile=index_profile, passed=passed)
    draft = VectorBenchmarkReport(
        benchmark_id=benchmark_id,
        index_profile=index_profile,
        decision=decision,
        passed=passed,
        tenant_id=fixture.tenant_id,
        embedding_model_id=fixture.embedding_model_id,
        embedding_model_version=fixture.embedding_model_version,
        dimensions=fixture.dimensions,
        record_count=len(fixture.records),
        query_count=query_count,
        top_k=thresholds.top_k,
        recall_at_1=recall_at_1,
        recall_at_k=recall_at_k,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        max_latency_ms=max_latency_ms,
        thresholds=thresholds,
        failed_checks=failed_checks,
        observations_hash=build_vector_benchmark_observations_hash(observations),
        measured_at_utc=measured_at_utc,
        report_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    return draft.model_copy(update={"report_hash": build_vector_benchmark_report_hash(draft)})


def vector_benchmark_report_payload(report: VectorBenchmarkReport) -> dict[str, object]:
    return report.model_dump(mode="json", exclude={"report_hash"})


def build_vector_benchmark_report_hash(report: VectorBenchmarkReport) -> str:
    report_bytes = json.dumps(
        vector_benchmark_report_payload(report),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(report_bytes)


def build_vector_benchmark_observations_hash(observations: Sequence[VectorBenchmarkObservation]) -> str:
    payload = [
        observation.model_dump(mode="json") for observation in sorted(observations, key=lambda item: item.query_id)
    ]
    observations_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return compute_content_hash(observations_bytes)


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if quantile <= 0 or quantile > 1:
        raise ValueError("quantile must be greater than 0 and less than or equal to 1")
    ordered = sorted(values)
    index = ceil(quantile * len(ordered)) - 1
    return ordered[max(index, 0)]


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


def _observations_by_query(
    *,
    fixture: ExactSearchBenchmarkFixture,
    observations: Sequence[VectorBenchmarkObservation],
) -> dict[str, VectorBenchmarkObservation]:
    expected_query_ids = {query.query_id for query in fixture.queries}
    seen_query_ids: set[str] = set()
    duplicates: set[str] = set()
    unknown: set[str] = set()
    by_query: dict[str, VectorBenchmarkObservation] = {}
    for observation in observations:
        if observation.query_id in seen_query_ids:
            duplicates.add(observation.query_id)
        if observation.query_id not in expected_query_ids:
            unknown.add(observation.query_id)
        by_query[observation.query_id] = observation
        seen_query_ids.add(observation.query_id)

    missing = expected_query_ids - seen_query_ids
    errors = []
    if duplicates:
        errors.append(f"duplicate observations: {', '.join(sorted(duplicates))}")
    if unknown:
        errors.append(f"unknown observations: {', '.join(sorted(unknown))}")
    if missing:
        errors.append(f"missing observations: {', '.join(sorted(missing))}")
    if errors:
        raise ValueError("; ".join(errors))
    return by_query


def _benchmark_decision(
    *,
    index_profile: VectorBenchmarkIndexProfile,
    passed: bool,
) -> VectorBenchmarkDecision:
    if index_profile == VectorBenchmarkIndexProfile.EXACT_PGVECTOR:
        return VectorBenchmarkDecision.EXACT_BASELINE_ONLY
    if passed:
        return VectorBenchmarkDecision.ANN_CANDIDATE_PASSED
    return VectorBenchmarkDecision.ANN_CANDIDATE_REJECTED


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized
