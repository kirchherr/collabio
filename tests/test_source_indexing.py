from dataclasses import dataclass, field

import pytest

from suite.ai_control_plane.models import DataClass
from suite.rag.models import SourceDocument, VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.repositories import InMemorySourceRepository
from suite.rag.source_indexing import (
    DeterministicHashEmbeddingProvider,
    EmbeddingModelVersion,
    FixedSizeTextChunker,
    InMemoryEmbeddingModelVersionRegistry,
    PlainTextExtractor,
    RepositorySourceResolver,
    SourceIndexCommand,
    SourceIndexingPipeline,
)
from suite.rag.vector_worker import VectorIndexWorker


@dataclass
class CapturingVectorIndexStore:
    marked: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    upserted: list[VectorEmbeddingRecord] = field(default_factory=list)
    deleted_orphans: list[tuple[str, str, str, set[str], str | None]] = field(default_factory=list)

    def mark_source_for_reindex(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        audit_event_id: str | None = None,
    ) -> int:
        self.marked.append((tenant_id, source_object_id, source_version_id, audit_event_id))
        return 0

    def upsert_embedding(self, record: VectorEmbeddingRecord) -> None:
        self.upserted.append(record)

    def delete_reindex_orphans(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        keep_chunk_ids: set[str],
        audit_event_id: str | None = None,
    ) -> int:
        self.deleted_orphans.append((tenant_id, source_object_id, source_version_id, keep_chunk_ids, audit_event_id))
        return 0

    def transition_source_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> int:
        raise AssertionError("source indexing must not perform lifecycle deletion")


def pipeline_for(
    document: SourceDocument,
    store: CapturingVectorIndexStore,
    *,
    acl_version: int = 1,
    embedding_model_registry: InMemoryEmbeddingModelVersionRegistry | None = None,
) -> SourceIndexingPipeline:
    repository = InMemorySourceRepository(documents={document.object_id: document})
    return SourceIndexingPipeline(
        resolver=RepositorySourceResolver(
            repository,
            acl_version=acl_version,
            created_at_clock=lambda: "2026-06-10T00:00:00Z",
        ),
        text_extractor=PlainTextExtractor(),
        chunker=FixedSizeTextChunker(max_characters=32),
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=3),
        embedding_model_registry=embedding_model_registry
        or InMemoryEmbeddingModelVersionRegistry.approved_single_model(),
        worker=VectorIndexWorker(store),
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:01:00Z",
    )


def test_source_indexing_pipeline_builds_chunks_and_reindexes_source() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Alpha policy applies.\nBeta policy applies.\nGamma policy applies.",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(document, store)

    result = pipeline.index_source(
        SourceIndexCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            expected_acl_version=1,
            audit_event_id="audit-source-index",
        )
    )

    assert result.chunk_count == 2
    assert result.reindex_result.upserted_chunks == 2
    assert store.marked == [("tenant-1", "doc-1", "v1", "audit-source-index")]
    assert store.deleted_orphans == [("tenant-1", "doc-1", "v1", {"chunk-0000", "chunk-0001"}, "audit-source-index")]

    first = store.upserted[0]
    assert first.metadata.tenant_id == "tenant-1"
    assert first.metadata.source_object_id == "doc-1"
    assert first.metadata.source_version_id == "v1"
    assert first.metadata.chunk_id == "chunk-0000"
    assert first.metadata.classification == DataClass.INTERNAL
    assert first.metadata.retention_policy_id == "rp-standard"
    assert first.metadata.legal_hold_state == "none"
    assert first.metadata.acl_hash.startswith("sha256:")
    assert first.metadata.acl_version == 1
    assert first.metadata.embedding_model_id == "mock-embedding"
    assert first.metadata.embedding_model_version == "1"
    assert first.metadata.content_hash.startswith("sha256:")
    assert first.embedding_dimensions == 3
    assert len(first.embedding) == 3
    assert first.content_byte_length > 0
    assert first.indexed_at_utc == "2026-06-10T00:01:00Z"
    assert first.audit_event_id == "audit-source-index"


