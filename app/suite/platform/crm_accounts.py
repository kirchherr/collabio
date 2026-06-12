from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext

CRM_ERP_MODULE_ID = "crm_erp"
CRM_ACCOUNTS_FEATURE_ID = "crm_erp.crm.accounts"
CRM_ACCOUNT_OBJECT_TYPE = "crm.account"
CRM_ACCOUNT_SCHEMA_VERSION = "crm_account.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class CrmAccountLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class CrmAccountKind(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"


class CrmAccountStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class CrmAccountRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = CRM_ACCOUNT_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: CrmAccountLifecycleState = CrmAccountLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = CRM_ACCOUNT_SCHEMA_VERSION
    account_number: str | None = None
    display_name: str
    account_kind: CrmAccountKind = CrmAccountKind.ORGANIZATION
    status: CrmAccountStatus = CrmAccountStatus.ACTIVE

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
            raise ValueError("CRM account fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_account_object_type(cls, value: str) -> str:
        if value != CRM_ACCOUNT_OBJECT_TYPE:
            raise ValueError("CRM account records must use crm.account object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_account_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.PERSONAL:
            raise ValueError("CRM accounts are personal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("CRM accounts must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("CRM account legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("CRM account references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("CRM account source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != CRM_ACCOUNT_SCHEMA_VERSION:
            raise ValueError("CRM account schema_version must match crm_account.v1")
        return value

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("CRM account account_number must not be empty")
        return value

    @model_validator(mode="after")
    def require_restricted_lifecycle_when_status_is_restricted(self) -> CrmAccountRecord:
        if self.status == CrmAccountStatus.RESTRICTED and self.lifecycle_state != CrmAccountLifecycleState.RESTRICTED:
            raise ValueError("restricted CRM accounts must use restricted lifecycle_state")
        return self


class CrmAccountView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    account_number: str | None = None
    display_name: str
    account_kind: CrmAccountKind
    status: CrmAccountStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: CrmAccountLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class CrmAccountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ACCOUNTS_FEATURE_ID
    accounts: list[CrmAccountView]
    audit_event_id: str


class CrmAccountRepository(Protocol):
    def list_accounts(self, *, tenant_id: str) -> Sequence[CrmAccountRecord]:
        pass


def crm_account_view(record: CrmAccountRecord) -> CrmAccountView:
    return CrmAccountView(
        object_id=record.object_id,
        object_type=record.object_type,
        account_number=record.account_number,
        display_name=record.display_name,
        account_kind=record.account_kind,
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


class InMemoryCrmAccountRepository:
    def __init__(self, accounts: Sequence[CrmAccountRecord]) -> None:
        self._accounts = tuple(accounts)

    @classmethod
    def demo(cls) -> InMemoryCrmAccountRepository:
        return cls(
            accounts=(
                CrmAccountRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-account-acme-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:00:00Z",
                    updated_at_utc="2026-06-11T12:00:00Z",
                    kms_key_ref="kms:tenant-demo:crm-account",
                    audit_chain_ref="audit:crm-account-acme-demo",
                    account_number="CRM-1001",
                    display_name="Acme Demo GmbH",
                ),
                CrmAccountRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-account-northwind-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:05:00Z",
                    updated_at_utc="2026-06-11T12:05:00Z",
                    kms_key_ref="kms:tenant-demo:crm-account",
                    audit_chain_ref="audit:crm-account-northwind-demo",
                    account_number="CRM-1002",
                    display_name="Northwind Demo AG",
                ),
                CrmAccountRecord(
                    tenant_id="tenant-other",
                    object_id="crm-account-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T12:10:00Z",
                    updated_at_utc="2026-06-11T12:10:00Z",
                    kms_key_ref="kms:tenant-other:crm-account",
                    audit_chain_ref="audit:crm-account-other-tenant",
                    account_number="CRM-9001",
                    display_name="Other Tenant AG",
                ),
            )
        )

    def list_accounts(self, *, tenant_id: str) -> Sequence[CrmAccountRecord]:
        return tuple(account for account in self._accounts if account.tenant_id == tenant_id)


class CrmAccountService:
    def __init__(self, *, repository: CrmAccountRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_accounts(self, *, user_context: UserContext) -> CrmAccountsResponse:
        candidate_records = sorted(
            self.repository.list_accounts(tenant_id=user_context.tenant_id),
            key=lambda record: (record.display_name.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [crm_account_view(record) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.account.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ACCOUNTS_FEATURE_ID,
                "object_type": CRM_ACCOUNT_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "result_contract": "metadata_only",
            },
        )
        return CrmAccountsResponse(
            tenant_id=user_context.tenant_id,
            accounts=views,
            audit_event_id=event.event_id,
        )
