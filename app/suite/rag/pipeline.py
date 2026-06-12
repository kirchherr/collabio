from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, TenantPolicy, UserContext
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.rag.models import RagQuery, RagResponse, RagSource
from suite.rag.repositories import AuthorizedChunkRepository, VectorStore


def render_authorized_source_block(document_id: str, version_id: str, chunk_id: str, text: str) -> str:
    return (
        f'<authorized_source object_id="{document_id}" version_id="{version_id}" chunk_id="{chunk_id}">\n'
        "UNTRUSTED_SOURCE_TEXT_BEGIN\n"
        f"{text}\n"
        "UNTRUSTED_SOURCE_TEXT_END\n"
        "</authorized_source>"
    )


class RagPipeline:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        chunk_repository: AuthorizedChunkRepository,
        llm_gateway: LocalLLMGateway,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.vector_store = vector_store
        self.chunk_repository = chunk_repository
        self.llm_gateway = llm_gateway
        self.audit_logger = audit_logger

    def answer(
        self,
        *,
        query: RagQuery,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
    ) -> RagResponse:
        self.llm_gateway.policy_engine.authorize_rag(
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        candidates = self.vector_store.search(
            tenant_id=user_context.tenant_id,
            query=query.question,
            top_k=query.top_k,
        )
        allowed_sources: list[RagSource] = []
        context_blocks: list[str] = []
        for candidate in candidates:
            chunk = self.chunk_repository.get_authorized_chunk(user_context=user_context, candidate=candidate)
            if chunk is None:
                continue
            metadata = chunk.metadata
            allowed_sources.append(
                RagSource(
                    object_id=metadata.source_object_id,
                    version_id=metadata.source_version_id,
                    chunk_id=metadata.chunk_id,
                    title=chunk.title,
                    classification=metadata.classification,
                    access_checked=True,
                )
            )
            context_blocks.append(
                render_authorized_source_block(
                    document_id=metadata.source_object_id,
                    version_id=metadata.source_version_id,
                    chunk_id=metadata.chunk_id,
                    text=chunk.text,
                )
            )

        source_object_ids = unique_source_object_ids(allowed_sources)
        authorized_chunk_refs = [
            f"{source.object_id}:{source.version_id}:{source.chunk_id}" for source in allowed_sources
        ]
        context_data_classes = {source.classification for source in allowed_sources}
        retrieval_audit = self.audit_logger.record(
            user_context=user_context,
            event_type="rag.retrieval",
            source_object_ids=source_object_ids,
            input_text=query.question,
            metadata={
                "candidate_count": len(candidates),
                "authorized_source_count": len(allowed_sources),
                "authorized_chunk_count": len(allowed_sources),
                "authorized_chunk_refs": authorized_chunk_refs,
                "authorized_source_data_classes": sorted(data_class.value for data_class in context_data_classes),
                "retrieval_policy_id": "authorized_chunk_v1",
            },
        )

        request = InferenceRequest(
            prompt_template_id="rag_answer_v1",
            model_id="mock-summarizer",
            purpose=Purpose.RAG,
            input_text=query.question,
            data_classes={DataClass.AI_PROMPT, *context_data_classes},
            source_object_ids=source_object_ids,
        )
        response = self.llm_gateway.infer(
            request=request,
            user_context=user_context,
            tenant_policy=tenant_policy,
            sources_text="\n".join(context_blocks),
        )
        return RagResponse(
            answer=response.answer,
            confidence="medium" if allowed_sources else "low",
            sources=allowed_sources,
            model_id=response.model_id,
            prompt_template_id=response.prompt_template_id,
            retrieval_policy_id="authorized_chunk_v1",
            audit_event_id=retrieval_audit.event_id,
        )


def unique_source_object_ids(sources: list[RagSource]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in sources:
        if source.object_id in seen:
            continue
        seen.add(source.object_id)
        ordered.append(source.object_id)
    return ordered
