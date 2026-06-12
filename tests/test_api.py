import base64
import hmac
import json
from hashlib import sha256
from typing import Annotated, Any
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from main import app, require_module_api_gate
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.context import DEFAULT_DEV_JWT_SECRET, DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER
from suite.platform.modules import InMemoryModuleRegistry, ModuleGateDecision, default_module_registry
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository

client = TestClient(app)

DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}
DEMO_ADMIN_HEADERS = {
    **DEMO_HEADERS,
    "X-Role-Ids": "tenant-admin",
}
DEMO_SECURITY_ADMIN_HEADERS = {
    **DEMO_HEADERS,
    "X-Role-Ids": "security-admin",
}
DEMO_CRM_ACCOUNT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo",
}
DEMO_CRM_CONTACT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo,crm-contact-ada-demo,crm-contact-max-demo"
    ),
}
DEMO_CRM_ACTIVITY_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo,"
        "crm-contact-ada-demo,crm-contact-max-demo,"
        "crm-activity-followup-demo,crm-activity-review-demo,"
        "crm-note-acme-demo,crm-note-northwind-demo"
    ),
}
DEMO_ERP_PRODUCT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": "doc-1,mail-1,erp-product-standard-widget-demo,erp-product-service-plan-demo",
}
DEMO_KB_ARTICLE_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,"
        "kb-article-backup-runbook-demo,kb-article-version-backup-runbook-v1-demo,"
        "kb-article-security-baseline-demo,kb-article-version-security-baseline-v1-demo"
    ),
}
DECOMMISSION_REQUEST_PAYLOAD = {
    "approval_reference": "approval:module-decommission-request",
    "reason": "tenant requests controlled module decommission",
    "retention_evaluation_ref": "retention:eval-1",
    "legal_hold_check_ref": "legal-hold:check-1",
    "export_archive_decision_ref": "export:decision-1",
    "audit_evidence_ref": "audit:evidence-1",
    "backup_restore_evidence_ref": "backup:restore-1",
}
DECOMMISSION_BLOCK_PAYLOAD = {
    "approval_reference": "approval:module-decommission-block",
    "reason": "legal hold still blocks decommission completion",
    "blocker_report_ref": "decommission-blocker:report-1",
    "remediation_plan_ref": "decommission-remediation:plan-1",
}
DECOMMISSION_COMPLETE_PAYLOAD = {
    "approval_reference": "approval:module-decommission-complete",
    "reason": "all final disposition evidence is complete",
    "final_retention_disposition_ref": "retention:final-disposition-1",
    "final_legal_hold_clearance_ref": "legal-hold:clearance-1",
    "final_export_archive_manifest_ref": "export:archive-manifest-1",
    "final_audit_closure_ref": "audit:closure-1",
    "final_backup_disposition_ref": "backup:final-disposition-1",
    "final_data_disposition_ref": "data-disposition:final-1",
}
DECOMMISSION_CANCEL_PAYLOAD = {
    "approval_reference": "approval:module-decommission-cancel",
    "reason": "tenant cancels the decommission workflow",
    "cancel_approval_ref": "approval:module-decommission-cancel",
    "cancel_audit_evidence_ref": "audit:decommission-cancel-evidence-1",
}
DECOMMISSION_REOPEN_PAYLOAD = {
    "approval_reference": "approval:module-decommission-reopen",
    "reason": "decommission blocker has remediation evidence",
    "reopen_approval_ref": "approval:module-decommission-reopen",
    "blocker_remediation_evidence_ref": "decommission-remediation:evidence-1",
    "reopen_audit_evidence_ref": "audit:decommission-reopen-evidence-1",
}


def signed_jwt_for_api(subject: str = "user-demo", *, tenant_id: str = "tenant-demo") -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": subject,
        "tenant_id": tenant_id,
        "iat": 1_780_000_000,
        "exp": 1_800_000_000,
        "roles": ["tenant-admin"],
        "readable_object_ids": ["secret-1"],
    }
    encoded_header = base64url_json(header)
    encoded_payload = base64url_json(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode("utf-8"), signing_input, sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url_bytes(signature)}"


def base64url_json(payload: dict[str, Any]) -> str:
    return base64url_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def reset_module_registry() -> None:
    app.state.module_registry = default_module_registry()


