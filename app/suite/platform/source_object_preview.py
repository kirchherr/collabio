from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from suite.storage.source_objects import SourceObjectType


class SourceObjectPreviewGateStatus(StrEnum):
    METADATA_READY_CONTENT_BLOCKED = "metadata_ready_content_blocked"


COMMON_METADATA_FIELDS = (
    "tenant_id",
    "source_object_id",
    "source_version_id",
    "source_object_type",
    "title",
    "source_system",
    "data_classification",
    "retention_policy_id",
    "legal_hold_state",
    "lifecycle_state",
    "manifest_hash",
    "content_hash",
    "acl_version",
    "mime_type",
    "content_byte_length",
)
CONTENT_RELEASE_REQUIRED_EVIDENCE = (
    "tenant_preview_policy_enabled",
    "source_object_acl_checked",
    "source_detail_audit_event",
    "parser_sanitizer_evidence",
    "human_content_release_confirmation",
)
ISOLATED_PARSER_BOUNDARIES = (
    "network_access_allowed=false",
    "external_processes_allowed=false",
    "read_only_filesystem=true",
    "no_direct_storage_mutation=true",
    "no_direct_vector_writes=true",
)
SANITIZER_BOUNDARIES = (
    "strip_active_content=true",
    "external_resource_loading=false",
    "html_rendering_blocked_until_policy_gate=true",
)


class SourceObjectPreviewGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    policy_id: str
    status: SourceObjectPreviewGateStatus = SourceObjectPreviewGateStatus.METADATA_READY_CONTENT_BLOCKED
    metadata_first: bool = True
    raw_content_included: bool = False
    content_release_allowed: bool = False
    parser_profile_id: str
    sanitizer_profile_id: str
    parser_boundaries: tuple[str, ...]
    sanitizer_boundaries: tuple[str, ...]
    allowed_metadata_fields: tuple[str, ...] = COMMON_METADATA_FIELDS
    mail_header_metadata_fields: tuple[str, ...] = ()
    attachment_metadata_fields: tuple[str, ...] = ()
    required_content_release_evidence: tuple[str, ...] = CONTENT_RELEASE_REQUIRED_EVIDENCE
    blocking_reasons: tuple[str, ...] = ("content_release_requires_policy_acl_audit_and_sanitizer_evidence",)
    schema_version: str = "source_object_preview_gate.v1"


class SourceObjectPreviewSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    surface: str
    label: str
    gate: SourceObjectPreviewGate
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
                gate=_mail_preview_gate(),
            ),
        )
    if source_object_type == SourceObjectType.WIKI:
        return (
            SourceObjectPreviewSlot(
                slot_id="knowledge_base.article.preview.metadata",
                surface="knowledge_base.article.preview",
                label="Knowledge Base Preview",
                gate=_knowledge_base_preview_gate(),
            ),
        )
    return (
        SourceObjectPreviewSlot(
            slot_id="office.document.preview.metadata",
            surface="office.document.preview",
            label="Document Preview",
            gate=_document_preview_gate(),
        ),
    )


def _document_preview_gate() -> SourceObjectPreviewGate:
    return SourceObjectPreviewGate(
        gate_id="office.document.preview.gate.v1",
        policy_id="preview-policy.document.metadata-first.v1",
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        parser_boundaries=ISOLATED_PARSER_BOUNDARIES,
        sanitizer_boundaries=SANITIZER_BOUNDARIES,
    )


def _mail_preview_gate() -> SourceObjectPreviewGate:
    return SourceObjectPreviewGate(
        gate_id="mail.message.preview.gate.v1",
        policy_id="preview-policy.mail.metadata-first.v1",
        parser_profile_id="policy-enforced-parser-worker:1",
        sanitizer_profile_id="mail-preview-sanitizer:headers-and-attachment-metadata.v1",
        parser_boundaries=ISOLATED_PARSER_BOUNDARIES,
        sanitizer_boundaries=SANITIZER_BOUNDARIES,
        mail_header_metadata_fields=("from", "to", "cc", "date", "subject", "message_id", "thread_id"),
        attachment_metadata_fields=(
            "filename",
            "mime_type",
            "content_byte_length",
            "content_hash",
            "retention_policy_id",
            "legal_hold_state",
            "scan_state",
        ),
        blocking_reasons=(
            "mail_body_release_requires_policy_acl_audit_and_sanitizer_evidence",
            "attachment_opening_requires_scan_and_explicit_confirmation",
        ),
    )


def _knowledge_base_preview_gate() -> SourceObjectPreviewGate:
    return SourceObjectPreviewGate(
        gate_id="knowledge_base.article.preview.gate.v1",
        policy_id="preview-policy.knowledge-base.metadata-first.v1",
        parser_profile_id="policy-enforced-parser-worker:1",
        sanitizer_profile_id="knowledge-base-preview-sanitizer:metadata-first.v1",
        parser_boundaries=ISOLATED_PARSER_BOUNDARIES,
        sanitizer_boundaries=SANITIZER_BOUNDARIES,
    )
