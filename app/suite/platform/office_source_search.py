from __future__ import annotations

import re
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.office_ai_risk_marking import office_document_risk_blocks
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentService,
    OfficeInformationClassification,
)
from suite.platform.office_reviews import ReviewAnchor

OFFICE_SOURCE_SEARCH_POLICY_ID = "office_current_version_keyword_acl_v1"
MAX_SOURCE_SEARCH_DOCUMENTS = 100
MAX_SOURCE_SEARCH_DOCUMENT_CHARACTERS = 32_000
MAX_SOURCE_SEARCH_TOTAL_CHARACTERS = 256_000
_TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)


class OfficeSourceSearchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=2, max_length=200)
    top_k: int = Field(default=6, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        tokens = _tokens(normalized)
        if not normalized or not tokens or len(set(tokens)) > 8:
            raise ValueError("source search query must contain one through eight searchable terms")
        return normalized


class OfficeSourceSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    version_id: str
    title: str
    information_classification: OfficeInformationClassification
    content_hash: str
    acl_version: int = Field(ge=1)
    anchor: ReviewAnchor
    source_excerpt: str
    score: int = Field(ge=1)
    authoritative_acl_validated: bool = True
    current_version_validated: bool = True


class OfficeSourceSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    query_hash: str
    results: list[OfficeSourceSearchResult]
    result_count: int = Field(ge=0, le=10)
    searched_document_count: int = Field(ge=0, le=MAX_SOURCE_SEARCH_DOCUMENTS)
    corpus_truncated: bool
    search_policy_id: str = OFFICE_SOURCE_SEARCH_POLICY_ID
    audit_event_id: str
    result_contract: str = "current_version_content_acl_revalidated"
    ai_used: bool = False
    vector_search_used: bool = False
    rag_context_created: bool = False
    persisted: bool = False
    document_changed: bool = False


class OfficeSourceSearchService:
    def __init__(self, *, documents: OfficeDocumentService) -> None:
        self.documents = documents

    def search(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: OfficeSourceSearchCommand,
    ) -> OfficeSourceSearchResponse:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("Source search requires the current saved document version")

        query_terms = set(_tokens(command.query))
        records = self.documents.repository.list_documents(
            user_context=user_context,
            query="",
            limit=MAX_SOURCE_SEARCH_DOCUMENTS + 1,
        )
        corpus_truncated = len(records) > MAX_SOURCE_SEARCH_DOCUMENTS
        searched = 0
        admitted_characters = 0
        results: list[OfficeSourceSearchResult] = []
        for record in records[:MAX_SOURCE_SEARCH_DOCUMENTS]:
            if record.object_id == object_id:
                continue
            # Both calls revalidate tenant and authoritative read ACL at source fetch time.
            document = self.documents.repository.get_document(
                user_context=user_context,
                object_id=record.object_id,
            )
            version = self.documents.repository.get_version(
                user_context=user_context,
                object_id=document.object_id,
                version_id=document.current_version_id,
            )
            if version.content_byte_length > MAX_SOURCE_SEARCH_DOCUMENT_CHARACTERS * 4:
                continue
            content = self.documents._read_content(document, version)
            blocks = office_document_risk_blocks(content)
            text_characters = sum(len(block.text) for block in blocks)
            if text_characters > MAX_SOURCE_SEARCH_DOCUMENT_CHARACTERS:
                continue
            if admitted_characters + text_characters > MAX_SOURCE_SEARCH_TOTAL_CHARACTERS:
                corpus_truncated = True
                break
            admitted_characters += text_characters
            searched += 1
            best_score = 0
            best_block = None
            for block in blocks:
                token_counts = {term: _tokens(block.text).count(term) for term in query_terms}
                score = sum(token_counts.values())
                if score > best_score:
                    best_score = score
                    best_block = block
            if best_block is None:
                continue
            results.append(
                OfficeSourceSearchResult(
                    object_id=document.object_id,
                    version_id=version.version_id,
                    title=version.title,
                    information_classification=version.information_classification,
                    content_hash=version.content_hash,
                    acl_version=version.acl_version,
                    anchor=best_block.anchor,
                    source_excerpt=best_block.text,
                    score=best_score,
                )
            )

        results = sorted(results, key=lambda item: (-item.score, item.title.casefold(), item.object_id))[
            : command.top_k
        ]
        query_hash = "sha256:" + sha256(command.query.casefold().encode("utf-8")).hexdigest()
        audit_event_id = self.documents._audit(
            user_context,
            "office.sources.searched",
            object_id=object_id,
            version_id=source.version.version_id,
            query_hash=query_hash,
            searched_document_count=searched,
            result_count=len(results),
            result_refs=[f"{result.object_id}:{result.version_id}" for result in results],
            result_content_hashes=[result.content_hash for result in results],
            corpus_truncated=corpus_truncated,
            search_policy_id=OFFICE_SOURCE_SEARCH_POLICY_ID,
            ai_used=False,
            vector_search_used=False,
            rag_context_created=False,
            persisted=False,
            document_changed=False,
        )
        return OfficeSourceSearchResponse(
            tenant_id=user_context.tenant_id,
            source_object_id=object_id,
            source_version_id=source.version.version_id,
            query_hash=query_hash,
            results=results,
            result_count=len(results),
            searched_document_count=searched,
            corpus_truncated=corpus_truncated,
            audit_event_id=audit_event_id,
        )


def _tokens(value: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(value)]
