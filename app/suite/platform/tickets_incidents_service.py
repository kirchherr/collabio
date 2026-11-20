from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

import psycopg
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.tickets_incidents_module import TICKETS_INCIDENTS_MODULE_ID

TICKET_OBJECT_TYPE = "ticket.ticket"
TICKET_EVENT_OBJECT_TYPE = "ticket.event"
TICKET_SCHEMA_VERSION = "ticket_item.v1"
TICKET_EVENT_SCHEMA_VERSION = "ticket_event.v1"
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")
OPERATOR_ROLES = frozenset({"tenant-admin", "tenant_admin", "security-admin", "tickets-agent", "service-desk-agent"})


def utc_now() -> datetime:
    return datetime.now(UTC)


class TicketStatus(StrEnum):
    NEW = "new"
    OPEN = "open"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketSlaState(StrEnum):
    NOT_STARTED = "not_started"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    PAUSED = "paused"
    COMPLETED = "completed"


class TicketEventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"


class TicketRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TICKET_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: str = "new"
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TICKET_SCHEMA_VERSION
    ticket_id: str
    ticket_number: str
    ticket_status: TicketStatus = TicketStatus.NEW
    priority: TicketPriority = TicketPriority.NORMAL
    subject_redacted: str
    sla_state: TicketSlaState = TicketSlaState.NOT_STARTED

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "ticket_id",
        "ticket_number",
        "subject_redacted",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ticket metadata fields must not be empty")
        return value

    @field_validator("subject_redacted")
    @classmethod
    def require_redacted_subject(cls, value: str) -> str:
        if len(value) > 240 or "\n" in value or "\r" in value:
            raise ValueError("subject_redacted must be a single redacted line of at most 240 characters")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value):
            raise ValueError("ticket security references must be namespaced")
        return value

    @model_validator(mode="after")
    def require_governed_metadata(self) -> TicketRecord:
        if self.object_id != self.ticket_id or self.object_type != TICKET_OBJECT_TYPE:
            raise ValueError("ticket identity metadata is inconsistent")
        if self.schema_version != TICKET_SCHEMA_VERSION:
            raise ValueError("ticket schema version is invalid")
        if self.data_classification not in {DataClass.PERSONAL, DataClass.LEGAL_HOLD}:
            raise ValueError("ticket classification is invalid")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("ticket retention policy is invalid")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("ticket Legal Hold state is invalid")
        if self.legal_hold_state == "active" and self.retention_policy_id != "rp-legal-hold":
            raise ValueError("active Legal Hold requires rp-legal-hold")
        if self.lifecycle_state != self.ticket_status.value:
            raise ValueError("ticket lifecycle must match status")
        if not SOURCE_SYSTEM_PATTERN.fullmatch(self.source_system):
            raise ValueError("ticket source_system is invalid")
        return self


class TicketEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str = TICKET_EVENT_OBJECT_TYPE
    owner_principal_id: str
    created_by: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass = DataClass.PERSONAL
    retention_policy_id: str = "rp-standard"
    legal_hold_state: str = "none"
    lifecycle_state: str = "open"
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str = "native"
    schema_version: str = TICKET_EVENT_SCHEMA_VERSION
    event_id: str
    ticket_id: str
    event_type: TicketEventType
    event_status: str
    event_summary_redacted: str
    occurred_at_utc: datetime

    @field_validator(
        "tenant_id",
        "object_id",
        "owner_principal_id",
        "created_by",
        "event_id",
        "ticket_id",
        "event_status",
        "event_summary_redacted",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ticket event metadata fields must not be empty")
        return value

    @field_validator("event_summary_redacted")
    @classmethod
    def require_redacted_summary(cls, value: str) -> str:
        if len(value) > 400 or "\n" in value or "\r" in value:
            raise ValueError("event summary must be a single redacted line of at most 400 characters")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value):
            raise ValueError("ticket event security references must be namespaced")
        return value

    @model_validator(mode="after")
    def require_governed_metadata(self) -> TicketEventRecord:
        if self.object_id != self.event_id or self.object_type != TICKET_EVENT_OBJECT_TYPE:
            raise ValueError("ticket event identity metadata is inconsistent")
        if self.schema_version != TICKET_EVENT_SCHEMA_VERSION:
            raise ValueError("ticket event schema version is invalid")
        if self.data_classification not in {DataClass.PERSONAL, DataClass.LEGAL_HOLD}:
            raise ValueError("ticket event classification is invalid")
        if self.retention_policy_id not in {"rp-standard", "rp-restricted", "rp-legal-hold"}:
            raise ValueError("ticket event retention policy is invalid")
        if self.event_status not in {"open", "in_progress", "waiting", "resolved", "cancelled"}:
            raise ValueError("ticket event status is invalid")
        return self


class CreateTicketCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    ticket_number: str
    subject_redacted: str
    priority: TicketPriority = TicketPriority.NORMAL
    owner_principal_id: str | None = None
    kms_key_ref: str
    audit_chain_ref: str
    created_event_id: str
    created_event_summary_redacted: str
    occurred_at_utc: datetime = Field(default_factory=utc_now)
    source_system: str = "native"

    @field_validator(
        "ticket_id",
        "ticket_number",
        "subject_redacted",
        "created_event_id",
        "created_event_summary_redacted",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ticket create command fields must not be empty")
        return value.strip()

    @field_validator("subject_redacted")
    @classmethod
    def require_redacted_subject_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or len(value) > 240:
            raise ValueError("ticket subject must be a single redacted line")
        return value

    @field_validator("created_event_summary_redacted")
    @classmethod
    def require_redacted_event_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or len(value) > 400:
            raise ValueError("ticket event summary must be a single redacted line")
        return value

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value):
            raise ValueError("ticket create references must be namespaced")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at_utc must include a timezone")
        return value


class TransitionTicketCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("event_summary_redacted")
    @classmethod
    def require_redacted_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or len(value) > 400:
            raise ValueError("ticket event summary must be a single redacted line")
        return value

    event_id: str
    expected_status: TicketStatus
    new_status: TicketStatus
    event_summary_redacted: str
    audit_chain_ref: str
    occurred_at_utc: datetime = Field(default_factory=utc_now)

    @field_validator("event_id", "event_summary_redacted")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ticket transition fields must not be empty")
        return value.strip()

    @field_validator("audit_chain_ref")
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value):
            raise ValueError("ticket transition audit reference must be namespaced")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_change(self) -> TransitionTicketCommand:
        if self.expected_status == self.new_status:
            raise ValueError("ticket transition must change status")
        return self


class TicketView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    object_id: str
    object_type: str
    ticket_number: str
    subject_redacted: str
    ticket_status: TicketStatus
    priority: TicketPriority
    sla_state: TicketSlaState
    owner_principal_id: str
    created_at_utc: datetime
    updated_at_utc: datetime
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: str
    source_system: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class TicketEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    object_id: str
    object_type: str
    ticket_id: str
    event_type: TicketEventType
    event_status: str
    event_summary_redacted: str
    occurred_at_utc: datetime
    created_by: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    schema_version: str
    audit_chain_ref: str
    access_checked: bool = True


class TicketsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    tickets: list[TicketView]
    audit_event_id: str


class TicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    ticket: TicketView
    audit_event_id: str


class TicketEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    ticket_id: str
    events: list[TicketEventView]
    audit_event_id: str


class TicketMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    ticket: TicketView
    event: TicketEventView
    audit_event_id: str


class TicketRepository(Protocol):
    def list_tickets(self, *, tenant_id: str) -> Sequence[TicketRecord]: ...

    def get_ticket(self, *, tenant_id: str, ticket_id: str) -> TicketRecord: ...

    def list_events(self, *, tenant_id: str, ticket_id: str) -> Sequence[TicketEventRecord]: ...

    def create_ticket_with_event(
        self, *, ticket: TicketRecord, event: TicketEventRecord
    ) -> tuple[TicketRecord, TicketEventRecord]: ...

    def transition_ticket(
        self,
        *,
        ticket_id: str,
        expected_status: TicketStatus,
        updated: TicketRecord,
        event: TicketEventRecord,
    ) -> tuple[TicketRecord, TicketEventRecord]: ...


