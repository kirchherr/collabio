from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.persistent_metadata import persistent_metadata_audit_metadata, validate_persistent_object_metadata

CRM_ERP_MODULE_ID = "crm_erp"
ERP_ORDERS_FEATURE_ID = "crm_erp.erp.orders"
ERP_INVOICES_FEATURE_ID = "crm_erp.erp.invoices"
ERP_ORDER_OBJECT_TYPE = "erp.order"
ERP_INVOICE_OBJECT_TYPE = "erp.invoice"
ERP_ORDER_SCHEMA_VERSION = "erp_order.v1"
ERP_INVOICE_SCHEMA_VERSION = "erp_invoice.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")
CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


class ErpSalesLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class ErpOrderStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class ErpInvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    CANCELLED = "cancelled"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class ErpOrderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = ERP_ORDER_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.GOBD
    retention_policy_id: str = "rp-gobd-10y"
    legal_hold_state: str = "none"
    lifecycle_state: ErpSalesLifecycleState = ErpSalesLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = ERP_ORDER_SCHEMA_VERSION
    order_number: str
    account_object_id: str | None = None
    product_object_ids: tuple[str, ...] = ()
    order_date: str
    currency_code: str = "EUR"
    net_amount_minor: int
    tax_amount_minor: int
    gross_amount_minor: int
    status: ErpOrderStatus = ErpOrderStatus.CONFIRMED

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "order_number",
        "order_date",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ERP order fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_order_object_type(cls, value: str) -> str:
        if value != ERP_ORDER_OBJECT_TYPE:
            raise ValueError("ERP order records must use erp.order object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_order_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.GOBD:
            raise ValueError("ERP orders must use GoBD classification")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_gobd_retention(cls, value: str) -> str:
        if value != "rp-gobd-10y":
            raise ValueError("ERP orders must start with rp-gobd-10y retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("ERP order legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("ERP order references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("ERP order source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != ERP_ORDER_SCHEMA_VERSION:
            raise ValueError("ERP order schema_version must match erp_order.v1")
        return value

    @field_validator("account_object_id")
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ERP order optional fields must not be empty")
        return value

    @field_validator("product_object_ids")
    @classmethod
    def validate_product_object_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("ERP order product_object_ids must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("ERP order product_object_ids must not be empty")
        return value

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, value: str) -> str:
        if not CURRENCY_CODE_PATTERN.fullmatch(value):
            raise ValueError("ERP order currency_code must be ISO 4217 style")
        return value

    @field_validator("net_amount_minor", "tax_amount_minor", "gross_amount_minor")
    @classmethod
    def require_non_negative_amounts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ERP order amounts must not be negative")
        return value

    @model_validator(mode="after")
    def require_consistent_order_record(self) -> ErpOrderRecord:
        validate_persistent_object_metadata(
            self,
            expected_object_type=ERP_ORDER_OBJECT_TYPE,
            expected_schema_version=ERP_ORDER_SCHEMA_VERSION,
            expected_classification=DataClass.GOBD,
        )
        if self.status == ErpOrderStatus.RESTRICTED and self.lifecycle_state != ErpSalesLifecycleState.RESTRICTED:
            raise ValueError("restricted ERP orders must use restricted lifecycle_state")
        if self.net_amount_minor + self.tax_amount_minor != self.gross_amount_minor:
            raise ValueError("ERP order gross_amount_minor must equal net plus tax")
        return self


class ErpInvoiceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = ERP_INVOICE_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.GOBD
    retention_policy_id: str = "rp-gobd-10y"
    legal_hold_state: str = "none"
    lifecycle_state: ErpSalesLifecycleState = ErpSalesLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = ERP_INVOICE_SCHEMA_VERSION
    invoice_number: str
    order_object_id: str | None = None
    account_object_id: str | None = None
    product_object_ids: tuple[str, ...] = ()
    invoice_date: str
    due_date: str
    currency_code: str = "EUR"
    net_amount_minor: int
    tax_amount_minor: int
    gross_amount_minor: int
    status: ErpInvoiceStatus = ErpInvoiceStatus.ISSUED

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "invoice_number",
        "invoice_date",
        "due_date",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ERP invoice fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_invoice_object_type(cls, value: str) -> str:
        if value != ERP_INVOICE_OBJECT_TYPE:
            raise ValueError("ERP invoice records must use erp.invoice object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_invoice_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.GOBD:
            raise ValueError("ERP invoices must use GoBD classification")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_gobd_retention(cls, value: str) -> str:
        if value != "rp-gobd-10y":
            raise ValueError("ERP invoices must start with rp-gobd-10y retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("ERP invoice legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("ERP invoice references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("ERP invoice source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != ERP_INVOICE_SCHEMA_VERSION:
            raise ValueError("ERP invoice schema_version must match erp_invoice.v1")
        return value

    @field_validator("order_object_id", "account_object_id")
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ERP invoice optional fields must not be empty")
        return value

    @field_validator("product_object_ids")
    @classmethod
    def validate_product_object_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("ERP invoice product_object_ids must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("ERP invoice product_object_ids must not be empty")
        return value

    @field_validator("currency_code")
    @classmethod
    def validate_currency_code(cls, value: str) -> str:
        if not CURRENCY_CODE_PATTERN.fullmatch(value):
            raise ValueError("ERP invoice currency_code must be ISO 4217 style")
        return value

    @field_validator("net_amount_minor", "tax_amount_minor", "gross_amount_minor")
    @classmethod
    def require_non_negative_amounts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ERP invoice amounts must not be negative")
        return value

    @model_validator(mode="after")
    def require_consistent_invoice_record(self) -> ErpInvoiceRecord:
        validate_persistent_object_metadata(
            self,
            expected_object_type=ERP_INVOICE_OBJECT_TYPE,
            expected_schema_version=ERP_INVOICE_SCHEMA_VERSION,
            expected_classification=DataClass.GOBD,
        )
        if self.status == ErpInvoiceStatus.RESTRICTED and self.lifecycle_state != ErpSalesLifecycleState.RESTRICTED:
            raise ValueError("restricted ERP invoices must use restricted lifecycle_state")
        if self.net_amount_minor + self.tax_amount_minor != self.gross_amount_minor:
            raise ValueError("ERP invoice gross_amount_minor must equal net plus tax")
        return self


class ErpOrderView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    order_number: str
    account_object_id: str | None = None
    product_object_ids: tuple[str, ...]
    order_date: str
    currency_code: str
    net_amount_minor: int
    tax_amount_minor: int
    gross_amount_minor: int
    status: ErpOrderStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: ErpSalesLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_refs_access_checked: bool = True


class ErpInvoiceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    invoice_number: str
    order_object_id: str | None = None
    account_object_id: str | None = None
    product_object_ids: tuple[str, ...]
    invoice_date: str
    due_date: str
    currency_code: str
    net_amount_minor: int
    tax_amount_minor: int
    gross_amount_minor: int
    status: ErpInvoiceStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: ErpSalesLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_refs_access_checked: bool = True


class ErpOrdersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = ERP_ORDERS_FEATURE_ID
    orders: list[ErpOrderView]
    audit_event_id: str


class ErpInvoicesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = ERP_INVOICES_FEATURE_ID
    invoices: list[ErpInvoiceView]
    audit_event_id: str


class ErpOrderRepository(Protocol):
    def list_orders(self, *, tenant_id: str) -> Sequence[ErpOrderRecord]:
        pass


class ErpInvoiceRepository(Protocol):
    def list_invoices(self, *, tenant_id: str) -> Sequence[ErpInvoiceRecord]:
        pass


def erp_order_view(record: ErpOrderRecord, *, readable_object_ids: set[str]) -> ErpOrderView:
    account_object_id = record.account_object_id
    if account_object_id is not None and account_object_id not in readable_object_ids:
        account_object_id = None
    product_object_ids = tuple(
        product_object_id for product_object_id in record.product_object_ids if product_object_id in readable_object_ids
    )
    return ErpOrderView(
        object_id=record.object_id,
        object_type=record.object_type,
        order_number=record.order_number,
        account_object_id=account_object_id,
        product_object_ids=product_object_ids,
        order_date=record.order_date,
        currency_code=record.currency_code,
        net_amount_minor=record.net_amount_minor,
        tax_amount_minor=record.tax_amount_minor,
        gross_amount_minor=record.gross_amount_minor,
        status=record.status,
        owner_principal_id=record.owner_principal_id,
        created_at_utc=record.created_at_utc,
        updated_at_utc=record.updated_at_utc,
        data_classification=record.data_classification,
        retention_policy_id=record.retention_policy_id,
        legal_hold_state=record.legal_hold_state,
        lifecycle_state=record.lifecycle_state,
        source_system=record.source_system,
        schema_version=record.schema_version,
        audit_chain_ref=record.audit_chain_ref,
    )


def erp_invoice_view(record: ErpInvoiceRecord, *, readable_object_ids: set[str]) -> ErpInvoiceView:
    order_object_id = record.order_object_id
    if order_object_id is not None and order_object_id not in readable_object_ids:
        order_object_id = None
    account_object_id = record.account_object_id
    if account_object_id is not None and account_object_id not in readable_object_ids:
        account_object_id = None
    product_object_ids = tuple(
        product_object_id for product_object_id in record.product_object_ids if product_object_id in readable_object_ids
    )
    return ErpInvoiceView(
        object_id=record.object_id,
        object_type=record.object_type,
        invoice_number=record.invoice_number,
        order_object_id=order_object_id,
        account_object_id=account_object_id,
        product_object_ids=product_object_ids,
        invoice_date=record.invoice_date,
        due_date=record.due_date,
        currency_code=record.currency_code,
        net_amount_minor=record.net_amount_minor,
        tax_amount_minor=record.tax_amount_minor,
        gross_amount_minor=record.gross_amount_minor,
        status=record.status,
        owner_principal_id=record.owner_principal_id,
        created_at_utc=record.created_at_utc,
        updated_at_utc=record.updated_at_utc,
        data_classification=record.data_classification,
        retention_policy_id=record.retention_policy_id,
        legal_hold_state=record.legal_hold_state,
        lifecycle_state=record.lifecycle_state,
        source_system=record.source_system,
        schema_version=record.schema_version,
        audit_chain_ref=record.audit_chain_ref,
    )


class InMemoryErpOrderRepository:
    def __init__(self, orders: Sequence[ErpOrderRecord]) -> None:
        self._orders = tuple(orders)

    @classmethod
    def demo(cls) -> InMemoryErpOrderRepository:
        return cls(
            orders=(
                ErpOrderRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-order-acme-widget-demo",
                    account_object_id="crm-account-acme-demo",
                    product_object_ids=("erp-product-standard-widget-demo",),
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-12T09:00:00Z",
                    updated_at_utc="2026-06-12T09:00:00Z",
                    kms_key_ref="kms:tenant-demo:erp-order",
                    audit_chain_ref="audit:erp-order-acme-widget-demo",
                    order_number="ERP-O-1001",
                    order_date="2026-06-12",
                    net_amount_minor=100_000,
                    tax_amount_minor=19_000,
                    gross_amount_minor=119_000,
                ),
                ErpOrderRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-order-northwind-service-demo",
                    account_object_id="crm-account-northwind-demo",
                    product_object_ids=("erp-product-service-plan-demo",),
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-12T09:15:00Z",
                    updated_at_utc="2026-06-12T09:45:00Z",
                    kms_key_ref="kms:tenant-demo:erp-order",
                    audit_chain_ref="audit:erp-order-northwind-service-demo",
                    order_number="ERP-O-1002",
                    order_date="2026-06-12",
                    net_amount_minor=24_000,
                    tax_amount_minor=4_560,
                    gross_amount_minor=28_560,
                    status=ErpOrderStatus.FULFILLED,
                ),
                ErpOrderRecord(
                    tenant_id="tenant-other",
                    object_id="erp-order-other-tenant",
                    account_object_id="crm-account-other-tenant",
                    product_object_ids=("erp-product-other-tenant",),
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-12T10:00:00Z",
                    updated_at_utc="2026-06-12T10:00:00Z",
                    kms_key_ref="kms:tenant-other:erp-order",
                    audit_chain_ref="audit:erp-order-other-tenant",
                    order_number="ERP-O-9001",
                    order_date="2026-06-12",
                    net_amount_minor=10_000,
                    tax_amount_minor=1_900,
                    gross_amount_minor=11_900,
                ),
            )
        )

    def list_orders(self, *, tenant_id: str) -> Sequence[ErpOrderRecord]:
        return tuple(order for order in self._orders if order.tenant_id == tenant_id)


class InMemoryErpInvoiceRepository:
    def __init__(self, invoices: Sequence[ErpInvoiceRecord]) -> None:
        self._invoices = tuple(invoices)

    @classmethod
    def demo(cls) -> InMemoryErpInvoiceRepository:
        return cls(
            invoices=(
                ErpInvoiceRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-invoice-acme-widget-demo",
                    order_object_id="erp-order-acme-widget-demo",
                    account_object_id="crm-account-acme-demo",
                    product_object_ids=("erp-product-standard-widget-demo",),
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-13T08:00:00Z",
                    updated_at_utc="2026-06-13T08:00:00Z",
                    kms_key_ref="kms:tenant-demo:erp-invoice",
                    audit_chain_ref="audit:erp-invoice-acme-widget-demo",
                    invoice_number="ERP-I-1001",
                    invoice_date="2026-06-13",
                    due_date="2026-07-13",
                    net_amount_minor=100_000,
                    tax_amount_minor=19_000,
                    gross_amount_minor=119_000,
                ),
                ErpInvoiceRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-invoice-northwind-service-demo",
                    order_object_id="erp-order-northwind-service-demo",
                    account_object_id="crm-account-northwind-demo",
                    product_object_ids=("erp-product-service-plan-demo",),
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-13T08:15:00Z",
                    updated_at_utc="2026-06-13T08:45:00Z",
                    kms_key_ref="kms:tenant-demo:erp-invoice",
                    audit_chain_ref="audit:erp-invoice-northwind-service-demo",
                    invoice_number="ERP-I-1002",
                    invoice_date="2026-06-13",
                    due_date="2026-07-13",
                    net_amount_minor=24_000,
                    tax_amount_minor=4_560,
                    gross_amount_minor=28_560,
                    status=ErpInvoiceStatus.PAID,
                ),
                ErpInvoiceRecord(
                    tenant_id="tenant-other",
                    object_id="erp-invoice-other-tenant",
                    order_object_id="erp-order-other-tenant",
                    account_object_id="crm-account-other-tenant",
                    product_object_ids=("erp-product-other-tenant",),
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-13T09:00:00Z",
                    updated_at_utc="2026-06-13T09:00:00Z",
                    kms_key_ref="kms:tenant-other:erp-invoice",
                    audit_chain_ref="audit:erp-invoice-other-tenant",
                    invoice_number="ERP-I-9001",
                    invoice_date="2026-06-13",
                    due_date="2026-07-13",
                    net_amount_minor=10_000,
                    tax_amount_minor=1_900,
                    gross_amount_minor=11_900,
                ),
            )
        )

    def list_invoices(self, *, tenant_id: str) -> Sequence[ErpInvoiceRecord]:
        return tuple(invoice for invoice in self._invoices if invoice.tenant_id == tenant_id)


class ErpSalesService:
    def __init__(
        self,
        *,
        order_repository: ErpOrderRepository,
        invoice_repository: ErpInvoiceRepository,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.order_repository = order_repository
        self.invoice_repository = invoice_repository
        self.audit_logger = audit_logger

    def list_orders(self, *, user_context: UserContext) -> ErpOrdersResponse:
        candidate_records = sorted(
            self.order_repository.list_orders(tenant_id=user_context.tenant_id),
            key=lambda record: (record.order_date, record.order_number, record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [erp_order_view(record, readable_object_ids=user_context.readable_object_ids) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="erp.order.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": ERP_ORDERS_FEATURE_ID,
                "object_type": ERP_ORDER_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
                **persistent_metadata_audit_metadata(),
            },
        )
        return ErpOrdersResponse(
            tenant_id=user_context.tenant_id,
            orders=views,
            audit_event_id=event.event_id,
        )

    def list_invoices(self, *, user_context: UserContext) -> ErpInvoicesResponse:
        candidate_records = sorted(
            self.invoice_repository.list_invoices(tenant_id=user_context.tenant_id),
            key=lambda record: (record.invoice_date, record.invoice_number, record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [erp_invoice_view(record, readable_object_ids=user_context.readable_object_ids) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="erp.invoice.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": ERP_INVOICES_FEATURE_ID,
                "object_type": ERP_INVOICE_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
                **persistent_metadata_audit_metadata(),
            },
        )
        return ErpInvoicesResponse(
            tenant_id=user_context.tenant_id,
            invoices=views,
            audit_event_id=event.event_id,
        )
