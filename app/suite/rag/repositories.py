from suite.ai_control_plane.models import DataClass, UserContext
from suite.rag.models import ChunkMetadata, SourceDocument, VectorCandidate


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


class InMemoryAclAuthorizer:
    def __init__(self, allowed_by_user: dict[str, set[str]]) -> None:
        self._allowed_by_user = allowed_by_user

    @classmethod
    def demo(cls) -> "InMemoryAclAuthorizer":
        return cls(allowed_by_user={"user-demo": {"doc-1", "mail-1"}})

    def can_read(self, *, user_context: UserContext, object_id: str, acl_version: int) -> bool:
        return object_id in self._allowed_by_user.get(user_context.user_id, set())