def provision_and_enable_crm_accounts_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM accounts"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_crm_contacts_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM contacts"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM contacts",
            "enabled_features": {"crm_erp.crm.contacts": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_crm_activities_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM activities"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM activities and notes",
            "enabled_features": {"crm_erp.crm.activities": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_erp_products_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare ERP products"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate ERP products",
            "enabled_features": {"crm_erp.erp.products": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_knowledge_base_articles_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base articles"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate knowledge base articles",
            "enabled_features": {"knowledge_base.articles.read": True},
        },
    )
    assert enable_response.status_code == 200


def build_module_gate_probe_app(module_registry: InMemoryModuleRegistry) -> FastAPI:
    probe_app = FastAPI()
    probe_app.state.module_registry = module_registry
    probe_app.state.tenant_policy_repository = InMemoryTenantPolicyRepository.default()

    @probe_app.get("/normal", response_model=ModuleGateDecision)
    def normal_route(
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id="crm_erp", feature_id="crm_erp.crm.accounts")),
        ],
    ) -> ModuleGateDecision:
        return gate

    @probe_app.get("/compliance", response_model=ModuleGateDecision)
    def compliance_route(
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id="crm_erp", compliance=True)),
        ],
    ) -> ModuleGateDecision:
        return gate

    return probe_app


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tenant_data_endpoints_require_request_context() -> None:
    response = client.post("/v1/ai/inference", json={"input_text": "Bitte zusammenfassen."})
    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_dev_header_tenant_context_is_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITE_ENV", "production")
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Dev header tenant context is disabled in production"


def test_jwt_auth_mode_requires_bearer_token_and_ignores_dev_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer authorization header required"


def test_jwt_auth_mode_uses_signed_token_and_server_side_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    forged_headers = {
        **DEMO_ADMIN_HEADERS,
        "X-Tenant-Id": "tenant-unknown",
        "X-Readable-Object-Ids": "doc-1,mail-1,secret-1",
        "Authorization": f"Bearer {signed_jwt_for_api()}",
    }

    response = client.get("/v1/platform/modules", headers=forged_headers)

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-demo"

    admin_response = client.get("/v1/admin/tenant-policy", headers=forged_headers)
    assert admin_response.status_code == 403
    assert admin_response.json()["detail"] == "Tenant admin role required"

    inference_response = client.post(
        "/v1/ai/inference",
        headers=forged_headers,
        json={"input_text": "Bitte zusammenfassen.", "source_object_ids": ["secret-1"]},
    )
    assert inference_response.status_code == 403
    assert inference_response.json()["detail"] == "User cannot read one or more requested sources"


def test_unknown_tenant_policy_is_blocked() -> None:
    response = client.post(
        "/v1/ai/inference",
        headers={**DEMO_HEADERS, "X-Tenant-Id": "tenant-unknown"},
        json={"input_text": "Bitte zusammenfassen."},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant policy is not available"


def test_platform_modules_discovery_requires_request_context() -> None:
    response = client.get("/v1/platform/modules")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_modules_discovery_returns_tenant_scoped_module_metadata() -> None:
    reset_module_registry()

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert len(body["modules"]) == 2
    modules = {module["module_id"]: module for module in body["modules"]}
    crm_module = modules["crm_erp"]
    assert crm_module["display_name"] == "CRM/ERP"
    assert crm_module["status"] == "available"
    assert crm_module["normal_use_enabled"] is False
    assert crm_module["compliance_access_allowed"] is False
    assert crm_module["enabled_features"]["crm_erp.legacy_import.sqlserver"] is False

    kb_module = modules["knowledge_base"]
    assert kb_module["display_name"] == "Knowledge Base"
    assert kb_module["status"] == "available"
    assert kb_module["normal_use_enabled"] is False
    assert kb_module["enabled_features"]["knowledge_base.articles.read"] is True
    assert kb_module["enabled_features"]["knowledge_base.articles.write"] is False

    for module in body["modules"]:
        assert "audit_chain_ref" not in module
        assert "policy_snapshot_hash" not in module
        assert "changed_by" not in module


def test_module_api_gate_dependency_blocks_normal_routes_and_allows_compliance_routes() -> None:
    module_registry = default_module_registry()
    probe_client = TestClient(build_module_gate_probe_app(module_registry))

    unavailable_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert unavailable_response.status_code == 403
    assert "not enabled" in unavailable_response.json()["detail"]

    module_registry.provision_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:provision",
        migration_manifest_entries=load_migration_manifest(),
    )
    module_registry.enable_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:enable",
        enabled_features={"crm_erp.crm.accounts": True},
    )

    normal_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert normal_response.status_code == 200
    normal_body = normal_response.json()
    assert normal_body["tenant_id"] == "tenant-demo"
    assert normal_body["surface"] == "normal_api"
    assert normal_body["status"] == "enabled"
    assert normal_body["feature_id"] == "crm_erp.crm.accounts"
    assert normal_body["normal_use_enabled"] is True

    module_registry.disable_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:disable",
    )

    disabled_normal_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert disabled_normal_response.status_code == 403
    assert "not enabled" in disabled_normal_response.json()["detail"]

    compliance_response = probe_client.get("/compliance", headers=DEMO_HEADERS)
    assert compliance_response.status_code == 200
    compliance_body = compliance_response.json()
    assert compliance_body["surface"] == "compliance_api"
    assert compliance_body["status"] == "disabled"
    assert compliance_body["normal_use_enabled"] is False
    assert compliance_body["compliance_access_allowed"] is True


