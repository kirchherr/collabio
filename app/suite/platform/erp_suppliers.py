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
ERP_SUPPLIERS_FEATURE_ID = "crm_erp.erp.suppliers"
ERP_SUPPLIER_OBJECT_TYPE = "erp.supplier"
ERP_SUPPLIER_SCHEMA_VERSION = "erp_supplier.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


class ErpSupplierKind(StrEnum):
    ORGANIZATION = "organization"
    INDIVIDUAL = "individual"
    SERVICE_PROVIDER = "service_provider"


class ErpSupplierStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class ErpSupplierLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class ErpSupplierRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = ERP_SUPPLIER_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: ErpSupplierLifecycleState = ErpSupplierLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = ERP_SUPPLIER_SCHEMA_VERSION
    supplier_number: str
    display_name: str
    supplier_kind: ErpSupplierKind = ErpSupplierKind.ORGANIZATION
    primary_contact_label: str | None = None
    country_code: str = "DE"
    status: ErpSupplierStatus = ErpSupplierStatus.ACTIVE

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "supplier_number",
        "display_name",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ERP supplier fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_supplier_object_type(cls, value: str) -> str:
        if value != ERP_SUPPLIER_OBJECT_TYPE:
            raise ValueError("ERP supplier records must use erp.supplier object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_supplier_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.PERSONAL:
            raise ValueError("ERP suppliers must use personal classification by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("ERP suppliers must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("ERP supplier legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("ERP supplier references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("ERP supplier source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != ERP_SUPPLIER_SCHEMA_VERSION:
            raise ValueError("ERP supplier schema_version must match erp_supplier.v1")
        return value

    @field_validator("primary_contact_label")
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ERP supplier optional fields must not be empty")
        return value

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        if not COUNTRY_CODE_PATTERN.fullmatch(value):
            raise ValueError("ERP supplier country_code must be ISO 3166 alpha-2 style")
        return value

    @model_validator(mode="after")
    def require_consistent_supplier_record(self) -> ErpSupplierRecord:
        validate_persistent_object_metadata(
            self,
            expected_object_type=ERP_SUPPLIER_OBJECT_TYPE,
            expected_schema_version=ERP_SUPPLIER_SCHEMA_VERSION,
            expected_classification=DataClass.PERSONAL,
        )
        if self.status == ErpSupplierStatus.RESTRICTED and self.lifecycle_state != ErpSupplierLifecycleState.RESTRICTED:
            raise ValueError("restricted ERP suppliers must use restricted lifecycle_state")
        return self


class ErpSupplierView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    supplier_number: str
    display_name: str
    supplier_kind: ErpSupplierKind
    primary_contact_label: str | None = None
    country_code: str
    status: ErpSupplierStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: ErpSupplierLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class ErpSuppliersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = ERP_SUPPLIERS_FEATURE_ID
    suppliers: list[ErpSupplierView]
    audit_event_id: str


class ErpSupplierRepository(Protocol):
    def list_suppliers(self, *, tenant_id: str) -> Sequence[ErpSupplierRecord]:
        pass


def erp_supplier_view(record: ErpSupplierRecord) -> ErpSupplierView:
    return ErpSupplierView(
        object_id=record.object_id,
        object_type=record.object_type,
        supplier_number=record.supplier_number,
        display_name=record.display_name,
        supplier_kind=record.supplier_kind,
        primary_contact_label=record.primary_contact_label,
        country_code=record.country_code,
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


class InMemoryErpSupplierRepository:
    def __init__(self, suppliers: Sequence[ErpSupplierRecord]) -> None:
        self._suppliers = tuple(suppliers)

    @classmethod
    def demo(cls) -> InMemoryErpSupplierRepository:
        return cls(
            suppliers=(
                ErpSupplierRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-supplier-contoso-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T14:00:00Z",
                    updated_at_utc="2026-06-11T14:00:00Z",
                    kms_key_ref="kms:tenant-demo:erp-supplier",
                    audit_chain_ref="audit:erp-supplier-contoso-demo",
                    supplier_number="ERP-S-1001",
                    display_name="Contoso Components",
                    primary_contact_label="Contoso procurement desk",
                    country_code="DE",
                ),
                ErpSupplierRecord(
                    tenant_id="tenant-demo",
                    object_id="erp-supplier-fabrikam-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T14:05:00Z",
                    updated_at_utc="2026-06-11T14:05:00Z",
                    kms_key_ref="kms:tenant-demo:erp-supplier",
                    audit_chain_ref="audit:erp-supplier-fabrikam-demo",
                    supplier_number="ERP-S-1002",
                    display_name="Fabrikam Services",
                    supplier_kind=ErpSupplierKind.SERVICE_PROVIDER,
                    primary_contact_label="Fabrikam service desk",
                    country_code="NL",
                ),
                ErpSupplierRecord(
                    tenant_id="tenant-other",
                    object_id="erp-supplier-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T14:10:00Z",
                    updated_at_utc="2026-06-11T14:10:00Z",
                    kms_key_ref="kms:tenant-other:erp-supplier",
                    audit_chain_ref="audit:erp-supplier-other-tenant",
                    supplier_number="ERP-S-9001",
                    display_name="Other Tenant Supplier",
                    primary_contact_label="Other tenant desk",
                ),
            )
        )

    def list_suppliers(self, *, tenant_id: str) -> Sequence[ErpSupplierRecord]:
        return tuple(supplier for supplier in self._suppliers if supplier.tenant_id == tenant_id)


class ErpSupplierService:
    def __init__(self, *, repository: ErpSupplierRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_suppliers(self, *, user_context: UserContext) -> ErpSuppliersResponse:
        candidate_records = sorted(
            self.repository.list_suppliers(tenant_id=user_context.tenant_id),
            key=lambda record: (record.display_name.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [erp_supplier_view(record) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="erp.supplier.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": ERP_SUPPLIERS_FEATURE_ID,
                "object_type": ERP_SUPPLIER_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
                **persistent_metadata_audit_metadata(),
            },
        )
        return ErpSuppliersResponse(
            tenant_id=user_context.tenant_id,
            suppliers=views,
            audit_event_id=event.event_id,
        )
