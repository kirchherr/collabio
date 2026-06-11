import pytest

from suite.rag.vector_benchmarks import (
    ExactSearchBenchmarkFixture,
    VectorBenchmarkDecision,
    VectorBenchmarkIndexProfile,
    VectorBenchmarkObservation,
    VectorBenchmarkThresholds,
    assert_exact_search_fixture_consistency,
    build_exact_search_benchmark_fixture,
    build_vector_benchmark_report,
    build_vector_benchmark_report_hash,
    cosine_similarity,
    percentile,
    rank_exact_vectors,
)


def test_exact_search_benchmark_fixture_is_deterministic_and_self_validating() -> None:
    first = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )
    second = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )

    assert_exact_search_fixture_consistency(first)
    assert [record.embedding for record in first.records] == [record.embedding for record in second.records]
    assert [query.expected_chunk_id for query in first.queries] == [
        "benchmark-chunk-0000",
        "benchmark-chunk-0001",
        "benchmark-chunk-0002",
    ]

    for query in first.queries:
        ranked = rank_exact_vectors(first.records, query.embedding, top_k=1)
        assert ranked[0].chunk_id == query.expected_chunk_id
        assert ranked[0].score == pytest.approx(1.0)


def test_exact_search_benchmark_fixture_validates_shape() -> None:
    with pytest.raises(ValueError, match="query_count"):
        build_exact_search_benchmark_fixture(
            tenant_id="tenant-benchmark",
            embedding_model_id="benchmark-embedding",
            record_count=2,
            query_count=3,
            dimensions=4,
        )

    with pytest.raises(ValueError, match="dimensions"):
        cosine_similarity([1.0, 0.0], [1.0])


def test_vector_benchmark_report_records_exact_baseline_without_ann_approval() -> None:
    fixture = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )
    thresholds = VectorBenchmarkThresholds(
        min_record_count=6,
        min_query_count=3,
        max_p95_latency_ms=50.0,
        max_p99_latency_ms=60.0,
        top_k=2,
    )

    report = build_vector_benchmark_report(
        fixture=fixture,
        observations=_benchmark_observations(fixture, latencies=(10.0, 20.0, 30.0)),
        thresholds=thresholds,
        benchmark_id="benchmark:exact-baseline",
        measured_at_utc="2026-06-11T00:00:00Z",
    )

    assert report.passed is True
    assert report.decision == VectorBenchmarkDecision.EXACT_BASELINE_ONLY
    assert report.index_profile == VectorBenchmarkIndexProfile.EXACT_PGVECTOR
    assert report.recall_at_1 == pytest.approx(1.0)
    assert report.recall_at_k == pytest.approx(1.0)
    assert report.p95_latency_ms == pytest.approx(30.0)
    assert report.p99_latency_ms == pytest.approx(30.0)
    assert report.failed_checks == ()
    assert report.observations_hash.startswith("sha256:")
    assert report.report_hash == build_vector_benchmark_report_hash(report)


def test_vector_benchmark_report_allows_ann_candidate_only_when_thresholds_pass() -> None:
    fixture = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )
    thresholds = VectorBenchmarkThresholds(
        min_record_count=6,
        min_query_count=3,
        max_p95_latency_ms=50.0,
        max_p99_latency_ms=60.0,
        top_k=2,
    )

    report = build_vector_benchmark_report(
        fixture=fixture,
        observations=_benchmark_observations(fixture, latencies=(10.0, 20.0, 30.0)),
        thresholds=thresholds,
        benchmark_id="benchmark:hnsw-candidate",
        index_profile=VectorBenchmarkIndexProfile.HNSW_CANDIDATE,
        measured_at_utc="2026-06-11T00:00:00Z",
    )

    assert report.passed is True
    assert report.decision == VectorBenchmarkDecision.ANN_CANDIDATE_PASSED


def test_vector_benchmark_report_rejects_ann_candidate_on_recall_or_latency_failure() -> None:
    fixture = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )
    thresholds = VectorBenchmarkThresholds(
        min_record_count=6,
        min_query_count=3,
        max_p95_latency_ms=50.0,
        max_p99_latency_ms=60.0,
        top_k=2,
    )

    report = build_vector_benchmark_report(
        fixture=fixture,
        observations=_benchmark_observations(fixture, latencies=(10.0, 20.0, 90.0), miss_first=True),
        thresholds=thresholds,
        benchmark_id="benchmark:ivfflat-candidate",
        index_profile=VectorBenchmarkIndexProfile.IVFFLAT_CANDIDATE,
        measured_at_utc="2026-06-11T00:00:00Z",
    )

    assert report.passed is False
    assert report.decision == VectorBenchmarkDecision.ANN_CANDIDATE_REJECTED
    assert report.recall_at_1 == pytest.approx(2 / 3)
    assert report.recall_at_k == pytest.approx(1.0)
    assert report.failed_checks == ("recall_at_1", "p95_latency_ms", "p99_latency_ms")


def test_vector_benchmark_report_requires_complete_observations() -> None:
    fixture = build_exact_search_benchmark_fixture(
        tenant_id="tenant-benchmark",
        embedding_model_id="benchmark-embedding",
        record_count=6,
        query_count=3,
        dimensions=4,
    )
    thresholds = VectorBenchmarkThresholds(
        min_record_count=6,
        min_query_count=3,
        top_k=2,
    )
    observations = _benchmark_observations(fixture, latencies=(10.0, 20.0, 30.0))

    with pytest.raises(ValueError, match="missing observations"):
        build_vector_benchmark_report(
            fixture=fixture,
            observations=observations[:-1],
            thresholds=thresholds,
            benchmark_id="benchmark:missing",
            measured_at_utc="2026-06-11T00:00:00Z",
        )

    with pytest.raises(ValueError, match="duplicate observations"):
        build_vector_benchmark_report(
            fixture=fixture,
            observations=(*observations, observations[0]),
            thresholds=thresholds,
            benchmark_id="benchmark:duplicate",
            measured_at_utc="2026-06-11T00:00:00Z",
        )

    with pytest.raises(ValueError, match="unknown observations"):
        build_vector_benchmark_report(
            fixture=fixture,
            observations=(
                *observations[:-1],
                VectorBenchmarkObservation(
                    query_id="benchmark-query-unknown",
                    returned_chunk_ids=("benchmark-chunk-0000",),
                    latency_ms=10.0,
                ),
            ),
            thresholds=thresholds,
            benchmark_id="benchmark:unknown",
            measured_at_utc="2026-06-11T00:00:00Z",
        )


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.95) == pytest.approx(40.0)
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.50) == pytest.approx(20.0)

    with pytest.raises(ValueError, match="at least one value"):
        percentile([], 0.95)


def _benchmark_observations(
    fixture: ExactSearchBenchmarkFixture,
    *,
    latencies: tuple[float, ...],
    miss_first: bool = False,
) -> tuple[VectorBenchmarkObservation, ...]:
    observations: list[VectorBenchmarkObservation] = []
    for index, query in enumerate(fixture.queries):
        returned_chunk_ids = (query.expected_chunk_id, "benchmark-fallback")
        if miss_first and index == 0:
            returned_chunk_ids = ("benchmark-fallback", query.expected_chunk_id)
        observations.append(
            VectorBenchmarkObservation(
                query_id=query.query_id,
                returned_chunk_ids=returned_chunk_ids,
                latency_ms=latencies[index],
            )
        )
    return tuple(observations)
