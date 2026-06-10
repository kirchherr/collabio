import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from suite.ai_control_plane.models import AuditEvent, UserContext

GENESIS_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def stable_hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def audit_event_hash(event: AuditEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"event_hash"})
    return stable_hash(canonical_json(payload))


@dataclass(frozen=True)
class AuditChainVerificationResult:
    ok: bool
    verified_events: int
    failure: str | None = None


def verify_audit_chain(events: Sequence[AuditEvent]) -> AuditChainVerificationResult:
    previous_hash = GENESIS_HASH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence_number != expected_sequence:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Expected sequence {expected_sequence}, found {event.sequence_number}",
            )
        if event.previous_event_hash != previous_hash:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Event {event.event_id} has invalid previous hash",
            )
        expected_hash = audit_event_hash(event)
        if event.event_hash != expected_hash:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Event {event.event_id} has invalid event hash",
            )
        previous_hash = event.event_hash
    return AuditChainVerificationResult(ok=True, verified_events=len(events))


class InMemoryAuditLogger:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_id: str | None = None,
        prompt_template_id: str | None = None,
        source_object_ids: list[str] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        event = AuditEvent(
            sequence_number=len(self._events) + 1,
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            event_type=event_type,
            model_id=model_id,
            prompt_template_id=prompt_template_id,
            source_object_ids=source_object_ids or [],
            input_hash=stable_hash(input_text) if input_text is not None else None,
            output_hash=stable_hash(output_text) if output_text is not None else None,
            metadata=metadata or {},
            previous_event_hash=previous_hash,
            event_hash="",
        )
        event.event_hash = audit_event_hash(event)
        self._events.append(event)
        return event

    def verify(self) -> AuditChainVerificationResult:
        return verify_audit_chain(self.events)
