from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_search import CRM_ERP_SEARCH_FEATURE_ID
from suite.platform.crm_erp_source_resolver import (
    CrmErpResolvedSourceRef,
    CrmErpSourceResolverAclTraceRequest,
    CrmErpSourceResolverAclTraceService,
)

CRM_ERP_SOURCE_CITATION_CONTRACT_SCHEMA_VERSION = "crm_erp_source_citation_contract.v1"
CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT = "metadata_only_source_citation_contract_no_context"
CRM_ERP_SOURCE_CITATION_CONTRACT_ENDPOINT = "/v1/platform/search/crm-erp/source-citation-contract"


class CrmErpSourceCitationContractRequest(CrmErpSourceResolverAclTraceRequest):
    pass


class CrmErpSourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    citation_id: str
    source_object_id: str
    source_object_type: str
    source_version_id: str
    source_chunk_id: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    acl_version: int
    acl_hash: str
    content_hash: str
    access_checked: bool = True
    authorized: bool = True

    @model_validator(mode="after")
    def require_authorized_metadata_ref(self) -> CrmErpSourceCitation:
        required_text = (
            self.tenant_id,
            self.citation_id,
            self.source_object_id,
            self.source_object_type,
            self.source_version_id,
            self.source_chunk_id,
            self.retention_policy_id,
            self.legal_hold_state,
            self.acl_hash,
            self.content_hash,
        )
        if any(not value.strip() for value in required_text):
            raise ValueError("source citation metadata fields must not be empty")
        if not self.access_checked or not self.authorized:
            raise ValueError("source citations require authorized ACL-checked refs")
        return self


class CrmErpSourceCitationContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_SOURCE_CITATION_CONTRACT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_SEARCH_FEATURE_ID
    endpoint: str = CRM_ERP_SOURCE_CITATION_CONTRACT_ENDPOINT
    requested_object_ids: tuple[str, ...]
    citations: tuple[CrmErpSourceCitation, ...]
    blocked_source_object_ids: tuple[str, ...]
    unresolved_source_object_ids: tuple[str, ...]
    candidate_count: int
    citation_count: int
    blocked_count: int
    unresolved_count: int
    source_resolver_acl_trace_ready: bool
    source_citation_contract_ready: bool
    source_resolver_audit_event_id: str
    audit_event_id: str
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT
    content_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @model_validator(mode="after")
    def require_metadata_only_citation_contract(self) -> CrmErpSourceCitationContractResponse:
        if self.content_included or self.ai_used or self.rag_context_created:
            raise ValueError("CRM/ERP source citation contract must not include content, AI, or RAG context")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP source citation contract must not allow side effects")
        if self.candidate_count != len(self.requested_object_ids):
            raise ValueError("candidate_count must match requested object IDs")
        if self.citation_count != len(self.citations):
            raise ValueError("citation_count must match citations")
        if self.blocked_count != len(self.blocked_source_object_ids):
            raise ValueError("blocked_count must match blocked source object IDs")
        if self.unresolved_count != len(self.unresolved_source_object_ids):
            raise ValueError("unresolved_count must match unresolved source object IDs")
        if any(citation.tenant_id != self.tenant_id for citation in self.citations):
            raise ValueError("source citations must match the response tenant")
        expected_ready = (
            self.source_resolver_acl_trace_ready
            and self.candidate_count > 0
            and self.citation_count == self.candidate_count
            and self.blocked_count == 0
            and self.unresolved_count == 0
        )
        if self.source_citation_contract_ready != expected_ready:
            raise ValueError("source_citation_contract_ready must reflect citation completeness")
        return self


class CrmErpSourceCitationContractService:
    def __init__(
        self,
        *,
        source_resolver_acl_trace_service: CrmErpSourceResolverAclTraceService,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._source_resolver_acl_trace_service = source_resolver_acl_trace_service
        self._audit_logger = audit_logger

    def build_contract(
        self,
        *,
        request: CrmErpSourceCitationContractRequest,
        user_context: UserContext,
    ) -> CrmErpSourceCitationContractResponse:
        trace = self._source_resolver_acl_trace_service.build_trace(
            request=CrmErpSourceResolverAclTraceRequest(object_ids=request.object_ids),
            user_context=user_context,
        )
        citations = tuple(_citation_from_resolved_source_ref(source) for source in trace.resolved_source_refs)
        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.source_citation_contract",
            source_object_ids=[citation.source_object_id for citation in citations],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_SEARCH_FEATURE_ID,
                "result_contract": CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT,
                "source_resolver_audit_event_id": trace.audit_event_id,
                "candidate_count": trace.candidate_count,
                "citation_count": len(citations),
                "blocked_count": trace.blocked_count,
                "unresolved_count": trace.unresolved_count,
                "content_included": False,
                "ai_used": False,
                "rag_context_created": False,
            },
        )
        return CrmErpSourceCitationContractResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=trace.requested_object_ids,
            citations=citations,
            blocked_source_object_ids=trace.blocked_source_object_ids,
            unresolved_source_object_ids=trace.unresolved_source_object_ids,
            candidate_count=trace.candidate_count,
            citation_count=len(citations),
            blocked_count=trace.blocked_count,
            unresolved_count=trace.unresolved_count,
            source_resolver_acl_trace_ready=trace.source_resolver_acl_trace_ready,
            source_citation_contract_ready=(
                trace.source_resolver_acl_trace_ready
                and trace.candidate_count > 0
                and len(citations) == trace.candidate_count
            ),
            source_resolver_audit_event_id=trace.audit_event_id,
            audit_event_id=event.event_id,
            guardrails=(
                "tenant_context_required",
                "server_side_source_resolution_required",
                "authoritative_acl_validation_required",
                "source_object_id_required",
                "source_version_id_required",
                "source_chunk_id_required",
                "blocked_refs_exclude_metadata",
                "no_raw_source_payload_fields",
                "no_rag_context_created",
            ),
        )


def build_crm_erp_source_citation_contract_service(
    *,
    source_resolver_acl_trace_service: CrmErpSourceResolverAclTraceService,
    audit_logger: InMemoryAuditLogger,
) -> CrmErpSourceCitationContractService:
    return CrmErpSourceCitationContractService(
        source_resolver_acl_trace_service=source_resolver_acl_trace_service,
        audit_logger=audit_logger,
    )


def _citation_from_resolved_source_ref(source: CrmErpResolvedSourceRef) -> CrmErpSourceCitation:
    return CrmErpSourceCitation(
        tenant_id=source.tenant_id,
        citation_id=f"{source.object_id}:{source.version_id}:{source.chunk_id}",
        source_object_id=source.object_id,
        source_object_type=source.object_type,
        source_version_id=source.version_id,
        source_chunk_id=source.chunk_id,
        classification=source.classification,
        retention_policy_id=source.retention_policy_id,
        legal_hold_state=source.legal_hold_state,
        acl_version=source.acl_version,
        acl_hash=source.acl_hash,
        content_hash=source.content_hash,
    )