def test_crm_accounts_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/crm/accounts", headers=DEMO_CRM_ACCOUNT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_crm_accounts_endpoint_returns_tenant_scoped_accounts_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_accounts_for_demo()

    response = client.get("/v1/crm/accounts", headers=DEMO_CRM_ACCOUNT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.accounts"
    assert body["audit_event_id"]
    assert [account["display_name"] for account in body["accounts"]] == ["Acme Demo GmbH", "Northwind Demo AG"]
    assert {account["object_type"] for account in body["accounts"]} == {"crm.account"}
    assert {account["data_classification"] for account in body["accounts"]} == {"personal"}
    assert {account["retention_policy_id"] for account in body["accounts"]} == {"rp-standard"}
    assert all(account["access_checked"] for account in body["accounts"])
    assert "Other Tenant AG" not in {account["display_name"] for account in body["accounts"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.account.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_contacts_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/crm/contacts", headers=DEMO_CRM_CONTACT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_crm_contacts_endpoint_returns_tenant_scoped_contacts_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_contacts_for_demo()

    response = client.get("/v1/crm/contacts", headers=DEMO_CRM_CONTACT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.contacts"
    assert body["audit_event_id"]
    assert [contact["display_name"] for contact in body["contacts"]] == ["Ada Demo", "Max Demo"]
    assert {contact["object_type"] for contact in body["contacts"]} == {"crm.contact"}
    assert {contact["data_classification"] for contact in body["contacts"]} == {"personal"}
    assert {contact["retention_policy_id"] for contact in body["contacts"]} == {"rp-standard"}
    assert [contact["account_object_id"] for contact in body["contacts"]] == [
        "crm-account-acme-demo",
        "crm-account-northwind-demo",
    ]
    assert all(contact["access_checked"] for contact in body["contacts"])
    assert all(contact["linked_account_access_checked"] for contact in body["contacts"])
    assert "Other Contact" not in {contact["display_name"] for contact in body["contacts"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.contact.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_account_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_activities_and_notes_endpoints_require_enabled_module_feature() -> None:
    reset_module_registry()

    activities_response = client.get("/v1/crm/activities", headers=DEMO_CRM_ACTIVITY_HEADERS)
    notes_response = client.get("/v1/crm/notes", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert activities_response.status_code == 403
    assert notes_response.status_code == 403
    assert "not enabled" in activities_response.json()["detail"]
    assert "not enabled" in notes_response.json()["detail"]


def test_crm_activities_endpoint_returns_tenant_scoped_activities_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_activities_for_demo()

    response = client.get("/v1/crm/activities", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.activities"
    assert body["audit_event_id"]
    assert [activity["subject"] for activity in body["activities"]] == ["Acme follow-up", "Northwind review"]
    assert {activity["object_type"] for activity in body["activities"]} == {"crm.activity"}
    assert {activity["data_classification"] for activity in body["activities"]} == {"personal"}
    assert {activity["retention_policy_id"] for activity in body["activities"]} == {"rp-standard"}
    assert [activity["contact_object_id"] for activity in body["activities"]] == [
        "crm-contact-ada-demo",
        "crm-contact-max-demo",
    ]
    assert all(activity["access_checked"] for activity in body["activities"])
    assert all(activity["linked_object_access_checked"] for activity in body["activities"])
    assert "Other tenant task" not in {activity["subject"] for activity in body["activities"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.activity.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_notes_endpoint_returns_metadata_only_notes_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_activities_for_demo()

    response = client.get("/v1/crm/notes", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.activities"
    assert body["audit_event_id"]
    assert [note["title"] for note in body["notes"]] == ["Acme onboarding note", "Northwind review note"]
    assert {note["object_type"] for note in body["notes"]} == {"crm.note"}
    assert {note["data_classification"] for note in body["notes"]} == {"personal"}
    assert {note["retention_policy_id"] for note in body["notes"]} == {"rp-standard"}
    assert all(note["access_checked"] for note in body["notes"])
    assert all(note["linked_object_access_checked"] for note in body["notes"])
    assert all("note_body" not in note for note in body["notes"])
    assert "Other tenant note" not in {note["title"] for note in body["notes"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.note.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_erp_products_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/erp/products", headers=DEMO_ERP_PRODUCT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_erp_products_endpoint_returns_internal_products_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_erp_products_for_demo()

    response = client.get("/v1/erp/products", headers=DEMO_ERP_PRODUCT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.erp.products"
    assert body["audit_event_id"]
    assert [product["display_name"] for product in body["products"]] == ["Service Plan", "Standard Widget"]
    assert {product["object_type"] for product in body["products"]} == {"erp.product"}
    assert {product["data_classification"] for product in body["products"]} == {"internal"}
    assert {product["retention_policy_id"] for product in body["products"]} == {"rp-standard"}
    assert all(product["access_checked"] for product in body["products"])
    assert "Other Tenant Product" not in {product["display_name"] for product in body["products"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "erp.product.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_knowledge_base_articles_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_knowledge_base_articles_endpoint_returns_metadata_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_knowledge_base_articles_for_demo()

    response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["feature_id"] == "knowledge_base.articles.read"
    assert body["audit_event_id"]
    assert body["restore_evidence_hash"].startswith("sha256:")
    assert len(body["source_version_evidence_hashes"]) == 2
    assert [article["title"] for article in body["articles"]] == ["Backup Restore Runbook", "Security Baseline"]
    assert {article["object_type"] for article in body["articles"]} == {"kb.article"}
    assert {article["data_classification"] for article in body["articles"]} == {"internal"}
    assert {article["retention_policy_id"] for article in body["articles"]} == {"rp-standard"}
    assert all(article["access_checked"] for article in body["articles"])
    assert all(article["source_version_access_checked"] for article in body["articles"])
    assert {article["current_source_version_id"] for article in body["articles"]} == {"v1"}
    assert all(article["source_version_evidence_hash"].startswith("sha256:") for article in body["articles"])
    assert all("article_body" not in article for article in body["articles"])
    assert "Other Tenant Article" not in {article["title"] for article in body["articles"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "knowledge_base.article.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["continuity_domain"] == "knowledge_base_content"
    assert new_events[-1].metadata["restore_evidence_hash"] == body["restore_evidence_hash"]
    assert new_events[-1].metadata["source_version_evidence_hashes"] == body["source_version_evidence_hashes"]


def test_knowledge_base_admin_evidence_endpoint_is_compliance_scoped_and_metadata_only() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base evidence"},
    )
    assert provision_response.status_code == 200
    assert provision_response.json()["status"] == "disabled"

    normal_response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)
    assert normal_response.status_code == 403
    assert "not enabled" in normal_response.json()["detail"]

    non_admin_response = client.get("/v1/admin/kb/evidence", headers=DEMO_HEADERS)
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    response = client.get("/v1/admin/kb/evidence", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    body_text = json.dumps(body)
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["continuity_domain"] == "knowledge_base_content"
    assert len(body["source_version_evidence"]) == 2
    assert body["restore_evidence"]["source_version_evidence_count"] == 2
    assert body["restore_evidence"]["disabled_state_restore_verified"] is True
    assert body["restore_evidence"]["legal_hold_restore_verified"] is True
    assert body["restore_evidence"]["evidence_hash"].startswith("sha256:")
    assert {evidence["source_version_id"] for evidence in body["source_version_evidence"]} == {"v1"}
    assert all(evidence["evidence_hash"].startswith("sha256:") for evidence in body["source_version_evidence"])
    assert "article_body" not in body_text
    assert "source content" not in body_text
    assert "prompt_text" not in body_text
    assert "output_text" not in body_text

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "knowledge_base.evidence.read"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["surface"] == "compliance_api"
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["restore_evidence_hash"] == body["restore_evidence"]["evidence_hash"]


def test_knowledge_base_write_dry_run_endpoint_requires_admin_and_does_not_persist() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base write dry-run"},
    )
    assert provision_response.status_code == 200
    assert provision_response.json()["status"] == "disabled"
    payload = {
        "approval_reference": "approval:kb-write-dry-run",
        "reason": "prepare controlled knowledge base edit",
        "operation": "edit",
        "article_object_id": "kb-article-backup-runbook-demo",
        "article_key": "KB-BACKUP-001",
        "title": "Backup Restore Runbook",
        "proposed_version_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_version_label": "v2",
        "proposed_source_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_source_version_id": "v2",
        "proposed_source_manifest_hash": "sha256:" + "3" * 64,
        "proposed_content_hash": "sha256:" + "4" * 64,
        "proposed_acl_version": 1,
        "expected_current_version_object_id": "kb-article-version-backup-runbook-v1-demo",
    }

    normal_response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)
    assert normal_response.status_code == 403

    non_admin_response = client.post("/v1/admin/kb/articles/write-dry-run", headers=DEMO_HEADERS, json=payload)
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    response = client.post("/v1/admin/kb/articles/write-dry-run", headers=DEMO_ADMIN_HEADERS, json=payload)

    assert response.status_code == 200
    body = response.json()
    body_text = json.dumps(body)
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["feature_id"] == "knowledge_base.articles.write"
    assert body["operation"] == "edit"
    assert body["dry_run"] is True
    assert body["persistence_allowed"] is False
    assert body["rag_indexing_allowed"] is False
    assert body["source_authority_verified"] is False
    assert body["command_hash"].startswith("sha256:")
    assert body["proposed_source_version_evidence_hash"].startswith("sha256:")
    assert body["current_restore_evidence_hash"].startswith("sha256:")
    assert "source_object_write_guard" in body["required_evidence"]
    assert "article_body" not in body_text
    assert "source content" not in body_text
    assert "prompt_text" not in body_text
    assert "output_text" not in body_text

    after_response = client.get("/v1/admin/kb/evidence", headers=DEMO_ADMIN_HEADERS)
    assert after_response.status_code == 200
    assert {evidence["source_version_id"] for evidence in after_response.json()["source_version_evidence"]} == {"v1"}

    invalid_body_response = client.post(
        "/v1/admin/kb/articles/write-dry-run",
        headers=DEMO_ADMIN_HEADERS,
        json={**payload, "article_body": "must not be accepted"},
    )
    assert invalid_body_response.status_code == 422

    new_events = app.state.audit_logger.events[starting_event_count:]
    dry_run_events = [event for event in new_events if event.event_type == "knowledge_base.write_approval.dry_run"]
    assert len(dry_run_events) == 1
    event = dry_run_events[0]
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["surface"] == "compliance_api"
    assert event.metadata["dry_run"] is True
    assert event.metadata["persistence_allowed"] is False
    assert event.metadata["command_hash"] == body["command_hash"]
    assert event.metadata["approval_reference"] == "approval:kb-write-dry-run"


def test_tenant_module_admin_actions_require_admin_role_and_approval_reference() -> None:
    reset_module_registry()

    non_admin_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    missing_approval_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"reason": "prepare module"},
    )
    assert missing_approval_response.status_code == 422


def test_tenant_admin_can_provision_enable_disable_and_suspend_module() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)

    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    assert provision_response.status_code == 200
    provisioned = provision_response.json()
    assert provisioned["status"] == "disabled"
    assert provisioned["normal_use_enabled"] is False
    assert provisioned["compliance_access_allowed"] is True
    assert provisioned["audit_chain_ref"].startswith("audit:")
    assert [evidence["version"] for evidence in provisioned["migration_evidence"]] == [
        "0007",
        "0008",
        "0009",
        "0010",
        "0011",
        "0016",
        "0017",
        "0018",
        "0019",
        "0020",
    ]

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    assert enable_response.status_code == 200
    enabled = enable_response.json()
    assert enabled["status"] == "enabled"
    assert enabled["normal_use_enabled"] is True
    assert enabled["enabled_features"]["crm_erp.crm.accounts"] is True

    disable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/disable",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-disable", "reason": "pause normal usage"},
    )
    assert disable_response.status_code == 200
    disabled = disable_response.json()
    assert disabled["status"] == "disabled"
    assert disabled["normal_use_enabled"] is False
    assert disabled["compliance_access_allowed"] is True

    suspend_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/suspend",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-suspend", "reason": "compliance review"},
    )
    assert suspend_response.status_code == 200
    suspended = suspend_response.json()
    assert suspended["status"] == "suspended"
    assert suspended["compliance_access_allowed"] is True

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-4:]] == [
        "tenant_module.provisioned",
        "tenant_module.enabled",
        "tenant_module.disabled",
        "tenant_module.suspended",
    ]
    assert all(event.input_hash is not None and event.output_hash is None for event in new_events[-4:])
    assert all("reason" not in event.metadata for event in new_events[-4:])


def test_tenant_module_decommission_check_is_admin_scoped_and_audited() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get("/v1/admin/tenant-modules/crm_erp/decommission-check", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["status"] == "disabled"
    assert body["can_decommission"] is False
    assert "Legal Hold check" in body["required_evidence"]
    assert "backup/restore evidence check" in body["required_evidence"]

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_check"
    assert new_events[-1].input_hash is None


def test_tenant_module_decommission_request_requires_evidence_and_blocks_normal_use() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    enabled_request_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    assert enabled_request_response.status_code == 400
    assert "disabled or suspended" in enabled_request_response.json()["detail"]

    client.post(
        "/v1/admin/tenant-modules/crm_erp/disable",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-disable", "reason": "pause normal usage"},
    )
    starting_event_count = len(app.state.audit_logger.events)

    request_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )

    assert request_response.status_code == 200
    body = request_response.json()
    assert body["status"] == "decommission_requested"
    assert body["normal_use_enabled"] is False
    assert body["compliance_access_allowed"] is True
    assert body["enabled_features"]["crm_erp.crm.accounts"] is False
    assert body["decommission_evidence_refs"]["retention_evaluation_ref"] == "retention:eval-1"
    assert body["decommission_evidence_refs"]["legal_hold_check_ref"] == "legal-hold:check-1"
    assert body["decommission_evidence_refs"]["export_archive_decision_ref"] == "export:decision-1"
    assert body["decommission_evidence_refs"]["audit_evidence_ref"] == "audit:evidence-1"
    assert body["decommission_evidence_refs"]["backup_restore_evidence_ref"] == "backup:restore-1"

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_requested"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-request"
    assert "reason" not in new_events[-1].metadata


def test_tenant_module_decommission_request_requires_all_evidence_refs() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    incomplete_payload = dict(DECOMMISSION_REQUEST_PAYLOAD)
    del incomplete_payload["backup_restore_evidence_ref"]

    response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_payload,
    )

    assert response.status_code == 422


def test_tenant_module_decommission_cancel_returns_to_disabled_and_audits() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    starting_event_count = len(app.state.audit_logger.events)

    cancel_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-cancel",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_CANCEL_PAYLOAD,
    )

    assert cancel_response.status_code == 200
    cancelled = cancel_response.json()
    assert cancelled["status"] == "disabled"
    assert cancelled["normal_use_enabled"] is False
    assert cancelled["compliance_access_allowed"] is True
    assert cancelled["decommission_cancelled_at_utc"] is not None
    assert cancelled["enabled_features"]["crm_erp.crm.accounts"] is False
    assert cancelled["decommission_evidence_refs"]["cancel_approval_ref"] == "approval:module-decommission-cancel"
    assert cancelled["decommission_evidence_refs"]["cancel_audit_evidence_ref"] == (
        "audit:decommission-cancel-evidence-1"
    )

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_cancelled"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-cancel"
    assert "reason" not in new_events[-1].metadata


def test_tenant_module_decommission_block_and_complete_are_audited() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    starting_event_count = len(app.state.audit_logger.events)

    block_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-block",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_BLOCK_PAYLOAD,
    )

    assert block_response.status_code == 200
    blocked = block_response.json()
    assert blocked["status"] == "decommission_blocked"
    assert blocked["normal_use_enabled"] is False
    assert blocked["compliance_access_allowed"] is True
    assert blocked["decommission_blocked_at_utc"] is not None
    assert blocked["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"
    assert blocked["decommission_evidence_refs"]["remediation_plan_ref"] == "decommission-remediation:plan-1"

    incomplete_completion_payload = dict(DECOMMISSION_COMPLETE_PAYLOAD)
    del incomplete_completion_payload["final_data_disposition_ref"]
    incomplete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-complete",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_completion_payload,
    )
    assert incomplete_response.status_code == 422

    complete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-complete",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_COMPLETE_PAYLOAD,
    )

    assert complete_response.status_code == 200
    completed = complete_response.json()
    assert completed["status"] == "decommissioned"
    assert completed["normal_use_enabled"] is False
    assert completed["compliance_access_allowed"] is False
    assert completed["decommissioned_at_utc"] is not None
    assert completed["decommission_evidence_refs"]["final_data_disposition_ref"] == "data-disposition:final-1"
    assert completed["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-2:]] == [
        "tenant_module.decommission_blocked",
        "tenant_module.decommission_completed",
    ]
    assert all(event.input_hash is not None for event in new_events[-2:])
    assert all("reason" not in event.metadata for event in new_events[-2:])


def test_tenant_module_decommission_reopen_requires_evidence_and_audits() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-block",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_BLOCK_PAYLOAD,
    )

    incomplete_payload = dict(DECOMMISSION_REOPEN_PAYLOAD)
    del incomplete_payload["reopen_audit_evidence_ref"]
    incomplete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-reopen",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_payload,
    )
    assert incomplete_response.status_code == 422

    starting_event_count = len(app.state.audit_logger.events)
    reopen_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-reopen",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REOPEN_PAYLOAD,
    )

    assert reopen_response.status_code == 200
    reopened = reopen_response.json()
    assert reopened["status"] == "decommission_requested"
    assert reopened["normal_use_enabled"] is False
    assert reopened["compliance_access_allowed"] is True
    assert reopened["decommission_reopened_at_utc"] is not None
    assert reopened["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"
    assert reopened["decommission_evidence_refs"]["blocker_remediation_evidence_ref"] == (
        "decommission-remediation:evidence-1"
    )
    assert reopened["decommission_evidence_refs"]["reopen_audit_evidence_ref"] == (
        "audit:decommission-reopen-evidence-1"
    )

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_reopened"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-reopen"
    assert "reason" not in new_events[-1].metadata


def test_admin_tenant_policy_requires_admin_role() -> None:
    response = client.get("/v1/admin/tenant-policy", headers=DEMO_HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant admin role required"


def test_embedding_model_admin_requires_security_admin_role() -> None:
    response = client.get("/v1/admin/embedding-models", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == "Security admin role required"


def test_authz_admin_mutations_require_security_admin_role_and_approval_reference() -> None:
    non_security_response = client.post(
        "/v1/admin/authz/roles",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "role_id": "auditor",
            "display_name": "Auditor",
            "approval_reference": "approval:authz-role",
            "reason": "create role",
        },
    )
    assert non_security_response.status_code == 403
    assert non_security_response.json()["detail"] == "Security admin role required"

    missing_approval_response = client.post(
        "/v1/admin/authz/roles",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={"role_id": "auditor", "display_name": "Auditor", "reason": "create role"},
    )
    assert missing_approval_response.status_code == 422


def test_security_admin_can_mutate_authz_store_and_replay_retention_with_audit() -> None:
    suffix = uuid4().hex
    subject = f"authz-subject-{suffix}"
    role_id = f"authz-role-{suffix}"
    group_id = f"authz-group-{suffix}"
    object_id = f"authz-doc-{suffix}"
    policy_id = f"authz-policy-{suffix}"
    starting_event_count = len(app.state.audit_logger.events)

    requests = [
        (
            "/v1/admin/authz/principals",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "user_id": f"authz-user-{suffix}",
                "display_name": "Authz User",
                "approval_reference": "approval:authz-principal",
                "reason": "register authz principal",
            },
            "tenant_principal",
        ),
        (
            "/v1/admin/authz/memberships",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "approval_reference": "approval:authz-membership",
                "reason": "activate tenant membership",
            },
            "tenant_principal_membership",
        ),
        (
            "/v1/admin/authz/roles",
            {
                "role_id": role_id,
                "display_name": "Authz Role",
                "approval_reference": "approval:authz-role",
                "reason": "create role",
            },
            "tenant_role",
        ),
        (
            "/v1/admin/authz/groups",
            {
                "group_id": group_id,
                "display_name": "Authz Group",
                "approval_reference": "approval:authz-group",
                "reason": "create group",
            },
            "tenant_group",
        ),
        (
            "/v1/admin/authz/role-assignments",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "role_id": role_id,
                "approval_reference": "approval:authz-role-assignment",
                "reason": "assign role",
            },
            "tenant_principal_role_assignment",
        ),
        (
            "/v1/admin/authz/group-memberships",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "group_id": group_id,
                "approval_reference": "approval:authz-group-membership",
                "reason": "assign group",
            },
            "tenant_principal_group_membership",
        ),
        (
            "/v1/admin/authz/object-acl-entries",
            {
                "object_id": object_id,
                "object_type": "document",
                "acl_subject_type": "group",
                "acl_subject_id": group_id,
                "permission": "read",
                "acl_version": 1,
                "approval_reference": "approval:authz-acl",
                "reason": "grant read access",
            },
            "object_acl_entry",
        ),
        (
            "/v1/admin/authz/abac-policy-bindings",
            {
                "policy_id": policy_id,
                "effect": "allow",
                "principal_selector": {"roles": [role_id]},
                "resource_selector": {"object_type": "document"},
                "condition": {"classification": {"not_in": ["confidential"]}},
                "priority": 10,
                "approval_reference": "approval:authz-abac",
                "reason": "bind ABAC policy",
            },
            "abac_policy_binding",
        ),
    ]

    for path, payload, resource_type in requests:
        response = client.post(path, headers=DEMO_SECURITY_ADMIN_HEADERS, json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == "tenant-demo"
        assert body["resource_type"] == resource_type
        assert body["audit_chain_ref"].startswith("audit:")

    purge_response = client.post(
        "/v1/admin/authz/jwt-replay-retention/purge",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "expires_before_epoch": 2_000,
            "approval_reference": "approval:authz-jwt-retention",
            "reason": "purge expired replay tokens",
        },
    )
    assert purge_response.status_code == 200
    purge_body = purge_response.json()
    assert purge_body["tenant_id"] == "tenant-demo"
    assert purge_body["audit_chain_ref"].startswith("audit:")

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-9:]] == [
        "authz.principal.upsert",
        "authz.membership.upsert",
        "authz.role.upsert",
        "authz.group.upsert",
        "authz.role_assignment.upsert",
        "authz.group_membership.upsert",
        "authz.object_acl.upsert",
        "authz.abac_policy_binding.upsert",
        "authz.jwt_replay_retention.purge",
    ]
    assert all(event.input_hash is not None and event.output_hash is None for event in new_events[-9:])
    assert all("reason" not in event.metadata for event in new_events[-9:])


