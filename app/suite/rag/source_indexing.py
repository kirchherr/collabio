from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import sqrt
from typing import Protocol

from suite.ai_control_plane.models import DataClass
from suite.compliance.data_classes import source_indexable_data_classes
from suite.rag.models import ChunkMetadata, SourceDocument, VectorEmbeddingRecord
from suite.rag.vector_worker import ReindexSourceCommand, ReindexSourceResult, VectorIndexWorker

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")
DEFAULT_EMBEDDING_MODEL_DATA_CLASSES = source_indexable_data_classes()


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


class SourceRepository(Protocol):
    def get(self, object_id: str) -> SourceDocument: ...


class SourceResolver(Protocol):
    def resolve_source(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
    ) -> ResolvedSource: ...


class TextExtractor(Protocol):
    def extract_text(self, source: ResolvedSource) -> ExtractedText: ...


class TextChunker(Protocol):
    def chunk(self, *, source: ResolvedSource, text: str) -> tuple[ExtractedChunk, ...]: ...


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


class EmbeddingModelVersionRegistry(Protocol):
    def get(
        self,
        *,
        embedding_model_id: str,
        embedding_model_version: str,
    ) -> EmbeddingModelVersion: ...


@dataclass(frozen=True)
class EmbeddingModelVersion:
    embedding_model_id: str
    embedding_model_version: str
    provider: str
    deployment: str
    dimensions: int
    checksum: str
    approved_for_data_classes: frozenset[DataClass]
    distance_metric: str = "cosine"
    approved_at_utc: str | None = None
    retired_at_utc: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "embedding_model_id",
            "embedding_model_version",
            "provider",
            "deployment",
            "distance_metric",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.dimensions < 1:
            raise ValueError("embedding model dimensions must be greater than or equal to 1")
        if not NAMESPACED_REF_PATTERN.fullmatch(self.checksum.strip()):
            raise ValueError("embedding model checksum must be a namespaced reference")
        if not self.approved_for_data_classes:
            raise ValueError("embedding model must declare approved data classes")
        if self.approved_at_utc is not None:
            _require_utc_timestamp(self.approved_at_utc)
        if self.retired_at_utc is not None:
            _require_utc_timestamp(self.retired_at_utc)


class InMemoryEmbeddingModelVersionRegistry:
    def __init__(self, model_versions: Sequence[EmbeddingModelVersion]) -> None:
        self._model_versions: dict[tuple[str, str], EmbeddingModelVersion] = {}
        for model_version in model_versions:
            key = (model_version.embedding_model_id, model_version.embedding_model_version)
            if key in self._model_versions:
                raise ValueError("embedding model registry contains duplicate model versions")
            self._model_versions[key] = model_version

    @classmethod
    def approved_single_model(
        cls,
        *,
        embedding_model_id: str = "mock-embedding",
        embedding_model_version: str = "1",
        dimensions: int = 3,
        approved_for_data_classes: frozenset[DataClass] = DEFAULT_EMBEDDING_MODEL_DATA_CLASSES,
    ) -> InMemoryEmbeddingModelVersionRegistry:
        return cls(
            model_versions=(
                EmbeddingModelVersion(
                    embedding_model_id=embedding_model_id,
                    embedding_model_version=embedding_model_version,
                    provider="local-test",
                    deployment="deterministic-hash",
                    dimensions=dimensions,
                    checksum=sha256_text(f"{embedding_model_id}:{embedding_model_version}:{dimensions}"),
                    approved_for_data_classes=approved_for_data_classes,
                    approved_at_utc="2026-06-10T00:00:00Z",
                ),
            )
        )

    def get(
        self,
        *,
        embedding_model_id: str,
        embedding_model_version: str,
    ) -> EmbeddingModelVersion:
        try:
            return self._model_versions[(embedding_model_id, embedding_model_version)]
        except KeyError as exc:
            version_key = f"{embedding_model_id}@{embedding_model_version}"
            raise LookupError(f"Unknown embedding model version: {version_key}") from exc

    def list_model_versions(self) -> tuple[EmbeddingModelVersion, ...]:
        return tuple(self._model_versions[key] for key in sorted(self._model_versions))

    def upsert(self, model_version: EmbeddingModelVersion) -> EmbeddingModelVersion:
        key = (model_version.embedding_model_id, model_version.embedding_model_version)
        self._model_versions[key] = model_version
        return model_version


@dataclass(frozen=True)
class ResolvedSource:
    tenant_id: str
    object_id: str
    version_id: str
    title: str
    text: str
    classification: DataClass
    source_object_type: str
    retention_policy_id: str
    legal_hold_state: str
    acl_hash: str
    acl_version: int
    created_at_utc: str
    mime_type: str = "text/plain"
    content_bytes: bytes | None = None


