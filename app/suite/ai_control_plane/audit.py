from hashlib import sha256

from suite.ai_control_plane.models import AuditEvent, UserContext


def stable_hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


class InMemoryAuditLogger:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

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
        metadata: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            event_type=event_type,
            model_id=model_id,
            prompt_template_id=prompt_template_id,
            source_object_ids=source_object_ids or [],
            input_hash=stable_hash(input_text) if input_text is not None else None,
            output_hash=stable_hash(output_text) if output_text is not None else None,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event

