from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_redaction_contract import (
    CrmErpRedactionContractRequest,
    CrmErpRedactionContractService,
)
from suite.platform.crm_erp_search_readiness import CRM_ERP_RAG_INDEXING_FEATURE_ID
from suite.platform.crm_erp_source_citations import CrmErpSourceCitation

CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_SCHEMA_VERSION = "crm_erp_authorized_context_contract.v1"
CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_RESULT_CONTRACT = "metadata_only_authorized_context_contract_no_context"
CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_ENDPOINT = "/v1/platform/search/crm-erp/authorized-context-contract"
CRM_ERP_AUTHORIZED_CONTEXT_REQUIRED_STEPS = (
    "source_resolver_acl_trace_required",
    "source_citation_contract_required",
    "prompt_audit_contract_required",
    "redaction_contract_required",
    "exact_chunk_refs_only",
    "tenant_and_acl_revalidation_before_fetch",
    "redacted_context_hash_required",
    "authorized_context_audit_event_required",
    "no_context_body_logging",
)


class CrmErpAuthorizedContextContractRequest(CrmErpRedactionContractRequest):
    pass


class CrmErpAuthorizedContextContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_RAG_INDEXING_FEATURE_ID
    endpoint: str = CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_ENDPOINT
    requested_object_ids: tuple[str, ...]
    citations: tuple[CrmErpSourceCitation, ...]
    authorized_chunk_refs: tuple[str, ...]
    redaction_policy_id: str
    required_context_steps: tuple[str, ...] = CRM_ERP_AUTHORIZED_CONTEXT_REQUIRED_STEPS
    covered_source_data_classes: tuple[DataClass, ...]
    authorized_context_contract_hash: str
    redaction_contract_hash: str
    source_resolver_audit_event_id: str
    source_citation_contract_audit_event_id: str
    prompt_audit_contract_audit_event_id: str
    redaction_contract_audit_event_id: str
    audit_event_id: str
    redaction_contract_ready: bool
    authorized_context_contract_ready: bool
    contract_blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_RESULT_CONTRACT
    content_included: bool = False
    redacted_content_included: bool = False
    prompt_body_included: bool = False
    output_body_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    context_body_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator(
        "tenant_id",
        "module_id",
        "feature_id",
        "endpoint",
        "redaction_policy_id",
        "authorized_context_contract_hash",
        "redaction_contract_hash",
        "source_resolver_audit_event_id",
        "source_citation_contract_audit_event_id",
        "prompt_audit_contract_audit_event_id",
        "redaction_contract_audit_event_id",
        "audit_event_id",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM/ERP authorized context contract text fields must not be empty")
        return value

    @field_validator("required_context_steps", "guardrails")
    @classmethod
    def require_non_empty_text_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("CRM/ERP authorized context contract lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_authorized_context_contract(self) -> CrmErpAuthorizedContextContractResponse:
        if self.content_included or self.redacted_content_included:
            raise ValueError("CRM/ERP authorized context contract must not include source or redacted content")
        if self.prompt_body_included or self.output_body_included:
            raise ValueError("CRM/ERP authorized context contract must not include prompt or output bodies")
        if self.ai_used or self.rag_context_created or self.context_body_created:
            raise ValueError("CRM/ERP authorized context contract must not use AI or create context")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP authorized context contract must not allow side effects")
        expected_ready = (
            self.redaction_contract_ready
            and bool(self.citations)
            and bool(self.authorized_chunk_refs)
            and bool(self.covered_source_data_classes)
            and not self.contract_blocking_reasons
        )
        if self.authorized_context_contract_ready != expected_ready:
            raise ValueError("authorized_context_contract_ready must reflect complete context contract state")
        return self


class CrmErpAuthorizedContextContractService:
    def __init__(
        self,
        *,
        redaction_contract_service: CrmErpRedactionContractService,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._redaction_contract_service = redaction_contract_service
        self._audit_logger = audit_logger

    def build_contract(
        self,
        *,
        request: CrmErpAuthorizedContextContractRequest,
        user_context: UserContext,
    ) -> CrmErpAuthorizedContextContractResponse:
        redaction_contract = self._redaction_contract_service.build_contract(
            request=CrmErpRedactionContractRequest(
                object_ids=request.object_ids,
                model_id=request.model_id,
                prompt_template_id=request.prompt_template_id,
                redaction_policy_id=request.redaction_policy_id,
            ),
            user_context=user_context,
        )
        authorized_chunk_refs = tuple(_authorized_chunk_ref(citation) for citation in redaction_contract.citations)
        blocking_reasons = _blocking_reasons(
            redaction_contract_ready=redaction_contract.redaction_contract_ready,
            authorized_chunk_refs=authorized_chunk_refs,
            covered_source_data_classes=redaction_contract.covered_source_data_classes,
        )
        contract_hash = _authorized_context_contract_hash(
            tenant_id=user_context.tenant_id,
            redaction_policy_id=request.redaction_policy_id,
            authorized_chunk_refs=authorized_chunk_refs,
            covered_source_data_classes=redaction_contract.covered_source_data_classes,
            required_context_steps=CRM_ERP_AUTHORIZED_CONTEXT_REQUIRED_STEPS,
            redaction_contract_hash=redaction_contract.redaction_contract_hash,
        )
        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.authorized_context_contract",
            model_id=request.model_id,
            prompt_template_id=request.prompt_template_id,
            source_object_ids=[citation.source_object_id for citation in redaction_contract.citations],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_RAG_INDEXING_FEATURE_ID,
                "result_contract": CRM_ERP_AUTHORIZED_CONTEXT_CONTRACT_RESULT_CONTRACT,
                "redaction_policy_id": request.redaction_policy_id,
                "authorized_context_contract_hash": contract_hash,
                "redaction_contract_hash": redaction_contract.redaction_contract_hash,
                "source_resolver_audit_event_id": redaction_contract.source_resolver_audit_event_id,
                "source_citation_contract_audit_event_id": (redaction_contract.source_citation_contract_audit_event_id),
                "prompt_audit_contract_audit_event_id": redaction_contract.prompt_audit_contract_audit_event_id,
                "redaction_contract_audit_event_id": redaction_contract.audit_event_id,
                "authorized_chunk_count": len(authorized_chunk_refs),
                "covered_source_data_classes": tuple(
                    data_class.value for data_class in redaction_contract.covered_source_data_classes
                ),
                "required_context_steps": CRM_ERP_AUTHORIZED_CONTEXT_REQUIRED_STEPS,
                "contract_blocking_reasons": blocking_reasons,
                "content_included": False,
                "redacted_content_included": False,
                "prompt_body_included": False,
                "output_body_included": False,
                "ai_used": False,
                "rag_context_created": False,
                "context_body_created": False,
            },
        )
        return CrmErpAuthorizedContextContractResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=redaction_contract.requested_object_ids,
            citations=redaction_contract.citations,
            authorized_chunk_refs=authorized_chunk_refs,
            redaction_policy_id=request.redaction_policy_id,
            covered_source_data_classes=redaction_contract.covered_source_data_classes,
            authorized_context_contract_hash=contract_hash,
            redaction_contract_hash=redaction_contract.redaction_contract_hash,
            source_resolver_audit_event_id=redaction_contract.source_resolver_audit_event_id,
            source_citation_contract_audit_event_id=redaction_contract.source_citation_contract_audit_event_id,
            prompt_audit_contract_audit_event_id=redaction_contract.prompt_audit_contract_audit_event_id,
            redaction_contract_audit_event_id=redaction_contract.audit_event_id,
            audit_event_id=event.event_id,
            redaction_contract_ready=redaction_contract.redaction_contract_ready,
            authorized_context_contract_ready=not blocking_reasons,
            contract_blocking_reasons=blocking_reasons,
            guardrails=(
                "tenant_context_required",
                "server_side_redaction_contract_required",
                "exact_authorized_chunk_refs_required",
                "tenant_and_acl_revalidation_before_fetch",
                "redacted_context_hash_required",
                "no_source_or_redacted_content_returned",
                "no_prompt_or_output_body_logging",
                "no_ai_or_context_body_created",
            ),
        )


