from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_ai_summary import LOCAL_MODEL_PROVIDERS
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_source_search import (
    OfficeSourceSearchCommand,
    OfficeSourceSearchResult,
    OfficeSourceSearchService,
    _tokens,
)

OFFICE_RAG_PROMPT_ID = "rag_answer_v1"
OFFICE_RAG_RETRIEVAL_POLICY_ID = "office_current_version_keyword_rag_v1"
MAX_RAG_SOURCE_CHARACTERS = 4_000
MAX_RAG_CONTEXT_CHARACTERS = 12_000


class OfficeRagAnswerUnavailable(RuntimeError):
    pass


class OfficeRagAnswerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=2, max_length=200)
    top_k: int = Field(default=4, ge=1, le=6)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        tokens = _tokens(normalized)
        if not normalized or not tokens or len(set(tokens)) > 8:
            raise ValueError("RAG question must contain one through eight searchable terms")
        return normalized


class OfficeRagCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    version_id: str
    title: str
    information_classification: str
    content_hash: str
    acl_version: int = Field(ge=1)
    anchor: ReviewAnchor
    source_excerpt: str
    authoritative_acl_validated: Literal[True] = True
    exact_current_version_validated: Literal[True] = True


class OfficeRagAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    question_hash: str
    answer: str
    answer_supported: bool
    confidence: Literal["source_grounded_unverified", "unsupported"]
    citations: list[OfficeRagCitation]
    citation_count: int = Field(ge=0, le=6)
    retrieval_policy_id: str = OFFICE_RAG_RETRIEVAL_POLICY_ID
    retrieval_audit_event_id: str
    inference_audit_event_id: str | None
    audit_event_id: str
    model_id: str | None
    prompt_template_id: str | None
    output_trust: Literal["untrusted"] = "untrusted"
    requires_human_review: Literal[True] = True
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False
    rag_indexing_allowed: Literal[False] = False