class InMemoryTicketRepository:
    def __init__(
        self,
        *,
        tickets: Sequence[TicketRecord] = (),
        events: Sequence[TicketEventRecord] = (),
    ) -> None:
        self._tickets = {(item.tenant_id, item.ticket_id): item for item in tickets}
        self._events = {(item.tenant_id, item.event_id): item for item in events}

    def list_tickets(self, *, tenant_id: str) -> Sequence[TicketRecord]:
        return tuple(
            sorted(
                (item for (stored_tenant, _), item in self._tickets.items() if stored_tenant == tenant_id),
                key=lambda item: (item.updated_at_utc, item.ticket_number),
                reverse=True,
            )
        )

    def get_ticket(self, *, tenant_id: str, ticket_id: str) -> TicketRecord:
        try:
            return self._tickets[(tenant_id, ticket_id)]
        except KeyError as exc:
            raise KeyError("ticket not found") from exc

    def list_events(self, *, tenant_id: str, ticket_id: str) -> Sequence[TicketEventRecord]:
        return tuple(
            sorted(
                (
                    item
                    for (stored_tenant, _), item in self._events.items()
                    if stored_tenant == tenant_id and item.ticket_id == ticket_id
                ),
                key=lambda item: (item.occurred_at_utc, item.event_id),
            )
        )

    def create_ticket_with_event(
        self, *, ticket: TicketRecord, event: TicketEventRecord
    ) -> tuple[TicketRecord, TicketEventRecord]:
        ticket_key = (ticket.tenant_id, ticket.ticket_id)
        event_key = (event.tenant_id, event.event_id)
        if ticket_key in self._tickets:
            raise ValueError("ticket already exists")
        if any(
            item.tenant_id == ticket.tenant_id and item.ticket_number == ticket.ticket_number
            for item in self._tickets.values()
        ):
            raise ValueError("ticket number already exists")
        if event_key in self._events:
            raise ValueError("ticket event already exists")
        self._tickets[ticket_key] = ticket
        self._events[event_key] = event
        return ticket, event

    def transition_ticket(
        self,
        *,
        ticket_id: str,
        expected_status: TicketStatus,
        updated: TicketRecord,
        event: TicketEventRecord,
    ) -> tuple[TicketRecord, TicketEventRecord]:
        key = (updated.tenant_id, ticket_id)
        current = self.get_ticket(tenant_id=updated.tenant_id, ticket_id=ticket_id)
        if current.ticket_status != expected_status:
            raise ValueError("ticket status changed concurrently")
        event_key = (event.tenant_id, event.event_id)
        if event_key in self._events:
            raise ValueError("ticket event already exists")
        self._tickets[key] = updated
        self._events[event_key] = event
        return updated, event


_TICKET_COLUMNS = (
    "tenant_id, object_id, object_type, owner_principal_id, created_by, created_at_utc, "
    "updated_at_utc, data_classification, retention_policy_id, legal_hold_state, lifecycle_state, "
    "kms_key_ref, audit_chain_ref, source_system, schema_version, ticket_id, ticket_number, "
    "ticket_status, priority, subject_redacted, sla_state"
)
_EVENT_COLUMNS = (
    "tenant_id, object_id, object_type, owner_principal_id, created_by, created_at_utc, "
    "updated_at_utc, data_classification, retention_policy_id, legal_hold_state, lifecycle_state, "
    "kms_key_ref, audit_chain_ref, source_system, schema_version, event_id, ticket_id, event_type, "
    "event_status, event_summary_redacted, occurred_at_utc"
)


