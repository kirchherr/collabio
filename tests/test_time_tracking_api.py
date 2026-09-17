from typing import Any

from fastapi.testclient import TestClient

from main import app
from suite.platform.modules import default_module_registry
from suite.platform.time_tracking_module import (
    TIME_APPROVALS_READ_FEATURE_ID,
    TIME_APPROVALS_WRITE_FEATURE_ID,
    TIME_ENTRIES_READ_FEATURE_ID,
    TIME_ENTRIES_WRITE_FEATURE_ID,
)
from suite.platform.time_tracking_service import InMemoryTimeTrackingStore, TimeTrackingService

client = TestClient(app)

ADMIN_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "tenant-admin",
}
READER_HEADERS = {**ADMIN_HEADERS, "X-Role-Ids": "knowledge-worker"}
PAYLOAD: dict[str, Any] = {
    "mutation_reference": "request:api-time-entry-v1",
    "entry_object_id": "time-entry-api-v1",
    "entry_number": "TIME-API-001",
    "work_date": "2026-07-30",
    "started_at_utc": "2026-07-30T08:00:00Z",
    "ended_at_utc": "2026-07-30T12:30:00Z",
    "project_reference": "project:customer-review",
    "cost_center_reference": "cost-center:delivery",
    "approval_object_id": "time-approval-api-v1",
    "approval_number": "TIME-APPROVAL-API-001",
}


def reset_runtime() -> None:
    app.state.module_registry = default_module_registry()
    app.state.time_tracking_service = TimeTrackingService(
        store=InMemoryTimeTrackingStore(),
        audit_logger=app.state.audit_logger,
    )


def enable_time_tracking_features() -> None:
    provision = client.post(
        "/v1/admin/tenant-modules/time_tracking/provision",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:time-tracking-provision",
            "reason": "prepare productive time tracking slice",
        },
    )
    assert provision.status_code == 200, provision.text
    enable = client.post(
        "/v1/admin/tenant-modules/time_tracking/enable",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:time-tracking-enable",
            "reason": "activate governed time entry creation",
            "enabled_features": {
                TIME_ENTRIES_READ_FEATURE_ID: True,
                TIME_APPROVALS_READ_FEATURE_ID: True,
                TIME_APPROVALS_WRITE_FEATURE_ID: True,
                TIME_ENTRIES_WRITE_FEATURE_ID: True,
            },
        },
    )
    assert enable.status_code == 200, enable.text


def test_time_tracking_api_requires_enabled_module_features_and_creator_role() -> None:
    reset_runtime()

    module_blocked = client.post("/v1/time-tracking/entries", headers=ADMIN_HEADERS, json=PAYLOAD)
    assert module_blocked.status_code == 404

    enable_time_tracking_features()
    role_blocked = client.post("/v1/time-tracking/entries", headers=READER_HEADERS, json=PAYLOAD)
    assert role_blocked.status_code == 403
    assert role_blocked.json()["detail"] == "Time Tracking creator role required"


