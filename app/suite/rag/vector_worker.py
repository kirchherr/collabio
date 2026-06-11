from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from suite.ai_control_plane.audit import JsonlAuditLogger
from suite.ai_control_plane.models import AuditEvent, UserContext
from suite.platform.storage_paths import suite_data_dir
from suite.rag.models import VectorEmbeddingRecord, VectorLifecycleState

DEFAULT_DEPLOYMENT_AUDIT_LOG_RELATIVE_PATH = Path("audit") / "events.jsonl"
FORBIDDEN_VECTOR_WORKER_AUDIT_METADATA_KEYS = frozenset(
    {
        "answer",
        "embedding",
        "embeddings",
        "generated_answer",
        "output",
        "output_text",
        "prompt",
        "prompt_text",
        "raw_audio",
        "raw_embedding",
        "raw_embeddings",
        "source_text",
        "transcript",
    }
)


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


class AuditEventRecorder(Protocol):
    def record(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_id: str | None = None,
        prompt_template_id: str | None = None,
        source_object_ids: list[str] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent: ...


class VectorWorkerAuditSink(Protocol):
    def record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_object_id: str,
        source_version_id: str,
        metadata: dict[str, Any],
    ) -> str: ...


@dataclass(frozen=True)
class AuditLoggerVectorWorkerAuditSink:
    audit_logger: AuditEventRecorder
    user_id: str = "vector-index-worker"

    def record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_object_id: str,
        source_version_id: str,
        metadata: dict[str, Any],
    ) -> str:
        _assert_safe_vector_worker_audit_metadata(metadata)
        event = self.audit_logger.record(
            user_context=UserContext(user_id=self.user_id, tenant_id=tenant_id),
            event_type=event_type,
            source_object_ids=[source_object_id],
            metadata={
                "source_version_id": source_version_id,
                **metadata,
            },
        )
        return event.event_id


def build_durable_vector_worker_audit_sink(
    *,
    data_dir: Path | None = None,
    audit_log_path: Path | None = None,
    user_id: str = "vector-index-worker",
) -> AuditLoggerVectorWorkerAuditSink:
    if data_dir is not None and audit_log_path is not None:
        raise ValueError("use either data_dir or audit_log_path, not both")
    resolved_audit_log_path = audit_log_path
    if resolved_audit_log_path is None:
        resolved_audit_log_path = (data_dir or suite_data_dir()) / DEFAULT_DEPLOYMENT_AUDIT_LOG_RELATIVE_PATH
    return AuditLoggerVectorWorkerAuditSink(
        audit_logger=JsonlAuditLogger.load(resolved_audit_log_path),
        user_id=user_id,
    )