class PgTicketRepository:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def list_tickets(self, *, tenant_id: str) -> Sequence[TicketRecord]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                f"SELECT {_TICKET_COLUMNS} FROM tickets.ticket_items "
                "WHERE tenant_id = %s ORDER BY updated_at_utc DESC, ticket_number",
                (tenant_id,),
            ).fetchall()
        return tuple(_ticket_from_row(row) for row in rows)

    def get_ticket(self, *, tenant_id: str, ticket_id: str) -> TicketRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"SELECT {_TICKET_COLUMNS} FROM tickets.ticket_items WHERE tenant_id = %s AND ticket_id = %s",
                (tenant_id, ticket_id),
            ).fetchone()
        if row is None:
            raise KeyError("ticket not found")
        return _ticket_from_row(row)

    def list_events(self, *, tenant_id: str, ticket_id: str) -> Sequence[TicketEventRecord]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM tickets.ticket_events "
                "WHERE tenant_id = %s AND ticket_id = %s ORDER BY occurred_at_utc, event_id",
                (tenant_id, ticket_id),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def create_ticket_with_event(
        self, *, ticket: TicketRecord, event: TicketEventRecord
    ) -> tuple[TicketRecord, TicketEventRecord]:
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, ticket.tenant_id)
                ticket_row = connection.execute(
                    f"INSERT INTO tickets.ticket_items ({_TICKET_COLUMNS}) "
                    f"VALUES ({_placeholders(21)}) RETURNING {_TICKET_COLUMNS}",
                    _ticket_values(ticket),
                ).fetchone()
                event_row = connection.execute(
                    f"INSERT INTO tickets.ticket_events ({_EVENT_COLUMNS}) "
                    f"VALUES ({_placeholders(21)}) RETURNING {_EVENT_COLUMNS}",
                    _event_values(event),
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("ticket or initial event already exists") from exc
        if ticket_row is None or event_row is None:
            raise RuntimeError("ticket create transaction returned no records")
        return _ticket_from_row(ticket_row), _event_from_row(event_row)

    def transition_ticket(
        self,
        *,
        ticket_id: str,
        expected_status: TicketStatus,
        updated: TicketRecord,
        event: TicketEventRecord,
    ) -> tuple[TicketRecord, TicketEventRecord]:
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, updated.tenant_id)
                ticket_row = connection.execute(
                    f"UPDATE tickets.ticket_items SET ticket_status = %s, lifecycle_state = %s, "
                    "sla_state = %s, audit_chain_ref = %s "
                    "WHERE tenant_id = %s AND ticket_id = %s AND ticket_status = %s "
                    f"RETURNING {_TICKET_COLUMNS}",
                    (
                        updated.ticket_status.value,
                        updated.lifecycle_state,
                        updated.sla_state.value,
                        updated.audit_chain_ref,
                        updated.tenant_id,
                        ticket_id,
                        expected_status.value,
                    ),
                ).fetchone()
                if ticket_row is None:
                    raise ValueError("ticket status changed concurrently or ticket was not found")
                event_row = connection.execute(
                    f"INSERT INTO tickets.ticket_events ({_EVENT_COLUMNS}) "
                    f"VALUES ({_placeholders(21)}) RETURNING {_EVENT_COLUMNS}",
                    _event_values(event),
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("ticket event already exists") from exc
        if event_row is None:
            raise RuntimeError("ticket transition transaction returned no event")
        return _ticket_from_row(ticket_row), _event_from_row(event_row)

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


class TicketService:
    def __init__(self, *, repository: TicketRepository, audit_logger: InMemoryAuditLogger) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def list_tickets(self, *, user_context: UserContext) -> TicketsResponse:
        records = self.repository.list_tickets(tenant_id=user_context.tenant_id)
        if user_context.role_ids.isdisjoint(OPERATOR_ROLES):
            records = tuple(item for item in records if item.owner_principal_id == user_context.user_id)
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="tickets.items.read",
            source_object_ids=[item.object_id for item in records],
            metadata={"result_count": len(records), "access_checked": True, "content_included": False},
        )
        return TicketsResponse(
            tenant_id=user_context.tenant_id,
            tickets=[ticket_view(item) for item in records],
            audit_event_id=event.event_id,
        )

    def get_ticket(self, *, user_context: UserContext, ticket_id: str) -> TicketResponse:
        record = self.repository.get_ticket(tenant_id=user_context.tenant_id, ticket_id=ticket_id)
        self._require_read_access(user_context=user_context, ticket=record)
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="tickets.item.read",
            source_object_ids=[record.object_id],
            metadata={"access_checked": True, "content_included": False},
        )
        return TicketResponse(
            tenant_id=user_context.tenant_id,
            ticket=ticket_view(record),
            audit_event_id=event.event_id,
        )

    def create_ticket(self, *, user_context: UserContext, command: CreateTicketCommand) -> TicketMutationResponse:
        self._require_operator(user_context)
        if (
            command.owner_principal_id is not None
            and command.owner_principal_id != user_context.user_id
            and user_context.role_ids.isdisjoint({"tenant-admin", "tenant_admin", "security-admin"})
        ):
            raise PermissionError("only tenant administrators may create tickets for another owner")
        owner = command.owner_principal_id or user_context.user_id
        ticket = TicketRecord(
            tenant_id=user_context.tenant_id,
            object_id=command.ticket_id,
            owner_principal_id=owner,
            created_by=user_context.user_id,
            created_at_utc=command.occurred_at_utc,
            updated_at_utc=command.occurred_at_utc,
            kms_key_ref=command.kms_key_ref,
            audit_chain_ref=command.audit_chain_ref,
            source_system=command.source_system,
            ticket_id=command.ticket_id,
            ticket_number=command.ticket_number,
            priority=command.priority,
            subject_redacted=command.subject_redacted,
        )
        initial_event = _build_event(
            ticket=ticket,
            event_id=command.created_event_id,
            event_type=TicketEventType.CREATED,
            summary=command.created_event_summary_redacted,
            actor=user_context.user_id,
            occurred_at=command.occurred_at_utc,
            audit_chain_ref=command.audit_chain_ref,
        )
        stored_ticket, stored_event = self.repository.create_ticket_with_event(ticket=ticket, event=initial_event)
        audit = self.audit_logger.record(
            user_context=user_context,
            event_type="tickets.item.created",
            source_object_ids=[stored_ticket.object_id, stored_event.object_id],
            metadata={
                "ticket_status": stored_ticket.ticket_status.value,
                "priority": stored_ticket.priority.value,
                "event_type": stored_event.event_type.value,
                "content_included": False,
            },
        )
        return TicketMutationResponse(
            tenant_id=user_context.tenant_id,
            ticket=ticket_view(stored_ticket),
            event=ticket_event_view(stored_event),
            audit_event_id=audit.event_id,
        )

    def transition_ticket(
        self, *, user_context: UserContext, ticket_id: str, command: TransitionTicketCommand
    ) -> TicketMutationResponse:
        self._require_operator(user_context)
        current = self.repository.get_ticket(tenant_id=user_context.tenant_id, ticket_id=ticket_id)
        if current.ticket_status != command.expected_status:
            raise ValueError("ticket status changed concurrently")
        self._require_transition(current.ticket_status, command.new_status)
        if current.legal_hold_state == "active" and command.new_status == TicketStatus.ARCHIVED:
            raise ValueError("tickets under Legal Hold must not be archived")
        updated = TicketRecord.model_validate(
            current.model_copy(
                update={
                    "ticket_status": command.new_status,
                    "lifecycle_state": command.new_status.value,
                    "updated_at_utc": command.occurred_at_utc,
                    "audit_chain_ref": command.audit_chain_ref,
                    "sla_state": (
                        TicketSlaState.COMPLETED
                        if command.new_status in {TicketStatus.RESOLVED, TicketStatus.CANCELLED, TicketStatus.ARCHIVED}
                        else current.sla_state
                    ),
                }
            ).model_dump()
        )
        transition_event = _build_event(
            ticket=updated,
            event_id=command.event_id,
            event_type=TicketEventType.STATUS_CHANGED,
            summary=command.event_summary_redacted,
            actor=user_context.user_id,
            occurred_at=command.occurred_at_utc,
            audit_chain_ref=command.audit_chain_ref,
        )
        stored_ticket, stored_event = self.repository.transition_ticket(
            ticket_id=ticket_id,
            expected_status=command.expected_status,
            updated=updated,
            event=transition_event,
        )
        audit = self.audit_logger.record(
            user_context=user_context,
            event_type="tickets.item.status_changed",
            source_object_ids=[stored_ticket.object_id, stored_event.object_id],
            metadata={
                "previous_status": command.expected_status.value,
                "new_status": stored_ticket.ticket_status.value,
                "event_type": stored_event.event_type.value,
                "content_included": False,
            },
        )
        return TicketMutationResponse(
            tenant_id=user_context.tenant_id,
            ticket=ticket_view(stored_ticket),
            event=ticket_event_view(stored_event),
            audit_event_id=audit.event_id,
        )

    def list_events(self, *, user_context: UserContext, ticket_id: str) -> TicketEventsResponse:
        ticket = self.repository.get_ticket(tenant_id=user_context.tenant_id, ticket_id=ticket_id)
        self._require_read_access(user_context=user_context, ticket=ticket)
        records = self.repository.list_events(tenant_id=user_context.tenant_id, ticket_id=ticket_id)
        audit = self.audit_logger.record(
            user_context=user_context,
            event_type="tickets.events.read",
            source_object_ids=[ticket.object_id, *(item.object_id for item in records)],
            metadata={"result_count": len(records), "access_checked": True, "content_included": False},
        )
        return TicketEventsResponse(
            tenant_id=user_context.tenant_id,
            ticket_id=ticket_id,
            events=[ticket_event_view(item) for item in records],
            audit_event_id=audit.event_id,
        )

    @staticmethod
    def _require_operator(user_context: UserContext) -> None:
        if user_context.role_ids.isdisjoint(OPERATOR_ROLES):
            raise PermissionError("Tickets operator role required")

    @staticmethod
    def _require_read_access(*, user_context: UserContext, ticket: TicketRecord) -> None:
        if user_context.role_ids.isdisjoint(OPERATOR_ROLES) and ticket.owner_principal_id != user_context.user_id:
            raise PermissionError("ticket is not authorized for this principal")

    @staticmethod
    def _require_transition(current: TicketStatus, target: TicketStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise ValueError(f"ticket transition is not allowed: {current.value} -> {target.value}")


def ticket_view(record: TicketRecord) -> TicketView:
    return TicketView(
        ticket_id=record.ticket_id,
        object_id=record.object_id,
        object_type=record.object_type,
        ticket_number=record.ticket_number,
        subject_redacted=record.subject_redacted,
        ticket_status=record.ticket_status,
        priority=record.priority,
        sla_state=record.sla_state,
        owner_principal_id=record.owner_principal_id,
        created_at_utc=record.created_at_utc,
        updated_at_utc=record.updated_at_utc,
        data_classification=record.data_classification,
        retention_policy_id=record.retention_policy_id,
        legal_hold_state=record.legal_hold_state,
        lifecycle_state=record.lifecycle_state,
        source_system=record.source_system,
        schema_version=record.schema_version,
        audit_chain_ref=record.audit_chain_ref,
    )


def ticket_event_view(record: TicketEventRecord) -> TicketEventView:
    return TicketEventView(
        event_id=record.event_id,
        object_id=record.object_id,
        object_type=record.object_type,
        ticket_id=record.ticket_id,
        event_type=record.event_type,
        event_status=record.event_status,
        event_summary_redacted=record.event_summary_redacted,
        occurred_at_utc=record.occurred_at_utc,
        created_by=record.created_by,
        data_classification=record.data_classification,
        retention_policy_id=record.retention_policy_id,
        legal_hold_state=record.legal_hold_state,
        schema_version=record.schema_version,
        audit_chain_ref=record.audit_chain_ref,
    )


def build_default_ticket_repository(
    environ: Mapping[str, str] | None = None,
) -> TicketRepository:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TICKETS_REPOSITORY_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTicketRepository()
    if backend in {"postgres", "postgresql", "pg"}:
        dsn = env.get("SUITE_TICKETS_REPOSITORY_DSN") or env.get("SUITE_DATABASE_DSN")
        if not dsn:
            raise ValueError(
                "PostgreSQL Tickets repository requires SUITE_TICKETS_REPOSITORY_DSN or SUITE_DATABASE_DSN"
            )
        return PgTicketRepository(database_dsn=dsn)
    raise ValueError(f"Unsupported SUITE_TICKETS_REPOSITORY_BACKEND: {backend}")


def _build_event(
    *,
    ticket: TicketRecord,
    event_id: str,
    event_type: TicketEventType,
    summary: str,
    actor: str,
    occurred_at: datetime,
    audit_chain_ref: str,
) -> TicketEventRecord:
    event_status, lifecycle = _event_state(ticket.ticket_status)
    return TicketEventRecord(
        tenant_id=ticket.tenant_id,
        object_id=event_id,
        owner_principal_id=ticket.owner_principal_id,
        created_by=actor,
        created_at_utc=occurred_at,
        updated_at_utc=occurred_at,
        data_classification=ticket.data_classification,
        retention_policy_id=ticket.retention_policy_id,
        legal_hold_state=ticket.legal_hold_state,
        lifecycle_state=lifecycle,
        kms_key_ref=ticket.kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=ticket.source_system,
        event_id=event_id,
        ticket_id=ticket.ticket_id,
        event_type=event_type,
        event_status=event_status,
        event_summary_redacted=summary,
        occurred_at_utc=occurred_at,
    )


def _event_state(status: TicketStatus) -> tuple[str, str]:
    if status in {TicketStatus.NEW, TicketStatus.OPEN, TicketStatus.TRIAGED}:
        return "open", "open"
    if status == TicketStatus.IN_PROGRESS:
        return "in_progress", "in_progress"
    if status == TicketStatus.WAITING:
        return "waiting", "waiting"
    if status in {TicketStatus.RESOLVED, TicketStatus.ARCHIVED}:
        return "resolved", "resolved"
    return "cancelled", "cancelled"


_ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.NEW: frozenset({TicketStatus.OPEN, TicketStatus.TRIAGED, TicketStatus.CANCELLED}),
    TicketStatus.OPEN: frozenset(
        {
            TicketStatus.TRIAGED,
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING,
            TicketStatus.RESOLVED,
            TicketStatus.CANCELLED,
        }
    ),
    TicketStatus.TRIAGED: frozenset(
        {
            TicketStatus.IN_PROGRESS,
            TicketStatus.WAITING,
            TicketStatus.RESOLVED,
            TicketStatus.CANCELLED,
        }
    ),
    TicketStatus.IN_PROGRESS: frozenset({TicketStatus.WAITING, TicketStatus.RESOLVED, TicketStatus.CANCELLED}),
    TicketStatus.WAITING: frozenset({TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CANCELLED}),
    TicketStatus.RESOLVED: frozenset({TicketStatus.OPEN, TicketStatus.ARCHIVED}),
    TicketStatus.CANCELLED: frozenset({TicketStatus.OPEN, TicketStatus.ARCHIVED}),
    TicketStatus.ARCHIVED: frozenset(),
}


def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def _ticket_values(item: TicketRecord) -> tuple[object, ...]:
    return tuple(item.model_dump(mode="python")[field] for field in _TICKET_COLUMNS.split(", "))


def _event_values(item: TicketEventRecord) -> tuple[object, ...]:
    return tuple(item.model_dump(mode="python")[field] for field in _EVENT_COLUMNS.split(", "))


def _ticket_from_row(row: Sequence[Any]) -> TicketRecord:
    return TicketRecord.model_validate(dict(zip(_TICKET_COLUMNS.split(", "), row, strict=True)))


def _event_from_row(row: Sequence[Any]) -> TicketEventRecord:
    return TicketEventRecord.model_validate(dict(zip(_EVENT_COLUMNS.split(", "), row, strict=True)))