class OfficeRagAnswerService:
    def __init__(
        self,
        *,
        documents: OfficeDocumentService,
        source_search: OfficeSourceSearchService,
        gateway: LocalLLMGateway,
    ) -> None:
        self.documents = documents
        self.source_search = source_search
        self.gateway = gateway

    def answer(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeRagAnswerCommand,
    ) -> OfficeRagAnswerResponse:
        if not tenant_policy.ai_enabled or not tenant_policy.rag_enabled:
            raise PolicyViolation("Office RAG requires tenant AI and RAG policy admission")
        search = self.source_search.search(
            user_context=user_context,
            object_id=object_id,
            command=OfficeSourceSearchCommand(
                expected_current_version_id=command.expected_current_version_id,
                query=command.question,
                top_k=command.top_k,
            ),
        )
        citations: list[OfficeRagCitation] = []
        source_blocks: list[str] = []
        context_characters = 0
        data_classes = {DataClass.AI_PROMPT}
        for candidate in search.results:
            citation = self._reauthorize_citation(user_context=user_context, candidate=candidate)
            if len(citation.source_excerpt) > MAX_RAG_SOURCE_CHARACTERS:
                continue
            if context_characters + len(citation.source_excerpt) > MAX_RAG_CONTEXT_CHARACTERS:
                break
            context_characters += len(citation.source_excerpt)
            citations.append(citation)
            data_classes.add(self._data_class(citation.information_classification))
            source_blocks.append(self._source_block(citation))

        question_hash = "sha256:" + sha256(command.question.casefold().encode("utf-8")).hexdigest()
        if not citations:
            answer = "Keine durch lesbare aktuelle Dokumentversionen belegte Antwort verfügbar."
            audit_event_id = self.documents._audit(
                user_context,
                "office.rag.answer.unsupported",
                object_id=object_id,
                version_id=search.source_version_id,
                question_hash=question_hash,
                retrieval_audit_event_id=search.audit_event_id,
                retrieval_policy_id=OFFICE_RAG_RETRIEVAL_POLICY_ID,
                citation_count=0,
                answer_supported=False,
                output_hash="sha256:" + sha256(answer.encode("utf-8")).hexdigest(),
                persisted=False,
                document_changed=False,
                automatic_action_allowed=False,
            )
            return OfficeRagAnswerResponse(
                tenant_id=user_context.tenant_id,
                object_id=object_id,
                source_version_id=search.source_version_id,
                question_hash=question_hash,
                answer=answer,
                answer_supported=False,
                confidence="unsupported",
                citations=[],
                citation_count=0,
                retrieval_audit_event_id=search.audit_event_id,
                inference_audit_event_id=None,
                audit_event_id=audit_event_id,
                model_id=None,
                prompt_template_id=None,
            )

        model_id = self._local_rag_model_id(tenant_policy=tenant_policy, data_classes=data_classes)
        source_ids = [citation.object_id for citation in citations]
        inference_user = user_context.model_copy(
            update={"readable_object_ids": set(user_context.readable_object_ids) | set(source_ids)}
        )
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=OFFICE_RAG_PROMPT_ID,
                model_id=model_id,
                purpose=Purpose.RAG,
                input_text=command.question,
                data_classes=data_classes,
                source_object_ids=source_ids,
                risk_level=RiskLevel.MEDIUM,
            ),
            user_context=inference_user,
            tenant_policy=tenant_policy,
            sources_text="\n".join(source_blocks),
        )
        answer = inference.answer.strip()
        if (
            not answer
            or len(answer) > 6_000
            or any((ord(character) < 32 and character not in "\n\t") for character in answer)
            or any(0xD800 <= ord(character) <= 0xDFFF for character in answer)
        ):
            raise OfficeRagAnswerUnavailable("Local model returned an invalid Office RAG answer")
        audit_event_id = self.documents._audit(
            user_context,
            "office.rag.answer.generated",
            object_id=object_id,
            version_id=search.source_version_id,
            question_hash=question_hash,
            retrieval_audit_event_id=search.audit_event_id,
            inference_audit_event_id=inference.audit_event_id,
            retrieval_policy_id=OFFICE_RAG_RETRIEVAL_POLICY_ID,
            citation_refs=[f"{citation.object_id}:{citation.version_id}" for citation in citations],
            citation_content_hashes=[citation.content_hash for citation in citations],
            citation_count=len(citations),
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            answer_supported=True,
            output_hash="sha256:" + sha256(answer.encode("utf-8")).hexdigest(),
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
            automatic_action_allowed=False,
        )
        return OfficeRagAnswerResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=search.source_version_id,
            question_hash=question_hash,
            answer=answer,
            answer_supported=True,
            confidence="source_grounded_unverified",
            citations=citations,
            citation_count=len(citations),
            retrieval_audit_event_id=search.audit_event_id,
            inference_audit_event_id=inference.audit_event_id,
            audit_event_id=audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
        )

    def _reauthorize_citation(
        self, *, user_context: UserContext, candidate: OfficeSourceSearchResult
    ) -> OfficeRagCitation:
        document = self.documents.repository.get_document(
            user_context=user_context,
            object_id=candidate.object_id,
        )
        version = self.documents.repository.get_version(
            user_context=user_context,
            object_id=document.object_id,
            version_id=candidate.version_id,
        )
        if (
            document.current_version_id != candidate.version_id
            or version.content_hash != candidate.content_hash
            or version.acl_version != candidate.acl_version
            or version.title != candidate.title
            or version.information_classification != candidate.information_classification
        ):
            raise OfficeDocumentConflictError("Office RAG source is no longer current")
        content = self.documents._read_content(document, version)
        excerpt = derive_review_quote(content, candidate.anchor)
        if excerpt is None or excerpt != candidate.source_excerpt:
            raise OfficeRagAnswerUnavailable("Office RAG source anchor no longer matches")
        return OfficeRagCitation(
            object_id=candidate.object_id,
            version_id=candidate.version_id,
            title=candidate.title,
            information_classification=candidate.information_classification,
            content_hash=candidate.content_hash,
            acl_version=candidate.acl_version,
            anchor=candidate.anchor,
            source_excerpt=excerpt,
        )

    @staticmethod
    def _source_block(citation: OfficeRagCitation) -> str:
        return (
            f'<authorized_source object_id="{citation.object_id}" version_id="{citation.version_id}">\n'
            "UNTRUSTED_SOURCE_TEXT_BEGIN\n"
            f"{citation.source_excerpt}\n"
            "UNTRUSTED_SOURCE_TEXT_END\n"
            "</authorized_source>"
        )

    @staticmethod
    def _data_class(classification: str) -> DataClass:
        return DataClass.CONFIDENTIAL if classification in {"confidential", "restricted"} else DataClass.INTERNAL

    def _local_rag_model_id(self, *, tenant_policy: TenantPolicy, data_classes: set[DataClass]) -> str:
        candidates = []
        for model_id in tenant_policy.allowed_model_ids:
            try:
                model = self.gateway.model_registry.get(model_id)
            except LookupError:
                continue
            if (
                model.deployment == "local"
                and model.provider in LOCAL_MODEL_PROVIDERS
                and Purpose.RAG in model.approved_for
                and Purpose.RAG not in model.blocked_for
                and data_classes.issubset(model.allowed_data_classes)
            ):
                candidates.append(model)
        if not candidates:
            raise PolicyViolation("Office RAG requires an admitted local model for all source classifications")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
