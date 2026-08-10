from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from suite.platform.preview_cdr import (
    PREVIEW_CDR_PROFILE_REF,
    PreviewCdrBundleManifest,
    PreviewCdrPageManifest,
    build_preview_cdr_manifest_hash,
    require_preview_cdr_bundle,
)

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.source_object_preview_conversion import (
    ZERO_HASH,
    PreviewConversionBlocked,
    PreviewConversionCommand,
    PreviewConversionResourceLimits,
    PreviewConversionWorkerEnvelope,
    PreviewConversionWorkerResult,
    build_preview_conversion_command_hash,
    build_preview_conversion_result_hash,
    require_preview_conversion_worker_envelope,
)
from suite.storage.source_objects import SourceObjectType, sha256_bytes

ACTIVE_PDF_TOKENS = (
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/EmbeddedFile",
    b"/RichMedia",
)
ACTIVE_PDF_NAMES = frozenset(
    {
        "/AA",
        "/EmbeddedFile",
        "/EmbeddedFiles",
        "/GoToE",
        "/GoToR",
        "/ImportData",
        "/JavaScript",
        "/JS",
        "/Launch",
        "/OpenAction",
        "/RichMedia",
        "/SubmitForm",
        "/URI",
    }
)
PPM_HEADER_PATTERN = re.compile(rb"\AP6\n([1-9][0-9]*) ([1-9][0-9]*)\n255\n")
CDR_RASTER_DPI = 144
CDR_MAXIMUM_PAGE_DIMENSION_PIXELS = 4096
MEBIBYTE = 1024 * 1024
QPDF_JSON_MAX_BYTES = 64 * 1024 * 1024
PDF_PAGE_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", flags=re.MULTILINE)
SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+:/()-]{0,255}$")
ENGINE_SELF_TEST_IMAGE_REF = "local/preview-converter@sha256:" + ("f" * 64)
ENGINE_SELF_TEST_GATE_HASH = "sha256:" + ("e" * 64)
ENGINE_SELF_TEST_PREFLIGHT_HASH = "sha256:" + ("d" * 64)


class PreviewConversionWorkerError(RuntimeError):
    pass


class PreviewConversionEngineSelfTestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "source_object_preview_conversion_engine_self_test.v2"
    development_only: bool = True
    production_execution_gate_evaluated: bool = False
    source_fixture_type: str = "synthetic_rtf"
    source_fixture_included: bool = False
    output_included: bool = False
    external_network_used: bool = False
    converter_engine: str
    converter_version: str
    pdf_validator_engine: str
    pdf_validator_version: str
    font_baseline_hash: str
    output_content_hash: str
    output_content_byte_length: int
    page_count: int
    cdr_profile_ref: str
    cdr_manifest_hash: str
    cdr_page_count: int = Field(ge=1)
    pixel_reconstruction_passed: bool
    cdr_trust_boundary_separated: bool = False
    qpdf_validation_passed: bool
    pdfinfo_validation_passed: bool
    active_pdf_content_absent: bool
    completed_at_utc: datetime
    report_hash: str


def run_preview_conversion(
    *,
    command: PreviewConversionCommand,
    input_dir: Path,
    output_dir: Path,
    sandbox_runtime_class: str,
    font_baseline_hash: str,
) -> PreviewConversionWorkerResult:
    _require_empty_directory(output_dir, "preview conversion output workspace")
    with tempfile.TemporaryDirectory(prefix="preview-cdr-combined-") as directory:
        cdr_dir = Path(directory) / "cdr"
        manifest = render_preview_to_cdr_bundle(
            command=command,
            input_dir=input_dir,
            cdr_dir=cdr_dir,
            font_baseline_hash=font_baseline_hash,
        )
        return rebuild_preview_from_cdr_bundle(
            command=command,
            manifest=manifest,
            cdr_dir=cdr_dir,
            output_dir=output_dir,
            sandbox_runtime_class=sandbox_runtime_class,
            cdr_trust_boundary_separated=False,
        )


