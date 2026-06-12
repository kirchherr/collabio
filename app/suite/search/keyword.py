import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.rag.models import ChunkMetadata
from suite.rag.repositories import AclAuthorizer
from suite.search.models import (
    SEARCH_POLICY_ID,
    KeywordSearchCandidate,
    KeywordSearchQuery,
    KeywordSearchResponse,
)

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
ACTIVE_LIFECYCLE_STATE = "active"


@dataclass(frozen=True)
class KeywordIndexedChunk:
    metadata: ChunkMetadata
    title: str
    index_text: str
    lifecycle_state: str = ACTIVE_LIFECYCLE_STATE

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.index_text.strip():
            raise ValueError("index_text must not be empty")


@dataclass(frozen=True)
class KeywordIndexCandidate:
    metadata: ChunkMetadata
    title: str
    score: float


class KeywordIndex(Protocol):
    def search(self, *, tenant_id: str, query: str, top_k: int) -> list[KeywordIndexCandidate]: ...


class InMemoryKeywordIndex:
    def __init__(self, records: list[KeywordIndexedChunk]) -> None:
        self._records = records

    @classmethod
    def demo(cls) -> "InMemoryKeywordIndex":
        return cls(
            records=[
                KeywordIndexedChunk(
                    metadata=keyword_metadata(
                        object_id="doc-1",
                        chunk_id="chunk-doc-1",
                        classification=DataClass.INTERNAL,
                        retention_policy_id="rp-standard",
                        acl_hash="sha256:acl-doc-1",
                        content_hash="sha256:doc-1",
                    ),
                    title="Demo policy",
                    index_text="AI suggestions must remain drafts and require source citations for RAG answers.",
                ),
                KeywordIndexedChunk(
                    metadata=keyword_metadata(
                        object_id="secret-1",
                        chunk_id="chunk-secret-1",
                        classification=DataClass.CONFIDENTIAL,
                        retention_policy_id="rp-restricted",
                        acl_hash="sha256:acl-secret-1",
                        content_hash="sha256:secret-1",
                    ),
                    title="Restricted note",
                    index_text="This confidential source must never be exposed to unauthorized users.",
                ),
            ]
        )

    def search(self, *, tenant_id: str, query: str, top_k: int) -> list[KeywordIndexCandidate]:
        query_terms = set(tokenize(query))
        if not query_terms:
            return []

        candidates: list[KeywordIndexCandidate] = []
        for record in self._records:
            if record.metadata.tenant_id != tenant_id:
                continue
            if record.lifecycle_state != ACTIVE_LIFECYCLE_STATE:
                continue
            token_counts = Counter(tokenize(f"{record.title} {record.index_text}"))
            score = float(sum(token_counts[term] for term in query_terms))
            if score <= 0:
                continue
            candidates.append(
                KeywordIndexCandidate(
                    metadata=record.metadata,
                    title=record.title,
                    score=score,
                )
            )

        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                candidate.metadata.source_object_id,
                candidate.metadata.source_version_id,
                candidate.metadata.chunk_id,
            ),
        )[:top_k]


class KeywordSearchService:
    def __init__(
        self,
        *,
        index: KeywordIndex,
        acl_authorizer: AclAuthorizer,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.index = index
        self.acl_authorizer = acl_authorizer
        self.audit_logger = audit_logger

    def search(self, *, query: KeywordSearchQuery, user_context: UserContext) -> KeywordSearchResponse:
        candidates = self.index.search(
            tenant_id=user_context.tenant_id,
            query=query.query,
            top_k=query.top_k,
        )
        authorized_candidates: list[KeywordSearchCandidate] = []
        for candidate in candidates:
            metadata = candidate.metadata
            if metadata.tenant_id != user_context.tenant_id:
                continue
            if not self.acl_authorizer.can_read(
                user_context=user_context,
                object_id=metadata.source_object_id,
                acl_version=metadata.acl_version,
            ):
                continue
            authorized_candidates.append(candidate_view(candidate))

        audit_event = self.audit_logger.record(
            user_context=user_context,
            event_type="search.keyword.query",
            source_object_ids=unique_candidate_object_ids(authorized_candidates),
            input_text=query.query,
            metadata={
                "candidate_count": len(candidates),
                "authorized_candidate_count": len(authorized_candidates),
                "authorized_candidate_refs": candidate_refs(authorized_candidates),
                "authorized_source_data_classes": sorted(
                    {candidate.classification.value for candidate in authorized_candidates}
                ),
                "index_kind": "keyword",
                "result_contract": "candidate_only",
                "search_policy_id": SEARCH_POLICY_ID,
            },
        )
        return KeywordSearchResponse(
            candidates=authorized_candidates,
            search_policy_id=SEARCH_POLICY_ID,
            audit_event_id=audit_event.event_id,
        )


def keyword_metadata(
    *,
    object_id: str,
    chunk_id: str,
    classification: DataClass,
    retention_policy_id: str,
    acl_hash: str,
    content_hash: str,
    tenant_id: str = "tenant-demo",
    object_type: str = "document",
    version_id: str = "v1",
    acl_version: int = 1,
) -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id=tenant_id,
        source_object_id=object_id,
        source_object_type=object_type,
        source_version_id=version_id,
        chunk_id=chunk_id,
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state="none",
        acl_hash=acl_hash,
        acl_version=acl_version,
        created_at_utc="2026-06-10T00:00:00Z",
        embedding_model_id="keyword-index",
        embedding_model_version="1",
        content_hash=content_hash,
    )


def candidate_view(candidate: KeywordIndexCandidate) -> KeywordSearchCandidate:
    metadata = candidate.metadata
    return KeywordSearchCandidate(
        object_id=metadata.source_object_id,
        object_type=metadata.source_object_type,
        version_id=metadata.source_version_id,
        chunk_id=metadata.chunk_id,
        title=candidate.title,
        classification=metadata.classification,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state,
        acl_version=metadata.acl_version,
        content_hash=metadata.content_hash,
        score=candidate.score,
        access_checked=True,
    )


def tokenize(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(value)]


def unique_candidate_object_ids(candidates: list[KeywordSearchCandidate]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate.object_id in seen:
            continue
        seen.add(candidate.object_id)
        ordered.append(candidate.object_id)
    return ordered


def candidate_refs(candidates: list[KeywordSearchCandidate]) -> list[str]:
    return [f"{candidate.object_id}:{candidate.version_id}:{candidate.chunk_id}" for candidate in candidates]
