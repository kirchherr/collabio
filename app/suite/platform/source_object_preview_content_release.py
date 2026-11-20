from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.knowledge_base import KnowledgeBaseArticleService
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.source_object_details import (
    SourceObjectDetailOrigin,
    build_source_object_metadata_detail_response,
)
from suite.platform.source_object_preview_decisions import (
    SourceObjectPreviewDecisionEvidence,
    SourceObjectPreviewDecisionLedger,
    build_source_object_preview_decision_evidence_hash,
)
from suite.platform.source_object_preview_renderer import (
    SourceObjectPreviewRendererEvidenceStore,
    build_source_object_preview_renderer_evidence_hash,
    source_object_preview_renderer_evidence_hash_from_ref,
)
from suite.platform.source_object_preview_renderer_release_gate import (
    SourceObjectPreviewRendererReleaseGateEvidence,
    SourceObjectPreviewRendererReleaseGateEvidenceStore,
    require_source_object_preview_renderer_release_gate_for_wiring,
)
from suite.storage.content_hash import ContentHashVerificationError, verify_content_hash
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    source_object_content_bytes,
)

CONTENT_RELEASE_CONFIRMATION_STATEMENT = (
    "I explicitly authorize this one-time ACL-checked, sanitized plain-text source preview release. "
    "No persistent preview output, external fetch, active content, attachment, mail body, "
    "or destructive action is authorized."
)
CONTENT_RELEASE_SCHEMA_VERSION = "source_object_preview_content_release_receipt.v1"
CONTENT_RELEASE_RESULT_CONTRACT = "acl_checked_sanitized_plain_text_preview.v1"
CONTENT_RELEASE_CONTINUITY_DOMAIN = "source_object_preview_content_release_evidence"
CONTENT_RELEASE_MAX_SOURCE_BYTES = 262_144
CONTENT_RELEASE_ALLOWED_MIME_TYPES = frozenset({"text/plain", "text/markdown"})
CONTENT_RELEASE_ALLOWED_OBJECT_TYPES = frozenset(
    {SourceObjectType.DOCUMENT, SourceObjectType.WIKI, SourceObjectType.PROCEDURE_DOC}
)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ZERO_HASH = "sha256:" + ("0" * 64)
_CLOCK_SKEW = timedelta(minutes=5)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry


class SourceObjectPreviewContentReleaseAccessDenied(PermissionError):
    pass


class SourceObjectPreviewContentReleaseInvalidRequest(ValueError):
    pass


class SourceObjectPreviewContentReleaseUnsupportedMediaType(ValueError):
    pass


class SourceObjectPreviewContentReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_statement: ClassVar[str] = CONTENT_RELEASE_CONFIRMATION_STATEMENT

    preview_decision_evidence_hash: str
    renderer_release_gate_evidence_hash: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    release_request_reference: str
    reason: str = Field(min_length=1, max_length=2_000)
    release_requested: bool = True
    persistent_output_requested: bool = False
    external_fetch_requested: bool = False
    active_content_requested: bool = False
    attachment_open_requested: bool = False
    mail_body_release_requested: bool = False
    destructive_action_requested: bool = False

    @field_validator("preview_decision_evidence_hash", "renderer_release_gate_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("content release evidence hashes must be sha256 references")
        return value

    @field_validator("human_confirmation_reference", "release_request_reference")
    @classmethod
    def require_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("content release references must use typed prefixes")
        return normalized

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value.strip() != cls.confirmation_statement:
            raise ValueError("exact source preview content release confirmation statement required")
        return value.strip()

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content release reason must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_closed_release_scope(self) -> Self:
        if not self.release_requested:
            raise ValueError("content release must be explicitly requested")
        if (
            self.persistent_output_requested
            or self.external_fetch_requested
            or self.active_content_requested
            or self.attachment_open_requested
            or self.mail_body_release_requested
            or self.destructive_action_requested
        ):
            raise ValueError("content release request opens a forbidden surface")
        return self


class SourceObjectPreviewContentReleaseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTENT_RELEASE_SCHEMA_VERSION
    continuity_domain: str = CONTENT_RELEASE_CONTINUITY_DOMAIN
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    source_mime_type: str
    preview_slot_id: str
    preview_policy_id: str
    parser_profile_id: str
    sanitizer_profile_id: str
    preview_decision_evidence_hash: str
    renderer_sandbox_evidence_hash: str
    renderer_release_gate_evidence_hash: str
    human_confirmation_reference: str
    confirmation_statement_hash: str
    release_request_reference: str
    command_hash: str
    reason_hash: str
    sanitized_content_hash: str
    sanitized_content_byte_length: int = Field(gt=0, le=CONTENT_RELEASE_MAX_SOURCE_BYTES)
    requested_by: str
    released_at_utc: datetime
    audit_event_id: str
    access_checked: bool = True
    tenant_policy_checked: bool = True
    renderer_evidence_checked: bool = True
    renderer_release_gate_checked: bool = True
    source_integrity_checked: bool = True
    content_included_in_receipt: bool = False
    content_persisted: bool = False
    external_fetch_allowed: bool = False
    active_content_allowed: bool = False
    attachment_open_allowed: bool = False
    mail_body_release_allowed: bool = False
    destructive_action_allowed: bool = False
    evidence_hash: str

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "preview_decision_evidence_hash",
        "renderer_sandbox_evidence_hash",
        "renderer_release_gate_evidence_hash",
        "confirmation_statement_hash",
        "command_hash",
        "reason_hash",
        "sanitized_content_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("content release receipt hashes must be sha256 references")
        return value

    @field_validator("human_confirmation_reference", "release_request_reference")
    @classmethod
    def require_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("content release receipt references must use typed prefixes")
        return value

    @field_validator("released_at_utc")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("content release timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def require_fail_closed_receipt(self) -> Self:
        if self.continuity_domain != CONTENT_RELEASE_CONTINUITY_DOMAIN:
            raise ValueError("content release receipt continuity domain mismatch")
        if self.source_object_type not in CONTENT_RELEASE_ALLOWED_OBJECT_TYPES:
            raise ValueError("content release receipt source object type is not allowlisted")
        if self.source_mime_type.lower() not in CONTENT_RELEASE_ALLOWED_MIME_TYPES:
            raise ValueError("content release receipt MIME type is not allowlisted")
        if not (
            self.access_checked
            and self.tenant_policy_checked
            and self.renderer_evidence_checked
            and self.renderer_release_gate_checked
            and self.source_integrity_checked
        ):
            raise ValueError("content release receipt requires all release checks")
        if (
            self.content_included_in_receipt
            or self.content_persisted
            or self.external_fetch_allowed
            or self.active_content_allowed
            or self.attachment_open_allowed
            or self.mail_body_release_allowed
            or self.destructive_action_allowed
        ):
            raise ValueError("content release receipt violates the closed-surface contract")
        return self


class SourceObjectPreviewContentReleaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "source_object_preview_content_release.v1"
    result_contract: str = CONTENT_RELEASE_RESULT_CONTRACT
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    response_media_type: str = "text/plain; charset=utf-8"
    render_contract: str = "plain_text_json_field_no_html_interpretation"
    content: str
    content_included: bool = True
    content_persisted: bool = False
    sanitized: bool = True
    external_fetch_allowed: bool = False
    active_content_allowed: bool = False
    attachment_open_allowed: bool = False
    mail_body_release_allowed: bool = False
    destructive_action_allowed: bool = False
    sanitized_content_hash: str
    sanitized_content_byte_length: int
    preview_decision_evidence_hash: str
    renderer_sandbox_evidence_hash: str
    renderer_release_gate_evidence_hash: str
    audit_event_id: str
    content_release_receipt_evidence_hash: str
    content_release_receipt_ref: str
    receipt_persisted: bool = True


class SourceObjectPreviewContentReleaseReceiptStore(Protocol):
    def append(self, receipt: SourceObjectPreviewContentReleaseReceipt) -> SourceObjectPreviewContentReleaseReceipt: ...

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewContentReleaseReceipt: ...

    def list_receipts(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewContentReleaseReceipt]: ...


class InMemorySourceObjectPreviewContentReleaseReceiptStore:
    def __init__(self, receipts: Sequence[SourceObjectPreviewContentReleaseReceipt] = ()) -> None:
        self._receipts: dict[tuple[str, str], SourceObjectPreviewContentReleaseReceipt] = {}
        for receipt in receipts:
            self.append(receipt)

    def append(self, receipt: SourceObjectPreviewContentReleaseReceipt) -> SourceObjectPreviewContentReleaseReceipt:
        _require_valid_receipt_hash(receipt)
        key = (receipt.tenant_id, receipt.evidence_hash)
        if key in self._receipts:
            raise ValueError("source preview content release receipt already exists")
        self._receipts[key] = receipt
        return receipt

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewContentReleaseReceipt:
        try:
            return self._receipts[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("source preview content release receipt not found") from exc

    def list_receipts(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewContentReleaseReceipt]:
        return tuple(
            receipt for (stored_tenant_id, _), receipt in self._receipts.items() if stored_tenant_id == tenant_id
        )


class PgSourceObjectPreviewContentReleaseReceiptStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, receipt: SourceObjectPreviewContentReleaseReceipt) -> SourceObjectPreviewContentReleaseReceipt:
        _require_valid_receipt_hash(receipt)
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, receipt.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.source_object_preview_content_release_receipts (
                        tenant_id, source_object_id, source_version_id, source_object_type,
                        source_manifest_hash, source_content_hash, source_acl_version,
                        source_mime_type, preview_decision_evidence_hash,
                        renderer_sandbox_evidence_hash, renderer_release_gate_evidence_hash,
                        command_hash, sanitized_content_hash, sanitized_content_byte_length,
                        released_at_utc, audit_event_id, receipt, evidence_hash, schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        receipt.tenant_id,
                        receipt.source_object_id,
                        receipt.source_version_id,
                        receipt.source_object_type.value,
                        receipt.source_manifest_hash,
                        receipt.source_content_hash,
                        receipt.source_acl_version,
                        receipt.source_mime_type,
                        receipt.preview_decision_evidence_hash,
                        receipt.renderer_sandbox_evidence_hash,
                        receipt.renderer_release_gate_evidence_hash,
                        receipt.command_hash,
                        receipt.sanitized_content_hash,
                        receipt.sanitized_content_byte_length,
                        receipt.released_at_utc,
                        receipt.audit_event_id,
                        Jsonb(receipt.model_dump(mode="json")),
                        receipt.evidence_hash,
                        receipt.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source preview content release receipt already exists") from exc
        return receipt

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewContentReleaseReceipt:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT receipt
                FROM collabio.source_object_preview_content_release_receipts
                WHERE tenant_id = %s AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("source preview content release receipt not found")
        return _receipt_from_row(row)

    def list_receipts(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewContentReleaseReceipt]:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT receipt
                FROM collabio.source_object_preview_content_release_receipts
                WHERE tenant_id = %s
                ORDER BY released_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(_receipt_from_row(row) for row in rows)

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))


def build_default_source_object_preview_content_release_receipt_store(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewContentReleaseReceiptStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_SOURCE_PREVIEW_CONTENT_RELEASE_RECEIPT_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemorySourceObjectPreviewContentReleaseReceiptStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_SOURCE_PREVIEW_CONTENT_RELEASE_RECEIPT_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError("PostgreSQL source preview content release receipt store requires a database DSN")
        return PgSourceObjectPreviewContentReleaseReceiptStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported source preview content release receipt backend: {backend}")


def build_source_object_preview_content_release(
    *,
    user_context: UserContext,
    tenant_policy: TenantPolicy,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
    renderer_release_gate_store: SourceObjectPreviewRendererReleaseGateEvidenceStore,
    content_release_receipt_store: SourceObjectPreviewContentReleaseReceiptStore,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewContentReleaseRequest,
    released_at_utc: datetime | None = None,
) -> SourceObjectPreviewContentReleaseResponse:
    if source_object_id not in user_context.readable_object_ids:
        _audit_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
            rejection_reason="acl_object_not_readable",
        )
        raise SourceObjectPreviewContentReleaseAccessDenied("User cannot release requested source object content")
    if tenant_policy.tenant_id != user_context.tenant_id or not tenant_policy.content_preview_enabled:
        _audit_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
            rejection_reason="tenant_content_preview_policy_disabled",
        )
        raise SourceObjectPreviewContentReleaseAccessDenied("Tenant content preview policy is disabled")

    decision = _load_decision(
        ledger=preview_decision_ledger,
        tenant_id=user_context.tenant_id,
        evidence_hash=request.preview_decision_evidence_hash,
    )
    if (
        decision.source_object_id != source_object_id
        or decision.source_version_id != source_version_id
        or not decision.tenant_preview_policy_enabled
        or not decision.content_release_evidence_complete
        or decision.missing_evidence
        or not decision.renderer_sandbox_evidence_verified
        or not decision.backup_coverage_evidence_verified
        or not decision.restore_evidence_verified
        or not decision.human_confirmation_verified
        or decision.human_confirmation_reference != request.human_confirmation_reference
    ):
        raise SourceObjectPreviewContentReleaseInvalidRequest(
            "preview decision evidence is incomplete or does not match the release request"
        )

    renderer_evidence_hash = source_object_preview_renderer_evidence_hash_from_ref(
        decision.renderer_sandbox_evidence_ref or ""
    )
    if renderer_evidence_hash is None:
        raise SourceObjectPreviewContentReleaseInvalidRequest("preview decision has no valid renderer evidence")
    try:
        renderer_evidence = preview_renderer_evidence_store.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=renderer_evidence_hash,
        )
    except KeyError as exc:
        raise SourceObjectPreviewContentReleaseInvalidRequest("renderer evidence was not found") from exc
    if (
        renderer_evidence.renderer_sandbox_evidence_hash
        != build_source_object_preview_renderer_evidence_hash(renderer_evidence)
        or renderer_evidence.source_object_id != source_object_id
        or renderer_evidence.source_version_id != source_version_id
        or renderer_evidence.source_object_type != decision.source_object_type
        or renderer_evidence.preview_slot_id != decision.preview_slot_id
        or renderer_evidence.preview_policy_id != decision.preview_policy_id
        or renderer_evidence.renderer_sandbox_evidence_ref != decision.renderer_sandbox_evidence_ref
        or renderer_evidence.rendering_allowed
        or renderer_evidence.content_rendered
        or renderer_evidence.content_included
        or renderer_evidence.output_persisted
        or renderer_evidence.external_fetch_allowed
        or not renderer_evidence.temporary_workspace_destroyed
    ):
        raise SourceObjectPreviewContentReleaseInvalidRequest("renderer evidence integrity or boundary mismatch")

    try:
        release_gate = renderer_release_gate_store.get(
            tenant_id=user_context.tenant_id,
            evidence_hash=request.renderer_release_gate_evidence_hash,
        )
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=release_gate,
            tenant_id=user_context.tenant_id,
            evidence_hash=request.renderer_release_gate_evidence_hash,
        )
    except (KeyError, ValueError) as exc:
        raise SourceObjectPreviewContentReleaseInvalidRequest("renderer content release gate is not ready") from exc

    release_time = _aware(released_at_utc or datetime.now(UTC))
    if not _release_gate_is_current(release_gate=release_gate, released_at_utc=release_time):
        raise SourceObjectPreviewContentReleaseInvalidRequest("renderer content release gate evidence is stale")

    detail = build_source_object_metadata_detail_response(
        user_context=user_context,
        workspace_source_repository=workspace_source_repository,
        module_registry=module_registry,
        knowledge_base_article_service=knowledge_base_article_service,
        audit_logger=audit_logger,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
    )
    record = _authoritative_record(
        detail_origin=detail.origin,
        tenant_id=user_context.tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        workspace_source_repository=workspace_source_repository,
        knowledge_base_article_service=knowledge_base_article_service,
    )
    metadata = record.metadata
    if (
        metadata.manifest_hash != detail.manifest_hash
        or metadata.content_hash != detail.content_hash
        or metadata.acl_version != detail.acl_version
        or metadata.manifest_hash != renderer_evidence.source_manifest_hash
        or metadata.content_hash != renderer_evidence.source_content_hash
        or metadata.acl_version != renderer_evidence.source_acl_version
    ):
        raise SourceObjectPreviewContentReleaseInvalidRequest("source object changed after renderer evidence capture")
    if metadata.lifecycle_state in {
        SourceLifecycleState.RESTRICTED,
        SourceLifecycleState.DELETED,
        SourceLifecycleState.CRYPTOSHREDDED,
    }:
        raise SourceObjectPreviewContentReleaseAccessDenied("source lifecycle state blocks content release")
    if metadata.object_type not in CONTENT_RELEASE_ALLOWED_OBJECT_TYPES:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType(
            "source object type is not enabled for safe plain-text preview release"
        )
    if metadata.mime_type.lower() not in CONTENT_RELEASE_ALLOWED_MIME_TYPES:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType(
            "source MIME type is not enabled for safe plain-text preview release"
        )

    source_bytes = source_object_content_bytes(record)
    if len(source_bytes) > CONTENT_RELEASE_MAX_SOURCE_BYTES:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType("source exceeds safe preview byte limit")
    try:
        verify_content_hash(
            content=source_bytes,
            expected_hash=metadata.content_hash,
            verification_context="source_object_preview_content_release",
        )
    except ContentHashVerificationError as exc:
        raise SourceObjectPreviewContentReleaseInvalidRequest("authoritative source content hash mismatch") from exc
    sanitized_content = sanitize_source_object_preview_text(source_bytes)
    if not sanitized_content:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType(
            "safe plain-text preview rejects empty sanitized output"
        )
    sanitized_bytes = sanitized_content.encode("utf-8")
    sanitized_content_hash = stable_hash(sanitized_content)
    command_hash = _command_hash(request)
    reason_hash = stable_hash(request.reason)

    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_content.released",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "source_object_type": metadata.object_type.value,
            "source_mime_type": metadata.mime_type,
            "result_contract": CONTENT_RELEASE_RESULT_CONTRACT,
            "preview_decision_evidence_hash": decision.evidence_hash,
            "renderer_sandbox_evidence_hash": renderer_evidence.renderer_sandbox_evidence_hash,
            "renderer_release_gate_evidence_hash": release_gate.evidence_hash,
            "source_manifest_hash": metadata.manifest_hash,
            "source_content_hash": metadata.content_hash,
            "source_acl_version": metadata.acl_version,
            "sanitized_content_hash": sanitized_content_hash,
            "sanitized_content_byte_length": len(sanitized_bytes),
            "command_hash": command_hash,
            "reason_hash": reason_hash,
            "confirmation_statement_hash": stable_hash(request.human_confirmation_statement),
            "access_checked": True,
            "tenant_policy_checked": True,
            "source_integrity_checked": True,
            "content_included_in_response": True,
            "content_included_in_audit": False,
            "content_persisted": False,
            "external_fetch_allowed": False,
            "active_content_allowed": False,
            "attachment_open_allowed": False,
            "mail_body_release_allowed": False,
            "destructive_action_allowed": False,
        },
    )
    receipt = _build_receipt(
        user_context=user_context,
        request=request,
        record=record,
        decision=decision,
        renderer_evidence_hash=renderer_evidence.renderer_sandbox_evidence_hash,
        release_gate_evidence_hash=release_gate.evidence_hash,
        command_hash=command_hash,
        reason_hash=reason_hash,
        sanitized_content_hash=sanitized_content_hash,
        sanitized_content_byte_length=len(sanitized_bytes),
        released_at_utc=release_time,
        audit_event_id=event.event_id,
    )
    persisted = content_release_receipt_store.append(receipt)
    return SourceObjectPreviewContentReleaseResponse(
        tenant_id=user_context.tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        source_object_type=metadata.object_type,
        source_mime_type=metadata.mime_type,
        content=sanitized_content,
        sanitized_content_hash=sanitized_content_hash,
        sanitized_content_byte_length=len(sanitized_bytes),
        preview_decision_evidence_hash=decision.evidence_hash,
        renderer_sandbox_evidence_hash=renderer_evidence.renderer_sandbox_evidence_hash,
        renderer_release_gate_evidence_hash=release_gate.evidence_hash,
        audit_event_id=event.event_id,
        content_release_receipt_evidence_hash=persisted.evidence_hash,
        content_release_receipt_ref=f"source-preview-content-release:{persisted.evidence_hash}",
    )


