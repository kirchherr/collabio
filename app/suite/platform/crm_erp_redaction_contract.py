from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_prompt_audit_contract import (
    CrmErpPromptAuditContractRequest,
    CrmErpPromptAuditContractService,
)
from suite.platform.crm_erp_search_readiness import CRM_ERP_RAG_INDEXING_FEATURE_ID
from suite.platform.crm_erp_source_citations import CrmErpSourceCitation

CRM_ERP_REDACTION_CONTRACT_SCHEMA_VERSION = "crm_erp_redaction_contract.v1"
CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT = "metadata_only_redaction_contract_no_context"
CRM_ERP_REDACTION_CONTRACT_ENDPOINT = "/v1/platform/search/crm-erp/redaction-contract"
DEFAULT_CRM_ERP_RAG_REDACTION_POLICY_ID = "redaction-policy:crm-erp-rag-v1"
CRM_ERP_REDACTION_REQUIRED_STEPS = (
    "fetch_exact_chunks_only_after_authorized_context_gate",
    "classification_aware_redaction_required",
    "personal_data_minimization_required",
    "secret_and_credential_masking_required",
    "legal_hold_markers_preserved",
    "untrusted_source_block_wrapping_required",
    "redacted_context_hash_required",
    "redaction_audit_event_required",
)


