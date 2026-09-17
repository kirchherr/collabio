from typing import Any

from fastapi.testclient import TestClient

from main import app
from suite.platform.modules import default_module_registry
from suite.platform.tasks_activities_module import (
    TASKS_ACTIVITY_READ_FEATURE_ID,
    TASKS_ITEMS_READ_FEATURE_ID,
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
)
from suite.platform.tasks_activities_service import (
    InMemoryTasksActivitiesStore,
    TasksActivitiesService,
)

client = TestClient(app)

ADMIN_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "tenant-admin",
}
READER_HEADERS = {**ADMIN_HEADERS, "X-Role-Ids": "knowledge-worker"}
PAYLOAD: dict[str, Any] = {
    "mutation_reference": "request:api-task-create-v1",
    "task_object_id": "task-api-create-v1",
    "task_number": "TASK-API-001",
    "title": "Prepare API customer review",
    "priority": "high",
    "due_at_utc": "2026-08-05T10:00:00Z",
    "activity_object_id": "task-activity-api-create-v1",
    "activity_number": "TASK-ACT-API-001",
    "activity_summary": "Task created through API",
}


def reset_runtime() -> None:
    app.state.module_registry = default_module_registry()
    app.state.tasks_activities_service = TasksActivitiesService(
        store=InMemoryTasksActivitiesStore(),
        audit_logger=app.state.audit_logger,
    )


def enable_tasks_features() -> None:
    provision = client.post(
        "/v1/admin/tenant-modules/tasks_activities/provision",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:tasks-provision",
            "reason": "prepare productive task slice",
        },
    )
    assert provision.status_code == 200, provision.text
    enable = client.post(
        "/v1/admin/tenant-modules/tasks_activities/enable",
        headers=ADMIN_HEADERS,
        json={
            "approval_reference": "approval:tasks-enable",
            "reason": "activate governed task creation",
            "enabled_features": {
                TASKS_ITEMS_READ_FEATURE_ID: True,
                TASKS_ACTIVITY_READ_FEATURE_ID: True,
                TASKS_WORKFLOW_WRITE_FEATURE_ID: True,
            },
        },
    )
    assert enable.status_code == 200, enable.text


def test_tasks_api_requires_installed_tenant_module_features_and_operator_role() -> None:
    reset_runtime()

    module_blocked = client.post("/v1/tasks/items", headers=ADMIN_HEADERS, json=PAYLOAD)
    assert module_blocked.status_code == 404

    enable_tasks_features()
    role_blocked = client.post("/v1/tasks/items", headers=READER_HEADERS, json=PAYLOAD)
    assert role_blocked.status_code == 403
    assert role_blocked.json()["detail"] == "Tasks & Activities operator role required"


def test_tasks_api_creates_replays_and_reads_only_authorized_objects() -> None:
    reset_runtime()
    enable_tasks_features()

    first = client.post("/v1/tasks/items", headers=ADMIN_HEADERS, json=PAYLOAD)
    replay = client.post("/v1/tasks/items", headers=ADMIN_HEADERS, json=PAYLOAD)
    conflict = client.post(
        "/v1/tasks/items",
        headers=ADMIN_HEADERS,
        json={**PAYLOAD, "title": "Changed title"},
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert conflict.status_code == 409
    body = first.json()
    assert body["atomic_transaction_committed"] is True
    assert body["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["receipt"]["receipt_hash"] == body["receipt"]["receipt_hash"]
    assert body["acl_grant_count"] == 2
    assert body["receipt_content_included"] is False
    assert "title" not in body["receipt"]
    assert "activity_summary" not in body["receipt"]

    readable_headers = {
        **ADMIN_HEADERS,
        "X-Readable-Object-Ids": f"{PAYLOAD['task_object_id']},{PAYLOAD['activity_object_id']}",
    }
    items = client.get("/v1/tasks/items", headers=readable_headers)
    activities = client.get("/v1/tasks/activities", headers=readable_headers)
    hidden_activities = client.get(
        "/v1/tasks/activities",
        headers={
            **ADMIN_HEADERS,
            "X-Readable-Object-Ids": str(PAYLOAD["activity_object_id"]),
        },
    )

    assert items.status_code == 200
    assert activities.status_code == 200
    assert [item["object_id"] for item in items.json()["items"]] == [PAYLOAD["task_object_id"]]
    assert [item["object_id"] for item in activities.json()["activities"]] == [PAYLOAD["activity_object_id"]]
    assert hidden_activities.json()["activities"] == []


def test_tasks_api_commits_append_only_lifecycle_transitions() -> None:
    reset_runtime()
    enable_tasks_features()
    created = client.post("/v1/tasks/items", headers=ADMIN_HEADERS, json=PAYLOAD)
    assert created.status_code == 200, created.text
    readable = {
        **ADMIN_HEADERS,
        "X-Readable-Object-Ids": f"{PAYLOAD['task_object_id']},{PAYLOAD['activity_object_id']}",
    }
    transition_payload = {
        "mutation_reference": "request:api-task-start-v1",
        "transition_object_id": "task-transition-start-v1",
        "activity_object_id": "task-activity-start-v1",
        "activity_number": "TASK-ACT-API-START-001",
        "expected_state": "assigned",
        "target_state": "in_progress",
        "transition_kind": "started",
        "activity_summary": "Task work started",
        "source_system": "native",
    }
    transitioned = client.post(
        f"/v1/tasks/items/{PAYLOAD['task_object_id']}/transitions",
        headers=readable,
        json=transition_payload,
    )
    replay = client.post(
        f"/v1/tasks/items/{PAYLOAD['task_object_id']}/transitions",
        headers=readable,
        json=transition_payload,
    )
    assert transitioned.status_code == 200, transitioned.text
    body = transitioned.json()
    assert body["task"]["lifecycle_state"] == "in_progress"
    assert body["transition"]["sequence_no"] == 1
    assert body["transition"]["previous_transition_hash"] == "sha256:" + "0" * 64
    assert body["transition"]["confirmation_statement_hash"] is None
    assert body["transition_content_included"] is False
    assert replay.json()["idempotent_replay"] is True

    stale = client.post(
        f"/v1/tasks/items/{PAYLOAD['task_object_id']}/transitions",
        headers=readable,
        json={
            **transition_payload,
            "mutation_reference": "request:api-task-stale-v1",
            "transition_object_id": "task-transition-stale-v1",
            "activity_object_id": "task-activity-stale-v1",
            "activity_number": "TASK-ACT-API-STALE-001",
        },
    )
    assert stale.status_code == 409
    assert "expected assigned, current in_progress" in stale.json()["detail"]

    cancelled = client.post(
        f"/v1/tasks/items/{PAYLOAD['task_object_id']}/transitions",
        headers=readable,
        json={
            "mutation_reference": "request:api-task-cancel-v1",
            "transition_object_id": "task-transition-cancel-v1",
            "activity_object_id": "task-activity-cancel-v1",
            "activity_number": "TASK-ACT-API-CANCEL-001",
            "expected_state": "in_progress",
            "target_state": "cancelled",
            "transition_kind": "cancelled",
            "activity_summary": "Task cancelled by operator",
            "human_confirmation_statement": (
                f"I explicitly confirm task {PAYLOAD['task_object_id']} transition to cancelled."
            ),
            "source_system": "native",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["transition"]["sequence_no"] == 2
    assert cancelled.json()["transition"]["confirmation_statement_hash"].startswith("sha256:")

    listed = client.get("/v1/tasks/items", headers=readable)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["lifecycle_state"] == "cancelled"
