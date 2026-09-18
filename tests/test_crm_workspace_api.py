import base64
import hmac
import json
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from time import time
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    HmacJwtVerifier,
    InMemoryPrincipalDirectory,
    JwtPrincipalResolver,
    ObjectAclRecord,
    PrincipalRecord,
    TenantMembership,
)
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_workspace import CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS, CrmAccountWorkspaceService
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
WORKSPACE_PATH = "/v1/crm/accounts/crm-account-acme-demo/workspace"


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
    assert response.headers["Cache-Control"] == "no-store"
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
    assert response.headers["Cache-Control"] == "no-store"


@dataclass
class WorkspaceHarness:
    client: TestClient
    service: CrmAccountWorkspaceService


@pytest.fixture
def workspace_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkspaceHarness]:
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    logger = InMemoryAuditLogger()
    service = CrmAccountWorkspaceService(
        account_repository=InMemoryCrmAccountRepository.demo(),
        contact_repository=InMemoryCrmContactRepository.demo(),
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        audit_logger=logger,
    )
    monkeypatch.setattr(app.state, "module_registry", default_module_registry())
    monkeypatch.setattr(app.state, "crm_account_workspace_service", service)
    with TestClient(app) as scoped_client:
        enable_crm_features(dict.fromkeys(CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS, True))
        yield WorkspaceHarness(scoped_client, service)


