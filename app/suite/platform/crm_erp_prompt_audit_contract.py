from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, Purpose, UserContext
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_search_readiness import CRM_ERP_RAG_INDEXING_FEATURE_ID
from suite.platform.crm_erp_source_citations import (
    CrmErpSourceCitation,
    CrmErpSourceCitationContractRequest,
    CrmErpSourceCitationContractService,
)

CRM_ERP_PROMPT_AUDIT_CONTRACT_SCHEMA_VERSION = "crm_erp_prompt_audit_contract.v1"
CRM_ERP_PROMPT_AUDIT_CONTRACT_RESULT_CONTRACT = "metadata_only_prompt_audit_contract_no_context"
CRM_ERP_PROMPT_AUDIT_CONTRACT_ENDPOINT = "/v1/platform/search/crm-erp/prompt-audit-contract"
CRM_ERP_PROMPT_AUDIT_EVENT_TYPE = "ai.inference"
DEFAULT_CRM_ERP_RAG_MODEL_ID = "mock-summarizer"
DEFAULT_CRM_ERP_RAG_PROMPT_TEMPLATE_ID = "rag_answer_v1"
PROMPT_AUDIT_REQUIRED_EVENT_FIELDS = (
    "tenant_id",
    "user_id",
    "event_type",
    "model_id",
    "prompt_template_id",
    "source_object_ids",
    "input_hash",
    "output_hash",
    "metadata",
)
PROMPT_AUDIT_REQUIRED_METADATA_FIELDS = (
    "purpose",
    "risk_level",
    "retrieval_audit_event_id",
    "source_citation_contract_audit_event_id",
    "authorized_chunk_refs",
    "authorized_source_data_classes",
    "context_hash",
    "tool_call_hashes",
    "redaction_policy_id",
)


