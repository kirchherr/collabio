import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.erp_sales import (
    CRM_ERP_MODULE_ID,
    ERP_INVOICE_OBJECT_TYPE,
    ERP_INVOICES_FEATURE_ID,
    ERP_ORDER_OBJECT_TYPE,
    ERP_ORDERS_FEATURE_ID,
    ErpInvoiceRecord,
    ErpOrderRecord,
    ErpSalesService,
    InMemoryErpInvoiceRepository,
    InMemoryErpOrderRepository,
)
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
)


def sales_service(audit_logger: InMemoryAuditLogger) -> ErpSalesService:
    return ErpSalesService(
        order_repository=InMemoryErpOrderRepository.demo(),
        invoice_repository=InMemoryErpInvoiceRepository.demo(),
        audit_logger=audit_logger,
    )


def test_erp_sales_records_require_gobd_compliance_metadata() -> None:
    order = InMemoryErpOrderRepository.demo().list_orders(tenant_id="tenant-demo")[0]
    invoice = InMemoryErpInvoiceRepository.demo().list_invoices(tenant_id="tenant-demo")[0]

    assert order.object_type == ERP_ORDER_OBJECT_TYPE
    assert invoice.object_type == ERP_INVOICE_OBJECT_TYPE
    assert order.data_classification == DataClass.GOBD
    assert invoice.data_classification == DataClass.GOBD
    assert order.retention_policy_id == "rp-gobd-10y"
    assert invoice.retention_policy_id == "rp-gobd-10y"
    assert order.legal_hold_state == "none"
    assert invoice.legal_hold_state == "none"
    assert order.kms_key_ref.startswith("kms:")
    assert invoice.kms_key_ref.startswith("kms:")
    assert order.audit_chain_ref.startswith("audit:")
    assert invoice.audit_chain_ref.startswith("audit:")
    assert order.schema_version == "erp_order.v1"
    assert invoice.schema_version == "erp_invoice.v1"


def test_erp_sales_records_reject_wrong_classification_or_amount_totals() -> None:
    order_values = {
        "tenant_id": "tenant-demo",
        "object_id": "erp-order-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-12T09:00:00Z",
        "updated_at_utc": "2026-06-12T09:00:00Z",
        "kms_key_ref": "kms:tenant-demo:erp-order",
        "audit_chain_ref": "audit:erp-order-invalid",
        "order_number": "ERP-O-INVALID",
        "order_date": "2026-06-12",
        "net_amount_minor": 100,
        "tax_amount_minor": 19,
        "gross_amount_minor": 119,
    }
    invoice_values = {
        "tenant_id": "tenant-demo",
        "object_id": "erp-invoice-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-13T08:00:00Z",
        "updated_at_utc": "2026-06-13T08:00:00Z",
        "kms_key_ref": "kms:tenant-demo:erp-invoice",
        "audit_chain_ref": "audit:erp-invoice-invalid",
        "invoice_number": "ERP-I-INVALID",
        "invoice_date": "2026-06-13",
        "due_date": "2026-07-13",
        "net_amount_minor": 100,
        "tax_amount_minor": 19,
        "gross_amount_minor": 119,
    }

    with pytest.raises(ValidationError, match=r"erp\.order"):
        ErpOrderRecord.model_validate({**order_values, "object_type": "erp.invoice"})

    with pytest.raises(ValidationError, match="GoBD"):
        ErpInvoiceRecord.model_validate({**invoice_values, "data_classification": "internal"})

    with pytest.raises(ValidationError, match="gross_amount_minor"):
        ErpOrderRecord.model_validate({**order_values, "gross_amount_minor": 120})

    with pytest.raises(ValidationError, match="ISO 4217"):
        ErpInvoiceRecord.model_validate({**invoice_values, "currency_code": "eur"})


def test_erp_sales_service_returns_orders_only_for_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = sales_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "crm-account-acme-demo",
            "crm-account-northwind-demo",
            "erp-product-standard-widget-demo",
            "erp-product-service-plan-demo",
            "erp-order-acme-widget-demo",
            "erp-order-northwind-service-demo",
        },
    )

    response = service.list_orders(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_ORDERS_FEATURE_ID
    assert [order.order_number for order in response.orders] == ["ERP-O-1001", "ERP-O-1002"]
    assert all(order.object_type == ERP_ORDER_OBJECT_TYPE for order in response.orders)
    assert {order.data_classification for order in response.orders} == {DataClass.GOBD}
    assert all(order.retention_policy_id == "rp-gobd-10y" for order in response.orders)
    assert all(order.access_checked for order in response.orders)
    assert all(order.linked_refs_access_checked for order in response.orders)
    assert response.orders[0].account_object_id == "crm-account-acme-demo"
    assert response.orders[0].product_object_ids == ("erp-product-standard-widget-demo",)

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.order.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["erp-order-acme-widget-demo", "erp-order-northwind-service-demo"]
    assert event.metadata == {
        "feature_id": ERP_ORDERS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_ORDER_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_erp_sales_service_returns_invoices_only_for_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = sales_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "crm-account-acme-demo",
            "crm-account-northwind-demo",
            "erp-product-standard-widget-demo",
            "erp-product-service-plan-demo",
            "erp-order-acme-widget-demo",
            "erp-order-northwind-service-demo",
            "erp-invoice-acme-widget-demo",
            "erp-invoice-northwind-service-demo",
        },
    )

    response = service.list_invoices(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_INVOICES_FEATURE_ID
    assert [invoice.invoice_number for invoice in response.invoices] == ["ERP-I-1001", "ERP-I-1002"]
    assert all(invoice.object_type == ERP_INVOICE_OBJECT_TYPE for invoice in response.invoices)
    assert {invoice.data_classification for invoice in response.invoices} == {DataClass.GOBD}
    assert all(invoice.retention_policy_id == "rp-gobd-10y" for invoice in response.invoices)
    assert response.invoices[0].order_object_id == "erp-order-acme-widget-demo"
    assert response.invoices[0].account_object_id == "crm-account-acme-demo"
    assert response.invoices[0].product_object_ids == ("erp-product-standard-widget-demo",)

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.invoice.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["erp-invoice-acme-widget-demo", "erp-invoice-northwind-service-demo"]
    assert event.metadata == {
        "feature_id": ERP_INVOICES_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_INVOICE_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_erp_sales_service_filters_unreadable_sales_objects_and_linked_refs() -> None:
    audit_logger = InMemoryAuditLogger()
    service = sales_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"erp-order-acme-widget-demo", "erp-invoice-acme-widget-demo"},
    )

    orders = service.list_orders(user_context=user_context)
    invoices = service.list_invoices(user_context=user_context)

    assert [order.object_id for order in orders.orders] == ["erp-order-acme-widget-demo"]
    assert orders.orders[0].account_object_id is None
    assert orders.orders[0].product_object_ids == ()
    assert [invoice.object_id for invoice in invoices.invoices] == ["erp-invoice-acme-widget-demo"]
    assert invoices.invoices[0].order_object_id == "erp-order-acme-widget-demo"
    assert invoices.invoices[0].account_object_id is None
    assert invoices.invoices[0].product_object_ids == ()
    assert audit_logger.events[-2].metadata["candidate_count"] == 2
    assert audit_logger.events[-2].metadata["result_count"] == 1
    assert audit_logger.events[-1].metadata["candidate_count"] == 2
    assert audit_logger.events[-1].metadata["result_count"] == 1
