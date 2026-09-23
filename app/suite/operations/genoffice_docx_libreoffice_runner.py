from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_fidelity_evidence import (
    MAX_EVIDENCE_BYTES,
    GenOfficeDocxFidelityCdrManifest,
    GenOfficeDocxFidelityEvidenceArtifact,
    GenOfficeDocxFidelityExecutionReceipt,
    GenOfficeDocxFidelityFontBaselineReport,
    GenOfficeDocxFidelityVisualComparisonManifest,
    GenOfficeDocxOpenXmlValidationFinding,
    GenOfficeDocxOpenXmlValidationReport,
    build_genoffice_docx_fidelity_cdr_manifest_hash,
    build_genoffice_docx_fidelity_execution_receipt_hash,
    build_genoffice_docx_fidelity_font_baseline_report_hash,
    build_genoffice_docx_fidelity_visual_comparison_manifest_hash,
    build_genoffice_docx_openxml_validation_report_hash,
)
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_FIXTURE_IDS,
    ZERO_HASH,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityStudyPlan,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_payload_hash,
    build_genoffice_docx_fidelity_study_plan,
    build_genoffice_docx_fidelity_study_policy,
    build_genoffice_docx_structural_fingerprint,
    compare_genoffice_docx_rgb_page,
)
from suite.operations.genoffice_docx_quick_edit_preflight import (
    GenOfficeDocxQuickEditCorpusManifest,
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_preflight_policy,
    inspect_genoffice_docx_quick_edit_candidate,
)
from suite.platform.preview_cdr import PreviewCdrPageManifest

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_DOCX_BYTES: Literal[16777216] = 16777216
MAX_PAGE_COUNT: Literal[32] = 32
MAX_PAGE_DIMENSION_PIXELS: Literal[4096] = 4096
RUN_REQUEST_MAX_AGE = timedelta(hours=4)
RUNNER_PIPELINE_STEPS = (
    "source_preflight",
    "libreoffice_docx_roundtrip",
    "output_preflight",
    "output_structural_fingerprint",
    "open_xml_sdk_validation_office2021",
    "same_engine_source_pdf_render",
    "same_engine_candidate_pdf_render",
    "pdftoppm_raw_rgb_144_dpi",
    "integer_visual_measurement",
    "write_once_evidence_receipt",
    "external_ed25519_signature_handoff",
)
RUNNER_IMAGE_PATTERN = re.compile(r"^(?:[a-z0-9][a-z0-9._/:+-]*@)?sha256:[a-f0-9]{64}$")
PPM_HEADER_PATTERN = re.compile(rb"\AP6\n([1-9][0-9]*) ([1-9][0-9]*)\n255\n")
PDF_PAGE_PATTERN = re.compile(r"^Pages:\s+([1-9][0-9]*)\s*$", flags=re.MULTILINE)
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+:/()=-]{0,511}$")
INPUT_TOP_LEVEL_ENTRIES = ("control", "input")
CONTROL_ENTRIES = ("corpus-manifest.json", "run-request.json", "study-plan.json")
OUTPUT_TOP_LEVEL_ENTRIES = ("evidence", "handoff")


class GenOfficeDocxLibreOfficeRunnerError(RuntimeError):
    pass


class GenOfficeDocxLibreOfficeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_libreoffice_run_request.v1"] = "genoffice_docx_libreoffice_run_request.v1"
    request_id: str
    assignment_id: str
    fixture_id: str
    source_filename: str
    source_content_sha256: str
    study_plan_hash: str
    fidelity_policy_hash: str
    preflight_policy_hash: str
    corpus_manifest_hash: str
    runner_image_ref: str
    requested_at_utc: datetime
    expires_at_utc: datetime
    pipeline_steps: tuple[str, ...] = RUNNER_PIPELINE_STEPS
    max_docx_bytes: Literal[16777216] = MAX_DOCX_BYTES
    max_page_count: Literal[32] = MAX_PAGE_COUNT
    max_page_dimension_pixels: Literal[4096] = MAX_PAGE_DIMENSION_PIXELS
    raster_dpi: Literal[144] = 144
    execution_authorization_basis: Literal["explicit_synthetic_study_run_request"] = (
        "explicit_synthetic_study_run_request"
    )
    engine_id: Literal["libreoffice"] = "libreoffice"
    runner_mode: Literal["isolated_headless_worker"] = "isolated_headless_worker"
    source_synthetic: Literal[True] = True
    network_mode: Literal["none"] = "none"
    tenant_content_allowed: Literal[False] = False
    tenant_credentials_allowed: Literal[False] = False
    private_key_allowed: Literal[False] = False
    persistent_product_write_allowed: Literal[False] = False
    external_side_effect_allowed: Literal[False] = False
    engine_execution_allowed: Literal[True] = True
    request_hash: str

    @field_validator("requested_at_utc", "expires_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LibreOffice fidelity run request time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_scope(self) -> GenOfficeDocxLibreOfficeRunRequest:
        if (
            self.request_id != f"run-request:{self.assignment_id}"
            or self.assignment_id != f"libreoffice:{self.fixture_id}"
            or self.fixture_id not in FIDELITY_FIXTURE_IDS
            or self.source_filename != f"{self.fixture_id}.docx"
            or self.pipeline_steps != RUNNER_PIPELINE_STEPS
        ):
            raise ValueError("LibreOffice fidelity run request scope drifted")
        if (
            self.expires_at_utc <= self.requested_at_utc
            or self.expires_at_utc - self.requested_at_utc > RUN_REQUEST_MAX_AGE
        ):
            raise ValueError("LibreOffice fidelity run request lifetime is invalid")
        if not RUNNER_IMAGE_PATTERN.fullmatch(self.runner_image_ref):
            raise ValueError("LibreOffice fidelity runner image is not digest pinned")
        for value in (
            self.source_content_sha256,
            self.study_plan_hash,
            self.fidelity_policy_hash,
            self.preflight_policy_hash,
            self.corpus_manifest_hash,
            self.request_hash,
        ):
            _require_sha256(value)
        return self


class GenOfficeDocxLibreOfficeRunnerReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_libreoffice_runner_report.v1"] = (
        "genoffice_docx_libreoffice_runner_report.v1"
    )
    assignment_id: str
    run_request_hash: str
    runner_image_ref: str
    engine_version: str
    engine_identity_hash: str
    executor_environment_hash: str
    output_docx_sha256: str
    execution_receipt_hash: str
    result_payload_hash: str
    signature_message_sha256: str
    evidence_artifact_count: int = Field(ge=1)
    evidence_total_bytes: int = Field(ge=1, le=MAX_EVIDENCE_BYTES)
    engine_executed: Literal[True] = True
    evidence_materialized: Literal[True] = True
    result_signed: Literal[False] = False
    evidence_independently_verified: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    quick_edit_spike_complete: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    private_key_included: Literal[False] = False
    document_content_in_report: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_unsigned_handoff(self) -> GenOfficeDocxLibreOfficeRunnerReport:
        if not self.assignment_id.startswith("libreoffice:") or not RUNNER_IMAGE_PATTERN.fullmatch(
            self.runner_image_ref
        ):
            raise ValueError("LibreOffice fidelity runner report identity drifted")
        for value in (
            self.run_request_hash,
            self.engine_identity_hash,
            self.executor_environment_hash,
            self.output_docx_sha256,
            self.execution_receipt_hash,
            self.result_payload_hash,
            self.signature_message_sha256,
            self.report_hash,
        ):
            _require_sha256(value)
        return self


class _RawOpenXmlFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error_id: str
    error_type: Literal["schema", "semantic", "package", "markup_compatibility"]
    part_uri: str
    path: str


class _RawOpenXmlReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validator_name: Literal["DocumentFormat.OpenXml"]
    validator_version: str
    target_file_format_version: Literal["Office2021"]
    markup_compatibility_processing_enabled: Literal[True]
    findings: tuple[_RawOpenXmlFinding, ...]


@dataclass(frozen=True)
class RenderedRgbPage:
    page_number: int
    width_pixels: int
    height_pixels: int
    rgb_bytes: bytes


@dataclass(frozen=True)
class LibreOfficeToolIdentity:
    engine_version: str
    rasterizer_version: str
    validator_version: str
    engine_identity_hash: str
    executor_environment_hash: str
    font_inventory: tuple[str, ...]


class LibreOfficeFidelityToolchain(Protocol):
    def identity(self, *, runner_image_ref: str) -> LibreOfficeToolIdentity: ...

    def roundtrip_docx(self, *, source_path: Path, output_path: Path, workspace: Path) -> None: ...

    def render_docx(self, *, docx_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]: ...

    def validate_openxml(self, *, docx_path: Path) -> _RawOpenXmlReport: ...


def _require_sha256(value: str) -> None:
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("LibreOffice fidelity hash is invalid")


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _hash_model(model: BaseModel, *, hash_field: str) -> str:
    return stable_hash(canonical_json(model.model_dump(mode="json", exclude={hash_field})))


def build_genoffice_docx_libreoffice_run_request_hash(request: GenOfficeDocxLibreOfficeRunRequest) -> str:
    return _hash_model(request, hash_field="request_hash")


