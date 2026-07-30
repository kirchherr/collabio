from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import (
    CRM_ACCOUNTS_FEATURE_ID,
    CRM_ERP_MODULE_ID,
    CrmAccountRepository,
    CrmAccountView,
    crm_account_view,
)
from suite.platform.crm_activities import (
    CRM_ACTIVITIES_FEATURE_ID,
    CrmActivityRepository,
    CrmActivityView,
    CrmNoteRepository,
    CrmNoteView,
    crm_activity_view,
    crm_note_view,
)
from suite.platform.crm_contacts import (
    CRM_CONTACTS_FEATURE_ID,
    CrmContactRepository,
    CrmContactView,
    crm_contact_view,
)
from suite.platform.persistent_metadata import persistent_metadata_audit_metadata

CRM_ACCOUNT_WORKSPACE_SCHEMA_VERSION = "crm_account_workspace.v1"
CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS = (
    CRM_ACCOUNTS_FEATURE_ID,
    CRM_CONTACTS_FEATURE_ID,
    CRM_ACTIVITIES_FEATURE_ID,
)


class CrmAccountWorkspaceCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_count: int
    activity_count: int
    note_count: int
    total_object_count: int


class CrmAccountWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ACCOUNT_WORKSPACE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    required_feature_ids: tuple[str, ...] = CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS
    account: CrmAccountView
    contacts: tuple[CrmContactView, ...]
    activities: tuple[CrmActivityView, ...]
    notes: tuple[CrmNoteView, ...]
    counts: CrmAccountWorkspaceCounts
    audit_event_id: str
    result_contract: str = "metadata_only_account_workspace"
    content_included: bool = False
    access_checked: bool = True

    @field_validator("tenant_id", "audit_event_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CRM account workspace fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_workspace_contract(self) -> CrmAccountWorkspaceResponse:
        if self.content_included or not self.access_checked:
            raise ValueError("CRM account workspace must remain metadata-only and access checked")
        if self.required_feature_ids != CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS:
            raise ValueError("CRM account workspace requires all CRM foundation features")
        expected_total = 1 + len(self.contacts) + len(self.activities) + len(self.notes)
        if self.counts.total_object_count != expected_total:
            raise ValueError("CRM account workspace object count is inconsistent")
        return self


class CrmAccountWorkspaceService:
    def __init__(
        self,
        *,
        account_repository: CrmAccountRepository,
        contact_repository: CrmContactRepository,
        activity_repository: CrmActivityRepository,
        note_repository: CrmNoteRepository,
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self.account_repository = account_repository
        self.contact_repository = contact_repository
        self.activity_repository = activity_repository
        self.note_repository = note_repository
        self.audit_logger = audit_logger

    def read_account_workspace(
        self,
        *,
        user_context: UserContext,
        account_object_id: str,
    ) -> CrmAccountWorkspaceResponse:
        if not account_object_id.strip():
            raise KeyError("CRM account workspace not found")

        account_candidates = tuple(self.account_repository.list_accounts(tenant_id=user_context.tenant_id))
        account = next(
            (
                record
                for record in account_candidates
                if record.object_id == account_object_id and record.object_id in user_context.readable_object_ids
            ),
            None,
        )
        if account is None:
            raise KeyError("CRM account workspace not found")

        contact_candidates = tuple(self.contact_repository.list_contacts(tenant_id=user_context.tenant_id))
        contacts = tuple(
            sorted(
                (
                    record
                    for record in contact_candidates
                    if record.account_object_id == account.object_id
                    and record.object_id in user_context.readable_object_ids
                ),
                key=lambda record: (record.display_name.lower(), record.object_id),
            )
        )
        contact_ids = {record.object_id for record in contacts}

        activity_candidates = tuple(self.activity_repository.list_activities(tenant_id=user_context.tenant_id))
        activities = tuple(
            sorted(
                (
                    record
                    for record in activity_candidates
                    if record.object_id in user_context.readable_object_ids
                    and (
                        record.account_object_id == account.object_id
                        or (record.account_object_id is None and record.contact_object_id in contact_ids)
                    )
                ),
                key=lambda record: (record.due_at_utc or record.updated_at_utc, record.object_id),
            )
        )
        activity_ids = {record.object_id for record in activities}

        note_candidates = tuple(self.note_repository.list_notes(tenant_id=user_context.tenant_id))
        notes = tuple(
            sorted(
                (
                    record
                    for record in note_candidates
                    if record.object_id in user_context.readable_object_ids
                    and (
                        record.account_object_id == account.object_id
                        or (
                            record.account_object_id is None
                            and (record.contact_object_id in contact_ids or record.activity_object_id in activity_ids)
                        )
                    )
                ),
                key=lambda record: (record.updated_at_utc, record.object_id),
                reverse=True,
            )
        )

        account_view = crm_account_view(account)
        contact_views = tuple(
            crm_contact_view(record, readable_object_ids=user_context.readable_object_ids) for record in contacts
        )
        activity_views = tuple(
            crm_activity_view(record, readable_object_ids=user_context.readable_object_ids) for record in activities
        )
        note_views = tuple(
            crm_note_view(record, readable_object_ids=user_context.readable_object_ids) for record in notes
        )
        source_object_ids = [
            account.object_id,
            *(record.object_id for record in contacts),
            *(record.object_id for record in activities),
            *(record.object_id for record in notes),
        ]
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.account.workspace.read",
            source_object_ids=source_object_ids,
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "required_feature_ids": CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS,
                "account_object_id": account.object_id,
                "account_candidate_count": len(account_candidates),
                "contact_candidate_count": len(contact_candidates),
                "activity_candidate_count": len(activity_candidates),
                "note_candidate_count": len(note_candidates),
                "contact_count": len(contact_views),
                "activity_count": len(activity_views),
                "note_count": len(note_views),
                "result_contract": "metadata_only_account_workspace",
                "content_included": False,
                "access_checked": True,
                **persistent_metadata_audit_metadata(),
            },
        )
        return CrmAccountWorkspaceResponse(
            tenant_id=user_context.tenant_id,
            account=account_view,
            contacts=contact_views,
            activities=activity_views,
            notes=note_views,
            counts=CrmAccountWorkspaceCounts(
                contact_count=len(contact_views),
                activity_count=len(activity_views),
                note_count=len(note_views),
                total_object_count=len(source_object_ids),
            ),
            audit_event_id=event.event_id,
        )
