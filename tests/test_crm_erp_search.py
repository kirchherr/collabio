from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_search import (
    CRM_ERP_SEARCH_RESULT_CONTRACT,
    CrmErpSearchService,
    build_crm_erp_search_service,
)
from suite.platform.crm_erp_search_readiness import (
    CRM_ERP_RAG_READINESS_RESULT_CONTRACT,
    CRM_ERP_SEARCH_READINESS_RESULT_CONTRACT,
    build_crm_erp_rag_readiness_response,
    build_crm_erp_search_readiness_response,
)
from suite.platform.erp_products import InMemoryErpProductRepository
from suite.platform.erp_sales import (
    InMemoryErpInvoiceItemRepository,
    InMemoryErpInvoiceRepository,
    InMemoryErpOrderItemRepository,
    InMemoryErpOrderRepository,
)
from suite.platform.erp_suppliers import InMemoryErpSupplierRepository
from suite.platform.modules import default_module_registry
from suite.search.models import KeywordSearchQuery


def user_context(*, tenant_id: str = "tenant-demo", readable_object_ids: set[str] | None = None) -> UserContext:
    return UserContext(
        user_id="user-demo",
        tenant_id=tenant_id,
        role_ids={"knowledge-worker"},
        readable_object_ids=readable_object_ids or set(),
    )