def render_preview_to_cdr_bundle(
    *,
    command: PreviewConversionCommand,
    input_dir: Path,
    cdr_dir: Path,
    font_baseline_hash: str,
) -> PreviewCdrBundleManifest:
    input_path = _resolve_job_path(input_dir, command.input_filename)
    if not input_path.is_file():
        raise PreviewConversionWorkerError("preview conversion input file is missing")
    _require_empty_directory(cdr_dir, "preview CDR output workspace")
    source_bytes = input_path.read_bytes()
    if len(source_bytes) != command.source_content_byte_length:
        raise PreviewConversionWorkerError("preview conversion input length mismatch")
    if len(source_bytes) > command.resource_limits.max_input_bytes:
        raise PreviewConversionWorkerError("preview conversion input exceeds admitted size")
    if sha256_bytes(source_bytes) != command.source_content_hash:
        raise PreviewConversionWorkerError("preview conversion input content hash mismatch")

    workspace = _create_preview_conversion_workspace()
    try:
        intermediate_pdf = _render_intermediate_pdf(
            command=command,
            input_path=input_path,
            source_bytes=source_bytes,
            workspace=workspace,
        )
        converter_version = _safe_tool_version(("libreoffice", "--version"), "libreoffice")
        rasterizer_version = _safe_tool_version(("pdftoppm", "-v"), "pdftoppm")
        _run_qpdf_check(
            output_path=intermediate_pdf,
            timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
        )
        page_count = _read_pdf_page_count(
            output_path=intermediate_pdf,
            timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
        )
        if page_count < 1 or page_count > command.resource_limits.max_page_count:
            raise PreviewConversionWorkerError("preview CDR source page count exceeds admitted limit")
        ppm_paths = _run_pdftoppm(
            input_pdf=intermediate_pdf,
            workspace=workspace,
            page_count=page_count,
            timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
        )
        page_manifests: list[PreviewCdrPageManifest] = []
        total_rgb_bytes = 0
        for page_number, ppm_path in enumerate(ppm_paths, start=1):
            width, height, rgb_bytes = _read_poppler_ppm(ppm_path)
            total_rgb_bytes += len(rgb_bytes)
            if total_rgb_bytes > command.resource_limits.temporary_storage_megabytes * MEBIBYTE:
                raise PreviewConversionWorkerError("preview CDR RGB output exceeds admitted temporary storage")
            page = PreviewCdrPageManifest(
                page_number=page_number,
                width_pixels=width,
                height_pixels=height,
                rgb_content_hash=sha256_bytes(rgb_bytes),
                rgb_byte_length=len(rgb_bytes),
            )
            (cdr_dir / page.filename).write_bytes(rgb_bytes)
            page_manifests.append(page)
        draft = PreviewCdrBundleManifest(
            tenant_id=command.tenant_id,
            source_object_id=command.source_object_id,
            source_version_id=command.source_version_id,
            source_manifest_hash=command.source_manifest_hash,
            source_content_hash=command.source_content_hash,
            command_hash=command.command_hash,
            execution_gate_evidence_hash=command.execution_gate_evidence_hash,
            source_preflight_evidence_hash=command.source_preflight_evidence_hash,
            worker_image_ref=command.worker_image_ref,
            document_converter_version=converter_version,
            rasterizer_version=rasterizer_version,
            font_baseline_hash=font_baseline_hash,
            raster_dpi=CDR_RASTER_DPI,
            maximum_page_dimension_pixels=CDR_MAXIMUM_PAGE_DIMENSION_PIXELS,
            page_count=page_count,
            raw_rgb_byte_length=total_rgb_bytes,
            pages=tuple(page_manifests),
            completed_at_utc=datetime.now(UTC),
            manifest_hash=ZERO_HASH,
        )
        manifest = draft.model_copy(update={"manifest_hash": build_preview_cdr_manifest_hash(draft)})
        _write_json_atomically(cdr_dir / "manifest.json", manifest.model_dump(mode="json"))
        return manifest
    except Exception:
        _clear_directory(cdr_dir)
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def rebuild_preview_from_cdr_bundle(
    *,
    command: PreviewConversionCommand,
    manifest: PreviewCdrBundleManifest,
    cdr_dir: Path,
    output_dir: Path,
    sandbox_runtime_class: str,
    cdr_trust_boundary_separated: bool = True,
) -> PreviewConversionWorkerResult:
    _require_cdr_manifest_bindings(command=command, manifest=manifest)
    page_paths = require_preview_cdr_bundle(
        manifest=manifest,
        bundle_dir=cdr_dir,
        maximum_raw_rgb_bytes=command.resource_limits.temporary_storage_megabytes * MEBIBYTE,
    )
    _require_empty_directory(output_dir, "preview conversion output workspace")
    output_path = _resolve_job_path(output_dir, command.output_filename)
    workspace = _create_preview_conversion_workspace()
    try:
        pillow_version = _reconstruct_pdf_from_rgb(
            manifest=manifest,
            page_paths=page_paths,
            output_path=output_path,
        )
        qpdf_version = _safe_tool_version(("qpdf", "--version"), "qpdf")
        _run_qpdf_check(output_path=output_path, timeout_seconds=command.resource_limits.wallclock_timeout_seconds)
        _run_qpdf_active_content_check(
            output_path=output_path,
            json_path=workspace / "qpdf-objects.json",
            timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
        )
        page_count = _read_pdf_page_count(
            output_path=output_path,
            timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
        )
        if page_count != manifest.page_count:
            raise PreviewConversionWorkerError("preview CDR reconstructed page count mismatch")
        output_bytes = output_path.read_bytes()
        _validate_pdf_bytes(
            pdf_bytes=output_bytes,
            max_output_bytes=command.resource_limits.max_output_bytes,
            max_page_count=command.resource_limits.max_page_count,
            page_count=page_count,
        )
    except Exception:
        _clear_directory(output_dir)
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    draft = PreviewConversionWorkerResult(
        schema_version=(
            "source_object_preview_conversion_result.v3"
            if cdr_trust_boundary_separated
            else "source_object_preview_conversion_result.v2"
        ),
        tenant_id=command.tenant_id,
        source_object_id=command.source_object_id,
        source_version_id=command.source_version_id,
        source_manifest_hash=command.source_manifest_hash,
        source_content_hash=command.source_content_hash,
        command_hash=command.command_hash,
        execution_gate_evidence_hash=command.execution_gate_evidence_hash,
        source_preflight_evidence_hash=command.source_preflight_evidence_hash,
        production_admission_gate_hash=command.production_admission_gate_hash,
        worker_image_ref=command.worker_image_ref,
        sandbox_runtime_class=sandbox_runtime_class,
        converter_engine="libreoffice+pdftoppm+pillow",
        converter_version=f"{manifest.document_converter_version} / {manifest.rasterizer_version} / Pillow {pillow_version}",
        pdf_validator_version=qpdf_version,
        font_baseline_hash=manifest.font_baseline_hash,
        cdr_profile_ref=PREVIEW_CDR_PROFILE_REF,
        cdr_manifest_hash=manifest.manifest_hash,
        cdr_page_count=manifest.page_count,
        pixel_reconstruction_passed=True,
        cdr_fail_closed_verified=True,
        cdr_trust_boundary_separated=cdr_trust_boundary_separated,
        source_bytes_accessible_to_cdr_rebuilder=not cdr_trust_boundary_separated,
        output_content_hash=sha256_bytes(output_bytes),
        output_content_byte_length=len(output_bytes),
        page_count=page_count,
        source_hash_verified=True,
        output_hash_verified=True,
        qpdf_validation_passed=True,
        pdfinfo_validation_passed=True,
        active_pdf_content_absent=True,
        temporary_workspace_destroyed=not workspace.exists(),
        completed_at_utc=datetime.now(UTC),
        result_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"result_hash": build_preview_conversion_result_hash(draft)})


