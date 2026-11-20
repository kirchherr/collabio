import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import (
    CRM_ACCOUNT_OBJECT_TYPE,
    CRM_ACCOUNTS_FEATURE_ID,
    CRM_ERP_MODULE_ID,
    CrmAccountRecord,
    CrmAccountService,
    InMemoryCrmAccountRepository,
)
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
)


def test_crm_account_records_require_compliance_metadata() -> None:
    account = InMemoryCrmAccountRepository.demo().list_accounts(tenant_id="tenant-demo")[0]

    assert account.object_type == CRM_ACCOUNT_OBJECT_TYPE
    assert account.data_classification == DataClass.PERSONAL
    assert account.retention_policy_id == "rp-standard"
    assert account.legal_hold_state == "none"
    assert account.kms_key_ref.startswith("kms:")
    assert account.audit_chain_ref.startswith("audit:")
    assert account.source_system == "native"
    assert account.schema_version == "crm_account.v1"


def test_crm_account_records_reject_wrong_object_type_or_missing_refs() -> None:
    values = {
        "tenant_id": "tenant-demo",
        "object_id": "crm-account-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T12:00:00Z",
        "updated_at_utc": "2026-06-11T12:00:00Z",
        "kms_key_ref": "kms:tenant-demo:crm-account",
        "audit_chain_ref": "audit:crm-account-invalid",
        "display_name": "Invalid Account",
    }

    with pytest.raises(ValidationError, match=r"crm\.account"):
        CrmAccountRecord.model_validate({**values, "object_type": "crm.contact"})

    with pytest.raises(ValidationError, match="namespaced"):
        CrmAccountRecord.model_validate({**values, "kms_key_ref": "missing-namespace"})


def test_crm_account_service_returns_only_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = CrmAccountService(
        repository=InMemoryCrmAccountRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"crm-account-acme-demo", "crm-account-northwind-demo"},
    )

    response = service.list_accounts(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == CRM_ACCOUNTS_FEATURE_ID
    assert [account.display_name for account in response.accounts] == ["Acme Demo GmbH", "Northwind Demo AG"]
    assert all(account.object_type == CRM_ACCOUNT_OBJECT_TYPE for account in response.accounts)
    assert all(account.access_checked for account in response.accounts)
    assert "Other Tenant AG" not in {account.display_name for account in response.accounts}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "crm.account.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["crm-account-acme-demo", "crm-account-northwind-demo"]
    assert event.metadata == {
        "feature_id": CRM_ACCOUNTS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": CRM_ACCOUNT_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_crm_account_service_filters_unreadable_account_objects() -> None:
    audit_logger = InMemoryAuditLogger()
    service = CrmAccountService(
        repository=InMemoryCrmAccountRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"crm-account-acme-demo"},
    )

    response = service.list_accounts(user_context=user_context)

    assert [account.object_id for account in response.accounts] == ["crm-account-acme-demo"]
    event = audit_logger.events[-1]
    assert event.source_object_ids == ["crm-account-acme-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
