from typing import Any

from fastapi.testclient import TestClient

from main import app
from suite.platform.crm_onboarding import (
    CrmAccountOnboardingService,
    InMemoryCrmAccountOnboardingStore,
)
from suite.platform.modules import default_module_registry

client = TestClient(app)

ADMIN_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "tenant-admin",
}
READER_HEADERS = {**ADMIN_HEADERS, "X-Role-Ids": "knowledge-worker"}
PAYLOAD: dict[str, Any] = {
    "mutation_reference": "request:api-crm-onboarding-v1",
    "account": {
        "object_id": "crm-account-api-onboarding",
        "account_number": "CRM-API-01",
        "display_name": "API Customer GmbH",
    },
    "contact": {
        "object_id": "crm-contact-api-onboarding",
        "contact_number": "CRM-C-API-01",
        "display_name": "API Contact",
        "primary_email": "contact@example.test",
    },
    "activity": {
        "object_id": "crm-activity-api-onboarding",
        "activity_number": "CRM-A-API-01",
        "activity_type": "follow_up",
        "subject": "Call API contact",
    },
    "note": {
        "object_id": "crm-note-api-onboarding",
        "note_number": "CRM-N-API-01",
        "title": "Metadata only",
    },
}


def reset_runtime() -> None:
    app.state.module_registry = default_module_registry()
    app.state.crm_account_onboarding_service = CrmAccountOnboardingService(
        store=InMemoryCrmAccountOnboardingStore(),
        audit_logger=app.state.audit_logger,
    )


def enable_crm_features() -> None:
    provision = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=ADMIN_HEADERS,
        json={"approval_reference": "approval:crm-onboarding-provision", "reason": "prepare CRM writes"},
    )
    assert provision.status_code == 200
    enable = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:crm-onboarding-enable",
            "reason": "activate CRM writes",
            "enabled_features": {
                "crm_erp.crm.accounts": True,
                "crm_erp.crm.contacts": True,
                "crm_erp.crm.activities": True,
            },
        },
    )
    assert enable.status_code == 200


def test_crm_onboarding_api_enforces_module_and_operator_roles() -> None:
    reset_runtime()

    module_blocked = client.post(
        "/v1/crm/account-onboardings",
        headers=ADMIN_HEADERS,
        json=PAYLOAD,
    )
    assert module_blocked.status_code == 403

    enable_crm_features()
    role_blocked = client.post(
        "/v1/crm/account-onboardings",
        headers=READER_HEADERS,
        json=PAYLOAD,
    )
    assert role_blocked.status_code == 403
    assert role_blocked.json()["detail"] == "CRM operator role required"


def test_crm_onboarding_api_is_metadata_only_idempotent_and_conflict_safe() -> None:
    reset_runtime()
    enable_crm_features()

    first = client.post(
        "/v1/crm/account-onboardings",
        headers=ADMIN_HEADERS,
        json=PAYLOAD,
    )
    replay = client.post(
        "/v1/crm/account-onboardings",
        headers=ADMIN_HEADERS,
        json=PAYLOAD,
    )
    changed_payload = {**PAYLOAD, "note": {**PAYLOAD["note"], "title": "Changed"}}
    conflict = client.post(
        "/v1/crm/account-onboardings",
        headers=ADMIN_HEADERS,
        json=changed_payload,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert conflict.status_code == 409
    body = first.json()
    assert body["atomic_transaction_committed"] is True
    assert body["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["receipt"]["receipt_hash"] == body["receipt"]["receipt_hash"]
    assert body["acl_grant_count"] == 4
    assert body["content_included"] is False
    assert "display_name" not in body["receipt"]
    assert "primary_email" not in body["receipt"]
    assert "note_body" not in first.text