def run_worker_once(
    *,
    request_path: Path,
    input_dir: Path,
    output_dir: Path,
    configured_worker_image_ref: str,
    configured_runtime_class: str,
    production_admission_required: bool = False,
    production_admission_path: Path | None = None,
    production_evidence_path: Path | None = None,
    production_recovery_report_path: Path | None = None,
    production_attestation_path: Path | None = None,
    production_signer_policy_path: Path | None = None,
) -> PreviewConversionWorkerResult:
    if production_admission_required:
        raise PreviewConversionWorkerError("combined preview conversion is forbidden for production admission")
    envelope, font_baseline_hash = _load_admitted_worker_envelope(
        request_path=request_path,
        configured_worker_image_ref=configured_worker_image_ref,
        configured_runtime_class=configured_runtime_class,
        production_admission_required=production_admission_required,
        production_admission_path=production_admission_path,
        production_evidence_path=production_evidence_path,
        production_recovery_report_path=production_recovery_report_path,
        production_attestation_path=production_attestation_path,
        production_signer_policy_path=production_signer_policy_path,
    )
    result = run_preview_conversion(
        command=envelope.command,
        input_dir=input_dir,
        output_dir=output_dir,
        sandbox_runtime_class=configured_runtime_class,
        font_baseline_hash=font_baseline_hash,
    )
    _write_json_atomically(output_dir / "result.json", result.model_dump(mode="json"))
    return result


