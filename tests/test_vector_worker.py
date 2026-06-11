from dataclasses import dataclass, field
from pathlib import Path

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger, JsonlAuditLogger
from suite.ai_control_plane.models import DataClass
from suite.rag.models import ChunkMetadata, VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.vector_worker import (
    AuditLoggerVectorWorkerAuditSink,
    DeletionPropagationCommand,
    ReindexSourceCommand,
    VectorIndexWorker,
    build_durable_vector_worker_audit_sink,
)


def record(
    *,
    tenant_id: str = "tenant-1",
    source_object_id: str = "doc-1",
    source_version_id: str = "v1",
    chunk_id: str = "chunk-1",
    lifecycle_state: VectorLifecycleState = VectorLifecycleState.ACTIVE,
    acl_hash: str = "sha256:acl",
    acl_version: int = 1,
) -> VectorEmbeddingRecord:
    return VectorEmbeddingRecord(
        metadata=ChunkMetadata(
            tenant_id=tenant_id,
            source_object_id=source_object_id,
            source_object_type="document",
            source_version_id=source_version_id,
            chunk_id=chunk_id,
            classification=DataClass.EMBEDDING,
            retention_policy_id="rp-standard",
            legal_hold_state="none",
            acl_hash=acl_hash,
            acl_version=acl_version,
            created_at_utc="2026-06-10T00:00:00Z",
            embedding_model_id="mock-embedding",
            embedding_model_version="1",
            content_hash=f"sha256:{chunk_id}",
        ),
        embedding=[1.0, 0.0, 0.0],
        embedding_dimensions=3,
        content_byte_length=42,
        lifecycle_state=lifecycle_state,
        indexed_at_utc="2026-06-10T00:01:00Z",
    )


@dataclass
class FakeVectorIndexStore:
    marked: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    upserted: list[VectorEmbeddingRecord] = field(default_factory=list)
    deleted_orphans: list[tuple[str, str, str, set[str], str | None]] = field(default_factory=list)
    propagated: list[tuple[str, str, str, VectorLifecycleState, str | None]] = field(default_factory=list)

    def mark_source_for_reindex(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        audit_event_id: str | None = None,
    ) -> int:
        self.marked.append((tenant_id, source_object_id, source_version_id, audit_event_id))
        return 2

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
        return 1

    def transition_source_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> int:
        self.propagated.append((tenant_id, source_object_id, source_version_id, lifecycle_state, audit_event_id))
        return 3


def test_reindex_source_marks_upserts_and_deletes_orphans() -> None:
    store = FakeVectorIndexStore()
    worker = VectorIndexWorker(store)
    first = record(chunk_id="chunk-1")
    second = record(chunk_id="chunk-2")

    result = worker.reindex_source(
        ReindexSourceCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            chunks=(first, second),
            audit_event_id="audit-reindex",
        )
    )

    assert result.marked_reindex_pending == 2
    assert result.upserted_chunks == 2
    assert result.deleted_stale_chunks == 1
    assert store.marked == [("tenant-1", "doc-1", "v1", "audit-reindex")]
    assert store.upserted == [first, second]
    assert store.deleted_orphans == [("tenant-1", "doc-1", "v1", {"chunk-1", "chunk-2"}, "audit-reindex")]


def test_reindex_source_emits_hash_chained_audit_events_without_raw_embeddings() -> None:
    store = FakeVectorIndexStore()
    audit_logger = InMemoryAuditLogger()
    worker = VectorIndexWorker(
        store,
        audit_sink=AuditLoggerVectorWorkerAuditSink(audit_logger),
    )

    worker.reindex_source(
        ReindexSourceCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            chunks=(record(chunk_id="chunk-1"), record(chunk_id="chunk-2")),
            audit_event_id="audit-upstream",
        )
    )

    assert audit_logger.verify().ok
    assert [event.event_type for event in audit_logger.events] == [
        "vector.reindex.started",
        "vector.reindex.completed",
    ]
    assert audit_logger.events[0].tenant_id == "tenant-1"
    assert audit_logger.events[0].user_id == "vector-index-worker"
    assert audit_logger.events[0].source_object_ids == ["doc-1"]
    assert audit_logger.events[0].input_hash is None
    assert audit_logger.events[0].output_hash is None
    assert audit_logger.events[0].metadata == {
        "source_version_id": "v1",
        "requested_chunk_count": 2,
        "requested_audit_event_id": "audit-upstream",
        "embedding_models": [
            {
                "embedding_model_id": "mock-embedding",
                "embedding_model_version": "1",
            }
        ],
        "acl_hashes": ["sha256:acl"],
        "acl_versions": [1],
    }
    assert audit_logger.events[1].metadata == {
        "source_version_id": "v1",
        "marked_reindex_pending": 2,
        "upserted_chunks": 2,
        "deleted_stale_chunks": 1,
        "requested_audit_event_id": "audit-upstream",
    }