def workspace_read_spies(harness: WorkspaceHarness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    methods = {
        "accounts": (harness.service.account_repository, "list_accounts"),
        "contacts": (harness.service.contact_repository, "list_contacts"),
        "activities": (harness.service.activity_repository, "list_activities"),
        "notes": (harness.service.note_repository, "list_notes"),
    }
    spies = {}
    for key, (repository, method) in methods.items():
        spy = Mock(wraps=getattr(repository, method))
        monkeypatch.setattr(repository, method, spy)
        spies[key] = spy
    return spies


def test_workspace_returns_only_readable_relations_and_metadata_only_audit(
    workspace_harness: WorkspaceHarness, caplog: pytest.LogCaptureFixture
) -> None:
    headers = {
        **DEMO_HEADERS,
        "X-Readable-Object-Ids": "crm-account-acme-demo,crm-activity-followup-demo,crm-note-acme-demo",
    }
    response = workspace_harness.client.get(WORKSPACE_PATH, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["contacts"] == []
    assert len(body["activities"]) == len(body["notes"]) == 1
    assert body["activities"][0]["contact_object_id"] is None
    assert body["notes"][0]["contact_object_id"] is None
    assert body["notes"][0]["activity_object_id"] == "crm-activity-followup-demo"
    assert body["counts"] == {
        "contact_count": 0,
        "activity_count": 1,
        "note_count": 1,
        "total_object_count": 3,
    }
    assert body["access_checked"] is True
    assert body["content_included"] is False
    assert body["result_contract"] == "metadata_only_account_workspace"
    assert "crm-contact-ada-demo" not in response.text
    events = workspace_harness.service.audit_logger.events
    assert len(events) == 1
    event = events[0]
    assert event.event_id == body["audit_event_id"]
    assert event.input_hash is event.output_hash is None
    assert set(event.source_object_ids) == {
        "crm-account-acme-demo", "crm-activity-followup-demo", "crm-note-acme-demo"
    }
    audit_json = event.model_dump_json()
    for private_value in (body["account"]["display_name"], body["activities"][0]["subject"], body["notes"][0]["title"]):
        assert private_value not in audit_json
        assert private_value not in caplog.text


@pytest.mark.parametrize("block", ["authentication", "module", *CRM_ACCOUNT_WORKSPACE_REQUIRED_FEATURE_IDS])
def test_workspace_authentication_module_and_each_feature_gate_precede_repository_access(
    workspace_harness: WorkspaceHarness, monkeypatch: pytest.MonkeyPatch, block: str
) -> None:
    spies = workspace_read_spies(workspace_harness, monkeypatch)
    headers = DEMO_HEADERS
    if block == "authentication":
        headers = {}
    elif block == "module":
        response = workspace_harness.client.post(
            "/v1/admin/tenant-modules/crm_erp/disable",
            headers=ADMIN_HEADERS,
            json={"approval_reference": "approval:workspace-test-disable", "reason": "read gate test"},
        )
        assert response.status_code == 200
    else:
        registry = app.state.module_registry
        current = registry.get_tenant_module("tenant-demo", "crm_erp")
        features = {**current.enabled_features, block: False}
        registry.upsert_tenant_module(current.model_copy(update={"enabled_features": features}))
    response = workspace_harness.client.get(WORKSPACE_PATH, headers=headers)
    assert response.status_code == (401 if block == "authentication" else 403)
    for spy in spies.values():
        spy.assert_not_called()
    assert workspace_harness.service.audit_logger.events == ()


@pytest.mark.parametrize("target", ["crm-account-acme-demo", "crm-account-other-tenant", "crm-account-missing"])
def test_workspace_denied_missing_and_foreign_accounts_are_generic_and_do_not_read_children(
    workspace_harness: WorkspaceHarness, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    spies = workspace_read_spies(workspace_harness, monkeypatch)
    headers = {
        **DEMO_HEADERS,
        "X-Readable-Object-Ids": "crm-contact-ada-demo,crm-account-other-tenant,crm-account-missing",
    }
    response = workspace_harness.client.get(f"/v1/crm/accounts/{target}/workspace", headers=headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "CRM account workspace not found"}
    assert response.headers["Cache-Control"] == "no-store"
    spies["accounts"].assert_called_once_with(tenant_id="tenant-demo")
    for key in ("contacts", "activities", "notes"):
        spies[key].assert_not_called()
    assert workspace_harness.service.audit_logger.events == ()


@pytest.mark.parametrize("surface", ["accounts", "contacts", "activities", "notes"])
def test_workspace_database_outage_returns_safe_503_without_partial_data_or_success_audit(
    workspace_harness: WorkspaceHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    surface: str,
) -> None:
    spies = workspace_read_spies(workspace_harness, monkeypatch)
    private_detail = "private-contact@example.invalid SQL connection credential"
    spies[surface].side_effect = psycopg.OperationalError(private_detail)
    response = workspace_harness.client.get(WORKSPACE_PATH, headers=DEMO_HEADERS)
    assert response.status_code == 503
    assert response.json() == {"detail": "CRM account workspace unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert private_detail not in caplog.text
    assert private_detail not in response.text
    assert workspace_harness.service.audit_logger.events == ()


def test_workspace_jwt_uses_fresh_server_acl_and_ignores_forged_roles_tenant_and_readable_ids(
    workspace_harness: WorkspaceHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    principal = PrincipalRecord(
        issuer=DEFAULT_JWT_ISSUER,
        subject="crm-reader-subject",
        user_id="crm-reader",
        memberships=[TenantMembership(tenant_id="tenant-demo", role_ids={"knowledge-worker"})],
    )
    resolver = JwtPrincipalResolver(
        verifier=HmacJwtVerifier(
            issuer=DEFAULT_JWT_ISSUER, audience=DEFAULT_JWT_AUDIENCE, secret=DEFAULT_DEV_JWT_SECRET
        ),
        directory=InMemoryPrincipalDirectory(principals=[principal], object_acls=[]),
    )
    monkeypatch.setattr(app.state, "principal_resolver", resolver)
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": "crm-reader-subject",
        "tenant_id": "tenant-demo",
        "iat": int(time()) - 1,
        "exp": int(time()) + 120,
        "roles": ["tenant-admin"],
        "readable_object_ids": DEMO_HEADERS["X-Readable-Object-Ids"].split(","),
    }
    segments = [
        base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")
        for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    ]
    signing_input = ".".join(segments)
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode(), signing_input.encode(), sha256).digest()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    headers = {
        **DEMO_HEADERS,
        "X-Tenant-Id": "tenant-other",
        "X-User-Id": "forged-admin",
        "X-Role-Ids": "tenant-admin",
        "Authorization": f"Bearer {token}",
    }
    spies = workspace_read_spies(workspace_harness, monkeypatch)
    denied = workspace_harness.client.get(WORKSPACE_PATH, headers=headers)
    assert denied.status_code == 404
    for key in ("contacts", "activities", "notes"):
        spies[key].assert_not_called()
    resolver.directory = InMemoryPrincipalDirectory(
        principals=[principal],
        object_acls=[
            ObjectAclRecord(tenant_id="tenant-demo", object_id=object_id, readable_user_ids={"crm-reader"})
            for object_id in ("crm-account-acme-demo", "crm-contact-ada-demo")
        ],
    )
    allowed = workspace_harness.client.get(WORKSPACE_PATH, headers=headers)
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["tenant_id"] == "tenant-demo"
    assert len(body["contacts"]) == 1
    assert body["activities"] == body["notes"] == []
    assert workspace_harness.service.audit_logger.events[-1].user_id == "crm-reader"
    resolver.directory = InMemoryPrincipalDirectory(principals=[principal], object_acls=[])
    assert workspace_harness.client.get(WORKSPACE_PATH, headers=headers).status_code == 404
    assert len(workspace_harness.service.audit_logger.events) == 1