class CrmErpRedactionContractRequest(CrmErpPromptAuditContractRequest):
    redaction_policy_id: str = DEFAULT_CRM_ERP_RAG_REDACTION_POLICY_ID

    @field_validator("redaction_policy_id")
    @classmethod
    def require_non_empty_redaction_policy(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("CRM/ERP redaction policy ID must not be empty")
        return candidate


class CrmErpRedactionContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_REDACTION_CONTRACT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_RAG_INDEXING_FEATURE_ID
    endpoint: str = CRM_ERP_REDACTION_CONTRACT_ENDPOINT
    requested_object_ids: tuple[str, ...]
    citations: tuple[CrmErpSourceCitation, ...]
    redaction_policy_id: str
    required_redaction_steps: tuple[str, ...] = CRM_ERP_REDACTION_REQUIRED_STEPS
    covered_source_data_classes: tuple[DataClass, ...]
    redaction_contract_hash: str
    prompt_audit_contract_hash: str
    source_resolver_audit_event_id: str
    source_citation_contract_audit_event_id: str
    prompt_audit_contract_audit_event_id: str
    audit_event_id: str
    prompt_audit_contract_ready: bool
    redaction_contract_ready: bool
    contract_blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT
    content_included: bool = False
    redacted_content_included: bool = False
    prompt_body_included: bool = False
    output_body_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator(
        "tenant_id",
        "module_id",
        "feature_id",
        "endpoint",
        "redaction_policy_id",
        "redaction_contract_hash",
        "prompt_audit_contract_hash",
        "source_resolver_audit_event_id",
        "source_citation_contract_audit_event_id",
        "prompt_audit_contract_audit_event_id",
        "audit_event_id",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM/ERP redaction contract text fields must not be empty")
        return value

    @field_validator("required_redaction_steps", "guardrails")
    @classmethod
    def require_non_empty_text_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("CRM/ERP redaction contract lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_redaction_contract(self) -> CrmErpRedactionContractResponse:
        if self.content_included or self.redacted_content_included:
            raise ValueError("CRM/ERP redaction contract must not include source or redacted content")
        if self.prompt_body_included or self.output_body_included:
            raise ValueError("CRM/ERP redaction contract must not include prompt or output bodies")
        if self.ai_used or self.rag_context_created:
            raise ValueError("CRM/ERP redaction contract must not use AI or create RAG context")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP redaction contract must not allow side effects")
        expected_ready = (
            self.prompt_audit_contract_ready
            and bool(self.citations)
            and bool(self.covered_source_data_classes)
            and not self.contract_blocking_reasons
        )
        if self.redaction_contract_ready != expected_ready:
            raise ValueError("redaction_contract_ready must reflect complete redaction contract state")
        return self


class CrmErpRedactionContractService:
    def __init__(
        self,
        *,
        prompt_audit_contract_service: CrmErpPromptAuditContractService,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._prompt_audit_contract_service = prompt_audit_contract_service
        self._audit_logger = audit_logger

    def build_contract(
        self,
        *,
        request: CrmErpRedactionContractRequest,
        user_context: UserContext,
    ) -> CrmErpRedactionContractResponse:
        prompt_audit_contract = self._prompt_audit_contract_service.build_contract(
            request=CrmErpPromptAuditContractRequest(
                object_ids=request.object_ids,
                model_id=request.model_id,
                prompt_template_id=request.prompt_template_id,
            ),
            user_context=user_context,
        )
        covered_source_data_classes = tuple(
            sorted(
                {citation.classification for citation in prompt_audit_contract.citations},
                key=lambda data_class: data_class.value,
            )
        )
        blocking_reasons = _blocking_reasons(
            prompt_audit_contract_ready=prompt_audit_contract.prompt_audit_contract_ready,
            citation_count=len(prompt_audit_contract.citations),
            covered_source_data_classes=covered_source_data_classes,
        )
        contract_hash = _redaction_contract_hash(
            tenant_id=user_context.tenant_id,
            redaction_policy_id=request.redaction_policy_id,
            citation_ids=tuple(citation.citation_id for citation in prompt_audit_contract.citations),
            covered_source_data_classes=covered_source_data_classes,
            required_redaction_steps=CRM_ERP_REDACTION_REQUIRED_STEPS,
            prompt_audit_contract_hash=prompt_audit_contract.prompt_audit_contract_hash,
        )
        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.redaction_contract",
            model_id=prompt_audit_contract.model_id,
            prompt_template_id=prompt_audit_contract.prompt_template_id,
            source_object_ids=[citation.source_object_id for citation in prompt_audit_contract.citations],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_RAG_INDEXING_FEATURE_ID,
                "result_contract": CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT,
                "redaction_policy_id": request.redaction_policy_id,
                "redaction_contract_hash": contract_hash,
                "prompt_audit_contract_hash": prompt_audit_contract.prompt_audit_contract_hash,
                "source_resolver_audit_event_id": prompt_audit_contract.source_resolver_audit_event_id,
                "source_citation_contract_audit_event_id": (
                    prompt_audit_contract.source_citation_contract_audit_event_id
                ),
                "prompt_audit_contract_audit_event_id": prompt_audit_contract.audit_event_id,
                "citation_count": len(prompt_audit_contract.citations),
                "covered_source_data_classes": tuple(data_class.value for data_class in covered_source_data_classes),
                "required_redaction_steps": CRM_ERP_REDACTION_REQUIRED_STEPS,
                "contract_blocking_reasons": blocking_reasons,
                "content_included": False,
                "redacted_content_included": False,
                "prompt_body_included": False,
                "output_body_included": False,
                "ai_used": False,
                "rag_context_created": False,
            },
        )
        return CrmErpRedactionContractResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=prompt_audit_contract.requested_object_ids,
            citations=prompt_audit_contract.citations,
            redaction_policy_id=request.redaction_policy_id,
            covered_source_data_classes=covered_source_data_classes,
            redaction_contract_hash=contract_hash,
            prompt_audit_contract_hash=prompt_audit_contract.prompt_audit_contract_hash,
            source_resolver_audit_event_id=prompt_audit_contract.source_resolver_audit_event_id,
            source_citation_contract_audit_event_id=prompt_audit_contract.source_citation_contract_audit_event_id,
            prompt_audit_contract_audit_event_id=prompt_audit_contract.audit_event_id,
            audit_event_id=event.event_id,
            prompt_audit_contract_ready=prompt_audit_contract.prompt_audit_contract_ready,
            redaction_contract_ready=not blocking_reasons,
            contract_blocking_reasons=blocking_reasons,
            guardrails=(
                "tenant_context_required",
                "server_side_prompt_audit_contract_required",
                "redaction_policy_id_required",
                "classification_aware_redaction_required",
                "redacted_context_hash_required",
                "no_source_or_redacted_content_returned",
                "no_prompt_or_output_body_logging",
                "no_ai_or_rag_context_created",
            ),
        )


def build_crm_erp_redaction_contract_service(
    *,
    prompt_audit_contract_service: CrmErpPromptAuditContractService,
    audit_logger: InMemoryAuditLogger,
) -> CrmErpRedactionContractService:
    return CrmErpRedactionContractService(
        prompt_audit_contract_service=prompt_audit_contract_service,
        audit_logger=audit_logger,
    )


def _blocking_reasons(
    *,
    prompt_audit_contract_ready: bool,
    citation_count: int,
    covered_source_data_classes: tuple[DataClass, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not prompt_audit_contract_ready:
        reasons.append("prompt_audit_contract_not_ready")
    if citation_count < 1:
        reasons.append("redaction_requires_authorized_citations")
    if not covered_source_data_classes:
        reasons.append("redaction_requires_source_data_classes")
    return tuple(reasons)


def _redaction_contract_hash(
    *,
    tenant_id: str,
    redaction_policy_id: str,
    citation_ids: tuple[str, ...],
    covered_source_data_classes: tuple[DataClass, ...],
    required_redaction_steps: tuple[str, ...],
    prompt_audit_contract_hash: str,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "citation_ids": citation_ids,
                "covered_source_data_classes": tuple(data_class.value for data_class in covered_source_data_classes),
                "prompt_audit_contract_hash": prompt_audit_contract_hash,
                "redaction_policy_id": redaction_policy_id,
                "required_redaction_steps": required_redaction_steps,
                "tenant_id": tenant_id,
            }
        )
    )