def test_admin_tenant_policy_rejects_unknown_allowed_model() -> None:
    response = client.patch(
        "/v1/admin/tenant-policy/ai-settings",
        headers=DEMO_ADMIN_HEADERS,
        json={"allowed_model_ids": ["unknown-model"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown model: unknown-model"


def test_admin_can_update_tenant_ai_settings() -> None:
    response = client.patch(
        "/v1/admin/tenant-policy/ai-settings",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "ai_enabled": True,
            "rag_enabled": True,
            "voice_enabled": True,
            "external_ai_enabled": False,
            "allowed_model_ids": ["mock-summarizer"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["ai_enabled"] is True
    assert body["rag_enabled"] is True
    assert body["voice_enabled"] is True
    assert body["external_ai_enabled"] is False
    assert set(body["allowed_model_ids"]) == {"mock-summarizer"}

    matching_audit_events = [
        event for event in app.state.audit_logger.events if event.event_type == "tenant_policy.ai_settings.update"
    ]
    assert matching_audit_events
    assert matching_audit_events[-1].metadata["allowed_model_count"] == 1


def test_security_admin_can_register_approve_and_retire_embedding_model_version() -> None:
    model_id = f"api-embedding-{uuid4().hex}"
    registration_response = client.post(
        "/v1/admin/embedding-models",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "embedding_model_id": model_id,
            "embedding_model_version": "2026-06-11",
            "provider": "local",
            "deployment": "deterministic-hash",
            "dimensions": 3,
            "distance_metric": "cosine",
            "checksum": "sha256:api-embedding-model",
            "approved_for_data_classes": ["internal", "personal"],
            "change_reference": "change:api-embedding-model",
        },
    )
    assert registration_response.status_code == 200
    registered = registration_response.json()
    assert registered["embedding_model_id"] == model_id
    assert registered["approved_at_utc"] is None

    approval_response = client.post(
        f"/v1/admin/embedding-models/{model_id}/versions/2026-06-11/approve",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={"approval_reference": "approval:api-embedding-model"},
    )
    assert approval_response.status_code == 200
    approved = approval_response.json()
    assert approved["approved_at_utc"] is not None

    retirement_response = client.post(
        f"/v1/admin/embedding-models/{model_id}/versions/2026-06-11/retire",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "retirement_reference": "approval:api-embedding-model-retire",
            "reason": "superseded",
        },
    )
    assert retirement_response.status_code == 200
    retired = retirement_response.json()
    assert retired["retired_at_utc"] is not None

    matching_audit_events = [
        event for event in app.state.audit_logger.events if event.metadata.get("embedding_model_id") == model_id
    ]
    assert [event.event_type for event in matching_audit_events[-3:]] == [
        "embedding_model_version.registered",
        "embedding_model_version.approved",
        "embedding_model_version.retired",
    ]
    assert all(event.input_hash is None and event.output_hash is None for event in matching_audit_events[-3:])


def test_inference_writes_untrusted_output() -> None:
    response = client.post(
        "/v1/ai/inference",
        headers=DEMO_HEADERS,
        json={"input_text": "Bitte zusammenfassen.", "source_object_ids": ["doc-1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["output_trust"] == "untrusted"
    assert body["model_id"] == "mock-summarizer"
    assert body["audit_event_id"]


def test_rag_filters_unauthorized_sources_before_context() -> None:
    response = client.post(
        "/v1/rag/query",
        headers=DEMO_HEADERS,
        json={"question": "Was ist die Policy?", "top_k": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert [source["object_id"] for source in body["sources"]] == ["doc-1"]
    assert all(source["access_checked"] for source in body["sources"])
    assert "secret-1" not in body["answer"]


def test_keyword_search_returns_candidate_only_authorized_results_and_audit() -> None:
    starting_event_count = len(app.state.audit_logger.events)

    response = client.post(
        "/v1/search/keyword",
        headers=DEMO_HEADERS,
        json={"query": "policy citations", "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_policy_id"] == "keyword_candidate_acl_v1"
    assert body["audit_event_id"]
    assert [candidate["object_id"] for candidate in body["candidates"]] == ["doc-1"]
    assert body["candidates"][0]["access_checked"] is True
    assert "text" not in body["candidates"][0]
    assert "snippet" not in body["candidates"][0]
    assert "AI suggestions must remain drafts" not in response.text
    assert "This confidential source" not in response.text

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "search.keyword.query"
    assert new_events[-1].event_id == body["audit_event_id"]
    assert new_events[-1].input_hash is not None
    assert new_events[-1].output_hash is None
    assert new_events[-1].source_object_ids == ["doc-1"]
    assert new_events[-1].metadata["authorized_candidate_count"] == 1
    assert "query" not in new_events[-1].metadata


def test_voice_requires_push_to_talk() -> None:
    response = client.post(
        "/v1/voice/transcripts",
        headers=DEMO_HEADERS,
        json={"transcript": "Fasse diese Mail zusammen.", "push_to_talk_active": False},
    )
    assert response.status_code == 403
