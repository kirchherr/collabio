from datetime import UTC, datetime
from pathlib import Path

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.tickets_incidents_service import (
    CreateTicketCommand,
    InMemoryTicketRepository,
    PgTicketRepository,
    TicketPriority,
    TicketRecord,
    TicketService,
    TicketStatus,
    TransitionTicketCommand,
    build_default_ticket_repository,
)


def user(
    tenant_id: str = "tenant-a",
    user_id: str = "agent-a",
    roles: set[str] | None = None,
) -> UserContext:
    return UserContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role_ids=roles or {"tickets-agent"},
    )


def create_command(
    *,
    ticket_id: str = "ticket-1",
    ticket_number: str = "T-1001",
) -> CreateTicketCommand:
    return CreateTicketCommand(
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        subject_redacted="Access request",
        priority=TicketPriority.HIGH,
        kms_key_ref="kms:tenant-a:tickets",
        audit_chain_ref=f"audit:{ticket_id}:created",
        created_event_id=f"event:{ticket_id}:created",
        created_event_summary_redacted="Ticket created",
        occurred_at_utc=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
    )


def build_service(repository: InMemoryTicketRepository | None = None) -> TicketService:
    return TicketService(
        repository=repository or InMemoryTicketRepository(),
        audit_logger=InMemoryAuditLogger(),
    )


def test_ticket_create_and_transition_are_atomic_metadata_only_events() -> None:
    service = build_service()

    created = service.create_ticket(user_context=user(), command=create_command())
    transitioned = service.transition_ticket(
        user_context=user(),
        ticket_id="ticket-1",
        command=TransitionTicketCommand(
            event_id="event:ticket-1:open",
            expected_status=TicketStatus.NEW,
            new_status=TicketStatus.OPEN,
            event_summary_redacted="Ticket accepted",
            audit_chain_ref="audit:ticket-1:open",
            occurred_at_utc=datetime(2026, 7, 29, 8, 5, tzinfo=UTC),
        ),
    )
    events = service.list_events(user_context=user(), ticket_id="ticket-1")

    assert created.ticket.ticket_status == TicketStatus.NEW
    assert created.event.event_type == "created"
    assert transitioned.ticket.ticket_status == TicketStatus.OPEN
    assert transitioned.ticket.lifecycle_state == "open"
    assert transitioned.event.event_type == "status_changed"
    assert [item.event_id for item in events.events] == [
        "event:ticket-1:created",
        "event:ticket-1:open",
    ]
    assert all(item.access_checked for item in events.events)
    assert "kms_key_ref" not in created.ticket.model_dump()
    assert "ticket_content" not in created.model_dump()


def test_ticket_repository_enforces_tenant_isolation_and_owner_read_scope() -> None:
    repository = InMemoryTicketRepository(
        tickets=(
            TicketRecord(
                tenant_id="tenant-a",
                object_id="ticket-a",
                owner_principal_id="owner-a",
                created_by="agent-a",
                created_at_utc=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
                kms_key_ref="kms:tenant-a:tickets",
                audit_chain_ref="audit:ticket-a",
                ticket_id="ticket-a",
                ticket_number="T-A",
                subject_redacted="Tenant A",
            ),
            TicketRecord(
                tenant_id="tenant-b",
                object_id="ticket-b",
                owner_principal_id="owner-b",
                created_by="agent-b",
                created_at_utc=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
                kms_key_ref="kms:tenant-b:tickets",
                audit_chain_ref="audit:ticket-b",
                ticket_id="ticket-b",
                ticket_number="T-B",
                subject_redacted="Tenant B",
            ),
        )
    )
    service = build_service(repository)

    owner_view = service.list_tickets(user_context=user(user_id="owner-a", roles={"knowledge-worker"}))
    other_view = service.list_tickets(user_context=user(user_id="other-a", roles={"knowledge-worker"}))

    assert [item.ticket_id for item in owner_view.tickets] == ["ticket-a"]
    assert other_view.tickets == []
    with pytest.raises(KeyError, match="ticket not found"):
        service.get_ticket(
            user_context=user(tenant_id="tenant-b"),
            ticket_id="ticket-a",
        )
    with pytest.raises(PermissionError, match="not authorized"):
        service.get_ticket(
            user_context=user(user_id="other-a", roles={"knowledge-worker"}),
            ticket_id="ticket-a",
        )


def test_ticket_transition_rejects_invalid_or_stale_state_without_event_append() -> None:
    service = build_service()
    service.create_ticket(user_context=user(), command=create_command())

    with pytest.raises(ValueError, match="not allowed"):
        service.transition_ticket(
            user_context=user(),
            ticket_id="ticket-1",
            command=TransitionTicketCommand(
                event_id="event:ticket-1:archived",
                expected_status=TicketStatus.NEW,
                new_status=TicketStatus.ARCHIVED,
                event_summary_redacted="Invalid archive",
                audit_chain_ref="audit:ticket-1:invalid",
            ),
        )
    with pytest.raises(ValueError, match="concurrently"):
        service.transition_ticket(
            user_context=user(),
            ticket_id="ticket-1",
            command=TransitionTicketCommand(
                event_id="event:ticket-1:stale",
                expected_status=TicketStatus.OPEN,
                new_status=TicketStatus.RESOLVED,
                event_summary_redacted="Stale transition",
                audit_chain_ref="audit:ticket-1:stale",
            ),
        )

    events = service.list_events(user_context=user(), ticket_id="ticket-1")
    assert [item.event_id for item in events.events] == ["event:ticket-1:created"]


def test_ticket_write_requires_operator_role() -> None:
    service = build_service()

    with pytest.raises(PermissionError, match="operator role"):
        service.create_ticket(
            user_context=user(roles={"knowledge-worker"}),
            command=create_command(),
        )


def test_ticket_subject_and_event_summary_must_be_single_redacted_lines() -> None:
    with pytest.raises(ValueError, match="single redacted line"):
        CreateTicketCommand.model_validate(
            {
                **create_command().model_dump(),
                "subject_redacted": "line one\nline two",
            }
        )


def test_ticket_repository_backend_is_explicit_and_compose_uses_postgres() -> None:
    assert isinstance(
        build_default_ticket_repository({"SUITE_TICKETS_REPOSITORY_BACKEND": "memory"}),
        InMemoryTicketRepository,
    )
    repository = build_default_ticket_repository(
        {
            "SUITE_TICKETS_REPOSITORY_BACKEND": "postgres",
            "SUITE_DATABASE_DSN": "postgresql://app:secret@postgres/collabio",
        }
    )
    assert isinstance(repository, PgTicketRepository)
    assert repository.database_dsn == "postgresql://app:secret@postgres/collabio"

    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SUITE_TICKETS_REPOSITORY_BACKEND: postgres" in compose
