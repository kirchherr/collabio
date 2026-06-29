import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.erp_sales import (
    CRM_ERP_MODULE_ID,
    ERP_INVOICE_ITEM_OBJECT_TYPE,
    ERP_INVOICE_OBJECT_TYPE,
    ERP_INVOICES_FEATURE_ID,
    ERP_ORDER_ITEM_OBJECT_TYPE,
    ERP_ORDER_OBJECT_TYPE,
    ERP_ORDERS_FEATURE_ID,
    ErpInvoiceItemRecord,
    ErpInvoiceRecord,
    ErpOrderItemRecord,
    ErpOrderRecord,
    ErpSalesService,
    InMemoryErpInvoiceItemRepository,
    InMemoryErpInvoiceRepository,
    InMemoryErpOrderItemRepository,
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
        order_item_repository=InMemoryErpOrderItemRepository.demo(),
        invoice_item_repository=InMemoryErpInvoiceItemRepository.demo(),
        audit_logger=audit_logger,
    )


def test_erp_sales_records_require_gobd_compliance_metadata() -> None:
    order = InMemoryErpOrderRepository.demo().list_orders(tenant_id="tenant-demo")[0]
    invoice = InMemoryErpInvoiceRepository.demo().list_invoices(tenant_id="tenant-demo")[0]
    order_item = InMemoryErpOrderItemRepository.demo().list_order_items(tenant_id="tenant-demo")[0]
    invoice_item = InMemoryErpInvoiceItemRepository.demo().list_invoice_items(tenant_id="tenant-demo")[0]

    assert order.object_type == ERP_ORDER_OBJECT_TYPE
    assert invoice.object_type == ERP_INVOICE_OBJECT_TYPE
    assert order_item.object_type == ERP_ORDER_ITEM_OBJECT_TYPE
    assert invoice_item.object_type == ERP_INVOICE_ITEM_OBJECT_TYPE
    assert order.data_classification == DataClass.GOBD
    assert invoice.data_classification == DataClass.GOBD
    assert order_item.data_classification == DataClass.GOBD
    assert invoice_item.data_classification == DataClass.GOBD
    assert order.retention_policy_id == "rp-gobd-10y"
    assert invoice.retention_policy_id == "rp-gobd-10y"
    assert order_item.retention_policy_id == "rp-gobd-10y"
    assert invoice_item.retention_policy_id == "rp-gobd-10y"
    assert order.legal_hold_state == "none"
    assert invoice.legal_hold_state == "none"
    assert order_item.legal_hold_state == "none"
    assert invoice_item.legal_hold_state == "none"
    assert order.kms_key_ref.startswith("kms:")
    assert invoice.kms_key_ref.startswith("kms:")
    assert order_item.kms_key_ref.startswith("kms:")
    assert invoice_item.kms_key_ref.startswith("kms:")
    assert order.audit_chain_ref.startswith("audit:")
    assert invoice.audit_chain_ref.startswith("audit:")
    assert order_item.audit_chain_ref.startswith("audit:")
    assert invoice_item.audit_chain_ref.startswith("audit:")
    assert order.schema_version == "erp_order.v1"
    assert invoice.schema_version == "erp_invoice.v1"
    assert order_item.schema_version == "erp_order_item.v1"
    assert invoice_item.schema_version == "erp_invoice_item.v1"


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

    order_item_values = InMemoryErpOrderItemRepository.demo().list_order_items(tenant_id="tenant-demo")[0].model_dump()
    invoice_item_values = (
        InMemoryErpInvoiceItemRepository.demo().list_invoice_items(tenant_id="tenant-demo")[0].model_dump()
    )

    with pytest.raises(ValidationError, match=r"erp\.order_item"):
        ErpOrderItemRecord.model_validate({**order_item_values, "object_type": ERP_ORDER_OBJECT_TYPE})

    with pytest.raises(ValidationError, match="quantity_milli"):
        ErpOrderItemRecord.model_validate({**order_item_values, "quantity_milli": 0})

    with pytest.raises(ValidationError, match="gross_amount_minor"):
        ErpInvoiceItemRecord.model_validate(
            {**invoice_item_values, "gross_amount_minor": invoice_item_values["gross_amount_minor"] + 1}
        )


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
        readable_object_ids={
            "erp-order-acme-widget-demo",
            "erp-invoice-acme-widget-demo",
            "erp-order-item-acme-widget-demo",
            "erp-invoice-item-acme-widget-demo",
        },
    )

    orders = service.list_orders(user_context=user_context)
    invoices = service.list_invoices(user_context=user_context)
    order_items = service.list_order_items(user_context=user_context)
    invoice_items = service.list_invoice_items(user_context=user_context)

    assert [order.object_id for order in orders.orders] == ["erp-order-acme-widget-demo"]
    assert orders.orders[0].account_object_id is None
    assert orders.orders[0].product_object_ids == ()
    assert [invoice.object_id for invoice in invoices.invoices] == ["erp-invoice-acme-widget-demo"]
    assert invoices.invoices[0].order_object_id == "erp-order-acme-widget-demo"
    assert invoices.invoices[0].account_object_id is None
    assert invoices.invoices[0].product_object_ids == ()
    assert [item.object_id for item in order_items.order_items] == ["erp-order-item-acme-widget-demo"]
    assert order_items.order_items[0].order_object_id == "erp-order-acme-widget-demo"
    assert order_items.order_items[0].product_object_id is None
    assert [item.object_id for item in invoice_items.invoice_items] == ["erp-invoice-item-acme-widget-demo"]
    assert invoice_items.invoice_items[0].invoice_object_id == "erp-invoice-acme-widget-demo"
    assert invoice_items.invoice_items[0].order_item_object_id == "erp-order-item-acme-widget-demo"
    assert invoice_items.invoice_items[0].product_object_id is None
    assert audit_logger.events[-4].metadata["candidate_count"] == 2
    assert audit_logger.events[-4].metadata["result_count"] == 1
    assert audit_logger.events[-3].metadata["candidate_count"] == 2
    assert audit_logger.events[-3].metadata["result_count"] == 1
    assert audit_logger.events[-2].metadata["candidate_count"] == 2
    assert audit_logger.events[-2].metadata["result_count"] == 1
    assert audit_logger.events[-2].metadata["redacted_link_count"] == 1
    assert audit_logger.events[-1].metadata["candidate_count"] == 2
    assert audit_logger.events[-1].metadata["result_count"] == 1
    assert audit_logger.events[-1].metadata["redacted_link_count"] == 1


