from __future__ import annotations

import hashlib
import json
import os
import re
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
MAX_SCRIPT_BYTES = 512 * 1024
MAX_COMMAND_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_DOCX_BYTES: Literal[16777216] = 16777216
MAX_PDF_BYTES: Literal[134217728] = 134217728
MAX_PAGE_COUNT: Literal[32] = 32
MAX_PAGE_DIMENSION_PIXELS: Literal[4096] = 4096
RUN_REQUEST_MAX_AGE = timedelta(hours=8)
SAFE_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+:/()=-]{0,511}$")
PPM_HEADER_PATTERN = re.compile(rb"\AP6\n([1-9][0-9]*) ([1-9][0-9]*)\n255\n")
PDF_PAGE_PATTERN = re.compile(r"^Pages:\s+([1-9][0-9]*)\s*$", flags=re.MULTILINE)
RUNNER_SCRIPT_FILENAME = "Invoke-CollabioWordFidelity.ps1"
INPUT_TOP_LEVEL_ENTRIES = ("control", "input", "runner")
CONTROL_ENTRIES = (
    "corpus-manifest.json",
    "host-readiness-report.json",
    "run-request.json",
    "study-plan.json",
)
HANDOFF_ENTRIES = ("candidate.pdf", "output.docx", "reference.pdf", "word-interactive-receipt.json")
OUTPUT_TOP_LEVEL_ENTRIES = ("evidence", "handoff")
RUNNER_PIPELINE_STEPS = (
    "source_preflight",
    "interactive_windows_session_revalidation",
    "dedicated_local_account_revalidation",
    "winword_outbound_firewall_block_revalidation",
    "office_identity_absence_revalidation",
    "signing_custody_inaccessibility_revalidation",
    "visible_word_client_start",
    "macro_force_disable",
    "read_only_source_open",
    "same_engine_source_pdf_export",
    "explicit_human_confirmation",
    "word_docx_roundtrip_save_as",
    "same_engine_candidate_pdf_export",
    "write_once_public_handoff",
    "source_blind_output_preflight",
    "output_structural_fingerprint",
    "open_xml_sdk_validation_office2021",
    "pdftoppm_raw_rgb_144_dpi",
    "integer_visual_measurement",
    "write_once_evidence_receipt",
    "external_ed25519_signature_handoff",
)
HOST_BLOCKING_REASONS = (
    "dedicated_local_account_not_verified",
    "interactive_user_session_not_verified",
    "office_identity_or_tenant_credentials_present",
    "signing_custody_accessible",
    "winword_not_available",
    "winword_outbound_firewall_block_not_verified",
    "word_process_already_running",
)


class GenOfficeDocxWordRunnerError(RuntimeError):
    pass


class GenOfficeDocxWordHostReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_word_host_readiness_report.v1"] = (
        "genoffice_docx_word_host_readiness_report.v1"
    )
    observed_at_utc: datetime
    runner_script_sha256: str
    operator_account_sid_sha256: str
    word_executable_sha256: str
    word_version: str
    windows_product_name: str
    windows_display_version: str
    windows_build: str
    process_architecture: str
    powershell_version: str
    font_inventory: tuple[str, ...]
    font_count: int = Field(ge=0, le=100000)
    normalized_font_inventory_sha256: str
    network_isolation_rule_sha256: str
    dedicated_local_account_verified: bool
    interactive_user_session_verified: bool
    session_zero_absent: bool
    office_identity_absent: bool
    tenant_credentials_available: bool
    signing_custody_accessible: bool
    winword_installed: bool
    outbound_firewall_block_verified: bool
    word_process_absent: bool
    host_ready: bool
    blocking_reasons: tuple[str, ...]
    source_synthetic_only: Literal[True] = True
    tenant_content_included: Literal[False] = False
    document_content_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Word fidelity host-readiness time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_consistent_readiness(self) -> GenOfficeDocxWordHostReadinessReport:
        fonts = tuple(sorted(set(self.font_inventory)))
        if self.font_inventory != fonts or self.font_count != len(fonts):
            raise ValueError("Word fidelity font inventory is not canonical")
        if self.normalized_font_inventory_sha256 != stable_hash("\n".join(fonts)):
            raise ValueError("Word fidelity font inventory hash is invalid")
        checks = {
            "dedicated_local_account_not_verified": self.dedicated_local_account_verified,
            "interactive_user_session_not_verified": (
                self.interactive_user_session_verified and self.session_zero_absent
            ),
            "office_identity_or_tenant_credentials_present": (
                self.office_identity_absent and not self.tenant_credentials_available
            ),
            "signing_custody_accessible": not self.signing_custody_accessible,
            "winword_not_available": self.winword_installed,
            "winword_outbound_firewall_block_not_verified": self.outbound_firewall_block_verified,
            "word_process_already_running": self.word_process_absent,
        }
        expected = tuple(reason for reason in HOST_BLOCKING_REASONS if not checks[reason])
        if self.blocking_reasons != expected or self.host_ready != (not expected):
            raise ValueError("Word fidelity host-readiness blockers are inconsistent")
        for value in (
            self.runner_script_sha256,
            self.operator_account_sid_sha256,
            self.word_executable_sha256,
            self.normalized_font_inventory_sha256,
            self.network_isolation_rule_sha256,
        ):
            _require_sha256(value)
        for value in (
            self.word_version,
            self.windows_product_name,
            self.windows_display_version,
            self.windows_build,
            self.process_architecture,
            self.powershell_version,
        ):
            if not SAFE_IDENTITY_PATTERN.fullmatch(value):
                raise ValueError("Word fidelity host identity is invalid")
        return self


class GenOfficeDocxWordRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_word_run_request.v1"] = "genoffice_docx_word_run_request.v1"
    request_id: str
    assignment_id: str
    fixture_id: str
    source_filename: str
    source_content_sha256: str
    study_plan_hash: str
    fidelity_policy_hash: str
    preflight_policy_hash: str
    corpus_manifest_hash: str
    host_readiness_report_sha256: str
    runner_script_sha256: str
    operator_account_sid_sha256: str
    word_executable_sha256: str
    network_isolation_rule_sha256: str
    requested_at_utc: datetime
    expires_at_utc: datetime
    pipeline_steps: tuple[str, ...] = RUNNER_PIPELINE_STEPS
    max_docx_bytes: Literal[16777216] = MAX_DOCX_BYTES
    max_pdf_bytes: Literal[134217728] = MAX_PDF_BYTES
    max_page_count: Literal[32] = MAX_PAGE_COUNT
    max_page_dimension_pixels: Literal[4096] = MAX_PAGE_DIMENSION_PIXELS
    raster_dpi: Literal[144] = 144
    execution_authorization_basis: Literal["explicit_synthetic_interactive_study_run_request"] = (
        "explicit_synthetic_interactive_study_run_request"
    )
    engine_id: Literal["microsoft_word"] = "microsoft_word"
    runner_mode: Literal["interactive_windows_client"] = "interactive_windows_client"
    source_synthetic: Literal[True] = True
    interactive_user_session_required: Literal[True] = True
    unattended_execution_allowed: Literal[False] = False
    visible_word_client_required: Literal[True] = True
    explicit_human_confirmation_required: Literal[True] = True
    network_isolation_required: Literal[True] = True
    dedicated_local_account_required: Literal[True] = True
    tenant_content_allowed: Literal[False] = False
    tenant_credentials_allowed: Literal[False] = False
    signing_custody_access_allowed: Literal[False] = False
    private_key_allowed: Literal[False] = False
    persistent_product_write_allowed: Literal[False] = False
    external_side_effect_allowed: Literal[False] = False
    engine_execution_allowed: Literal[True] = True
    request_hash: str

    @field_validator("requested_at_utc", "expires_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Word fidelity run-request time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_scope(self) -> GenOfficeDocxWordRunRequest:
        if (
            self.request_id != f"run-request:{self.assignment_id}"
            or self.assignment_id != f"microsoft_word:{self.fixture_id}"
            or self.fixture_id not in FIDELITY_FIXTURE_IDS
            or self.source_filename != f"{self.fixture_id}.docx"
            or self.pipeline_steps != RUNNER_PIPELINE_STEPS
        ):
            raise ValueError("Word fidelity run-request scope drifted")
        if (
            self.expires_at_utc <= self.requested_at_utc
            or self.expires_at_utc - self.requested_at_utc > RUN_REQUEST_MAX_AGE
        ):
            raise ValueError("Word fidelity run-request lifetime is invalid")
        for value in (
            self.source_content_sha256,
            self.study_plan_hash,
            self.fidelity_policy_hash,
            self.preflight_policy_hash,
            self.corpus_manifest_hash,
            self.host_readiness_report_sha256,
            self.runner_script_sha256,
            self.operator_account_sid_sha256,
            self.word_executable_sha256,
            self.network_isolation_rule_sha256,
            self.request_hash,
        ):
            _require_sha256(value)
        return self


class GenOfficeDocxWordInteractiveReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_word_interactive_receipt.v1"] = "genoffice_docx_word_interactive_receipt.v1"
    assignment_id: str
    run_request_hash: str
    host_readiness_report_sha256: str
    runner_script_sha256: str
    operator_account_sid_sha256: str
    word_executable_sha256: str
    network_isolation_rule_sha256: str
    source_content_sha256: str
    output_docx_sha256: str
    reference_pdf_sha256: str
    candidate_pdf_sha256: str
    word_version: str
    windows_product_name: str
    windows_display_version: str
    windows_build: str
    process_architecture: str
    powershell_version: str
    font_inventory: tuple[str, ...]
    font_count: int = Field(ge=1, le=100000)
    normalized_font_inventory_sha256: str
    started_at_utc: datetime
    human_confirmed_at_utc: datetime
    completed_at_utc: datetime
    engine_id: Literal["microsoft_word"] = "microsoft_word"
    runner_mode: Literal["interactive_windows_client"] = "interactive_windows_client"
    interactive_user_session_verified: Literal[True] = True
    session_zero_absent: Literal[True] = True
    dedicated_local_account_verified: Literal[True] = True
    word_visible_during_execution: Literal[True] = True
    explicit_human_confirmation_verified: Literal[True] = True
    macros_force_disabled: Literal[True] = True
    source_opened_read_only: Literal[True] = True
    add_to_recent_files: Literal[False] = False
    network_isolation_verified: Literal[True] = True
    office_identity_absent: Literal[True] = True
    tenant_credentials_available: Literal[False] = False
    signing_custody_accessible: Literal[False] = False
    source_synthetic: Literal[True] = True
    tenant_content_processed: Literal[False] = False
    persistent_product_version_written: Literal[False] = False
    private_key_included: Literal[False] = False
    document_content_in_receipt: Literal[False] = False

    @field_validator("started_at_utc", "human_confirmed_at_utc", "completed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Word fidelity interactive receipt time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_closed_interactive_receipt(self) -> GenOfficeDocxWordInteractiveReceipt:
        if (
            self.assignment_id.split(":", 1)[0] != "microsoft_word"
            or not self.started_at_utc <= self.human_confirmed_at_utc <= self.completed_at_utc
        ):
            raise ValueError("Word fidelity interactive receipt scope or time is invalid")
        fonts = tuple(sorted(set(self.font_inventory)))
        if self.font_inventory != fonts or self.font_count != len(fonts):
            raise ValueError("Word fidelity interactive font inventory is not canonical")
        if self.normalized_font_inventory_sha256 != stable_hash("\n".join(fonts)):
            raise ValueError("Word fidelity interactive font inventory hash is invalid")
        for value in (
            self.run_request_hash,
            self.host_readiness_report_sha256,
            self.runner_script_sha256,
            self.operator_account_sid_sha256,
            self.word_executable_sha256,
            self.network_isolation_rule_sha256,
            self.source_content_sha256,
            self.output_docx_sha256,
            self.reference_pdf_sha256,
            self.candidate_pdf_sha256,
            self.normalized_font_inventory_sha256,
        ):
            _require_sha256(value)
        for value in (
            self.word_version,
            self.windows_product_name,
            self.windows_display_version,
            self.windows_build,
            self.process_architecture,
            self.powershell_version,
        ):
            if not SAFE_IDENTITY_PATTERN.fullmatch(value):
                raise ValueError("Word fidelity interactive host identity is invalid")
        return self


class GenOfficeDocxWordCollectorReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_word_collector_report.v1"] = "genoffice_docx_word_collector_report.v1"
    assignment_id: str
    run_request_hash: str
    host_readiness_report_sha256: str
    interactive_receipt_sha256: str
    engine_version: str
    engine_identity_hash: str
    executor_environment_hash: str
    collector_identity_hash: str
    output_docx_sha256: str
    execution_receipt_hash: str
    result_payload_hash: str
    signature_message_sha256: str
    evidence_artifact_count: int = Field(ge=1)
    evidence_total_bytes: int = Field(ge=1, le=MAX_EVIDENCE_BYTES)
    interactive_engine_execution_verified: Literal[True] = True
    source_blind_collection_verified: Literal[True] = True
    evidence_materialized: Literal[True] = True
    result_signed: Literal[False] = False
    evidence_independently_verified: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    private_key_included: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_closed_collector(self) -> GenOfficeDocxWordCollectorReport:
        if not self.assignment_id.startswith("microsoft_word:") or not self.engine_version.strip():
            raise ValueError("Word fidelity collector identity is invalid")
        for value in (
            self.run_request_hash,
            self.host_readiness_report_sha256,
            self.interactive_receipt_sha256,
            self.engine_identity_hash,
            self.executor_environment_hash,
            self.collector_identity_hash,
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
    target_file_format_version: str
    markup_compatibility_processing_enabled: Literal[True]
    findings: tuple[_RawOpenXmlFinding, ...]


@dataclass(frozen=True)
class RenderedRgbPage:
    page_number: int
    width_pixels: int
    height_pixels: int
    rgb_bytes: bytes


@dataclass(frozen=True)
class WordCollectorIdentity:
    rasterizer_version: str
    validator_version: str
    collector_identity_hash: str


class WordFidelityCollectorToolchain(Protocol):
    def identity(self) -> WordCollectorIdentity: ...

    def rasterize_pdf(self, *, pdf_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]: ...

    def validate_openxml(self, *, docx_path: Path) -> _RawOpenXmlReport: ...


def _require_sha256(value: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError("Word fidelity SHA-256 value is invalid")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ValueError("Word fidelity SHA-256 value is invalid") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _hash_model(model: BaseModel, *, hash_field: str) -> str:
    return stable_hash(canonical_json(model.model_dump(mode="json", exclude={hash_field})))


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
        raise GenOfficeDocxWordRunnerError(f"Word fidelity output already exists or is unsafe: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_empty_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise GenOfficeDocxWordRunnerError(f"Word fidelity {label} directory is invalid")
    root = path.resolve()
    if any(root.iterdir()):
        raise GenOfficeDocxWordRunnerError(f"Word fidelity {label} directory is not empty")
    return root


def _read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise GenOfficeDocxWordRunnerError(f"Word fidelity input is not a regular file: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > maximum_bytes:
        raise GenOfficeDocxWordRunnerError(f"Word fidelity input size is invalid: {path.name}")
    content = path.read_bytes()
    if len(content) != size:
        raise GenOfficeDocxWordRunnerError(f"Word fidelity input changed while reading: {path.name}")
    return content


def _strict_json(content: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise GenOfficeDocxWordRunnerError("Word fidelity JSON contains duplicate keys")
            value[key] = item
        return value

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeDocxWordRunnerError("Word fidelity JSON is invalid") from exc


def _load_model[TModel: BaseModel](path: Path, model: type[TModel]) -> tuple[TModel, bytes]:
    content = _read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
    try:
        return model.model_validate(_strict_json(content)), content
    except ValidationError as exc:
        raise GenOfficeDocxWordRunnerError(f"Word fidelity model is invalid: {path.name}") from exc


def _require_exact_directory(path: Path, expected: Sequence[str], *, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise GenOfficeDocxWordRunnerError(f"Word fidelity {label} directory is invalid")
    root = path.resolve()
    entries = tuple(root.iterdir())
    if tuple(sorted(item.name for item in entries)) != tuple(sorted(expected)):
        raise GenOfficeDocxWordRunnerError(f"Word fidelity {label} inventory is not exact")
    if any(item.is_symlink() or not item.is_file() for item in entries):
        raise GenOfficeDocxWordRunnerError(f"Word fidelity {label} contains a non-regular file")
    return root


def build_genoffice_docx_word_run_request_hash(request: GenOfficeDocxWordRunRequest) -> str:
    return _hash_model(request, hash_field="request_hash")


def build_genoffice_docx_word_collector_report_hash(report: GenOfficeDocxWordCollectorReport) -> str:
    return _hash_model(report, hash_field="report_hash")


def build_genoffice_docx_word_run_request(
    *,
    fixture_id: str,
    host_readiness: GenOfficeDocxWordHostReadinessReport,
    host_readiness_bytes: bytes,
    runner_script: bytes,
    requested_at_utc: datetime,
) -> tuple[GenOfficeDocxWordRunRequest, GenOfficeDocxFidelityStudyPlan, GenOfficeDocxQuickEditCorpusManifest, bytes]:
    if not host_readiness.host_ready:
        raise GenOfficeDocxWordRunnerError("Word fidelity host is not ready")
    runner_script_sha256 = _sha256_bytes(runner_script)
    if runner_script_sha256 != host_readiness.runner_script_sha256:
        raise GenOfficeDocxWordRunnerError("Word fidelity runner script drifted from host readiness")
    preflight_policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, corpus_manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight_policy)
    policy = build_genoffice_docx_fidelity_study_policy()
    plan = build_genoffice_docx_fidelity_study_plan(
        policy=policy,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
    )
    source_filename = f"{fixture_id}.docx"
    if fixture_id not in FIDELITY_FIXTURE_IDS or source_filename not in files:
        raise GenOfficeDocxWordRunnerError("Word fidelity fixture is invalid")
    assignment = next(item for item in plan.assignments if item.assignment_id == f"microsoft_word:{fixture_id}")
    source = files[source_filename]
    if assignment.source_content_sha256 != _sha256_bytes(source):
        raise GenOfficeDocxWordRunnerError("Word fidelity source binding drifted")
    requested = requested_at_utc.astimezone(UTC)
    draft = GenOfficeDocxWordRunRequest(
        request_id=f"run-request:{assignment.assignment_id}",
        assignment_id=assignment.assignment_id,
        fixture_id=fixture_id,
        source_filename=source_filename,
        source_content_sha256=assignment.source_content_sha256,
        study_plan_hash=plan.plan_hash,
        fidelity_policy_hash=policy.policy_hash,
        preflight_policy_hash=preflight_policy.policy_hash,
        corpus_manifest_hash=corpus_manifest.manifest_hash,
        host_readiness_report_sha256=_sha256_bytes(host_readiness_bytes),
        runner_script_sha256=runner_script_sha256,
        operator_account_sid_sha256=host_readiness.operator_account_sid_sha256,
        word_executable_sha256=host_readiness.word_executable_sha256,
        network_isolation_rule_sha256=host_readiness.network_isolation_rule_sha256,
        requested_at_utc=requested,
        expires_at_utc=requested + RUN_REQUEST_MAX_AGE,
        request_hash=ZERO_HASH,
    )
    request = draft.model_copy(update={"request_hash": build_genoffice_docx_word_run_request_hash(draft)})
    return request, plan, corpus_manifest, source


def materialize_genoffice_docx_word_assignment(
    *,
    output_directory: Path,
    fixture_id: str,
    host_readiness_report_path: Path,
    runner_script_path: Path,
    requested_at_utc: datetime | None = None,
) -> GenOfficeDocxWordRunRequest:
    root = _require_empty_directory(output_directory, label="assignment output")
    host_readiness, host_bytes = _load_model(
        host_readiness_report_path,
        GenOfficeDocxWordHostReadinessReport,
    )
    script = _read_regular_file(runner_script_path, maximum_bytes=MAX_SCRIPT_BYTES)
    request, plan, manifest, source = build_genoffice_docx_word_run_request(
        fixture_id=fixture_id,
        host_readiness=host_readiness,
        host_readiness_bytes=host_bytes,
        runner_script=script,
        requested_at_utc=requested_at_utc or datetime.now(UTC),
    )
    control = root / "control"
    input_directory = root / "input"
    runner = root / "runner"
    for directory in (control, input_directory, runner):
        directory.mkdir(mode=0o700)
    _write_new_private(control / "run-request.json", _json_bytes(request))
    _write_new_private(control / "study-plan.json", _json_bytes(plan))
    _write_new_private(control / "corpus-manifest.json", _json_bytes(manifest))
    _write_new_private(control / "host-readiness-report.json", host_bytes)
    _write_new_private(input_directory / request.source_filename, source)
    _write_new_private(runner / RUNNER_SCRIPT_FILENAME, script)
    return request


def _load_and_verify_assignment(
    *, input_root: Path, now_utc: datetime
) -> tuple[
    GenOfficeDocxWordRunRequest,
    GenOfficeDocxFidelityStudyPlan,
    GenOfficeDocxWordHostReadinessReport,
    bytes,
]:
    if input_root.is_symlink() or not input_root.is_dir():
        raise GenOfficeDocxWordRunnerError("Word fidelity assignment root is invalid")
    root = input_root.resolve()
    entries = tuple(root.iterdir())
    if tuple(sorted(item.name for item in entries)) != INPUT_TOP_LEVEL_ENTRIES:
        raise GenOfficeDocxWordRunnerError("Word fidelity assignment inventory is not exact")
    if any(item.is_symlink() or not item.is_dir() for item in entries):
        raise GenOfficeDocxWordRunnerError("Word fidelity assignment contains an invalid directory")
    control = _require_exact_directory(root / "control", CONTROL_ENTRIES, label="control")
    request, _ = _load_model(control / "run-request.json", GenOfficeDocxWordRunRequest)
    plan, _ = _load_model(control / "study-plan.json", GenOfficeDocxFidelityStudyPlan)
    manifest, _ = _load_model(control / "corpus-manifest.json", GenOfficeDocxQuickEditCorpusManifest)
    host, host_bytes = _load_model(control / "host-readiness-report.json", GenOfficeDocxWordHostReadinessReport)
    input_directory = _require_exact_directory(root / "input", (request.source_filename,), label="source")
    runner_directory = _require_exact_directory(root / "runner", (RUNNER_SCRIPT_FILENAME,), label="runner")
    source = _read_regular_file(input_directory / request.source_filename, maximum_bytes=request.max_docx_bytes)
    script = _read_regular_file(runner_directory / RUNNER_SCRIPT_FILENAME, maximum_bytes=MAX_SCRIPT_BYTES)
    canonical_request, canonical_plan, canonical_manifest, canonical_source = build_genoffice_docx_word_run_request(
        fixture_id=request.fixture_id,
        host_readiness=host,
        host_readiness_bytes=host_bytes,
        runner_script=script,
        requested_at_utc=request.requested_at_utc,
    )
    observed_now = now_utc.astimezone(UTC)
    if (
        request != canonical_request
        or plan != canonical_plan
        or manifest != canonical_manifest
        or source != canonical_source
        or not request.requested_at_utc <= observed_now <= request.expires_at_utc
    ):
        raise GenOfficeDocxWordRunnerError("Word fidelity assignment binding or lifetime drifted")
    return request, plan, host, source


def _load_and_verify_handoff(
    *, handoff_root: Path, request: GenOfficeDocxWordRunRequest, host: GenOfficeDocxWordHostReadinessReport
) -> tuple[GenOfficeDocxWordInteractiveReceipt, bytes, bytes, bytes, bytes]:
    handoff = _require_exact_directory(handoff_root, HANDOFF_ENTRIES, label="interactive handoff")
    receipt, receipt_bytes = _load_model(
        handoff / "word-interactive-receipt.json",
        GenOfficeDocxWordInteractiveReceipt,
    )
    output_docx = _read_regular_file(handoff / "output.docx", maximum_bytes=request.max_docx_bytes)
    reference_pdf = _read_regular_file(handoff / "reference.pdf", maximum_bytes=request.max_pdf_bytes)
    candidate_pdf = _read_regular_file(handoff / "candidate.pdf", maximum_bytes=request.max_pdf_bytes)
    expected = (
        request.assignment_id,
        request.request_hash,
        request.host_readiness_report_sha256,
        request.runner_script_sha256,
        request.operator_account_sid_sha256,
        request.word_executable_sha256,
        request.network_isolation_rule_sha256,
        request.source_content_sha256,
        _sha256_bytes(output_docx),
        _sha256_bytes(reference_pdf),
        _sha256_bytes(candidate_pdf),
        host.word_version,
        host.font_inventory,
        host.normalized_font_inventory_sha256,
    )
    observed = (
        receipt.assignment_id,
        receipt.run_request_hash,
        receipt.host_readiness_report_sha256,
        receipt.runner_script_sha256,
        receipt.operator_account_sid_sha256,
        receipt.word_executable_sha256,
        receipt.network_isolation_rule_sha256,
        receipt.source_content_sha256,
        receipt.output_docx_sha256,
        receipt.reference_pdf_sha256,
        receipt.candidate_pdf_sha256,
        receipt.word_version,
        receipt.font_inventory,
        receipt.normalized_font_inventory_sha256,
    )
    if observed != expected:
        raise GenOfficeDocxWordRunnerError("Word fidelity interactive handoff binding drifted")
    return receipt, receipt_bytes, output_docx, reference_pdf, candidate_pdf


def _build_page_manifest(page: RenderedRgbPage) -> PreviewCdrPageManifest:
    if (
        page.page_number < 1
        or page.width_pixels < 1
        or page.height_pixels < 1
        or page.width_pixels > MAX_PAGE_DIMENSION_PIXELS
        or page.height_pixels > MAX_PAGE_DIMENSION_PIXELS
        or len(page.rgb_bytes) != page.width_pixels * page.height_pixels * 3
    ):
        raise GenOfficeDocxWordRunnerError("Word fidelity RGB page dimensions are invalid")
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
    assignment_id: str,
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
        assignment_id=assignment_id,
        render_stage=render_stage,
        rendered_docx_sha256=rendered_docx_sha256,
        rasterizer_engine="microsoft-word-pdf-export+pdftoppm",
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
            raise GenOfficeDocxWordRunnerError("Word fidelity evidence contains a symlink")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "execution-receipt.json":
            continue
        content = _read_regular_file(path, maximum_bytes=MAX_EVIDENCE_BYTES)
        total += len(content)
        if total > MAX_EVIDENCE_BYTES:
            raise GenOfficeDocxWordRunnerError("Word fidelity evidence exceeds its byte limit")
        artifacts.append(
            GenOfficeDocxFidelityEvidenceArtifact(
                relative_path=relative,
                size_bytes=len(content),
                content_sha256=_sha256_bytes(content),
            )
        )
    return tuple(artifacts)


def _host_engine_identity(host: GenOfficeDocxWordHostReadinessReport) -> tuple[str, str]:
    engine_identity_hash = stable_hash(
        canonical_json(
            {
                "engine": "microsoft_word",
                "word_executable_sha256": host.word_executable_sha256,
                "word_version": host.word_version,
            }
        )
    )
    environment_hash = stable_hash(
        canonical_json(
            {
                "network_isolation_rule_sha256": host.network_isolation_rule_sha256,
                "operator_account_sid_sha256": host.operator_account_sid_sha256,
                "powershell_version": host.powershell_version,
                "process_architecture": host.process_architecture,
                "windows_build": host.windows_build,
                "windows_display_version": host.windows_display_version,
                "windows_product_name": host.windows_product_name,
            }
        )
    )
    return engine_identity_hash, environment_hash


def collect_genoffice_docx_word_assignment(
    *,
    input_root: Path,
    interactive_handoff_root: Path,
    output_root: Path,
    toolchain: WordFidelityCollectorToolchain,
    now_utc: datetime | None = None,
) -> GenOfficeDocxWordCollectorReport:
    observed_now = now_utc or datetime.now(UTC)
    request, study_plan, host, source = _load_and_verify_assignment(input_root=input_root, now_utc=observed_now)
    receipt, receipt_bytes, output_docx, reference_pdf, candidate_pdf = _load_and_verify_handoff(
        handoff_root=interactive_handoff_root,
        request=request,
        host=host,
    )
    if not request.requested_at_utc <= receipt.started_at_utc <= receipt.completed_at_utc <= request.expires_at_utc:
        raise GenOfficeDocxWordRunnerError("Word fidelity interactive execution is outside the request lifetime")
    source_preflight = inspect_genoffice_docx_quick_edit_candidate(
        source,
        policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    output_preflight = inspect_genoffice_docx_quick_edit_candidate(
        output_docx,
        policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    if not source_preflight.future_engine_evaluation_eligible or not output_preflight.future_engine_evaluation_eligible:
        raise GenOfficeDocxWordRunnerError("Word fidelity source or output preflight rejected the assignment")
    output = _require_empty_directory(output_root, label="collector output")
    evidence = output / "evidence"
    handoff = output / "handoff"
    evidence.mkdir(mode=0o700)
    handoff.mkdir(mode=0o700)
    output_docx_sha256 = _sha256_bytes(output_docx)
    structural = build_genoffice_docx_structural_fingerprint(
        fixture_id=request.fixture_id,
        content=output_docx,
        preflight_policy=build_genoffice_docx_quick_edit_preflight_policy(),
    )
    identity = toolchain.identity()
    with tempfile.TemporaryDirectory(prefix="word-fidelity-collector-") as temporary:
        workspace = Path(temporary)
        output_docx_path = workspace / "output.docx"
        reference_pdf_path = workspace / "reference.pdf"
        candidate_pdf_path = workspace / "candidate.pdf"
        output_docx_path.write_bytes(output_docx)
        reference_pdf_path.write_bytes(reference_pdf)
        candidate_pdf_path.write_bytes(candidate_pdf)
        raw_openxml = toolchain.validate_openxml(docx_path=output_docx_path)
        reference_pages = toolchain.rasterize_pdf(
            pdf_path=reference_pdf_path,
            workspace=workspace,
            stage="source",
        )
        candidate_pages = toolchain.rasterize_pdf(
            pdf_path=candidate_pdf_path,
            workspace=workspace,
            stage="candidate",
        )
    if (
        not reference_pages
        or len(reference_pages) != len(candidate_pages)
        or len(candidate_pages) > request.max_page_count
        or any(
            (reference.width_pixels, reference.height_pixels) != (candidate.width_pixels, candidate.height_pixels)
            for reference, candidate in zip(reference_pages, candidate_pages, strict=True)
        )
    ):
        raise GenOfficeDocxWordRunnerError("Word fidelity reference and candidate pages do not align")
    if raw_openxml.validator_version != identity.validator_version:
        raise GenOfficeDocxWordRunnerError("Word fidelity Open XML validator identity drifted")
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
        engine_id="microsoft_word",
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
    engine_identity_hash, environment_hash = _host_engine_identity(host)
    font_draft = GenOfficeDocxFidelityFontBaselineReport(
        assignment_id=request.assignment_id,
        engine_id="microsoft_word",
        runner_mode="interactive_windows_client",
        engine_version=receipt.word_version,
        engine_identity_hash=engine_identity_hash,
        executor_environment_hash=environment_hash,
        inventory_method="windows_font_inventory",
        font_count=receipt.font_count,
        normalized_inventory_sha256=receipt.normalized_font_inventory_sha256,
        report_hash=ZERO_HASH,
    )
    font = font_draft.model_copy(
        update={"report_hash": build_genoffice_docx_fidelity_font_baseline_report_hash(font_draft)}
    )
    _write_new_private(evidence / "font-baseline-report.json", _json_bytes(font))
    reference_cdr = _write_cdr(
        evidence_root=evidence,
        directory_name="reference-cdr",
        assignment_id=request.assignment_id,
        render_stage="source_reference",
        rendered_docx_sha256=request.source_content_sha256,
        font_report=font,
        rasterizer_version=identity.rasterizer_version,
        pages=reference_pages,
    )
    candidate_cdr = _write_cdr(
        evidence_root=evidence,
        directory_name="candidate-cdr",
        assignment_id=request.assignment_id,
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
    artifacts = _artifact_inventory(evidence)
    command_hash = stable_hash(
        canonical_json(
            {
                "collector_identity_hash": identity.collector_identity_hash,
                "interactive_receipt_sha256": _sha256_bytes(receipt_bytes),
                "pipeline_steps": list(request.pipeline_steps),
                "run_request_hash": request.request_hash,
            }
        )
    )
    execution_draft = GenOfficeDocxFidelityExecutionReceipt(
        assignment_id=request.assignment_id,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        engine_id="microsoft_word",
        runner_mode="interactive_windows_client",
        source_content_sha256=request.source_content_sha256,
        output_docx_sha256=output_docx_sha256,
        engine_identity_hash=engine_identity_hash,
        executor_environment_hash=environment_hash,
        authorization_evidence_hash=request.request_hash,
        command_hash=command_hash,
        started_at_utc=receipt.started_at_utc,
        completed_at_utc=receipt.completed_at_utc,
        artifacts=artifacts,
        receipt_hash=ZERO_HASH,
    )
    execution = execution_draft.model_copy(
        update={"receipt_hash": build_genoffice_docx_fidelity_execution_receipt_hash(execution_draft)}
    )
    _write_new_private(evidence / "execution-receipt.json", _json_bytes(execution))
    payload_draft = GenOfficeDocxFidelityEngineResultPayload(
        result_id=f"result:{request.assignment_id}",
        completed_at_utc=receipt.completed_at_utc,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        assignment_id=request.assignment_id,
        engine_id="microsoft_word",
        runner_mode="interactive_windows_client",
        fixture_id=request.fixture_id,
        source_content_sha256=request.source_content_sha256,
        engine_version=receipt.word_version,
        engine_identity_hash=engine_identity_hash,
        executor_environment_hash=environment_hash,
        output_docx_sha256=output_docx_sha256,
        output_preflight_report_hash=output_preflight.report_hash,
        output_structural_fingerprint_hash=structural.report_hash,
        open_xml_validation_report_hash=openxml.report_hash,
        cdr_manifest_hash=candidate_cdr.manifest_hash,
        font_baseline_hash=font.report_hash,
        page_count=len(candidate_pages),
        visual_comparison_manifest_hash=visual.manifest_hash,
        execution_receipt_hash=execution.receipt_hash,
        payload_hash=ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(payload_draft)}
    )
    signature_message = build_genoffice_docx_fidelity_result_message(payload)
    _write_new_private(handoff / "result-payload.json", _json_bytes(payload))
    _write_new_private(handoff / "result-signature-message.bin", signature_message)
    report_draft = GenOfficeDocxWordCollectorReport(
        assignment_id=request.assignment_id,
        run_request_hash=request.request_hash,
        host_readiness_report_sha256=request.host_readiness_report_sha256,
        interactive_receipt_sha256=_sha256_bytes(receipt_bytes),
        engine_version=receipt.word_version,
        engine_identity_hash=engine_identity_hash,
        executor_environment_hash=environment_hash,
        collector_identity_hash=identity.collector_identity_hash,
        output_docx_sha256=output_docx_sha256,
        execution_receipt_hash=execution.receipt_hash,
        result_payload_hash=payload.payload_hash,
        signature_message_sha256=_sha256_bytes(signature_message),
        evidence_artifact_count=len(artifacts),
        evidence_total_bytes=sum(item.size_bytes for item in artifacts),
        report_hash=ZERO_HASH,
    )
    report = report_draft.model_copy(
        update={"report_hash": build_genoffice_docx_word_collector_report_hash(report_draft)}
    )
    _write_new_private(handoff / "word-collector-report.json", _json_bytes(report))
    if tuple(sorted(item.name for item in output.iterdir())) != OUTPUT_TOP_LEVEL_ENTRIES:
        raise GenOfficeDocxWordRunnerError("Word fidelity collector output inventory drifted")
    return report


class SystemWordFidelityCollectorToolchain:
    def identity(self) -> WordCollectorIdentity:
        rasterizer_version = self._safe_version(("pdftoppm", "-v"), "pdftoppm")
        validator = self._run_openxml_validator(Path("/dev/null"), version_only=True)
        collector_identity_hash = stable_hash(
            canonical_json(
                {
                    "rasterizer_version": rasterizer_version,
                    "validator_version": validator.validator_version,
                }
            )
        )
        return WordCollectorIdentity(
            rasterizer_version=rasterizer_version,
            validator_version=validator.validator_version,
            collector_identity_hash=collector_identity_hash,
        )

    def rasterize_pdf(self, *, pdf_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]:
        info = self._run_command(("pdfinfo", str(pdf_path)), timeout_seconds=60)
        page_match = PDF_PAGE_PATTERN.search(info.stdout)
        if page_match is None:
            raise GenOfficeDocxWordRunnerError("Word fidelity PDF page count is unavailable")
        page_count = int(page_match.group(1))
        if page_count < 1 or page_count > MAX_PAGE_COUNT:
            raise GenOfficeDocxWordRunnerError("Word fidelity PDF page count exceeds policy")
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
                str(pdf_path),
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
                raise GenOfficeDocxWordRunnerError("Word fidelity PPM header is invalid")
            width = int(match.group(1))
            height = int(match.group(2))
            pages.append(RenderedRgbPage(page_number, width, height, ppm[match.end() :]))
        expected_names = {f"page-{index}.ppm" for index in range(1, page_count + 1)}
        if {path.name for path in raster.iterdir()} != expected_names:
            raise GenOfficeDocxWordRunnerError("Word fidelity raster inventory is not exact")
        return tuple(pages)

    def validate_openxml(self, *, docx_path: Path) -> _RawOpenXmlReport:
        return self._run_openxml_validator(docx_path)

    def _run_openxml_validator(self, docx_path: Path, *, version_only: bool = False) -> _RawOpenXmlReport:
        command = (
            "dotnet",
            "/opt/collabio-openxml-validator/Collabio.OpenXmlValidator.dll",
            "--version" if version_only else str(docx_path),
        )
        completed = self._run_command(command, timeout_seconds=60)
        try:
            return _RawOpenXmlReport.model_validate(_strict_json(completed.stdout.encode()))
        except ValidationError as exc:
            raise GenOfficeDocxWordRunnerError("Word fidelity Open XML validator output is invalid") from exc

    def _safe_version(self, command: Sequence[str], tool: str) -> str:
        completed = self._run_command(tuple(command), timeout_seconds=30)
        lines = tuple(line.strip() for line in (completed.stdout or completed.stderr).splitlines() if line.strip())
        value = lines[0] if lines else ""
        if not SAFE_IDENTITY_PATTERN.fullmatch(value):
            raise GenOfficeDocxWordRunnerError(f"Word fidelity {tool} version is invalid")
        return value

    def _run_command(self, command: tuple[str, ...], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GenOfficeDocxWordRunnerError("Word fidelity collector tool execution failed") from exc
        output_bytes = len(completed.stdout.encode()) + len(completed.stderr.encode())
        if completed.returncode != 0 or output_bytes > MAX_COMMAND_OUTPUT_BYTES:
            raise GenOfficeDocxWordRunnerError("Word fidelity collector tool rejected the operation")
        return completed


def persist_genoffice_docx_word_runner_schemas(output_directory: Path) -> dict[str, str]:
    root = _require_empty_directory(output_directory, label="schema output")
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-docx-word-host-readiness-report.schema.json", GenOfficeDocxWordHostReadinessReport),
        ("genoffice-docx-word-run-request.schema.json", GenOfficeDocxWordRunRequest),
        ("genoffice-docx-word-interactive-receipt.schema.json", GenOfficeDocxWordInteractiveReceipt),
        ("genoffice-docx-word-collector-report.schema.json", GenOfficeDocxWordCollectorReport),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(root / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_FIDELITY_WORD_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_docx_word_runner_schemas(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_OUTPUT_DIR"])
            )
        elif mode == "prepare":
            result = materialize_genoffice_docx_word_assignment(
                output_directory=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_OUTPUT_DIR"]),
                fixture_id=os.environ["SUITE_GENOFFICE_FIDELITY_WORD_FIXTURE_ID"],
                host_readiness_report_path=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_HOST_REPORT_PATH"]),
                runner_script_path=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_RUNNER_SCRIPT_PATH"]),
            )
        elif mode == "collect":
            result = collect_genoffice_docx_word_assignment(
                input_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_INPUT_DIR"]),
                interactive_handoff_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_HANDOFF_DIR"]),
                output_root=Path(os.environ["SUITE_GENOFFICE_FIDELITY_WORD_OUTPUT_DIR"]),
                toolchain=SystemWordFidelityCollectorToolchain(),
            )
        else:
            raise GenOfficeDocxWordRunnerError("Word fidelity runner mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeDocxWordRunnerError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_word_runner_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
