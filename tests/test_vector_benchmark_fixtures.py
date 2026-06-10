import pytest

from suite.rag.vector_benchmarks import (
    assert_exact_search_fixture_consistency,
    build_exact_search_benchmark_fixture,
    cosine_similarity,
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
