from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
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
