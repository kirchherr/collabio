from typing import Protocol

from suite.ai_control_plane.models import DataClass, UserContext
from suite.rag.models import ChunkMetadata, SourceChunk, SourceDocument, VectorCandidate


class VectorStore(Protocol):
    def search(self, *, tenant_id: str, query: str, top_k: int) -> list[VectorCandidate]: ...


class ChunkRepository(Protocol):
    def get_chunk(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        chunk_id: str,
    ) -> SourceChunk: ...


class AclAuthorizer(Protocol):
    def can_read(self, *, user_context: UserContext, object_id: str, acl_version: int) -> bool: ...


class InMemoryVectorStore:
    def __init__(self, candidates: list[VectorCandidate]) -> None:
        self._candidates = candidates

    @classmethod
    def demo(cls) -> "InMemoryVectorStore":
        candidates = [
            VectorCandidate(
                chunk_id="chunk-doc-1",
                score=0.91,
                metadata=ChunkMetadata(
                    tenant_id="tenant-demo",
                    source_object_id="doc-1",
                    source_object_type="document",
                    source_version_id="v1",
                    chunk_id="chunk-doc-1",
                    classification=DataClass.INTERNAL,
                    retention_policy_id="rp-standard",
                    legal_hold_state="none",
                    acl_hash="sha256:acl-doc-1",
                    acl_version=1,
                    created_at_utc="2026-06-10T00:00:00Z",
                    embedding_model_id="mock-embedding",
                    embedding_model_version="1",
                    content_hash="sha256:doc-1",
                ),
            ),
            VectorCandidate(
                chunk_id="chunk-secret-1",
                score=0.89,
                metadata=ChunkMetadata(
                    tenant_id="tenant-demo",
                    source_object_id="secret-1",
                    source_object_type="document",
                    source_version_id="v1",
                    chunk_id="chunk-secret-1",
                    classification=DataClass.CONFIDENTIAL,
                    retention_policy_id="rp-restricted",
                    legal_hold_state="none",
                    acl_hash="sha256:acl-secret-1",
                    acl_version=1,
                    created_at_utc="2026-06-10T00:00:00Z",
                    embedding_model_id="mock-embedding",
                    embedding_model_version="1",
                    content_hash="sha256:secret-1",
                ),
            ),
        ]
        return cls(candidates=candidates)

    def search(self, *, tenant_id: str, query: str, top_k: int) -> list[VectorCandidate]:
        candidates = [candidate for candidate in self._candidates if candidate.metadata.tenant_id == tenant_id]
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:top_k]


class InMemorySourceRepository:
    def __init__(self, documents: dict[str, SourceDocument]) -> None:
        self._documents = documents

    @classmethod
    def demo(cls) -> "InMemorySourceRepository":
        return cls(
            documents={
                "doc-1": SourceDocument(
                    object_id="doc-1",
                    version_id="v1",
                    title="Demo policy",
                    text="AI suggestions must remain drafts and require source citations for RAG answers.",
                    classification=DataClass.INTERNAL,
                ),
                "secret-1": SourceDocument(
                    object_id="secret-1",
                    version_id="v1",
                    title="Restricted note",
                    text="This confidential source must never be exposed to unauthorized users.",
                    classification=DataClass.CONFIDENTIAL,
                ),
            }
        )

    def get(self, object_id: str) -> SourceDocument:
        return self._documents[object_id]


