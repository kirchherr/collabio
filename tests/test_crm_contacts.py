import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_contacts import (
    CRM_CONTACT_OBJECT_TYPE,
    CRM_CONTACTS_FEATURE_ID,
    CRM_ERP_MODULE_ID,
    CrmContactRecord,
    CrmContactService,
    InMemoryCrmContactRepository,
)
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
)


def test_crm_contact_records_require_compliance_metadata() -> None:
    contact = InMemoryCrmContactRepository.demo().list_contacts(tenant_id="tenant-demo")[0]

    assert contact.object_type == CRM_CONTACT_OBJECT_TYPE
    assert contact.data_classification == DataClass.PERSONAL
    assert contact.retention_policy_id == "rp-standard"
    assert contact.legal_hold_state == "none"
    assert contact.kms_key_ref.startswith("kms:")
    assert contact.audit_chain_ref.startswith("audit:")
    assert contact.source_system == "native"
    assert contact.schema_version == "crm_contact.v1"
    assert contact.account_object_id == "crm-account-acme-demo"


def test_crm_contact_records_reject_wrong_object_type_or_missing_refs() -> None:
    values = {
        "tenant_id": "tenant-demo",
        "object_id": "crm-contact-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T12:00:00Z",
        "updated_at_utc": "2026-06-11T12:00:00Z",
        "kms_key_ref": "kms:tenant-demo:crm-contact",
        "audit_chain_ref": "audit:crm-contact-invalid",
        "display_name": "Invalid Contact",
    }

    with pytest.raises(ValidationError, match=r"crm\.contact"):
        CrmContactRecord.model_validate({**values, "object_type": "crm.account"})

    with pytest.raises(ValidationError, match="namespaced"):
        CrmContactRecord.model_validate({**values, "audit_chain_ref": "missing-namespace"})


def test_crm_contact_service_returns_only_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = CrmContactService(
        repository=InMemoryCrmContactRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={
            "crm-account-acme-demo",
            "crm-account-northwind-demo",
            "crm-contact-ada-demo",
            "crm-contact-max-demo",
        },
    )

    response = service.list_contacts(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == CRM_CONTACTS_FEATURE_ID
    assert [contact.display_name for contact in response.contacts] == ["Ada Demo", "Max Demo"]
    assert all(contact.object_type == CRM_CONTACT_OBJECT_TYPE for contact in response.contacts)
    assert all(contact.access_checked for contact in response.contacts)
    assert all(contact.linked_account_access_checked for contact in response.contacts)
    assert [contact.account_object_id for contact in response.contacts] == [
        "crm-account-acme-demo",
        "crm-account-northwind-demo",
    ]
    assert "Other Contact" not in {contact.display_name for contact in response.contacts}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "crm.contact.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["crm-contact-ada-demo", "crm-contact-max-demo"]
    assert event.metadata == {
        "feature_id": CRM_CONTACTS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": CRM_CONTACT_OBJECT_TYPE,
        "candidate_count": 2,
        "redacted_account_link_count": 0,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_crm_contact_service_filters_unreadable_contacts_and_redacts_unreadable_account_links() -> None:
    audit_logger = InMemoryAuditLogger()
    service = CrmContactService(
        repository=InMemoryCrmContactRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"crm-contact-ada-demo"},
    )

    response = service.list_contacts(user_context=user_context)

    assert [contact.object_id for contact in response.contacts] == ["crm-contact-ada-demo"]
    assert response.contacts[0].account_object_id is None
    event = audit_logger.events[-1]
    assert event.source_object_ids == ["crm-contact-ada-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
    assert event.metadata["redacted_account_link_count"] == 1
