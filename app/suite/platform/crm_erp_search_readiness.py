from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.crm_erp_legacy_mapping import CRM_ERP_MODULE_ID
from suite.platform.crm_erp_search import CRM_ERP_SEARCH_FEATURE_ID, CRM_ERP_SEARCH_RESULT_CONTRACT
from suite.platform.modules import ModuleGateSurface, ModuleLifecycleError, ModuleStatus, TenantModuleState

CRM_ERP_SEARCH_READINESS_SCHEMA_VERSION = "crm_erp_search_readiness.v1"
CRM_ERP_SEARCH_READINESS_RESULT_CONTRACT = "metadata_only_search_readiness_no_content"


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
            summary="RAG remains disabled until source citation and ACL revalidation gates are implemented.",
            evidence_ref="docs/RAG_SECURITY_MODEL.md",
        ),
    )


def _satisfied_or_blocked(value: bool) -> CrmErpSearchReadinessGateStatus:
    if value:
        return CrmErpSearchReadinessGateStatus.SATISFIED
    return CrmErpSearchReadinessGateStatus.BLOCKED