class InMemorySourceChunkRepository:
    def __init__(self, chunks: dict[tuple[str, str, str, str], SourceChunk]) -> None:
        self._chunks = chunks

    @classmethod
    def demo(cls) -> "InMemorySourceChunkRepository":
        return cls(
            chunks={
                (
                    "tenant-demo",
                    "doc-1",
                    "v1",
                    "chunk-doc-1",
                ): SourceChunk(
                    metadata=ChunkMetadata(
                        tenant_id="tenant-demo",
                        source_object_id="doc-1",
                        source_object_type="document",
                        source_version_id="v1",
                        chunk_id="chunk-doc-1",
                        classification=DataClass.INTERNAL,
                        retention_policy_id="rp-standard",
                        legal_hold_state="none",
                        acl_hash="sha256:acl-doc-1",
                        acl_version=1,
                        created_at_utc="2026-06-10T00:00:00Z",
                        embedding_model_id="mock-embedding",
                        embedding_model_version="1",
                        content_hash="sha256:doc-1",
                    ),
                    title="Demo policy",
                    text="AI suggestions must remain drafts and require source citations for RAG answers.",
                ),
                (
                    "tenant-demo",
                    "secret-1",
                    "v1",
                    "chunk-secret-1",
                ): SourceChunk(
                    metadata=ChunkMetadata(
                        tenant_id="tenant-demo",
                        source_object_id="secret-1",
                        source_object_type="document",
                        source_version_id="v1",
                        chunk_id="chunk-secret-1",
                        classification=DataClass.CONFIDENTIAL,
                        retention_policy_id="rp-restricted",
                        legal_hold_state="none",
                        acl_hash="sha256:acl-secret-1",
                        acl_version=1,
                        created_at_utc="2026-06-10T00:00:00Z",
                        embedding_model_id="mock-embedding",
                        embedding_model_version="1",
                        content_hash="sha256:secret-1",
                    ),
                    title="Restricted note",
                    text="This confidential source must never be exposed to unauthorized users.",
                ),
            }
        )

    def get_chunk(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        chunk_id: str,
    ) -> SourceChunk:
        return self._chunks[(tenant_id, source_object_id, source_version_id, chunk_id)]


class AuthorizedChunkRepository:
    def __init__(self, *, chunk_repository: ChunkRepository, acl_authorizer: AclAuthorizer) -> None:
        self.chunk_repository = chunk_repository
        self.acl_authorizer = acl_authorizer

    def get_authorized_chunk(self, *, user_context: UserContext, candidate: VectorCandidate) -> SourceChunk | None:
        metadata = candidate.metadata
        if metadata.tenant_id != user_context.tenant_id:
            return None
        if not self.acl_authorizer.can_read(
            user_context=user_context,
            object_id=metadata.source_object_id,
            acl_version=metadata.acl_version,
        ):
            return None
        try:
            chunk = self.chunk_repository.get_chunk(
                tenant_id=metadata.tenant_id,
                source_object_id=metadata.source_object_id,
                source_version_id=metadata.source_version_id,
                chunk_id=metadata.chunk_id,
            )
        except KeyError:
            return None

        if not self._metadata_matches_candidate(candidate, chunk):
            return None
        return chunk

    def _metadata_matches_candidate(self, candidate: VectorCandidate, chunk: SourceChunk) -> bool:
        expected = candidate.metadata
        actual = chunk.metadata
        return (
            actual.tenant_id == expected.tenant_id
            and actual.source_object_id == expected.source_object_id
            and actual.source_object_type == expected.source_object_type
            and actual.source_version_id == expected.source_version_id
            and actual.chunk_id == expected.chunk_id
            and actual.classification == expected.classification
            and actual.retention_policy_id == expected.retention_policy_id
            and actual.legal_hold_state == expected.legal_hold_state
            and actual.acl_hash == expected.acl_hash
            and actual.acl_version == expected.acl_version
            and actual.embedding_model_id == expected.embedding_model_id
            and actual.embedding_model_version == expected.embedding_model_version
            and actual.content_hash == expected.content_hash
        )


class InMemoryAclAuthorizer:
    def __init__(self, allowed_by_user: dict[str, set[str]]) -> None:
        self._allowed_by_user = allowed_by_user

    @classmethod
    def demo(cls) -> "InMemoryAclAuthorizer":
        return cls(allowed_by_user={"user-demo": {"doc-1", "mail-1"}})

    def can_read(self, *, user_context: UserContext, object_id: str, acl_version: int) -> bool:
        return object_id in self._allowed_by_user.get(user_context.user_id, set())


class ReadableObjectAclAuthorizer:
    def can_read(self, *, user_context: UserContext, object_id: str, acl_version: int) -> bool:
        return object_id in user_context.readable_object_ids
