from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.knowledge_base import KnowledgeBaseArticleService
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry
from suite.platform.source_object_details import build_source_object_metadata_detail_response
from suite.platform.source_object_preview_renderer_release_gate import (
    SourceObjectPreviewRendererReleaseGateEvidence,
    SourceObjectPreviewRendererReleaseGateEvidenceStore,
    require_source_object_preview_renderer_release_gate_for_wiring,
)
from suite.storage.source_objects import SourceObjectRepository, SourceObjectType

DEFAULT_PREVIEW_ADAPTER_ID = "canonical-pdf-libreoffice-pdfjs.v1"
PREVIEW_ADAPTER_CONTRACT_VERSION = "source_object_preview_adapter.v1"
PREVIEW_ADAPTER_DRY_RUN_SCHEMA_VERSION = "source_object_preview_adapter_dry_run.v1"
PREVIEW_ADAPTER_CLOCK_SKEW = timedelta(minutes=5)
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")

OFFICE_TO_PDF_MIME_TYPES = (
    "application/rtf",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
)
DIRECT_PDF_MIME_TYPES = ("application/pdf",)
PREVIEW_ADAPTER_SECURITY_CONTROLS = (
    "authoritative_acl_check_required",
    "fresh_tenant_release_gate_required",
    "current_tenant_content_preview_policy_required",
    "source_bytes_forbidden_in_dry_run",
    "digest_pinned_renderer_image_required",
    "gvisor_or_microvm_isolation_required",
    "network_egress_denied",
    "read_only_root_filesystem_required",
    "ephemeral_workspace_required",
    "non_root_and_capability_drop_required",
    "cpu_memory_wallclock_and_output_limits_required",
    "magic_byte_and_container_validation_required",
    "archive_expansion_limits_required",
    "malware_and_cdr_preflight_required",
    "macro_and_active_content_execution_forbidden",
    "external_resource_loading_forbidden",
    "canonical_pdf_output_revalidation_required",
    "output_hash_and_source_version_binding_required",
    "separate_origin_viewer_required",
    "strict_viewer_csp_required",
    "authenticated_short_lived_view_access_required",
    "viewer_direct_storage_access_forbidden",
    "wopi_editing_is_a_separate_boundary",
)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry


class SourceObjectPreviewAdapterDryRunBlocked(ValueError):
    pass


class PreviewAdapterRoute(StrEnum):
    ISOLATED_OFFICE_TO_PDF = "isolated_office_to_pdf"
    DIRECT_PDF_VIEWER = "direct_pdf_viewer"
    UNSUPPORTED = "unsupported"


class SourceObjectPreviewAdapterDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = DEFAULT_PREVIEW_ADAPTER_ID
    contract_version: str = PREVIEW_ADAPTER_CONTRACT_VERSION
    architecture: str = "canonical_pdf_preview"
    converter_engine_family: str = "libreoffice_headless"
    viewer_engine_family: str = "pdfjs"
    collaboration_protocol: str = "none"
    future_editing_protocol: str = "wopi"
    supported_source_object_types: tuple[SourceObjectType, ...] = (SourceObjectType.DOCUMENT,)
    office_to_pdf_mime_types: tuple[str, ...] = OFFICE_TO_PDF_MIME_TYPES
    direct_view_mime_types: tuple[str, ...] = DIRECT_PDF_MIME_TYPES
    target_media_type: str = "application/pdf"
    security_controls: tuple[str, ...] = PREVIEW_ADAPTER_SECURITY_CONTROLS
    metadata_only_dry_run: bool = True
    engine_execution_enabled: bool = False
    content_input_allowed: bool = False
    rendered_output_allowed: bool = False
    persistent_output_allowed: bool = False
    external_network_allowed: bool = False
    supply_chain_pin_required: bool = True

    @model_validator(mode="after")
    def require_closed_adapter_contract(self) -> SourceObjectPreviewAdapterDescriptor:
        if self.adapter_id != DEFAULT_PREVIEW_ADAPTER_ID:
            raise ValueError("preview adapter ID is not the selected architecture")
        if self.contract_version != PREVIEW_ADAPTER_CONTRACT_VERSION:
            raise ValueError("preview adapter contract version mismatch")
        if self.collaboration_protocol != "none" or self.future_editing_protocol != "wopi":
            raise ValueError("preview and collaborative editing boundaries must remain separate")
        if self.target_media_type != "application/pdf":
            raise ValueError("first preview adapter must produce canonical PDF")
        if (
            not self.metadata_only_dry_run
            or self.engine_execution_enabled
            or self.content_input_allowed
            or self.rendered_output_allowed
            or self.persistent_output_allowed
            or self.external_network_allowed
        ):
            raise ValueError("preview adapter dry-run contract opened a content or execution boundary")
        if set(self.security_controls) != set(PREVIEW_ADAPTER_SECURITY_CONTROLS):
            raise ValueError("preview adapter security controls are incomplete")
        return self


class SourceObjectPreviewAdapterDryRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    preview_slot_id: str
    preview_policy_id: str
    renderer_release_gate_evidence_hash: str

    @field_validator("source_manifest_hash", "source_content_hash", "renderer_release_gate_evidence_hash")
    @classmethod
    def require_sha256_reference(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview adapter input hashes must be sha256 references")
        return value


class SourceObjectPreviewAdapterDryRunPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_ADAPTER_DRY_RUN_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    preview_slot_id: str
    preview_policy_id: str
    renderer_release_gate_evidence_hash: str
    adapter_id: str
    adapter_contract_version: str
    adapter_descriptor_hash: str
    route: PreviewAdapterRoute
    target_media_type: str | None
    supported: bool
    blocking_reasons: tuple[str, ...]
    production_execution_requirements: tuple[str, ...]
    access_checked: bool = True
    release_gate_checked: bool = True
    release_gate_fresh: bool = True
    content_accessed: bool = False
    source_bytes_included: bool = False
    renderer_invoked: bool = False
    viewer_session_created: bool = False
    output_generated: bool = False
    output_persisted: bool = False
    external_network_allowed: bool = False
    wopi_session_created: bool = False
    plan_hash: str

    @model_validator(mode="after")
    def require_metadata_only_plan(self) -> SourceObjectPreviewAdapterDryRunPlan:
        if self.supported != (self.route != PreviewAdapterRoute.UNSUPPORTED):
            raise ValueError("preview adapter support and route are inconsistent")
        if self.supported and self.blocking_reasons:
            raise ValueError("supported preview adapter plan cannot contain blocking reasons")
        if not self.supported and not self.blocking_reasons:
            raise ValueError("unsupported preview adapter plan requires blocking reasons")
        if self.supported and self.target_media_type != "application/pdf":
            raise ValueError("supported preview adapter plan must target canonical PDF")
        if any(
            (
                self.content_accessed,
                self.source_bytes_included,
                self.renderer_invoked,
                self.viewer_session_created,
                self.output_generated,
                self.output_persisted,
                self.external_network_allowed,
                self.wopi_session_created,
            )
        ):
            raise ValueError("preview adapter dry-run plan opened a content or execution boundary")
        return self


class SourceObjectPreviewAdapterDryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str = DEFAULT_PREVIEW_ADAPTER_ID
    preview_slot_id: str
    preview_policy_id: str
    renderer_release_gate_evidence_hash: str
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("adapter_id", "preview_slot_id", "preview_policy_id", "reason")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("preview adapter request value must not be empty")
        return stripped

    @field_validator("renderer_release_gate_evidence_hash")
    @classmethod
    def require_release_gate_hash(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("renderer release gate evidence hash must be a sha256 reference")
        return value


class SourceObjectPreviewAdapterDryRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_ADAPTER_DRY_RUN_SCHEMA_VERSION
    result_contract: str = "metadata_only_preview_adapter_wiring_dry_run"
    plan: SourceObjectPreviewAdapterDryRunPlan
    source_detail_audit_event_id: str
    audit_event_id: str
    reason_hash: str
    content_included: bool = False
    execution_performed: bool = False
    evidence_persisted_outside_audit: bool = False


class SourceObjectPreviewAdapter(Protocol):
    @property
    def descriptor(self) -> SourceObjectPreviewAdapterDescriptor: ...

    def dry_run(self, input_data: SourceObjectPreviewAdapterDryRunInput) -> SourceObjectPreviewAdapterDryRunPlan: ...


class CanonicalPdfSourceObjectPreviewAdapter:
    def __init__(self) -> None:
        self._descriptor = SourceObjectPreviewAdapterDescriptor()

    @property
    def descriptor(self) -> SourceObjectPreviewAdapterDescriptor:
        return self._descriptor

    def dry_run(self, input_data: SourceObjectPreviewAdapterDryRunInput) -> SourceObjectPreviewAdapterDryRunPlan:
        route, blocking_reasons = self._route(input_data)
        supported = route != PreviewAdapterRoute.UNSUPPORTED
        descriptor_hash = build_source_object_preview_adapter_descriptor_hash(self.descriptor)
        draft = SourceObjectPreviewAdapterDryRunPlan(
            tenant_id=input_data.tenant_id,
            source_object_id=input_data.source_object_id,
            source_version_id=input_data.source_version_id,
            source_object_type=input_data.source_object_type,
            source_mime_type=input_data.source_mime_type,
            source_manifest_hash=input_data.source_manifest_hash,
            source_content_hash=input_data.source_content_hash,
            source_acl_version=input_data.source_acl_version,
            preview_slot_id=input_data.preview_slot_id,
            preview_policy_id=input_data.preview_policy_id,
            renderer_release_gate_evidence_hash=input_data.renderer_release_gate_evidence_hash,
            adapter_id=self.descriptor.adapter_id,
            adapter_contract_version=self.descriptor.contract_version,
            adapter_descriptor_hash=descriptor_hash,
            route=route,
            target_media_type=self.descriptor.target_media_type if supported else None,
            supported=supported,
            blocking_reasons=blocking_reasons,
            production_execution_requirements=self.descriptor.security_controls,
            plan_hash="sha256:" + ("0" * 64),
        )
        return draft.model_copy(update={"plan_hash": build_source_object_preview_adapter_plan_hash(draft)})

    def _route(self, input_data: SourceObjectPreviewAdapterDryRunInput) -> tuple[PreviewAdapterRoute, tuple[str, ...]]:
        if input_data.source_object_type not in self.descriptor.supported_source_object_types:
            return PreviewAdapterRoute.UNSUPPORTED, ("source_object_type_not_supported",)
        mime_type = input_data.source_mime_type.lower()
        if mime_type in self.descriptor.direct_view_mime_types:
            return PreviewAdapterRoute.DIRECT_PDF_VIEWER, ()
        if mime_type in self.descriptor.office_to_pdf_mime_types:
            return PreviewAdapterRoute.ISOLATED_OFFICE_TO_PDF, ()
        return PreviewAdapterRoute.UNSUPPORTED, ("source_mime_type_not_supported",)


class SourceObjectPreviewAdapterRegistry:
    def __init__(
        self,
        *,
        adapters: tuple[SourceObjectPreviewAdapter, ...],
        selected_adapter_id: str,
    ) -> None:
        self._adapters: dict[str, SourceObjectPreviewAdapter] = {}
        for adapter in adapters:
            adapter_id = adapter.descriptor.adapter_id
            if adapter_id in self._adapters:
                raise ValueError(f"duplicate source object preview adapter: {adapter_id}")
            self._adapters[adapter_id] = adapter
        if selected_adapter_id not in self._adapters:
            raise ValueError("selected source object preview adapter is not registered")
        self.selected_adapter_id = selected_adapter_id

    def selected(self, *, requested_adapter_id: str) -> SourceObjectPreviewAdapter:
        if requested_adapter_id != self.selected_adapter_id:
            raise SourceObjectPreviewAdapterDryRunBlocked("requested preview adapter is not selected")
        return self._adapters[requested_adapter_id]

    def descriptors(self) -> tuple[SourceObjectPreviewAdapterDescriptor, ...]:
        return tuple(adapter.descriptor for adapter in self._adapters.values())


def build_default_source_object_preview_adapter_registry(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewAdapterRegistry:
    env = os.environ if environ is None else environ
    selected_adapter_id = env.get("SUITE_SOURCE_PREVIEW_ADAPTER_ID", DEFAULT_PREVIEW_ADAPTER_ID).strip()
    return SourceObjectPreviewAdapterRegistry(
        adapters=(CanonicalPdfSourceObjectPreviewAdapter(),),
        selected_adapter_id=selected_adapter_id,
    )


def build_source_object_preview_adapter_dry_run(
    *,
    user_context: UserContext,
    workspace_source_repository: SourceObjectRepository,
    module_registry: ModuleRegistryStore,
    knowledge_base_article_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    renderer_release_gate_store: SourceObjectPreviewRendererReleaseGateEvidenceStore,
    adapter_registry: SourceObjectPreviewAdapterRegistry,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewAdapterDryRunRequest,
    checked_at_utc: datetime | None = None,
) -> SourceObjectPreviewAdapterDryRunResponse:
    detail = build_source_object_metadata_detail_response(
        user_context=user_context,
        workspace_source_repository=workspace_source_repository,
        module_registry=module_registry,
        knowledge_base_article_service=knowledge_base_article_service,
        audit_logger=audit_logger,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
    )
    if detail.content_accessed:
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="metadata_only_repository_required",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise SourceObjectPreviewAdapterDryRunBlocked(
            "preview adapter dry-run requires a metadata-only source repository"
        )
    slot = next((candidate for candidate in detail.preview_slots if candidate.slot_id == request.preview_slot_id), None)
    if slot is None or slot.gate.policy_id != request.preview_policy_id:
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="preview_slot_or_policy_mismatch",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise SourceObjectPreviewAdapterDryRunBlocked("preview slot or policy does not match source object")

    gate = _require_current_release_gate(
        store=renderer_release_gate_store,
        tenant_id=user_context.tenant_id,
        evidence_hash=request.renderer_release_gate_evidence_hash,
        checked_at_utc=checked_at_utc or datetime.now(UTC),
        audit_logger=audit_logger,
        user_context=user_context,
        source_object_id=detail.source_object_id,
        source_version_id=detail.source_version_id,
        request=request,
        source_detail_audit_event_id=detail.audit_event_id,
    )
    try:
        adapter = adapter_registry.selected(requested_adapter_id=request.adapter_id)
    except SourceObjectPreviewAdapterDryRunBlocked:
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            request=request,
            rejection_reason="adapter_not_selected",
            source_detail_audit_event_id=detail.audit_event_id,
        )
        raise

    plan = adapter.dry_run(
        SourceObjectPreviewAdapterDryRunInput(
            tenant_id=detail.tenant_id,
            source_object_id=detail.source_object_id,
            source_version_id=detail.source_version_id,
            source_object_type=detail.source_object_type,
            source_mime_type=detail.mime_type,
            source_manifest_hash=detail.manifest_hash,
            source_content_hash=detail.content_hash,
            source_acl_version=detail.acl_version,
            preview_slot_id=slot.slot_id,
            preview_policy_id=slot.gate.policy_id,
            renderer_release_gate_evidence_hash=gate.evidence_hash,
        )
    )
    reason_hash = stable_hash(request.reason)
    event = audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_adapter_dry_run.recorded",
        source_object_ids=[detail.source_object_id],
        metadata={
            "source_object_id": detail.source_object_id,
            "source_version_id": detail.source_version_id,
            "source_object_type": detail.source_object_type.value,
            "source_mime_type": detail.mime_type,
            "source_manifest_hash": detail.manifest_hash,
            "source_content_hash": detail.content_hash,
            "source_acl_version": detail.acl_version,
            "preview_slot_id": slot.slot_id,
            "preview_policy_id": slot.gate.policy_id,
            "renderer_release_gate_evidence_hash": gate.evidence_hash,
            "adapter_id": plan.adapter_id,
            "adapter_descriptor_hash": plan.adapter_descriptor_hash,
            "route": plan.route.value,
            "supported": plan.supported,
            "blocking_reasons": list(plan.blocking_reasons),
            "plan_hash": plan.plan_hash,
            "source_detail_audit_event_id": detail.audit_event_id,
            "result_contract": "metadata_only_preview_adapter_wiring_dry_run",
            "access_checked": True,
            "release_gate_checked": True,
            "release_gate_fresh": True,
            "content_accessed": False,
            "content_included": False,
            "renderer_invoked": False,
            "viewer_session_created": False,
            "output_generated": False,
            "output_persisted": False,
            "external_network_allowed": False,
            "wopi_session_created": False,
            "reason_hash": reason_hash,
        },
    )
    return SourceObjectPreviewAdapterDryRunResponse(
        plan=plan,
        source_detail_audit_event_id=detail.audit_event_id,
        audit_event_id=event.event_id,
        reason_hash=reason_hash,
    )


def build_source_object_preview_adapter_descriptor_hash(
    descriptor: SourceObjectPreviewAdapterDescriptor,
) -> str:
    return stable_hash(canonical_json(descriptor.model_dump(mode="json")))


def build_source_object_preview_adapter_plan_hash(plan: SourceObjectPreviewAdapterDryRunPlan) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"plan_hash"})))


