import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_activities import (
    CRM_ACTIVITIES_FEATURE_ID,
    CRM_ACTIVITY_OBJECT_TYPE,
    CRM_ERP_MODULE_ID,
    CRM_NOTE_OBJECT_TYPE,
    CrmActivityRecord,
    CrmActivityService,
    CrmNoteRecord,
    InMemoryCrmActivityRepository,
    InMemoryCrmNoteRepository,
)


def readable_demo_objects() -> set[str]:
    return {
        "crm-account-acme-demo",
        "crm-account-northwind-demo",
        "crm-contact-ada-demo",
        "crm-contact-max-demo",
        "crm-activity-followup-demo",
        "crm-activity-review-demo",
        "crm-note-acme-demo",
        "crm-note-northwind-demo",
    }


def crm_activity_service(audit_logger: InMemoryAuditLogger) -> CrmActivityService:
    return CrmActivityService(
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        audit_logger=audit_logger,
    )


def test_crm_activity_and_note_records_require_compliance_metadata() -> None:
    activity = InMemoryCrmActivityRepository.demo().list_activities(tenant_id="tenant-demo")[0]
    note = InMemoryCrmNoteRepository.demo().list_notes(tenant_id="tenant-demo")[0]

    assert activity.object_type == CRM_ACTIVITY_OBJECT_TYPE
    assert note.object_type == CRM_NOTE_OBJECT_TYPE
    for record in (activity, note):
        assert record.data_classification == DataClass.PERSONAL
        assert record.retention_policy_id == "rp-standard"
        assert record.legal_hold_state == "none"
        assert record.kms_key_ref.startswith("kms:")
        assert record.audit_chain_ref.startswith("audit:")
        assert record.source_system == "native"
    assert activity.schema_version == "crm_activity.v1"
    assert note.schema_version == "crm_note.v1"


def test_crm_activity_and_note_records_reject_wrong_object_type_or_missing_refs() -> None:
    activity_values = {
        "tenant_id": "tenant-demo",
        "object_id": "crm-activity-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T12:00:00Z",
        "updated_at_utc": "2026-06-11T12:00:00Z",
        "kms_key_ref": "kms:tenant-demo:crm-activity",
        "audit_chain_ref": "audit:crm-activity-invalid",
        "activity_type": "task",
        "subject": "Invalid activity",
    }
    note_values = {
        "tenant_id": "tenant-demo",
        "object_id": "crm-note-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T12:00:00Z",
        "updated_at_utc": "2026-06-11T12:00:00Z",
        "kms_key_ref": "kms:tenant-demo:crm-note",
        "audit_chain_ref": "audit:crm-note-invalid",
        "title": "Invalid note",
    }

    with pytest.raises(ValidationError, match=r"crm\.activity"):
        CrmActivityRecord.model_validate({**activity_values, "object_type": "crm.note"})

    with pytest.raises(ValidationError, match=r"crm\.note"):
        CrmNoteRecord.model_validate({**note_values, "object_type": "crm.activity"})

    with pytest.raises(ValidationError, match="namespaced"):
        CrmActivityRecord.model_validate({**activity_values, "kms_key_ref": "missing-namespace"})


def test_crm_activity_service_returns_only_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = crm_activity_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids=readable_demo_objects(),
    )

    response = service.list_activities(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == CRM_ACTIVITIES_FEATURE_ID
    assert [activity.subject for activity in response.activities] == ["Acme follow-up", "Northwind review"]
    assert all(activity.object_type == CRM_ACTIVITY_OBJECT_TYPE for activity in response.activities)
    assert [activity.contact_object_id for activity in response.activities] == [
        "crm-contact-ada-demo",
        "crm-contact-max-demo",
    ]
    assert "Other tenant task" not in {activity.subject for activity in response.activities}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.event_type == "crm.activity.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["crm-activity-followup-demo", "crm-activity-review-demo"]
    assert event.metadata == {
        "feature_id": CRM_ACTIVITIES_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": CRM_ACTIVITY_OBJECT_TYPE,
        "candidate_count": 2,
        "redacted_link_count": 0,
        "result_contract": "metadata_only",
        "result_count": 2,
    }


def test_crm_activity_service_filters_unreadable_activities_and_redacts_links() -> None:
    audit_logger = InMemoryAuditLogger()
    service = crm_activity_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"crm-activity-followup-demo"},
    )

    response = service.list_activities(user_context=user_context)

    assert [activity.object_id for activity in response.activities] == ["crm-activity-followup-demo"]
    assert response.activities[0].account_object_id is None
    assert response.activities[0].contact_object_id is None
    event = audit_logger.events[-1]
    assert event.source_object_ids == ["crm-activity-followup-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
    assert event.metadata["redacted_link_count"] == 2


def test_crm_note_service_returns_metadata_only_and_redacts_unreadable_links() -> None:
    audit_logger = InMemoryAuditLogger()
    service = crm_activity_service(audit_logger)
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"crm-note-acme-demo", "crm-activity-followup-demo"},
    )

    response = service.list_notes(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == CRM_ACTIVITIES_FEATURE_ID
    assert [note.object_id for note in response.notes] == ["crm-note-acme-demo"]
    assert response.notes[0].title == "Acme onboarding note"
    assert response.notes[0].object_type == CRM_NOTE_OBJECT_TYPE
    assert response.notes[0].activity_object_id == "crm-activity-followup-demo"
    assert response.notes[0].account_object_id is None
    assert response.notes[0].contact_object_id is None
    assert "note_body" not in response.notes[0].model_dump()

    event = audit_logger.events[-1]
    assert event.event_type == "crm.note.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["crm-note-acme-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
    assert event.metadata["redacted_link_count"] == 2
    assert event.metadata["result_contract"] == "metadata_only"
