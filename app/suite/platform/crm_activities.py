from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext

CRM_ERP_MODULE_ID = "crm_erp"
CRM_ACTIVITIES_FEATURE_ID = "crm_erp.crm.activities"
CRM_ACTIVITY_OBJECT_TYPE = "crm.activity"
CRM_NOTE_OBJECT_TYPE = "crm.note"
CRM_ACTIVITY_SCHEMA_VERSION = "crm_activity.v1"
CRM_NOTE_SCHEMA_VERSION = "crm_note.v1"
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class CrmLifecycleState(StrEnum):
    WORKING = "working"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DISPOSITION_PENDING = "disposition_pending"


class CrmActivityType(StrEnum):
    TASK = "task"
    CALL = "call"
    MEETING = "meeting"
    EMAIL = "email"
    FOLLOW_UP = "follow_up"


class CrmActivityStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    CANCELLED = "cancelled"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class CrmNoteStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    ARCHIVED = "archived"


class CrmActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = CRM_ACTIVITY_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: CrmLifecycleState = CrmLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = CRM_ACTIVITY_SCHEMA_VERSION
    account_object_id: str | None = None
    contact_object_id: str | None = None
    activity_number: str | None = None
    activity_type: CrmActivityType
    subject: str
    due_at_utc: str | None = None
    completed_at_utc: str | None = None
    status: CrmActivityStatus = CrmActivityStatus.PLANNED

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "subject",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM activity fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_activity_object_type(cls, value: str) -> str:
        if value != CRM_ACTIVITY_OBJECT_TYPE:
            raise ValueError("CRM activity records must use crm.activity object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_activity_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.PERSONAL:
            raise ValueError("CRM activities are personal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("CRM activities must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("CRM activity legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("CRM activity references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("CRM activity source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != CRM_ACTIVITY_SCHEMA_VERSION:
            raise ValueError("CRM activity schema_version must match crm_activity.v1")
        return value

    @field_validator(
        "account_object_id",
        "contact_object_id",
        "activity_number",
        "due_at_utc",
        "completed_at_utc",
    )
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("CRM activity optional fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_consistent_lifecycle(self) -> CrmActivityRecord:
        if self.status == CrmActivityStatus.RESTRICTED and self.lifecycle_state != CrmLifecycleState.RESTRICTED:
            raise ValueError("restricted CRM activities must use restricted lifecycle_state")
        if self.status == CrmActivityStatus.DONE and self.completed_at_utc is None:
            raise ValueError("done CRM activities must include completed_at_utc")
        return self


class CrmNoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = CRM_NOTE_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: CrmLifecycleState = CrmLifecycleState.ACTIVE
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = CRM_NOTE_SCHEMA_VERSION
    account_object_id: str | None = None
    contact_object_id: str | None = None
    activity_object_id: str | None = None
    note_number: str | None = None
    title: str
    status: CrmNoteStatus = CrmNoteStatus.ACTIVE

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "title",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM note fields must not be empty")
        return value

    @field_validator("object_type")
    @classmethod
    def require_note_object_type(cls, value: str) -> str:
        if value != CRM_NOTE_OBJECT_TYPE:
            raise ValueError("CRM note records must use crm.note object_type")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_note_classification(cls, value: DataClass) -> DataClass:
        if value != DataClass.PERSONAL:
            raise ValueError("CRM notes are personal by default")
        return value

    @field_validator("retention_policy_id")
    @classmethod
    def require_standard_retention(cls, value: str) -> str:
        if value != "rp-standard":
            raise ValueError("CRM notes must start with rp-standard retention")
        return value

    @field_validator("legal_hold_state")
    @classmethod
    def validate_legal_hold_state(cls, value: str) -> str:
        if value not in {"none", "active"}:
            raise ValueError("CRM note legal_hold_state must be none or active")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("CRM note references must be namespaced")
        return value

    @field_validator("source_system")
    @classmethod
    def validate_source_system(cls, value: str) -> str:
        if not SOURCE_SYSTEM_PATTERN.fullmatch(value):
            raise ValueError("CRM note source_system must be lowercase and non-empty")
        return value

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        if value != CRM_NOTE_SCHEMA_VERSION:
            raise ValueError("CRM note schema_version must match crm_note.v1")
        return value

    @field_validator(
        "account_object_id",
        "contact_object_id",
        "activity_object_id",
        "note_number",
    )
    @classmethod
    def validate_optional_non_empty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("CRM note optional fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_restricted_lifecycle_when_status_is_restricted(self) -> CrmNoteRecord:
        if self.status == CrmNoteStatus.RESTRICTED and self.lifecycle_state != CrmLifecycleState.RESTRICTED:
            raise ValueError("restricted CRM notes must use restricted lifecycle_state")
        return self


class CrmActivityView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    account_object_id: str | None = None
    contact_object_id: str | None = None
    activity_number: str | None = None
    activity_type: CrmActivityType
    subject: str
    due_at_utc: str | None = None
    completed_at_utc: str | None = None
    status: CrmActivityStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: CrmLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_object_access_checked: bool = True


class CrmNoteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    account_object_id: str | None = None
    contact_object_id: str | None = None
    activity_object_id: str | None = None
    note_number: str | None = None
    title: str
    status: CrmNoteStatus
    owner_principal_id: str
    created_at_utc: str
    updated_at_utc: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: CrmLifecycleState
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True
    linked_object_access_checked: bool = True


class CrmActivitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ACTIVITIES_FEATURE_ID
    activities: list[CrmActivityView]
    audit_event_id: str


class CrmNotesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ACTIVITIES_FEATURE_ID
    notes: list[CrmNoteView]
    audit_event_id: str


class CrmActivityRepository(Protocol):
    def list_activities(self, *, tenant_id: str) -> Sequence[CrmActivityRecord]:
        pass


class CrmNoteRepository(Protocol):
    def list_notes(self, *, tenant_id: str) -> Sequence[CrmNoteRecord]:
        pass


def redact_linked_object_id(value: str | None, *, readable_object_ids: set[str]) -> str | None:
    if value is not None and value not in readable_object_ids:
        return None
    return value


def crm_activity_view(record: CrmActivityRecord, *, readable_object_ids: set[str]) -> CrmActivityView:
    return CrmActivityView(
        object_id=record.object_id,
        object_type=record.object_type,
        account_object_id=redact_linked_object_id(record.account_object_id, readable_object_ids=readable_object_ids),
        contact_object_id=redact_linked_object_id(record.contact_object_id, readable_object_ids=readable_object_ids),
        activity_number=record.activity_number,
        activity_type=record.activity_type,
        subject=record.subject,
        due_at_utc=record.due_at_utc,
        completed_at_utc=record.completed_at_utc,
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


def crm_note_view(record: CrmNoteRecord, *, readable_object_ids: set[str]) -> CrmNoteView:
    return CrmNoteView(
        object_id=record.object_id,
        object_type=record.object_type,
        account_object_id=redact_linked_object_id(record.account_object_id, readable_object_ids=readable_object_ids),
        contact_object_id=redact_linked_object_id(record.contact_object_id, readable_object_ids=readable_object_ids),
        activity_object_id=redact_linked_object_id(record.activity_object_id, readable_object_ids=readable_object_ids),
        note_number=record.note_number,
        title=record.title,
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


def redacted_link_count(
    records: Sequence[CrmActivityRecord | CrmNoteRecord],
    views: Sequence[CrmActivityView | CrmNoteView],
) -> int:
    count = 0
    for record, view in zip(records, views, strict=True):
        for field_name in ("account_object_id", "contact_object_id", "activity_object_id"):
            if not hasattr(record, field_name):
                continue
            if getattr(record, field_name) is not None and getattr(view, field_name) is None:
                count += 1
    return count


class InMemoryCrmActivityRepository:
    def __init__(self, activities: Sequence[CrmActivityRecord]) -> None:
        self._activities = tuple(activities)

    @classmethod
    def demo(cls) -> InMemoryCrmActivityRepository:
        return cls(
            activities=(
                CrmActivityRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-activity-followup-demo",
                    account_object_id="crm-account-acme-demo",
                    contact_object_id="crm-contact-ada-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:30:00Z",
                    updated_at_utc="2026-06-11T12:30:00Z",
                    kms_key_ref="kms:tenant-demo:crm-activity",
                    audit_chain_ref="audit:crm-activity-followup-demo",
                    activity_number="CRM-A-1001",
                    activity_type=CrmActivityType.FOLLOW_UP,
                    subject="Acme follow-up",
                    due_at_utc="2026-06-18T09:00:00Z",
                ),
                CrmActivityRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-activity-review-demo",
                    account_object_id="crm-account-northwind-demo",
                    contact_object_id="crm-contact-max-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:35:00Z",
                    updated_at_utc="2026-06-11T12:35:00Z",
                    kms_key_ref="kms:tenant-demo:crm-activity",
                    audit_chain_ref="audit:crm-activity-review-demo",
                    activity_number="CRM-A-1002",
                    activity_type=CrmActivityType.MEETING,
                    subject="Northwind review",
                    due_at_utc="2026-06-19T10:00:00Z",
                ),
                CrmActivityRecord(
                    tenant_id="tenant-other",
                    object_id="crm-activity-other-tenant",
                    account_object_id="crm-account-other-tenant",
                    contact_object_id="crm-contact-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T12:40:00Z",
                    updated_at_utc="2026-06-11T12:40:00Z",
                    kms_key_ref="kms:tenant-other:crm-activity",
                    audit_chain_ref="audit:crm-activity-other-tenant",
                    activity_number="CRM-A-9001",
                    activity_type=CrmActivityType.TASK,
                    subject="Other tenant task",
                ),
            )
        )

    def list_activities(self, *, tenant_id: str) -> Sequence[CrmActivityRecord]:
        return tuple(activity for activity in self._activities if activity.tenant_id == tenant_id)


class InMemoryCrmNoteRepository:
    def __init__(self, notes: Sequence[CrmNoteRecord]) -> None:
        self._notes = tuple(notes)

    @classmethod
    def demo(cls) -> InMemoryCrmNoteRepository:
        return cls(
            notes=(
                CrmNoteRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-note-acme-demo",
                    account_object_id="crm-account-acme-demo",
                    contact_object_id="crm-contact-ada-demo",
                    activity_object_id="crm-activity-followup-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:45:00Z",
                    updated_at_utc="2026-06-11T12:45:00Z",
                    kms_key_ref="kms:tenant-demo:crm-note",
                    audit_chain_ref="audit:crm-note-acme-demo",
                    note_number="CRM-N-1001",
                    title="Acme onboarding note",
                ),
                CrmNoteRecord(
                    tenant_id="tenant-demo",
                    object_id="crm-note-northwind-demo",
                    account_object_id="crm-account-northwind-demo",
                    contact_object_id="crm-contact-max-demo",
                    activity_object_id="crm-activity-review-demo",
                    owner_principal_id="user-demo",
                    created_by="system",
                    created_at_utc="2026-06-11T12:50:00Z",
                    updated_at_utc="2026-06-11T12:50:00Z",
                    kms_key_ref="kms:tenant-demo:crm-note",
                    audit_chain_ref="audit:crm-note-northwind-demo",
                    note_number="CRM-N-1002",
                    title="Northwind review note",
                ),
                CrmNoteRecord(
                    tenant_id="tenant-other",
                    object_id="crm-note-other-tenant",
                    account_object_id="crm-account-other-tenant",
                    contact_object_id="crm-contact-other-tenant",
                    activity_object_id="crm-activity-other-tenant",
                    owner_principal_id="user-other",
                    created_by="system",
                    created_at_utc="2026-06-11T12:55:00Z",
                    updated_at_utc="2026-06-11T12:55:00Z",
                    kms_key_ref="kms:tenant-other:crm-note",
                    audit_chain_ref="audit:crm-note-other-tenant",
                    note_number="CRM-N-9001",
                    title="Other tenant note",
                ),
            )
        )

    def list_notes(self, *, tenant_id: str) -> Sequence[CrmNoteRecord]:
        return tuple(note for note in self._notes if note.tenant_id == tenant_id)


class CrmActivityService:
    def __init__(
        self,
        *,
        activity_repository: CrmActivityRepository,
        note_repository: CrmNoteRepository,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.activity_repository = activity_repository
        self.note_repository = note_repository
        self.audit_logger = audit_logger

    def list_activities(self, *, user_context: UserContext) -> CrmActivitiesResponse:
        candidate_records = sorted(
            self.activity_repository.list_activities(tenant_id=user_context.tenant_id),
            key=lambda record: (record.subject.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [crm_activity_view(record, readable_object_ids=user_context.readable_object_ids) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.activity.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ACTIVITIES_FEATURE_ID,
                "object_type": CRM_ACTIVITY_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "redacted_link_count": redacted_link_count(records, views),
                "result_contract": "metadata_only",
            },
        )
        return CrmActivitiesResponse(
            tenant_id=user_context.tenant_id,
            activities=views,
            audit_event_id=event.event_id,
        )

    def list_notes(self, *, user_context: UserContext) -> CrmNotesResponse:
        candidate_records = sorted(
            self.note_repository.list_notes(tenant_id=user_context.tenant_id),
            key=lambda record: (record.title.lower(), record.object_id),
        )
        records = [record for record in candidate_records if record.object_id in user_context.readable_object_ids]
        views = [crm_note_view(record, readable_object_ids=user_context.readable_object_ids) for record in records]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.note.list",
            source_object_ids=[record.object_id for record in records],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ACTIVITIES_FEATURE_ID,
                "object_type": CRM_NOTE_OBJECT_TYPE,
                "candidate_count": len(candidate_records),
                "result_count": len(views),
                "redacted_link_count": redacted_link_count(records, views),
                "result_contract": "metadata_only",
            },
        )
        return CrmNotesResponse(
            tenant_id=user_context.tenant_id,
            notes=views,
            audit_event_id=event.event_id,
        )
