from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.knowledge_base import KnowledgeBaseArticleService
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.source_object_details import build_source_object_metadata_detail_response
from suite.storage.source_objects import SourceObjectRepository, SourceObjectType

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry

RENDERER_SANDBOX_EVIDENCE_REF_PREFIX = "renderer-sandbox:"
RENDERER_SANDBOX_WORKER_PROFILE_ID = "source-preview-renderer-sandbox-worker:metadata-only.v1"
RENDERER_SANDBOX_BOUNDARIES = (
    "network_access_allowed=false",
    "external_processes_allowed=false",
    "read_only_filesystem=true",
    "external_resource_loading=false",
    "no_direct_storage_mutation=true",
    "no_direct_vector_writes=true",
    "rendered_content_included=false",
    "raw_source_content_returned=false",
    "temporary_workspace_destroyed=true",
)


class SourceObjectPreviewRendererRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_slot_id: str
    preview_policy_id: str
    parser_sanitizer_evidence_ref: str
    backup_coverage_evidence_ref: str
    restore_evidence_ref: str
    reason: str = Field(min_length=1)
    worker_profile_id: str = RENDERER_SANDBOX_WORKER_PROFILE_ID

    @field_validator(
        "preview_slot_id",
        "preview_policy_id",
        "parser_sanitizer_evidence_ref",
        "backup_coverage_evidence_ref",
        "restore_evidence_ref",
        "reason",
        "worker_profile_id",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator(
        "parser_sanitizer_evidence_ref",
        "backup_coverage_evidence_ref",
        "restore_evidence_ref",
        "worker_profile_id",
    )
    @classmethod
    def validate_namespaced_reference(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("reference must include a namespace prefix")
        return value


class SourceObjectPreviewRendererRunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    preview_slot_id: str
    preview_policy_id: str
    gate_id: str
    parser_profile_id: str
    sanitizer_profile_id: str
    worker_profile_id: str
    parser_sanitizer_evidence_ref: str
    backup_coverage_evidence_ref: str
    restore_evidence_ref: str
    sandbox_boundaries: tuple[str, ...]
    access_checked: bool = True
    rendering_allowed: bool = False
    content_rendered: bool = False
    content_included: bool = False
    output_persisted: bool = False
    external_fetch_allowed: bool = False
    temporary_workspace_destroyed: bool = True
    source_detail_audit_event_id: str
    audit_event_id: str
    requested_by: str
    reason_hash: str
    renderer_sandbox_evidence_hash: str
    renderer_sandbox_evidence_ref: str
    schema_version: str = "source_object_preview_renderer_sandbox_evidence.v1"


class SourceObjectPreviewRendererRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    schema_version: str = "source_object_preview_renderer_sandbox_run.v1"
    result_contract: str = "metadata_only_renderer_sandbox_worker_evidence"
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    preview_slot_id: str
    preview_policy_id: str
    worker_profile_id: str
    parser_profile_id: str
    sanitizer_profile_id: str
    parser_sanitizer_evidence_ref: str
    backup_coverage_evidence_ref: str
    restore_evidence_ref: str
    sandbox_boundaries: tuple[str, ...]
    access_checked: bool = True
    rendering_allowed: bool = False
    content_rendered: bool = False
    content_included: bool = False
    output_persisted: bool = False
    external_fetch_allowed: bool = False
    temporary_workspace_destroyed: bool = True
    source_detail_audit_event_id: str
    audit_event_id: str
    renderer_sandbox_evidence_hash: str
    renderer_sandbox_evidence_ref: str
    evidence_persisted: bool = True


class SourceObjectPreviewRendererEvidenceStore(Protocol):
    def append(self, evidence: SourceObjectPreviewRendererRunEvidence) -> SourceObjectPreviewRendererRunEvidence:
        raise NotImplementedError

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererRunEvidence:
        raise NotImplementedError

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererRunEvidence]:
        raise NotImplementedError


class InMemorySourceObjectPreviewRendererEvidenceStore:
    def __init__(self, evidences: Sequence[SourceObjectPreviewRendererRunEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], SourceObjectPreviewRendererRunEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(self, evidence: SourceObjectPreviewRendererRunEvidence) -> SourceObjectPreviewRendererRunEvidence:
        key = (evidence.tenant_id, evidence.renderer_sandbox_evidence_hash)
        if key in self._evidences:
            raise ValueError("source object preview renderer evidence already exists")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererRunEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("source object preview renderer evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererRunEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class JsonlSourceObjectPreviewRendererEvidenceStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._evidences: dict[tuple[str, str], SourceObjectPreviewRendererRunEvidence] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            evidence = SourceObjectPreviewRendererRunEvidence.model_validate_json(line)
            key = (evidence.tenant_id, evidence.renderer_sandbox_evidence_hash)
            if key in self._evidences:
                raise ValueError("duplicate source object preview renderer evidence in store")
            self._evidences[key] = evidence

    def append(self, evidence: SourceObjectPreviewRendererRunEvidence) -> SourceObjectPreviewRendererRunEvidence:
        key = (evidence.tenant_id, evidence.renderer_sandbox_evidence_hash)
        if key in self._evidences:
            raise ValueError("source object preview renderer evidence already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\n")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererRunEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("source object preview renderer evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererRunEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


@dataclass(frozen=True)
class SourceObjectPreviewRendererEvidenceValidation:
    verified: bool
    blocking_reasons: tuple[str, ...] = ()


def build_source_object_preview_renderer_run(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewRendererRunRequest,
) -> SourceObjectPreviewRendererRunResponse:
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
        _audit_renderer_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            source_object_type=detail.source_object_type,
            request=request,
            source_detail_audit_event_id=detail.audit_event_id,
            rejection_reason="unknown_preview_slot",
        )
        raise ValueError("Preview slot is not available for source object")
    if slot.gate.policy_id != request.preview_policy_id:
        _audit_renderer_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            source_object_type=detail.source_object_type,
            request=request,
            source_detail_audit_event_id=detail.audit_event_id,
            rejection_reason="preview_policy_mismatch",
        )
        raise ValueError("Preview policy does not match selected slot")

    sandbox_boundaries = (
        *slot.gate.parser_boundaries,
        *slot.gate.sanitizer_boundaries,
        *RENDERER_SANDBOX_BOUNDARIES,
    )
    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_renderer_run.recorded",
        source_object_ids=[detail.source_object_id],
        metadata={
            "source_object_id": detail.source_object_id,
            "source_version_id": detail.source_version_id,
            "source_object_type": detail.source_object_type.value,
            "preview_slot_id": slot.slot_id,
            "preview_policy_id": slot.gate.policy_id,
            "worker_profile_id": request.worker_profile_id,
            "result_contract": "metadata_only_renderer_sandbox_worker_evidence",
            "access_checked": True,
            "rendering_allowed": False,
            "content_rendered": False,
            "content_included": False,
            "output_persisted": False,
            "external_fetch_allowed": False,
            "temporary_workspace_destroyed": True,
            "source_detail_audit_event_id": detail.audit_event_id,
            "parser_sanitizer_evidence_ref": request.parser_sanitizer_evidence_ref,
            "backup_coverage_evidence_ref": request.backup_coverage_evidence_ref,
            "restore_evidence_ref": request.restore_evidence_ref,
            "sandbox_boundaries": list(sandbox_boundaries),
            "reason_hash": stable_hash(request.reason),
        },
    )
    evidence = build_source_object_preview_renderer_run_evidence(
        tenant_id=detail.tenant_id,
        source_object_id=detail.source_object_id,
        source_version_id=detail.source_version_id,
        source_object_type=detail.source_object_type,
        source_manifest_hash=detail.manifest_hash,
        source_content_hash=detail.content_hash,
        source_acl_version=detail.acl_version,
        preview_slot_id=slot.slot_id,
        preview_policy_id=slot.gate.policy_id,
        gate_id=slot.gate.gate_id,
        parser_profile_id=slot.gate.parser_profile_id,
        sanitizer_profile_id=slot.gate.sanitizer_profile_id,
        worker_profile_id=request.worker_profile_id,
        parser_sanitizer_evidence_ref=request.parser_sanitizer_evidence_ref,
        backup_coverage_evidence_ref=request.backup_coverage_evidence_ref,
        restore_evidence_ref=request.restore_evidence_ref,
        sandbox_boundaries=sandbox_boundaries,
        source_detail_audit_event_id=detail.audit_event_id,
        audit_event_id=event.event_id,
        requested_by=user_context.user_id,
        reason_hash=stable_hash(request.reason),
    )
    persisted = renderer_evidence_store.append(evidence)
    return SourceObjectPreviewRendererRunResponse(
        tenant_id=persisted.tenant_id,
        source_object_id=persisted.source_object_id,
        source_version_id=persisted.source_version_id,
        source_object_type=persisted.source_object_type,
        preview_slot_id=persisted.preview_slot_id,
        preview_policy_id=persisted.preview_policy_id,
        worker_profile_id=persisted.worker_profile_id,
        parser_profile_id=persisted.parser_profile_id,
        sanitizer_profile_id=persisted.sanitizer_profile_id,
        parser_sanitizer_evidence_ref=persisted.parser_sanitizer_evidence_ref,
        backup_coverage_evidence_ref=persisted.backup_coverage_evidence_ref,
        restore_evidence_ref=persisted.restore_evidence_ref,
        sandbox_boundaries=persisted.sandbox_boundaries,
        source_detail_audit_event_id=persisted.source_detail_audit_event_id,
        audit_event_id=persisted.audit_event_id,
        renderer_sandbox_evidence_hash=persisted.renderer_sandbox_evidence_hash,
        renderer_sandbox_evidence_ref=persisted.renderer_sandbox_evidence_ref,
    )


def build_source_object_preview_renderer_run_evidence(
    *,
    tenant_id: str,
    source_object_id: str,
    source_version_id: str,
    source_object_type: SourceObjectType,
    source_manifest_hash: str,
    source_content_hash: str,
    source_acl_version: int,
    preview_slot_id: str,
    preview_policy_id: str,
    gate_id: str,
    parser_profile_id: str,
    sanitizer_profile_id: str,
    worker_profile_id: str,
    parser_sanitizer_evidence_ref: str,
    backup_coverage_evidence_ref: str,
    restore_evidence_ref: str,
    sandbox_boundaries: tuple[str, ...],
    source_detail_audit_event_id: str,
    audit_event_id: str,
    requested_by: str,
    reason_hash: str,
) -> SourceObjectPreviewRendererRunEvidence:
    placeholder_hash = "sha256:" + "0" * 64
    draft = SourceObjectPreviewRendererRunEvidence(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        source_object_type=source_object_type,
        source_manifest_hash=source_manifest_hash,
        source_content_hash=source_content_hash,
        source_acl_version=source_acl_version,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        gate_id=gate_id,
        parser_profile_id=parser_profile_id,
        sanitizer_profile_id=sanitizer_profile_id,
        worker_profile_id=worker_profile_id,
        parser_sanitizer_evidence_ref=parser_sanitizer_evidence_ref,
        backup_coverage_evidence_ref=backup_coverage_evidence_ref,
        restore_evidence_ref=restore_evidence_ref,
        sandbox_boundaries=sandbox_boundaries,
        source_detail_audit_event_id=source_detail_audit_event_id,
        audit_event_id=audit_event_id,
        requested_by=requested_by,
        reason_hash=reason_hash,
        renderer_sandbox_evidence_hash=placeholder_hash,
        renderer_sandbox_evidence_ref=f"{RENDERER_SANDBOX_EVIDENCE_REF_PREFIX}{placeholder_hash}",
    )
    evidence_hash = build_source_object_preview_renderer_evidence_hash(draft)
    return draft.model_copy(
        update={
            "renderer_sandbox_evidence_hash": evidence_hash,
            "renderer_sandbox_evidence_ref": f"{RENDERER_SANDBOX_EVIDENCE_REF_PREFIX}{evidence_hash}",
        }
    )


def build_source_object_preview_renderer_evidence_hash(
    evidence: SourceObjectPreviewRendererRunEvidence,
) -> str:
    return stable_hash(
        canonical_json(
            evidence.model_dump(
                mode="json",
                exclude={"renderer_sandbox_evidence_hash", "renderer_sandbox_evidence_ref"},
            )
        )
    )


def build_default_source_object_preview_renderer_evidence_store(
    data_dir: Path,
) -> SourceObjectPreviewRendererEvidenceStore:
    backend = os.getenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemorySourceObjectPreviewRendererEvidenceStore()
    if backend in {"jsonl", "json-lines", "file"}:
        evidence_path = os.getenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_PATH")
        path = Path(evidence_path) if evidence_path else data_dir / "source_preview" / "renderer_evidence.jsonl"
        return JsonlSourceObjectPreviewRendererEvidenceStore(path=path)
    raise ValueError(f"Unsupported SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_BACKEND: {backend}")


def source_object_preview_renderer_evidence_hash_from_ref(ref: str) -> str | None:
    if not ref.startswith(RENDERER_SANDBOX_EVIDENCE_REF_PREFIX):
        return None
    evidence_hash = ref[len(RENDERER_SANDBOX_EVIDENCE_REF_PREFIX) :]
    if not evidence_hash.startswith("sha256:") or len(evidence_hash) != len("sha256:") + 64:
        return None
    return evidence_hash


def validate_source_object_preview_renderer_evidence(
    *,
    store: SourceObjectPreviewRendererEvidenceStore,
    tenant_id: str,
    source_object_id: str,
    source_version_id: str,
    source_object_type: SourceObjectType,
    preview_slot_id: str,
    preview_policy_id: str,
    parser_sanitizer_evidence_ref: str | None,
    backup_coverage_evidence_ref: str | None,
    restore_evidence_ref: str | None,
    renderer_sandbox_evidence_ref: str | None,
) -> SourceObjectPreviewRendererEvidenceValidation:
    if renderer_sandbox_evidence_ref is None:
        return SourceObjectPreviewRendererEvidenceValidation(verified=False)
    evidence_hash = source_object_preview_renderer_evidence_hash_from_ref(renderer_sandbox_evidence_ref)
    if evidence_hash is None:
        return SourceObjectPreviewRendererEvidenceValidation(
            verified=False,
            blocking_reasons=("renderer_sandbox_worker_evidence_ref_invalid",),
        )
    try:
        evidence = store.get(tenant_id=tenant_id, evidence_hash=evidence_hash)
    except KeyError:
        return SourceObjectPreviewRendererEvidenceValidation(
            verified=False,
            blocking_reasons=("renderer_sandbox_worker_evidence_not_found",),
        )

    blocking_reasons: list[str] = []
    if evidence.renderer_sandbox_evidence_ref != renderer_sandbox_evidence_ref:
        blocking_reasons.append("renderer_sandbox_worker_evidence_ref_mismatch")
    if (
        evidence.source_object_id != source_object_id
        or evidence.source_version_id != source_version_id
        or evidence.source_object_type != source_object_type
    ):
        blocking_reasons.append("renderer_sandbox_worker_evidence_source_mismatch")
    if evidence.preview_slot_id != preview_slot_id or evidence.preview_policy_id != preview_policy_id:
        blocking_reasons.append("renderer_sandbox_worker_evidence_preview_policy_mismatch")
    if parser_sanitizer_evidence_ref is None or evidence.parser_sanitizer_evidence_ref != parser_sanitizer_evidence_ref:
        blocking_reasons.append("renderer_sandbox_worker_evidence_parser_sanitizer_mismatch")
    if backup_coverage_evidence_ref is None or evidence.backup_coverage_evidence_ref != backup_coverage_evidence_ref:
        blocking_reasons.append("renderer_sandbox_worker_evidence_backup_mismatch")
    if restore_evidence_ref is None or evidence.restore_evidence_ref != restore_evidence_ref:
        blocking_reasons.append("renderer_sandbox_worker_evidence_restore_mismatch")
    if (
        evidence.rendering_allowed
        or evidence.content_rendered
        or evidence.content_included
        or evidence.output_persisted
        or evidence.external_fetch_allowed
        or not evidence.temporary_workspace_destroyed
    ):
        blocking_reasons.append("renderer_sandbox_worker_evidence_content_boundary_mismatch")
    return SourceObjectPreviewRendererEvidenceValidation(
        verified=not blocking_reasons,
        blocking_reasons=tuple(blocking_reasons),
    )


def _audit_renderer_run_rejection(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    source_object_type: SourceObjectType,
    request: SourceObjectPreviewRendererRunRequest,
    source_detail_audit_event_id: str,
    rejection_reason: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_renderer_run.rejected",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "source_object_type": source_object_type.value,
            "preview_slot_id": request.preview_slot_id,
            "preview_policy_id": request.preview_policy_id,
            "worker_profile_id": request.worker_profile_id,
            "result_contract": "metadata_only_renderer_sandbox_worker_evidence",
            "content_included": False,
            "access_checked": True,
            "rejection_reason": rejection_reason,
            "source_detail_audit_event_id": source_detail_audit_event_id,
            "reason_hash": stable_hash(request.reason),
        },
    )
