from uuid import uuid4

from fastapi.testclient import TestClient

from main import app
from suite.platform.modules import default_module_registry

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
DECOMMISSION_REQUEST_PAYLOAD = {
    "approval_reference": "approval:module-decommission-request",
    "reason": "tenant requests controlled module decommission",
    "retention_evaluation_ref": "retention:eval-1",
    "legal_hold_check_ref": "legal-hold:check-1",
    "export_archive_decision_ref": "export:decision-1",
    "audit_evidence_ref": "audit:evidence-1",
    "backup_restore_evidence_ref": "backup:restore-1",
}


def reset_module_registry() -> None:
    app.state.module_registry = default_module_registry()


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tenant_data_endpoints_require_request_context() -> None:
    response = client.post("/v1/ai/inference", json={"input_text": "Bitte zusammenfassen."})
    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


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
    assert len(body["modules"]) == 1
    module = body["modules"][0]
    assert module["module_id"] == "crm_erp"
    assert module["display_name"] == "CRM/ERP"
    assert module["status"] == "available"
    assert module["normal_use_enabled"] is False
    assert module["compliance_access_allowed"] is False
    assert module["enabled_features"]["crm_erp.legacy_import.sqlserver"] is False
    assert "audit_chain_ref" not in module
    assert "policy_snapshot_hash" not in module
    assert "changed_by" not in module


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


def test_admin_tenant_policy_requires_admin_role() -> None:
    response = client.get("/v1/admin/tenant-policy", headers=DEMO_HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant admin role required"


def test_embedding_model_admin_requires_security_admin_role() -> None:
    response = client.get("/v1/admin/embedding-models", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == "Security admin role required"


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


def test_voice_requires_push_to_talk() -> None:
    response = client.post(
        "/v1/voice/transcripts",
        headers=DEMO_HEADERS,
        json={"transcript": "Fasse diese Mail zusammen.", "push_to_talk_active": False},
    )
    assert response.status_code == 403
