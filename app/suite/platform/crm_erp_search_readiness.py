from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.crm_erp_legacy_mapping import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_search import CRM_ERP_SEARCH_FEATURE_ID, CRM_ERP_SEARCH_RESULT_CONTRACT
from suite.platform.modules import ModuleGateSurface, ModuleLifecycleError, ModuleStatus, TenantModuleState

CRM_ERP_SEARCH_READINESS_SCHEMA_VERSION = "crm_erp_search_readiness.v1"
CRM_ERP_SEARCH_READINESS_RESULT_CONTRACT = "metadata_only_search_readiness_no_content"
CRM_ERP_RAG_INDEXING_FEATURE_ID = "crm_erp.rag_indexing"
CRM_ERP_RAG_READINESS_SCHEMA_VERSION = "crm_erp_rag_readiness.v1"
CRM_ERP_RAG_READINESS_RESULT_CONTRACT = "metadata_only_rag_readiness_no_context"


class CrmErpSearchReadinessRegistry(Protocol):
    def get_tenant_module_or_none(self, *, tenant_id: str, module_id: str) -> TenantModuleState | None: ...

    def require_module_gate(
        self,
        *,
        tenant_id: str,
        module_id: str,
        surface: ModuleGateSurface,
        feature_id: str | None = None,
    ) -> object: ...


class CrmErpSearchReadinessStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class CrmErpSearchReadinessGateStatus(StrEnum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    DEFERRED_BY_POLICY = "deferred_by_policy"


class CrmErpSearchReadinessGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    status: CrmErpSearchReadinessGateStatus
    summary: str
    evidence_ref: str

    @field_validator("gate_id", "summary", "evidence_ref")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("search readiness gate fields must not be empty")
        return value


class CrmErpSearchReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_SEARCH_READINESS_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_SEARCH_FEATURE_ID
    endpoint: str = "/v1/crm-erp/search"
    status: CrmErpSearchReadinessStatus
    module_status: ModuleStatus
    module_enabled_for_normal_use: bool
    feature_configured_enabled: bool
    feature_enabled_for_normal_use: bool
    ready_for_keyword_search: bool
    ready_for_rag_context: bool = False
    gates: tuple[CrmErpSearchReadinessGate, ...]
    blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    result_contract: str = CRM_ERP_SEARCH_READINESS_RESULT_CONTRACT
    search_result_contract: str = CRM_ERP_SEARCH_RESULT_CONTRACT
    content_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator("tenant_id", "module_id", "feature_id", "endpoint", "result_contract", "search_result_contract")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("search readiness response text fields must not be empty")
        return value

    @field_validator("gates", "guardrails", "evidence_refs")
    @classmethod
    def require_non_empty_items(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if not value:
            raise ValueError("search readiness response lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_consistent_readiness(self) -> CrmErpSearchReadinessResponse:
        if self.schema_version != CRM_ERP_SEARCH_READINESS_SCHEMA_VERSION:
            raise ValueError("search readiness schema version is invalid")
        if self.module_id != CRM_ERP_MODULE_ID:
            raise ValueError("search readiness only applies to CRM/ERP")
        if self.feature_id != CRM_ERP_SEARCH_FEATURE_ID:
            raise ValueError("search readiness only applies to CRM/ERP keyword search")
        if self.ready_for_rag_context or self.content_included or self.ai_used or self.rag_context_created:
            raise ValueError("search readiness must remain metadata-only and non-AI")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("search readiness must not allow side effects")
        if self.ready_for_keyword_search and self.status != CrmErpSearchReadinessStatus.READY:
            raise ValueError("ready keyword search must use ready status")
        if not self.ready_for_keyword_search and self.status != CrmErpSearchReadinessStatus.BLOCKED:
            raise ValueError("blocked keyword search must use blocked status")
        if self.ready_for_keyword_search and self.blocking_reasons:
            raise ValueError("ready keyword search must not report blocking reasons")
        if not self.ready_for_keyword_search and not self.blocking_reasons:
            raise ValueError("blocked keyword search requires blocking reasons")
        return self


def build_crm_erp_search_readiness_response(
    *,
    user_context: UserContext,
    module_registry: CrmErpSearchReadinessRegistry,
) -> CrmErpSearchReadinessResponse:
    state = module_registry.get_tenant_module_or_none(
        tenant_id=user_context.tenant_id,
        module_id=CRM_ERP_MODULE_ID,
    )
    module_status = state.status if state is not None else ModuleStatus.NOT_INSTALLED
    module_enabled_for_normal_use = state.normal_use_enabled if state is not None else False
    feature_configured_enabled = (
        state.enabled_features.get(CRM_ERP_SEARCH_FEATURE_ID, False) if state is not None else False
    )

    blocking_reasons: list[str] = []
    if state is None:
        blocking_reasons.append("tenant_module_state_missing")
    if state is not None and not state.normal_use_enabled:
        blocking_reasons.append("module_normal_use_not_enabled")
    if state is not None and not feature_configured_enabled:
        blocking_reasons.append("feature_flag_not_enabled")

    try:
        module_registry.require_module_gate(
            tenant_id=user_context.tenant_id,
            module_id=CRM_ERP_MODULE_ID,
            surface=ModuleGateSurface.NORMAL_API,
            feature_id=CRM_ERP_SEARCH_FEATURE_ID,
        )
    except (LookupError, ModuleLifecycleError) as exc:
        gate_error = str(exc)
        if gate_error and gate_error not in blocking_reasons:
            blocking_reasons.append(gate_error)
        feature_enabled_for_normal_use = False
    else:
        feature_enabled_for_normal_use = True

    ready_for_keyword_search = feature_enabled_for_normal_use
    status = CrmErpSearchReadinessStatus.READY if ready_for_keyword_search else CrmErpSearchReadinessStatus.BLOCKED

    return CrmErpSearchReadinessResponse(
        tenant_id=user_context.tenant_id,
        status=status,
        module_status=module_status,
        module_enabled_for_normal_use=module_enabled_for_normal_use,
        feature_configured_enabled=feature_configured_enabled,
        feature_enabled_for_normal_use=feature_enabled_for_normal_use,
        ready_for_keyword_search=ready_for_keyword_search,
        gates=_readiness_gates(
            tenant_context_present=True,
            module_enabled_for_normal_use=module_enabled_for_normal_use,
            feature_configured_enabled=feature_configured_enabled,
            feature_enabled_for_normal_use=feature_enabled_for_normal_use,
        ),
        blocking_reasons=tuple(blocking_reasons),
        guardrails=(
            "tenant_context_required",
            "module_gate_required_before_search",
            "authoritative_acl_validation_required",
            "metadata_only_candidate_results",
            "no_ai_or_rag_context_created",
            "audit_event_required_for_search_queries",
        ),
        evidence_refs=(
            "tests/test_crm_erp_search.py",
            "app/suite/platform/crm_erp_search.py",
            "app/suite/rag/repositories.py::ReadableObjectAclAuthorizer",
            "docs/modules/CRM_ERP_SUBFEATURE_REGISTRY.md",
        ),
    )


def _readiness_gates(
    *,
    tenant_context_present: bool,
    module_enabled_for_normal_use: bool,
    feature_configured_enabled: bool,
    feature_enabled_for_normal_use: bool,
) -> tuple[CrmErpSearchReadinessGate, ...]:
    return (
        CrmErpSearchReadinessGate(
            gate_id="tenant_context",
            status=_satisfied_or_blocked(tenant_context_present),
            summary="Request carries a resolved tenant/user context before readiness is evaluated.",
            evidence_ref="suite.platform.context.get_tenant_request_context",
        ),
        CrmErpSearchReadinessGate(
            gate_id="module_normal_use",
            status=_satisfied_or_blocked(module_enabled_for_normal_use),
            summary="CRM/ERP module must be enabled for normal API use before search can run.",
            evidence_ref="suite.platform.modules.ModuleWorkerGate",
        ),
        CrmErpSearchReadinessGate(
            gate_id="feature_flag",
            status=_satisfied_or_blocked(feature_configured_enabled),
            summary="crm_erp.search.keyword must be configured as an enabled tenant feature.",
            evidence_ref="docs/modules/CRM_ERP_SUBFEATURE_REGISTRY.md",
        ),
        CrmErpSearchReadinessGate(
            gate_id="normal_api_feature_gate",
            status=_satisfied_or_blocked(feature_enabled_for_normal_use),
            summary="The same normal API module gate used by POST /v1/crm-erp/search must pass.",
            evidence_ref="app/main.py::require_module_api_gate",
        ),
        CrmErpSearchReadinessGate(
            gate_id="authoritative_acl_validation",
            status=CrmErpSearchReadinessGateStatus.SATISFIED,
            summary="Candidates are filtered through authoritative readable object IDs before response emission.",
            evidence_ref="suite.rag.repositories.ReadableObjectAclAuthorizer",
        ),
        CrmErpSearchReadinessGate(
            gate_id="rag_context",
            status=CrmErpSearchReadinessGateStatus.DEFERRED_BY_POLICY,
            summary="RAG remains disabled until prompt audit, redaction, and authorized context gates are implemented.",
            evidence_ref="docs/RAG_SECURITY_MODEL.md",
        ),
    )


def _satisfied_or_blocked(value: bool) -> CrmErpSearchReadinessGateStatus:
    if value:
        return CrmErpSearchReadinessGateStatus.SATISFIED
    return CrmErpSearchReadinessGateStatus.BLOCKED


class CrmErpRagReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_RAG_READINESS_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_RAG_INDEXING_FEATURE_ID
    readiness_endpoint: str = "/v1/platform/search/crm-erp/rag-readiness"
    protected_surface: str = ModuleGateSurface.FEATURE_WORKER.value
    status: CrmErpSearchReadinessStatus
    module_status: ModuleStatus
    module_enabled_for_normal_use: bool
    tenant_ai_enabled: bool
    tenant_rag_enabled: bool
    external_ai_enabled: bool
    rag_feature_configured_enabled: bool
    rag_feature_worker_enabled: bool
    source_resolver_acl_trace_ready: bool = False
    source_citation_contract_ready: bool = False
    prompt_audit_contract_ready: bool = False
    redaction_contract_ready: bool = False
    ready_for_rag_context: bool = False
    gates: tuple[CrmErpSearchReadinessGate, ...]
    blocking_reasons: tuple[str, ...]
    guardrails: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    result_contract: str = CRM_ERP_RAG_READINESS_RESULT_CONTRACT
    content_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator(
        "tenant_id",
        "module_id",
        "feature_id",
        "readiness_endpoint",
        "protected_surface",
        "result_contract",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM/ERP RAG readiness response text fields must not be empty")
        return value

    @field_validator("gates", "guardrails", "evidence_refs")
    @classmethod
    def require_non_empty_items(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if not value:
            raise ValueError("CRM/ERP RAG readiness response lists must not be empty")
        return value

    @model_validator(mode="after")
    def require_consistent_rag_readiness(self) -> CrmErpRagReadinessResponse:
        if self.schema_version != CRM_ERP_RAG_READINESS_SCHEMA_VERSION:
            raise ValueError("CRM/ERP RAG readiness schema version is invalid")
        if self.module_id != CRM_ERP_MODULE_ID:
            raise ValueError("CRM/ERP RAG readiness only applies to CRM/ERP")
        if self.feature_id != CRM_ERP_RAG_INDEXING_FEATURE_ID:
            raise ValueError("CRM/ERP RAG readiness only applies to rag_indexing")
        if self.content_included or self.ai_used or self.rag_context_created:
            raise ValueError("CRM/ERP RAG readiness must not create content, AI output, or RAG context")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP RAG readiness must not allow side effects")
        if self.ready_for_rag_context and self.status != CrmErpSearchReadinessStatus.READY:
            raise ValueError("ready CRM/ERP RAG context must use ready status")
        if not self.ready_for_rag_context and self.status != CrmErpSearchReadinessStatus.BLOCKED:
            raise ValueError("blocked CRM/ERP RAG readiness must use blocked status")
        if self.ready_for_rag_context and self.blocking_reasons:
            raise ValueError("ready CRM/ERP RAG readiness must not report blocking reasons")
        if not self.ready_for_rag_context and not self.blocking_reasons:
            raise ValueError("blocked CRM/ERP RAG readiness requires blocking reasons")
        return self


def build_crm_erp_rag_readiness_response(
    *,
    user_context: UserContext,
    module_registry: CrmErpSearchReadinessRegistry,
    tenant_policy: TenantPolicy,
    source_resolver_acl_trace_ready: bool = False,
    source_citation_contract_ready: bool = False,
    prompt_audit_contract_ready: bool = False,
    redaction_contract_ready: bool = False,
) -> CrmErpRagReadinessResponse:
    state = module_registry.get_tenant_module_or_none(
        tenant_id=user_context.tenant_id,
        module_id=CRM_ERP_MODULE_ID,
    )
    module_status = state.status if state is not None else ModuleStatus.NOT_INSTALLED
    module_enabled_for_normal_use = state.normal_use_enabled if state is not None else False
    rag_feature_configured_enabled = (
        state.enabled_features.get(CRM_ERP_RAG_INDEXING_FEATURE_ID, False) if state is not None else False
    )
    tenant_policy_matches_context = tenant_policy.tenant_id == user_context.tenant_id
    tenant_ai_enabled = tenant_policy_matches_context and tenant_policy.ai_enabled
    tenant_rag_enabled = tenant_policy_matches_context and tenant_policy.rag_enabled

    blocking_reasons: list[str] = []
    if not tenant_policy_matches_context:
        blocking_reasons.append("tenant_policy_context_mismatch")
    if state is None:
        blocking_reasons.append("tenant_module_state_missing")
    if state is not None and not state.normal_use_enabled:
        blocking_reasons.append("module_normal_use_not_enabled")
    if state is not None and not rag_feature_configured_enabled:
        blocking_reasons.append("rag_indexing_feature_flag_not_enabled")
    if not tenant_ai_enabled:
        blocking_reasons.append("tenant_ai_policy_not_enabled")
    if not tenant_rag_enabled:
        blocking_reasons.append("tenant_rag_policy_not_enabled")

    try:
        module_registry.require_module_gate(
            tenant_id=user_context.tenant_id,
            module_id=CRM_ERP_MODULE_ID,
            surface=ModuleGateSurface.FEATURE_WORKER,
            feature_id=CRM_ERP_RAG_INDEXING_FEATURE_ID,
        )
    except (LookupError, ModuleLifecycleError) as exc:
        gate_error = str(exc)
        if gate_error and gate_error not in blocking_reasons:
            blocking_reasons.append(gate_error)
        rag_feature_worker_enabled = False
    else:
        rag_feature_worker_enabled = True

    if not source_resolver_acl_trace_ready:
        blocking_reasons.append("source_resolver_acl_trace_missing")
    if not source_citation_contract_ready:
        blocking_reasons.append("source_citation_contract_missing")
    if not prompt_audit_contract_ready:
        blocking_reasons.append("prompt_audit_contract_missing")
    if not redaction_contract_ready:
        blocking_reasons.append("redaction_contract_missing")

    ready_for_rag_context = (
        rag_feature_worker_enabled
        and tenant_ai_enabled
        and tenant_rag_enabled
        and source_resolver_acl_trace_ready
        and source_citation_contract_ready
        and prompt_audit_contract_ready
        and redaction_contract_ready
    )
    status = CrmErpSearchReadinessStatus.READY if ready_for_rag_context else CrmErpSearchReadinessStatus.BLOCKED

    return CrmErpRagReadinessResponse(
        tenant_id=user_context.tenant_id,
        status=status,
        module_status=module_status,
        module_enabled_for_normal_use=module_enabled_for_normal_use,
        tenant_ai_enabled=tenant_ai_enabled,
        tenant_rag_enabled=tenant_rag_enabled,
        external_ai_enabled=tenant_policy.external_ai_enabled,
        rag_feature_configured_enabled=rag_feature_configured_enabled,
        rag_feature_worker_enabled=rag_feature_worker_enabled,
        source_resolver_acl_trace_ready=source_resolver_acl_trace_ready,
        source_citation_contract_ready=source_citation_contract_ready,
        prompt_audit_contract_ready=prompt_audit_contract_ready,
        redaction_contract_ready=redaction_contract_ready,
        ready_for_rag_context=ready_for_rag_context,
        gates=_rag_readiness_gates(
            tenant_context_present=True,
            tenant_ai_enabled=tenant_ai_enabled,
            tenant_rag_enabled=tenant_rag_enabled,
            module_enabled_for_normal_use=module_enabled_for_normal_use,
            rag_feature_configured_enabled=rag_feature_configured_enabled,
            rag_feature_worker_enabled=rag_feature_worker_enabled,
            source_resolver_acl_trace_ready=source_resolver_acl_trace_ready,
            source_citation_contract_ready=source_citation_contract_ready,
            prompt_audit_contract_ready=prompt_audit_contract_ready,
            redaction_contract_ready=redaction_contract_ready,
        ),
        blocking_reasons=tuple(dict.fromkeys(blocking_reasons)),
        guardrails=(
            "tenant_context_required",
            "tenant_ai_and_rag_policy_required",
            "rag_indexing_feature_worker_gate_required",
            "source_resolver_acl_trace_required",
            "source_object_id_and_version_citations_required",
            "prompt_and_output_hash_audit_required",
            "redaction_contract_required",
            "metadata_only_no_context_created",
            "no_cloud_ai_without_tenant_policy",
        ),
        evidence_refs=(
            "docs/RAG_SECURITY_MODEL.md",
            "docs/modules/CRM_ERP_SUBFEATURE_REGISTRY.md",
            "app/suite/platform/crm_erp_search_readiness.py",
            "tests/test_crm_erp_search.py",
            "tests/test_api.py::test_crm_erp_rag_readiness_api_reports_blocked_governance_state_without_context",
        ),
    )


def _rag_readiness_gates(
    *,
    tenant_context_present: bool,
    tenant_ai_enabled: bool,
    tenant_rag_enabled: bool,
    module_enabled_for_normal_use: bool,
    rag_feature_configured_enabled: bool,
    rag_feature_worker_enabled: bool,
    source_resolver_acl_trace_ready: bool,
    source_citation_contract_ready: bool,
    prompt_audit_contract_ready: bool,
    redaction_contract_ready: bool,
) -> tuple[CrmErpSearchReadinessGate, ...]:
    return (
        CrmErpSearchReadinessGate(
            gate_id="tenant_context",
            status=_satisfied_or_blocked(tenant_context_present),
            summary="Request carries a resolved tenant/user context before RAG readiness is evaluated.",
            evidence_ref="suite.platform.context.get_tenant_request_context",
        ),
        CrmErpSearchReadinessGate(
            gate_id="tenant_ai_policy",
            status=_satisfied_or_blocked(tenant_ai_enabled),
            summary="Tenant policy must enable AI before any CRM/ERP RAG context can be prepared.",
            evidence_ref="suite.ai_control_plane.models.TenantPolicy.ai_enabled",
        ),
        CrmErpSearchReadinessGate(
            gate_id="tenant_rag_policy",
            status=_satisfied_or_blocked(tenant_rag_enabled),
            summary="Tenant policy must explicitly enable RAG before CRM/ERP retrieval context can be prepared.",
            evidence_ref="suite.ai_control_plane.models.TenantPolicy.rag_enabled",
        ),
        CrmErpSearchReadinessGate(
            gate_id="module_normal_use",
            status=_satisfied_or_blocked(module_enabled_for_normal_use),
            summary="CRM/ERP module must be enabled for normal use before RAG indexing workers can run.",
            evidence_ref="suite.platform.modules.ModuleWorkerGate",
        ),
        CrmErpSearchReadinessGate(
            gate_id="rag_feature_flag",
            status=_satisfied_or_blocked(rag_feature_configured_enabled),
            summary="crm_erp.rag_indexing must be enabled for the tenant before any CRM/ERP RAG worker runs.",
            evidence_ref="docs/modules/CRM_ERP_SUBFEATURE_REGISTRY.md",
        ),
        CrmErpSearchReadinessGate(
            gate_id="feature_worker_gate",
            status=_satisfied_or_blocked(rag_feature_worker_enabled),
            summary="The feature-worker module gate for crm_erp.rag_indexing must pass.",
            evidence_ref="app/main.py::ModuleGateSurface.FEATURE_WORKER",
        ),
        CrmErpSearchReadinessGate(
            gate_id="source_resolver_acl_trace",
            status=_satisfied_or_blocked(source_resolver_acl_trace_ready),
            summary="Source resolver must provide authoritative ACL traces before RAG context creation.",
            evidence_ref="docs/RAG_SECURITY_MODEL.md",
        ),
        CrmErpSearchReadinessGate(
            gate_id="source_citation_contract",
            status=_satisfied_or_blocked(source_citation_contract_ready),
            summary="RAG answers must cite source object IDs and source versions before the feature is ready.",
            evidence_ref="docs/RAG_SECURITY_MODEL.md",
        ),
        CrmErpSearchReadinessGate(
            gate_id="prompt_audit_contract",
            status=_satisfied_or_blocked(prompt_audit_contract_ready),
            summary="Prompt, context, model ID, output hash, and tool calls must be audit logged before RAG runs.",
            evidence_ref="docs/AI_AUDIT_SCHEMA.md",
        ),
        CrmErpSearchReadinessGate(
            gate_id="redaction_contract",
            status=_satisfied_or_blocked(redaction_contract_ready),
            summary="Authorized source blocks must pass redaction before prompt construction.",
            evidence_ref="docs/RAG_SECURITY_MODEL.md",
        ),
    )
