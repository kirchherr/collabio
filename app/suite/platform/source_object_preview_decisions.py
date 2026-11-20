from __future__ import annotations

import json
import os
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.knowledge_base import KnowledgeBaseArticleService
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.source_object_details import (
    SourceObjectMetadataDetailResponse,
    build_source_object_metadata_detail_response,
)
from suite.platform.source_object_preview import SourceObjectPreviewGate
from suite.platform.source_object_preview_renderer import (
    SourceObjectPreviewRendererEvidenceStore,
    validate_source_object_preview_renderer_evidence,
)
from suite.storage.source_objects import SourceObjectRepository, SourceObjectType

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry

BACKUP_COVERAGE_EVIDENCE = "backup_coverage_evidence"
RENDERER_SANDBOX_WORKER_EVIDENCE = "renderer_sandbox_worker_evidence"
RESTORE_DRILL_EVIDENCE = "restore_drill_evidence"


class SourceObjectPreviewDecisionStatus(StrEnum):
    BLOCKED = "blocked"


class SourceObjectPreviewDecisionAccessDenied(PermissionError):
    pass


class SourceObjectPreviewDecisionInvalidRequest(ValueError):
    pass


class SourceObjectPreviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_slot_id: str
    preview_policy_id: str
    reason: str = Field(min_length=1)
    parser_sanitizer_evidence_ref: str | None = None
    renderer_sandbox_evidence_ref: str | None = None
    backup_coverage_evidence_ref: str | None = None
    restore_evidence_ref: str | None = None
    human_confirmation_reference: str | None = None

    @field_validator("preview_slot_id", "preview_policy_id", "reason")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator(
        "parser_sanitizer_evidence_ref",
        "renderer_sandbox_evidence_ref",
        "backup_coverage_evidence_ref",
        "restore_evidence_ref",
        "human_confirmation_reference",
    )
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("reference must not be empty")
        if ":" not in stripped:
            raise ValueError("reference must include a namespace prefix")
        return stripped


class SourceObjectPreviewDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: str = "source_object_preview_decision.v1"
    result_contract: str = "metadata_only_preview_decision"
    decision_status: SourceObjectPreviewDecisionStatus = SourceObjectPreviewDecisionStatus.BLOCKED
    content_release_allowed: bool = False
    content_included: bool = False
    access_checked: bool = True
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    preview_slot_id: str
    preview_policy_id: str
    gate: SourceObjectPreviewGate
    tenant_policy_checked: bool = True
    tenant_preview_policy_enabled: bool = False
    required_content_release_evidence: tuple[str, ...]
    provided_evidence: tuple[str, ...]
    provided_evidence_refs: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    parser_profile_id: str
    sanitizer_profile_id: str
    renderer_sandbox_required: bool = True
    renderer_sandbox_evidence_ref: str | None = None
    backup_coverage_required: bool = True
    backup_coverage_evidence_ref: str | None = None
    restore_evidence_required: bool = True
    restore_evidence_ref: str | None = None
    human_confirmation_reference: str | None = None
    source_detail_audit_event_id: str
    audit_event_id: str
    renderer_sandbox_evidence_verified: bool = False
    backup_coverage_evidence_verified: bool = False
    restore_evidence_verified: bool = False
    human_confirmation_verified: bool = False
    content_release_evidence_complete: bool = False
    preview_decision_evidence_hash: str
    decision_ledger_ref: str
    ledger_entry_persisted: bool = True


class SourceObjectPreviewDecisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    preview_slot_id: str
    preview_policy_id: str
    decision_status: SourceObjectPreviewDecisionStatus
    content_release_allowed: bool = False
    content_included: bool = False
    access_checked: bool = True
    tenant_policy_checked: bool = True
    tenant_preview_policy_enabled: bool = False
    required_content_release_evidence: tuple[str, ...]
    provided_evidence: tuple[str, ...]
    provided_evidence_refs: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    parser_profile_id: str
    sanitizer_profile_id: str
    renderer_sandbox_required: bool = True
    renderer_sandbox_evidence_ref: str | None = None
    backup_coverage_required: bool = True
    backup_coverage_evidence_ref: str | None = None
    restore_evidence_required: bool = True
    restore_evidence_ref: str | None = None
    human_confirmation_reference: str | None = None
    renderer_sandbox_evidence_verified: bool = False
    backup_coverage_evidence_verified: bool = False
    restore_evidence_verified: bool = False
    human_confirmation_verified: bool = False
    content_release_evidence_complete: bool = False
    source_detail_audit_event_id: str
    audit_event_id: str
    requested_by: str
    reason_hash: str
    evidence_hash: str
    schema_version: str = "source_object_preview_decision_evidence.v1"


class SourceObjectPreviewDecisionLedger(Protocol):
    def append(self, evidence: SourceObjectPreviewDecisionEvidence) -> SourceObjectPreviewDecisionEvidence:
        raise NotImplementedError

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewDecisionEvidence:
        raise NotImplementedError

    def list_decisions(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewDecisionEvidence]:
        raise NotImplementedError


class InMemorySourceObjectPreviewDecisionLedger:
    def __init__(self, evidences: Sequence[SourceObjectPreviewDecisionEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], SourceObjectPreviewDecisionEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(self, evidence: SourceObjectPreviewDecisionEvidence) -> SourceObjectPreviewDecisionEvidence:
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("source object preview decision evidence already exists")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewDecisionEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("source object preview decision evidence not found") from exc

    def list_decisions(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewDecisionEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class JsonlSourceObjectPreviewDecisionLedger:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._evidences: dict[tuple[str, str], SourceObjectPreviewDecisionEvidence] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            evidence = SourceObjectPreviewDecisionEvidence.model_validate_json(line)
            key = (evidence.tenant_id, evidence.evidence_hash)
            if key in self._evidences:
                raise ValueError("duplicate source object preview decision evidence in ledger")
            self._evidences[key] = evidence

    def append(self, evidence: SourceObjectPreviewDecisionEvidence) -> SourceObjectPreviewDecisionEvidence:
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("source object preview decision evidence already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\n")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewDecisionEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("source object preview decision evidence not found") from exc

    def list_decisions(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewDecisionEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class PgSourceObjectPreviewDecisionLedger:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, evidence: SourceObjectPreviewDecisionEvidence) -> SourceObjectPreviewDecisionEvidence:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, evidence.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.source_object_preview_decision_evidence (
                        tenant_id,
                        source_object_id,
                        source_version_id,
                        source_object_type,
                        preview_slot_id,
                        preview_policy_id,
                        decision_status,
                        content_release_allowed,
                        content_included,
                        access_checked,
                        tenant_policy_checked,
                        tenant_preview_policy_enabled,
                        required_content_release_evidence,
                        provided_evidence,
                        provided_evidence_refs,
                        missing_evidence,
                        blocking_reasons,
                        parser_profile_id,
                        sanitizer_profile_id,
                        renderer_sandbox_required,
                        renderer_sandbox_evidence_ref,
                        backup_coverage_required,
                        backup_coverage_evidence_ref,
                        restore_evidence_required,
                        restore_evidence_ref,
                        human_confirmation_reference,
                        renderer_sandbox_evidence_verified,
                        backup_coverage_evidence_verified,
                        restore_evidence_verified,
                        human_confirmation_verified,
                        content_release_evidence_complete,
                        source_detail_audit_event_id,
                        audit_event_id,
                        requested_by,
                        reason_hash,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._evidence_values(evidence),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source object preview decision evidence already exists") from exc
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewDecisionEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT {self._select_columns()}
                FROM collabio.source_object_preview_decision_evidence
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("source object preview decision evidence not found")
        return self._evidence_from_row(row)

    def list_decisions(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewDecisionEvidence]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                f"""
                SELECT {self._select_columns()}
                FROM collabio.source_object_preview_decision_evidence
                WHERE tenant_id = %s
                ORDER BY captured_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._evidence_from_row(row) for row in rows)

    def _evidence_values(self, evidence: SourceObjectPreviewDecisionEvidence) -> tuple[object, ...]:
        return (
            evidence.tenant_id,
            evidence.source_object_id,
            evidence.source_version_id,
            evidence.source_object_type.value,
            evidence.preview_slot_id,
            evidence.preview_policy_id,
            evidence.decision_status.value,
            evidence.content_release_allowed,
            evidence.content_included,
            evidence.access_checked,
            evidence.tenant_policy_checked,
            evidence.tenant_preview_policy_enabled,
            Jsonb(list(evidence.required_content_release_evidence)),
            Jsonb(list(evidence.provided_evidence)),
            Jsonb(list(evidence.provided_evidence_refs)),
            Jsonb(list(evidence.missing_evidence)),
            Jsonb(list(evidence.blocking_reasons)),
            evidence.parser_profile_id,
            evidence.sanitizer_profile_id,
            evidence.renderer_sandbox_required,
            evidence.renderer_sandbox_evidence_ref,
            evidence.backup_coverage_required,
            evidence.backup_coverage_evidence_ref,
            evidence.restore_evidence_required,
            evidence.restore_evidence_ref,
            evidence.human_confirmation_reference,
            evidence.renderer_sandbox_evidence_verified,
            evidence.backup_coverage_evidence_verified,
            evidence.restore_evidence_verified,
            evidence.human_confirmation_verified,
            evidence.content_release_evidence_complete,
            evidence.source_detail_audit_event_id,
            evidence.audit_event_id,
            evidence.requested_by,
            evidence.reason_hash,
            evidence.evidence_hash,
            evidence.schema_version,
        )

    def _evidence_from_row(self, row: tuple[Any, ...]) -> SourceObjectPreviewDecisionEvidence:
        return SourceObjectPreviewDecisionEvidence(
            tenant_id=str(row[0]),
            source_object_id=str(row[1]),
            source_version_id=str(row[2]),
            source_object_type=SourceObjectType(str(row[3])),
            preview_slot_id=str(row[4]),
            preview_policy_id=str(row[5]),
            decision_status=SourceObjectPreviewDecisionStatus(str(row[6])),
            content_release_allowed=bool(row[7]),
            content_included=bool(row[8]),
            access_checked=bool(row[9]),
            tenant_policy_checked=bool(row[10]),
            tenant_preview_policy_enabled=bool(row[11]),
            required_content_release_evidence=_row_json_tuple(row[12]),
            provided_evidence=_row_json_tuple(row[13]),
            provided_evidence_refs=_row_json_tuple(row[14]),
            missing_evidence=_row_json_tuple(row[15]),
            blocking_reasons=_row_json_tuple(row[16]),
            parser_profile_id=str(row[17]),
            sanitizer_profile_id=str(row[18]),
            renderer_sandbox_required=bool(row[19]),
            renderer_sandbox_evidence_ref=str(row[20]) if row[20] is not None else None,
            backup_coverage_required=bool(row[21]),
            backup_coverage_evidence_ref=str(row[22]) if row[22] is not None else None,
            restore_evidence_required=bool(row[23]),
            restore_evidence_ref=str(row[24]) if row[24] is not None else None,
            human_confirmation_reference=str(row[25]) if row[25] is not None else None,
            renderer_sandbox_evidence_verified=bool(row[26]),
            backup_coverage_evidence_verified=bool(row[27]),
            restore_evidence_verified=bool(row[28]),
            human_confirmation_verified=bool(row[29]),
            content_release_evidence_complete=bool(row[30]),
            source_detail_audit_event_id=str(row[31]),
            audit_event_id=str(row[32]),
            requested_by=str(row[33]),
            reason_hash=str(row[34]),
            evidence_hash=str(row[35]),
            schema_version=str(row[36]),
        )

    def _select_columns(self) -> str:
        return """
            tenant_id,
            source_object_id,
            source_version_id,
            source_object_type,
            preview_slot_id,
            preview_policy_id,
            decision_status,
            content_release_allowed,
            content_included,
            access_checked,
            tenant_policy_checked,
            tenant_preview_policy_enabled,
            required_content_release_evidence,
            provided_evidence,
            provided_evidence_refs,
            missing_evidence,
            blocking_reasons,
            parser_profile_id,
            sanitizer_profile_id,
            renderer_sandbox_required,
            renderer_sandbox_evidence_ref,
            backup_coverage_required,
            backup_coverage_evidence_ref,
            restore_evidence_required,
            restore_evidence_ref,
            human_confirmation_reference,
            renderer_sandbox_evidence_verified,
            backup_coverage_evidence_verified,
            restore_evidence_verified,
            human_confirmation_verified,
            content_release_evidence_complete,
            source_detail_audit_event_id,
            audit_event_id,
            requested_by,
            reason_hash,
            evidence_hash,
            schema_version
        """

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def _row_json_tuple(value: object) -> tuple[str, ...]:
    loaded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("source object preview decision ledger JSONB arrays must contain strings")
    return tuple(loaded)


def build_source_object_preview_decision(
    *,
    user_context: UserContext,
    tenant_policy: TenantPolicy,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewDecisionRequest,
) -> SourceObjectPreviewDecisionResponse:
    if source_object_id not in user_context.readable_object_ids:
        _audit_preview_decision_denial(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
        )
        raise SourceObjectPreviewDecisionAccessDenied("User cannot request preview decision for source object")

    detail = build_source_object_metadata_detail_response(
        user_context=user_context,
        workspace_source_repository=workspace_source_repository,
        module_registry=module_registry,
        knowledge_base_article_service=knowledge_base_article_service,
        audit_logger=audit_logger,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
    )
    slot = next((candidate for candidate in detail.preview_slots if candidate.slot_id == request.preview_slot_id), None)
    if slot is None:
        _audit_preview_decision_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            detail=detail,
            request=request,
            rejection_reason="unknown_preview_slot",
        )
        raise SourceObjectPreviewDecisionInvalidRequest("Preview slot is not available for source object")
    if slot.gate.policy_id != request.preview_policy_id:
        _audit_preview_decision_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            detail=detail,
            request=request,
            rejection_reason="preview_policy_mismatch",
        )
        raise SourceObjectPreviewDecisionInvalidRequest("Preview policy does not match selected slot")

    tenant_preview_policy_enabled = _tenant_preview_policy_enabled(tenant_policy)
    required_evidence = _required_evidence(slot.gate)
    renderer_validation = validate_source_object_preview_renderer_evidence(
        store=preview_renderer_evidence_store,
        tenant_id=detail.tenant_id,
        source_object_id=detail.source_object_id,
        source_version_id=detail.source_version_id,
        source_object_type=detail.source_object_type,
        preview_slot_id=slot.slot_id,
        preview_policy_id=slot.gate.policy_id,
        parser_sanitizer_evidence_ref=request.parser_sanitizer_evidence_ref,
        backup_coverage_evidence_ref=request.backup_coverage_evidence_ref,
        restore_evidence_ref=request.restore_evidence_ref,
        renderer_sandbox_evidence_ref=request.renderer_sandbox_evidence_ref,
    )
    provided_evidence = _provided_evidence(
        tenant_preview_policy_enabled=tenant_preview_policy_enabled,
        request=request,
        renderer_sandbox_evidence_verified=renderer_validation.verified,
    )
    provided_evidence_refs = _provided_evidence_refs(
        detail=detail,
        request=request,
        tenant_preview_policy_enabled=tenant_preview_policy_enabled,
        renderer_sandbox_evidence_verified=renderer_validation.verified,
    )
    missing_evidence = tuple(evidence for evidence in required_evidence if evidence not in provided_evidence)
    renderer_sandbox_evidence_verified = renderer_validation.verified
    backup_coverage_evidence_verified = request.backup_coverage_evidence_ref is not None
    restore_evidence_verified = request.restore_evidence_ref is not None
    human_confirmation_verified = request.human_confirmation_reference is not None
    content_release_evidence_complete = not missing_evidence
    blocking_reasons = (
        *slot.gate.blocking_reasons,
        *renderer_validation.blocking_reasons,
        "content_preview_skeleton_blocks_release_until_renderer_operational",
    )

    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_decision.blocked",
        source_object_ids=[detail.source_object_id],
        metadata={
            "source_object_id": detail.source_object_id,
            "source_version_id": detail.source_version_id,
            "source_object_type": detail.source_object_type.value,
            "preview_slot_id": slot.slot_id,
            "preview_policy_id": slot.gate.policy_id,
            "result_contract": "metadata_only",
            "decision_status": SourceObjectPreviewDecisionStatus.BLOCKED.value,
            "content_release_allowed": False,
            "content_included": False,
            "access_checked": True,
            "tenant_policy_checked": True,
            "tenant_preview_policy_enabled": tenant_preview_policy_enabled,
            "required_content_release_evidence": list(required_evidence),
            "provided_evidence": list(provided_evidence),
            "provided_evidence_refs": list(provided_evidence_refs),
            "missing_evidence": list(missing_evidence),
            "blocking_reasons": list(blocking_reasons),
            "source_detail_audit_event_id": detail.audit_event_id,
            "renderer_sandbox_evidence_verified": renderer_sandbox_evidence_verified,
            "backup_coverage_evidence_verified": backup_coverage_evidence_verified,
            "restore_evidence_verified": restore_evidence_verified,
            "human_confirmation_verified": human_confirmation_verified,
            "content_release_evidence_complete": content_release_evidence_complete,
            "reason_hash": stable_hash(request.reason),
        },
    )
    evidence = build_source_object_preview_decision_evidence(
        tenant_id=detail.tenant_id,
        source_object_id=detail.source_object_id,
        source_version_id=detail.source_version_id,
        source_object_type=detail.source_object_type,
        preview_slot_id=slot.slot_id,
        preview_policy_id=slot.gate.policy_id,
        tenant_preview_policy_enabled=tenant_preview_policy_enabled,
        required_content_release_evidence=required_evidence,
        provided_evidence=provided_evidence,
        provided_evidence_refs=provided_evidence_refs,
        missing_evidence=missing_evidence,
        blocking_reasons=blocking_reasons,
        parser_profile_id=slot.gate.parser_profile_id,
        sanitizer_profile_id=slot.gate.sanitizer_profile_id,
        renderer_sandbox_evidence_ref=request.renderer_sandbox_evidence_ref,
        backup_coverage_evidence_ref=request.backup_coverage_evidence_ref,
        restore_evidence_ref=request.restore_evidence_ref,
        human_confirmation_reference=request.human_confirmation_reference,
        renderer_sandbox_evidence_verified=renderer_sandbox_evidence_verified,
        backup_coverage_evidence_verified=backup_coverage_evidence_verified,
        restore_evidence_verified=restore_evidence_verified,
        human_confirmation_verified=human_confirmation_verified,
        content_release_evidence_complete=content_release_evidence_complete,
        source_detail_audit_event_id=detail.audit_event_id,
        audit_event_id=event.event_id,
        requested_by=user_context.user_id,
        reason_hash=stable_hash(request.reason),
    )
    persisted_evidence = preview_decision_ledger.append(evidence)
    return SourceObjectPreviewDecisionResponse(
        tenant_id=detail.tenant_id,
        source_object_id=detail.source_object_id,
        source_version_id=detail.source_version_id,
        source_object_type=detail.source_object_type,
        preview_slot_id=slot.slot_id,
        preview_policy_id=slot.gate.policy_id,
        gate=slot.gate,
        tenant_preview_policy_enabled=tenant_preview_policy_enabled,
        required_content_release_evidence=required_evidence,
        provided_evidence=provided_evidence,
        provided_evidence_refs=provided_evidence_refs,
        missing_evidence=missing_evidence,
        blocking_reasons=blocking_reasons,
        parser_profile_id=slot.gate.parser_profile_id,
        sanitizer_profile_id=slot.gate.sanitizer_profile_id,
        renderer_sandbox_evidence_ref=request.renderer_sandbox_evidence_ref,
        backup_coverage_evidence_ref=request.backup_coverage_evidence_ref,
        restore_evidence_ref=request.restore_evidence_ref,
        human_confirmation_reference=request.human_confirmation_reference,
        source_detail_audit_event_id=detail.audit_event_id,
        audit_event_id=event.event_id,
        renderer_sandbox_evidence_verified=renderer_sandbox_evidence_verified,
        backup_coverage_evidence_verified=backup_coverage_evidence_verified,
        restore_evidence_verified=restore_evidence_verified,
        human_confirmation_verified=human_confirmation_verified,
        content_release_evidence_complete=content_release_evidence_complete,
        preview_decision_evidence_hash=persisted_evidence.evidence_hash,
        decision_ledger_ref=f"preview-decision-ledger:{persisted_evidence.evidence_hash}",
    )


def _tenant_preview_policy_enabled(tenant_policy: TenantPolicy) -> bool:
    return tenant_policy.content_preview_enabled is True


def build_source_object_preview_decision_evidence(
    *,
    tenant_id: str,
    source_object_id: str,
    source_version_id: str,
    source_object_type: SourceObjectType,
    preview_slot_id: str,
    preview_policy_id: str,
    tenant_preview_policy_enabled: bool,
    required_content_release_evidence: tuple[str, ...],
    provided_evidence: tuple[str, ...],
    provided_evidence_refs: tuple[str, ...],
    missing_evidence: tuple[str, ...],
    blocking_reasons: tuple[str, ...],
    parser_profile_id: str,
    sanitizer_profile_id: str,
    renderer_sandbox_evidence_ref: str | None,
    backup_coverage_evidence_ref: str | None,
    restore_evidence_ref: str | None,
    human_confirmation_reference: str | None,
    renderer_sandbox_evidence_verified: bool,
    backup_coverage_evidence_verified: bool,
    restore_evidence_verified: bool,
    human_confirmation_verified: bool,
    content_release_evidence_complete: bool,
    source_detail_audit_event_id: str,
    audit_event_id: str,
    requested_by: str,
    reason_hash: str,
) -> SourceObjectPreviewDecisionEvidence:
    draft = SourceObjectPreviewDecisionEvidence(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        source_object_type=source_object_type,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        decision_status=SourceObjectPreviewDecisionStatus.BLOCKED,
        tenant_preview_policy_enabled=tenant_preview_policy_enabled,
        required_content_release_evidence=required_content_release_evidence,
        provided_evidence=provided_evidence,
        provided_evidence_refs=provided_evidence_refs,
        missing_evidence=missing_evidence,
        blocking_reasons=blocking_reasons,
        parser_profile_id=parser_profile_id,
        sanitizer_profile_id=sanitizer_profile_id,
        renderer_sandbox_evidence_ref=renderer_sandbox_evidence_ref,
        backup_coverage_evidence_ref=backup_coverage_evidence_ref,
        restore_evidence_ref=restore_evidence_ref,
        human_confirmation_reference=human_confirmation_reference,
        renderer_sandbox_evidence_verified=renderer_sandbox_evidence_verified,
        backup_coverage_evidence_verified=backup_coverage_evidence_verified,
        restore_evidence_verified=restore_evidence_verified,
        human_confirmation_verified=human_confirmation_verified,
        content_release_evidence_complete=content_release_evidence_complete,
        source_detail_audit_event_id=source_detail_audit_event_id,
        audit_event_id=audit_event_id,
        requested_by=requested_by,
        reason_hash=reason_hash,
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_decision_evidence_hash(draft)})


def build_source_object_preview_decision_evidence_hash(evidence: SourceObjectPreviewDecisionEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_default_source_object_preview_decision_ledger(data_dir: Path) -> SourceObjectPreviewDecisionLedger:
    backend = os.getenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemorySourceObjectPreviewDecisionLedger()
    if backend in {"jsonl", "json-lines", "file"}:
        ledger_path = os.getenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_PATH")
        path = Path(ledger_path) if ledger_path else data_dir / "source_preview" / "decision_ledger.jsonl"
        return JsonlSourceObjectPreviewDecisionLedger(path=path)
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = os.getenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_DSN") or os.getenv("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL source preview decision ledger requires "
                "SUITE_SOURCE_PREVIEW_DECISION_LEDGER_DSN or SUITE_DATABASE_DSN"
            )
        return PgSourceObjectPreviewDecisionLedger(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_SOURCE_PREVIEW_DECISION_LEDGER_BACKEND: {backend}")


def _required_evidence(gate: SourceObjectPreviewGate) -> tuple[str, ...]:
    return (
        *gate.required_content_release_evidence,
        RENDERER_SANDBOX_WORKER_EVIDENCE,
        BACKUP_COVERAGE_EVIDENCE,
        RESTORE_DRILL_EVIDENCE,
    )


def _provided_evidence(
    *,
    tenant_preview_policy_enabled: bool,
    request: SourceObjectPreviewDecisionRequest,
    renderer_sandbox_evidence_verified: bool,
) -> tuple[str, ...]:
    evidence = ["source_object_acl_checked", "source_detail_audit_event"]
    if tenant_preview_policy_enabled:
        evidence.append("tenant_preview_policy_enabled")
    if request.parser_sanitizer_evidence_ref is not None:
        evidence.append("parser_sanitizer_evidence")
    if request.human_confirmation_reference is not None:
        evidence.append("human_content_release_confirmation")
    if renderer_sandbox_evidence_verified:
        evidence.append(RENDERER_SANDBOX_WORKER_EVIDENCE)
    if request.backup_coverage_evidence_ref is not None:
        evidence.append(BACKUP_COVERAGE_EVIDENCE)
    if request.restore_evidence_ref is not None:
        evidence.append(RESTORE_DRILL_EVIDENCE)
    return tuple(evidence)


def _provided_evidence_refs(
    *,
    detail: SourceObjectMetadataDetailResponse,
    request: SourceObjectPreviewDecisionRequest,
    tenant_preview_policy_enabled: bool,
    renderer_sandbox_evidence_verified: bool,
) -> tuple[str, ...]:
    refs = [
        f"acl:source_object:{detail.source_object_id}:v{detail.acl_version}",
        f"audit:{detail.audit_event_id}",
    ]
    if tenant_preview_policy_enabled:
        refs.append(f"tenant_policy:{detail.tenant_id}:content_preview_enabled")
    if request.parser_sanitizer_evidence_ref is not None:
        refs.append(request.parser_sanitizer_evidence_ref)
    if renderer_sandbox_evidence_verified and request.renderer_sandbox_evidence_ref is not None:
        refs.append(request.renderer_sandbox_evidence_ref)
    if request.backup_coverage_evidence_ref is not None:
        refs.append(request.backup_coverage_evidence_ref)
    if request.restore_evidence_ref is not None:
        refs.append(request.restore_evidence_ref)
    if request.human_confirmation_reference is not None:
        refs.append(request.human_confirmation_reference)
    return tuple(refs)


def _audit_preview_decision_denial(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewDecisionRequest,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_decision.denied",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "preview_slot_id": request.preview_slot_id,
            "preview_policy_id": request.preview_policy_id,
            "result_contract": "metadata_only",
            "content_included": False,
            "access_checked": True,
            "denial_reason": "acl_object_not_readable",
            "reason_hash": stable_hash(request.reason),
        },
    )


def _audit_preview_decision_rejection(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    detail: SourceObjectMetadataDetailResponse,
    request: SourceObjectPreviewDecisionRequest,
    rejection_reason: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_decision.rejected",
        source_object_ids=[detail.source_object_id],
        metadata={
            "source_object_id": detail.source_object_id,
            "source_version_id": detail.source_version_id,
            "source_object_type": detail.source_object_type.value,
            "preview_slot_id": request.preview_slot_id,
            "preview_policy_id": request.preview_policy_id,
            "result_contract": "metadata_only",
            "content_included": False,
            "access_checked": True,
            "rejection_reason": rejection_reason,
            "source_detail_audit_event_id": detail.audit_event_id,
            "reason_hash": stable_hash(request.reason),
        },
    )
