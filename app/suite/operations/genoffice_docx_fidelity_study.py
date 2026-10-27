from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_docx_quick_edit_preflight import (
    GenOfficeDocxQuickEditCorpusManifest,
    GenOfficeDocxQuickEditPreflightPolicy,
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_preflight_policy,
    inspect_genoffice_docx_quick_edit_candidate,
)

ZERO_HASH = "sha256:" + "0" * 64
PUBLIC_KEY_SIZE_BYTES = 32
SIGNATURE_SIZE_BYTES = 64
RESULT_SIGNATURE_DOMAIN = b"collabio.genoffice_docx_fidelity_result.v1\n"
EngineId = Literal["microsoft_word", "libreoffice", "genoffice"]
RunnerMode = Literal["interactive_windows_client", "isolated_headless_worker", "authorized_runsc_kvm_worker"]
FidelityAxis = Literal[
    "ooxml_schema_conformance",
    "semantic_feature_preservation",
    "package_structure_preservation",
    "markup_compatibility_preservation",
    "visual_layout_measurement",
    "source_blind_security_revalidation",
]
FIDELITY_FIXTURE_IDS = (
    "formatting-table-fidelity",
    "headers-comments-footnotes-fidelity",
    "unknown-markup-passthrough",
)
FIDELITY_ENGINE_IDS: tuple[EngineId, ...] = ("microsoft_word", "libreoffice", "genoffice")
FIDELITY_AXES: tuple[FidelityAxis, ...] = (
    "ooxml_schema_conformance",
    "semantic_feature_preservation",
    "package_structure_preservation",
    "markup_compatibility_preservation",
    "visual_layout_measurement",
    "source_blind_security_revalidation",
)
READINESS_BLOCKERS = (
    "two_person_runtime_authorization_absent",
    "attested_executable_genoffice_harness_absent",
    "microsoft_word_interactive_runner_evidence_absent",
    "libreoffice_isolated_runner_evidence_absent",
    "result_signer_policy_absent",
    "signed_cross_engine_result_matrix_absent",
    "open_xml_validation_evidence_absent",
    "cdr_linked_visual_comparison_absent",
    "visual_thresholds_uncalibrated",
    "human_fidelity_review_absent",
)


class GenOfficeDocxFidelityStudyError(ValueError):
    pass


class GenOfficeDocxFidelityEngineTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_id: EngineId
    runner_mode: RunnerMode
    unattended_execution_allowed: bool
    interactive_user_session_required: bool
    runtime_authorization_required: bool
    network_mode: Literal["none"] = "none"
    synthetic_content_only: Literal[True] = True
    tenant_credentials_allowed: Literal[False] = False

    @model_validator(mode="after")
    def require_exact_runner_boundary(self) -> GenOfficeDocxFidelityEngineTarget:
        expected = {
            "microsoft_word": ("interactive_windows_client", False, True, False),
            "libreoffice": ("isolated_headless_worker", True, False, False),
            "genoffice": ("authorized_runsc_kvm_worker", True, False, True),
        }[self.engine_id]
        observed = (
            self.runner_mode,
            self.unattended_execution_allowed,
            self.interactive_user_session_required,
            self.runtime_authorization_required,
        )
        if observed != expected:
            raise ValueError("GenOffice fidelity engine runner boundary drifted")
        return self


class GenOfficeDocxFidelityStudyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_study_policy.v1"] = "genoffice_docx_fidelity_study_policy.v1"
    policy_id: Literal["genoffice-docx-fidelity-study-v1"] = "genoffice-docx-fidelity-study-v1"
    engine_targets: tuple[GenOfficeDocxFidelityEngineTarget, ...]
    fixture_ids: tuple[str, ...] = FIDELITY_FIXTURE_IDS
    fidelity_axes: tuple[FidelityAxis, ...] = FIDELITY_AXES
    open_xml_sdk_validation_required: Literal[True] = True
    markup_compatibility_validation_required: Literal[True] = True
    exact_engine_identity_required: Literal[True] = True
    exact_font_baseline_required: Literal[True] = True
    cdr_profile_ref: Literal["collabio-pixel-cdr:raw-rgb.v1"] = "collabio-pixel-cdr:raw-rgb.v1"
    raster_dpi: Literal[144] = 144
    signed_result_envelope_required: Literal[True] = True
    source_blind_revalidation_required: Literal[True] = True
    human_visual_review_required: Literal[True] = True
    calibrated_visual_thresholds_available: Literal[False] = False
    automated_layout_acceptance_allowed: Literal[False] = False
    compatibility_claims_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    policy_hash: str

    @model_validator(mode="after")
    def require_closed_policy(self) -> GenOfficeDocxFidelityStudyPolicy:
        if tuple(target.engine_id for target in self.engine_targets) != FIDELITY_ENGINE_IDS:
            raise ValueError("GenOffice fidelity engine inventory is not exact")
        if self.fixture_ids != FIDELITY_FIXTURE_IDS or self.fidelity_axes != FIDELITY_AXES:
            raise ValueError("GenOffice fidelity study scope is not exact")
        _require_sha256(self.policy_hash, field="fidelity study policy hash")
        return self


class GenOfficeDocxFidelityRunAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignment_id: str
    engine_id: EngineId
    runner_mode: RunnerMode
    fixture_id: str
    source_content_sha256: str
    required_fidelity_axes: tuple[FidelityAxis, ...] = FIDELITY_AXES
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def require_exact_assignment(self) -> GenOfficeDocxFidelityRunAssignment:
        expected_id = f"{self.engine_id}:{self.fixture_id}"
        if self.assignment_id != expected_id or self.fixture_id not in FIDELITY_FIXTURE_IDS:
            raise ValueError("GenOffice fidelity assignment identity is invalid")
        expected_mode = {
            "microsoft_word": "interactive_windows_client",
            "libreoffice": "isolated_headless_worker",
            "genoffice": "authorized_runsc_kvm_worker",
        }[self.engine_id]
        if self.runner_mode != expected_mode or self.required_fidelity_axes != FIDELITY_AXES:
            raise ValueError("GenOffice fidelity assignment runner or axes drifted")
        _require_sha256(self.source_content_sha256, field="fidelity assignment source hash")
        return self


class GenOfficeDocxFidelityStudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_study_plan.v1"] = "genoffice_docx_fidelity_study_plan.v1"
    study_id: Literal["genoffice-docx-fidelity-study-01"] = "genoffice-docx-fidelity-study-01"
    fidelity_policy_hash: str
    preflight_policy_hash: str
    corpus_manifest_hash: str
    assignments: tuple[GenOfficeDocxFidelityRunAssignment, ...]
    assignment_count: Literal[9] = 9
    synthetic_content_only: Literal[True] = True
    tenant_content_included: Literal[False] = False
    engine_execution_authorized: Literal[False] = False
    plan_hash: str

    @model_validator(mode="after")
    def require_exact_matrix(self) -> GenOfficeDocxFidelityStudyPlan:
        expected = tuple(f"{engine}:{fixture}" for engine in FIDELITY_ENGINE_IDS for fixture in FIDELITY_FIXTURE_IDS)
        if tuple(item.assignment_id for item in self.assignments) != expected:
            raise ValueError("GenOffice fidelity study assignment matrix is not exact")
        for value, field in (
            (self.fidelity_policy_hash, "fidelity plan policy hash"),
            (self.preflight_policy_hash, "fidelity plan preflight hash"),
            (self.corpus_manifest_hash, "fidelity plan corpus hash"),
            (self.plan_hash, "fidelity study plan hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxSemanticFeatureCount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str
    count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_feature_id(self) -> GenOfficeDocxSemanticFeatureCount:
        if not self.feature_id.strip():
            raise ValueError("GenOffice fidelity feature ID is empty")
        return self


class GenOfficeDocxStructuralFingerprintReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_structural_fingerprint_report.v1"] = (
        "genoffice_docx_structural_fingerprint_report.v1"
    )
    fixture_id: str
    input_sha256: str
    input_size_bytes: int = Field(ge=1)
    preflight_report_hash: str
    part_count: int = Field(ge=1)
    xml_part_count: int = Field(ge=1)
    relationship_count: int = Field(ge=0)
    part_name_inventory_hash: str
    content_type_inventory_hash: str
    relationship_inventory_hash: str
    semantic_features: tuple[GenOfficeDocxSemanticFeatureCount, ...]
    package_content_included: Literal[False] = False
    document_text_included: Literal[False] = False
    archive_extracted_to_filesystem: Literal[False] = False
    external_network_used: Literal[False] = False
    engine_executed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_metadata_only_fingerprint(self) -> GenOfficeDocxStructuralFingerprintReport:
        if self.fixture_id not in FIDELITY_FIXTURE_IDS:
            raise ValueError("GenOffice structural fingerprint fixture is not in the fidelity scope")
        if tuple(sorted(item.feature_id for item in self.semantic_features)) != tuple(
            item.feature_id for item in self.semantic_features
        ):
            raise ValueError("GenOffice structural fingerprint features are not canonical")
        for value, field in (
            (self.input_sha256, "structural fingerprint input hash"),
            (self.preflight_report_hash, "structural fingerprint preflight hash"),
            (self.part_name_inventory_hash, "structural part-name inventory hash"),
            (self.content_type_inventory_hash, "structural content-type inventory hash"),
            (self.relationship_inventory_hash, "structural relationship inventory hash"),
            (self.report_hash, "structural fingerprint report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityBaselineReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_baseline_report.v1"] = "genoffice_docx_fidelity_baseline_report.v1"
    study_plan_hash: str
    preflight_policy_hash: str
    corpus_manifest_hash: str
    fixture_fingerprints: tuple[GenOfficeDocxStructuralFingerprintReport, ...]
    fixture_count: Literal[3] = 3
    engine_output_included: Literal[False] = False
    tenant_content_included: Literal[False] = False
    engine_executed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_complete_baseline(self) -> GenOfficeDocxFidelityBaselineReport:
        if tuple(item.fixture_id for item in self.fixture_fingerprints) != FIDELITY_FIXTURE_IDS:
            raise ValueError("GenOffice fidelity baseline fixture inventory is not exact")
        for value, field in (
            (self.study_plan_hash, "fidelity baseline plan hash"),
            (self.preflight_policy_hash, "fidelity baseline preflight hash"),
            (self.corpus_manifest_hash, "fidelity baseline corpus hash"),
            (self.report_hash, "fidelity baseline report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxRgbPageComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_rgb_page_comparison_report.v1"] = (
        "genoffice_docx_rgb_page_comparison_report.v1"
    )
    page_number: int = Field(ge=1, le=10000)
    width_pixels: int = Field(ge=1, le=4096)
    height_pixels: int = Field(ge=1, le=4096)
    reference_rgb_sha256: str
    candidate_rgb_sha256: str
    total_pixels: int = Field(ge=1)
    changed_pixels: int = Field(ge=0)
    changed_pixel_ratio_ppm: int = Field(ge=0, le=1_000_000)
    mean_absolute_channel_delta_ppm: int = Field(ge=0, le=1_000_000)
    maximum_channel_delta: int = Field(ge=0, le=255)
    exact_pixel_match: bool
    raw_rgb_content_included: Literal[False] = False
    automated_acceptance_allowed: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_consistent_measurement(self) -> GenOfficeDocxRgbPageComparisonReport:
        if self.total_pixels != self.width_pixels * self.height_pixels or self.changed_pixels > self.total_pixels:
            raise ValueError("GenOffice RGB comparison dimensions or counts are inconsistent")
        if self.exact_pixel_match != (self.changed_pixels == 0 and self.maximum_channel_delta == 0):
            raise ValueError("GenOffice RGB exact-match result is inconsistent")
        for value, field in (
            (self.reference_rgb_sha256, "RGB reference hash"),
            (self.candidate_rgb_sha256, "RGB candidate hash"),
            (self.report_hash, "RGB comparison report hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityEngineResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_engine_result_payload.v1"] = (
        "genoffice_docx_fidelity_engine_result_payload.v1"
    )
    result_id: str
    completed_at_utc: datetime
    study_plan_hash: str
    fidelity_policy_hash: str
    assignment_id: str
    engine_id: EngineId
    runner_mode: RunnerMode
    fixture_id: str
    source_content_sha256: str
    engine_version: str
    engine_identity_hash: str
    executor_environment_hash: str
    output_docx_sha256: str
    output_preflight_report_hash: str
    output_structural_fingerprint_hash: str
    open_xml_validation_report_hash: str
    cdr_manifest_hash: str
    font_baseline_hash: str
    page_count: int = Field(ge=1, le=10000)
    visual_comparison_manifest_hash: str
    execution_receipt_hash: str
    source_synthetic: Literal[True] = True
    network_isolation_verified: Literal[True] = True
    macro_execution_disabled: Literal[True] = True
    source_blind_revalidation_verified: Literal[True] = True
    engine_execution_authorized: Literal[True] = True
    engine_executed: Literal[True] = True
    tenant_content_processed: Literal[False] = False
    tenant_credentials_available: Literal[False] = False
    persistent_product_version_written: Literal[False] = False
    document_content_in_payload: Literal[False] = False
    payload_hash: str

    @field_validator("completed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice fidelity result time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_bound_result(self) -> GenOfficeDocxFidelityEngineResultPayload:
        expected_assignment_id = f"{self.engine_id}:{self.fixture_id}"
        if self.result_id != f"result:{self.assignment_id}" or self.assignment_id != expected_assignment_id:
            raise ValueError("GenOffice fidelity result identity is invalid")
        if self.fixture_id not in FIDELITY_FIXTURE_IDS or not self.engine_version.strip():
            raise ValueError("GenOffice fidelity result scope or engine version is invalid")
        expected_mode = {
            "microsoft_word": "interactive_windows_client",
            "libreoffice": "isolated_headless_worker",
            "genoffice": "authorized_runsc_kvm_worker",
        }[self.engine_id]
        if self.runner_mode != expected_mode:
            raise ValueError("GenOffice fidelity result runner mode drifted")
        for value, field in (
            (self.study_plan_hash, "fidelity result plan hash"),
            (self.fidelity_policy_hash, "fidelity result policy hash"),
            (self.source_content_sha256, "fidelity result source hash"),
            (self.engine_identity_hash, "fidelity engine identity hash"),
            (self.executor_environment_hash, "fidelity executor environment hash"),
            (self.output_docx_sha256, "fidelity output DOCX hash"),
            (self.output_preflight_report_hash, "fidelity output preflight hash"),
            (self.output_structural_fingerprint_hash, "fidelity output structural hash"),
            (self.open_xml_validation_report_hash, "Open XML validation report hash"),
            (self.cdr_manifest_hash, "fidelity CDR manifest hash"),
            (self.font_baseline_hash, "fidelity font baseline hash"),
            (self.visual_comparison_manifest_hash, "fidelity visual comparison hash"),
            (self.execution_receipt_hash, "fidelity execution receipt hash"),
            (self.payload_hash, "fidelity result payload hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityResultSigner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signer_id: str
    key_id: str
    engine_id: EngineId
    ed25519_public_key_base64: str
    active: bool = True

    @model_validator(mode="after")
    def require_valid_signer(self) -> GenOfficeDocxFidelityResultSigner:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice fidelity result signer identity is empty")
        _decode_canonical_base64(
            self.ed25519_public_key_base64,
            field="fidelity result signer public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        )
        return self


class GenOfficeDocxFidelityResultSignerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_result_signer_policy.v1"] = (
        "genoffice_docx_fidelity_result_signer_policy.v1"
    )
    policy_id: str
    effective_at_utc: datetime
    signers: tuple[GenOfficeDocxFidelityResultSigner, ...]
    policy_hash: str

    @field_validator("effective_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice fidelity signer-policy time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_runner_signers(self) -> GenOfficeDocxFidelityResultSignerPolicy:
        active = tuple(item for item in self.signers if item.active)
        if not self.policy_id.strip() or tuple(item.engine_id for item in active) != FIDELITY_ENGINE_IDS:
            raise ValueError("GenOffice fidelity signer-policy engine inventory is not exact")
        if len({item.signer_id for item in active}) != 3 or len({item.key_id for item in active}) != 3:
            raise ValueError("GenOffice fidelity signer-policy identities or keys are not distinct")
        if len({item.ed25519_public_key_base64 for item in active}) != 3:
            raise ValueError("GenOffice fidelity signer-policy public keys are not distinct")
        _require_sha256(self.policy_hash, field="fidelity signer-policy hash")
        return self


class GenOfficeDocxFidelitySignedResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_signed_result_envelope.v1"] = (
        "genoffice_docx_fidelity_signed_result_envelope.v1"
    )
    signer_policy_hash: str
    payload: GenOfficeDocxFidelityEngineResultPayload
    signer_id: str
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    private_key_included: Literal[False] = False
    document_content_included: Literal[False] = False
    envelope_hash: str

    @model_validator(mode="after")
    def require_bound_envelope(self) -> GenOfficeDocxFidelitySignedResultEnvelope:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice fidelity result envelope signer identity is empty")
        _require_sha256(self.signer_policy_hash, field="fidelity envelope signer-policy hash")
        _require_sha256(self.envelope_hash, field="fidelity result envelope hash")
        _decode_canonical_base64(
            self.signature_base64,
            field="fidelity result signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        return self


class GenOfficeDocxFidelityResultMatrixIntakeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_result_matrix_intake_report.v1"] = (
        "genoffice_docx_fidelity_result_matrix_intake_report.v1"
    )
    fidelity_policy_hash: str
    study_plan_hash: str
    signer_policy_hash: str
    assignment_ids: tuple[str, ...]
    envelope_hashes: tuple[str, ...]
    accepted_signed_result_count: Literal[9] = 9
    exact_assignment_matrix_verified: Literal[True] = True
    signatures_verified: Literal[True] = True
    source_blind_revalidation_attested: Literal[True] = True
    referenced_evidence_hashes_bound: Literal[True] = True
    referenced_evidence_content_verified: Literal[False] = False
    visual_thresholds_calibrated: Literal[False] = False
    human_fidelity_review_verified: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    quick_edit_spike_complete: Literal[False] = False
    report_hash: str

    @model_validator(mode="after")
    def require_fail_closed_intake(self) -> GenOfficeDocxFidelityResultMatrixIntakeReport:
        expected = tuple(f"{engine}:{fixture}" for engine in FIDELITY_ENGINE_IDS for fixture in FIDELITY_FIXTURE_IDS)
        if self.assignment_ids != expected or len(self.envelope_hashes) != 9:
            raise ValueError("GenOffice fidelity result intake matrix is not exact")
        for value, field in (
            (self.fidelity_policy_hash, "fidelity intake policy hash"),
            (self.study_plan_hash, "fidelity intake plan hash"),
            (self.signer_policy_hash, "fidelity intake signer-policy hash"),
            (self.report_hash, "fidelity intake report hash"),
            *((value, "fidelity intake envelope hash") for value in self.envelope_hashes),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_readiness_report.v1"] = (
        "genoffice_docx_fidelity_readiness_report.v1"
    )
    fidelity_policy_hash: str
    study_plan_hash: str
    baseline_report_hash: str
    structural_baselines_verified: Literal[True] = True
    expected_assignment_count: Literal[9] = 9
    accepted_signed_result_count: Literal[0] = 0
    result_signer_policy_present: Literal[False] = False
    exact_cross_engine_matrix_verified: Literal[False] = False
    open_xml_validation_evidence_verified: Literal[False] = False
    cdr_linked_visual_comparison_verified: Literal[False] = False
    visual_thresholds_calibrated: Literal[False] = False
    human_fidelity_review_verified: Literal[False] = False
    engine_executed: Literal[False] = False
    tenant_content_processed: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    quick_edit_spike_complete: Literal[False] = False
    blocking_reasons: tuple[str, ...] = READINESS_BLOCKERS
    report_hash: str

    @model_validator(mode="after")
    def require_fail_closed_readiness(self) -> GenOfficeDocxFidelityReadinessReport:
        if self.blocking_reasons != READINESS_BLOCKERS:
            raise ValueError("GenOffice fidelity readiness blockers drifted")
        for value, field in (
            (self.fidelity_policy_hash, "fidelity readiness policy hash"),
            (self.study_plan_hash, "fidelity readiness plan hash"),
            (self.baseline_report_hash, "fidelity readiness baseline hash"),
            (self.report_hash, "fidelity readiness report hash"),
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


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _decode_canonical_base64(value: str, *, field: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeDocxFidelityStudyError(f"GenOffice {field} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeDocxFidelityStudyError(f"GenOffice {field} has an invalid size or encoding")
    return decoded


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
        raise GenOfficeDocxFidelityStudyError(f"GenOffice fidelity output cannot be persisted: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_genoffice_docx_fidelity_study_policy() -> GenOfficeDocxFidelityStudyPolicy:
    targets = (
        GenOfficeDocxFidelityEngineTarget(
            engine_id="microsoft_word",
            runner_mode="interactive_windows_client",
            unattended_execution_allowed=False,
            interactive_user_session_required=True,
            runtime_authorization_required=False,
        ),
        GenOfficeDocxFidelityEngineTarget(
            engine_id="libreoffice",
            runner_mode="isolated_headless_worker",
            unattended_execution_allowed=True,
            interactive_user_session_required=False,
            runtime_authorization_required=False,
        ),
        GenOfficeDocxFidelityEngineTarget(
            engine_id="genoffice",
            runner_mode="authorized_runsc_kvm_worker",
            unattended_execution_allowed=True,
            interactive_user_session_required=False,
            runtime_authorization_required=True,
        ),
    )
    draft = GenOfficeDocxFidelityStudyPolicy(engine_targets=targets, policy_hash=ZERO_HASH)
    return draft.model_copy(update={"policy_hash": _hash_model(draft, hash_field="policy_hash")})


def build_genoffice_docx_fidelity_study_plan(
    *,
    policy: GenOfficeDocxFidelityStudyPolicy,
    preflight_policy: GenOfficeDocxQuickEditPreflightPolicy,
    corpus_manifest: GenOfficeDocxQuickEditCorpusManifest,
) -> GenOfficeDocxFidelityStudyPlan:
    if policy != build_genoffice_docx_fidelity_study_policy():
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity study policy is not canonical")
    if preflight_policy != build_genoffice_docx_quick_edit_preflight_policy():
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity preflight policy is not canonical")
    _, canonical_manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight_policy)
    if corpus_manifest != canonical_manifest:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity corpus manifest is not canonical")
    artifacts = {artifact.fixture_id: artifact for artifact in corpus_manifest.artifacts}
    assignments = tuple(
        GenOfficeDocxFidelityRunAssignment(
            assignment_id=f"{target.engine_id}:{fixture_id}",
            engine_id=target.engine_id,
            runner_mode=target.runner_mode,
            fixture_id=fixture_id,
            source_content_sha256=artifacts[fixture_id].content_sha256,
        )
        for target in policy.engine_targets
        for fixture_id in FIDELITY_FIXTURE_IDS
    )
    draft = GenOfficeDocxFidelityStudyPlan(
        fidelity_policy_hash=policy.policy_hash,
        preflight_policy_hash=preflight_policy.policy_hash,
        corpus_manifest_hash=corpus_manifest.manifest_hash,
        assignments=assignments,
        plan_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"plan_hash": _hash_model(draft, hash_field="plan_hash")})


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _structural_inventory(
    content: bytes,
) -> tuple[int, int, int, str, str, str, tuple[GenOfficeDocxSemanticFeatureCount, ...]]:
    names: list[str] = []
    content_types: list[tuple[str, str]] = []
    relationships: list[tuple[str, str, str, str]] = []
    feature_counts: dict[str, int] = {
        "alternate_content": 0,
        "bold": 0,
        "comments": 0,
        "custom_xml_parts": 0,
        "footnotes": 0,
        "headers": 0,
        "internal_relationships": 0,
        "italic": 0,
        "paragraphs": 0,
        "runs": 0,
        "table_cells": 0,
        "table_rows": 0,
        "tables": 0,
    }
    xml_part_count = 0
    with zipfile.ZipFile(BytesIO(content), "r") as archive:
        infos = archive.infolist()
        for info in infos:
            name = info.filename
            names.append(name)
            if name.startswith("customXml/"):
                feature_counts["custom_xml_parts"] += 1
            if not (name.endswith((".xml", ".rels")) or name == "[Content_Types].xml"):
                continue
            xml_part_count += 1
            root = ElementTree.fromstring(archive.read(info))
            for element in root.iter():
                local = _local_name(element.tag)
                feature_key = {
                    "AlternateContent": "alternate_content",
                    "b": "bold",
                    "comment": "comments",
                    "footnote": "footnotes",
                    "hdr": "headers",
                    "i": "italic",
                    "p": "paragraphs",
                    "r": "runs",
                    "tc": "table_cells",
                    "tr": "table_rows",
                    "tbl": "tables",
                }.get(local)
                if feature_key is not None:
                    feature_counts[feature_key] += 1
                if name == "[Content_Types].xml" and local in {"Default", "Override"}:
                    content_types.append(
                        (
                            element.attrib.get("PartName", element.attrib.get("Extension", "")),
                            element.attrib.get("ContentType", ""),
                        )
                    )
                if name.endswith(".rels") and local == "Relationship":
                    mode = element.attrib.get("TargetMode", "Internal")
                    relationships.append(
                        (
                            name,
                            element.attrib.get("Type", ""),
                            element.attrib.get("Target", ""),
                            mode,
                        )
                    )
                    if mode.casefold() != "external":
                        feature_counts["internal_relationships"] += 1
    features = tuple(
        GenOfficeDocxSemanticFeatureCount(feature_id=name, count=count)
        for name, count in sorted(feature_counts.items())
    )
    return (
        len(names),
        xml_part_count,
        len(relationships),
        stable_hash(canonical_json(sorted(names))),
        stable_hash(canonical_json(sorted(content_types))),
        stable_hash(canonical_json(sorted(relationships))),
        features,
    )


def build_genoffice_docx_structural_fingerprint(
    *,
    fixture_id: str,
    content: bytes,
    preflight_policy: GenOfficeDocxQuickEditPreflightPolicy,
) -> GenOfficeDocxStructuralFingerprintReport:
    preflight = inspect_genoffice_docx_quick_edit_candidate(content, policy=preflight_policy)
    if not preflight.future_engine_evaluation_eligible:
        raise GenOfficeDocxFidelityStudyError("GenOffice structural fingerprint input failed preflight")
    part_count, xml_count, rel_count, names_hash, types_hash, rels_hash, features = _structural_inventory(content)
    draft = GenOfficeDocxStructuralFingerprintReport(
        fixture_id=fixture_id,
        input_sha256=_sha256_bytes(content),
        input_size_bytes=len(content),
        preflight_report_hash=preflight.report_hash,
        part_count=part_count,
        xml_part_count=xml_count,
        relationship_count=rel_count,
        part_name_inventory_hash=names_hash,
        content_type_inventory_hash=types_hash,
        relationship_inventory_hash=rels_hash,
        semantic_features=features,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": _hash_model(draft, hash_field="report_hash")})


def build_genoffice_docx_fidelity_baseline_report(
    *,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    preflight_policy: GenOfficeDocxQuickEditPreflightPolicy,
    corpus_manifest: GenOfficeDocxQuickEditCorpusManifest,
    corpus_files: Mapping[str, bytes],
) -> GenOfficeDocxFidelityBaselineReport:
    policy = build_genoffice_docx_fidelity_study_policy()
    canonical_plan = build_genoffice_docx_fidelity_study_plan(
        policy=policy,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
    )
    if study_plan != canonical_plan:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity baseline study plan is not canonical")
    artifacts = {artifact.fixture_id: artifact for artifact in corpus_manifest.artifacts}
    fingerprints = tuple(
        build_genoffice_docx_structural_fingerprint(
            fixture_id=fixture_id,
            content=corpus_files[artifacts[fixture_id].filename],
            preflight_policy=preflight_policy,
        )
        for fixture_id in FIDELITY_FIXTURE_IDS
    )
    for fingerprint in fingerprints:
        artifact = artifacts[fingerprint.fixture_id]
        if fingerprint.input_sha256 != artifact.content_sha256:
            raise GenOfficeDocxFidelityStudyError("GenOffice fidelity baseline source binding drifted")
    draft = GenOfficeDocxFidelityBaselineReport(
        study_plan_hash=study_plan.plan_hash,
        preflight_policy_hash=preflight_policy.policy_hash,
        corpus_manifest_hash=corpus_manifest.manifest_hash,
        fixture_fingerprints=fingerprints,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": _hash_model(draft, hash_field="report_hash")})


def compare_genoffice_docx_rgb_page(
    *,
    page_number: int,
    width_pixels: int,
    height_pixels: int,
    reference_rgb: bytes,
    candidate_rgb: bytes,
) -> GenOfficeDocxRgbPageComparisonReport:
    expected_length = width_pixels * height_pixels * 3
    if expected_length <= 0 or len(reference_rgb) != expected_length or len(candidate_rgb) != expected_length:
        raise GenOfficeDocxFidelityStudyError("GenOffice RGB comparison input dimensions are inconsistent")
    changed_pixels = 0
    total_channel_delta = 0
    maximum_channel_delta = 0
    for offset in range(0, expected_length, 3):
        pixel_changed = False
        for channel in range(3):
            delta = abs(reference_rgb[offset + channel] - candidate_rgb[offset + channel])
            total_channel_delta += delta
            maximum_channel_delta = max(maximum_channel_delta, delta)
            pixel_changed = pixel_changed or delta > 0
        changed_pixels += int(pixel_changed)
    total_pixels = width_pixels * height_pixels
    changed_ratio_ppm = (changed_pixels * 1_000_000) // total_pixels
    mean_delta_ppm = (total_channel_delta * 1_000_000) // (expected_length * 255)
    draft = GenOfficeDocxRgbPageComparisonReport(
        page_number=page_number,
        width_pixels=width_pixels,
        height_pixels=height_pixels,
        reference_rgb_sha256=_sha256_bytes(reference_rgb),
        candidate_rgb_sha256=_sha256_bytes(candidate_rgb),
        total_pixels=total_pixels,
        changed_pixels=changed_pixels,
        changed_pixel_ratio_ppm=changed_ratio_ppm,
        mean_absolute_channel_delta_ppm=mean_delta_ppm,
        maximum_channel_delta=maximum_channel_delta,
        exact_pixel_match=changed_pixels == 0,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": _hash_model(draft, hash_field="report_hash")})


def build_genoffice_docx_fidelity_result_payload_hash(payload: GenOfficeDocxFidelityEngineResultPayload) -> str:
    return _hash_model(payload, hash_field="payload_hash")


def build_genoffice_docx_fidelity_result_message(payload: GenOfficeDocxFidelityEngineResultPayload) -> bytes:
    return RESULT_SIGNATURE_DOMAIN + canonical_json(payload.model_dump(mode="json")).encode("utf-8")


def build_genoffice_docx_fidelity_signed_result_envelope_hash(
    envelope: GenOfficeDocxFidelitySignedResultEnvelope,
) -> str:
    return _hash_model(envelope, hash_field="envelope_hash")


def build_genoffice_docx_fidelity_result_signer_policy_hash(
    policy: GenOfficeDocxFidelityResultSignerPolicy,
) -> str:
    return _hash_model(policy, hash_field="policy_hash")


def verify_genoffice_docx_fidelity_signed_result(
    *,
    envelope: GenOfficeDocxFidelitySignedResultEnvelope,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeDocxFidelityEngineResultPayload:
    if _hash_model(study_plan, hash_field="plan_hash") != study_plan.plan_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity study plan hash is invalid")
    if build_genoffice_docx_fidelity_result_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result signer policy hash is invalid")
    if envelope.signer_policy_hash != signer_policy.policy_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result signer policy binding drifted")
    if build_genoffice_docx_fidelity_signed_result_envelope_hash(envelope) != envelope.envelope_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result envelope hash is invalid")
    payload = envelope.payload
    if payload.completed_at_utc < signer_policy.effective_at_utc:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result predates its signer policy")
    if build_genoffice_docx_fidelity_result_payload_hash(payload) != payload.payload_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result payload hash is invalid")
    assignments = {assignment.assignment_id: assignment for assignment in study_plan.assignments}
    assignment = assignments.get(payload.assignment_id)
    if assignment is None:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result assignment is unknown")
    if (
        payload.study_plan_hash != study_plan.plan_hash
        or payload.fidelity_policy_hash != study_plan.fidelity_policy_hash
        or payload.engine_id != assignment.engine_id
        or payload.fixture_id != assignment.fixture_id
        or payload.runner_mode != assignment.runner_mode
        or payload.source_content_sha256 != assignment.source_content_sha256
    ):
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result assignment binding drifted")
    signers = {
        (signer.signer_id, signer.key_id): signer
        for signer in signer_policy.signers
        if signer.active and signer.engine_id == payload.engine_id
    }
    signer = signers.get((envelope.signer_id, envelope.key_id))
    if signer is None:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result signer is not authorized for the engine")
    public_key = _decode_canonical_base64(
        signer.ed25519_public_key_base64,
        field="fidelity result signer public key",
        expected_size=PUBLIC_KEY_SIZE_BYTES,
    )
    signature = _decode_canonical_base64(
        envelope.signature_base64,
        field="fidelity result signature",
        expected_size=SIGNATURE_SIZE_BYTES,
    )
    if not verifier.verify_ed25519(
        public_key=public_key,
        signature=signature,
        message=build_genoffice_docx_fidelity_result_message(payload),
    ):
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity result signature is invalid")
    return payload


def verify_genoffice_docx_fidelity_result_matrix_intake(
    *,
    envelopes: Sequence[GenOfficeDocxFidelitySignedResultEnvelope],
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeDocxFidelityResultMatrixIntakeReport:
    expected_ids = tuple(assignment.assignment_id for assignment in study_plan.assignments)
    observed_ids = tuple(envelope.payload.assignment_id for envelope in envelopes)
    if observed_ids != expected_ids or len({envelope.envelope_hash for envelope in envelopes}) != 9:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity signed result matrix is not exact")
    payloads = tuple(
        verify_genoffice_docx_fidelity_signed_result(
            envelope=envelope,
            signer_policy=signer_policy,
            study_plan=study_plan,
            verifier=verifier,
        )
        for envelope in envelopes
    )
    if not all(payload.source_blind_revalidation_verified for payload in payloads):
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity source-blind revalidation is absent")
    draft = GenOfficeDocxFidelityResultMatrixIntakeReport(
        fidelity_policy_hash=study_plan.fidelity_policy_hash,
        study_plan_hash=study_plan.plan_hash,
        signer_policy_hash=signer_policy.policy_hash,
        assignment_ids=observed_ids,
        envelope_hashes=tuple(envelope.envelope_hash for envelope in envelopes),
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": _hash_model(draft, hash_field="report_hash")})


def build_genoffice_docx_fidelity_readiness_report(
    *,
    policy: GenOfficeDocxFidelityStudyPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    baseline: GenOfficeDocxFidelityBaselineReport,
) -> GenOfficeDocxFidelityReadinessReport:
    if study_plan.fidelity_policy_hash != policy.policy_hash or baseline.study_plan_hash != study_plan.plan_hash:
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity readiness evidence binding drifted")
    draft = GenOfficeDocxFidelityReadinessReport(
        fidelity_policy_hash=policy.policy_hash,
        study_plan_hash=study_plan.plan_hash,
        baseline_report_hash=baseline.report_hash,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": _hash_model(draft, hash_field="report_hash")})


def materialize_genoffice_docx_fidelity_study_bundle(output_directory: Path) -> GenOfficeDocxFidelityReadinessReport:
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise GenOfficeDocxFidelityStudyError("GenOffice fidelity study output directory is not empty")
    preflight_policy = build_genoffice_docx_quick_edit_preflight_policy()
    corpus_files, corpus_manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight_policy)
    policy = build_genoffice_docx_fidelity_study_policy()
    plan = build_genoffice_docx_fidelity_study_plan(
        policy=policy,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
    )
    baseline = build_genoffice_docx_fidelity_baseline_report(
        study_plan=plan,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
        corpus_files=corpus_files,
    )
    readiness = build_genoffice_docx_fidelity_readiness_report(
        policy=policy,
        study_plan=plan,
        baseline=baseline,
    )
    for filename, model in (
        ("genoffice-docx-fidelity-study-policy.json", policy),
        ("genoffice-docx-fidelity-study-plan.json", plan),
        ("genoffice-docx-fidelity-baseline-report.json", baseline),
        ("genoffice-docx-fidelity-readiness-report.json", readiness),
    ):
        _write_new_private(output_directory / filename, _json_bytes(model))
    return readiness


def persist_genoffice_docx_fidelity_study_schemas(output_directory: Path) -> dict[str, str]:
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-docx-fidelity-study-policy.schema.json", GenOfficeDocxFidelityStudyPolicy),
        ("genoffice-docx-fidelity-study-plan.schema.json", GenOfficeDocxFidelityStudyPlan),
        ("genoffice-docx-structural-fingerprint-report.schema.json", GenOfficeDocxStructuralFingerprintReport),
        ("genoffice-docx-fidelity-baseline-report.schema.json", GenOfficeDocxFidelityBaselineReport),
        ("genoffice-docx-rgb-page-comparison-report.schema.json", GenOfficeDocxRgbPageComparisonReport),
        ("genoffice-docx-fidelity-engine-result-payload.schema.json", GenOfficeDocxFidelityEngineResultPayload),
        ("genoffice-docx-fidelity-result-signer-policy.schema.json", GenOfficeDocxFidelityResultSignerPolicy),
        ("genoffice-docx-fidelity-signed-result-envelope.schema.json", GenOfficeDocxFidelitySignedResultEnvelope),
        (
            "genoffice-docx-fidelity-result-matrix-intake-report.schema.json",
            GenOfficeDocxFidelityResultMatrixIntakeReport,
        ),
        ("genoffice-docx-fidelity-readiness-report.schema.json", GenOfficeDocxFidelityReadinessReport),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(output_directory / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_FIDELITY_STUDY_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_docx_fidelity_study_schemas(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_STUDY_OUTPUT_DIR"])
            )
        elif mode == "bundle":
            result = materialize_genoffice_docx_fidelity_study_bundle(
                Path(os.environ["SUITE_GENOFFICE_FIDELITY_STUDY_OUTPUT_DIR"])
            )
        else:
            raise GenOfficeDocxFidelityStudyError("GenOffice fidelity study mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeDocxFidelityStudyError, KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_fidelity_study_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