def test_source_indexing_rejects_version_mismatch_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(document, store)

    with pytest.raises(ValueError, match="version_id"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v2",
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_stale_expected_acl_version_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(document, store, acl_version=3)

    with pytest.raises(ValueError, match="acl_version"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                expected_acl_version=2,
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_unknown_embedding_model_version_at_construction() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )

    with pytest.raises(LookupError, match="Unknown embedding model version"):
        SourceIndexingPipeline(
            resolver=RepositorySourceResolver(InMemorySourceRepository(documents={"doc-1": document})),
            text_extractor=PlainTextExtractor(),
            chunker=FixedSizeTextChunker(max_characters=32),
            embedding_provider=DeterministicHashEmbeddingProvider(dimensions=3),
            embedding_model_registry=InMemoryEmbeddingModelVersionRegistry(model_versions=()),
            worker=VectorIndexWorker(store),
            embedding_model_id="mock-embedding",
            embedding_model_version="1",
            indexed_at_clock=lambda: "2026-06-10T00:01:00Z",
        )


def test_source_indexing_rejects_unapproved_embedding_model_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(
        document,
        store,
        embedding_model_registry=InMemoryEmbeddingModelVersionRegistry(
            model_versions=(
                EmbeddingModelVersion(
                    embedding_model_id="mock-embedding",
                    embedding_model_version="1",
                    provider="local-test",
                    deployment="deterministic-hash",
                    dimensions=3,
                    checksum="sha256:model",
                    approved_for_data_classes=frozenset({DataClass.INTERNAL}),
                    approved_at_utc=None,
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="not approved for indexing"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_retired_embedding_model_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(
        document,
        store,
        embedding_model_registry=InMemoryEmbeddingModelVersionRegistry(
            model_versions=(
                EmbeddingModelVersion(
                    embedding_model_id="mock-embedding",
                    embedding_model_version="1",
                    provider="local-test",
                    deployment="deterministic-hash",
                    dimensions=3,
                    checksum="sha256:model",
                    approved_for_data_classes=frozenset({DataClass.INTERNAL}),
                    approved_at_utc="2026-06-10T00:00:00Z",
                    retired_at_utc="2026-06-11T00:00:00Z",
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="retired"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_embedding_model_data_class_mismatch_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Confidential source",
        text="Source text",
        classification=DataClass.CONFIDENTIAL,
    )
    pipeline = pipeline_for(
        document,
        store,
        embedding_model_registry=InMemoryEmbeddingModelVersionRegistry.approved_single_model(
            approved_for_data_classes=frozenset({DataClass.INTERNAL})
        ),
    )

    with pytest.raises(ValueError, match="not approved for source data class"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_embedding_dimension_mismatch_before_writing() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Retention policy",
        text="Source text",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(
        document,
        store,
        embedding_model_registry=InMemoryEmbeddingModelVersionRegistry.approved_single_model(dimensions=4),
    )

    with pytest.raises(ValueError, match="dimensions"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
            )
        )

    assert store.upserted == []


def test_source_indexing_rejects_empty_extracted_text() -> None:
    store = CapturingVectorIndexStore()
    document = SourceDocument(
        object_id="doc-1",
        version_id="v1",
        title="Blank source",
        text="   \r\n\t  ",
        classification=DataClass.INTERNAL,
    )
    pipeline = pipeline_for(document, store)

    with pytest.raises(ValueError, match="empty after extraction"):
        pipeline.index_source(
            SourceIndexCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
            )
        )

    assert store.upserted == []


def test_deterministic_hash_embedding_provider_is_stable_and_dimensioned() -> None:
    provider = DeterministicHashEmbeddingProvider(dimensions=4)

    first = provider.embed("same text")
    second = provider.embed("same text")
    different = provider.embed("different text")

    assert first == second
    assert first != different
    assert len(first) == 4
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_fixed_size_chunker_validates_overlap() -> None:
    with pytest.raises(ValueError, match="overlap_characters"):
        FixedSizeTextChunker(max_characters=10, overlap_characters=10)
