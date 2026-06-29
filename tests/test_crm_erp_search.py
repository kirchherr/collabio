from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_search import (
    CRM_ERP_SEARCH_RESULT_CONTRACT,
    CrmErpSearchService,
    build_crm_erp_search_service,
)
from suite.platform.erp_products import InMemoryErpProductRepository
from suite.platform.erp_sales import InMemoryErpInvoiceRepository, InMemoryErpOrderRepository
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
        order_repository=InMemoryErpOrderRepository.demo(),
        invoice_repository=InMemoryErpInvoiceRepository.demo(),
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
