from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from suite.rag.models import VectorEmbeddingRecord, VectorLifecycleState


class VectorIndexStore(Protocol):
    def mark_source_for_reindex(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        audit_event_id: str | None = None,
    ) -> int: ...

    def upsert_embedding(self, record: VectorEmbeddingRecord) -> None: ...

    def delete_reindex_orphans(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        keep_chunk_ids: set[str],
        audit_event_id: str | None = None,
    ) -> int: ...

    def transition_source_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> int: ...


@dataclass(frozen=True)
class ReindexSourceCommand:
    tenant_id: str
    source_object_id: str
    source_version_id: str
    chunks: tuple[VectorEmbeddingRecord, ...]
    audit_event_id: str | None = None


@dataclass(frozen=True)
class ReindexSourceResult:
    marked_reindex_pending: int
    upserted_chunks: int
    deleted_stale_chunks: int


@dataclass(frozen=True)
class DeletionPropagationCommand:
    tenant_id: str
    source_object_id: str
    source_version_id: str
    lifecycle_state: VectorLifecycleState = VectorLifecycleState.DELETED
    audit_event_id: str | None = None


@dataclass(frozen=True)
class DeletionPropagationResult:
    transitioned_chunks: int


class VectorIndexWorker:
    def __init__(self, store: VectorIndexStore) -> None:
        self.store = store

    def reindex_source(self, command: ReindexSourceCommand) -> ReindexSourceResult:
        self._validate_reindex_command(command)

        marked = self.store.mark_source_for_reindex(
            tenant_id=command.tenant_id,
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            audit_event_id=command.audit_event_id,
        )
        for chunk in command.chunks:
            self.store.upsert_embedding(chunk)

        deleted_stale = self.store.delete_reindex_orphans(
            tenant_id=command.tenant_id,
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            keep_chunk_ids={chunk.metadata.chunk_id for chunk in command.chunks},
            audit_event_id=command.audit_event_id,
        )
        return ReindexSourceResult(
            marked_reindex_pending=marked,
            upserted_chunks=len(command.chunks),
            deleted_stale_chunks=deleted_stale,
        )

    def propagate_deletion(self, command: DeletionPropagationCommand) -> DeletionPropagationResult:
        if command.lifecycle_state not in {VectorLifecycleState.DELETED, VectorLifecycleState.CRYPTOSHREDDED}:
            raise ValueError("deletion propagation must use deleted or cryptoshredded lifecycle state")

        transitioned = self.store.transition_source_lifecycle(
            tenant_id=command.tenant_id,
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            lifecycle_state=command.lifecycle_state,
            audit_event_id=command.audit_event_id,
        )
        return DeletionPropagationResult(transitioned_chunks=transitioned)

    def _validate_reindex_command(self, command: ReindexSourceCommand) -> None:
        if not command.chunks:
            raise ValueError("reindex command must contain at least one chunk")
        duplicate_chunk_ids = self._duplicate_chunk_ids(command.chunks)
        if duplicate_chunk_ids:
            raise ValueError(f"reindex command contains duplicate chunk ids: {', '.join(duplicate_chunk_ids)}")

        for chunk in command.chunks:
            metadata = chunk.metadata
            if metadata.tenant_id != command.tenant_id:
                raise ValueError("chunk tenant_id does not match reindex command")
            if metadata.source_object_id != command.source_object_id:
                raise ValueError("chunk source_object_id does not match reindex command")
            if metadata.source_version_id != command.source_version_id:
                raise ValueError("chunk source_version_id does not match reindex command")
            if chunk.lifecycle_state != VectorLifecycleState.ACTIVE:
                raise ValueError("reindex chunks must be active records")

    def _duplicate_chunk_ids(self, chunks: Iterable[VectorEmbeddingRecord]) -> list[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for chunk in chunks:
            chunk_id = chunk.metadata.chunk_id
            if chunk_id in seen:
                duplicates.add(chunk_id)
            seen.add(chunk_id)
        return sorted(duplicates)