def test_erp_sales_service_returns_order_items_only_for_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = sales_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "erp-order-acme-widget-demo",
            "erp-order-northwind-service-demo",
            "erp-order-item-acme-widget-demo",
            "erp-order-item-northwind-service-demo",
            "erp-product-standard-widget-demo",
            "erp-product-service-plan-demo",
        },
    )

    response = service.list_order_items(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_ORDERS_FEATURE_ID
    assert [item.object_id for item in response.order_items] == [
        "erp-order-item-acme-widget-demo",
        "erp-order-item-northwind-service-demo",
    ]
    assert all(item.object_type == ERP_ORDER_ITEM_OBJECT_TYPE for item in response.order_items)
    assert {item.data_classification for item in response.order_items} == {DataClass.GOBD}
    assert all(item.retention_policy_id == "rp-gobd-10y" for item in response.order_items)
    assert all(item.access_checked for item in response.order_items)
    assert all(item.linked_refs_access_checked for item in response.order_items)
    assert response.order_items[0].order_object_id == "erp-order-acme-widget-demo"
    assert response.order_items[0].product_object_id == "erp-product-standard-widget-demo"

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.order_item.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == [
        "erp-order-item-acme-widget-demo",
        "erp-order-item-northwind-service-demo",
    ]
    assert event.metadata == {
        "feature_id": ERP_ORDERS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_ORDER_ITEM_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "redacted_link_count": 0,
        "result_count": 2,
    }


def test_erp_sales_service_returns_invoice_items_only_for_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = sales_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "erp-invoice-acme-widget-demo",
            "erp-invoice-northwind-service-demo",
            "erp-invoice-item-acme-widget-demo",
            "erp-invoice-item-northwind-service-demo",
            "erp-order-item-acme-widget-demo",
            "erp-order-item-northwind-service-demo",
            "erp-product-standard-widget-demo",
            "erp-product-service-plan-demo",
        },
    )

    response = service.list_invoice_items(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_INVOICES_FEATURE_ID
    assert [item.object_id for item in response.invoice_items] == [
        "erp-invoice-item-acme-widget-demo",
        "erp-invoice-item-northwind-service-demo",
    ]
    assert all(item.object_type == ERP_INVOICE_ITEM_OBJECT_TYPE for item in response.invoice_items)
    assert {item.data_classification for item in response.invoice_items} == {DataClass.GOBD}
    assert all(item.retention_policy_id == "rp-gobd-10y" for item in response.invoice_items)
    assert response.invoice_items[0].invoice_object_id == "erp-invoice-acme-widget-demo"
    assert response.invoice_items[0].order_item_object_id == "erp-order-item-acme-widget-demo"
    assert response.invoice_items[0].product_object_id == "erp-product-standard-widget-demo"

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.invoice_item.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == [
        "erp-invoice-item-acme-widget-demo",
        "erp-invoice-item-northwind-service-demo",
    ]
    assert event.metadata == {
        "feature_id": ERP_INVOICES_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_INVOICE_ITEM_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "redacted_link_count": 0,
        "result_count": 2,
    }