@dataclass(frozen=True)
class ReindexSourceCommand:
    tenant_id: str
    source_object_id: str
    source_version_id: str
    chunks: tuple[VectorEmbeddingRecord, ...]
    expected_acl_hash: str | None = None
    expected_acl_version: int | None = None
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
    def __init__(self, store: VectorIndexStore, *, audit_sink: VectorWorkerAuditSink | None = None) -> None:
        self.store = store
        self.audit_sink = audit_sink

    def reindex_source(self, command: ReindexSourceCommand) -> ReindexSourceResult:
        self._validate_reindex_command(command)
        self._record_worker_event(
            tenant_id=command.tenant_id,
            event_type="vector.reindex.started",
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            metadata={
                "requested_chunk_count": len(command.chunks),
                "requested_audit_event_id": command.audit_event_id,
                "embedding_models": self._embedding_models(command.chunks),
                "acl_hashes": self._acl_hashes(command.chunks),
                "acl_versions": self._acl_versions(command.chunks),
            },
        )

        try:
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
        except Exception as exc:
            self._record_worker_event(
                tenant_id=command.tenant_id,
                event_type="vector.reindex.failed",
                source_object_id=command.source_object_id,
                source_version_id=command.source_version_id,
                metadata={
                    "error_type": type(exc).__name__,
                    "requested_chunk_count": len(command.chunks),
                    "requested_audit_event_id": command.audit_event_id,
                },
            )
            raise

        result = ReindexSourceResult(
            marked_reindex_pending=marked,
            upserted_chunks=len(command.chunks),
            deleted_stale_chunks=deleted_stale,
        )
        self._record_worker_event(
            tenant_id=command.tenant_id,
            event_type="vector.reindex.completed",
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            metadata={
                "marked_reindex_pending": result.marked_reindex_pending,
                "upserted_chunks": result.upserted_chunks,
                "deleted_stale_chunks": result.deleted_stale_chunks,
                "requested_audit_event_id": command.audit_event_id,
            },
        )
        return result

    def propagate_deletion(self, command: DeletionPropagationCommand) -> DeletionPropagationResult:
        if command.lifecycle_state not in {VectorLifecycleState.DELETED, VectorLifecycleState.CRYPTOSHREDDED}:
            raise ValueError("deletion propagation must use deleted or cryptoshredded lifecycle state")

        self._record_worker_event(
            tenant_id=command.tenant_id,
            event_type="vector.deletion_propagation.started",
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            metadata={
                "target_lifecycle_state": command.lifecycle_state.value,
                "requested_audit_event_id": command.audit_event_id,
            },
        )
        try:
            transitioned = self.store.transition_source_lifecycle(
                tenant_id=command.tenant_id,
                source_object_id=command.source_object_id,
                source_version_id=command.source_version_id,
                lifecycle_state=command.lifecycle_state,
                audit_event_id=command.audit_event_id,
            )
        except Exception as exc:
            self._record_worker_event(
                tenant_id=command.tenant_id,
                event_type="vector.deletion_propagation.failed",
                source_object_id=command.source_object_id,
                source_version_id=command.source_version_id,
                metadata={
                    "error_type": type(exc).__name__,
                    "target_lifecycle_state": command.lifecycle_state.value,
                    "requested_audit_event_id": command.audit_event_id,
                },
            )
            raise

        result = DeletionPropagationResult(transitioned_chunks=transitioned)
        self._record_worker_event(
            tenant_id=command.tenant_id,
            event_type="vector.deletion_propagation.completed",
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            metadata={
                "target_lifecycle_state": command.lifecycle_state.value,
                "transitioned_chunks": result.transitioned_chunks,
                "requested_audit_event_id": command.audit_event_id,
            },
        )
        return result

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

        acl_hashes = self._acl_hashes(command.chunks)
        acl_versions = self._acl_versions(command.chunks)
        if len(acl_hashes) != 1:
            raise ValueError("reindex chunks must share one acl_hash")
        if len(acl_versions) != 1:
            raise ValueError("reindex chunks must share one acl_version")
        if command.expected_acl_hash is not None and acl_hashes[0] != command.expected_acl_hash:
            raise ValueError("chunk acl_hash does not match expected ACL hash")
        if command.expected_acl_version is not None and acl_versions[0] != command.expected_acl_version:
            raise ValueError("chunk acl_version does not match expected ACL version")

    def _duplicate_chunk_ids(self, chunks: Iterable[VectorEmbeddingRecord]) -> list[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for chunk in chunks:
            chunk_id = chunk.metadata.chunk_id
            if chunk_id in seen:
                duplicates.add(chunk_id)
            seen.add(chunk_id)
        return sorted(duplicates)

    def _record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_object_id: str,
        source_version_id: str,
        metadata: dict[str, Any],
    ) -> str | None:
        if self.audit_sink is None:
            return None
        return self.audit_sink.record_worker_event(
            tenant_id=tenant_id,
            event_type=event_type,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            metadata=metadata,
        )

    def _embedding_models(self, chunks: Iterable[VectorEmbeddingRecord]) -> list[dict[str, str]]:
        models = {
            (
                chunk.metadata.embedding_model_id,
                chunk.metadata.embedding_model_version,
            )
            for chunk in chunks
        }
        return [
            {
                "embedding_model_id": model_id,
                "embedding_model_version": model_version,
            }
            for model_id, model_version in sorted(models)
        ]

    def _acl_hashes(self, chunks: Iterable[VectorEmbeddingRecord]) -> list[str]:
        return sorted({chunk.metadata.acl_hash for chunk in chunks})

    def _acl_versions(self, chunks: Iterable[VectorEmbeddingRecord]) -> list[int]:
        return sorted({chunk.metadata.acl_version for chunk in chunks})


def _assert_safe_vector_worker_audit_metadata(metadata: dict[str, Any]) -> None:
    unsafe_key = _find_unsafe_vector_worker_audit_metadata_key(metadata)
    if unsafe_key is not None:
        raise ValueError(f"vector worker audit metadata must not include raw payload field: {unsafe_key}")


def _find_unsafe_vector_worker_audit_metadata_key(value: Any, *, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_text = str(key)
            normalized_key = key_text.lower()
            key_path = f"{path}.{key_text}" if path else key_text
            if normalized_key in FORBIDDEN_VECTOR_WORKER_AUDIT_METADATA_KEYS:
                return key_path
            nested_unsafe_key = _find_unsafe_vector_worker_audit_metadata_key(nested_value, path=key_path)
            if nested_unsafe_key is not None:
                return nested_unsafe_key
    if isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            nested_unsafe_key = _find_unsafe_vector_worker_audit_metadata_key(nested_value, path=f"{path}[{index}]")
            if nested_unsafe_key is not None:
                return nested_unsafe_key
    return None
