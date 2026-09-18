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
ERP_PRODUCTS_FEATURE_ID = "crm_erp.erp.products"
ERP_PRODUCT_OBJECT_TYPE = "erp.product"
ERP_PRODUCT_SCHEMA_VERSION = "erp_product.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class ErpProductKind(StrEnum):
    GOOD = "good"
    SERVICE = "service"
    BUNDLE = "bundle"


class ErpProductStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class ErpProductLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class ErpProductRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = ERP_PRODUCT_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.INTERNAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: ErpProductLifecycleState = ErpProductLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = ERP_PRODUCT_SCHEMA_VERSION
    product_number: str
    display_name: str
    product_kind: ErpProductKind = ErpProductKind.GOOD
    unit_code: str = "pcs"
    status: ErpProductStatus = ErpProductStatus.ACTIVE

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "product_number",
        "display_name",
        "unit_code",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ERP product fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_product_object_type(cls, value: str) -> str:
        if value != ERP_PRODUCT_OBJECT_TYPE:
            raise ValueError("ERP product records must use erp.product object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_product_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.INTERNAL:
            raise ValueError("ERP products are internal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("ERP products must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("ERP product legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("ERP product references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("ERP product source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != ERP_PRODUCT_SCHEMA_VERSION:
            raise ValueError("ERP product schema_version must match erp_product.v1")
        return value

    @model_validator(mode="after")
    def require_restricted_lifecycle_when_status_is_restricted(self) -> ErpProductRecord:
        validate_persistent_object_metadata(
            self,
            expected_object_type=ERP_PRODUCT_OBJECT_TYPE,
            expected_schema_version=ERP_PRODUCT_SCHEMA_VERSION,
            expected_classification=DataClass.INTERNAL,
        )
        if self.status == ErpProductStatus.RESTRICTED and self.lifecycle_state != ErpProductLifecycleState.RESTRICTED:
            raise ValueError("restricted ERP products must use restricted lifecycle_state")
        return self


class ErpProductView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    product_number: str
    display_name: str
    product_kind: ErpProductKind
    unit_code: str
    status: ErpProductStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: ErpProductLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class ErpProductsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = ERP_PRODUCTS_FEATURE_ID
    products: list[ErpProductView]
    audit_event_id: str


class ErpProductRepository(Protocol):
    def list_products(self, *, tenant_id: str) -> Sequence[ErpProductRecord]:
        pass


def erp_product_view(record: ErpProductRecord) -> ErpProductView:
    return ErpProductView(
        object_id=record.object_id,
        object_type=record.object_type,
        product_number=record.product_number,
        display_name=record.display_name,
        product_kind=record.product_kind,
        unit_code=record.unit_code,
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


class InMemoryErpProductRepository:
    def __init__(self, products: Sequence[ErpProductRecord]) -> None:
        self._products = tuple(products)

    @classmethod
    def demo(cls) -> InMemoryErpProductRepository:
        return cls(
            products=(
                ErpProductRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-product-standard-widget-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T13:00:00Z",
                    updated_at_utc="2026-06-11T13:00:00Z",
                    kms_key_ref="kms:tenant-demo:erp-product",
                    audit_chain_ref="audit:erp-product-standard-widget-demo",
                    product_number="ERP-P-1001",
                    display_name="Standard Widget",
                    unit_code="pcs",
                ),
                ErpProductRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-product-service-plan-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T13:05:00Z",
                    updated_at_utc="2026-06-11T13:05:00Z",
                    kms_key_ref="kms:tenant-demo:erp-product",
                    audit_chain_ref="audit:erp-product-service-plan-demo",
                    product_number="ERP-P-1002",
                    display_name="Service Plan",
                    product_kind=ErpProductKind.SERVICE,
                    unit_code="hour",
                ),
                ErpProductRecord(
                    tenant_id="tenant-other",
                    object_id="erp-product-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T13:10:00Z",
                    updated_at_utc="2026-06-11T13:10:00Z",
                    kms_key_ref="kms:tenant-other:erp-product",
                    audit_chain_ref="audit:erp-product-other-tenant",
                    product_number="ERP-P-9001",
                    display_name="Other Tenant Product",
                ),
            )
        )

    def list_products(self, *, tenant_id: str) -> Sequence[ErpProductRecord]:
        return tuple(product for product in self._products if product.tenant_id == tenant_id)


class ErpProductService:
    def __init__(self, *, repository: ErpProductRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_products(self, *, user_context: UserContext) -> ErpProductsResponse:
        candidate_records = sorted(
            self.repository.list_products(tenant_id=user_context.tenant_id),
            key=lambda record: (record.display_name.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [erp_product_view(record) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="erp.product.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": ERP_PRODUCTS_FEATURE_ID,
                "object_type": ERP_PRODUCT_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
                **persistent_metadata_audit_metadata(),
            },
        )
        return ErpProductsResponse(
            tenant_id=user_context.tenant_id,
            products=views,
            audit_event_id=event.event_id,
        )
