from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from suite.storage.source_objects import SourceObjectType


class SourceObjectPreviewSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    surface: str
    label: str
    render_contract: str = "metadata_only_no_source_content"
    content_included: bool = False
    requires_acl_checked_detail: bool = True
    allowed_actions: tuple[str, ...] = ("open_metadata_detail",)
    blocking_reason: str = "content_preview_requires_future_policy_gate"


def build_source_object_preview_slots(source_object_type: SourceObjectType) -> tuple[SourceObjectPreviewSlot, ...]:
    if source_object_type == SourceObjectType.MAIL:
        return (
            SourceObjectPreviewSlot(
                slot_id="mail.message.preview.metadata",
                surface="mail.message.preview",
                label="Mail Preview",
            ),
        )
    if source_object_type == SourceObjectType.WIKI:
        return (
            SourceObjectPreviewSlot(
                slot_id="knowledge_base.article.preview.metadata",
                surface="knowledge_base.article.preview",
                label="Knowledge Base Preview",
            ),
        )
    return (
        SourceObjectPreviewSlot(
            slot_id="office.document.preview.metadata",
            surface="office.document.preview",
            label="Document Preview",
        ),
    )
