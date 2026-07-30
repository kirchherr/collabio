import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_workspace import (
    CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS,
    CrmAccountWorkspaceService,
)


def build_service(audit_logger: InMemoryAuditLogger) -> CrmAccountWorkspaceService:
    return CrmAccountWorkspaceService(
        account_repository=InMemoryCrmAccountRepository.demo(),
        contact_repository=InMemoryCrmContactRepository.demo(),
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        audit_logger=audit_logger,
    )


def user_context(readable_object_ids: set[str]) -> UserContext:
    return UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids=readable_object_ids,
    )


def test_account_workspace_returns_one_acl_checked_relation_graph_and_audits_once() -> None:
    audit_logger = InMemoryAuditLogger()
    service = build_service(audit_logger)
    response = service.read_account_workspace(
        user_context=user_context(
            {
                "crm-account-acme-demo",
                "crm-contact-ada-demo",
                "crm-activity-followup-demo",
                "crm-note-acme-demo",
            }
        ),
        account_object_id="crm-account-acme-demo",
    )

    assert response.schema_version == "crm_account_workspace.v1"
    assert response.required_feature_ids == CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS
    assert response.account.object_id == "crm-account-acme-demo"
    assert [record.object_id for record in response.contacts] == ["crm-contact-ada-demo"]
    assert [record.object_id for record in response.activities] == ["crm-activity-followup-demo"]
    assert [record.object_id for record in response.notes] == ["crm-note-acme-demo"]
    assert response.counts.model_dump() == {
        "contact_count": 1,
        "activity_count": 1,
        "note_count": 1,
        "total_object_count": 4,
    }
    assert response.content_included is False
    assert "note_body" not in response.model_dump_json()

    assert len(audit_logger.events) == 1
    event = audit_logger.events[0]
    assert event.event_type == "crm.account.workspace.read"
    assert event.source_object_ids == [
        "crm-account-acme-demo",
        "crm-contact-ada-demo",
        "crm-activity-followup-demo",
        "crm-note-acme-demo",
    ]
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.metadata["result_contract"] == "metadata_only_account_workspace"
    assert event.metadata["access_checked"] is True


def test_account_workspace_supports_partial_acl_and_redacts_unreadable_relations() -> None:
    service = build_service(InMemoryAuditLogger())
    response = service.read_account_workspace(
        user_context=user_context({"crm-account-acme-demo", "crm-note-acme-demo"}),
        account_object_id="crm-account-acme-demo",
    )

    assert response.contacts == ()
    assert response.activities == ()
    assert len(response.notes) == 1
    assert response.notes[0].account_object_id == "crm-account-acme-demo"
    assert response.notes[0].contact_object_id is None
    assert response.notes[0].activity_object_id is None
    assert response.counts.total_object_count == 2


def test_account_workspace_hides_unreadable_and_cross_tenant_accounts_without_audit() -> None:
    audit_logger = InMemoryAuditLogger()
    service = build_service(audit_logger)

    with pytest.raises(KeyError, match="not found"):
        service.read_account_workspace(
            user_context=user_context({"crm-contact-ada-demo"}),
            account_object_id="crm-account-acme-demo",
        )
    with pytest.raises(KeyError, match="not found"):
        service.read_account_workspace(
            user_context=user_context({"crm-account-other-tenant"}),
            account_object_id="crm-account-other-tenant",
        )

    assert audit_logger.events == ()