def build_crm_erp_authorized_context_contract_service(
    *,
    redaction_contract_service: CrmErpRedactionContractService,
    audit_logger: InMemoryAuditLogger,
) -> CrmErpAuthorizedContextContractService:
    return CrmErpAuthorizedContextContractService(
        redaction_contract_service=redaction_contract_service,
        audit_logger=audit_logger,
    )


def _authorized_chunk_ref(citation: CrmErpSourceCitation) -> str:
    return f"{citation.source_object_id}:{citation.source_version_id}:{citation.source_chunk_id}"


def _blocking_reasons(
    *,
    redaction_contract_ready: bool,
    authorized_chunk_refs: tuple[str, ...],
    covered_source_data_classes: tuple[DataClass, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not redaction_contract_ready:
        reasons.append("redaction_contract_not_ready")
    if not authorized_chunk_refs:
        reasons.append("authorized_context_requires_chunk_refs")
    if not covered_source_data_classes:
        reasons.append("authorized_context_requires_source_data_classes")
    return tuple(reasons)


def _authorized_context_contract_hash(
    *,
    tenant_id: str,
    redaction_policy_id: str,
    authorized_chunk_refs: tuple[str, ...],
    covered_source_data_classes: tuple[DataClass, ...],
    required_context_steps: tuple[str, ...],
    redaction_contract_hash: str,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "authorized_chunk_refs": authorized_chunk_refs,
                "covered_source_data_classes": tuple(data_class.value for data_class in covered_source_data_classes),
                "redaction_contract_hash": redaction_contract_hash,
                "redaction_policy_id": redaction_policy_id,
                "required_context_steps": required_context_steps,
                "tenant_id": tenant_id,
            }
        )
    )