def sanitize_source_object_preview_text(source_bytes: bytes) -> str:
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType(
            "safe plain-text preview requires valid UTF-8"
        ) from exc
    if "\x00" in text:
        raise SourceObjectPreviewContentReleaseUnsupportedMediaType("safe plain-text preview rejects NUL bytes")
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "".join(
        character
        for character in normalized
        if character in {"\n", "\t"} or unicodedata.category(character) not in {"Cc", "Cf"}
    )


def build_source_object_preview_content_release_receipt_hash(
    receipt: SourceObjectPreviewContentReleaseReceipt,
) -> str:
    return stable_hash(canonical_json(receipt.model_dump(mode="json", exclude={"evidence_hash"})))


def _build_receipt(
    *,
    user_context: UserContext,
    request: SourceObjectPreviewContentReleaseRequest,
    record: SourceObjectRecord,
    decision: SourceObjectPreviewDecisionEvidence,
    renderer_evidence_hash: str,
    release_gate_evidence_hash: str,
    command_hash: str,
    reason_hash: str,
    sanitized_content_hash: str,
    sanitized_content_byte_length: int,
    released_at_utc: datetime,
    audit_event_id: str,
) -> SourceObjectPreviewContentReleaseReceipt:
    metadata = record.metadata
    draft = SourceObjectPreviewContentReleaseReceipt(
        tenant_id=user_context.tenant_id,
        source_object_id=metadata.object_id,
        source_version_id=metadata.version_id,
        source_object_type=metadata.object_type,
        source_manifest_hash=metadata.manifest_hash,
        source_content_hash=metadata.content_hash,
        source_acl_version=metadata.acl_version,
        source_mime_type=metadata.mime_type,
        preview_slot_id=decision.preview_slot_id,
        preview_policy_id=decision.preview_policy_id,
        parser_profile_id=decision.parser_profile_id,
        sanitizer_profile_id=decision.sanitizer_profile_id,
        preview_decision_evidence_hash=decision.evidence_hash,
        renderer_sandbox_evidence_hash=renderer_evidence_hash,
        renderer_release_gate_evidence_hash=release_gate_evidence_hash,
        human_confirmation_reference=request.human_confirmation_reference,
        confirmation_statement_hash=stable_hash(request.human_confirmation_statement),
        release_request_reference=request.release_request_reference,
        command_hash=command_hash,
        reason_hash=reason_hash,
        sanitized_content_hash=sanitized_content_hash,
        sanitized_content_byte_length=sanitized_content_byte_length,
        requested_by=user_context.user_id,
        released_at_utc=released_at_utc,
        audit_event_id=audit_event_id,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_content_release_receipt_hash(draft)})