def test_vector_worker_audit_events_persist_to_deployment_audit_storage(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit" / "events.jsonl"
    store = FakeVectorIndexStore()
    first_worker = VectorIndexWorker(
        store,
        audit_sink=build_durable_vector_worker_audit_sink(audit_log_path=audit_path),
    )

    first_worker.reindex_source(
        ReindexSourceCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            chunks=(record(chunk_id="chunk-1"), record(chunk_id="chunk-2")),
            audit_event_id="audit-upstream",
        )
    )
    second_worker = VectorIndexWorker(
        store,
        audit_sink=build_durable_vector_worker_audit_sink(audit_log_path=audit_path),
    )
    second_worker.propagate_deletion(
        DeletionPropagationCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            lifecycle_state=VectorLifecycleState.DELETED,
            audit_event_id="audit-delete",
        )
    )

    reloaded = JsonlAuditLogger.load(audit_path)
    assert reloaded.verify().ok
    assert [event.event_type for event in reloaded.events] == [
        "vector.reindex.started",
        "vector.reindex.completed",
        "vector.deletion_propagation.started",
        "vector.deletion_propagation.completed",
    ]
    assert [event.sequence_number for event in reloaded.events] == [1, 2, 3, 4]
    assert reloaded.events[0].user_id == "vector-index-worker"
    assert reloaded.events[0].input_hash is None
    assert reloaded.events[0].output_hash is None
    assert reloaded.events[2].previous_event_hash == reloaded.events[1].event_hash
    audit_log_text = audit_path.read_text(encoding="utf-8")
    assert '"embedding":' not in audit_log_text
    assert "1.0" not in audit_log_text


def test_vector_worker_audit_sink_rejects_raw_payload_metadata() -> None:
    audit_logger = InMemoryAuditLogger()
    sink = AuditLoggerVectorWorkerAuditSink(audit_logger)

    with pytest.raises(ValueError, match="source_text"):
        sink.record_worker_event(
            tenant_id="tenant-1",
            event_type="vector.reindex.started",
            source_object_id="doc-1",
            source_version_id="v1",
            metadata={"source_text": "classified content"},
        )

    with pytest.raises(ValueError, match=r"nested\.raw_embedding"):
        sink.record_worker_event(
            tenant_id="tenant-1",
            event_type="vector.reindex.started",
            source_object_id="doc-1",
            source_version_id="v1",
            metadata={"nested": {"raw_embedding": [1.0, 0.0, 0.0]}},
        )

    assert audit_logger.events == ()


def test_reindex_source_rejects_mismatched_or_duplicate_chunks() -> None:
    worker = VectorIndexWorker(FakeVectorIndexStore())

    with pytest.raises(ValueError, match="duplicate chunk ids"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(chunk_id="dup"), record(chunk_id="dup")),
            )
        )

    with pytest.raises(ValueError, match="tenant_id"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(tenant_id="tenant-2"),),
            )
        )

    with pytest.raises(ValueError, match="active records"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(lifecycle_state=VectorLifecycleState.RESTRICTED),),
            )
        )

    with pytest.raises(ValueError, match="acl_version"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(chunk_id="chunk-1", acl_version=1), record(chunk_id="chunk-2", acl_version=2)),
            )
        )

    with pytest.raises(ValueError, match="expected ACL version"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(chunk_id="chunk-1", acl_version=2),),
                expected_acl_version=1,
            )
        )

    with pytest.raises(ValueError, match="expected ACL hash"):
        worker.reindex_source(
            ReindexSourceCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                chunks=(record(chunk_id="chunk-1", acl_hash="sha256:new-acl"),),
                expected_acl_hash="sha256:old-acl",
            )
        )


def test_deletion_propagation_allows_only_delete_states() -> None:
    store = FakeVectorIndexStore()
    worker = VectorIndexWorker(store)

    result = worker.propagate_deletion(
        DeletionPropagationCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            lifecycle_state=VectorLifecycleState.CRYPTOSHREDDED,
            audit_event_id="audit-delete",
        )
    )

    assert result.transitioned_chunks == 3
    assert store.propagated == [("tenant-1", "doc-1", "v1", VectorLifecycleState.CRYPTOSHREDDED, "audit-delete")]

    with pytest.raises(ValueError, match="deleted or cryptoshredded"):
        worker.propagate_deletion(
            DeletionPropagationCommand(
                tenant_id="tenant-1",
                source_object_id="doc-1",
                source_version_id="v1",
                lifecycle_state=VectorLifecycleState.RESTRICTED,
            )
        )


def test_deletion_propagation_emits_worker_audit_events() -> None:
    store = FakeVectorIndexStore()
    audit_logger = InMemoryAuditLogger()
    worker = VectorIndexWorker(
        store,
        audit_sink=AuditLoggerVectorWorkerAuditSink(audit_logger),
    )

    result = worker.propagate_deletion(
        DeletionPropagationCommand(
            tenant_id="tenant-1",
            source_object_id="doc-1",
            source_version_id="v1",
            lifecycle_state=VectorLifecycleState.DELETED,
            audit_event_id="audit-delete",
        )
    )

    assert result.transitioned_chunks == 3
    assert audit_logger.verify().ok
    assert [event.event_type for event in audit_logger.events] == [
        "vector.deletion_propagation.started",
        "vector.deletion_propagation.completed",
    ]
    assert audit_logger.events[0].metadata == {
        "source_version_id": "v1",
        "target_lifecycle_state": "deleted",
        "requested_audit_event_id": "audit-delete",
    }
    assert audit_logger.events[1].metadata == {
        "source_version_id": "v1",
        "target_lifecycle_state": "deleted",
        "transitioned_chunks": 3,
        "requested_audit_event_id": "audit-delete",
    }
