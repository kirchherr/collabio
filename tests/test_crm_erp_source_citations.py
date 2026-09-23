from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_source_citations import (
    CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT,
    CrmErpSourceCitationContractRequest,
    CrmErpSourceCitationContractService,
    build_crm_erp_source_citation_contract_service,
)
from suite.platform.crm_erp_source_resolver import build_crm_erp_source_resolver_acl_trace_service
from suite.platform.erp_products import InMemoryErpProductRepository
from suite.platform.erp_sales import (
    InMemoryErpInvoiceItemRepository,
    InMemoryErpInvoiceRepository,
    InMemoryErpOrderItemRepository,
    InMemoryErpOrderRepository,
)
from suite.platform.erp_suppliers import InMemoryErpSupplierRepository


def user_context(*, readable_object_ids: set[str]) -> UserContext:
    return UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids=readable_object_ids,
    )


def build_service() -> tuple[CrmErpSourceCitationContractService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    source_resolver = build_crm_erp_source_resolver_acl_trace_service(
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
    return (
        build_crm_erp_source_citation_contract_service(
            source_resolver_acl_trace_service=source_resolver,
            audit_logger=audit_logger,
        ),
        audit_logger,
    )


def test_crm_erp_source_citation_contract_builds_authorized_metadata_citations_without_context() -> None:
    service, audit_logger = build_service()

    response = service.build_contract(
        request=CrmErpSourceCitationContractRequest(
            object_ids=(
                "crm-account-acme-demo",
                "erp-order-item-acme-widget-demo",
                "erp-supplier-contoso-demo",
                "erp-product-other-tenant",
                "crm-account-acme-demo",
            )
        ),
        user_context=user_context(
            readable_object_ids={
                "crm-account-acme-demo",
                "erp-order-item-acme-widget-demo",
            }
        ),
    )

    serialized_response = response.model_dump_json()
    source_resolver_event = audit_logger.events[-2]
    citation_event = audit_logger.events[-1]
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.search.keyword"
    assert response.endpoint == "/v1/platform/search/crm-erp/source-citation-contract"
    assert response.requested_object_ids == (
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
        "erp-supplier-contoso-demo",
        "erp-product-other-tenant",
    )
    assert [citation.source_object_id for citation in response.citations] == [
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
    ]
    assert {
        (
            citation.source_object_type,
            citation.source_version_id,
            citation.source_chunk_id,
        )
        for citation in response.citations
    } == {
        ("crm.account", "crm_account.v1", "crm-account-acme-demo-metadata"),
        ("erp.order_item", "erp_order_item.v1", "erp-order-item-acme-widget-demo-metadata"),
    }
    assert all(citation.citation_id for citation in response.citations)
    assert all(citation.access_checked for citation in response.citations)
    assert all(citation.authorized for citation in response.citations)
    assert response.blocked_source_object_ids == ("erp-supplier-contoso-demo",)
    assert response.unresolved_source_object_ids == ("erp-product-other-tenant",)
    assert response.candidate_count == 4
    assert response.citation_count == 2
    assert response.blocked_count == 1
    assert response.unresolved_count == 1
    assert response.source_resolver_acl_trace_ready is False
    assert response.source_citation_contract_ready is False
    assert response.source_resolver_audit_event_id == source_resolver_event.event_id
    assert response.audit_event_id == citation_event.event_id
    assert response.result_contract == CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT
    assert response.content_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "Standard Widget" not in serialized_response
    assert "Contoso procurement desk" not in serialized_response

    assert source_resolver_event.event_type == "crm_erp.source_resolver_acl_trace"
    assert citation_event.event_type == "crm_erp.source_citation_contract"
    assert citation_event.source_object_ids == ["crm-account-acme-demo", "erp-order-item-acme-widget-demo"]
    assert citation_event.input_hash is None
    assert citation_event.output_hash is None
    assert citation_event.metadata["result_contract"] == CRM_ERP_SOURCE_CITATION_CONTRACT_RESULT_CONTRACT
    assert citation_event.metadata["source_resolver_audit_event_id"] == source_resolver_event.event_id
    assert citation_event.metadata["candidate_count"] == 4
    assert citation_event.metadata["citation_count"] == 2
    assert citation_event.metadata["blocked_count"] == 1
    assert citation_event.metadata["unresolved_count"] == 1
    assert citation_event.metadata["content_included"] is False
    assert citation_event.metadata["ai_used"] is False
    assert citation_event.metadata["rag_context_created"] is False


def test_crm_erp_source_citation_contract_ready_when_all_requested_refs_have_authorized_citations() -> None:
    service, _audit_logger = build_service()

    response = service.build_contract(
        request=CrmErpSourceCitationContractRequest(
            object_ids=("erp-invoice-item-acme-widget-demo", "erp-invoice-item-acme-widget-demo")
        ),
        user_context=user_context(readable_object_ids={"erp-invoice-item-acme-widget-demo"}),
    )

    assert response.requested_object_ids == ("erp-invoice-item-acme-widget-demo",)
    assert [citation.source_object_id for citation in response.citations] == ["erp-invoice-item-acme-widget-demo"]
    assert response.blocked_source_object_ids == ()
    assert response.unresolved_source_object_ids == ()
    assert response.source_resolver_acl_trace_ready is True
    assert response.source_citation_contract_ready is True