def _load_decision(
    *, ledger: SourceObjectPreviewDecisionLedger, tenant_id: str, evidence_hash: str
) -> SourceObjectPreviewDecisionEvidence:
    try:
        decision = ledger.get(tenant_id=tenant_id, evidence_hash=evidence_hash)
    except KeyError as exc:
        raise SourceObjectPreviewContentReleaseInvalidRequest("preview decision evidence was not found") from exc
    if build_source_object_preview_decision_evidence_hash(decision) != decision.evidence_hash:
        raise SourceObjectPreviewContentReleaseInvalidRequest("preview decision evidence hash mismatch")
    return decision


def _authoritative_record(
    *,
    detail_origin: SourceObjectDetailOrigin,
    tenant_id: str,
    source_object_id: str,
    source_version_id: str,
    workspace_source_repository: SourceObjectRepository,
    knowledge_base_article_service: KnowledgeBaseArticleService,
) -> SourceObjectRecord:
    repository = (
        knowledge_base_article_service.source_repository
        if detail_origin == SourceObjectDetailOrigin.KNOWLEDGE_BASE
        else workspace_source_repository
    )
    try:
        return repository.get(
            tenant_id=tenant_id,
            object_id=source_object_id,
            version_id=source_version_id,
        )
    except KeyError as exc:
        raise SourceObjectPreviewContentReleaseInvalidRequest("authoritative source content was not found") from exc