@dataclass(frozen=True)
class ExtractedText:
    text: str


@dataclass(frozen=True)
class ExtractedChunk:
    chunk_id: str
    text: str
    content_hash: str
    content_byte_length: int


@dataclass(frozen=True)
class SourceIndexCommand:
    tenant_id: str
    source_object_id: str
    source_version_id: str
    expected_acl_hash: str | None = None
    expected_acl_version: int | None = None
    audit_event_id: str | None = None


@dataclass(frozen=True)
class SourceIndexResult:
    source_object_id: str
    source_version_id: str
    chunk_count: int
    reindex_result: ReindexSourceResult


class RepositorySourceResolver:
    def __init__(
        self,
        source_repository: SourceRepository,
        *,
        source_object_type: str = "document",
        retention_policy_id: str = "rp-standard",
        legal_hold_state: str = "none",
        acl_version: int = 1,
        created_at_clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        if not source_object_type:
            raise ValueError("source_object_type must not be empty")
        if not retention_policy_id:
            raise ValueError("retention_policy_id must not be empty")
        if legal_hold_state not in {"none", "active"}:
            raise ValueError("legal_hold_state must be none or active")
        if acl_version < 1:
            raise ValueError("acl_version must be greater than or equal to 1")

        self.source_repository = source_repository
        self.source_object_type = source_object_type
        self.retention_policy_id = retention_policy_id
        self.legal_hold_state = legal_hold_state
        self.acl_version = acl_version
        self.created_at_clock = created_at_clock

    def resolve_source(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
    ) -> ResolvedSource:
        document = self.source_repository.get(source_object_id)
        if document.object_id != source_object_id:
            raise ValueError("resolved source object_id does not match index command")
        if document.version_id != source_version_id:
            raise ValueError("resolved source version_id does not match index command")

        acl_hash_input = f"{tenant_id}:{document.object_id}:{document.version_id}:{document.classification.value}"
        return ResolvedSource(
            tenant_id=tenant_id,
            object_id=document.object_id,
            version_id=document.version_id,
            title=document.title,
            text=document.text,
            classification=document.classification,
            source_object_type=self.source_object_type,
            retention_policy_id=self.retention_policy_id,
            legal_hold_state=self.legal_hold_state,
            acl_hash=sha256_text(acl_hash_input),
            acl_version=self.acl_version,
            created_at_utc=self.created_at_clock(),
            mime_type=document.mime_type,
            content_bytes=document.content_bytes,
        )


class PlainTextExtractor:
    def extract_text(self, source: ResolvedSource) -> ExtractedText:
        text = source.text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.rstrip() for line in text.split("\n")).strip()
        if not normalized:
            raise ValueError("source text is empty after extraction")
        return ExtractedText(text=normalized)


class FixedSizeTextChunker:
    def __init__(
        self,
        *,
        max_characters: int = 1200,
        overlap_characters: int = 0,
        chunk_id_prefix: str = "chunk",
    ) -> None:
        if max_characters < 1:
            raise ValueError("max_characters must be greater than or equal to 1")
        if overlap_characters < 0 or overlap_characters >= max_characters:
            raise ValueError("overlap_characters must be non-negative and smaller than max_characters")
        if not chunk_id_prefix:
            raise ValueError("chunk_id_prefix must not be empty")

        self.max_characters = max_characters
        self.overlap_characters = overlap_characters
        self.chunk_id_prefix = chunk_id_prefix

    def chunk(self, *, source: ResolvedSource, text: str) -> tuple[ExtractedChunk, ...]:
        del source
        normalized = text.strip()
        if not normalized:
            raise ValueError("extracted source text is empty")

        step = self.max_characters - self.overlap_characters
        chunks: list[ExtractedChunk] = []
        start = 0
        while start < len(normalized):
            segment = normalized[start : start + self.max_characters].strip()
            if segment:
                index = len(chunks)
                chunks.append(
                    ExtractedChunk(
                        chunk_id=f"{self.chunk_id_prefix}-{index:04d}",
                        text=segment,
                        content_hash=sha256_text(segment),
                        content_byte_length=len(segment.encode("utf-8")),
                    )
                )
            start += step

        if not chunks:
            raise ValueError("source text produced no chunks")
        return tuple(chunks)


class DeterministicHashEmbeddingProvider:
    def __init__(self, *, dimensions: int = 3) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be greater than or equal to 1")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        values: list[float] = []
        seed = sha256(text.encode("utf-8")).digest()
        counter = 0
        while len(values) < self.dimensions:
            block = sha256(seed + counter.to_bytes(4, byteorder="big")).digest()
            for offset in range(0, len(block), 4):
                raw = int.from_bytes(block[offset : offset + 4], byteorder="big")
                values.append((raw / 2**32) * 2 - 1)
                if len(values) == self.dimensions:
                    break
            counter += 1

        magnitude = sqrt(sum(value * value for value in values))
        if magnitude == 0:
            return values
        return [value / magnitude for value in values]


