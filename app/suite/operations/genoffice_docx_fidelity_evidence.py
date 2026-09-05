from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_FIXTURE_IDS,
    ZERO_HASH,
    EngineId,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityStudyPlan,
    GenOfficeDocxRgbPageComparisonReport,
    GenOfficeDocxStructuralFingerprintReport,
    RunnerMode,
    build_genoffice_docx_structural_fingerprint,
    compare_genoffice_docx_rgb_page,
    verify_genoffice_docx_fidelity_signed_result,
)
from suite.operations.genoffice_docx_quick_edit_preflight import (
    GenOfficeDocxQuickEditPreflightReport,
    build_genoffice_docx_quick_edit_preflight_policy,
    inspect_genoffice_docx_quick_edit_candidate,
)
from suite.platform.preview_cdr import PreviewCdrPageManifest

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024 * 1024
OPENXML_VALIDATOR_NAME: Literal["DocumentFormat.OpenXml"] = "DocumentFormat.OpenXml"
EVIDENCE_TOP_LEVEL_ENTRIES = (
    "candidate-cdr",
    "execution-receipt.json",
    "font-baseline-report.json",
    "openxml-validation-report.json",
    "output-preflight-report.json",
    "output-structural-fingerprint-report.json",
    "output.docx",
    "reference-cdr",
    "visual-comparison-manifest.json",
)
PUBLIC_INPUT_ENTRIES = (
    "result-envelope.json",
    "signer-policy.json",
    "study-plan.json",
)

RenderStage = Literal["source_reference", "roundtrip_candidate"]
FontInventoryMethod = Literal["windows_font_inventory", "fontconfig_fc_list", "worker_image_font_manifest"]
OpenXmlErrorType = Literal["schema", "semantic", "package", "markup_compatibility"]


class GenOfficeDocxFidelityEvidenceError(ValueError):
    pass


class GenOfficeDocxOpenXmlValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error_id: str
    error_type: OpenXmlErrorType
    part_uri: str
    path_hash: str

    @model_validator(mode="after")
    def require_metadata_only_finding(self) -> GenOfficeDocxOpenXmlValidationFinding:
        if not self.error_id.strip() or not self.part_uri.startswith("/") or ".." in PurePosixPath(self.part_uri).parts:
            raise ValueError("GenOffice Open XML validation finding is invalid")
        _require_sha256(self.path_hash, field="Open XML finding path hash")
        return self


class GenOfficeDocxOpenXmlValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_openxml_validation_report.v1"] = (
        "genoffice_docx_openxml_validation_report.v1"
    )
    assignment_id: str
    engine_id: EngineId
    fixture_id: str
    output_docx_sha256: str
    validator_name: Literal["DocumentFormat.OpenXml"] = OPENXML_VALIDATOR_NAME
    validator_version: str
    target_file_format_version: str
    markup_compatibility_processing_enabled: Literal[True] = True
    findings: tuple[GenOfficeDocxOpenXmlValidationFinding, ...]
    validation_error_count: int = Field(ge=0)
    schema_conformant: bool
    document_content_included: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_consistent_validation(self) -> GenOfficeDocxOpenXmlValidationReport:
        if self.assignment_id != f"{self.engine_id}:{self.fixture_id}" or self.fixture_id not in FIDELITY_FIXTURE_IDS:
            raise ValueError("GenOffice Open XML validation assignment is invalid")
        if not self.validator_version.strip() or not self.target_file_format_version.strip():
            raise ValueError("GenOffice Open XML validator identity is incomplete")
        expected_findings = tuple(
            sorted(self.findings, key=lambda item: (item.part_uri, item.error_type, item.error_id, item.path_hash))
        )
        if self.findings != expected_findings or len(set(self.findings)) != len(self.findings):
            raise ValueError("GenOffice Open XML validation findings are not canonical")
        if self.validation_error_count != len(self.findings):
            raise ValueError("GenOffice Open XML validation finding count is inconsistent")
        if self.schema_conformant != (self.validation_error_count == 0):
            raise ValueError("GenOffice Open XML schema result is inconsistent")
        _require_sha256(self.output_docx_sha256, field="Open XML output hash")
        _require_sha256(self.report_hash, field="Open XML report hash")
        return self


class GenOfficeDocxFidelityFontBaselineReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_font_baseline_report.v1"] = (
        "genoffice_docx_fidelity_font_baseline_report.v1"
    )
    assignment_id: str
    engine_id: EngineId
    runner_mode: RunnerMode
    engine_version: str
    engine_identity_hash: str
    executor_environment_hash: str
    inventory_method: FontInventoryMethod
    font_count: int = Field(ge=1, le=100000)
    normalized_inventory_sha256: str
    font_names_included: Literal[False] = False
    host_paths_included: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_bound_baseline(self) -> GenOfficeDocxFidelityFontBaselineReport:
        expected_method: dict[EngineId, FontInventoryMethod] = {
            "microsoft_word": "windows_font_inventory",
            "libreoffice": "fontconfig_fc_list",
            "genoffice": "worker_image_font_manifest",
        }
        expected_mode: dict[EngineId, RunnerMode] = {
            "microsoft_word": "interactive_windows_client",
            "libreoffice": "isolated_headless_worker",
            "genoffice": "authorized_runsc_kvm_worker",
        }
        if (
            not self.engine_version.strip()
            or not self.assignment_id.startswith(f"{self.engine_id}:")
            or self.inventory_method != expected_method[self.engine_id]
            or self.runner_mode != expected_mode[self.engine_id]
        ):
            raise ValueError("GenOffice fidelity font baseline identity is invalid")
        for value, field in (
            (self.engine_identity_hash, "font baseline engine identity hash"),
            (self.executor_environment_hash, "font baseline environment hash"),
            (self.normalized_inventory_sha256, "font baseline inventory hash"),
            (self.report_hash, "font baseline report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityCdrManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_cdr_manifest.v1"] = "genoffice_docx_fidelity_cdr_manifest.v1"
    assignment_id: str
    render_stage: RenderStage
    rendered_docx_sha256: str
    cdr_profile_ref: Literal["collabio-pixel-cdr:raw-rgb.v1"] = "collabio-pixel-cdr:raw-rgb.v1"
    rasterizer_engine: str
    rasterizer_version: str
    font_baseline_report_hash: str
    raster_dpi: Literal[144] = 144
    page_count: int = Field(ge=1, le=10000)
    raw_rgb_byte_length: int = Field(ge=3, le=MAX_EVIDENCE_BYTES)
    pages: tuple[PreviewCdrPageManifest, ...]
    source_synthetic: Literal[True] = True
    tenant_identifier_included: Literal[False] = False
    document_content_in_manifest: Literal[False] = False
    active_content_preserved: Literal[False] = False
    external_network_used: Literal[False] = False
    manifest_hash: str

    @model_validator(mode="after")
    def require_closed_manifest(self) -> GenOfficeDocxFidelityCdrManifest:
        if not self.assignment_id.strip() or not self.rasterizer_engine.strip() or not self.rasterizer_version.strip():
            raise ValueError("GenOffice fidelity CDR identity is incomplete")
        if self.page_count != len(self.pages):
            raise ValueError("GenOffice fidelity CDR page count is inconsistent")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("GenOffice fidelity CDR pages are not contiguous")
        if self.raw_rgb_byte_length != sum(page.rgb_byte_length for page in self.pages):
            raise ValueError("GenOffice fidelity CDR byte length is inconsistent")
        _require_sha256(self.rendered_docx_sha256, field="fidelity CDR document hash")
        _require_sha256(self.font_baseline_report_hash, field="fidelity CDR font baseline hash")
        _require_sha256(self.manifest_hash, field="fidelity CDR manifest hash")
        return self


class GenOfficeDocxFidelityVisualComparisonManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_visual_comparison_manifest.v1"] = (
        "genoffice_docx_fidelity_visual_comparison_manifest.v1"
    )
    assignment_id: str
    reference_kind: Literal["same_engine_source_render"] = "same_engine_source_render"
    reference_cdr_manifest_hash: str
    candidate_cdr_manifest_hash: str
    page_comparisons: tuple[GenOfficeDocxRgbPageComparisonReport, ...]
    page_count: int = Field(ge=1, le=10000)
    page_dimensions_match: Literal[True] = True
    measurements_verified: Literal[True] = True
    thresholds_calibrated: Literal[False] = False
    automated_acceptance_allowed: Literal[False] = False
    human_review_verified: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    raw_rgb_content_included: Literal[False] = False
    manifest_hash: str

    @model_validator(mode="after")
    def require_measurement_only_manifest(self) -> GenOfficeDocxFidelityVisualComparisonManifest:
        if self.page_count != len(self.page_comparisons):
            raise ValueError("GenOffice fidelity visual page count is inconsistent")
        if tuple(item.page_number for item in self.page_comparisons) != tuple(range(1, self.page_count + 1)):
            raise ValueError("GenOffice fidelity visual pages are not contiguous")
        for value, field in (
            (self.reference_cdr_manifest_hash, "visual reference CDR hash"),
            (self.candidate_cdr_manifest_hash, "visual candidate CDR hash"),
            (self.manifest_hash, "visual comparison manifest hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityEvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    size_bytes: int = Field(ge=1, le=MAX_EVIDENCE_BYTES)
    content_sha256: str

    @model_validator(mode="after")
    def require_safe_path(self) -> GenOfficeDocxFidelityEvidenceArtifact:
        candidate = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or "\\" in self.relative_path
            or candidate.is_absolute()
            or ".." in candidate.parts
            or str(candidate) != self.relative_path
        ):
            raise ValueError("GenOffice fidelity evidence artifact path is unsafe")
        _require_sha256(self.content_sha256, field="evidence artifact content hash")
        return self


class GenOfficeDocxFidelityExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_execution_receipt.v1"] = (
        "genoffice_docx_fidelity_execution_receipt.v1"
    )
    assignment_id: str
    study_plan_hash: str
    fidelity_policy_hash: str
    engine_id: EngineId
    runner_mode: RunnerMode
    source_content_sha256: str
    output_docx_sha256: str
    engine_identity_hash: str
    executor_environment_hash: str
    authorization_evidence_hash: str
    command_hash: str
    started_at_utc: datetime
    completed_at_utc: datetime
    exit_code: Literal[0] = 0
    artifacts: tuple[GenOfficeDocxFidelityEvidenceArtifact, ...]
    source_synthetic: Literal[True] = True
    network_isolation_verified: Literal[True] = True
    macro_execution_disabled: Literal[True] = True
    source_blind_revalidation_verified: Literal[True] = True
    engine_execution_authorized: Literal[True] = True
    engine_executed: Literal[True] = True
    tenant_content_processed: Literal[False] = False
    tenant_credentials_available: Literal[False] = False
    persistent_product_version_written: Literal[False] = False
    private_key_included: Literal[False] = False
    document_content_in_receipt: Literal[False] = False
    receipt_hash: str

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice fidelity execution receipt time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_closed_receipt(self) -> GenOfficeDocxFidelityExecutionReceipt:
        assignment_parts = self.assignment_id.split(":", 1)
        expected_mode: dict[EngineId, RunnerMode] = {
            "microsoft_word": "interactive_windows_client",
            "libreoffice": "isolated_headless_worker",
            "genoffice": "authorized_runsc_kvm_worker",
        }
        if (
            len(assignment_parts) != 2
            or assignment_parts[0] != self.engine_id
            or assignment_parts[1] not in FIDELITY_FIXTURE_IDS
            or self.runner_mode != expected_mode[self.engine_id]
        ):
            raise ValueError("GenOffice fidelity execution receipt assignment is invalid")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("GenOffice fidelity execution receipt time window is invalid")
        paths = tuple(item.relative_path for item in self.artifacts)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("GenOffice fidelity evidence artifact inventory is not canonical")
        if "execution-receipt.json" in paths:
            raise ValueError("GenOffice fidelity execution receipt cannot hash itself")
        for value, field in (
            (self.study_plan_hash, "execution receipt study plan hash"),
            (self.fidelity_policy_hash, "execution receipt fidelity policy hash"),
            (self.source_content_sha256, "execution receipt source hash"),
            (self.output_docx_sha256, "execution receipt output hash"),
            (self.engine_identity_hash, "execution receipt engine identity hash"),
            (self.executor_environment_hash, "execution receipt environment hash"),
            (self.authorization_evidence_hash, "execution receipt authorization hash"),
            (self.command_hash, "execution receipt command hash"),
            (self.receipt_hash, "execution receipt hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityEvidenceVerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_evidence_verification_report.v1"] = (
        "genoffice_docx_fidelity_evidence_verification_report.v1"
    )
    assignment_id: str
    signed_result_envelope_hash: str
    execution_receipt_hash: str
    output_docx_sha256: str
    output_preflight_report_hash: str
    output_structural_fingerprint_hash: str
    open_xml_validation_report_hash: str
    font_baseline_report_hash: str
    reference_cdr_manifest_hash: str
    candidate_cdr_manifest_hash: str
    visual_comparison_manifest_hash: str
    artifact_count: int = Field(ge=1)
    artifact_total_bytes: int = Field(ge=1, le=MAX_EVIDENCE_BYTES)
    signed_result_verified: Literal[True] = True
    artifact_inventory_exact: Literal[True] = True
    artifact_bytes_verified: Literal[True] = True
    output_preflight_recomputed: Literal[True] = True
    structural_fingerprint_verified: Literal[True] = True
    open_xml_evidence_verified: Literal[True] = True
    open_xml_schema_conformant: bool
    font_baseline_verified: Literal[True] = True
    reference_cdr_bytes_verified: Literal[True] = True
    candidate_cdr_bytes_verified: Literal[True] = True
    visual_measurements_recomputed: Literal[True] = True
    referenced_evidence_content_verified: Literal[True] = True
    source_blind_revalidation_verified: Literal[True] = True
    thresholds_calibrated: Literal[False] = False
    human_fidelity_review_verified: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    quick_edit_spike_complete: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    document_content_in_report: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_verified_but_unaccepted(self) -> GenOfficeDocxFidelityEvidenceVerificationReport:
        for value, field in (
            (self.signed_result_envelope_hash, "evidence verification envelope hash"),
            (self.execution_receipt_hash, "evidence verification receipt hash"),
            (self.output_docx_sha256, "evidence verification output hash"),
            (self.output_preflight_report_hash, "evidence verification preflight hash"),
            (self.output_structural_fingerprint_hash, "evidence verification structure hash"),
            (self.open_xml_validation_report_hash, "evidence verification Open XML hash"),
            (self.font_baseline_report_hash, "evidence verification font hash"),
            (self.reference_cdr_manifest_hash, "evidence verification reference CDR hash"),
            (self.candidate_cdr_manifest_hash, "evidence verification candidate CDR hash"),
            (self.visual_comparison_manifest_hash, "evidence verification visual hash"),
            (self.report_hash, "evidence verification report hash"),
        ):
            _require_sha256(value, field=field)
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"GenOffice {field} is invalid")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError(f"GenOffice {field} is invalid") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _hash_model(model: BaseModel, *, hash_field: str) -> str:
    return stable_hash(canonical_json(model.model_dump(mode="json", exclude={hash_field})))