def _release_gate_is_current(
    *, release_gate: SourceObjectPreviewRendererReleaseGateEvidence, released_at_utc: datetime
) -> bool:
    window = timedelta(hours=release_gate.freshness_window_hours)
    checked_times = (
        _aware(release_gate.api_smoke_checked_at_utc),
        _aware(release_gate.recovery_drill_checked_at_utc),
        _aware(release_gate.evaluated_at_utc),
    )
    return all(checked_at - _CLOCK_SKEW <= released_at_utc <= checked_at + window for checked_at in checked_times)


def _command_hash(request: SourceObjectPreviewContentReleaseRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"human_confirmation_statement", "reason"})
    payload["confirmation_statement_hash"] = stable_hash(request.human_confirmation_statement)
    payload["reason_hash"] = stable_hash(request.reason)
    return stable_hash(canonical_json(payload))


def _audit_rejection(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewContentReleaseRequest,
    rejection_reason: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_content.rejected",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "preview_decision_evidence_hash": request.preview_decision_evidence_hash,
            "renderer_release_gate_evidence_hash": request.renderer_release_gate_evidence_hash,
            "command_hash": _command_hash(request),
            "reason_hash": stable_hash(request.reason),
            "rejection_reason": rejection_reason,
            "content_included": False,
            "content_persisted": False,
        },
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("content release evidence timestamps must include a timezone")
    return value.astimezone(UTC)


def _require_valid_receipt_hash(receipt: SourceObjectPreviewContentReleaseReceipt) -> None:
    if build_source_object_preview_content_release_receipt_hash(receipt) != receipt.evidence_hash:
        raise ValueError("source preview content release receipt hash mismatch")


def _receipt_from_row(row: tuple[Any, ...]) -> SourceObjectPreviewContentReleaseReceipt:
    receipt = SourceObjectPreviewContentReleaseReceipt.model_validate(row[0])
    _require_valid_receipt_hash(receipt)
    return receipt
