from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_source_resolver import (
    CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT,
    CrmErpSourceResolverAclTraceRequest,
    CrmErpSourceResolverAclTraceService,
    build_crm_erp_source_resolver_acl_trace_service,
)
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


def build_service() -> tuple[CrmErpSourceResolverAclTraceService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    service = build_crm_erp_source_resolver_acl_trace_service(
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


def test_crm_erp_source_resolver_acl_trace_resolves_only_authorized_metadata_without_context() -> None:
    service, audit_logger = build_service()

    response = service.build_trace(
        request=CrmErpSourceResolverAclTraceRequest(
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
    audit_event = audit_logger.events[-1]
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.search.keyword"
    assert response.requested_object_ids == (
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
        "erp-supplier-contoso-demo",
        "erp-product-other-tenant",
    )
    assert [source.object_id for source in response.resolved_source_refs] == [
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
    ]
    assert {source.object_type for source in response.resolved_source_refs} == {"crm.account", "erp.order_item"}
    assert all(source.access_checked for source in response.resolved_source_refs)
    assert all(source.authorized for source in response.resolved_source_refs)
    assert response.blocked_source_object_ids == ("erp-supplier-contoso-demo",)
    assert response.unresolved_source_object_ids == ("erp-product-other-tenant",)
    assert response.candidate_count == 4
    assert response.authorized_count == 2
    assert response.blocked_count == 1
    assert response.unresolved_count == 1
    assert response.source_resolver_acl_trace_ready is False
    assert response.result_contract == CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT
    assert response.content_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "Standard Widget" not in serialized_response
    assert "Contoso procurement desk" not in serialized_response

    assert response.audit_event_id == audit_event.event_id
    assert audit_event.event_type == "crm_erp.source_resolver_acl_trace"
    assert audit_event.source_object_ids == ["crm-account-acme-demo", "erp-order-item-acme-widget-demo"]
    assert audit_event.input_hash is None
    assert audit_event.output_hash is None
    assert audit_event.metadata["result_contract"] == CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT
    assert audit_event.metadata["candidate_count"] == 4
    assert audit_event.metadata["authorized_count"] == 2
    assert audit_event.metadata["blocked_count"] == 1
    assert audit_event.metadata["unresolved_count"] == 1
    assert audit_event.metadata["content_included"] is False
    assert audit_event.metadata["ai_used"] is False
    assert audit_event.metadata["rag_context_created"] is False


def test_crm_erp_source_resolver_acl_trace_ready_when_all_requested_refs_are_authorized() -> None:
    service, _audit_logger = build_service()

    response = service.build_trace(
        request=CrmErpSourceResolverAclTraceRequest(
            object_ids=("erp-invoice-item-acme-widget-demo", "erp-invoice-item-acme-widget-demo")
        ),
        user_context=user_context(readable_object_ids={"erp-invoice-item-acme-widget-demo"}),
    )

    assert response.requested_object_ids == ("erp-invoice-item-acme-widget-demo",)
    assert [source.object_id for source in response.resolved_source_refs] == ["erp-invoice-item-acme-widget-demo"]
    assert response.blocked_source_object_ids == ()
    assert response.unresolved_source_object_ids == ()
    assert response.source_resolver_acl_trace_ready is True
