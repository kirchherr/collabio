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
from pathlib import Path

from pydantic import BaseModel, ConfigDict

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

    schema_version: str = "source_object_preview_conversion_engine_self_test.v1"
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
    input_path = _resolve_job_path(input_dir, command.input_filename)
    output_path = _resolve_job_path(output_dir, command.output_filename)
    if not input_path.is_file():
        raise PreviewConversionWorkerError("preview conversion input file is missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise PreviewConversionWorkerError("preview conversion output workspace is not empty")
    source_bytes = input_path.read_bytes()
    if len(source_bytes) != command.source_content_byte_length:
        raise PreviewConversionWorkerError("preview conversion input length mismatch")
    if len(source_bytes) > command.resource_limits.max_input_bytes:
        raise PreviewConversionWorkerError("preview conversion input exceeds admitted size")
    if sha256_bytes(source_bytes) != command.source_content_hash:
        raise PreviewConversionWorkerError("preview conversion input content hash mismatch")

    workspace = Path(tempfile.mkdtemp(prefix="preview-conversion-", dir=output_dir.parent))
    generated_pdf = output_dir / f"{input_path.stem}.pdf"
    try:
        if command.conversion_route == "direct_pdf_viewer":
            output_path.write_bytes(source_bytes)
        elif command.conversion_route == "isolated_office_to_pdf":
            _run_libreoffice(
                input_path=input_path,
                output_dir=output_dir,
                workspace=workspace,
                timeout_seconds=command.resource_limits.wallclock_timeout_seconds,
            )
            if generated_pdf != output_path:
                if not generated_pdf.is_file():
                    raise PreviewConversionWorkerError("preview conversion did not produce the expected PDF")
                generated_pdf.replace(output_path)
        else:
            raise PreviewConversionWorkerError("preview conversion route is not supported")

        converter_version = _safe_tool_version(("libreoffice", "--version"), "libreoffice")
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
        output_bytes = output_path.read_bytes()
        _validate_pdf_bytes(
            pdf_bytes=output_bytes,
            max_output_bytes=command.resource_limits.max_output_bytes,
            max_page_count=command.resource_limits.max_page_count,
            page_count=page_count,
        )
        output_content_hash = sha256_bytes(output_bytes)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    draft = PreviewConversionWorkerResult(
        tenant_id=command.tenant_id,
        source_object_id=command.source_object_id,
        source_version_id=command.source_version_id,
        source_manifest_hash=command.source_manifest_hash,
        source_content_hash=command.source_content_hash,
        command_hash=command.command_hash,
        execution_gate_evidence_hash=command.execution_gate_evidence_hash,
        source_preflight_evidence_hash=command.source_preflight_evidence_hash,
        worker_image_ref=command.worker_image_ref,
        sandbox_runtime_class=sandbox_runtime_class,
        converter_version=converter_version,
        pdf_validator_version=qpdf_version,
        font_baseline_hash=font_baseline_hash,
        output_content_hash=output_content_hash,
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
) -> PreviewConversionWorkerResult:
    envelope = PreviewConversionWorkerEnvelope.model_validate_json(request_path.read_text(encoding="utf-8"))
    font_baseline_hash = build_installed_font_baseline_hash()
    try:
        require_preview_conversion_worker_envelope(
            envelope=envelope,
            configured_worker_image_ref=configured_worker_image_ref,
            configured_runtime_class=configured_runtime_class,
            actual_font_baseline_hash=font_baseline_hash,
        )
    except PreviewConversionBlocked as exc:
        raise PreviewConversionWorkerError("preview conversion envelope was not admitted") from exc
    result = run_preview_conversion(
        command=envelope.command,
        input_dir=input_dir,
        output_dir=output_dir,
        sandbox_runtime_class=configured_runtime_class,
        font_baseline_hash=font_baseline_hash,
    )
    _write_json_atomically(output_dir / "result.json", result.model_dump(mode="json"))
    return result


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
            pdfinfo_validation_passed=result.pdfinfo_validation_passed,
            active_pdf_content_absent=result.active_pdf_content_absent,
            completed_at_utc=result.completed_at_utc,
            report_hash=ZERO_HASH,
        )
        return draft.model_copy(
            update={"report_hash": build_preview_conversion_engine_self_test_report_hash(draft)}
        )


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
    value = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
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
    parser.add_argument("--input-dir", type=Path, default=Path("/job/input"))
    parser.add_argument("--output-dir", type=Path, default=Path("/job/output"))
    parser.add_argument("--report", type=Path)
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
    run_worker_once(
        request_path=args.request,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        configured_worker_image_ref=worker_image_ref,
        configured_runtime_class=runtime_class,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreviewConversionWorkerError:
        print("preview conversion worker failed closed", file=sys.stderr)
        raise SystemExit(1) from None