def build_genoffice_docx_libreoffice_runner_report_hash(report: GenOfficeDocxLibreOfficeRunnerReport) -> str:
    return _hash_model(report, hash_field="report_hash")


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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
        raise GenOfficeDocxLibreOfficeRunnerError(
            f"LibreOffice fidelity output cannot be written: {path.name}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_empty_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {label} directory is invalid")
    root = path.resolve()
    if any(root.iterdir()):
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {label} directory is not empty")
    return root


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity input is not a regular file: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity input size is invalid: {path.name}")
    content = path.read_bytes()
    if len(content) != size:
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity input changed while reading: {path.name}")
    return content


def _strict_json(content: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity JSON contains duplicate keys")
            value[key] = item
        return value

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity JSON is invalid") from exc


def _load_model[TModel: BaseModel](path: Path, model: type[TModel]) -> TModel:
    try:
        return model.model_validate(_strict_json(_read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)))
    except ValidationError as exc:
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity model is invalid: {path.name}") from exc


def build_genoffice_docx_libreoffice_run_request(
    *,
    fixture_id: str,
    runner_image_ref: str,
    requested_at_utc: datetime,
) -> tuple[
    GenOfficeDocxLibreOfficeRunRequest,
    GenOfficeDocxFidelityStudyPlan,
    GenOfficeDocxQuickEditCorpusManifest,
    bytes,
]:
    if requested_at_utc.tzinfo is None or requested_at_utc.utcoffset() is None:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity request time lacks a timezone")
    preflight_policy = build_genoffice_docx_quick_edit_preflight_policy()
    corpus_files, corpus_manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight_policy)
    fidelity_policy = build_genoffice_docx_fidelity_study_policy()
    study_plan = build_genoffice_docx_fidelity_study_plan(
        policy=fidelity_policy,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
    )
    assignments = {assignment.assignment_id: assignment for assignment in study_plan.assignments}
    assignment = assignments.get(f"libreoffice:{fixture_id}")
    if assignment is None:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity fixture is not in the study plan")
    artifacts = {artifact.fixture_id: artifact for artifact in corpus_manifest.artifacts}
    artifact = artifacts[fixture_id]
    source = corpus_files[artifact.filename]
    requested = requested_at_utc.astimezone(UTC)
    draft = GenOfficeDocxLibreOfficeRunRequest(
        request_id=f"run-request:{assignment.assignment_id}",
        assignment_id=assignment.assignment_id,
        fixture_id=fixture_id,
        source_filename=artifact.filename,
        source_content_sha256=artifact.content_sha256,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        preflight_policy_hash=study_plan.preflight_policy_hash,
        corpus_manifest_hash=study_plan.corpus_manifest_hash,
        runner_image_ref=runner_image_ref,
        requested_at_utc=requested,
        expires_at_utc=requested + RUN_REQUEST_MAX_AGE,
        request_hash=ZERO_HASH,
    )
    request = draft.model_copy(update={"request_hash": build_genoffice_docx_libreoffice_run_request_hash(draft)})
    return request, study_plan, corpus_manifest, source


def materialize_genoffice_docx_libreoffice_assignment(
    *,
    output_directory: Path,
    fixture_id: str,
    runner_image_ref: str,
    requested_at_utc: datetime | None = None,
) -> GenOfficeDocxLibreOfficeRunRequest:
    root = _require_empty_directory(output_directory, label="assignment output")
    request, study_plan, corpus_manifest, source = build_genoffice_docx_libreoffice_run_request(
        fixture_id=fixture_id,
        runner_image_ref=runner_image_ref,
        requested_at_utc=requested_at_utc or datetime.now(UTC),
    )
    control = root / "control"
    input_directory = root / "input"
    control.mkdir(mode=0o700)
    input_directory.mkdir(mode=0o700)
    _write_new_private(control / "run-request.json", _json_bytes(request))
    _write_new_private(control / "study-plan.json", _json_bytes(study_plan))
    _write_new_private(control / "corpus-manifest.json", _json_bytes(corpus_manifest))
    _write_new_private(input_directory / request.source_filename, source)
    return request


