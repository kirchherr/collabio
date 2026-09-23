from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import (
    DataClass,
    InferenceRequest,
    PromptTemplate,
    Purpose,
    RiskLevel,
    TenantPolicy,
    UserContext,
)
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_authorized_context_contract import (
    CrmErpAuthorizedContextContractRequest,
    CrmErpAuthorizedContextContractService,
)
from suite.platform.crm_erp_prompt_audit_contract import CRM_ERP_PROMPT_AUDIT_EVENT_TYPE
from suite.platform.crm_erp_search_readiness import CRM_ERP_RAG_INDEXING_FEATURE_ID
from suite.platform.crm_erp_source_citations import CrmErpSourceCitation

CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_SCHEMA_VERSION = "crm_erp_inference_execution_boundary.v1"
CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT = "metadata_only_inference_execution_boundary_no_prompt"
CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_ENDPOINT = "/v1/platform/search/crm-erp/inference-execution-boundary"
CRM_ERP_INFERENCE_EXECUTION_REQUIRED_STEPS = (
    "authorized_context_contract_required",
    "tenant_ai_policy_required",
    "tenant_rag_policy_required",
    "model_policy_required",
    "prompt_template_policy_required",
    "source_object_acl_revalidation_required",
    "input_hash_required",
    "output_hash_required",
    "tool_call_hashes_required",
    "source_citations_required",
    "llm_output_validation_required",
    "no_destructive_or_external_side_effects",
    "human_confirmation_required_for_high_risk",
)
INFERENCE_BOUNDARY_PLACEHOLDER_INPUT = "[metadata-only CRM/ERP inference boundary: prompt body not captured]"


class CrmErpInferenceExecutionBoundaryRequest(CrmErpAuthorizedContextContractRequest):
    risk_level: RiskLevel = RiskLevel.MEDIUM
    human_confirmation_ref: str | None = None

    @field_validator("human_confirmation_ref")
    @classmethod
    def normalize_human_confirmation_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        if not candidate:
            raise ValueError("human confirmation ref must not be empty when supplied")
        return candidate


class CrmErpInferenceExecutionBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_RAG_INDEXING_FEATURE_ID
    endpoint: str = CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_ENDPOINT
    requested_object_ids: tuple[str, ...]
    citations: tuple[CrmErpSourceCitation, ...]
    authorized_chunk_refs: tuple[str, ...]
    model_id: str
    model_provider: str
    model_checksum: str
    model_approved_for_rag: bool
    prompt_template_id: str
    prompt_template_version: str
    prompt_template_approval_status: str
    tenant_ai_enabled: bool
    tenant_rag_enabled: bool
    external_ai_enabled: bool
    risk_level: RiskLevel
    purpose: Purpose = Purpose.RAG
    inference_data_classes: tuple[DataClass, ...]
    required_event_type: str = CRM_ERP_PROMPT_AUDIT_EVENT_TYPE
    required_inference_steps: tuple[str, ...] = CRM_ERP_INFERENCE_EXECUTION_REQUIRED_STEPS
    authorized_context_contract_hash: str
    inference_execution_boundary_hash: str
    source_resolver_audit_event_id: str
    source_citation_contract_audit_event_id: str
    prompt_audit_contract_audit_event_id: str
    redaction_contract_audit_event_id: str
    authorized_context_contract_audit_event_id: str
    audit_event_id: str
    authorized_context_contract_ready: bool
    policy_authorized: bool
    human_confirmation_required: bool
    human_confirmation_ref: str | None = None
    inference_execution_boundary_ready: bool
    contract_blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT
    local_llm_gateway_required: bool = True
    tool_calls_allowed: bool = False
    provider_call_executed: bool = False
    answer_generation_executed: bool = False
    content_included: bool = False
    redacted_content_included: bool = False
    context_body_created: bool = False
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
        "model_id",
        "model_provider",
        "model_checksum",
        "prompt_template_id",
        "prompt_template_version",
        "prompt_template_approval_status",
        "required_event_type",
        "authorized_context_contract_hash",
        "inference_execution_boundary_hash",
        "source_resolver_audit_event_id",
        "source_citation_contract_audit_event_id",
        "prompt_audit_contract_audit_event_id",
        "redaction_contract_audit_event_id",
        "authorized_context_contract_audit_event_id",
        "audit_event_id",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM/ERP inference execution boundary text fields must not be empty")
        return value

    @field_validator("required_inference_steps", "guardrails")
    @classmethod
    def require_non_empty_text_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("CRM/ERP inference execution boundary lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_inference_boundary(self) -> CrmErpInferenceExecutionBoundaryResponse:
        if self.content_included or self.redacted_content_included:
            raise ValueError("CRM/ERP inference execution boundary must not include source or redacted content")
        if self.context_body_created or self.prompt_body_included or self.output_body_included:
            raise ValueError("CRM/ERP inference execution boundary must not create context, prompt, or output bodies")
        if self.ai_used or self.provider_call_executed or self.answer_generation_executed or self.rag_context_created:
            raise ValueError("CRM/ERP inference execution boundary must not execute AI or RAG")
        if self.tool_calls_allowed or self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP inference execution boundary must not allow tools or side effects")
        expected_ready = (
            self.authorized_context_contract_ready
            and self.policy_authorized
            and bool(self.citations)
            and bool(self.authorized_chunk_refs)
            and bool(self.inference_data_classes)
            and not self.contract_blocking_reasons
        )
        if self.inference_execution_boundary_ready != expected_ready:
            raise ValueError("inference_execution_boundary_ready must reflect complete boundary state")
        return self


class CrmErpInferenceExecutionBoundaryService:
    def __init__(
        self,
        *,
        authorized_context_contract_service: CrmErpAuthorizedContextContractService,
        model_registry: InMemoryModelRegistry,
        prompt_registry: InMemoryPromptRegistry,
        policy_engine: PolicyEngine,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._authorized_context_contract_service = authorized_context_contract_service
        self._model_registry = model_registry
        self._prompt_registry = prompt_registry
        self._policy_engine = policy_engine
        self._audit_logger = audit_logger

    def build_boundary(
        self,
        *,
        request: CrmErpInferenceExecutionBoundaryRequest,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
    ) -> CrmErpInferenceExecutionBoundaryResponse:
        authorized_context = self._authorized_context_contract_service.build_contract(
            request=CrmErpAuthorizedContextContractRequest(
                object_ids=request.object_ids,
                model_id=request.model_id,
                prompt_template_id=request.prompt_template_id,
                redaction_policy_id=request.redaction_policy_id,
            ),
            user_context=user_context,
        )
        model = self._model_registry.get(request.model_id)
        prompt_template = self._prompt_registry.get(request.prompt_template_id)
        source_object_ids = _unique_source_object_ids(authorized_context.citations)
        inference_data_classes = tuple(
            sorted(
                {DataClass.AI_PROMPT, *authorized_context.covered_source_data_classes},
                key=lambda data_class: data_class.value,
            )
        )
        policy_authorized, policy_blocking_reasons = _policy_authorization(
            policy_engine=self._policy_engine,
            model_id=request.model_id,
            prompt_template_id=request.prompt_template_id,
            source_object_ids=source_object_ids,
            inference_data_classes=inference_data_classes,
            risk_level=request.risk_level,
            prompt_template=prompt_template,
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        human_confirmation_required = self._policy_engine.requires_human_approval(
            InferenceRequest(
                prompt_template_id=request.prompt_template_id,
                model_id=request.model_id,
                purpose=Purpose.RAG,
                input_text=INFERENCE_BOUNDARY_PLACEHOLDER_INPUT,
                data_classes=set(inference_data_classes),
                source_object_ids=list(source_object_ids),
                risk_level=request.risk_level,
            ),
            tenant_policy,
        )
        blocking_reasons = _blocking_reasons(
            authorized_context_contract_ready=authorized_context.authorized_context_contract_ready,
            policy_blocking_reasons=policy_blocking_reasons,
            human_confirmation_required=human_confirmation_required,
            human_confirmation_ref=request.human_confirmation_ref,
            citation_count=len(authorized_context.citations),
            authorized_chunk_count=len(authorized_context.authorized_chunk_refs),
            inference_data_classes=inference_data_classes,
        )
        boundary_hash = _inference_execution_boundary_hash(
            tenant_id=user_context.tenant_id,
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            prompt_template_version=prompt_template.version,
            risk_level=request.risk_level,
            inference_data_classes=inference_data_classes,
            source_object_ids=source_object_ids,
            authorized_context_contract_hash=authorized_context.authorized_context_contract_hash,
            human_confirmation_ref=request.human_confirmation_ref,
            required_inference_steps=CRM_ERP_INFERENCE_EXECUTION_REQUIRED_STEPS,
        )
        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.inference_execution_boundary",
            model_id=model.model_id,
            prompt_template_id=prompt_template.prompt_template_id,
            source_object_ids=list(source_object_ids),
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_RAG_INDEXING_FEATURE_ID,
                "result_contract": CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT,
                "required_event_type": CRM_ERP_PROMPT_AUDIT_EVENT_TYPE,
                "model_provider": model.provider,
                "model_checksum": model.checksum,
                "prompt_template_version": prompt_template.version,
                "prompt_template_approval_status": prompt_template.approval_status,
                "tenant_ai_enabled": tenant_policy.ai_enabled,
                "tenant_rag_enabled": tenant_policy.rag_enabled,
                "external_ai_enabled": tenant_policy.external_ai_enabled,
                "risk_level": request.risk_level.value,
                "purpose": Purpose.RAG.value,
                "inference_data_classes": tuple(data_class.value for data_class in inference_data_classes),
                "authorized_context_contract_hash": authorized_context.authorized_context_contract_hash,
                "inference_execution_boundary_hash": boundary_hash,
                "source_resolver_audit_event_id": authorized_context.source_resolver_audit_event_id,
                "source_citation_contract_audit_event_id": authorized_context.source_citation_contract_audit_event_id,
                "prompt_audit_contract_audit_event_id": authorized_context.prompt_audit_contract_audit_event_id,
                "redaction_contract_audit_event_id": authorized_context.redaction_contract_audit_event_id,
                "authorized_context_contract_audit_event_id": authorized_context.audit_event_id,
                "authorized_chunk_count": len(authorized_context.authorized_chunk_refs),
                "policy_authorized": policy_authorized,
                "human_confirmation_required": human_confirmation_required,
                "human_confirmation_ref_present": request.human_confirmation_ref is not None,
                "contract_blocking_reasons": blocking_reasons,
                "provider_call_executed": False,
                "answer_generation_executed": False,
                "content_included": False,
                "redacted_content_included": False,
                "context_body_created": False,
                "prompt_body_included": False,
                "output_body_included": False,
                "ai_used": False,
                "rag_context_created": False,
            },
        )
        return CrmErpInferenceExecutionBoundaryResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=authorized_context.requested_object_ids,
            citations=authorized_context.citations,
            authorized_chunk_refs=authorized_context.authorized_chunk_refs,
            model_id=model.model_id,
            model_provider=model.provider,
            model_checksum=model.checksum,
            model_approved_for_rag=Purpose.RAG in model.approved_for and Purpose.RAG not in model.blocked_for,
            prompt_template_id=prompt_template.prompt_template_id,
            prompt_template_version=prompt_template.version,
            prompt_template_approval_status=prompt_template.approval_status,
            tenant_ai_enabled=tenant_policy.ai_enabled and tenant_policy.tenant_id == user_context.tenant_id,
            tenant_rag_enabled=tenant_policy.rag_enabled and tenant_policy.tenant_id == user_context.tenant_id,
            external_ai_enabled=tenant_policy.external_ai_enabled,
            risk_level=request.risk_level,
            inference_data_classes=inference_data_classes,
            authorized_context_contract_hash=authorized_context.authorized_context_contract_hash,
            inference_execution_boundary_hash=boundary_hash,
            source_resolver_audit_event_id=authorized_context.source_resolver_audit_event_id,
            source_citation_contract_audit_event_id=authorized_context.source_citation_contract_audit_event_id,
            prompt_audit_contract_audit_event_id=authorized_context.prompt_audit_contract_audit_event_id,
            redaction_contract_audit_event_id=authorized_context.redaction_contract_audit_event_id,
            authorized_context_contract_audit_event_id=authorized_context.audit_event_id,
            audit_event_id=event.event_id,
            authorized_context_contract_ready=authorized_context.authorized_context_contract_ready,
            policy_authorized=policy_authorized,
            human_confirmation_required=human_confirmation_required,
            human_confirmation_ref=request.human_confirmation_ref,
            inference_execution_boundary_ready=not blocking_reasons,
            contract_blocking_reasons=blocking_reasons,
            guardrails=(
                "tenant_context_required",
                "authorized_context_contract_required",
                "tenant_ai_and_rag_policy_required",
                "registered_rag_model_required",
                "approved_source_required_prompt_template_required",
                "inference_data_classes_derived_from_authorized_sources",
                "input_and_output_hashes_required_for_future_inference",
                "no_prompt_or_output_body_logging",
                "no_provider_call_or_answer_generation",
                "no_tools_or_side_effects",
            ),
        )