def build_service() -> tuple[CrmErpSearchService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    service = build_crm_erp_search_service(
        account_repository=InMemoryCrmAccountRepository.demo(),
        contact_repository=InMemoryCrmContactRepository.demo(),
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        product_repository=InMemoryErpProductRepository.demo(),
        supplier_repository=InMemoryErpSupplierRepository.demo(),
        order_repository=InMemoryErpOrderRepository.demo(),
        invoice_repository=InMemoryErpInvoiceRepository.demo(),
        order_item_repository=InMemoryErpOrderItemRepository.demo(),
        invoice_item_repository=InMemoryErpInvoiceItemRepository.demo(),
        audit_logger=audit_logger,
    )
    return service, audit_logger


def test_crm_erp_search_returns_authorized_metadata_candidates_without_content() -> None:
    service, audit_logger = build_service()

    response = service.search(
        query=KeywordSearchQuery(query="acme widget", top_k=10),
        user_context=user_context(
            readable_object_ids={
                "crm-account-acme-demo",
                "erp-product-standard-widget-demo",
                "erp-order-acme-widget-demo",
                "erp-invoice-acme-widget-demo",
            }
        ),
    )

    object_ids = {candidate.object_id for candidate in response.candidates}
    serialized_response = response.model_dump_json()
    audit_event = audit_logger.events[-1]
    assert object_ids == {
        "crm-account-acme-demo",
        "erp-product-standard-widget-demo",
        "erp-order-acme-widget-demo",
        "erp-invoice-acme-widget-demo",
    }
    assert {candidate.object_type for candidate in response.candidates} == {
        "crm.account",
        "erp.product",
        "erp.order",
        "erp.invoice",
    }
    assert all(candidate.access_checked for candidate in response.candidates)
    assert all(candidate.retention_policy_id for candidate in response.candidates)
    assert all(candidate.legal_hold_state == "none" for candidate in response.candidates)
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "ada.demo@example.invalid" not in serialized_response
    assert "Other Tenant Product" not in serialized_response
    assert audit_event.event_type == "crm_erp.search.keyword.query"
    assert audit_event.input_hash is not None
    assert "acme widget" not in audit_event.model_dump_json()
    assert audit_event.metadata["module_id"] == "crm_erp"
    assert audit_event.metadata["feature_id"] == "crm_erp.search.keyword"
    assert audit_event.metadata["result_contract"] == CRM_ERP_SEARCH_RESULT_CONTRACT
    assert audit_event.metadata["authorized_candidate_count"] == 4
    assert audit_event.metadata["content_included"] is False
    assert audit_event.metadata["ai_used"] is False
    assert audit_event.metadata["rag_context_created"] is False


def test_crm_erp_search_covers_authorized_suppliers_without_content() -> None:
    service, audit_logger = build_service()

    response = service.search(
        query=KeywordSearchQuery(query="contoso procurement", top_k=10),
        user_context=user_context(readable_object_ids={"erp-supplier-contoso-demo"}),
    )

    serialized_response = response.model_dump_json()
    audit_event = audit_logger.events[-1]
    assert [candidate.object_id for candidate in response.candidates] == ["erp-supplier-contoso-demo"]
    assert {candidate.object_type for candidate in response.candidates} == {"erp.supplier"}
    assert {candidate.classification.value for candidate in response.candidates} == {"personal"}
    assert all(candidate.access_checked for candidate in response.candidates)
    assert all(candidate.retention_policy_id == "rp-standard" for candidate in response.candidates)
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert audit_event.metadata["authorized_candidate_count"] == 1
    assert audit_event.metadata["content_included"] is False
    assert audit_event.metadata["ai_used"] is False
    assert audit_event.metadata["rag_context_created"] is False


def test_crm_erp_search_covers_authorized_order_and_invoice_items_without_content() -> None:
    service, audit_logger = build_service()

    response = service.search(
        query=KeywordSearchQuery(query="standard widget", top_k=10),
        user_context=user_context(
            readable_object_ids={
                "erp-order-item-acme-widget-demo",
                "erp-invoice-item-acme-widget-demo",
            }
        ),
    )

    object_ids = {candidate.object_id for candidate in response.candidates}
    serialized_response = response.model_dump_json()
    audit_event = audit_logger.events[-1]
    assert object_ids == {
        "erp-order-item-acme-widget-demo",
        "erp-invoice-item-acme-widget-demo",
    }
    assert {candidate.object_type for candidate in response.candidates} == {
        "erp.order_item",
        "erp.invoice_item",
    }
    assert all(candidate.access_checked for candidate in response.candidates)
    assert all(candidate.retention_policy_id == "rp-gobd-10y" for candidate in response.candidates)
    assert all(candidate.legal_hold_state == "none" for candidate in response.candidates)
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "erp-product-standard-widget-demo" not in object_ids
    assert audit_event.metadata["authorized_candidate_count"] == 2
    assert audit_event.metadata["content_included"] is False
    assert audit_event.metadata["ai_used"] is False
    assert audit_event.metadata["rag_context_created"] is False


def test_crm_erp_search_is_tenant_scoped_before_acl_authorization() -> None:
    service, audit_logger = build_service()

    response = service.search(
        query=KeywordSearchQuery(query="other tenant", top_k=10),
        user_context=user_context(readable_object_ids={"erp-product-other-tenant", "crm-account-other-tenant"}),
    )

    audit_event = audit_logger.events[-1]
    assert response.candidates == []
    assert audit_event.source_object_ids == []
    assert audit_event.metadata["candidate_count"] == 0
    assert audit_event.metadata["authorized_candidate_count"] == 0


def test_crm_erp_search_response_marks_non_ai_candidate_only_contract() -> None:
    service, _audit_logger = build_service()

    response = service.search(
        query=KeywordSearchQuery(query="acme", top_k=3),
        user_context=user_context(readable_object_ids={"crm-account-acme-demo"}),
    )

    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.search.keyword"
    assert response.search_policy_id == "keyword_candidate_acl_v1"
    assert response.result_contract == CRM_ERP_SEARCH_RESULT_CONTRACT
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.content_included is False
    assert [candidate.object_id for candidate in response.candidates] == ["crm-account-acme-demo"]


def test_crm_erp_rag_readiness_stays_blocked_without_context_creation() -> None:
    response = build_crm_erp_rag_readiness_response(
        user_context=user_context(),
        module_registry=default_module_registry(),
        tenant_policy=TenantPolicy(tenant_id="tenant-demo", ai_enabled=True, rag_enabled=True),
    )

    gate_statuses = {gate.gate_id: gate.status for gate in response.gates}
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.rag_indexing"
    assert response.readiness_endpoint == "/v1/platform/search/crm-erp/rag-readiness"
    assert response.protected_surface == "feature_worker"
    assert response.status == "blocked"
    assert response.module_status == "available"
    assert response.module_enabled_for_normal_use is False
    assert response.tenant_ai_enabled is True
    assert response.tenant_rag_enabled is True
    assert response.rag_feature_configured_enabled is False
    assert response.rag_feature_worker_enabled is False
    assert response.source_resolver_acl_trace_ready is False
    assert response.source_citation_contract_ready is False
    assert response.prompt_audit_contract_ready is False
    assert response.ready_for_rag_context is False
    assert response.result_contract == CRM_ERP_RAG_READINESS_RESULT_CONTRACT
    assert response.content_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "rag_indexing_feature_flag_not_enabled" in response.blocking_reasons
    assert "source_resolver_acl_trace_missing" in response.blocking_reasons
    assert "source_citation_contract_missing" in response.blocking_reasons
    assert "prompt_audit_contract_missing" in response.blocking_reasons
    assert gate_statuses["tenant_ai_policy"] == "satisfied"
    assert gate_statuses["tenant_rag_policy"] == "satisfied"
    assert gate_statuses["rag_feature_flag"] == "blocked"
    assert gate_statuses["source_resolver_acl_trace"] == "blocked"
    assert gate_statuses["source_citation_contract"] == "blocked"
    assert gate_statuses["prompt_audit_contract"] == "blocked"


def test_crm_erp_search_readiness_reports_blocked_module_gate_without_content() -> None:
    response = build_crm_erp_search_readiness_response(
        user_context=user_context(),
        module_registry=default_module_registry(),
    )

    gate_statuses = {gate.gate_id: gate.status for gate in response.gates}
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.search.keyword"
    assert response.endpoint == "/v1/crm-erp/search"
    assert response.status == "blocked"
    assert response.module_status == "available"
    assert response.feature_configured_enabled is True
    assert response.feature_enabled_for_normal_use is False
    assert response.ready_for_keyword_search is False
    assert response.ready_for_rag_context is False
    assert response.result_contract == CRM_ERP_SEARCH_READINESS_RESULT_CONTRACT
    assert response.search_result_contract == CRM_ERP_SEARCH_RESULT_CONTRACT
    assert response.content_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "module_normal_use_not_enabled" in response.blocking_reasons
    assert gate_statuses["tenant_context"] == "satisfied"
    assert gate_statuses["module_normal_use"] == "blocked"
    assert gate_statuses["rag_context"] == "deferred_by_policy"