def _require_exact_directory(path: Path, expected: Sequence[str], *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {label} directory is invalid")
    root = path.resolve()
    entries = tuple(root.iterdir())
    if tuple(sorted(item.name for item in entries)) != tuple(sorted(expected)):
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {label} inventory is not exact")
    if any(item.is_symlink() or not item.is_file() for item in entries):
        raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {label} contains a non-regular file")
    return root


def _load_and_verify_assignment(
    *, input_root: Path, runner_image_ref: str, now_utc: datetime
) -> tuple[GenOfficeDocxLibreOfficeRunRequest, GenOfficeDocxFidelityStudyPlan, bytes]:
    if input_root.is_symlink() or not input_root.is_dir():
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity assignment root is invalid")
    root = input_root.resolve()
    entries = tuple(root.iterdir())
    if tuple(sorted(item.name for item in entries)) != INPUT_TOP_LEVEL_ENTRIES:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity assignment inventory is not exact")
    if any(item.is_symlink() or not item.is_dir() for item in entries):
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity assignment contains an invalid directory")
    control = _require_exact_directory(root / "control", CONTROL_ENTRIES, label="control")
    request = _load_model(control / "run-request.json", GenOfficeDocxLibreOfficeRunRequest)
    study_plan = _load_model(control / "study-plan.json", GenOfficeDocxFidelityStudyPlan)
    corpus_manifest = _load_model(control / "corpus-manifest.json", GenOfficeDocxQuickEditCorpusManifest)
    input_directory = _require_exact_directory(root / "input", (request.source_filename,), label="source")
    source = _read_regular_file(input_directory / request.source_filename, maximum_bytes=request.max_docx_bytes)
    canonical_request, canonical_plan, canonical_manifest, canonical_source = (
        build_genoffice_docx_libreoffice_run_request(
            fixture_id=request.fixture_id,
            runner_image_ref=request.runner_image_ref,
            requested_at_utc=request.requested_at_utc,
        )
    )
    observed_now = now_utc.astimezone(UTC)
    if (
        request != canonical_request
        or study_plan != canonical_plan
        or corpus_manifest != canonical_manifest
        or source != canonical_source
        or runner_image_ref != request.runner_image_ref
        or not request.requested_at_utc <= observed_now <= request.expires_at_utc
    ):
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity assignment binding or lifetime drifted")
    return request, study_plan, source


def _build_page_manifest(page: RenderedRgbPage) -> PreviewCdrPageManifest:
    if (
        page.page_number < 1
        or page.width_pixels < 1
        or page.height_pixels < 1
        or page.width_pixels > MAX_PAGE_DIMENSION_PIXELS
        or page.height_pixels > MAX_PAGE_DIMENSION_PIXELS
        or len(page.rgb_bytes) != page.width_pixels * page.height_pixels * 3
    ):
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity RGB page dimensions are invalid")
    return PreviewCdrPageManifest(
        page_number=page.page_number,
        width_pixels=page.width_pixels,
        height_pixels=page.height_pixels,
        rgb_content_hash=_sha256_bytes(page.rgb_bytes),
        rgb_byte_length=len(page.rgb_bytes),
    )


def _write_cdr(
    *,
    evidence_root: Path,
    directory_name: str,
    request: GenOfficeDocxLibreOfficeRunRequest,
    render_stage: Literal["source_reference", "roundtrip_candidate"],
    rendered_docx_sha256: str,
    font_report: GenOfficeDocxFidelityFontBaselineReport,
    rasterizer_version: str,
    pages: tuple[RenderedRgbPage, ...],
) -> GenOfficeDocxFidelityCdrManifest:
    directory = evidence_root / directory_name
    directory.mkdir(mode=0o700)
    page_manifests = tuple(_build_page_manifest(page) for page in pages)
    draft = GenOfficeDocxFidelityCdrManifest(
        assignment_id=request.assignment_id,
        render_stage=render_stage,
        rendered_docx_sha256=rendered_docx_sha256,
        rasterizer_engine="libreoffice-pdf+pdftoppm",
        rasterizer_version=rasterizer_version,
        font_baseline_report_hash=font_report.report_hash,
        page_count=len(pages),
        raw_rgb_byte_length=sum(len(page.rgb_bytes) for page in pages),
        pages=page_manifests,
        manifest_hash=ZERO_HASH,
    )
    manifest = draft.model_copy(update={"manifest_hash": build_genoffice_docx_fidelity_cdr_manifest_hash(draft)})
    _write_new_private(directory / "manifest.json", _json_bytes(manifest))
    for page, page_manifest in zip(pages, page_manifests, strict=True):
        _write_new_private(directory / page_manifest.filename, page.rgb_bytes)
    return manifest


def _artifact_inventory(root: Path) -> tuple[GenOfficeDocxFidelityEvidenceArtifact, ...]:
    artifacts: list[GenOfficeDocxFidelityEvidenceArtifact] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity evidence contains a symlink")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "execution-receipt.json":
            continue
        content = _read_regular_file(path, maximum_bytes=MAX_EVIDENCE_BYTES)
        total += len(content)
        if total > MAX_EVIDENCE_BYTES:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity evidence exceeds its byte limit")
        artifacts.append(
            GenOfficeDocxFidelityEvidenceArtifact(
                relative_path=relative,
                size_bytes=len(content),
                content_sha256=_sha256_bytes(content),
            )
        )
    return tuple(artifacts)


def run_genoffice_docx_libreoffice_assignment(
    *,
    input_root: Path,
    output_root: Path,
    runner_image_ref: str,
    toolchain: LibreOfficeFidelityToolchain,
    now_utc: datetime | None = None,
) -> GenOfficeDocxLibreOfficeRunnerReport:
    observed_now = now_utc or datetime.now(UTC)
    request, study_plan, source = _load_and_verify_assignment(
        input_root=input_root,
        runner_image_ref=runner_image_ref,
        now_utc=observed_now,
    )
    output = _require_empty_directory(output_root, label="runner output")
    evidence = output / "evidence"
    handoff = output / "handoff"
    evidence.mkdir(mode=0o700)
    handoff.mkdir(mode=0o700)
    started_at = observed_now.astimezone(UTC)
    source_preflight = inspect_genoffice_docx_quick_edit_candidate(
        source,
        policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    if not source_preflight.future_engine_evaluation_eligible:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity source preflight rejected the assignment")
    identity = toolchain.identity(runner_image_ref=runner_image_ref)
    with tempfile.TemporaryDirectory(prefix="libreoffice-fidelity-") as temporary:
        workspace = Path(temporary)
        source_path = input_root.resolve() / "input" / request.source_filename
        output_docx_path = workspace / "roundtrip" / "output.docx"
        output_docx_path.parent.mkdir(mode=0o700)
        toolchain.roundtrip_docx(source_path=source_path, output_path=output_docx_path, workspace=workspace)
        output_docx = _read_regular_file(output_docx_path, maximum_bytes=request.max_docx_bytes)
        output_docx_sha256 = _sha256_bytes(output_docx)
        output_preflight = inspect_genoffice_docx_quick_edit_candidate(
            output_docx,
            policy=build_genoffice_docx_quick_edit_preflight_policy(),
        )
        if not output_preflight.future_engine_evaluation_eligible:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity output preflight rejected the result")
        structural = build_genoffice_docx_structural_fingerprint(
            fixture_id=request.fixture_id,
            content=output_docx,
            preflight_policy=build_genoffice_docx_quick_edit_preflight_policy(),
        )
        raw_openxml = toolchain.validate_openxml(docx_path=output_docx_path)
        reference_pages = toolchain.render_docx(docx_path=source_path, workspace=workspace, stage="source")
        candidate_pages = toolchain.render_docx(docx_path=output_docx_path, workspace=workspace, stage="candidate")
    if (
        not reference_pages
        or len(reference_pages) != len(candidate_pages)
        or len(candidate_pages) > request.max_page_count
        or any(
            (reference.width_pixels, reference.height_pixels) != (candidate.width_pixels, candidate.height_pixels)
            for reference, candidate in zip(reference_pages, candidate_pages, strict=True)
        )
    ):
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity reference and candidate pages do not align")
    if raw_openxml.validator_version != identity.validator_version:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity Open XML validator identity drifted")

    _write_new_private(evidence / "output.docx", output_docx)
    _write_new_private(evidence / "output-preflight-report.json", _json_bytes(output_preflight))
    _write_new_private(evidence / "output-structural-fingerprint-report.json", _json_bytes(structural))

    openxml_findings = tuple(
        GenOfficeDocxOpenXmlValidationFinding(
            error_id=finding.error_id,
            error_type=finding.error_type,
            part_uri=finding.part_uri,
            path_hash=stable_hash(finding.path),
        )
        for finding in raw_openxml.findings
    )
    openxml_draft = GenOfficeDocxOpenXmlValidationReport(
        assignment_id=request.assignment_id,
        engine_id="libreoffice",
        fixture_id=request.fixture_id,
        output_docx_sha256=output_docx_sha256,
        validator_version=raw_openxml.validator_version,
        target_file_format_version=raw_openxml.target_file_format_version,
        findings=tuple(
            sorted(openxml_findings, key=lambda item: (item.part_uri, item.error_type, item.error_id, item.path_hash))
        ),
        validation_error_count=len(openxml_findings),
        schema_conformant=not openxml_findings,
        report_hash=ZERO_HASH,
    )
    openxml = openxml_draft.model_copy(
        update={"report_hash": build_genoffice_docx_openxml_validation_report_hash(openxml_draft)}
    )
    _write_new_private(evidence / "openxml-validation-report.json", _json_bytes(openxml))

    normalized_fonts = tuple(sorted(set(identity.font_inventory)))
    if not normalized_fonts or any(not item.strip() for item in normalized_fonts):
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity font inventory is invalid")
    font_draft = GenOfficeDocxFidelityFontBaselineReport(
        assignment_id=request.assignment_id,
        engine_id="libreoffice",
        runner_mode="isolated_headless_worker",
        engine_version=identity.engine_version,
        engine_identity_hash=identity.engine_identity_hash,
        executor_environment_hash=identity.executor_environment_hash,
        inventory_method="fontconfig_fc_list",
        font_count=len(normalized_fonts),
        normalized_inventory_sha256=stable_hash("\n".join(normalized_fonts)),
        report_hash=ZERO_HASH,
    )
    font = font_draft.model_copy(
        update={"report_hash": build_genoffice_docx_fidelity_font_baseline_report_hash(font_draft)}
    )
    _write_new_private(evidence / "font-baseline-report.json", _json_bytes(font))

    reference_cdr = _write_cdr(
        evidence_root=evidence,
        directory_name="reference-cdr",
        request=request,
        render_stage="source_reference",
        rendered_docx_sha256=request.source_content_sha256,
        font_report=font,
        rasterizer_version=identity.rasterizer_version,
        pages=reference_pages,
    )
    candidate_cdr = _write_cdr(
        evidence_root=evidence,
        directory_name="candidate-cdr",
        request=request,
        render_stage="roundtrip_candidate",
        rendered_docx_sha256=output_docx_sha256,
        font_report=font,
        rasterizer_version=identity.rasterizer_version,
        pages=candidate_pages,
    )
    comparisons = tuple(
        compare_genoffice_docx_rgb_page(
            page_number=reference.page_number,
            width_pixels=reference.width_pixels,
            height_pixels=reference.height_pixels,
            reference_rgb=reference.rgb_bytes,
            candidate_rgb=candidate.rgb_bytes,
        )
        for reference, candidate in zip(reference_pages, candidate_pages, strict=True)
    )
    visual_draft = GenOfficeDocxFidelityVisualComparisonManifest(
        assignment_id=request.assignment_id,
        reference_cdr_manifest_hash=reference_cdr.manifest_hash,
        candidate_cdr_manifest_hash=candidate_cdr.manifest_hash,
        page_comparisons=comparisons,
        page_count=len(comparisons),
        manifest_hash=ZERO_HASH,
    )
    visual = visual_draft.model_copy(
        update={"manifest_hash": build_genoffice_docx_fidelity_visual_comparison_manifest_hash(visual_draft)}
    )
    _write_new_private(evidence / "visual-comparison-manifest.json", _json_bytes(visual))

    completed_at = datetime.now(UTC) if now_utc is None else observed_now.astimezone(UTC)
    artifacts = _artifact_inventory(evidence)
    command_hash = stable_hash(
        canonical_json(
            {
                "pipeline_steps": list(request.pipeline_steps),
                "run_request_hash": request.request_hash,
                "runner_image_ref": runner_image_ref,
            }
        )
    )
    receipt_draft = GenOfficeDocxFidelityExecutionReceipt(
        assignment_id=request.assignment_id,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        engine_id="libreoffice",
        runner_mode="isolated_headless_worker",
        source_content_sha256=request.source_content_sha256,
        output_docx_sha256=output_docx_sha256,
        engine_identity_hash=identity.engine_identity_hash,
        executor_environment_hash=identity.executor_environment_hash,
        authorization_evidence_hash=request.request_hash,
        command_hash=command_hash,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        artifacts=artifacts,
        receipt_hash=ZERO_HASH,
    )
    receipt = receipt_draft.model_copy(
        update={"receipt_hash": build_genoffice_docx_fidelity_execution_receipt_hash(receipt_draft)}
    )
    _write_new_private(evidence / "execution-receipt.json", _json_bytes(receipt))

    payload_draft = GenOfficeDocxFidelityEngineResultPayload(
        result_id=f"result:{request.assignment_id}",
        completed_at_utc=completed_at,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        assignment_id=request.assignment_id,
        engine_id="libreoffice",
        runner_mode="isolated_headless_worker",
        fixture_id=request.fixture_id,
        source_content_sha256=request.source_content_sha256,
        engine_version=identity.engine_version,
        engine_identity_hash=identity.engine_identity_hash,
        executor_environment_hash=identity.executor_environment_hash,
        output_docx_sha256=output_docx_sha256,
        output_preflight_report_hash=output_preflight.report_hash,
        output_structural_fingerprint_hash=structural.report_hash,
        open_xml_validation_report_hash=openxml.report_hash,
        cdr_manifest_hash=candidate_cdr.manifest_hash,
        font_baseline_hash=font.report_hash,
        page_count=len(candidate_pages),
        visual_comparison_manifest_hash=visual.manifest_hash,
        execution_receipt_hash=receipt.receipt_hash,
        payload_hash=ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(payload_draft)}
    )
    signature_message = build_genoffice_docx_fidelity_result_message(payload)
    _write_new_private(handoff / "result-payload.json", _json_bytes(payload))
    _write_new_private(handoff / "result-signature-message.bin", signature_message)
    report_draft = GenOfficeDocxLibreOfficeRunnerReport(
        assignment_id=request.assignment_id,
        run_request_hash=request.request_hash,
        runner_image_ref=runner_image_ref,
        engine_version=identity.engine_version,
        engine_identity_hash=identity.engine_identity_hash,
        executor_environment_hash=identity.executor_environment_hash,
        output_docx_sha256=output_docx_sha256,
        execution_receipt_hash=receipt.receipt_hash,
        result_payload_hash=payload.payload_hash,
        signature_message_sha256=_sha256_bytes(signature_message),
        evidence_artifact_count=len(artifacts),
        evidence_total_bytes=sum(item.size_bytes for item in artifacts),
        report_hash=ZERO_HASH,
    )
    report = report_draft.model_copy(
        update={"report_hash": build_genoffice_docx_libreoffice_runner_report_hash(report_draft)}
    )
    _write_new_private(handoff / "libreoffice-runner-report.json", _json_bytes(report))
    if tuple(sorted(item.name for item in output.iterdir())) != OUTPUT_TOP_LEVEL_ENTRIES:
        raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity runner output inventory drifted")
    return report


class SystemLibreOfficeFidelityToolchain:
    def identity(self, *, runner_image_ref: str) -> LibreOfficeToolIdentity:
        engine_version = self._safe_version(("libreoffice", "--version"), "LibreOffice")
        rasterizer_version = self._safe_version(("pdftoppm", "-v"), "pdftoppm")
        raw_validator = self._run_openxml_validator(Path("/dev/null"), version_only=True)
        font_result = self._run_command(("fc-list", "--format", "%{family}\t%{style}\n"), timeout_seconds=30)
        fonts = tuple(sorted(set(line.strip() for line in font_result.stdout.splitlines() if line.strip())))
        executable = shutil.which("libreoffice")
        if executable is None:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice executable is unavailable")
        launcher = Path(executable).resolve()
        launcher_hash = _sha256_bytes(_read_regular_file(launcher, maximum_bytes=16 * 1024 * 1024))
        engine_identity_hash = stable_hash(
            canonical_json(
                {
                    "engine": "libreoffice",
                    "engine_version": engine_version,
                    "launcher_sha256": launcher_hash,
                    "runner_image_ref": runner_image_ref,
                }
            )
        )
        environment_hash = stable_hash(
            canonical_json(
                {
                    "effective_gid": os.getgid(),
                    "effective_uid": os.getuid(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "runner_image_ref": runner_image_ref,
                    "system": platform.system(),
                    "validator_version": raw_validator.validator_version,
                    "rasterizer_version": rasterizer_version,
                }
            )
        )
        return LibreOfficeToolIdentity(
            engine_version=engine_version,
            rasterizer_version=rasterizer_version,
            validator_version=raw_validator.validator_version,
            engine_identity_hash=engine_identity_hash,
            executor_environment_hash=environment_hash,
            font_inventory=fonts,
        )

    def roundtrip_docx(self, *, source_path: Path, output_path: Path, workspace: Path) -> None:
        generated = self._convert_with_libreoffice(
            input_path=source_path,
            output_extension="docx",
            output_filter="Office Open XML Text",
            workspace=workspace,
            operation="roundtrip",
        )
        generated.replace(output_path)

    def render_docx(self, *, docx_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]:
        pdf = self._convert_with_libreoffice(
            input_path=docx_path,
            output_extension="pdf",
            output_filter="writer_pdf_Export",
            workspace=workspace,
            operation=f"render-{stage}",
        )
        page_info = self._run_command(("pdfinfo", str(pdf)), timeout_seconds=60)
        page_match = PDF_PAGE_PATTERN.search(page_info.stdout)
        if page_match is None:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity PDF page count is unavailable")
        page_count = int(page_match.group(1))
        if page_count < 1 or page_count > MAX_PAGE_COUNT:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity PDF page count exceeds policy")
        raster = workspace / f"raster-{stage}"
        raster.mkdir(mode=0o700)
        prefix = raster / "page"
        self._run_command(
            (
                "pdftoppm",
                "-f",
                "1",
                "-l",
                str(page_count),
                "-r",
                "144",
                "-forcenum",
                str(pdf),
                str(prefix),
            ),
            timeout_seconds=120,
        )
        pages: list[RenderedRgbPage] = []
        for page_number in range(1, page_count + 1):
            ppm_path = raster / f"page-{page_number}.ppm"
            ppm = _read_regular_file(
                ppm_path,
                maximum_bytes=MAX_PAGE_DIMENSION_PIXELS * MAX_PAGE_DIMENSION_PIXELS * 3 + 1024,
            )
            match = PPM_HEADER_PATTERN.match(ppm)
            if match is None:
                raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity PPM header is invalid")
            width = int(match.group(1))
            height = int(match.group(2))
            rgb = ppm[match.end() :]
            pages.append(RenderedRgbPage(page_number, width, height, rgb))
        if any(
            path.name not in {f"page-{index}.ppm" for index in range(1, page_count + 1)} for path in raster.iterdir()
        ):
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity raster inventory is not exact")
        return tuple(pages)

    def validate_openxml(self, *, docx_path: Path) -> _RawOpenXmlReport:
        return self._run_openxml_validator(docx_path)

    def _run_openxml_validator(self, docx_path: Path, *, version_only: bool = False) -> _RawOpenXmlReport:
        if version_only:
            completed = self._run_command(
                ("dotnet", "/opt/collabio-openxml-validator/Collabio.OpenXmlValidator.dll", "--version"),
                timeout_seconds=30,
            )
            try:
                return _RawOpenXmlReport.model_validate(_strict_json(completed.stdout.encode()))
            except ValidationError as exc:
                raise GenOfficeDocxLibreOfficeRunnerError("Open XML validator version report is invalid") from exc
        completed = self._run_command(
            ("dotnet", "/opt/collabio-openxml-validator/Collabio.OpenXmlValidator.dll", str(docx_path)),
            timeout_seconds=60,
        )
        try:
            return _RawOpenXmlReport.model_validate(_strict_json(completed.stdout.encode()))
        except ValidationError as exc:
            raise GenOfficeDocxLibreOfficeRunnerError("Open XML validator output is invalid") from exc

    def _convert_with_libreoffice(
        self,
        *,
        input_path: Path,
        output_extension: str,
        output_filter: str,
        workspace: Path,
        operation: str,
    ) -> Path:
        operation_root = workspace / operation
        output_directory = operation_root / "output"
        profile = operation_root / "profile"
        home = operation_root / "home"
        temporary = operation_root / "tmp"
        for directory in (output_directory, profile / "user", home, temporary):
            directory.mkdir(parents=True, mode=0o700)
        registry = profile / "user" / "registrymodifications.xcu"
        registry.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            "</item></oor:items>",
            encoding="utf-8",
        )
        environment = {
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SAL_DISABLE_JAVA": "1",
            "TMPDIR": str(temporary),
        }
        self._run_command(
            (
                "libreoffice",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                f"{output_extension}:{output_filter}",
                "--outdir",
                str(output_directory),
                str(input_path),
            ),
            timeout_seconds=120,
            environment=environment,
        )
        expected = output_directory / f"{input_path.stem}.{output_extension}"
        entries = tuple(output_directory.iterdir())
        if tuple(item.name for item in entries) != (expected.name,) or expected.is_symlink() or not expected.is_file():
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity conversion output inventory drifted")
        return expected

    def _safe_version(self, command: Sequence[str], tool: str) -> str:
        completed = self._run_command(tuple(command), timeout_seconds=30)
        lines = tuple(line.strip() for line in (completed.stdout or completed.stderr).splitlines() if line.strip())
        value = lines[0] if lines else ""
        if not SAFE_VERSION_PATTERN.fullmatch(value):
            raise GenOfficeDocxLibreOfficeRunnerError(f"LibreOffice fidelity {tool} version is invalid")
        return value

    def _run_command(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: int,
        environment: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=dict(environment) if environment is not None else None,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity tool execution failed") from exc
        output_bytes = len(completed.stdout.encode()) + len(completed.stderr.encode())
        if completed.returncode != 0 or output_bytes > MAX_COMMAND_OUTPUT_BYTES:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity tool rejected the operation")
        return completed


def persist_genoffice_docx_libreoffice_runner_schemas(output_directory: Path) -> dict[str, str]:
    root = _require_empty_directory(output_directory, label="schema output")
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-docx-libreoffice-run-request.schema.json", GenOfficeDocxLibreOfficeRunRequest),
        ("genoffice-docx-libreoffice-runner-report.schema.json", GenOfficeDocxLibreOfficeRunnerReport),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(root / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_docx_libreoffice_runner_schemas(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_OUTPUT_DIR"])
            )
        elif mode == "prepare":
            result = materialize_genoffice_docx_libreoffice_assignment(
                output_directory=Path(os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_OUTPUT_DIR"]),
                fixture_id=os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_FIXTURE_ID"],
                runner_image_ref=os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_RUNNER_IMAGE_REF"],
            )
        elif mode == "run":
            result = run_genoffice_docx_libreoffice_assignment(
                input_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_INPUT_DIR"]),
                output_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_OUTPUT_DIR"]),
                runner_image_ref=os.environ["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_RUNNER_IMAGE_REF"],
                toolchain=SystemLibreOfficeFidelityToolchain(),
            )
        else:
            raise GenOfficeDocxLibreOfficeRunnerError("LibreOffice fidelity runner mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeDocxLibreOfficeRunnerError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_libreoffice_runner_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
