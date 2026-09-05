from fastapi.testclient import TestClient

from main import app
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleStatus,
    default_module_catalog_entries,
    default_tenant_module_seed_states,
)
from suite.platform.tickets_incidents_module import (
    TICKETS_EVENTS_READ_FEATURE_ID,
    TICKETS_EVENTS_WRITE_FEATURE_ID,
    TICKETS_ITEMS_READ_FEATURE_ID,
    TICKETS_ITEMS_WRITE_FEATURE_ID,
)
from suite.platform.tickets_incidents_service import (
    InMemoryTicketRepository,
    TicketService,
)

client = TestClient(app)


def enabled_tickets_registry() -> InMemoryModuleRegistry:
    entries = [
        (
            entry.model_copy(update={"status": ModuleStatus.INSTALLED})
            if entry.module_id == "tickets_incidents"
            else entry
        )
        for entry in default_module_catalog_entries()
    ]
    registry = InMemoryModuleRegistry(
        catalog_entries=entries,
        tenant_modules=list(default_tenant_module_seed_states()),
    )
    registry.provision_tenant_module(
        tenant_id="tenant-demo",
        module_id="tickets_incidents",
        policy_snapshot_hash="sha256:tickets-pilot-policy",
        changed_by="tenant-admin-1",
        audit_chain_ref="audit:tickets-pilot-provision",
        migration_manifest_entries=load_migration_manifest(),
    )
    registry.enable_tenant_module(
        tenant_id="tenant-demo",
        module_id="tickets_incidents",
        policy_snapshot_hash="sha256:tickets-pilot-policy",
        changed_by="tenant-admin-1",
        audit_chain_ref="audit:tickets-pilot-enable",
        enabled_features={
            TICKETS_ITEMS_READ_FEATURE_ID: True,
            TICKETS_ITEMS_WRITE_FEATURE_ID: True,
            TICKETS_EVENTS_READ_FEATURE_ID: True,
            TICKETS_EVENTS_WRITE_FEATURE_ID: True,
        },
    )
    return registry


def test_tickets_api_vertical_slice_stays_gated_then_runs_end_to_end() -> None:
    headers = {
        "X-Tenant-Id": "tenant-demo",
        "X-User-Id": "tenant-admin-1",
        "X-Role-Ids": "tenant-admin",
    }
    original_registry = app.state.module_registry
    original_service = app.state.ticket_service
    try:
        blocked = client.get("/v1/tickets", headers=headers)
        assert blocked.status_code == 404

        app.state.module_registry = enabled_tickets_registry()
        app.state.ticket_service = TicketService(
            repository=InMemoryTicketRepository(),
            audit_logger=app.state.audit_logger,
        )
        created = client.post(
            "/v1/tickets",
            headers=headers,
            json={
                "ticket_id": "ticket-api-1",
                "ticket_number": "API-1001",
                "subject_redacted": "Pilot access request",
                "priority": "urgent",
                "kms_key_ref": "kms:tenant-demo:tickets",
                "audit_chain_ref": "audit:ticket-api-1:create",
                "created_event_id": "event:ticket-api-1:create",
                "created_event_summary_redacted": "Ticket created",
                "occurred_at_utc": "2026-07-29T08:00:00Z",
            },
        )
        listed = client.get("/v1/tickets", headers=headers)
        transitioned = client.post(
            "/v1/tickets/ticket-api-1/transitions",
            headers=headers,
            json={
                "event_id": "event:ticket-api-1:open",
                "expected_status": "new",
                "new_status": "open",
                "event_summary_redacted": "Ticket accepted",
                "audit_chain_ref": "audit:ticket-api-1:open",
                "occurred_at_utc": "2026-07-29T08:05:00Z",
            },
        )
        events = client.get("/v1/tickets/ticket-api-1/events", headers=headers)

        assert created.status_code == 201
        assert created.json()["ticket"]["ticket_status"] == "new"
        assert listed.status_code == 200
        assert [item["ticket_id"] for item in listed.json()["tickets"]] == ["ticket-api-1"]
        assert transitioned.status_code == 200
        assert transitioned.json()["ticket"]["ticket_status"] == "open"
        assert events.status_code == 200
        assert [item["event_type"] for item in events.json()["events"]] == [
            "created",
            "status_changed",
        ]
        assert all(item["access_checked"] for item in events.json()["events"])
    finally:
        app.state.module_registry = original_registry
        app.state.ticket_service = original_service


def test_tickets_api_requires_request_context() -> None:
    assert client.get("/v1/tickets").status_code == 401
    assert client.post("/v1/tickets", json={}).status_code == 401
    assert (
        client.post(
            "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-records",
            json={},
        ).status_code
        == 401
    )