def build_crm_erp_inference_execution_boundary_service(
    *,
    authorized_context_contract_service: CrmErpAuthorizedContextContractService,
    model_registry: InMemoryModelRegistry,
    prompt_registry: InMemoryPromptRegistry,
    policy_engine: PolicyEngine,
    audit_logger: InMemoryAuditLogger,
) -> CrmErpInferenceExecutionBoundaryService:
    return CrmErpInferenceExecutionBoundaryService(
        authorized_context_contract_service=authorized_context_contract_service,
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        policy_engine=policy_engine,
        audit_logger=audit_logger,
    )


def _unique_source_object_ids(citations: tuple[CrmErpSourceCitation, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for citation in citations:
        if citation.source_object_id in seen:
            continue
        seen.add(citation.source_object_id)
        ordered.append(citation.source_object_id)
    return tuple(ordered)


def _policy_authorization(
    *,
    policy_engine: PolicyEngine,
    model_id: str,
    prompt_template_id: str,
    source_object_ids: tuple[str, ...],
    inference_data_classes: tuple[DataClass, ...],
    risk_level: RiskLevel,
    prompt_template: PromptTemplate,
    user_context: UserContext,
    tenant_policy: TenantPolicy,
) -> tuple[bool, tuple[str, ...]]:
    try:
        policy_engine.authorize_rag(user_context=user_context, tenant_policy=tenant_policy)
        policy_engine.authorize_inference(
            request=InferenceRequest(
                prompt_template_id=prompt_template_id,
                model_id=model_id,
                purpose=Purpose.RAG,
                input_text=INFERENCE_BOUNDARY_PLACEHOLDER_INPUT,
                data_classes=set(inference_data_classes),
                source_object_ids=list(source_object_ids),
                risk_level=risk_level,
            ),
            prompt_template=prompt_template,
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
    except PolicyViolation as exc:
        return False, (_policy_blocking_reason(str(exc)),)
    return True, ()


def _policy_blocking_reason(message: str) -> str:
    reason_by_message = {
        "User tenant does not match tenant policy": "tenant_policy_context_mismatch",
        "AI is disabled for this tenant": "tenant_ai_policy_not_enabled",
        "RAG is disabled for this tenant": "tenant_rag_policy_not_enabled",
        "Model is not allowed for this tenant": "model_not_allowed_by_tenant_policy",
        "Model is blocked for this purpose": "model_blocked_for_rag",
        "Model is not approved for this purpose": "model_not_approved_for_rag",
        "Tenant policy blocks one or more data classes": "tenant_policy_blocks_inference_data_classes",
        "Model blocks one or more data classes": "model_blocks_inference_data_classes",
        "Prompt template blocks one or more data classes": "prompt_template_blocks_inference_data_classes",
        "User cannot read one or more requested sources": "user_cannot_read_one_or_more_requested_sources",
    }
    return reason_by_message.get(message, "policy_violation")


def _blocking_reasons(
    *,
    authorized_context_contract_ready: bool,
    policy_blocking_reasons: tuple[str, ...],
    human_confirmation_required: bool,
    human_confirmation_ref: str | None,
    citation_count: int,
    authorized_chunk_count: int,
    inference_data_classes: tuple[DataClass, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not authorized_context_contract_ready:
        reasons.append("authorized_context_contract_not_ready")
    reasons.extend(policy_blocking_reasons)
    if human_confirmation_required and human_confirmation_ref is None:
        reasons.append("human_confirmation_required")
    if citation_count < 1:
        reasons.append("source_citations_required")
    if authorized_chunk_count < 1:
        reasons.append("authorized_chunk_refs_required")
    if not inference_data_classes:
        reasons.append("inference_data_classes_required")
    return tuple(dict.fromkeys(reasons))


def _inference_execution_boundary_hash(
    *,
    tenant_id: str,
    model_id: str,
    prompt_template_id: str,
    prompt_template_version: str,
    risk_level: RiskLevel,
    inference_data_classes: tuple[DataClass, ...],
    source_object_ids: tuple[str, ...],
    authorized_context_contract_hash: str,
    human_confirmation_ref: str | None,
    required_inference_steps: tuple[str, ...],
) -> str:
    return stable_hash(
        canonical_json(
            {
                "authorized_context_contract_hash": authorized_context_contract_hash,
                "human_confirmation_ref": human_confirmation_ref,
                "inference_data_classes": tuple(data_class.value for data_class in inference_data_classes),
                "model_id": model_id,
                "prompt_template_id": prompt_template_id,
                "prompt_template_version": prompt_template_version,
                "required_inference_steps": required_inference_steps,
                "risk_level": risk_level.value,
                "source_object_ids": source_object_ids,
                "tenant_id": tenant_id,
            }
        )
    )