def _require_current_release_gate(
    *,
    store: SourceObjectPreviewRendererReleaseGateEvidenceStore,
    tenant_id: str,
    evidence_hash: str,
    checked_at_utc: datetime,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewAdapterDryRunRequest,
    source_detail_audit_event_id: str,
) -> SourceObjectPreviewRendererReleaseGateEvidence:
    try:
        gate = store.get(tenant_id=tenant_id, evidence_hash=evidence_hash)
    except KeyError as exc:
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
            rejection_reason="release_gate_not_found",
            source_detail_audit_event_id=source_detail_audit_event_id,
        )
        raise SourceObjectPreviewAdapterDryRunBlocked("preview renderer release gate was not found") from exc
    try:
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=gate,
            tenant_id=tenant_id,
            evidence_hash=evidence_hash,
        )
    except ValueError as exc:
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
            rejection_reason="release_gate_not_ready",
            source_detail_audit_event_id=source_detail_audit_event_id,
        )
        raise SourceObjectPreviewAdapterDryRunBlocked("preview renderer release gate is not ready") from exc
    if not source_object_preview_renderer_release_gate_is_current(gate=gate, checked_at_utc=checked_at_utc):
        _audit_adapter_dry_run_rejection(
            audit_logger=audit_logger,
            user_context=user_context,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
            request=request,
            rejection_reason="release_gate_stale",
            source_detail_audit_event_id=source_detail_audit_event_id,
        )
        raise SourceObjectPreviewAdapterDryRunBlocked("preview renderer release gate is stale")
    return gate


def source_object_preview_renderer_release_gate_is_current(
    *,
    gate: SourceObjectPreviewRendererReleaseGateEvidence,
    checked_at_utc: datetime,
) -> bool:
    checked_at = _aware(checked_at_utc)
    window = timedelta(hours=gate.freshness_window_hours)
    evidence_times = (
        _aware(gate.api_smoke_checked_at_utc),
        _aware(gate.recovery_drill_checked_at_utc),
        _aware(gate.evaluated_at_utc),
    )
    return all(
        evidence_time - PREVIEW_ADAPTER_CLOCK_SKEW <= checked_at <= evidence_time + window
        for evidence_time in evidence_times
    )


def _audit_adapter_dry_run_rejection(
    *,
    audit_logger: InMemoryAuditLogger,
    user_context: UserContext,
    source_object_id: str,
    source_version_id: str,
    request: SourceObjectPreviewAdapterDryRunRequest,
    rejection_reason: str,
    source_detail_audit_event_id: str,
) -> None:
    audit_logger.record(
        user_context=user_context,
        event_type="source_object.preview_adapter_dry_run.rejected",
        source_object_ids=[source_object_id],
        metadata={
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "adapter_id": request.adapter_id,
            "preview_slot_id": request.preview_slot_id,
            "preview_policy_id": request.preview_policy_id,
            "renderer_release_gate_evidence_hash": request.renderer_release_gate_evidence_hash,
            "source_detail_audit_event_id": source_detail_audit_event_id,
            "result_contract": "metadata_only_preview_adapter_wiring_dry_run",
            "rejection_reason": rejection_reason,
            "content_accessed": False,
            "content_included": False,
            "renderer_invoked": False,
            "viewer_session_created": False,
            "output_generated": False,
            "output_persisted": False,
            "external_network_allowed": False,
            "wopi_session_created": False,
            "reason_hash": stable_hash(request.reason),
        },
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("preview adapter evidence timestamps must include a timezone")
    return value.astimezone(UTC)
