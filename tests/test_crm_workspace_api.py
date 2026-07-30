from fastapi.testclient import TestClient

from main import app
from suite.platform.modules import default_module_registry

client = TestClient(app)

DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": (
        "crm-account-acme-demo,crm-contact-ada-demo,crm-activity-followup-demo,crm-note-acme-demo"
    ),
}
ADMIN_HEADERS = {**DEMO_HEADERS, "X-Role-Ids": "tenant-admin"}


def reset_module_registry() -> None:
    app.state.module_registry = default_module_registry()


def enable_crm_features(enabled_features: dict[str, bool]) -> None:
    provision = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=ADMIN_HEADERS,
        json={"approval_reference": "approval:crm-workspace-provision", "reason": "prepare CRM workspace"},
    )
    assert provision.status_code == 200
    enable = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:crm-workspace-enable",
            "reason": "activate CRM workspace",
            "enabled_features": enabled_features,
        },
    )
    assert enable.status_code == 200


def test_crm_account_workspace_requires_all_three_foundation_features() -> None:
    reset_module_registry()
    enable_crm_features({"crm_erp.crm.accounts": True})

    response = client.get(
        "/v1/crm/accounts/crm-account-acme-demo/workspace",
        headers=DEMO_HEADERS,
    )

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_crm_account_workspace_api_returns_postgres_ready_metadata_workflow() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    enable_crm_features(
        {
            "crm_erp.crm.accounts": True,
            "crm_erp.crm.contacts": True,
            "crm_erp.crm.activities": True,
        }
    )

    response = client.get(
        "/v1/crm/accounts/crm-account-acme-demo/workspace",
        headers=DEMO_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["account"]["object_id"] == "crm-account-acme-demo"
    assert [item["object_id"] for item in body["contacts"]] == ["crm-contact-ada-demo"]
    assert [item["object_id"] for item in body["activities"]] == ["crm-activity-followup-demo"]
    assert [item["object_id"] for item in body["notes"]] == ["crm-note-acme-demo"]
    assert body["counts"]["total_object_count"] == 4
    assert body["content_included"] is False
    assert "note_body" not in response.text

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.account.workspace.read"
    assert new_events[-1].metadata["access_checked"] is True


def test_crm_account_workspace_api_uses_generic_not_found_for_unreadable_account() -> None:
    reset_module_registry()
    enable_crm_features(
        {
            "crm_erp.crm.accounts": True,
            "crm_erp.crm.contacts": True,
            "crm_erp.crm.activities": True,
        }
    )
    headers = {**DEMO_HEADERS, "X-Readable-Object-Ids": "crm-contact-ada-demo"}

    response = client.get(
        "/v1/crm/accounts/crm-account-acme-demo/workspace",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "CRM account workspace not found"
