from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyEngine
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.rag.models import RagQuery, RagResponse, RagSource
from suite.rag.repositories import InMemoryAclAuthorizer, InMemorySourceRepository, InMemoryVectorStore


class RagPipeline:
    def __init__(
        self,
        *,
        vector_store: InMemoryVectorStore,
        source_repository: InMemorySourceRepository,
        acl_authorizer: InMemoryAclAuthorizer,
        llm_gateway: LocalLLMGateway,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.vector_store = vector_store
        self.source_repository = source_repository
        self.acl_authorizer = acl_authorizer
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
            object_id = candidate.metadata.source_object_id
            if not self.acl_authorizer.can_read(
                user_context=user_context,
                object_id=object_id,
                acl_version=candidate.metadata.acl_version,
            ):
                continue
            document = self.source_repository.get(object_id)
            allowed_sources.append(
                RagSource(
                    object_id=document.object_id,
                    version_id=document.version_id,
                    chunk_id=candidate.chunk_id,
                    title=document.title,
                    classification=document.classification,
                    access_checked=True,
                )
            )
            context_blocks.append(f"[{document.object_id}@{document.version_id}] {document.text}")

        source_object_ids = [source.object_id for source in allowed_sources]
        retrieval_audit = self.audit_logger.record(
            user_context=user_context,
            event_type="rag.retrieval",
            source_object_ids=source_object_ids,
            input_text=query.question,
            metadata={
                "candidate_count": len(candidates),
                "authorized_source_count": len(allowed_sources),
                "retrieval_policy_id": "acl_first_v1",
            },
        )

        request = InferenceRequest(
            prompt_template_id="rag_answer_v1",
            model_id="mock-summarizer",
            purpose=Purpose.RAG,
            input_text=query.question,
            data_classes={DataClass.INTERNAL},
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
            retrieval_policy_id="acl_first_v1",
            audit_event_id=retrieval_audit.event_id,
        )

