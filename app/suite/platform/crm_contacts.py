from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext

CRM_ERP_MODULE_ID = "crm_erp"
CRM_CONTACTS_FEATURE_ID = "crm_erp.crm.contacts"
CRM_CONTACT_OBJECT_TYPE = "crm.contact"
CRM_CONTACT_SCHEMA_VERSION = "crm_contact.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class CrmContactLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class CrmContactStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class CrmContactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = CRM_CONTACT_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: CrmContactLifecycleState = CrmContactLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = CRM_CONTACT_SCHEMA_VERSION
    account_object_id: str | None = None
    contact_number: str | None = None
    display_name: str
    given_name: str | None = None
    family_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    role_label: str | None = None
    status: CrmContactStatus = CrmContactStatus.ACTIVE

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "display_name",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM contact fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_contact_object_type(cls, value: str) -> str:
        if value != CRM_CONTACT_OBJECT_TYPE:
            raise ValueError("CRM contact records must use crm.contact object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_contact_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.PERSONAL:
            raise ValueError("CRM contacts are personal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("CRM contacts must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("CRM contact legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("CRM contact references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("CRM contact source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != CRM_CONTACT_SCHEMA_VERSION:
            raise ValueError("CRM contact schema_version must match crm_contact.v1")
        return value

    @field_validator(
        "account_object_id",
        "contact_number",
        "given_name",
        "family_name",
        "primary_email",
        "primary_phone",
        "role_label",
    )
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("CRM contact optional fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_restricted_lifecycle_when_status_is_restricted(self) -> CrmContactRecord:
        if self.status == CrmContactStatus.RESTRICTED and self.lifecycle_state != CrmContactLifecycleState.RESTRICTED:
            raise ValueError("restricted CRM contacts must use restricted lifecycle_state")
        return self


class CrmContactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    account_object_id: str | None = None
    contact_number: str | None = None
    display_name: str
    given_name: str | None = None
    family_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    role_label: str | None = None
    status: CrmContactStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: CrmContactLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_account_access_checked: bool = True


class CrmContactsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_CONTACTS_FEATURE_ID
    contacts: list[CrmContactView]
    audit_event_id: str


class CrmContactRepository(Protocol):
    def list_contacts(self, *, tenant_id: str) -> Sequence[CrmContactRecord]:
        pass


def crm_contact_view(record: CrmContactRecord, *, readable_object_ids: set[str]) -> CrmContactView:
    account_object_id = record.account_object_id
    if account_object_id is not None and account_object_id not in readable_object_ids:
        account_object_id = None
    return CrmContactView(
        object_id=record.object_id,
        object_type=record.object_type,
        account_object_id=account_object_id,
        contact_number=record.contact_number,
        display_name=record.display_name,
        given_name=record.given_name,
        family_name=record.family_name,
        primary_email=record.primary_email,
        primary_phone=record.primary_phone,
        role_label=record.role_label,
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


class InMemoryCrmContactRepository:
    def __init__(self, contacts: Sequence[CrmContactRecord]) -> None:
        self._contacts = tuple(contacts)

    @classmethod
    def demo(cls) -> InMemoryCrmContactRepository:
        return cls(
            contacts=(
                CrmContactRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-contact-ada-demo",
                    account_object_id="crm-account-acme-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:15:00Z",
                    updated_at_utc="2026-06-11T12:15:00Z",
                    kms_key_ref="kms:tenant-demo:crm-contact",
                    audit_chain_ref="audit:crm-contact-ada-demo",
                    contact_number="CRM-C-1001",
                    display_name="Ada Demo",
                    given_name="Ada",
                    family_name="Demo",
                    primary_email="ada.demo@example.invalid",
                    role_label="Procurement",
                ),
                CrmContactRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-contact-max-demo",
                    account_object_id="crm-account-northwind-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:20:00Z",
                    updated_at_utc="2026-06-11T12:20:00Z",
                    kms_key_ref="kms:tenant-demo:crm-contact",
                    audit_chain_ref="audit:crm-contact-max-demo",
                    contact_number="CRM-C-1002",
                    display_name="Max Demo",
                    given_name="Max",
                    family_name="Demo",
                    primary_email="max.demo@example.invalid",
                    role_label="Operations",
                ),
                CrmContactRecord(
                    tenant_id="tenant-other",
                    object_id="crm-contact-other-tenant",
                    account_object_id="crm-account-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T12:25:00Z",
                    updated_at_utc="2026-06-11T12:25:00Z",
                    kms_key_ref="kms:tenant-other:crm-contact",
                    audit_chain_ref="audit:crm-contact-other-tenant",
                    contact_number="CRM-C-9001",
                    display_name="Other Contact",
                    given_name="Other",
                    family_name="Contact",
                    primary_email="other.contact@example.invalid",
                ),
            )
        )

    def list_contacts(self, *, tenant_id: str) -> Sequence[CrmContactRecord]:
        return tuple(contact for contact in self._contacts if contact.tenant_id == tenant_id)


class CrmContactService:
    def __init__(self, *, repository: CrmContactRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_contacts(self, *, user_context: UserContext) -> CrmContactsResponse:
        candidate_records = sorted(
            self.repository.list_contacts(tenant_id=user_context.tenant_id),
            key=lambda record: (record.display_name.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [crm_contact_view(record, readable_object_ids=user_context.readable_object_ids) for record in records]
        redacted_account_links = sum(
            1
            for record, view in zip(records, views, strict=True)
            if record.account_object_id is not None and view.account_object_id is None
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.contact.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_CONTACTS_FEATURE_ID,
                "object_type": CRM_CONTACT_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "redacted_account_link_count": redacted_account_links,
                "result_contract": "metadata_only",
            },
        )
        return CrmContactsResponse(
            tenant_id=user_context.tenant_id,
            contacts=views,
            audit_event_id=event.event_id,
        )