def build_genoffice_docx_openxml_validation_report_hash(report: GenOfficeDocxOpenXmlValidationReport) -> str:
    return _hash_model(report, hash_field="report_hash")


def build_genoffice_docx_fidelity_font_baseline_report_hash(
    report: GenOfficeDocxFidelityFontBaselineReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def build_genoffice_docx_fidelity_cdr_manifest_hash(manifest: GenOfficeDocxFidelityCdrManifest) -> str:
    return _hash_model(manifest, hash_field="manifest_hash")


def build_genoffice_docx_fidelity_visual_comparison_manifest_hash(
    manifest: GenOfficeDocxFidelityVisualComparisonManifest,
) -> str:
    return _hash_model(manifest, hash_field="manifest_hash")


def build_genoffice_docx_fidelity_execution_receipt_hash(receipt: GenOfficeDocxFidelityExecutionReceipt) -> str:
    return _hash_model(receipt, hash_field="receipt_hash")


def build_genoffice_docx_fidelity_evidence_verification_report_hash(
    report: GenOfficeDocxFidelityEvidenceVerificationReport,
) -> str:
    return _hash_model(report, hash_field="report_hash")


def _strict_json_loads(content: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity JSON contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence JSON is invalid") from exc


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise GenOfficeDocxFidelityEvidenceError(f"GenOffice fidelity evidence file is invalid: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise GenOfficeDocxFidelityEvidenceError(f"GenOffice fidelity evidence file size is invalid: {path.name}")
    content = path.read_bytes()
    if len(content) != size:
        raise GenOfficeDocxFidelityEvidenceError(f"GenOffice fidelity evidence file changed while reading: {path.name}")
    return content


def _load_model[TModel: BaseModel](path: Path, model: type[TModel]) -> tuple[TModel, bytes]:
    content = _read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
    try:
        return model.model_validate(_strict_json_loads(content)), content
    except ValidationError as exc:
        raise GenOfficeDocxFidelityEvidenceError(f"GenOffice fidelity evidence model is invalid: {path.name}") from exc


def _require_report_hash(model: BaseModel, *, field: str, hash_field: str) -> str:
    observed = str(getattr(model, hash_field))
    if _hash_model(model, hash_field=hash_field) != observed:
        raise GenOfficeDocxFidelityEvidenceError(f"GenOffice fidelity {field} hash is invalid")
    return observed


def _require_top_level_inventory(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence root is invalid")
    entries = tuple(root.iterdir())
    if tuple(sorted(entry.name for entry in entries)) != EVIDENCE_TOP_LEVEL_ENTRIES:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence top-level inventory is not exact")
    directories = {"reference-cdr", "candidate-cdr"}
    for entry in entries:
        if entry.is_symlink():
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence contains a symlink")
        if entry.name in directories and not entry.is_dir():
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR entry is not a directory")
        if entry.name not in directories and not entry.is_file():
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence entry is not a regular file")


def _require_empty_output_directory(output_directory: Path) -> Path:
    if output_directory.is_symlink() or not output_directory.is_dir():
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence output directory is invalid")
    root = output_directory.resolve()
    if any(root.iterdir()):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence output directory is not empty")
    return root


def _load_and_verify_cdr(
    *,
    directory: Path,
    expected_stage: RenderStage,
    expected_assignment_id: str,
    expected_docx_sha256: str,
    expected_font_hash: str,
) -> tuple[GenOfficeDocxFidelityCdrManifest, tuple[bytes, ...], bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR directory is invalid")
    manifest, manifest_bytes = _load_model(directory / "manifest.json", GenOfficeDocxFidelityCdrManifest)
    if build_genoffice_docx_fidelity_cdr_manifest_hash(manifest) != manifest.manifest_hash:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR manifest hash is invalid")
    if (
        manifest.render_stage != expected_stage
        or manifest.assignment_id != expected_assignment_id
        or manifest.rendered_docx_sha256 != expected_docx_sha256
        or manifest.font_baseline_report_hash != expected_font_hash
    ):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR binding drifted")
    expected_entries = {"manifest.json", *(page.filename for page in manifest.pages)}
    entries = tuple(directory.iterdir())
    if {entry.name for entry in entries} != expected_entries:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR page inventory is not exact")
    pages: list[bytes] = []
    total = 0
    for page in manifest.pages:
        content = _read_regular_file(directory / page.filename, maximum_bytes=4096 * 4096 * 3)
        if len(content) != page.rgb_byte_length or _sha256_bytes(content) != page.rgb_content_hash:
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR page bytes drifted")
        pages.append(content)
        total += len(content)
    if total != manifest.raw_rgb_byte_length:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR aggregate bytes drifted")
    return manifest, tuple(pages), manifest_bytes


def _artifact_inventory(root: Path) -> tuple[GenOfficeDocxFidelityEvidenceArtifact, ...]:
    artifacts: list[GenOfficeDocxFidelityEvidenceArtifact] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence contains a symlink")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "execution-receipt.json":
            continue
        content = _read_regular_file(path, maximum_bytes=MAX_EVIDENCE_BYTES)
        total += len(content)
        if total > MAX_EVIDENCE_BYTES:
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence exceeds the aggregate byte limit")
        artifacts.append(
            GenOfficeDocxFidelityEvidenceArtifact(
                relative_path=relative,
                size_bytes=len(content),
                content_sha256=_sha256_bytes(content),
            )
        )
    return tuple(artifacts)


def _require_payload_bindings(
    *,
    payload: GenOfficeDocxFidelityEngineResultPayload,
    preflight: GenOfficeDocxQuickEditPreflightReport,
    structural: GenOfficeDocxStructuralFingerprintReport,
    openxml: GenOfficeDocxOpenXmlValidationReport,
    font: GenOfficeDocxFidelityFontBaselineReport,
    candidate_cdr: GenOfficeDocxFidelityCdrManifest,
    visual: GenOfficeDocxFidelityVisualComparisonManifest,
    receipt: GenOfficeDocxFidelityExecutionReceipt,
) -> None:
    observed = (
        preflight.report_hash,
        structural.report_hash,
        openxml.report_hash,
        candidate_cdr.manifest_hash,
        font.report_hash,
        visual.manifest_hash,
        receipt.receipt_hash,
    )
    expected = (
        payload.output_preflight_report_hash,
        payload.output_structural_fingerprint_hash,
        payload.open_xml_validation_report_hash,
        payload.cdr_manifest_hash,
        payload.font_baseline_hash,
        payload.visual_comparison_manifest_hash,
        payload.execution_receipt_hash,
    )
    if observed != expected:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity signed payload evidence binding drifted")


def _require_receipt_binding(
    *,
    receipt: GenOfficeDocxFidelityExecutionReceipt,
    payload: GenOfficeDocxFidelityEngineResultPayload,
    artifacts: tuple[GenOfficeDocxFidelityEvidenceArtifact, ...],
) -> None:
    if receipt.artifacts != artifacts:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity receipt artifact inventory drifted")
    if (
        receipt.assignment_id != payload.assignment_id
        or receipt.study_plan_hash != payload.study_plan_hash
        or receipt.fidelity_policy_hash != payload.fidelity_policy_hash
        or receipt.engine_id != payload.engine_id
        or receipt.runner_mode != payload.runner_mode
        or receipt.source_content_sha256 != payload.source_content_sha256
        or receipt.output_docx_sha256 != payload.output_docx_sha256
        or receipt.engine_identity_hash != payload.engine_identity_hash
        or receipt.executor_environment_hash != payload.executor_environment_hash
        or receipt.completed_at_utc != payload.completed_at_utc
    ):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity execution receipt binding drifted")


def verify_genoffice_docx_fidelity_evidence_bundle(
    *,
    evidence_root: Path,
    envelope: GenOfficeDocxFidelitySignedResultEnvelope,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeDocxFidelityEvidenceVerificationReport:
    payload = verify_genoffice_docx_fidelity_signed_result(
        envelope=envelope,
        signer_policy=signer_policy,
        study_plan=study_plan,
        verifier=verifier,
    )
    if evidence_root.is_symlink():
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence root is invalid")
    root = evidence_root.resolve()
    _require_top_level_inventory(root)
    output_docx = _read_regular_file(root / "output.docx", maximum_bytes=MAX_EVIDENCE_BYTES)
    output_sha256 = _sha256_bytes(output_docx)
    if output_sha256 != payload.output_docx_sha256:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity output DOCX bytes drifted")

    preflight, _ = _load_model(root / "output-preflight-report.json", GenOfficeDocxQuickEditPreflightReport)
    recomputed_preflight = inspect_genoffice_docx_quick_edit_candidate(
        output_docx,
        policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    if preflight != recomputed_preflight or not preflight.future_engine_evaluation_eligible:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity output preflight did not reproduce")

    structural, _ = _load_model(
        root / "output-structural-fingerprint-report.json",
        GenOfficeDocxStructuralFingerprintReport,
    )
    recomputed_structural = build_genoffice_docx_structural_fingerprint(
        fixture_id=payload.fixture_id,
        content=output_docx,
        preflight_policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    if structural != recomputed_structural:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity structural fingerprint binding drifted")

    openxml, _ = _load_model(root / "openxml-validation-report.json", GenOfficeDocxOpenXmlValidationReport)
    _require_report_hash(openxml, field="Open XML validation", hash_field="report_hash")
    if openxml.assignment_id != payload.assignment_id or openxml.output_docx_sha256 != output_sha256:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity Open XML report binding drifted")

    font, _ = _load_model(root / "font-baseline-report.json", GenOfficeDocxFidelityFontBaselineReport)
    _require_report_hash(font, field="font baseline", hash_field="report_hash")
    if (
        font.assignment_id != payload.assignment_id
        or font.engine_id != payload.engine_id
        or font.runner_mode != payload.runner_mode
        or font.engine_version != payload.engine_version
        or font.engine_identity_hash != payload.engine_identity_hash
        or font.executor_environment_hash != payload.executor_environment_hash
    ):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity font baseline binding drifted")

    reference_cdr, reference_pages, _ = _load_and_verify_cdr(
        directory=root / "reference-cdr",
        expected_stage="source_reference",
        expected_assignment_id=payload.assignment_id,
        expected_docx_sha256=payload.source_content_sha256,
        expected_font_hash=font.report_hash,
    )
    candidate_cdr, candidate_pages, _ = _load_and_verify_cdr(
        directory=root / "candidate-cdr",
        expected_stage="roundtrip_candidate",
        expected_assignment_id=payload.assignment_id,
        expected_docx_sha256=output_sha256,
        expected_font_hash=font.report_hash,
    )
    if payload.page_count != candidate_cdr.page_count or reference_cdr.page_count != candidate_cdr.page_count:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity CDR page counts drifted")

    visual, _ = _load_model(
        root / "visual-comparison-manifest.json",
        GenOfficeDocxFidelityVisualComparisonManifest,
    )
    _require_report_hash(visual, field="visual comparison", hash_field="manifest_hash")
    if (
        visual.assignment_id != payload.assignment_id
        or visual.reference_cdr_manifest_hash != reference_cdr.manifest_hash
        or visual.candidate_cdr_manifest_hash != candidate_cdr.manifest_hash
    ):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity visual comparison binding drifted")
    recomputed_comparisons = tuple(
        compare_genoffice_docx_rgb_page(
            page_number=reference_page.page_number,
            width_pixels=reference_page.width_pixels,
            height_pixels=reference_page.height_pixels,
            reference_rgb=reference_content,
            candidate_rgb=candidate_content,
        )
        for reference_page, candidate_page, reference_content, candidate_content in zip(
            reference_cdr.pages,
            candidate_cdr.pages,
            reference_pages,
            candidate_pages,
            strict=True,
        )
        if reference_page.width_pixels == candidate_page.width_pixels
        and reference_page.height_pixels == candidate_page.height_pixels
    )
    if len(recomputed_comparisons) != visual.page_count or recomputed_comparisons != visual.page_comparisons:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity visual measurements did not reproduce")

    receipt, _ = _load_model(root / "execution-receipt.json", GenOfficeDocxFidelityExecutionReceipt)
    _require_report_hash(receipt, field="execution receipt", hash_field="receipt_hash")
    artifacts = _artifact_inventory(root)
    _require_receipt_binding(receipt=receipt, payload=payload, artifacts=artifacts)
    _require_payload_bindings(
        payload=payload,
        preflight=preflight,
        structural=structural,
        openxml=openxml,
        font=font,
        candidate_cdr=candidate_cdr,
        visual=visual,
        receipt=receipt,
    )

    draft = GenOfficeDocxFidelityEvidenceVerificationReport(
        assignment_id=payload.assignment_id,
        signed_result_envelope_hash=envelope.envelope_hash,
        execution_receipt_hash=receipt.receipt_hash,
        output_docx_sha256=output_sha256,
        output_preflight_report_hash=preflight.report_hash,
        output_structural_fingerprint_hash=structural.report_hash,
        open_xml_validation_report_hash=openxml.report_hash,
        font_baseline_report_hash=font.report_hash,
        reference_cdr_manifest_hash=reference_cdr.manifest_hash,
        candidate_cdr_manifest_hash=candidate_cdr.manifest_hash,
        visual_comparison_manifest_hash=visual.manifest_hash,
        artifact_count=len(artifacts),
        artifact_total_bytes=sum(item.size_bytes for item in artifacts),
        open_xml_schema_conformant=openxml.schema_conformant,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"report_hash": build_genoffice_docx_fidelity_evidence_verification_report_hash(draft)}
    )


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GenOfficeDocxFidelityEvidenceError(
            f"GenOffice fidelity evidence output cannot be persisted: {path.name}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def persist_genoffice_docx_fidelity_evidence_schemas(output_directory: Path) -> dict[str, str]:
    output_root = _require_empty_output_directory(output_directory)
    schemas: Sequence[tuple[str, type[BaseModel]]] = (
        ("genoffice-docx-openxml-validation-report.schema.json", GenOfficeDocxOpenXmlValidationReport),
        ("genoffice-docx-fidelity-font-baseline-report.schema.json", GenOfficeDocxFidelityFontBaselineReport),
        ("genoffice-docx-fidelity-cdr-manifest.schema.json", GenOfficeDocxFidelityCdrManifest),
        (
            "genoffice-docx-fidelity-visual-comparison-manifest.schema.json",
            GenOfficeDocxFidelityVisualComparisonManifest,
        ),
        ("genoffice-docx-fidelity-execution-receipt.schema.json", GenOfficeDocxFidelityExecutionReceipt),
        (
            "genoffice-docx-fidelity-evidence-verification-report.schema.json",
            GenOfficeDocxFidelityEvidenceVerificationReport,
        ),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(output_root / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def _load_external_model[TModel: BaseModel](path: Path, model: type[TModel]) -> TModel:
    value, _ = _load_model(path, model)
    return value


def load_genoffice_docx_fidelity_verification_inputs(
    input_directory: Path,
) -> tuple[
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelityStudyPlan,
]:
    if input_directory.is_symlink() or not input_directory.is_dir():
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity public input directory is invalid")
    root = input_directory.resolve()
    entries = tuple(root.iterdir())
    if tuple(sorted(entry.name for entry in entries)) != PUBLIC_INPUT_ENTRIES:
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity public input inventory is not exact")
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity public input is not a regular file")
    return (
        _load_external_model(root / "result-envelope.json", GenOfficeDocxFidelitySignedResultEnvelope),
        _load_external_model(root / "signer-policy.json", GenOfficeDocxFidelityResultSignerPolicy),
        _load_external_model(root / "study-plan.json", GenOfficeDocxFidelityStudyPlan),
    )


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_FIDELITY_EVIDENCE_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_docx_fidelity_evidence_schemas(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_EVIDENCE_OUTPUT_DIR"])
            )
        elif mode == "verify":
            output_root = _require_empty_output_directory(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_EVIDENCE_OUTPUT_DIR"])
            )
            envelope, signer_policy, study_plan = load_genoffice_docx_fidelity_verification_inputs(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_INPUT_DIR"])
            )
            result = verify_genoffice_docx_fidelity_evidence_bundle(
                evidence_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_EVIDENCE_ROOT"]),
                envelope=envelope,
                signer_policy=signer_policy,
                study_plan=study_plan,
            )
            _write_new_private(
                output_root / "genoffice-docx-fidelity-evidence-verification-report.json",
                _json_bytes(result),
            )
        else:
            raise GenOfficeDocxFidelityEvidenceError("GenOffice fidelity evidence mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeDocxFidelityEvidenceError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_fidelity_evidence_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