class CrmErpPromptAuditContractRequest(CrmErpSourceCitationContractRequest):
    model_id: str = DEFAULT_CRM_ERP_RAG_MODEL_ID
    prompt_template_id: str = DEFAULT_CRM_ERP_RAG_PROMPT_TEMPLATE_ID

    @field_validator("model_id", "prompt_template_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("CRM/ERP prompt audit contract fields must not be empty")
        return candidate


class CrmErpPromptAuditContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_PROMPT_AUDIT_CONTRACT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_RAG_INDEXING_FEATURE_ID
    endpoint: str = CRM_ERP_PROMPT_AUDIT_CONTRACT_ENDPOINT
    requested_object_ids: tuple[str, ...]
    citations: tuple[CrmErpSourceCitation, ...]
    model_id: str
    model_provider: str
    model_checksum: str
    model_approved_for_rag: bool
    prompt_template_id: str
    prompt_template_version: str
    prompt_template_approval_status: str
    prompt_template_requires_sources: bool
    prompt_template_allows_ai_prompt_data_class: bool
    required_event_type: str = CRM_ERP_PROMPT_AUDIT_EVENT_TYPE
    required_event_fields: tuple[str, ...] = PROMPT_AUDIT_REQUIRED_EVENT_FIELDS
    required_metadata_fields: tuple[str, ...] = PROMPT_AUDIT_REQUIRED_METADATA_FIELDS
    prompt_audit_contract_hash: str
    source_resolver_audit_event_id: str
    source_citation_contract_audit_event_id: str
    audit_event_id: str
    source_citation_contract_ready: bool
    prompt_audit_contract_ready: bool
    contract_blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_PROMPT_AUDIT_CONTRACT_RESULT_CONTRACT
    content_included: bool = False
    prompt_body_included: bool = False
    output_body_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    normal_application_body_logging_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator(
        "tenant_id",
        "module_id",
        "feature_id",
        "endpoint",
        "model_id",
        "model_provider",
        "model_checksum",
        "prompt_template_id",
        "prompt_template_version",
        "prompt_template_approval_status",
        "required_event_type",
        "prompt_audit_contract_hash",
        "source_resolver_audit_event_id",
        "source_citation_contract_audit_event_id",
        "audit_event_id",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM/ERP prompt audit contract text fields must not be empty")
        return value

    @field_validator("required_event_fields", "required_metadata_fields", "guardrails")
    @classmethod
    def require_non_empty_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("CRM/ERP prompt audit contract lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_prompt_audit_contract(self) -> CrmErpPromptAuditContractResponse:
        if self.content_included or self.prompt_body_included or self.output_body_included:
            raise ValueError("CRM/ERP prompt audit contract must not include source, prompt, or output bodies")
        if self.ai_used or self.rag_context_created:
            raise ValueError("CRM/ERP prompt audit contract must not use AI or create RAG context")
        if self.normal_application_body_logging_allowed:
            raise ValueError("CRM/ERP prompt audit contract must not allow body logging")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP prompt audit contract must not allow side effects")
        expected_ready = (
            self.source_citation_contract_ready
            and self.model_approved_for_rag
            and self.prompt_template_approval_status == "approved"
            and self.prompt_template_requires_sources
            and self.prompt_template_allows_ai_prompt_data_class
            and not self.contract_blocking_reasons
        )
        if self.prompt_audit_contract_ready != expected_ready:
            raise ValueError("prompt_audit_contract_ready must reflect the complete audit contract state")
        return self


class CrmErpPromptAuditContractService:
    def __init__(
        self,
        *,
        source_citation_contract_service: CrmErpSourceCitationContractService,
        model_registry: InMemoryModelRegistry,
        prompt_registry: InMemoryPromptRegistry,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._source_citation_contract_service = source_citation_contract_service
        self._model_registry = model_registry
        self._prompt_registry = prompt_registry
        self._audit_logger = audit_logger

    def build_contract(
        self,
        *,
        request: CrmErpPromptAuditContractRequest,
        user_context: UserContext,
    ) -> CrmErpPromptAuditContractResponse:
        citation_contract = self._source_citation_contract_service.build_contract(
            request=CrmErpSourceCitationContractRequest(object_ids=request.object_ids),
            user_context=user_context,
        )
        model = self._model_registry.get(request.model_id)
        prompt_template = self._prompt_registry.get(request.prompt_template_id)
        model_approved_for_rag = Purpose.RAG in model.approved_for and Purpose.RAG not in model.blocked_for
        prompt_template_requires_sources = prompt_template.required_sources
        prompt_template_allows_ai_prompt_data_class = DataClass.AI_PROMPT in prompt_template.allowed_data_classes
        blocking_reasons = _blocking_reasons(
            source_citation_contract_ready=citation_contract.source_citation_contract_ready,
            model_approved_for_rag=model_approved_for_rag,
            prompt_template_approval_status=prompt_template.approval_status,
            prompt_template_requires_sources=prompt_template_requires_sources,
            prompt_template_allows_ai_prompt_data_class=prompt_template_allows_ai_prompt_data_class,
        )
        contract_hash = _prompt_audit_contract_hash(
            tenant_id=user_context.tenant_id,
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            prompt_template_version=prompt_template.version,
            citation_ids=tuple(citation.citation_id for citation in citation_contract.citations),
            source_citation_contract_audit_event_id=citation_contract.audit_event_id,
            required_event_fields=PROMPT_AUDIT_REQUIRED_EVENT_FIELDS,
            required_metadata_fields=PROMPT_AUDIT_REQUIRED_METADATA_FIELDS,
        )
        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.prompt_audit_contract",
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            source_object_ids=[citation.source_object_id for citation in citation_contract.citations],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_RAG_INDEXING_FEATURE_ID,
                "result_contract": CRM_ERP_PROMPT_AUDIT_CONTRACT_RESULT_CONTRACT,
                "required_event_type": CRM_ERP_PROMPT_AUDIT_EVENT_TYPE,
                "prompt_audit_contract_hash": contract_hash,
                "source_resolver_audit_event_id": citation_contract.source_resolver_audit_event_id,
                "source_citation_contract_audit_event_id": citation_contract.audit_event_id,
                "citation_count": len(citation_contract.citations),
                "model_approved_for_rag": model_approved_for_rag,
                "prompt_template_approval_status": prompt_template.approval_status,
                "prompt_template_requires_sources": prompt_template_requires_sources,
                "contract_blocking_reasons": blocking_reasons,
                "content_included": False,
                "prompt_body_included": False,
                "output_body_included": False,
                "ai_used": False,
                "rag_context_created": False,
            },
        )
        return CrmErpPromptAuditContractResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=citation_contract.requested_object_ids,
            citations=citation_contract.citations,
            model_id=model.model_id,
            model_provider=model.provider,
            model_checksum=model.checksum,
            model_approved_for_rag=model_approved_for_rag,
            prompt_template_id=prompt_template.prompt_template_id,
            prompt_template_version=prompt_template.version,
            prompt_template_approval_status=prompt_template.approval_status,
            prompt_template_requires_sources=prompt_template_requires_sources,
            prompt_template_allows_ai_prompt_data_class=prompt_template_allows_ai_prompt_data_class,
            prompt_audit_contract_hash=contract_hash,
            source_resolver_audit_event_id=citation_contract.source_resolver_audit_event_id,
            source_citation_contract_audit_event_id=citation_contract.audit_event_id,
            audit_event_id=event.event_id,
            source_citation_contract_ready=citation_contract.source_citation_contract_ready,
            prompt_audit_contract_ready=not blocking_reasons,
            contract_blocking_reasons=blocking_reasons,
            guardrails=(
                "tenant_context_required",
                "server_side_source_citation_contract_required",
                "registered_rag_model_required",
                "approved_source_required_prompt_template_required",
                "prompt_and_output_hashes_required",
                "context_hash_required",
                "tool_call_hashes_required",
                "no_prompt_or_output_body_logging",
                "no_ai_or_rag_context_created",
            ),
        )


def build_crm_erp_prompt_audit_contract_service(
    *,
    source_citation_contract_service: CrmErpSourceCitationContractService,
    model_registry: InMemoryModelRegistry,
    prompt_registry: InMemoryPromptRegistry,
    audit_logger: InMemoryAuditLogger,
) -> CrmErpPromptAuditContractService:
    return CrmErpPromptAuditContractService(
        source_citation_contract_service=source_citation_contract_service,
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        audit_logger=audit_logger,
    )


def _blocking_reasons(
    *,
    source_citation_contract_ready: bool,
    model_approved_for_rag: bool,
    prompt_template_approval_status: str,
    prompt_template_requires_sources: bool,
    prompt_template_allows_ai_prompt_data_class: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not source_citation_contract_ready:
        reasons.append("source_citation_contract_not_ready")
    if not model_approved_for_rag:
        reasons.append("model_not_approved_for_rag")
    if prompt_template_approval_status != "approved":
        reasons.append("prompt_template_not_approved")
    if not prompt_template_requires_sources:
        reasons.append("prompt_template_sources_not_required")
    if not prompt_template_allows_ai_prompt_data_class:
        reasons.append("prompt_template_ai_prompt_data_class_not_allowed")
    return tuple(reasons)


def _prompt_audit_contract_hash(
    *,
    tenant_id: str,
    model_id: str,
    prompt_template_id: str,
    prompt_template_version: str,
    citation_ids: tuple[str, ...],
    source_citation_contract_audit_event_id: str,
    required_event_fields: tuple[str, ...],
    required_metadata_fields: tuple[str, ...],
) -> str:
    return stable_hash(
        canonical_json(
            {
                "citation_ids": citation_ids,
                "model_id": model_id,
                "prompt_template_id": prompt_template_id,
                "prompt_template_version": prompt_template_version,
                "required_event_fields": required_event_fields,
                "required_metadata_fields": required_metadata_fields,
                "source_citation_contract_audit_event_id": source_citation_contract_audit_event_id,
                "tenant_id": tenant_id,
            }
        )
    )
