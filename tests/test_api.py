from uuid import uuid4

from fastapi.testclient import TestClient

from main import app

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