class SourceIndexingPipeline:
    def __init__(
        self,
        *,
        resolver: SourceResolver,
        text_extractor: TextExtractor,
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        embedding_model_registry: EmbeddingModelVersionRegistry,
        worker: VectorIndexWorker,
        embedding_model_id: str,
        embedding_model_version: str,
        indexed_at_clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.resolver = resolver
        self.text_extractor = text_extractor
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model_registry.get(
            embedding_model_id=embedding_model_id,
            embedding_model_version=embedding_model_version,
        )
        self.worker = worker
        self.embedding_model_id = embedding_model_id
        self.embedding_model_version = embedding_model_version
        self.indexed_at_clock = indexed_at_clock

    def index_source(self, command: SourceIndexCommand) -> SourceIndexResult:
        source = self.resolver.resolve_source(
            tenant_id=command.tenant_id,
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
        )
        self._validate_source(command=command, source=source)
        self._validate_embedding_model_for_source(source)

        extracted = self.text_extractor.extract_text(source)
        chunks = self.chunker.chunk(source=source, text=extracted.text)
        records = tuple(
            self._build_record(source=source, chunk=chunk, audit_event_id=command.audit_event_id) for chunk in chunks
        )
        reindex_result = self.worker.reindex_source(
            ReindexSourceCommand(
                tenant_id=command.tenant_id,
                source_object_id=command.source_object_id,
                source_version_id=command.source_version_id,
                chunks=records,
                expected_acl_hash=command.expected_acl_hash,
                expected_acl_version=command.expected_acl_version,
                audit_event_id=command.audit_event_id,
            )
        )
        return SourceIndexResult(
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            chunk_count=len(records),
            reindex_result=reindex_result,
        )

    def _build_record(
        self,
        *,
        source: ResolvedSource,
        chunk: ExtractedChunk,
        audit_event_id: str | None,
    ) -> VectorEmbeddingRecord:
        embedding = list(self.embedding_provider.embed(chunk.text))
        if len(embedding) != self.embedding_model.dimensions:
            raise ValueError("embedding dimensions do not match registered model version")
        return VectorEmbeddingRecord(
            metadata=ChunkMetadata(
                tenant_id=source.tenant_id,
                source_object_id=source.object_id,
                source_object_type=source.source_object_type,
                source_version_id=source.version_id,
                chunk_id=chunk.chunk_id,
                classification=source.classification,
                retention_policy_id=source.retention_policy_id,
                legal_hold_state=source.legal_hold_state,
                acl_hash=source.acl_hash,
                acl_version=source.acl_version,
                created_at_utc=source.created_at_utc,
                embedding_model_id=self.embedding_model_id,
                embedding_model_version=self.embedding_model_version,
                content_hash=chunk.content_hash,
            ),
            embedding=embedding,
            embedding_dimensions=len(embedding),
            content_byte_length=chunk.content_byte_length,
            indexed_at_utc=self.indexed_at_clock(),
            audit_event_id=audit_event_id,
        )

    def _validate_source(self, *, command: SourceIndexCommand, source: ResolvedSource) -> None:
        if source.tenant_id != command.tenant_id:
            raise ValueError("resolved source tenant_id does not match index command")
        if source.object_id != command.source_object_id:
            raise ValueError("resolved source object_id does not match index command")
        if source.version_id != command.source_version_id:
            raise ValueError("resolved source version_id does not match index command")
        if source.acl_version < 1:
            raise ValueError("resolved source acl_version must be greater than or equal to 1")
        if command.expected_acl_hash is not None and source.acl_hash != command.expected_acl_hash:
            raise ValueError("resolved source acl_hash does not match index command")
        if command.expected_acl_version is not None and source.acl_version != command.expected_acl_version:
            raise ValueError("resolved source acl_version does not match index command")

    def _validate_embedding_model_for_source(self, source: ResolvedSource) -> None:
        if self.embedding_model.embedding_model_id != self.embedding_model_id:
            raise ValueError("registered embedding model_id does not match pipeline configuration")
        if self.embedding_model.embedding_model_version != self.embedding_model_version:
            raise ValueError("registered embedding model_version does not match pipeline configuration")
        if self.embedding_model.approved_at_utc is None:
            raise ValueError("embedding model version is not approved for indexing")
        if self.embedding_model.retired_at_utc is not None:
            raise ValueError("embedding model version is retired")
        if source.classification not in self.embedding_model.approved_for_data_classes:
            raise ValueError("embedding model version is not approved for source data class")


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized
