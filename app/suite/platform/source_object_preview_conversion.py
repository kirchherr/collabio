from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.storage.source_objects import (
    InMemorySourceObjectWriteReceiptStore,
    PgSourceObjectWriteReceiptStore,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteReceipt,
    SourceObjectWriteReceiptStore,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
)

PREVIEW_CONVERSION_EXECUTION_GATE_SCHEMA_VERSION = "source_object_preview_conversion_execution_gate.v1"
PREVIEW_CONVERSION_PREFLIGHT_SCHEMA_VERSION = "source_object_preview_conversion_source_preflight.v1"
PREVIEW_CONVERSION_COMMAND_SCHEMA_VERSION = "source_object_preview_conversion_command.v1"
PREVIEW_CONVERSION_RESULT_SCHEMA_VERSION = "source_object_preview_conversion_result.v1"
DERIVED_PREVIEW_RECEIPT_SCHEMA_VERSION = "source_object_derived_preview_receipt.v1"
PREVIEW_CONVERSION_JOB_EVIDENCE_SCHEMA_VERSION = "source_object_preview_conversion_job_evidence.v1"
PREVIEW_CONVERSION_GATE_MAX_CLOCK_SKEW = timedelta(minutes=5)
ZERO_HASH = "sha256:" + ("0" * 64)
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
IMAGE_DIGEST_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/:+-]*@sha256:[a-f0-9]{64}$")
SAFE_JOB_FILENAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ALLOWED_SANDBOX_RUNTIME_CLASSES = frozenset({"runsc", "kata-clh", "kata-qemu", "firecracker"})
ALLOWED_CONVERSION_ROUTES = frozenset({"isolated_office_to_pdf", "direct_pdf_viewer"})
MIME_TYPE_INPUT_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/rtf": ".rtf",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}


class PreviewConversionBlocked(ValueError):
    pass


class PreviewConversionGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class PreviewConversionResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_input_bytes: int = Field(default=64 * 1024 * 1024, ge=1, le=512 * 1024 * 1024)
    max_output_bytes: int = Field(default=128 * 1024 * 1024, ge=1, le=512 * 1024 * 1024)
    max_page_count: int = Field(default=1000, ge=1, le=10000)
    wallclock_timeout_seconds: int = Field(default=120, ge=1, le=900)
    cpu_limit: float = Field(default=2.0, gt=0, le=8)
    memory_limit_megabytes: int = Field(default=1024, ge=128, le=8192)
    process_limit: int = Field(default=128, ge=16, le=512)
    temporary_storage_megabytes: int = Field(default=512, ge=64, le=4096)


class PreviewConversionExecutionGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CONVERSION_EXECUTION_GATE_SCHEMA_VERSION
    tenant_id: str
    worker_image_ref: str
    worker_image_digest: str
    sandbox_runtime_class: str
    sandbox_runtime_evidence_hash: str
    malware_scanner_profile_ref: str
    malware_scanner_evidence_hash: str
    cdr_profile_ref: str
    cdr_evidence_hash: str
    pdf_validator_profile_ref: str
    pdf_validator_evidence_hash: str
    font_baseline_hash: str
    backup_restore_evidence_hash: str
    viewer_origin: str
    viewer_csp_evidence_hash: str
    resource_limits: PreviewConversionResourceLimits
    image_digest_pinned: bool
    stronger_sandbox_attested: bool
    network_egress_denied: bool
    read_only_root_filesystem: bool
    non_root_user: bool
    all_capabilities_dropped: bool
    no_new_privileges: bool
    ephemeral_workspace: bool
    malware_cdr_ready: bool
    pdf_revalidation_ready: bool
    font_baseline_ready: bool
    restore_ready: bool
    separate_viewer_origin_ready: bool
    strict_viewer_csp_ready: bool
    evaluated_at_utc: datetime
    expires_at_utc: datetime
    blocking_reasons: tuple[str, ...]
    gate_status: PreviewConversionGateStatus
    evidence_hash: str

    @field_validator("tenant_id", "sandbox_runtime_class")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("preview conversion gate values must not be empty")
        return normalized

    @field_validator("worker_image_ref")
    @classmethod
    def require_digest_pinned_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not IMAGE_DIGEST_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion worker image must be pinned by sha256 digest")
        return normalized

    @field_validator(
        "worker_image_digest",
        "sandbox_runtime_evidence_hash",
        "malware_scanner_evidence_hash",
        "cdr_evidence_hash",
        "pdf_validator_evidence_hash",
        "font_baseline_hash",
        "backup_restore_evidence_hash",
        "viewer_csp_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion gate hashes must be sha256 references")
        return value

    @field_validator("malware_scanner_profile_ref", "cdr_profile_ref", "pdf_validator_profile_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion profiles must be namespaced references")
        return normalized

    @field_validator("viewer_origin")
    @classmethod
    def require_https_origin(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("preview viewer origin must be an HTTPS origin without path")
        if parsed.params or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("preview viewer origin must not contain credentials, query, or fragment")
        return normalized

    @model_validator(mode="after")
    def require_consistent_gate(self) -> PreviewConversionExecutionGateEvidence:
        image_digest = self.worker_image_ref.rsplit("@", maxsplit=1)[1]
        if image_digest != self.worker_image_digest:
            raise ValueError("preview conversion image digest does not match image reference")
        if self.sandbox_runtime_class not in ALLOWED_SANDBOX_RUNTIME_CLASSES:
            raise ValueError("preview conversion sandbox runtime is not allowlisted")
        if self.expires_at_utc <= self.evaluated_at_utc:
            raise ValueError("preview conversion gate must expire after evaluation")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ValueError("preview conversion gate blocking reasons must be unique")
        ready = not self.blocking_reasons and all(_gate_control_values(self))
        expected_status = PreviewConversionGateStatus.READY if ready else PreviewConversionGateStatus.BLOCKED
        if self.gate_status != expected_status:
            raise ValueError("preview conversion gate status is inconsistent")
        return self


class PreviewConversionSourcePreflightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CONVERSION_PREFLIGHT_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_manifest_hash: str
    source_content_hash: str
    scanner_profile_ref: str
    scanner_signature_set_hash: str
    cdr_profile_ref: str
    checked_at_utc: datetime
    expires_at_utc: datetime
    content_hash_verified: bool
    malware_detected: bool
    password_protected: bool
    active_content_execution_required: bool
    external_resource_loading_required: bool
    cdr_preflight_passed: bool
    conversion_allowed: bool
    blocking_reasons: tuple[str, ...]
    evidence_hash: str

    @field_validator("tenant_id", "source_object_id", "source_version_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("preview conversion preflight values must not be empty")
        return normalized

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "scanner_signature_set_hash",
        "evidence_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion preflight hashes must be sha256 references")
        return value

    @field_validator("scanner_profile_ref", "cdr_profile_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion preflight profiles must be namespaced references")
        return normalized

    @model_validator(mode="after")
    def require_consistent_preflight(self) -> PreviewConversionSourcePreflightEvidence:
        if self.expires_at_utc <= self.checked_at_utc:
            raise ValueError("preview conversion preflight must expire after its check")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ValueError("preview conversion preflight blocking reasons must be unique")
        allowed = (
            self.content_hash_verified
            and not self.malware_detected
            and not self.password_protected
            and not self.active_content_execution_required
            and not self.external_resource_loading_required
            and self.cdr_preflight_passed
            and not self.blocking_reasons
        )
        if self.conversion_allowed != allowed:
            raise ValueError("preview conversion preflight state is inconsistent")
        return self


class PreviewConversionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CONVERSION_COMMAND_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_object_type: SourceObjectType
    source_mime_type: str
    source_manifest_hash: str
    source_content_hash: str
    source_content_byte_length: int = Field(ge=1)
    source_acl_version: int = Field(ge=1)
    preview_slot_id: str
    preview_policy_id: str
    adapter_id: str
    adapter_descriptor_hash: str
    adapter_plan_hash: str
    conversion_route: str
    production_admission_gate_hash: str | None = None
    renderer_release_gate_evidence_hash: str
    execution_gate_evidence_hash: str
    source_preflight_evidence_hash: str
    worker_image_ref: str
    resource_limits: PreviewConversionResourceLimits
    input_filename: str
    output_filename: str = "preview.pdf"
    requested_by: str
    requested_at_utc: datetime
    reason_hash: str
    idempotency_key_hash: str
    command_hash: str

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "adapter_descriptor_hash",
        "adapter_plan_hash",
        "renderer_release_gate_evidence_hash",
        "execution_gate_evidence_hash",
        "source_preflight_evidence_hash",
        "reason_hash",
        "idempotency_key_hash",
        "command_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion command hashes must be sha256 references")
        return value

    @field_validator("production_admission_gate_hash")
    @classmethod
    def require_optional_production_admission_hash(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion production admission hash must be a sha256 reference")
        return value

    @field_validator("worker_image_ref")
    @classmethod
    def require_digest_pinned_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not IMAGE_DIGEST_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion command image must be digest pinned")
        return normalized

    @field_validator("input_filename", "output_filename")
    @classmethod
    def require_safe_filename(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SAFE_JOB_FILENAME_PATTERN.fullmatch(normalized) or "/" in normalized or "\\" in normalized:
            raise ValueError("preview conversion filenames must be safe basename values")
        return normalized

    @model_validator(mode="after")
    def require_closed_command(self) -> PreviewConversionCommand:
        if self.source_object_type != SourceObjectType.DOCUMENT:
            raise ValueError("first preview conversion command supports document SourceObjects only")
        if self.conversion_route not in ALLOWED_CONVERSION_ROUTES:
            raise ValueError("preview conversion route is not allowlisted")
        if self.output_filename != "preview.pdf":
            raise ValueError("preview conversion output filename is fixed")
        if self.source_content_byte_length > self.resource_limits.max_input_bytes:
            raise ValueError("preview conversion source exceeds input limit")
        return self


class PreviewConversionWorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CONVERSION_RESULT_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_manifest_hash: str
    source_content_hash: str
    command_hash: str
    execution_gate_evidence_hash: str
    source_preflight_evidence_hash: str
    production_admission_gate_hash: str | None = None
    worker_image_ref: str
    sandbox_runtime_class: str
    converter_engine: str = "libreoffice"
    converter_version: str
    pdf_validator_engine: str = "qpdf+pdfinfo"
    pdf_validator_version: str
    font_baseline_hash: str
    output_mime_type: str = "application/pdf"
    output_content_hash: str
    output_content_byte_length: int = Field(ge=1)
    page_count: int = Field(ge=1)
    source_hash_verified: bool
    output_hash_verified: bool
    qpdf_validation_passed: bool
    pdfinfo_validation_passed: bool
    active_pdf_content_absent: bool
    external_network_used: bool = False
    source_content_in_result: bool = False
    stdout_in_result: bool = False
    stderr_in_result: bool = False
    temporary_workspace_destroyed: bool
    completed_at_utc: datetime
    result_hash: str

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "command_hash",
        "execution_gate_evidence_hash",
        "source_preflight_evidence_hash",
        "font_baseline_hash",
        "output_content_hash",
        "result_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion result hashes must be sha256 references")
        return value
    @field_validator("production_admission_gate_hash")
    @classmethod
    def require_optional_production_admission_hash(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion result production admission hash must be a sha256 reference")
        return value


    @model_validator(mode="after")
    def require_safe_result(self) -> PreviewConversionWorkerResult:
        checks = (
            self.source_hash_verified,
            self.output_hash_verified,
            self.qpdf_validation_passed,
            self.pdfinfo_validation_passed,
            self.active_pdf_content_absent,
            self.temporary_workspace_destroyed,
        )
        forbidden = (
            self.external_network_used,
            self.source_content_in_result,
            self.stdout_in_result,
            self.stderr_in_result,
        )
        if not all(checks) or any(forbidden):
            raise ValueError("preview conversion result did not preserve the sandbox contract")
        if self.output_mime_type != "application/pdf":
            raise ValueError("preview conversion output must be PDF")
        return self


class PreviewConversionWorkerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: PreviewConversionCommand
    execution_gate: PreviewConversionExecutionGateEvidence
    source_preflight: PreviewConversionSourcePreflightEvidence


class PreviewConversionJobEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PREVIEW_CONVERSION_JOB_EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    derived_object_id: str
    derived_version_id: str
    derived_preview_receipt_hash: str
    source_object_write_receipt_hash: str
    command_hash: str
    source_preflight_evidence_hash: str
    result_hash: str
    execution_gate_evidence_hash: str
    worker_image_ref: str
    command: PreviewConversionCommand
    source_preflight: PreviewConversionSourcePreflightEvidence
    result: PreviewConversionWorkerResult
    completed_at_utc: datetime
    source_content_in_evidence: bool = False
    output_content_in_evidence: bool = False
    job_evidence_hash: str

    @field_validator(
        "derived_preview_receipt_hash",
        "source_object_write_receipt_hash",
        "command_hash",
        "source_preflight_evidence_hash",
        "result_hash",
        "execution_gate_evidence_hash",
        "job_evidence_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion job evidence hashes must be sha256 references")
        return value

    @field_validator("worker_image_ref")
    @classmethod
    def require_digest_pinned_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not IMAGE_DIGEST_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion job image must be digest pinned")
        return normalized

    @model_validator(mode="after")
    def require_consistent_job_evidence(self) -> PreviewConversionJobEvidence:
        bindings = (
            self.command.tenant_id == self.tenant_id,
            self.source_preflight.tenant_id == self.tenant_id,
            self.result.tenant_id == self.tenant_id,
            self.command.source_object_id == self.source_object_id,
            self.source_preflight.source_object_id == self.source_object_id,
            self.result.source_object_id == self.source_object_id,
            self.command.source_version_id == self.source_version_id,
            self.source_preflight.source_version_id == self.source_version_id,
            self.result.source_version_id == self.source_version_id,
            self.command.command_hash == self.command_hash,
            self.source_preflight.evidence_hash == self.source_preflight_evidence_hash,
            self.result.result_hash == self.result_hash,
            self.command.execution_gate_evidence_hash == self.execution_gate_evidence_hash,
            self.result.execution_gate_evidence_hash == self.execution_gate_evidence_hash,
            self.command.source_preflight_evidence_hash == self.source_preflight_evidence_hash,
            self.result.source_preflight_evidence_hash == self.source_preflight_evidence_hash,
            self.command.worker_image_ref == self.worker_image_ref,
            self.result.worker_image_ref == self.worker_image_ref,
            self.result.command_hash == self.command_hash,
            self.command.production_admission_gate_hash == self.result.production_admission_gate_hash,
        )
        if not all(bindings):
            raise ValueError("preview conversion job evidence lineage is inconsistent")
        if self.result.completed_at_utc != self.completed_at_utc:
            raise ValueError("preview conversion job completion timestamp mismatch")
        if self.source_content_in_evidence or self.output_content_in_evidence:
            raise ValueError("preview conversion job evidence must not contain source or output content")
        if build_preview_conversion_command_hash(self.command) != self.command_hash:
            raise ValueError("preview conversion job command hash is invalid")
        if build_preview_conversion_source_preflight_hash(self.source_preflight) != self.source_preflight_evidence_hash:
            raise ValueError("preview conversion job preflight hash is invalid")
        if build_preview_conversion_result_hash(self.result) != self.result_hash:
            raise ValueError("preview conversion job result hash is invalid")
        return self


class DerivedPreviewReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = DERIVED_PREVIEW_RECEIPT_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    source_manifest_hash: str
    source_content_hash: str
    source_acl_version: int = Field(ge=1)
    derived_object_id: str
    derived_version_id: str
    derived_manifest_hash: str
    derived_content_hash: str
    derived_content_byte_length: int = Field(ge=1)
    derived_mime_type: str = "application/pdf"
    command_hash: str
    result_hash: str
    execution_gate_evidence_hash: str
    source_preflight_evidence_hash: str
    worker_image_ref: str
    source_classification_inherited: bool
    source_acl_inherited: bool
    source_retention_inherited: bool
    source_legal_hold_inherited: bool
    source_lifecycle_inherited: bool
    source_version_lineage_bound: bool
    output_revalidated: bool
    source_content_in_receipt: bool = False
    output_content_in_receipt: bool = False
    audit_event_id: str
    created_at_utc: datetime
    receipt_hash: str

    @field_validator(
        "source_manifest_hash",
        "source_content_hash",
        "derived_manifest_hash",
        "derived_content_hash",
        "command_hash",
        "result_hash",
        "execution_gate_evidence_hash",
        "source_preflight_evidence_hash",
        "receipt_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("derived preview receipt hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_inherited_controls(self) -> DerivedPreviewReceipt:
        inherited = (
            self.source_classification_inherited,
            self.source_acl_inherited,
            self.source_retention_inherited,
            self.source_legal_hold_inherited,
            self.source_lifecycle_inherited,
            self.source_version_lineage_bound,
            self.output_revalidated,
        )
        if not all(inherited) or self.source_content_in_receipt or self.output_content_in_receipt:
            raise ValueError("derived preview receipt did not preserve source controls")
        if self.derived_mime_type != "application/pdf":
            raise ValueError("derived preview receipt must describe a PDF")
        return self


class DerivedPreviewArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    record: SourceObjectRecord
    source_object_write_receipt: SourceObjectWriteReceipt
    derived_preview_receipt: DerivedPreviewReceipt
    job_evidence: PreviewConversionJobEvidence


class PreviewConversionExecutionGateStore(Protocol):
    def append(
        self,
        evidence: PreviewConversionExecutionGateEvidence,
    ) -> PreviewConversionExecutionGateEvidence: ...

    def get(self, *, tenant_id: str, evidence_hash: str) -> PreviewConversionExecutionGateEvidence: ...

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionExecutionGateEvidence]: ...


class DerivedPreviewReceiptStore(Protocol):
    def append(self, receipt: DerivedPreviewReceipt) -> DerivedPreviewReceipt: ...

    def get(self, *, tenant_id: str, receipt_hash: str) -> DerivedPreviewReceipt: ...

    def list_receipts(self, *, tenant_id: str) -> Sequence[DerivedPreviewReceipt]: ...


class PreviewConversionJobEvidenceStore(Protocol):
    def append(self, evidence: PreviewConversionJobEvidence) -> PreviewConversionJobEvidence: ...

    def get(self, *, tenant_id: str, job_evidence_hash: str) -> PreviewConversionJobEvidence: ...

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionJobEvidence]: ...


class InMemoryPreviewConversionExecutionGateStore:
    def __init__(self, evidences: Sequence[PreviewConversionExecutionGateEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], PreviewConversionExecutionGateEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(
        self,
        evidence: PreviewConversionExecutionGateEvidence,
    ) -> PreviewConversionExecutionGateEvidence:
        _require_execution_gate_hash(evidence)
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("preview conversion execution gate already exists")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> PreviewConversionExecutionGateEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("preview conversion execution gate not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionExecutionGateEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class InMemoryDerivedPreviewReceiptStore:
    def __init__(self, receipts: Sequence[DerivedPreviewReceipt] = ()) -> None:
        self._receipts: dict[tuple[str, str], DerivedPreviewReceipt] = {}
        for receipt in receipts:
            self.append(receipt)

    def append(self, receipt: DerivedPreviewReceipt) -> DerivedPreviewReceipt:
        _require_derived_preview_receipt_hash(receipt)
        key = (receipt.tenant_id, receipt.receipt_hash)
        if key in self._receipts:
            raise ValueError("derived preview receipt already exists")
        self._receipts[key] = receipt
        return receipt

    def get(self, *, tenant_id: str, receipt_hash: str) -> DerivedPreviewReceipt:
        try:
            return self._receipts[(tenant_id, receipt_hash)]
        except KeyError as exc:
            raise KeyError("derived preview receipt not found") from exc

    def list_receipts(self, *, tenant_id: str) -> Sequence[DerivedPreviewReceipt]:
        return tuple(
            receipt for (stored_tenant_id, _), receipt in self._receipts.items() if stored_tenant_id == tenant_id
        )


class InMemoryPreviewConversionJobEvidenceStore:
    def __init__(self, evidences: Sequence[PreviewConversionJobEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], PreviewConversionJobEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(self, evidence: PreviewConversionJobEvidence) -> PreviewConversionJobEvidence:
        _require_job_evidence_hash(evidence)
        key = (evidence.tenant_id, evidence.job_evidence_hash)
        if key in self._evidences:
            raise ValueError("preview conversion job evidence already exists")
        if any(
            existing.derived_preview_receipt_hash == evidence.derived_preview_receipt_hash
            for (tenant_id, _), existing in self._evidences.items()
            if tenant_id == evidence.tenant_id
        ):
            raise ValueError("derived preview receipt already has job evidence")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, job_evidence_hash: str) -> PreviewConversionJobEvidence:
        try:
            return self._evidences[(tenant_id, job_evidence_hash)]
        except KeyError as exc:
            raise KeyError("preview conversion job evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionJobEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class PgPreviewConversionExecutionGateStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(
        self,
        evidence: PreviewConversionExecutionGateEvidence,
    ) -> PreviewConversionExecutionGateEvidence:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                _set_tenant(connection, evidence.tenant_id)
                self.append_in_transaction(connection, evidence)
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("preview conversion execution gate already exists") from exc
        return evidence

    def append_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        evidence: PreviewConversionExecutionGateEvidence,
    ) -> PreviewConversionExecutionGateEvidence:
        _require_execution_gate_hash(evidence)
        connection.execute(
            """
            INSERT INTO collabio.source_object_preview_conversion_execution_gates (
                tenant_id, evidence_hash, gate_status, worker_image_ref,
                sandbox_runtime_class, evaluated_at_utc, expires_at_utc, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                evidence.tenant_id,
                evidence.evidence_hash,
                evidence.gate_status.value,
                evidence.worker_image_ref,
                evidence.sandbox_runtime_class,
                evidence.evaluated_at_utc,
                evidence.expires_at_utc,
                Jsonb(evidence.model_dump(mode="json")),
            ),
        )
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> PreviewConversionExecutionGateEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT evidence
                FROM collabio.source_object_preview_conversion_execution_gates
                WHERE tenant_id = %s AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("preview conversion execution gate not found")
        evidence = PreviewConversionExecutionGateEvidence.model_validate(row[0])
        _require_execution_gate_hash(evidence)
        return evidence

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionExecutionGateEvidence]:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT evidence
                FROM collabio.source_object_preview_conversion_execution_gates
                WHERE tenant_id = %s
                ORDER BY evaluated_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        evidences = tuple(PreviewConversionExecutionGateEvidence.model_validate(row[0]) for row in rows)
        for evidence in evidences:
            _require_execution_gate_hash(evidence)
        return evidences


class PgDerivedPreviewReceiptStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, receipt: DerivedPreviewReceipt) -> DerivedPreviewReceipt:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                _set_tenant(connection, receipt.tenant_id)
                self.append_in_transaction(connection, receipt)
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("derived preview receipt already exists") from exc
        return receipt

    def append_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        receipt: DerivedPreviewReceipt,
    ) -> DerivedPreviewReceipt:
        _require_derived_preview_receipt_hash(receipt)
        connection.execute(
            """
            INSERT INTO collabio.source_object_derived_preview_receipts (
                tenant_id, source_object_id, source_version_id, derived_object_id,
                derived_version_id, command_hash, result_hash, execution_gate_evidence_hash,
                source_preflight_evidence_hash, worker_image_ref, created_at_utc,
                receipt_hash, receipt
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt.tenant_id,
                receipt.source_object_id,
                receipt.source_version_id,
                receipt.derived_object_id,
                receipt.derived_version_id,
                receipt.command_hash,
                receipt.result_hash,
                receipt.execution_gate_evidence_hash,
                receipt.source_preflight_evidence_hash,
                receipt.worker_image_ref,
                receipt.created_at_utc,
                receipt.receipt_hash,
                Jsonb(receipt.model_dump(mode="json")),
            ),
        )
        return receipt

    def get(self, *, tenant_id: str, receipt_hash: str) -> DerivedPreviewReceipt:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT receipt
                FROM collabio.source_object_derived_preview_receipts
                WHERE tenant_id = %s AND receipt_hash = %s
                """,
                (tenant_id, receipt_hash),
            ).fetchone()
        if row is None:
            raise KeyError("derived preview receipt not found")
        receipt = DerivedPreviewReceipt.model_validate(row[0])
        _require_derived_preview_receipt_hash(receipt)
        return receipt

    def list_receipts(self, *, tenant_id: str) -> Sequence[DerivedPreviewReceipt]:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT receipt
                FROM collabio.source_object_derived_preview_receipts
                WHERE tenant_id = %s
                ORDER BY created_at_utc, receipt_hash
                """,
                (tenant_id,),
            ).fetchall()
        receipts = tuple(DerivedPreviewReceipt.model_validate(row[0]) for row in rows)
        for receipt in receipts:
            _require_derived_preview_receipt_hash(receipt)
        return receipts


class PgPreviewConversionJobEvidenceStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, evidence: PreviewConversionJobEvidence) -> PreviewConversionJobEvidence:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                _set_tenant(connection, evidence.tenant_id)
                self.append_in_transaction(connection, evidence)
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("preview conversion job evidence already exists") from exc
        return evidence

    def append_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        evidence: PreviewConversionJobEvidence,
    ) -> PreviewConversionJobEvidence:
        _require_job_evidence_hash(evidence)
        connection.execute(
            """
            INSERT INTO collabio.source_object_preview_conversion_job_evidence (
                tenant_id, job_evidence_hash, derived_preview_receipt_hash,
                source_object_write_receipt_hash, source_object_id, source_version_id,
                derived_object_id, derived_version_id, command_hash,
                source_preflight_evidence_hash, result_hash, execution_gate_evidence_hash,
                completed_at_utc, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                evidence.tenant_id,
                evidence.job_evidence_hash,
                evidence.derived_preview_receipt_hash,
                evidence.source_object_write_receipt_hash,
                evidence.source_object_id,
                evidence.source_version_id,
                evidence.derived_object_id,
                evidence.derived_version_id,
                evidence.command_hash,
                evidence.source_preflight_evidence_hash,
                evidence.result_hash,
                evidence.execution_gate_evidence_hash,
                evidence.completed_at_utc,
                Jsonb(evidence.model_dump(mode="json")),
            ),
        )
        return evidence

    def get(self, *, tenant_id: str, job_evidence_hash: str) -> PreviewConversionJobEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT evidence
                FROM collabio.source_object_preview_conversion_job_evidence
                WHERE tenant_id = %s AND job_evidence_hash = %s
                """,
                (tenant_id, job_evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("preview conversion job evidence not found")
        evidence = PreviewConversionJobEvidence.model_validate(row[0])
        _require_job_evidence_hash(evidence)
        return evidence

    def list_evidence(self, *, tenant_id: str) -> Sequence[PreviewConversionJobEvidence]:
        with psycopg.connect(self.database_dsn) as connection:
            _set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT evidence
                FROM collabio.source_object_preview_conversion_job_evidence
                WHERE tenant_id = %s
                ORDER BY completed_at_utc, job_evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        evidences = tuple(PreviewConversionJobEvidence.model_validate(row[0]) for row in rows)
        for evidence in evidences:
            _require_job_evidence_hash(evidence)
        return evidences


class DerivedPreviewWriteUnitOfWork:
    def __init__(
        self,
        *,
        source_repository: SourceObjectRepository,
        source_object_write_receipt_store: SourceObjectWriteReceiptStore,
        derived_preview_receipt_store: DerivedPreviewReceiptStore,
        job_evidence_store: PreviewConversionJobEvidenceStore,
    ) -> None:
        self.source_repository = source_repository
        self.source_object_write_receipt_store = source_object_write_receipt_store
        self.derived_preview_receipt_store = derived_preview_receipt_store
        self.job_evidence_store = job_evidence_store

    def commit(self, artifact: DerivedPreviewArtifact) -> DerivedPreviewArtifact:
        self.source_object_write_receipt_store.append(artifact.source_object_write_receipt)
        add_with_receipt = getattr(self.source_repository, "add_with_receipt", None)
        if callable(add_with_receipt):
            add_with_receipt(
                record=artifact.record,
                source_object_write_receipt_hash=artifact.source_object_write_receipt.receipt_hash,
            )
        else:
            self.source_repository.add(artifact.record)
        self.derived_preview_receipt_store.append(artifact.derived_preview_receipt)
        self.job_evidence_store.append(artifact.job_evidence)
        return artifact


class PostgresDerivedPreviewWriteUnitOfWork:
    def __init__(
        self,
        *,
        database_dsn: str,
        source_repository: Any,
        source_object_write_receipt_store: PgSourceObjectWriteReceiptStore,
        derived_preview_receipt_store: PgDerivedPreviewReceiptStore,
        job_evidence_store: PgPreviewConversionJobEvidenceStore,
    ) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn
        self.source_repository = source_repository
        self.source_object_write_receipt_store = source_object_write_receipt_store
        self.derived_preview_receipt_store = derived_preview_receipt_store
        self.job_evidence_store = job_evidence_store

    def commit(self, artifact: DerivedPreviewArtifact) -> DerivedPreviewArtifact:
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                _set_tenant(connection, artifact.record.metadata.tenant_id)
                self.source_object_write_receipt_store.append_in_transaction(
                    connection,
                    artifact.source_object_write_receipt,
                )
                self.source_repository.add_with_receipt_in_transaction(
                    connection,
                    record=artifact.record,
                    source_object_write_receipt_hash=artifact.source_object_write_receipt.receipt_hash,
                )
                self.derived_preview_receipt_store.append_in_transaction(
                    connection,
                    artifact.derived_preview_receipt,
                )
                self.job_evidence_store.append_in_transaction(connection, artifact.job_evidence)
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("derived preview write conflicts with existing evidence") from exc
        return artifact


def build_preview_conversion_execution_gate(
    *,
    tenant_id: str,
    worker_image_ref: str,
    sandbox_runtime_class: str,
    sandbox_runtime_evidence_hash: str,
    malware_scanner_profile_ref: str,
    malware_scanner_evidence_hash: str,
    cdr_profile_ref: str,
    cdr_evidence_hash: str,
    pdf_validator_profile_ref: str,
    pdf_validator_evidence_hash: str,
    font_baseline_hash: str,
    backup_restore_evidence_hash: str,
    viewer_origin: str,
    viewer_csp_evidence_hash: str,
    resource_limits: PreviewConversionResourceLimits | None = None,
    evaluated_at_utc: datetime | None = None,
    validity_hours: int = 24,
    image_digest_pinned: bool = True,
    stronger_sandbox_attested: bool = True,
    network_egress_denied: bool = True,
    read_only_root_filesystem: bool = True,
    non_root_user: bool = True,
    all_capabilities_dropped: bool = True,
    no_new_privileges: bool = True,
    ephemeral_workspace: bool = True,
    malware_cdr_ready: bool = True,
    pdf_revalidation_ready: bool = True,
    font_baseline_ready: bool = True,
    restore_ready: bool = True,
    separate_viewer_origin_ready: bool = True,
    strict_viewer_csp_ready: bool = True,
) -> PreviewConversionExecutionGateEvidence:
    evaluated_at = _aware(evaluated_at_utc or datetime.now(UTC))
    controls = {
        "image_digest_pinned": image_digest_pinned,
        "stronger_sandbox_attested": stronger_sandbox_attested,
        "network_egress_denied": network_egress_denied,
        "read_only_root_filesystem": read_only_root_filesystem,
        "non_root_user": non_root_user,
        "all_capabilities_dropped": all_capabilities_dropped,
        "no_new_privileges": no_new_privileges,
        "ephemeral_workspace": ephemeral_workspace,
        "malware_cdr_ready": malware_cdr_ready,
        "pdf_revalidation_ready": pdf_revalidation_ready,
        "font_baseline_ready": font_baseline_ready,
        "restore_ready": restore_ready,
        "separate_viewer_origin_ready": separate_viewer_origin_ready,
        "strict_viewer_csp_ready": strict_viewer_csp_ready,
    }
    blocking_reasons = tuple(f"{name}_required" for name, ready in controls.items() if not ready)
    if sandbox_runtime_class not in ALLOWED_SANDBOX_RUNTIME_CLASSES:
        blocking_reasons = (*blocking_reasons, "stronger_sandbox_runtime_not_allowlisted")
    worker_image_digest = worker_image_ref.rsplit("@", maxsplit=1)[-1]
    draft = PreviewConversionExecutionGateEvidence(
        tenant_id=tenant_id,
        worker_image_ref=worker_image_ref,
        worker_image_digest=worker_image_digest,
        sandbox_runtime_class=sandbox_runtime_class,
        sandbox_runtime_evidence_hash=sandbox_runtime_evidence_hash,
        malware_scanner_profile_ref=malware_scanner_profile_ref,
        malware_scanner_evidence_hash=malware_scanner_evidence_hash,
        cdr_profile_ref=cdr_profile_ref,
        cdr_evidence_hash=cdr_evidence_hash,
        pdf_validator_profile_ref=pdf_validator_profile_ref,
        pdf_validator_evidence_hash=pdf_validator_evidence_hash,
        font_baseline_hash=font_baseline_hash,
        backup_restore_evidence_hash=backup_restore_evidence_hash,
        viewer_origin=viewer_origin,
        viewer_csp_evidence_hash=viewer_csp_evidence_hash,
        resource_limits=resource_limits or PreviewConversionResourceLimits(),
        image_digest_pinned=image_digest_pinned,
        stronger_sandbox_attested=stronger_sandbox_attested,
        network_egress_denied=network_egress_denied,
        read_only_root_filesystem=read_only_root_filesystem,
        non_root_user=non_root_user,
        all_capabilities_dropped=all_capabilities_dropped,
        no_new_privileges=no_new_privileges,
        ephemeral_workspace=ephemeral_workspace,
        malware_cdr_ready=malware_cdr_ready,
        pdf_revalidation_ready=pdf_revalidation_ready,
        font_baseline_ready=font_baseline_ready,
        restore_ready=restore_ready,
        separate_viewer_origin_ready=separate_viewer_origin_ready,
        strict_viewer_csp_ready=strict_viewer_csp_ready,
        evaluated_at_utc=evaluated_at,
        expires_at_utc=evaluated_at + timedelta(hours=validity_hours),
        blocking_reasons=blocking_reasons,
        gate_status=(
            PreviewConversionGateStatus.READY if not blocking_reasons else PreviewConversionGateStatus.BLOCKED
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_preview_conversion_execution_gate_hash(draft)})


def build_preview_conversion_source_preflight(
    *,
    source_metadata: SourceObjectMetadata,
    scanner_profile_ref: str,
    scanner_signature_set_hash: str,
    cdr_profile_ref: str,
    checked_at_utc: datetime | None = None,
    validity_hours: int = 1,
    content_hash_verified: bool = True,
    malware_detected: bool = False,
    password_protected: bool = False,
    active_content_execution_required: bool = False,
    external_resource_loading_required: bool = False,
    cdr_preflight_passed: bool = True,
) -> PreviewConversionSourcePreflightEvidence:
    checked_at = _aware(checked_at_utc or datetime.now(UTC))
    blocking_reasons: list[str] = []
    if not content_hash_verified:
        blocking_reasons.append("source_content_hash_not_verified")
    if malware_detected:
        blocking_reasons.append("malware_detected")
    if password_protected:
        blocking_reasons.append("password_protected_source_not_supported")
    if active_content_execution_required:
        blocking_reasons.append("active_content_execution_required")
    if external_resource_loading_required:
        blocking_reasons.append("external_resource_loading_required")
    if not cdr_preflight_passed:
        blocking_reasons.append("cdr_preflight_not_passed")
    draft = PreviewConversionSourcePreflightEvidence(
        tenant_id=source_metadata.tenant_id,
        source_object_id=source_metadata.object_id,
        source_version_id=source_metadata.version_id,
        source_manifest_hash=source_metadata.manifest_hash,
        source_content_hash=source_metadata.content_hash,
        scanner_profile_ref=scanner_profile_ref,
        scanner_signature_set_hash=scanner_signature_set_hash,
        cdr_profile_ref=cdr_profile_ref,
        checked_at_utc=checked_at,
        expires_at_utc=checked_at + timedelta(hours=validity_hours),
        content_hash_verified=content_hash_verified,
        malware_detected=malware_detected,
        password_protected=password_protected,
        active_content_execution_required=active_content_execution_required,
        external_resource_loading_required=external_resource_loading_required,
        cdr_preflight_passed=cdr_preflight_passed,
        conversion_allowed=not blocking_reasons,
        blocking_reasons=tuple(blocking_reasons),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_preview_conversion_source_preflight_hash(draft)})


def build_preview_conversion_command(
    *,
    source_metadata: SourceObjectMetadata,
    adapter_id: str,
    adapter_descriptor_hash: str,
    adapter_plan_hash: str,
    conversion_route: str,
    preview_slot_id: str,
    preview_policy_id: str,
    renderer_release_gate_evidence_hash: str,
    execution_gate: PreviewConversionExecutionGateEvidence,
    source_preflight: PreviewConversionSourcePreflightEvidence,
    requested_by: str,
    reason: str,
    requested_at_utc: datetime | None = None,
) -> PreviewConversionCommand:
    requested_at = _aware(requested_at_utc or datetime.now(UTC))
    require_preview_conversion_execution_gate(
        gate=execution_gate,
        tenant_id=source_metadata.tenant_id,
        checked_at_utc=requested_at,
    )
    require_preview_conversion_source_preflight(
        evidence=source_preflight,
        source_metadata=source_metadata,
        checked_at_utc=requested_at,
    )
    input_suffix = MIME_TYPE_INPUT_SUFFIXES.get(source_metadata.mime_type.lower())
    if input_suffix is None:
        raise PreviewConversionBlocked("source MIME type is not supported by the preview converter")
    reason_hash = stable_hash(reason.strip())
    idempotency_key_hash = stable_hash(
        "\x1f".join(
            (
                source_metadata.tenant_id,
                source_metadata.object_id,
                source_metadata.version_id,
                source_metadata.manifest_hash,
                source_metadata.content_hash,
                adapter_plan_hash,
                execution_gate.evidence_hash,
                source_preflight.evidence_hash,
            )
        )
    )
    draft = PreviewConversionCommand(
        tenant_id=source_metadata.tenant_id,
        source_object_id=source_metadata.object_id,
        source_version_id=source_metadata.version_id,
        source_object_type=source_metadata.object_type,
        source_mime_type=source_metadata.mime_type,
        source_manifest_hash=source_metadata.manifest_hash,
        source_content_hash=source_metadata.content_hash,
        source_content_byte_length=source_metadata.content_byte_length,
        source_acl_version=source_metadata.acl_version,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        adapter_id=adapter_id,
        adapter_descriptor_hash=adapter_descriptor_hash,
        adapter_plan_hash=adapter_plan_hash,
        conversion_route=conversion_route,
        renderer_release_gate_evidence_hash=renderer_release_gate_evidence_hash,
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        source_preflight_evidence_hash=source_preflight.evidence_hash,
        worker_image_ref=execution_gate.worker_image_ref,
        resource_limits=execution_gate.resource_limits,
        input_filename=f"source{input_suffix}",
        requested_by=requested_by,
        requested_at_utc=requested_at,
        reason_hash=reason_hash,
        idempotency_key_hash=idempotency_key_hash,
        command_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"command_hash": build_preview_conversion_command_hash(draft)})


def require_preview_conversion_worker_envelope(
    *,
    envelope: PreviewConversionWorkerEnvelope,
    configured_worker_image_ref: str,
    configured_runtime_class: str,
    actual_font_baseline_hash: str,
    checked_at_utc: datetime | None = None,
) -> None:
    command = envelope.command
    gate = envelope.execution_gate
    preflight = envelope.source_preflight
    now = _aware(checked_at_utc or datetime.now(UTC))
    _require_command_hash(command)
    require_preview_conversion_execution_gate(gate=gate, tenant_id=command.tenant_id, checked_at_utc=now)
    if command.execution_gate_evidence_hash != gate.evidence_hash:
        raise PreviewConversionBlocked("preview conversion command is not bound to its execution gate")
    if command.source_preflight_evidence_hash != preflight.evidence_hash:
        raise PreviewConversionBlocked("preview conversion command is not bound to its source preflight")
    if command.worker_image_ref != configured_worker_image_ref or gate.worker_image_ref != configured_worker_image_ref:
        raise PreviewConversionBlocked("preview conversion worker image does not match the admitted digest")
    if gate.sandbox_runtime_class != configured_runtime_class:
        raise PreviewConversionBlocked("preview conversion sandbox runtime does not match gate evidence")
    if gate.font_baseline_hash != actual_font_baseline_hash:
        raise PreviewConversionBlocked("preview conversion font baseline does not match gate evidence")
    _require_preflight_matches_command(preflight=preflight, command=command, checked_at_utc=now)


def require_preview_conversion_execution_gate(
    *,
    gate: PreviewConversionExecutionGateEvidence,
    tenant_id: str,
    checked_at_utc: datetime | None = None,
) -> None:
    _require_execution_gate_hash(gate)
    now = _aware(checked_at_utc or datetime.now(UTC))
    if gate.tenant_id != tenant_id:
        raise PreviewConversionBlocked("preview conversion execution gate tenant mismatch")
    if gate.gate_status != PreviewConversionGateStatus.READY or gate.blocking_reasons:
        raise PreviewConversionBlocked("preview conversion execution gate is blocked")
    if now < gate.evaluated_at_utc - PREVIEW_CONVERSION_GATE_MAX_CLOCK_SKEW or now > gate.expires_at_utc:
        raise PreviewConversionBlocked("preview conversion execution gate is stale")


def require_preview_conversion_source_preflight(
    *,
    evidence: PreviewConversionSourcePreflightEvidence,
    source_metadata: SourceObjectMetadata,
    checked_at_utc: datetime | None = None,
) -> None:
    _require_source_preflight_hash(evidence)
    now = _aware(checked_at_utc or datetime.now(UTC))
    expected = (
        evidence.tenant_id == source_metadata.tenant_id
        and evidence.source_object_id == source_metadata.object_id
        and evidence.source_version_id == source_metadata.version_id
        and evidence.source_manifest_hash == source_metadata.manifest_hash
        and evidence.source_content_hash == source_metadata.content_hash
    )
    if not expected:
        raise PreviewConversionBlocked("preview conversion preflight does not match source version")
    if not evidence.conversion_allowed or evidence.blocking_reasons:
        raise PreviewConversionBlocked("preview conversion source preflight is blocked")
    if now < evidence.checked_at_utc - PREVIEW_CONVERSION_GATE_MAX_CLOCK_SKEW or now > evidence.expires_at_utc:
        raise PreviewConversionBlocked("preview conversion source preflight is stale")


def build_derived_preview_artifact(
    *,
    source_record: SourceObjectRecord,
    pdf_bytes: bytes,
    command: PreviewConversionCommand,
    result: PreviewConversionWorkerResult,
    execution_gate: PreviewConversionExecutionGateEvidence,
    source_preflight: PreviewConversionSourcePreflightEvidence,
    audit_event_id: str,
    created_at_utc: datetime | None = None,
) -> DerivedPreviewArtifact:
    created_at = _aware(created_at_utc or datetime.now(UTC))
    _require_derived_preview_inputs(
        source_record=source_record,
        pdf_bytes=pdf_bytes,
        command=command,
        result=result,
        execution_gate=execution_gate,
        source_preflight=source_preflight,
        checked_at_utc=created_at,
    )
    source = source_record.metadata
    derived_seed = stable_hash(
        "\x1f".join((source.tenant_id, source.object_id, source.version_id, result.result_hash))
    ).removeprefix("sha256:")
    derived_object_id = f"preview-{derived_seed[:40]}"
    derived_version_id = f"pv-{result.output_content_hash.removeprefix('sha256:')[:32]}"
    timestamp = created_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    audit_chain_ref = f"audit:preview-conversion:{audit_event_id}"
    draft_metadata = SourceObjectMetadata(
        tenant_id=source.tenant_id,
        object_id=derived_object_id,
        object_type=SourceObjectType.ATTACHMENT,
        version_id=derived_version_id,
        title=f"{source.title} (PDF preview)",
        owner_principal_id=source.owner_principal_id,
        created_by="system-preview-converter",
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        classification=source.classification,
        retention_policy_id=source.retention_policy_id,
        legal_hold_state=source.legal_hold_state,
        kms_key_ref=source.kms_key_ref,
        manifest_hash=ZERO_HASH,
        audit_chain_ref=audit_chain_ref,
        source_system="collabio.preview_converter",
        schema_version="source_object.preview_pdf.v1",
        mime_type="application/pdf",
        acl_hash=source.acl_hash,
        acl_version=source.acl_version,
        content_hash=result.output_content_hash,
        content_byte_length=len(pdf_bytes),
        lifecycle_state=source.lifecycle_state,
        parent_object_id=source.object_id,
        thread_id=source.thread_id,
        parser_profile_id="canonical_pdf.qpdf_pdfinfo.v1",
    )
    metadata = draft_metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft_metadata)})
    record = SourceObjectRecord(metadata=metadata, content_bytes=pdf_bytes)
    source_write_receipt = build_source_object_write_receipt(
        record=record,
        receipt_reference=f"derived-preview:{result.result_hash}",
        audit_chain_ref=audit_chain_ref,
        captured_at_utc=timestamp,
    )
    receipt_draft = DerivedPreviewReceipt(
        tenant_id=source.tenant_id,
        source_object_id=source.object_id,
        source_version_id=source.version_id,
        source_manifest_hash=source.manifest_hash,
        source_content_hash=source.content_hash,
        source_acl_version=source.acl_version,
        derived_object_id=metadata.object_id,
        derived_version_id=metadata.version_id,
        derived_manifest_hash=metadata.manifest_hash,
        derived_content_hash=metadata.content_hash,
        derived_content_byte_length=metadata.content_byte_length,
        command_hash=command.command_hash,
        result_hash=result.result_hash,
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        source_preflight_evidence_hash=source_preflight.evidence_hash,
        worker_image_ref=result.worker_image_ref,
        source_classification_inherited=metadata.classification == source.classification,
        source_acl_inherited=(metadata.acl_hash == source.acl_hash and metadata.acl_version == source.acl_version),
        source_retention_inherited=metadata.retention_policy_id == source.retention_policy_id,
        source_legal_hold_inherited=metadata.legal_hold_state == source.legal_hold_state,
        source_lifecycle_inherited=metadata.lifecycle_state == source.lifecycle_state,
        source_version_lineage_bound=True,
        output_revalidated=True,
        audit_event_id=audit_event_id,
        created_at_utc=created_at,
        receipt_hash=ZERO_HASH,
    )
    receipt = receipt_draft.model_copy(update={"receipt_hash": build_derived_preview_receipt_hash(receipt_draft)})
    job_evidence_draft = PreviewConversionJobEvidence(
        tenant_id=source.tenant_id,
        source_object_id=source.object_id,
        source_version_id=source.version_id,
        derived_object_id=metadata.object_id,
        derived_version_id=metadata.version_id,
        derived_preview_receipt_hash=receipt.receipt_hash,
        source_object_write_receipt_hash=source_write_receipt.receipt_hash,
        command_hash=command.command_hash,
        source_preflight_evidence_hash=source_preflight.evidence_hash,
        result_hash=result.result_hash,
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        worker_image_ref=result.worker_image_ref,
        command=command,
        source_preflight=source_preflight,
        result=result,
        completed_at_utc=result.completed_at_utc,
        job_evidence_hash=ZERO_HASH,
    )
    job_evidence = job_evidence_draft.model_copy(
        update={"job_evidence_hash": build_preview_conversion_job_evidence_hash(job_evidence_draft)}
    )
    return DerivedPreviewArtifact(
        record=record,
        source_object_write_receipt=source_write_receipt,
        derived_preview_receipt=receipt,
        job_evidence=job_evidence,
    )


def validate_derived_preview_pdf_bytes(
    *,
    pdf_bytes: bytes,
    expected_content_hash: str,
    max_output_bytes: int,
) -> None:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise PreviewConversionBlocked("derived preview output is not a PDF")
    if len(pdf_bytes) > max_output_bytes:
        raise PreviewConversionBlocked("derived preview output exceeds admitted size")
    if b"%%EOF" not in pdf_bytes[-4096:]:
        raise PreviewConversionBlocked("derived preview PDF has no terminal EOF marker")
    if sha256_bytes(pdf_bytes) != expected_content_hash:
        raise PreviewConversionBlocked("derived preview output content hash mismatch")
    forbidden_tokens = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia")
    if any(token in pdf_bytes for token in forbidden_tokens):
        raise PreviewConversionBlocked("derived preview PDF contains active content")


def build_preview_conversion_execution_gate_hash(
    evidence: PreviewConversionExecutionGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_preview_conversion_source_preflight_hash(
    evidence: PreviewConversionSourcePreflightEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_preview_conversion_command_hash(command: PreviewConversionCommand) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json", exclude={"command_hash"})))


def build_preview_conversion_result_hash(result: PreviewConversionWorkerResult) -> str:
    return stable_hash(canonical_json(result.model_dump(mode="json", exclude={"result_hash"})))


def build_derived_preview_receipt_hash(receipt: DerivedPreviewReceipt) -> str:
    return stable_hash(canonical_json(receipt.model_dump(mode="json", exclude={"receipt_hash"})))


def build_preview_conversion_job_evidence_hash(evidence: PreviewConversionJobEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"job_evidence_hash"})))


def build_default_preview_conversion_execution_gate_store(
    environ: Mapping[str, str] | None = None,
) -> PreviewConversionExecutionGateStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PREVIEW_CONVERSION_EXECUTION_GATE_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryPreviewConversionExecutionGateStore()
    if backend in {"postgres", "postgresql", "pg"}:
        dsn = env.get("SUITE_PREVIEW_CONVERSION_EXECUTION_GATE_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if not dsn:
            raise ValueError("PostgreSQL preview conversion execution gate store requires a database DSN")
        return PgPreviewConversionExecutionGateStore(database_dsn=dsn)
    raise ValueError(f"Unsupported preview conversion execution gate store backend: {backend}")


def build_default_derived_preview_receipt_store(
    environ: Mapping[str, str] | None = None,
) -> DerivedPreviewReceiptStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_DERIVED_PREVIEW_RECEIPT_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryDerivedPreviewReceiptStore()
    if backend in {"postgres", "postgresql", "pg"}:
        dsn = env.get("SUITE_DERIVED_PREVIEW_RECEIPT_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if not dsn:
            raise ValueError("PostgreSQL derived preview receipt store requires a database DSN")
        return PgDerivedPreviewReceiptStore(database_dsn=dsn)
    raise ValueError(f"Unsupported derived preview receipt store backend: {backend}")


def build_default_preview_conversion_job_evidence_store(
    environ: Mapping[str, str] | None = None,
) -> PreviewConversionJobEvidenceStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_PREVIEW_CONVERSION_JOB_EVIDENCE_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryPreviewConversionJobEvidenceStore()
    if backend in {"postgres", "postgresql", "pg"}:
        dsn = env.get("SUITE_PREVIEW_CONVERSION_JOB_EVIDENCE_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if not dsn:
            raise ValueError("PostgreSQL preview conversion job evidence store requires a database DSN")
        return PgPreviewConversionJobEvidenceStore(database_dsn=dsn)
    raise ValueError(f"Unsupported preview conversion job evidence store backend: {backend}")


def build_in_memory_derived_preview_write_unit_of_work(
    *,
    source_repository: SourceObjectRepository,
) -> DerivedPreviewWriteUnitOfWork:
    return DerivedPreviewWriteUnitOfWork(
        source_repository=source_repository,
        source_object_write_receipt_store=InMemorySourceObjectWriteReceiptStore(),
        derived_preview_receipt_store=InMemoryDerivedPreviewReceiptStore(),
        job_evidence_store=InMemoryPreviewConversionJobEvidenceStore(),
    )


def _require_derived_preview_inputs(
    *,
    source_record: SourceObjectRecord,
    pdf_bytes: bytes,
    command: PreviewConversionCommand,
    result: PreviewConversionWorkerResult,
    execution_gate: PreviewConversionExecutionGateEvidence,
    source_preflight: PreviewConversionSourcePreflightEvidence,
    checked_at_utc: datetime,
) -> None:
    source = source_record.metadata
    _require_command_hash(command)
    _require_result_hash(result)
    require_preview_conversion_execution_gate(
        gate=execution_gate,
        tenant_id=source.tenant_id,
        checked_at_utc=checked_at_utc,
    )
    require_preview_conversion_source_preflight(
        evidence=source_preflight,
        source_metadata=source,
        checked_at_utc=checked_at_utc,
    )
    source_binding = (
        command.tenant_id == source.tenant_id
        and command.source_object_id == source.object_id
        and command.source_version_id == source.version_id
        and command.source_manifest_hash == source.manifest_hash
        and command.source_content_hash == source.content_hash
        and command.source_acl_version == source.acl_version
        and result.tenant_id == source.tenant_id
        and result.source_object_id == source.object_id
        and result.source_version_id == source.version_id
        and result.source_manifest_hash == source.manifest_hash
        and result.source_content_hash == source.content_hash
    )
    if not source_binding:
        raise PreviewConversionBlocked("derived preview lineage does not match authoritative source version")
    evidence_binding = (
        result.command_hash == command.command_hash
        and command.execution_gate_evidence_hash == execution_gate.evidence_hash
        and result.execution_gate_evidence_hash == execution_gate.evidence_hash
        and command.source_preflight_evidence_hash == source_preflight.evidence_hash
        and result.source_preflight_evidence_hash == source_preflight.evidence_hash
        and result.worker_image_ref == execution_gate.worker_image_ref
        and result.production_admission_gate_hash == command.production_admission_gate_hash
        and result.font_baseline_hash == execution_gate.font_baseline_hash
    )
    if not evidence_binding:
        raise PreviewConversionBlocked("derived preview result is not bound to admitted execution evidence")
    if result.output_content_byte_length != len(pdf_bytes):
        raise PreviewConversionBlocked("derived preview output length mismatch")
    if result.page_count > execution_gate.resource_limits.max_page_count:
        raise PreviewConversionBlocked("derived preview output page count exceeds gate limit")
    validate_derived_preview_pdf_bytes(
        pdf_bytes=pdf_bytes,
        expected_content_hash=result.output_content_hash,
        max_output_bytes=execution_gate.resource_limits.max_output_bytes,
    )


def _require_preflight_matches_command(
    *,
    preflight: PreviewConversionSourcePreflightEvidence,
    command: PreviewConversionCommand,
    checked_at_utc: datetime,
) -> None:
    _require_source_preflight_hash(preflight)
    matches = (
        preflight.tenant_id == command.tenant_id
        and preflight.source_object_id == command.source_object_id
        and preflight.source_version_id == command.source_version_id
        and preflight.source_manifest_hash == command.source_manifest_hash
        and preflight.source_content_hash == command.source_content_hash
    )
    if not matches:
        raise PreviewConversionBlocked("preview conversion source preflight does not match command")
    if not preflight.conversion_allowed or preflight.blocking_reasons:
        raise PreviewConversionBlocked("preview conversion source preflight is blocked")
    if checked_at_utc > preflight.expires_at_utc:
        raise PreviewConversionBlocked("preview conversion source preflight is stale")


def _gate_control_values(evidence: PreviewConversionExecutionGateEvidence) -> tuple[bool, ...]:
    return (
        evidence.image_digest_pinned,
        evidence.stronger_sandbox_attested,
        evidence.network_egress_denied,
        evidence.read_only_root_filesystem,
        evidence.non_root_user,
        evidence.all_capabilities_dropped,
        evidence.no_new_privileges,
        evidence.ephemeral_workspace,
        evidence.malware_cdr_ready,
        evidence.pdf_revalidation_ready,
        evidence.font_baseline_ready,
        evidence.restore_ready,
        evidence.separate_viewer_origin_ready,
        evidence.strict_viewer_csp_ready,
    )


def _require_execution_gate_hash(evidence: PreviewConversionExecutionGateEvidence) -> None:
    if evidence.evidence_hash != build_preview_conversion_execution_gate_hash(evidence):
        raise PreviewConversionBlocked("preview conversion execution gate hash is invalid")


def _require_source_preflight_hash(evidence: PreviewConversionSourcePreflightEvidence) -> None:
    if evidence.evidence_hash != build_preview_conversion_source_preflight_hash(evidence):
        raise PreviewConversionBlocked("preview conversion source preflight hash is invalid")


def _require_command_hash(command: PreviewConversionCommand) -> None:
    if command.command_hash != build_preview_conversion_command_hash(command):
        raise PreviewConversionBlocked("preview conversion command hash is invalid")


def _require_result_hash(result: PreviewConversionWorkerResult) -> None:
    if result.result_hash != build_preview_conversion_result_hash(result):
        raise PreviewConversionBlocked("preview conversion result hash is invalid")


def _require_derived_preview_receipt_hash(receipt: DerivedPreviewReceipt) -> None:
    if receipt.receipt_hash != build_derived_preview_receipt_hash(receipt):
        raise PreviewConversionBlocked("derived preview receipt hash is invalid")


def _require_job_evidence_hash(evidence: PreviewConversionJobEvidence) -> None:
    if evidence.job_evidence_hash != build_preview_conversion_job_evidence_hash(evidence):
        raise PreviewConversionBlocked("preview conversion job evidence hash is invalid")


def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