def run_cdr_renderer_once(
    *,
    request_path: Path,
    input_dir: Path,
    cdr_dir: Path,
    configured_worker_image_ref: str,
    configured_runtime_class: str,
    **admission_paths: Any,
) -> PreviewCdrBundleManifest:
    envelope, font_baseline_hash = _load_admitted_worker_envelope(
        request_path=request_path,
        configured_worker_image_ref=configured_worker_image_ref,
        configured_runtime_class=configured_runtime_class,
        **admission_paths,
    )
    return render_preview_to_cdr_bundle(
        command=envelope.command,
        input_dir=input_dir,
        cdr_dir=cdr_dir,
        font_baseline_hash=font_baseline_hash,
    )


def run_cdr_rebuilder_once(
    *,
    request_path: Path,
    cdr_dir: Path,
    output_dir: Path,
    configured_worker_image_ref: str,
    configured_runtime_class: str,
    **admission_paths: Any,
) -> PreviewConversionWorkerResult:
    envelope, _ = _load_admitted_worker_envelope(
        request_path=request_path,
        configured_worker_image_ref=configured_worker_image_ref,
        configured_runtime_class=configured_runtime_class,
        **admission_paths,
    )
    manifest = PreviewCdrBundleManifest.model_validate_json(
        (cdr_dir / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.font_baseline_hash != envelope.execution_gate.font_baseline_hash:
        raise PreviewConversionWorkerError("preview CDR manifest font baseline does not match the execution gate")
    if manifest.cdr_profile_ref != envelope.execution_gate.cdr_profile_ref:
        raise PreviewConversionWorkerError("preview CDR manifest profile does not match the execution gate")
    result = rebuild_preview_from_cdr_bundle(
        command=envelope.command,
        manifest=manifest,
        cdr_dir=cdr_dir,
        output_dir=output_dir,
        sandbox_runtime_class=configured_runtime_class,
    )
    _write_json_atomically(output_dir / "result.json", result.model_dump(mode="json"))
    return result


def _load_admitted_worker_envelope(
    *,
    request_path: Path,
    configured_worker_image_ref: str,
    configured_runtime_class: str,
    production_admission_required: bool = False,
    production_admission_path: Path | None = None,
    production_evidence_path: Path | None = None,
    production_recovery_report_path: Path | None = None,
    production_attestation_path: Path | None = None,
    production_signer_policy_path: Path | None = None,
) -> tuple[PreviewConversionWorkerEnvelope, str]:
    envelope = PreviewConversionWorkerEnvelope.model_validate_json(request_path.read_text(encoding="utf-8"))
    font_baseline_hash = build_installed_font_baseline_hash()
    try:
        require_preview_conversion_worker_envelope(
            envelope=envelope,
            configured_worker_image_ref=configured_worker_image_ref,
            configured_runtime_class=configured_runtime_class,
            actual_font_baseline_hash=font_baseline_hash,
        )
        if (
            envelope.execution_gate.cdr_profile_ref != PREVIEW_CDR_PROFILE_REF
            or envelope.source_preflight.cdr_profile_ref != PREVIEW_CDR_PROFILE_REF
        ):
            raise PreviewConversionBlocked("preview conversion CDR profile does not match the worker")
    except PreviewConversionBlocked as exc:
        raise PreviewConversionWorkerError("preview conversion envelope was not admitted") from exc
    try:
        if production_admission_required:
            if (
                production_admission_path is None
                or production_evidence_path is None
                or production_recovery_report_path is None
                or production_attestation_path is None
                or production_signer_policy_path is None
            ):
                raise PreviewConversionWorkerError("preview conversion production admission evidence is missing")
            from suite.operations.preview_conversion_production_admission import (
                load_and_require_preview_conversion_production_admission,
            )

            load_and_require_preview_conversion_production_admission(
                command=envelope.command,
                execution_gate=envelope.execution_gate,
                production_gate_path=production_admission_path,
                evidence_bundle_path=production_evidence_path,
                recovery_report_path=production_recovery_report_path,
                attestation_path=production_attestation_path,
                signer_policy_path=production_signer_policy_path,
            )
    except (OSError, ValueError) as exc:
        raise PreviewConversionWorkerError("preview conversion production admission failed closed") from exc
    return envelope, font_baseline_hash


def _create_preview_conversion_workspace() -> Path:
    temporary_root = Path(tempfile.gettempdir())
    if temporary_root.is_symlink() or not temporary_root.is_dir():
        raise PreviewConversionWorkerError("preview conversion temporary root is invalid")
    resolved_root = temporary_root.resolve()
    workspace = Path(tempfile.mkdtemp(prefix="preview-conversion-", dir=resolved_root))
    if workspace.parent != resolved_root:
        shutil.rmtree(workspace, ignore_errors=True)
        raise PreviewConversionWorkerError("preview conversion temporary workspace escaped its root")
    return workspace


def build_installed_font_baseline_hash() -> str:
    completed = _run_command(
        ("fc-list", "--format", "%{file}\t%{family}\t%{style}\n"),
        timeout_seconds=30,
    )
    lines = sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())
    if not lines:
        raise PreviewConversionWorkerError("preview conversion font baseline is empty")
    return stable_hash("\n".join(lines))


def run_engine_self_test() -> PreviewConversionEngineSelfTestReport:
    with tempfile.TemporaryDirectory(prefix="preview-engine-self-test-") as directory:
        root = Path(directory)
        input_dir = root / "input"
        output_dir = root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        source_bytes = (
            b"{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Liberation Sans;}}"
            b"\\fs24 Collabio isolated preview conversion self-test.}"
        )
        input_path = input_dir / "source.rtf"
        input_path.write_bytes(source_bytes)
        font_baseline_hash = build_installed_font_baseline_hash()
        command = _build_engine_self_test_command(source_bytes=source_bytes)
        result = run_preview_conversion(
            command=command,
            input_dir=input_dir,
            output_dir=output_dir,
            sandbox_runtime_class="development-engine-smoke",
            font_baseline_hash=font_baseline_hash,
        )
        draft = PreviewConversionEngineSelfTestReport(
            converter_engine=result.converter_engine,
            converter_version=result.converter_version,
            pdf_validator_engine=result.pdf_validator_engine,
            pdf_validator_version=result.pdf_validator_version,
            font_baseline_hash=result.font_baseline_hash,
            output_content_hash=result.output_content_hash,
            output_content_byte_length=result.output_content_byte_length,
            page_count=result.page_count,
            qpdf_validation_passed=result.qpdf_validation_passed,
            cdr_profile_ref=result.cdr_profile_ref,
            cdr_manifest_hash=result.cdr_manifest_hash,
            cdr_page_count=result.cdr_page_count,
            pixel_reconstruction_passed=result.pixel_reconstruction_passed,
            cdr_trust_boundary_separated=result.cdr_trust_boundary_separated,
            pdfinfo_validation_passed=result.pdfinfo_validation_passed,
            active_pdf_content_absent=result.active_pdf_content_absent,
            completed_at_utc=result.completed_at_utc,
            report_hash=ZERO_HASH,
        )
        return draft.model_copy(update={"report_hash": build_preview_conversion_engine_self_test_report_hash(draft)})


def build_preview_conversion_engine_self_test_report_hash(report: PreviewConversionEngineSelfTestReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def _build_engine_self_test_command(*, source_bytes: bytes) -> PreviewConversionCommand:
    draft = PreviewConversionCommand(
        tenant_id="engine-self-test",
        source_object_id="synthetic-rtf",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        source_mime_type="application/rtf",
        source_manifest_hash="sha256:" + ("a" * 64),
        source_content_hash=sha256_bytes(source_bytes),
        source_content_byte_length=len(source_bytes),
        source_acl_version=1,
        preview_slot_id="document-body",
        preview_policy_id="preview-self-test",
        adapter_id="canonical-pdf-libreoffice-pdfjs.v1",
        adapter_descriptor_hash="sha256:" + ("b" * 64),
        adapter_plan_hash="sha256:" + ("c" * 64),
        conversion_route="isolated_office_to_pdf",
        renderer_release_gate_evidence_hash="sha256:" + ("9" * 64),
        execution_gate_evidence_hash=ENGINE_SELF_TEST_GATE_HASH,
        source_preflight_evidence_hash=ENGINE_SELF_TEST_PREFLIGHT_HASH,
        worker_image_ref=ENGINE_SELF_TEST_IMAGE_REF,
        resource_limits=PreviewConversionResourceLimits(
            max_input_bytes=1024 * 1024,
            max_output_bytes=8 * 1024 * 1024,
            max_page_count=10,
            wallclock_timeout_seconds=60,
            memory_limit_megabytes=1024,
            temporary_storage_megabytes=256,
        ),
        input_filename="source.rtf",
        requested_by="engine-self-test",
        requested_at_utc=datetime.now(UTC),
        reason_hash="sha256:" + ("8" * 64),
        idempotency_key_hash="sha256:" + ("7" * 64),
        command_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"command_hash": build_preview_conversion_command_hash(draft)})


def _run_libreoffice(
def _render_intermediate_pdf(
    *,
    command: PreviewConversionCommand,
    input_path: Path,
    source_bytes: bytes,
    workspace: Path,
) -> Path:
    rendered_dir = workspace / "rendered"
    rendered_dir.mkdir(mode=0o700)
    intermediate_pdf = workspace / "intermediate.pdf"
    if command.conversion_route == "direct_pdf_viewer":
        intermediate_pdf.write_bytes(source_bytes)
        return intermediate_pdf
    if command.conversion_route != "isolated_office_to_pdf":
        raise PreviewConversionWorkerError("preview conversion route is not supported")
    _run_libreoffice(
        input_path=input_path,
        output_dir=rendered_dir,
        workspace=workspace,
        timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
    )
    generated_pdf = rendered_dir / f"{input_path.stem}.pdf"
    if not generated_pdf.is_file():
        raise PreviewConversionWorkerError("preview conversion did not produce the expected intermediate PDF")
    generated_pdf.replace(intermediate_pdf)
    return intermediate_pdf


def _run_pdftoppm(
    *,
    input_pdf: Path,
    workspace: Path,
    page_count: int,
    timeout_seconds: int,
) -> tuple[Path, ...]:
    raster_dir = workspace / "raster"
    raster_dir.mkdir(mode=0o700)
    prefix = raster_dir / "page"
    completed = _run_command(
        (
            "pdftoppm",
            "-f",
            "1",
            "-l",
            str(page_count),
            "-r",
            str(CDR_RASTER_DPI),
            "-scale-to",
            str(CDR_MAXIMUM_PAGE_DIMENSION_PIXELS),
            "-forcenum",
            str(input_pdf),
            str(prefix),
        ),
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0:
        raise PreviewConversionWorkerError("pdftoppm failed to rasterize preview source")
    numbered_paths: list[tuple[int, Path]] = []
    for path in raster_dir.iterdir():
        match = re.fullmatch(r"page-([1-9][0-9]*)\.ppm", path.name)
        if match is None or path.is_symlink() or not path.is_file():
            raise PreviewConversionWorkerError("pdftoppm produced an unexpected raster entry")
        numbered_paths.append((int(match.group(1)), path))
    numbered_paths.sort(key=lambda item: item[0])
    if tuple(number for number, _ in numbered_paths) != tuple(range(1, page_count + 1)):
        raise PreviewConversionWorkerError("pdftoppm raster page sequence is incomplete")
    return tuple(path for _, path in numbered_paths)


def _read_poppler_ppm(path: Path) -> tuple[int, int, bytes]:
    maximum_size = CDR_MAXIMUM_PAGE_DIMENSION_PIXELS**2 * 3 + 64
    if path.stat().st_size > maximum_size:
        raise PreviewConversionWorkerError("preview CDR raster page exceeds admitted dimensions")
    payload = path.read_bytes()
    match = PPM_HEADER_PATTERN.match(payload)
    if match is None:
        raise PreviewConversionWorkerError("preview CDR raster page has an invalid PPM header")
    width = int(match.group(1))
    height = int(match.group(2))
    if width > CDR_MAXIMUM_PAGE_DIMENSION_PIXELS or height > CDR_MAXIMUM_PAGE_DIMENSION_PIXELS:
        raise PreviewConversionWorkerError("preview CDR raster page exceeds admitted dimensions")
    rgb_bytes = payload[match.end() :]
    if len(rgb_bytes) != width * height * 3:
        raise PreviewConversionWorkerError("preview CDR raster page has an invalid RGB length")
    return width, height, rgb_bytes


def _reconstruct_pdf_from_rgb(
    *,
    manifest: PreviewCdrBundleManifest,
    page_paths: tuple[Path, ...],
    output_path: Path,
) -> str:
    try:
        from PIL import Image, __version__ as pillow_version  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PreviewConversionWorkerError("preview CDR PDF reconstruction engine is unavailable") from exc
    images: list[Any] = []
    temporary_output = output_path.with_suffix(".pdf.tmp")
    try:
        for page, page_path in zip(manifest.pages, page_paths, strict=True):
            rgb_bytes = page_path.read_bytes()
            image = Image.frombytes("RGB", (page.width_pixels, page.height_pixels), rgb_bytes)
            images.append(image)
        if not images:
            raise PreviewConversionWorkerError("preview CDR bundle contains no pages")
        images[0].save(
            temporary_output,
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=float(manifest.raster_dpi),
            quality=90,
            subsampling=0,
            optimize=True,
        )
        temporary_output.replace(output_path)
    except (OSError, ValueError) as exc:
        raise PreviewConversionWorkerError("preview CDR PDF reconstruction failed") from exc
    finally:
        for image in images:
            image.close()
        temporary_output.unlink(missing_ok=True)
    return str(pillow_version)


def _require_cdr_manifest_bindings(
    *,
    command: PreviewConversionCommand,
    manifest: PreviewCdrBundleManifest,
) -> None:
    bindings = (
        manifest.tenant_id == command.tenant_id,
        manifest.source_object_id == command.source_object_id,
        manifest.source_version_id == command.source_version_id,
        manifest.source_manifest_hash == command.source_manifest_hash,
        manifest.source_content_hash == command.source_content_hash,
        manifest.command_hash == command.command_hash,
        manifest.execution_gate_evidence_hash == command.execution_gate_evidence_hash,
        manifest.source_preflight_evidence_hash == command.source_preflight_evidence_hash,
        manifest.worker_image_ref == command.worker_image_ref,
        manifest.cdr_profile_ref == PREVIEW_CDR_PROFILE_REF,
    )
    if not all(bindings):
        raise PreviewConversionWorkerError("preview CDR manifest is not bound to the conversion command")


def _require_empty_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise PreviewConversionWorkerError(f"{label} is a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or any(path.iterdir()):
        raise PreviewConversionWorkerError(f"{label} is not empty")


def _clear_directory(path: Path) -> None:
    if path.is_symlink() or not path.exists():
        return
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


    *,
    input_path: Path,
    output_dir: Path,
    workspace: Path,
    timeout_seconds: int,
) -> None:
    profile_dir = workspace / "libreoffice-profile"
    home_dir = workspace / "home"
    tmp_dir = workspace / "tmp"
    profile_dir.mkdir(mode=0o700)
    home_dir.mkdir(mode=0o700)
    tmp_dir.mkdir(mode=0o700)
    profile_uri = profile_dir.resolve().as_uri()
    environment = {
        "HOME": str(home_dir),
        "TMPDIR": str(tmp_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    completed = _run_command(
        (
            "libreoffice",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(input_path),
        ),
        timeout_seconds=timeout_seconds,
        environment=environment,
    )
    if completed.returncode != 0:
        raise PreviewConversionWorkerError("LibreOffice conversion failed")


def _run_qpdf_check(*, output_path: Path, timeout_seconds: int) -> None:
    completed = _run_command(
        ("qpdf", "--check", "--no-warn", str(output_path)),
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0:
        raise PreviewConversionWorkerError("qpdf rejected preview output")


def _run_qpdf_active_content_check(*, output_path: Path, json_path: Path, timeout_seconds: int) -> None:
    completed = _run_command(
        (
            "qpdf",
            "--json=2",
            "--json-stream-data=none",
            "--no-warn",
            str(output_path),
            str(json_path),
        ),
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0 or not json_path.is_file():
        raise PreviewConversionWorkerError("qpdf object inspection rejected preview output")
    if json_path.stat().st_size > QPDF_JSON_MAX_BYTES:
        raise PreviewConversionWorkerError("qpdf object inspection exceeds admitted size")
    try:
        qpdf_objects = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreviewConversionWorkerError("qpdf object inspection produced invalid evidence") from exc
    if _qpdf_json_contains_active_content(qpdf_objects):
        raise PreviewConversionWorkerError("preview conversion PDF contains active content")


def _qpdf_json_contains_active_content(value: object) -> bool:
    if isinstance(value, str):
        return value in ACTIVE_PDF_NAMES
    if isinstance(value, list):
        return any(_qpdf_json_contains_active_content(item) for item in value)
    if isinstance(value, dict):
        return any(key in ACTIVE_PDF_NAMES or _qpdf_json_contains_active_content(item) for key, item in value.items())
    return False


def _read_pdf_page_count(*, output_path: Path, timeout_seconds: int) -> int:
    completed = _run_command(("pdfinfo", str(output_path)), timeout_seconds=timeout_seconds)
    if completed.returncode != 0:
        raise PreviewConversionWorkerError("pdfinfo rejected preview output")
    match = PDF_PAGE_PATTERN.search(completed.stdout)
    if match is None:
        raise PreviewConversionWorkerError("pdfinfo did not report a page count")
    return int(match.group(1))


def _validate_pdf_bytes(
    *,
    pdf_bytes: bytes,
    max_output_bytes: int,
    max_page_count: int,
    page_count: int,
) -> None:
    if not pdf_bytes.startswith(b"%PDF-") or b"%%EOF" not in pdf_bytes[-4096:]:
        raise PreviewConversionWorkerError("preview conversion output is not a complete PDF")
    if len(pdf_bytes) > max_output_bytes:
        raise PreviewConversionWorkerError("preview conversion output exceeds admitted size")
    if page_count < 1 or page_count > max_page_count:
        raise PreviewConversionWorkerError("preview conversion page count exceeds admitted limit")
    if any(token in pdf_bytes for token in ACTIVE_PDF_TOKENS):
        raise PreviewConversionWorkerError("preview conversion PDF contains active content")


def _safe_tool_version(command: tuple[str, ...], expected_name: str) -> str:
    completed = _run_command(command, timeout_seconds=15)
    version_lines = [
        line.strip() for line in (completed.stdout + "\n" + completed.stderr).splitlines() if line.strip()
    ]
    value = version_lines[0] if version_lines else ""
    if completed.returncode != 0 or expected_name.lower() not in value.lower():
        raise PreviewConversionWorkerError(f"{expected_name} version attestation failed")
    if not SAFE_VERSION_PATTERN.fullmatch(value):
        raise PreviewConversionWorkerError(f"{expected_name} version output was not safe")
    return value


def _run_command(
    command: tuple[str, ...],
    *,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreviewConversionWorkerError("preview conversion tool execution failed") from exc


def _resolve_job_path(root: Path, filename: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / filename).resolve()
    if candidate.parent != resolved_root:
        raise PreviewConversionWorkerError("preview conversion path escaped the job directory")
    return candidate


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary_path.replace(path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Isolated Collabio source preview conversion worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--engine-self-test", action="store_true")
    parser.add_argument("--request", type=Path, default=Path("/job/input/request.json"))
    mode.add_argument("--render-cdr-bundle", action="store_true")
    mode.add_argument("--rebuild-cdr-bundle", action="store_true")
    parser.add_argument("--input-dir", type=Path, default=Path("/job/input"))
    parser.add_argument("--output-dir", type=Path, default=Path("/job/output"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cdr-dir", type=Path, default=Path("/job/cdr"))
    parser.add_argument("--production-admission-required", action="store_true")
    parser.add_argument("--production-admission", type=Path)
    parser.add_argument("--production-evidence", type=Path)
    parser.add_argument("--production-recovery-report", type=Path)
    parser.add_argument("--production-attestation", type=Path)
    parser.add_argument("--production-signer-policy", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.engine_self_test:
        report = run_engine_self_test()
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
        if args.report is not None:
            _write_json_atomically(args.report, report.model_dump(mode="json"))
        return 0
    worker_image_ref = os.getenv("SUITE_PREVIEW_CONVERTER_IMAGE_REF", "").strip().lower()
    runtime_class = os.getenv("SUITE_PREVIEW_SANDBOX_RUNTIME_CLASS", "").strip()
    if not worker_image_ref or not runtime_class:
        raise PreviewConversionWorkerError("preview conversion worker runtime attestation is missing")
    admission_paths = {
        "production_admission_required": args.production_admission_required,
        "production_admission_path": args.production_admission,
        "production_evidence_path": args.production_evidence,
        "production_recovery_report_path": args.production_recovery_report,
        "production_attestation_path": args.production_attestation,
        "production_signer_policy_path": args.production_signer_policy,
    }
    if args.render_cdr_bundle:
        run_cdr_renderer_once(
            request_path=args.request,
            input_dir=args.input_dir,
            cdr_dir=args.cdr_dir,
            configured_worker_image_ref=worker_image_ref,
            configured_runtime_class=runtime_class,
            **admission_paths,
        )
    elif args.rebuild_cdr_bundle:
        run_cdr_rebuilder_once(
            request_path=args.request,
            cdr_dir=args.cdr_dir,
            output_dir=args.output_dir,
            configured_worker_image_ref=worker_image_ref,
            configured_runtime_class=runtime_class,
            **admission_paths,
        )
    else:
        run_worker_once(
            request_path=args.request,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            configured_worker_image_ref=worker_image_ref,
            configured_runtime_class=runtime_class,
            production_admission_required=args.production_admission_required,
            production_admission_path=args.production_admission,
            production_evidence_path=args.production_evidence,
            production_recovery_report_path=args.production_recovery_report,
            production_attestation_path=args.production_attestation,
            production_signer_policy_path=args.production_signer_policy,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError):
        print("preview conversion worker failed closed", file=sys.stderr)
        raise SystemExit(1) from None