def test_time_tracking_api_creates_replays_and_reads_only_authorized_objects() -> None:
    reset_runtime()
    enable_time_tracking_features()

    first = client.post("/v1/time-tracking/entries", headers=ADMIN_HEADERS, json=PAYLOAD)
    replay = client.post("/v1/time-tracking/entries", headers=ADMIN_HEADERS, json=PAYLOAD)
    conflict = client.post(
        "/v1/time-tracking/entries",
        headers=ADMIN_HEADERS,
        json={**PAYLOAD, "cost_center_reference": "cost-center:changed"},
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert conflict.status_code == 409
    body = first.json()
    assert body["atomic_transaction_committed"] is True
    assert body["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["receipt"]["receipt_hash"] == body["receipt"]["receipt_hash"]
    assert body["entry"]["duration_minutes"] == 270
    assert body["approval"]["approval_state"] == "not_submitted"
    assert body["approval"]["approver_principal_id"] is None
    assert body["acl_grant_count"] == 2
    assert body["receipt_content_included"] is False
    assert "project_reference" not in body["receipt"]

    readable_headers = {
        **ADMIN_HEADERS,
        "X-Readable-Object-Ids": f"{PAYLOAD['entry_object_id']},{PAYLOAD['approval_object_id']}",
    }
    entries = client.get("/v1/time-tracking/entries", headers=readable_headers)
    approvals = client.get("/v1/time-tracking/approvals", headers=readable_headers)
    hidden_approvals = client.get(
        "/v1/time-tracking/approvals",
        headers={**ADMIN_HEADERS, "X-Readable-Object-Ids": str(PAYLOAD["approval_object_id"])},
    )

    assert entries.status_code == 200
    assert approvals.status_code == 200
    assert [item["object_id"] for item in entries.json()["entries"]] == [PAYLOAD["entry_object_id"]]
    assert [item["object_id"] for item in approvals.json()["approvals"]] == [PAYLOAD["approval_object_id"]]
    assert hidden_approvals.json()["approvals"] == []


def test_time_tracking_api_submits_and_approves_with_maker_checker_evidence() -> None:
    reset_runtime()
    enable_time_tracking_features()
    created = client.post("/v1/time-tracking/entries", headers=ADMIN_HEADERS, json=PAYLOAD)
    assert created.status_code == 200, created.text
    readable = {
        **ADMIN_HEADERS,
        "X-Readable-Object-Ids": f"{PAYLOAD['entry_object_id']},{PAYLOAD['approval_object_id']}",
    }
    submission_payload = {
        "mutation_reference": "request:api-time-submit-v1",
        "decision_object_id": "time-decision-submit-v1",
        "expected_state": "not_submitted",
        "target_state": "submitted",
        "action": "submit",
        "source_system": "native",
    }
    submitted = client.post(
        f"/v1/time-tracking/approvals/{PAYLOAD['approval_object_id']}/transitions",
        headers=readable,
        json=submission_payload,
    )
    replay = client.post(
        f"/v1/time-tracking/approvals/{PAYLOAD['approval_object_id']}/transitions",
        headers=readable,
        json=submission_payload,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["approval"]["approval_state"] == "submitted"
    assert submitted.json()["decision"]["sequence_no"] == 1
    assert submitted.json()["decision"]["previous_decision_hash"] == "sha256:" + "0" * 64
    assert submitted.json()["maker_checker_verified"] is True
    assert replay.json()["idempotent_replay"] is True

    self_approval = client.post(
        f"/v1/time-tracking/approvals/{PAYLOAD['approval_object_id']}/transitions",
        headers=readable,
        json={
            "mutation_reference": "request:api-time-approve-self-v1",
            "decision_object_id": "time-decision-approve-self-v1",
            "expected_state": "submitted",
            "target_state": "approved",
            "action": "approve",
            "human_confirmation_statement": (
                f"I explicitly confirm time approval {PAYLOAD['approval_object_id']} decision approved."
            ),
            "source_system": "native",
        },
    )
    assert self_approval.status_code == 403
    assert self_approval.json()["detail"] == "Time approval maker-checker separation required"

    approver_headers = {
        **readable,
        "X-User-Id": "approver-demo",
        "X-Role-Ids": "time-approver",
    }
    approval_payload = {
        "mutation_reference": "request:api-time-approve-v1",
        "decision_object_id": "time-decision-approve-v1",
        "expected_state": "submitted",
        "target_state": "approved",
        "action": "approve",
        "human_confirmation_statement": (
            f"I explicitly confirm time approval {PAYLOAD['approval_object_id']} decision approved."
        ),
        "source_system": "native",
    }
    approved = client.post(
        f"/v1/time-tracking/approvals/{PAYLOAD['approval_object_id']}/transitions",
        headers=approver_headers,
        json=approval_payload,
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["approval"]["approval_state"] == "approved"
    assert body["entry"]["lifecycle_state"] == "approved"
    assert body["decision"]["sequence_no"] == 2
    assert body["decision"]["confirmation_statement_hash"].startswith("sha256:")
    assert "human_confirmation_statement" not in body["decision"]
