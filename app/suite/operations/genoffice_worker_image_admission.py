from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tarfile
import uuid
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_development_build_context import (
    GenOfficeDevelopmentBuildContextReport,
    build_genoffice_development_build_context_report_hash,
)
from suite.operations.genoffice_docx_source_admission import (
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeSourceAdmissionError,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_license_material_collector import (
    GenOfficeLicenseMaterialCollectionError,
    load_genoffice_license_material_collection_report,
)
from suite.operations.genoffice_solo_founder_exception import (
    PUBLIC_KEY_SIZE_BYTES,
    SIGNATURE_SIZE_BYTES,
    GenOfficeSoloFounderExceptionError,
    GenOfficeSoloFounderExceptionReport,
    GenOfficeSoloFounderPolicy,
    build_genoffice_solo_founder_policy_hash,
    build_genoffice_solo_founder_report_hash,
    load_genoffice_solo_founder_policy,
    load_genoffice_solo_founder_report,
)

GENOFFICE_WORKER_BUILD_EVIDENCE_SCHEMA_VERSION = "genoffice_worker_image_build_evidence.v1"
GENOFFICE_WORKER_SIGNING_REQUEST_SCHEMA_VERSION = "genoffice_worker_build_signing_request.v1"
GENOFFICE_WORKER_SIGNATURE_RESPONSE_SCHEMA_VERSION = "genoffice_worker_build_signature_response.v1"
GENOFFICE_WORKER_ADMISSION_REPORT_SCHEMA_VERSION = "genoffice_worker_image_admission_report.v1"
GENOFFICE_WORKER_ATTESTATION_PAYLOAD_SCHEMA_VERSION = "genoffice_worker_build_attestation_payload.v1"
GENOFFICE_WORKER_IMAGE_SBOM_SCHEMA_VERSION = "genoffice_worker_image_sbom.v1"
GENOFFICE_WORKER_BASE_IMAGE_REF: Literal[
    "node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d"
] = "node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d"
GENOFFICE_WORKER_TRIVY_IMAGE_REF = (
    "aquasec/trivy@sha256:7cced7cae583819fc7806d4cbc0dbbc7cad18b99f7d3e235192e6da8c091045c"
)
GENOFFICE_WORKER_TRIVY_VERSION = "0.73.0"
GENOFFICE_WORKER_CYCLONEDX_VALIDATOR_REF = (
    "cyclonedx-cli-0.32.0@sha256:9a858a15e7b0843606efc0ff19d5f7575011a5428d7f3d343b4f6cf09d8f0d4e"
)
GENOFFICE_WORKER_IMAGE_NAME: Literal["collabio/genoffice-docx-worker"] = "collabio/genoffice-docx-worker"
GENOFFICE_WORKER_PLATFORM: Literal["linux/amd64"] = "linux/amd64"
GENOFFICE_WORKER_USER = "10003:10003"
GENOFFICE_WORKER_WORKDIR = "/opt/genoffice/packages/docx-engine"
GENOFFICE_WORKER_ENTRYPOINT = ("node", "/opt/collabio/worker-entrypoint.mjs")
GENOFFICE_WORKER_COMMAND = ("--status",)
GENOFFICE_WORKER_MAX_VALIDITY = timedelta(days=7)
MAX_SMALL_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TRIVY_DB_AGE_SECONDS = 24 * 60 * 60
_ZERO_HASH = "sha256:" + "0" * 64
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_REF_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*:[a-z0-9][a-z0-9._-]*")
_SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


class GenOfficeWorkerImageAdmissionError(ValueError):
    pass


class GenOfficeWorkerVulnerabilityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vulnerability_id: str
    package_purl: str
    package_name: str
    installed_version: str
    fixed_version: str | None
    severity: str
    primary_url: str | None


class GenOfficeWorkerImageBuildEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_worker_image_build_evidence.v1"] = "genoffice_worker_image_build_evidence.v1"
    observed_at_utc: datetime
    image_name: Literal["collabio/genoffice-docx-worker"] = GENOFFICE_WORKER_IMAGE_NAME
    image_ref_a: str
    image_ref_b: str
    image_config_digest: str
    image_platform: Literal["linux/amd64"] = GENOFFICE_WORKER_PLATFORM
    image_size_bytes: int
    image_archive_size_bytes: int
    image_archive_sha256: str
    rootfs_layer_digests: tuple[str, ...]
    build_a_inspect_sha256: str
    build_b_inspect_sha256: str
    dockerfile_sha256: str
    base_image_ref: Literal[
        "node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d"
    ] = GENOFFICE_WORKER_BASE_IMAGE_REF
    node_version: Literal["24.18.0"] = "24.18.0"
    npm_version: Literal["11.16.0"] = "11.16.0"
    development_build_context_report_hash: str
    development_build_context_tar_sha256: str
    source_archive_sha256: str
    source_manifest_hash: str
    development_authorization_report_hash: str
    signer_policy_hash: str
    license_material_collection_report_hash: str
    dependency_archive_count: int
    runtime_package_count: int
    source_date_epoch: int
    build_network_mode: Literal["none"] = "none"
    package_install_mode: Literal["offline_reviewed_tarball_cache"] = "offline_reviewed_tarball_cache"
    lifecycle_scripts_executed: Literal[False] = False
    upstream_code_executed: Literal[False] = False
    credentials_used: Literal[False] = False
    build_a_completed: Literal[True] = True
    build_b_completed: Literal[True] = True
    reproducible_image_config_verified: Literal[True] = True
    archive_config_binding_verified: Literal[True] = True
    runtime_inventory_verified: Literal[True] = True
    worker_image_built: Literal[True] = True
    worker_execution_allowed: Literal[False] = False
    source_import_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    report_hash: str

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice worker build evidence time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_closed_reproducible_build(self) -> GenOfficeWorkerImageBuildEvidence:
        if not _IMAGE_REF_PATTERN.fullmatch(self.image_ref_a) or not _IMAGE_REF_PATTERN.fullmatch(self.image_ref_b):
            raise ValueError("GenOffice worker image references are invalid")
        if self.image_ref_a == self.image_ref_b or not all(
            value.startswith(f"{self.image_name}:") for value in (self.image_ref_a, self.image_ref_b)
        ):
            raise ValueError("GenOffice worker verification images are not independent tags")
        for field, value in (
            ("image config digest", self.image_config_digest),
            ("image archive hash", self.image_archive_sha256),
            ("build A inspect hash", self.build_a_inspect_sha256),
            ("build B inspect hash", self.build_b_inspect_sha256),
            ("Dockerfile hash", self.dockerfile_sha256),
            ("build context report hash", self.development_build_context_report_hash),
            ("build context TAR hash", self.development_build_context_tar_sha256),
            ("source archive hash", self.source_archive_sha256),
            ("source manifest hash", self.source_manifest_hash),
            ("authorization report hash", self.development_authorization_report_hash),
            ("signer policy hash", self.signer_policy_hash),
            ("license material report hash", self.license_material_collection_report_hash),
            ("worker build evidence hash", self.report_hash),
        ):
            _require_sha256(value, field=field)
        if not self.rootfs_layer_digests or not all(
            _SHA256_PATTERN.fullmatch(item) for item in self.rootfs_layer_digests
        ):
            raise ValueError("GenOffice worker rootfs layer inventory is invalid")
        if not 0 < self.image_size_bytes <= MAX_IMAGE_ARCHIVE_BYTES:
            raise ValueError("GenOffice worker image size is invalid")
        if not 0 < self.image_archive_size_bytes <= MAX_IMAGE_ARCHIVE_BYTES:
            raise ValueError("GenOffice worker image archive size is invalid")
        if self.dependency_archive_count != self.runtime_package_count or self.runtime_package_count != 21:
            raise ValueError("GenOffice worker runtime package count is not the reviewed closure")
        if self.source_date_epoch < 0:
            raise ValueError("GenOffice worker SOURCE_DATE_EPOCH is invalid")
        return self


class GenOfficeWorkerBuildAttestationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_worker_build_attestation_payload.v1"] = (
        "genoffice_worker_build_attestation_payload.v1"
    )
    attestation_id: str
    issued_at_utc: datetime
    valid_until_utc: datetime
    image_name: Literal["collabio/genoffice-docx-worker"] = GENOFFICE_WORKER_IMAGE_NAME
    image_config_digest: str
    image_archive_sha256: str
    build_evidence_report_hash: str
    development_build_context_report_hash: str
    development_build_context_tar_sha256: str
    development_authorization_report_hash: str
    signer_policy_hash: str
    worker_sbom_sha256: str
    raw_scanner_sbom_sha256: str
    worker_sbom_component_count: int
    worker_sbom_npm_component_count: int
    worker_sbom_os_component_count: int
    sbom_schema_validation_receipt_hash: str
    vulnerability_report_hash: str
    trivy_db_metadata_hash: str
    vulnerability_count: int
    severity_counts: dict[str, int]
    vulnerability_findings: tuple[GenOfficeWorkerVulnerabilityFinding, ...]
    trivy_db_updated_at_utc: datetime
    trivy_db_age_seconds_at_scan: int
    reproducible_worker_build_verified: Literal[True] = True
    authoritative_image_sbom_verified: Literal[True] = True
    sbom_schema_validation_passed: Literal[True] = True
    vulnerability_review_complete: Literal[True] = True
    high_and_critical_findings_absent: Literal[True] = True
    detached_build_attestation_required: Literal[True] = True
    two_person_runtime_authorization_required: Literal[True] = True
    worker_execution_allowed: Literal[False] = False
    source_import_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    payload_hash: str

    @field_validator("issued_at_utc", "valid_until_utc", "trivy_db_updated_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice worker attestation time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_closed_attestation(self) -> GenOfficeWorkerBuildAttestationPayload:
        if not self.attestation_id.strip():
            raise ValueError("GenOffice worker attestation identity is empty")
        if not (self.issued_at_utc < self.valid_until_utc <= self.issued_at_utc + GENOFFICE_WORKER_MAX_VALIDITY):
            raise ValueError("GenOffice worker attestation validity window is invalid")
        if self.worker_sbom_component_count <= 0 or self.worker_sbom_npm_component_count != 23:
            raise ValueError("GenOffice worker SBOM npm inventory is incomplete")
        if self.worker_sbom_os_component_count <= 0:
            raise ValueError("GenOffice worker SBOM lacks operating-system inventory")
        if self.vulnerability_count != len(self.vulnerability_findings):
            raise ValueError("GenOffice worker vulnerability count is inconsistent")
        if (
            set(self.severity_counts) != set(_SEVERITIES)
            or sum(self.severity_counts.values()) != self.vulnerability_count
        ):
            raise ValueError("GenOffice worker vulnerability severities are inconsistent")
        if self.severity_counts["HIGH"] or self.severity_counts["CRITICAL"]:
            raise ValueError("GenOffice worker attestation contains high or critical vulnerabilities")
        if not 0 <= self.trivy_db_age_seconds_at_scan <= MAX_TRIVY_DB_AGE_SECONDS:
            raise ValueError("GenOffice worker Trivy DB was stale at scan time")
        for field, value in (
            ("image config digest", self.image_config_digest),
            ("image archive hash", self.image_archive_sha256),
            ("build evidence report hash", self.build_evidence_report_hash),
            ("build context report hash", self.development_build_context_report_hash),
            ("build context TAR hash", self.development_build_context_tar_sha256),
            ("authorization report hash", self.development_authorization_report_hash),
            ("signer policy hash", self.signer_policy_hash),
            ("worker SBOM hash", self.worker_sbom_sha256),
            ("raw scanner SBOM hash", self.raw_scanner_sbom_sha256),
            ("schema validation receipt hash", self.sbom_schema_validation_receipt_hash),
            ("vulnerability report hash", self.vulnerability_report_hash),
            ("Trivy DB metadata hash", self.trivy_db_metadata_hash),
            ("worker attestation payload hash", self.payload_hash),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeWorkerBuildSigningAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: Literal["founder_risk_owner"] = "founder_risk_owner"
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"


class GenOfficeWorkerBuildSigningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_worker_build_signing_request.v1"] = "genoffice_worker_build_signing_request.v1"
    prepared_at_utc: datetime
    payload: GenOfficeWorkerBuildAttestationPayload
    signing_assignment: GenOfficeWorkerBuildSigningAssignment
    signature_message_sha256: str
    signature_message_size_bytes: int
    worker_admission_effective: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice worker signing request time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_bound_request(self) -> GenOfficeWorkerBuildSigningRequest:
        if self.prepared_at_utc != self.payload.issued_at_utc:
            raise ValueError("GenOffice worker signing request and payload times differ")
        if not self.signing_assignment.signer_id.strip() or not self.signing_assignment.key_id.strip():
            raise ValueError("GenOffice worker signing assignment identity is empty")
        if self.signature_message_size_bytes <= 0:
            raise ValueError("GenOffice worker signature message is empty")
        _require_sha256(self.signature_message_sha256, field="worker signature message hash")
        _require_sha256(self.request_hash, field="worker signing request hash")
        return self


class GenOfficeWorkerBuildSignatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_worker_build_signature_response.v1"] = (
        "genoffice_worker_build_signature_response.v1"
    )
    request_hash: str
    signature_message_sha256: str
    signer_id: str
    signer_role: Literal["founder_risk_owner"] = "founder_risk_owner"
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @model_validator(mode="after")
    def require_bound_response(self) -> GenOfficeWorkerBuildSignatureResponse:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice worker signature response identity is empty")
        _require_sha256(self.request_hash, field="worker signing request hash")
        _require_sha256(self.signature_message_sha256, field="worker signature message hash")
        _decode_canonical_base64(
            self.signature_base64,
            label="worker detached signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        return self


class GenOfficeWorkerImageAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_worker_image_admission_report.v1"] = "genoffice_worker_image_admission_report.v1"
    attestation_id: str
    issued_at_utc: datetime
    valid_until_utc: datetime
    signer_id: str
    key_id: str
    signer_policy_hash: str
    solo_founder_exception_report_hash: str
    image_name: Literal["collabio/genoffice-docx-worker"] = GENOFFICE_WORKER_IMAGE_NAME
    image_config_digest: str
    image_archive_sha256: str
    build_evidence_report_hash: str
    development_build_context_report_hash: str
    development_build_context_tar_sha256: str
    worker_sbom_sha256: str
    raw_scanner_sbom_sha256: str
    sbom_schema_validation_receipt_hash: str
    vulnerability_report_hash: str
    trivy_db_metadata_hash: str
    vulnerability_count: int
    severity_counts: dict[str, int]
    signing_request_hash: str
    signature_response_hash: str
    attestation_payload_hash: str
    reproducible_worker_build_verified: Literal[True] = True
    authoritative_image_sbom_verified: Literal[True] = True
    sbom_schema_validation_passed: Literal[True] = True
    vulnerability_review_complete: Literal[True] = True
    high_and_critical_findings_absent: Literal[True] = True
    detached_build_attestation_verified: Literal[True] = True
    development_spike_image_available: Literal[True] = True
    two_person_runtime_authorization_verified: Literal[False] = False
    worker_execution_allowed: Literal[False] = False
    source_import_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    report_hash: str

    @field_validator("issued_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice worker admission time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_signed_non_runtime_admission(self) -> GenOfficeWorkerImageAdmissionReport:
        if not self.attestation_id.strip() or not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice worker admission identity is empty")
        if self.severity_counts.get("HIGH") or self.severity_counts.get("CRITICAL"):
            raise ValueError("GenOffice worker admission contains high or critical vulnerabilities")
        for field, value in (
            ("signer policy hash", self.signer_policy_hash),
            ("solo-founder exception report hash", self.solo_founder_exception_report_hash),
            ("image config digest", self.image_config_digest),
            ("image archive hash", self.image_archive_sha256),
            ("build evidence report hash", self.build_evidence_report_hash),
            ("build context report hash", self.development_build_context_report_hash),
            ("build context TAR hash", self.development_build_context_tar_sha256),
            ("worker SBOM hash", self.worker_sbom_sha256),
            ("raw scanner SBOM hash", self.raw_scanner_sbom_sha256),
            ("schema validation receipt hash", self.sbom_schema_validation_receipt_hash),
            ("vulnerability report hash", self.vulnerability_report_hash),
            ("Trivy DB metadata hash", self.trivy_db_metadata_hash),
            ("worker signing request hash", self.signing_request_hash),
            ("worker signature response hash", self.signature_response_hash),
            ("worker attestation payload hash", self.attestation_payload_hash),
            ("worker admission report hash", self.report_hash),
        ):
            _require_sha256(value, field=field)
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice {field} is not a SHA-256 hash")


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _hash_file(path: Path, *, maximum_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_size:
                    raise GenOfficeWorkerImageAdmissionError(f"GenOffice evidence exceeds its size limit: {path.name}")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice evidence cannot be read: {path.name}") from exc
    return f"sha256:{digest.hexdigest()}", size


def _hash_stream(source: BinaryIO, *, maximum_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > maximum_size:
            raise GenOfficeWorkerImageAdmissionError("GenOffice image archive member exceeds its size limit")
        digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _read_json(path: Path, *, maximum_size: int = MAX_SMALL_EVIDENCE_BYTES) -> Any:
    _hash_file(path, maximum_size=maximum_size)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice evidence is not readable JSON: {path.name}") from exc


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice worker output already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    temporary_created = False
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice worker output already exists: {path.name}") from exc
    except OSError as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice worker output cannot be persisted: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_created:
            with suppress(FileNotFoundError):
                temporary.unlink()


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice {field} lacks a timezone")
    return parsed.astimezone(UTC)


def _decode_canonical_base64(value: str, *, label: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice {label} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice {label} has an invalid size or encoding")
    return decoded


def _load_context_report(path: Path) -> GenOfficeDevelopmentBuildContextReport:
    try:
        report = GenOfficeDevelopmentBuildContextReport.model_validate(_read_json(path))
    except ValueError as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice development build context report is invalid") from exc
    if build_genoffice_development_build_context_report_hash(report) != report.report_hash:
        raise GenOfficeWorkerImageAdmissionError("GenOffice development build context report hash is invalid")
    return report


def _load_inspect(path: Path, *, expected_ref: str) -> tuple[dict[str, Any], str]:
    content_hash, _ = _hash_file(path, maximum_size=MAX_SMALL_EVIDENCE_BYTES)
    value = _read_json(path)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice Docker inspect evidence must contain one image")
    image = value[0]
    if expected_ref not in image.get("RepoTags", []):
        raise GenOfficeWorkerImageAdmissionError("GenOffice Docker inspect evidence is bound to another tag")
    return image, content_hash


def _inspect_boundary(
    image: Mapping[str, Any],
    *,
    context_report: GenOfficeDevelopmentBuildContextReport,
) -> tuple[str, str, int, tuple[str, ...]]:
    manifest_digest = str(image.get("Id", ""))
    if not _SHA256_PATTERN.fullmatch(manifest_digest):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker manifest ID is not a SHA-256 digest")
    descriptor = image.get("Descriptor")
    if not isinstance(descriptor, dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker OCI descriptor is missing")
    descriptor_digest = str(descriptor.get("digest", ""))
    descriptor_media_type = descriptor.get("mediaType")
    annotations = descriptor.get("annotations")
    if (
        descriptor_digest != manifest_digest
        or descriptor_media_type != "application/vnd.oci.image.manifest.v1+json"
        or not isinstance(annotations, dict)
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker OCI descriptor is invalid")
    image_config_digest = str(annotations.get("config.digest", ""))
    if not _SHA256_PATTERN.fullmatch(image_config_digest):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker config digest is missing")
    if (image.get("Os"), image.get("Architecture")) != ("linux", "amd64"):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image platform is not linux/amd64")
    size = image.get("Size")
    if not isinstance(size, int) or not 0 < size <= MAX_IMAGE_ARCHIVE_BYTES:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image size is invalid")
    config = image.get("Config")
    rootfs = image.get("RootFS")
    if not isinstance(config, dict) or not isinstance(rootfs, dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image configuration is missing")
    labels = config.get("Labels")
    if not isinstance(labels, dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image labels are missing")
    expected_labels = {
        "io.collabio.genoffice.authorization-report-sha256": context_report.development_authorization_report_hash,
        "io.collabio.genoffice.build-context-report-sha256": context_report.report_hash,
        "io.collabio.genoffice.build-context-sha256": context_report.context_tar_sha256,
        "io.collabio.genoffice.execution-state": "blocked",
        "io.collabio.genoffice.production-use-allowed": "false",
        "io.collabio.genoffice.scope": "development_evaluation",
        "io.collabio.genoffice.source-import-allowed": "false",
        "io.collabio.genoffice.tenant-content-allowed": "false",
    }
    if any(labels.get(name) != expected for name, expected in expected_labels.items()):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image boundary labels are invalid")
    if (
        config.get("User") != GENOFFICE_WORKER_USER
        or config.get("WorkingDir") != GENOFFICE_WORKER_WORKDIR
        or tuple(config.get("Entrypoint") or ()) != GENOFFICE_WORKER_ENTRYPOINT
        or tuple(config.get("Cmd") or ()) != GENOFFICE_WORKER_COMMAND
        or config.get("ExposedPorts") not in (None, {})
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker runtime boundary is not hardened")
    environment = config.get("Env")
    if not isinstance(environment, list) or "NODE_ENV=production" not in environment:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker production dependency mode is not configured")
    layers = tuple(rootfs.get("Layers") or ())
    if rootfs.get("Type") != "layers" or not layers or not all(_SHA256_PATTERN.fullmatch(item) for item in layers):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker rootfs evidence is invalid")
    return manifest_digest, image_config_digest, size, layers


def _read_archive_member(
    archive: tarfile.TarFile,
    members: Mapping[str, tarfile.TarInfo],
    name: str,
    *,
    maximum_size: int,
) -> bytes:
    member = members.get(name)
    if member is None or not member.isfile() or not 0 <= member.size <= maximum_size:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice image archive member is invalid: {name}")
    source = archive.extractfile(member)
    if source is None:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice image archive member is unreadable: {name}")
    return source.read()


def _verify_oci_archive(
    archive: tarfile.TarFile,
    members: Mapping[str, tarfile.TarInfo],
    *,
    manifest_digest: str | None,
    image_id: str,
    image_ref: str,
    config_name: str,
    layers: list[Any],
) -> None:
    if manifest_digest is None or not _SHA256_PATTERN.fullmatch(manifest_digest):
        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI archive lacks its inspected manifest digest")
    layout = json.loads(
        _read_archive_member(archive, members, "oci-layout", maximum_size=1024).decode("utf-8")
    )
    index = json.loads(
        _read_archive_member(archive, members, "index.json", maximum_size=1024 * 1024).decode("utf-8")
    )
    descriptors = index.get("manifests") if isinstance(index, dict) else None
    if (
        layout != {"imageLayoutVersion": "1.0.0"}
        or not isinstance(index, dict)
        or index.get("schemaVersion") != 2
        or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
        or not isinstance(descriptors, list)
        or len(descriptors) != 1
        or not isinstance(descriptors[0], dict)
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI archive index is invalid")
    descriptor = descriptors[0]
    annotations = descriptor.get("annotations")
    expected_image_names = {image_ref, f"docker.io/{image_ref}"}
    if (
        descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        or descriptor.get("digest") != manifest_digest
        or not isinstance(annotations, dict)
        or annotations.get("config.digest") != image_id
        or annotations.get("io.containerd.image.name") not in expected_image_names
        or annotations.get("org.opencontainers.image.ref.name") != image_ref.rsplit(":", maxsplit=1)[-1]
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI archive descriptor is invalid")
    manifest_name = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
    manifest_content = _read_archive_member(
        archive,
        members,
        manifest_name,
        maximum_size=1024 * 1024,
    )
    if _sha256_bytes(manifest_content) != manifest_digest or descriptor.get("size") != len(manifest_content):
        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI archive manifest digest is invalid")
    manifest = json.loads(manifest_content.decode("utf-8"))
    config = manifest.get("config") if isinstance(manifest, dict) else None
    layer_descriptors = manifest.get("layers") if isinstance(manifest, dict) else None
    config_member = members.get(config_name)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != 2
        or manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        or not isinstance(config, dict)
        or config.get("mediaType") != "application/vnd.oci.image.config.v1+json"
        or config.get("digest") != image_id
        or config_member is None
        or config.get("size") != config_member.size
        or not isinstance(layer_descriptors, list)
        or len(layer_descriptors) != len(layers)
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI image manifest is invalid")
    accepted_layer_media_types = {
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
    }
    for layer_path, layer_descriptor in zip(layers, layer_descriptors, strict=True):
        layer_member = members.get(str(layer_path))
        expected_digest = f"sha256:{str(layer_path).removeprefix('blobs/sha256/')}"
        if (
            not isinstance(layer_descriptor, dict)
            or layer_descriptor.get("mediaType") not in accepted_layer_media_types
            or layer_descriptor.get("digest") != expected_digest
            or layer_member is None
            or layer_descriptor.get("size") != layer_member.size
        ):
            raise GenOfficeWorkerImageAdmissionError("GenOffice OCI image layer descriptor is invalid")


def _verify_docker_archive(
    path: Path,
    *,
    image_id: str,
    image_ref: str,
    manifest_digest: str | None = None,
) -> tuple[str, int]:
    archive_hash, archive_size = _hash_file(path, maximum_size=MAX_IMAGE_ARCHIVE_BYTES)
    try:
        with tarfile.open(path, mode="r:*") as archive:
            archive_members = archive.getmembers()
            members = {member.name: member for member in archive_members}
            if len(archive_members) > 10_000 or len(members) != len(archive_members):
                raise GenOfficeWorkerImageAdmissionError("GenOffice image archive member inventory is invalid")
            for member in archive_members:
                member_path = PurePosixPath(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or not (member.isfile() or member.isdir())
                ):
                    raise GenOfficeWorkerImageAdmissionError("GenOffice image archive contains an unsafe member")
            manifest = json.loads(
                _read_archive_member(
                    archive,
                    members,
                    "manifest.json",
                    maximum_size=1024 * 1024,
                ).decode("utf-8")
            )
            if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
                raise GenOfficeWorkerImageAdmissionError("GenOffice image archive must contain one image")
            entry = manifest[0]
            config_name = entry.get("Config")
            repo_tags = entry.get("RepoTags")
            layers = entry.get("Layers")
            digest_hex = image_id.removeprefix("sha256:")
            classic_config_name = f"{digest_hex}.json"
            oci_config_name = f"blobs/sha256/{digest_hex}"
            if (
                not isinstance(config_name, str)
                or config_name not in {classic_config_name, oci_config_name}
                or repo_tags != [image_ref]
            ):
                raise GenOfficeWorkerImageAdmissionError("GenOffice image archive identity does not match inspect")
            if not isinstance(layers, list) or not layers:
                raise GenOfficeWorkerImageAdmissionError("GenOffice image archive has no layers")
            config_content = _read_archive_member(
                archive,
                members,
                config_name,
                maximum_size=MAX_SMALL_EVIDENCE_BYTES,
            )
            if _sha256_bytes(config_content) != image_id:
                raise GenOfficeWorkerImageAdmissionError("GenOffice image archive config digest is invalid")
            for layer in layers:
                if (
                    not isinstance(layer, str)
                    or PurePosixPath(layer).is_absolute()
                    or ".." in PurePosixPath(layer).parts
                ):
                    raise GenOfficeWorkerImageAdmissionError("GenOffice image archive layer path is unsafe")
                layer_member = members.get(layer)
                if layer_member is None or not layer_member.isfile():
                    raise GenOfficeWorkerImageAdmissionError("GenOffice image archive layer is not a file")
                if layer.startswith("blobs/sha256/"):
                    layer_file = archive.extractfile(layer_member)
                    if layer_file is None:
                        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI image layer is unreadable")
                    layer_hash, layer_size = _hash_stream(layer_file, maximum_size=MAX_IMAGE_ARCHIVE_BYTES)
                    if layer_hash != f"sha256:{layer.removeprefix('blobs/sha256/')}" or layer_size != layer_member.size:
                        raise GenOfficeWorkerImageAdmissionError("GenOffice OCI image layer digest is invalid")
            if config_name == oci_config_name:
                _verify_oci_archive(
                    archive,
                    members,
                    manifest_digest=manifest_digest,
                    image_id=image_id,
                    image_ref=image_ref,
                    config_name=config_name,
                    layers=layers,
                )
    except (KeyError, OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice image archive is invalid") from exc
    return archive_hash, archive_size


def build_genoffice_worker_build_evidence_report_hash(report: GenOfficeWorkerImageBuildEvidence) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_genoffice_worker_image_build_evidence(
    *,
    context_report_path: Path,
    context_tar_path: Path,
    exception_report_path: Path,
    license_material_report_path: Path,
    dockerfile_path: Path,
    inspect_a_path: Path,
    inspect_b_path: Path,
    image_archive_path: Path,
    image_ref_a: str,
    image_ref_b: str,
    observed_at_utc: datetime,
) -> GenOfficeWorkerImageBuildEvidence:
    context_report = _load_context_report(context_report_path)
    context_hash, context_size = _hash_file(context_tar_path, maximum_size=MAX_IMAGE_ARCHIVE_BYTES)
    if context_hash != context_report.context_tar_sha256 or context_size != context_report.context_tar_size_bytes:
        raise GenOfficeWorkerImageAdmissionError("GenOffice development build context TAR is invalid")
    try:
        exception_report = load_genoffice_solo_founder_report(exception_report_path)
        license_report = load_genoffice_license_material_collection_report(license_material_report_path)
    except (GenOfficeSoloFounderExceptionError, GenOfficeLicenseMaterialCollectionError) as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker build prerequisite evidence is invalid") from exc
    observed_at = observed_at_utc.astimezone(UTC)
    if not exception_report.issued_at_utc <= observed_at <= exception_report.valid_until_utc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice solo-founder worker-build authorization is not active")
    if (
        not exception_report.reproducible_worker_build_allowed
        or context_report.authorization_mode != "solo_founder_development_exception"
        or context_report.development_authorization_report_hash != exception_report.report_hash
        or context_report.signer_policy_hash != exception_report.signer_policy_hash
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker build is not bound to its active authorization")
    if (
        license_report.source_report_hash != context_report.source_report_hash
        or license_report.source_archive_sha256 != context_report.source_archive_sha256
        or license_report.artifact_count != 21
        or not license_report.all_artifact_integrities_verified
        or license_report.credentials_used
        or license_report.lifecycle_execution_performed
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice offline dependency evidence is invalid")
    image_a, inspect_a_hash = _load_inspect(inspect_a_path, expected_ref=image_ref_a)
    image_b, inspect_b_hash = _load_inspect(inspect_b_path, expected_ref=image_ref_b)
    manifest_a, image_id_a, image_size_a, layers_a = _inspect_boundary(image_a, context_report=context_report)
    manifest_b, image_id_b, image_size_b, layers_b = _inspect_boundary(image_b, context_report=context_report)
    if (manifest_a, image_id_a, image_size_a, layers_a) != (manifest_b, image_id_b, image_size_b, layers_b):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image builds are not reproducible")
    archive_hash, archive_size = _verify_docker_archive(
        image_archive_path,
        image_id=image_id_a,
        image_ref=image_ref_a,
        manifest_digest=manifest_a,
    )
    dockerfile_hash, _ = _hash_file(dockerfile_path, maximum_size=1024 * 1024)
    draft = GenOfficeWorkerImageBuildEvidence(
        observed_at_utc=observed_at,
        image_ref_a=image_ref_a,
        image_ref_b=image_ref_b,
        image_config_digest=image_id_a,
        image_size_bytes=image_size_a,
        image_archive_size_bytes=archive_size,
        image_archive_sha256=archive_hash,
        rootfs_layer_digests=layers_a,
        build_a_inspect_sha256=inspect_a_hash,
        build_b_inspect_sha256=inspect_b_hash,
        dockerfile_sha256=dockerfile_hash,
        development_build_context_report_hash=context_report.report_hash,
        development_build_context_tar_sha256=context_report.context_tar_sha256,
        source_archive_sha256=context_report.source_archive_sha256,
        source_manifest_hash=context_report.source_manifest_hash,
        development_authorization_report_hash=context_report.development_authorization_report_hash,
        signer_policy_hash=context_report.signer_policy_hash,
        license_material_collection_report_hash=license_report.report_hash,
        dependency_archive_count=license_report.artifact_count,
        runtime_package_count=len(license_report.artifacts),
        source_date_epoch=context_report.source_date_epoch,
        report_hash=_ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_worker_build_evidence_report_hash(draft)})


def load_genoffice_worker_build_evidence(path: Path) -> GenOfficeWorkerImageBuildEvidence:
    try:
        report = GenOfficeWorkerImageBuildEvidence.model_validate(_read_json(path))
    except ValueError as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker build evidence is invalid") from exc
    if build_genoffice_worker_build_evidence_report_hash(report) != report.report_hash:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker build evidence hash is invalid")
    return report


def _component_purl(component: Mapping[str, Any]) -> str | None:
    purl = component.get("purl")
    return purl if isinstance(purl, str) and purl.startswith("pkg:") else None


def _normalized_component(component: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = json.loads(json.dumps(component))
    purl = _component_purl(normalized)
    if purl is not None:
        normalized["bom-ref"] = purl
    normalized.pop("evidence", None)
    return normalized


def build_genoffice_worker_image_sbom(
    *,
    raw_sbom: Mapping[str, Any],
    raw_sbom_sha256: str,
    build_evidence: GenOfficeWorkerImageBuildEvidence,
    source_report: GenOfficeDocxSourceAdmissionReport,
    prebuild_sbom: Mapping[str, Any],
) -> dict[str, Any]:
    if raw_sbom.get("bomFormat") != "CycloneDX" or not isinstance(raw_sbom.get("components"), list):
        raise GenOfficeWorkerImageAdmissionError("GenOffice raw image SBOM is not CycloneDX")
    raw_components = [item for item in raw_sbom["components"] if isinstance(item, dict)]
    if len(raw_components) != len(raw_sbom["components"]):
        raise GenOfficeWorkerImageAdmissionError("GenOffice raw image SBOM contains malformed components")
    normalized_by_purl: dict[str, dict[str, Any]] = {}
    for component in raw_components:
        purl = _component_purl(component)
        if purl is not None:
            if purl in normalized_by_purl:
                raise GenOfficeWorkerImageAdmissionError("GenOffice raw image SBOM contains duplicate PURLs")
            normalized_by_purl[purl] = _normalized_component(component)
    expected_runtime_purls = {
        f"pkg:npm/{dependency.name.replace('@', '%40', 1) if dependency.name.startswith('@') else dependency.name}"
        f"@{dependency.version}"
        for dependency in source_report.runtime_dependencies
    }
    raw_npm_purls = {purl for purl in normalized_by_purl if purl.startswith("pkg:npm/")}
    if not expected_runtime_purls.issubset(raw_npm_purls):
        raise GenOfficeWorkerImageAdmissionError("GenOffice image SBOM lacks reviewed npm runtime packages")
    unknown_runtime_purls = raw_npm_purls - expected_runtime_purls
    engine_purl = "pkg:npm/%40genoffice/docx-engine@0.1.0"
    if unknown_runtime_purls not in (set(), {engine_purl}):
        raise GenOfficeWorkerImageAdmissionError("GenOffice image SBOM contains unexpected npm packages")
    prebuild_components = prebuild_sbom.get("components")
    if not isinstance(prebuild_components, list):
        raise GenOfficeWorkerImageAdmissionError("GenOffice pre-build SBOM components are missing")
    prebuild_by_purl = {
        str(component["purl"]): _normalized_component(component)
        for component in prebuild_components
        if isinstance(component, dict) and isinstance(component.get("purl"), str)
    }
    prebuild_root = prebuild_sbom.get("metadata", {}).get("component")
    if not isinstance(prebuild_root, dict) or _component_purl(prebuild_root) != engine_purl:
        raise GenOfficeWorkerImageAdmissionError("GenOffice pre-build SBOM root is invalid")
    normalized_by_purl.setdefault(engine_purl, _normalized_component(prebuild_root))
    vendored_purl = "pkg:npm/emf-converter@2.0.2"
    vendored = prebuild_by_purl.get(vendored_purl)
    if vendored is None:
        raise GenOfficeWorkerImageAdmissionError("GenOffice vendored runtime component is absent from pre-build SBOM")
    normalized_by_purl.setdefault(vendored_purl, vendored)
    npm_purls = {purl for purl in normalized_by_purl if purl.startswith("pkg:npm/")}
    if npm_purls != expected_runtime_purls | {engine_purl, vendored_purl}:
        raise GenOfficeWorkerImageAdmissionError("GenOffice authoritative npm inventory is not exact")
    os_purls = {purl for purl in normalized_by_purl if purl.startswith("pkg:deb/")}
    if not os_purls:
        raise GenOfficeWorkerImageAdmissionError("GenOffice image SBOM lacks Debian package inventory")
    image_digest = build_evidence.image_config_digest
    image_component_ref = f"urn:collabio:genoffice-worker:{image_digest}"
    timestamp = datetime.fromtimestamp(build_evidence.source_date_epoch, tz=UTC).isoformat().replace("+00:00", "Z")
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"{GENOFFICE_WORKER_IMAGE_NAME}@{image_digest}")
    components = sorted(normalized_by_purl.values(), key=lambda item: str(item.get("purl", item.get("bom-ref", ""))))
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "lifecycles": [{"phase": "build"}],
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "author": "Collabio",
                        "name": "genoffice-worker-image-sbom-normalizer",
                        "version": "1",
                    },
                    {
                        "type": "application",
                        "author": "Aqua Security",
                        "name": "Trivy",
                        "version": GENOFFICE_WORKER_TRIVY_VERSION,
                    },
                ]
            },
            "component": {
                "type": "container",
                "bom-ref": image_component_ref,
                "name": GENOFFICE_WORKER_IMAGE_NAME,
                "version": image_digest,
                "hashes": [{"alg": "SHA-256", "content": image_digest.removeprefix("sha256:")}],
                "properties": [
                    {"name": "collabio:genoffice:execution-state", "value": "blocked"},
                    {"name": "collabio:genoffice:source-import-allowed", "value": "false"},
                    {"name": "collabio:genoffice:tenant-content-allowed", "value": "false"},
                    {"name": "collabio:genoffice:production-use-allowed", "value": "false"},
                ],
            },
            "properties": [
                {"name": "collabio:genoffice:schema-version", "value": GENOFFICE_WORKER_IMAGE_SBOM_SCHEMA_VERSION},
                {"name": "collabio:genoffice:raw-scanner-sbom-sha256", "value": raw_sbom_sha256},
                {"name": "collabio:genoffice:build-evidence-report-hash", "value": build_evidence.report_hash},
                {
                    "name": "collabio:genoffice:development-build-context-report-hash",
                    "value": build_evidence.development_build_context_report_hash,
                },
            ],
        },
        "components": components,
        "dependencies": [
            {"ref": image_component_ref, "dependsOn": [engine_purl]},
            {
                "ref": engine_purl,
                "dependsOn": sorted(expected_runtime_purls | {vendored_purl}),
            },
        ],
    }


def _sbom_inventory(sbom: Mapping[str, Any]) -> tuple[str, int, int, int, str]:
    metadata = sbom.get("metadata")
    components = sbom.get("components")
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM identity is invalid")
    if not isinstance(metadata, dict) or not isinstance(components, list):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM inventory is missing")
    root = metadata.get("component")
    if not isinstance(root, dict) or root.get("name") != GENOFFICE_WORKER_IMAGE_NAME:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM root component is invalid")
    hashes = root.get("hashes")
    if not isinstance(hashes, list) or len(hashes) != 1 or not isinstance(hashes[0], dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM root digest is missing")
    image_digest = f"sha256:{hashes[0].get('content', '')}"
    _require_sha256(image_digest, field="worker SBOM image digest")
    purls = [_component_purl(item) for item in components if isinstance(item, dict)]
    if len(purls) != len(components) or any(purl is None for purl in purls):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM component PURLs are incomplete")
    values = [str(purl) for purl in purls]
    if len(values) != len(set(values)):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM component PURLs are duplicated")
    npm_count = sum(item.startswith("pkg:npm/") for item in values)
    os_count = sum(item.startswith("pkg:deb/") for item in values)
    properties = metadata.get("properties")
    raw_hash = None
    if isinstance(properties, list):
        for item in properties:
            if isinstance(item, dict) and item.get("name") == "collabio:genoffice:raw-scanner-sbom-sha256":
                raw_hash = item.get("value")
    if not isinstance(raw_hash, str):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM raw scanner binding is absent")
    _require_sha256(raw_hash, field="raw scanner SBOM hash")
    return image_digest, len(values), npm_count, os_count, raw_hash


def _schema_receipt(path: Path, *, sbom_hash: str) -> str:
    receipt_hash, _ = _hash_file(path, maximum_size=1024 * 1024)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM validation receipt is unreadable") from exc
    values: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition("=")
        if not separator or name in values:
            raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM validation receipt is malformed")
        values[name] = value
    expected = {
        "schema": "cyclonedx-1.6",
        "validator": GENOFFICE_WORKER_CYCLONEDX_VALIDATOR_REF,
        "sbom_sha256": sbom_hash.removeprefix("sha256:"),
        "status": "valid",
    }
    if values != expected:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM validation receipt is not bound")
    return receipt_hash


def _trivy_review(
    path: Path,
    *,
    expected_npm_count: int,
) -> tuple[str, datetime, int, dict[str, int], tuple[GenOfficeWorkerVulnerabilityFinding, ...]]:
    report_hash, _ = _hash_file(path, maximum_size=MAX_SMALL_EVIDENCE_BYTES)
    report = _read_json(path)
    trivy = report.get("Trivy") if isinstance(report, dict) else None
    if (
        not isinstance(report, dict)
        or report.get("SchemaVersion") != 2
        or report.get("ArtifactType") != "cyclonedx"
        or not isinstance(trivy, dict)
        or trivy.get("Version") != GENOFFICE_WORKER_TRIVY_VERSION
        or PurePosixPath(str(report.get("ArtifactName", ""))).name != "genoffice-worker-image.cdx.json"
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy report identity is invalid")
    scan_time = _parse_datetime(str(report.get("CreatedAt", "")), field="worker Trivy scan time")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy report has no results")
    package_purls: set[str] = set()
    findings: list[GenOfficeWorkerVulnerabilityFinding] = []
    for result in results:
        if not isinstance(result, dict):
            raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy result is malformed")
        packages = result.get("Packages") or []
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(packages, list) or not isinstance(vulnerabilities, list):
            raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy package inventory is malformed")
        for package in packages:
            identifier = package.get("Identifier") if isinstance(package, dict) else None
            purl = identifier.get("PURL") if isinstance(identifier, dict) else None
            if isinstance(purl, str):
                package_purls.add(purl)
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise GenOfficeWorkerImageAdmissionError("GenOffice worker vulnerability is malformed")
            severity = str(vulnerability.get("Severity", "UNKNOWN")).upper()
            if severity not in _SEVERITIES:
                severity = "UNKNOWN"
            identifier = vulnerability.get("PkgIdentifier")
            purl = identifier.get("PURL") if isinstance(identifier, dict) else None
            findings.append(
                GenOfficeWorkerVulnerabilityFinding(
                    vulnerability_id=str(vulnerability.get("VulnerabilityID", "unknown")),
                    package_purl=str(purl or "unknown"),
                    package_name=str(vulnerability.get("PkgName", "unknown")),
                    installed_version=str(vulnerability.get("InstalledVersion", "unknown")),
                    fixed_version=(str(vulnerability["FixedVersion"]) if vulnerability.get("FixedVersion") else None),
                    severity=severity,
                    primary_url=(str(vulnerability["PrimaryURL"]) if vulnerability.get("PrimaryURL") else None),
                )
            )
    if sum(purl.startswith("pkg:npm/") for purl in package_purls) < expected_npm_count:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy scan lacks npm runtime packages")
    severity_counter = Counter(item.severity for item in findings)
    severity_counts = {severity: severity_counter.get(severity, 0) for severity in _SEVERITIES}
    if severity_counts["HIGH"] or severity_counts["CRITICAL"]:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker image has high or critical vulnerabilities")
    return report_hash, scan_time, len(findings), severity_counts, tuple(findings)


def _trivy_db_review(path: Path, *, scan_time: datetime) -> tuple[str, datetime, int]:
    metadata_hash, _ = _hash_file(path, maximum_size=1024 * 1024)
    metadata = _read_json(path, maximum_size=1024 * 1024)
    if not isinstance(metadata, dict) or metadata.get("Version") != 2:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy DB metadata is invalid")
    updated_at = _parse_datetime(str(metadata.get("UpdatedAt", "")), field="worker Trivy DB update time")
    downloaded_at = _parse_datetime(str(metadata.get("DownloadedAt", "")), field="worker Trivy DB download time")
    next_update_at = _parse_datetime(str(metadata.get("NextUpdate", "")), field="worker Trivy DB next update time")
    age_seconds = int((scan_time - updated_at).total_seconds())
    if not (0 <= age_seconds <= MAX_TRIVY_DB_AGE_SECONDS and updated_at <= downloaded_at <= scan_time < next_update_at):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker Trivy DB was not fresh at scan time")
    return metadata_hash, updated_at, age_seconds


def build_genoffice_worker_attestation_payload_hash(payload: GenOfficeWorkerBuildAttestationPayload) -> str:
    return stable_hash(canonical_json(payload.model_dump(mode="json", exclude={"payload_hash"})))


def build_genoffice_worker_signing_request_hash(request: GenOfficeWorkerBuildSigningRequest) -> str:
    return stable_hash(canonical_json(request.model_dump(mode="json", exclude={"request_hash"})))


def build_genoffice_worker_signature_response_hash(response: GenOfficeWorkerBuildSignatureResponse) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json")))


def build_genoffice_worker_admission_report_hash(report: GenOfficeWorkerImageAdmissionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_genoffice_worker_signature_message(payload: GenOfficeWorkerBuildAttestationPayload) -> bytes:
    return canonical_json(payload.model_dump(mode="json")).encode("utf-8")


def build_genoffice_worker_signing_request(
    *,
    build_evidence: GenOfficeWorkerImageBuildEvidence,
    sbom: Mapping[str, Any],
    sbom_path: Path,
    schema_receipt_path: Path,
    vulnerability_report_path: Path,
    trivy_db_metadata_path: Path,
    policy: GenOfficeSoloFounderPolicy,
    exception_report: GenOfficeSoloFounderExceptionReport,
    attestation_id: str,
    issued_at_utc: datetime,
    valid_until_utc: datetime,
) -> tuple[GenOfficeWorkerBuildSigningRequest, bytes]:
    issued_at = issued_at_utc.astimezone(UTC)
    valid_until = valid_until_utc.astimezone(UTC)
    if not exception_report.issued_at_utc <= issued_at < valid_until <= exception_report.valid_until_utc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker attestation exceeds its active authorization")
    if (
        build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash
        or build_genoffice_solo_founder_report_hash(exception_report) != exception_report.report_hash
        or exception_report.signer_policy_hash != policy.policy_hash
        or build_evidence.signer_policy_hash != policy.policy_hash
        or build_evidence.development_authorization_report_hash != exception_report.report_hash
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signer or authorization evidence drifted")
    sbom_hash, _ = _hash_file(sbom_path, maximum_size=MAX_SMALL_EVIDENCE_BYTES)
    image_digest, component_count, npm_count, os_count, raw_sbom_hash = _sbom_inventory(sbom)
    if image_digest != build_evidence.image_config_digest:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM is bound to another image")
    receipt_hash = _schema_receipt(schema_receipt_path, sbom_hash=sbom_hash)
    vulnerability_hash, scan_time, finding_count, severity_counts, findings = _trivy_review(
        vulnerability_report_path,
        expected_npm_count=npm_count,
    )
    db_hash, db_updated_at, db_age = _trivy_db_review(trivy_db_metadata_path, scan_time=scan_time)
    payload_draft = GenOfficeWorkerBuildAttestationPayload(
        attestation_id=attestation_id,
        issued_at_utc=issued_at,
        valid_until_utc=valid_until,
        image_config_digest=build_evidence.image_config_digest,
        image_archive_sha256=build_evidence.image_archive_sha256,
        build_evidence_report_hash=build_evidence.report_hash,
        development_build_context_report_hash=build_evidence.development_build_context_report_hash,
        development_build_context_tar_sha256=build_evidence.development_build_context_tar_sha256,
        development_authorization_report_hash=build_evidence.development_authorization_report_hash,
        signer_policy_hash=build_evidence.signer_policy_hash,
        worker_sbom_sha256=sbom_hash,
        raw_scanner_sbom_sha256=raw_sbom_hash,
        worker_sbom_component_count=component_count,
        worker_sbom_npm_component_count=npm_count,
        worker_sbom_os_component_count=os_count,
        sbom_schema_validation_receipt_hash=receipt_hash,
        vulnerability_report_hash=vulnerability_hash,
        trivy_db_metadata_hash=db_hash,
        vulnerability_count=finding_count,
        severity_counts=severity_counts,
        vulnerability_findings=findings,
        trivy_db_updated_at_utc=db_updated_at,
        trivy_db_age_seconds_at_scan=db_age,
        payload_hash=_ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_worker_attestation_payload_hash(payload_draft)}
    )
    message = build_genoffice_worker_signature_message(payload)
    request_draft = GenOfficeWorkerBuildSigningRequest(
        prepared_at_utc=issued_at,
        payload=payload,
        signing_assignment=GenOfficeWorkerBuildSigningAssignment(
            signer_id=policy.signer.signer_id,
            key_id=policy.signer.key_id,
        ),
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        request_hash=_ZERO_HASH,
    )
    request = request_draft.model_copy(
        update={"request_hash": build_genoffice_worker_signing_request_hash(request_draft)}
    )
    return request, message


def verify_genoffice_worker_signing_request(request: GenOfficeWorkerBuildSigningRequest) -> bytes:
    if build_genoffice_worker_attestation_payload_hash(request.payload) != request.payload.payload_hash:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker attestation payload hash is invalid")
    if build_genoffice_worker_signing_request_hash(request) != request.request_hash:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signing request hash is invalid")
    message = build_genoffice_worker_signature_message(request.payload)
    if (
        _sha256_bytes(message) != request.signature_message_sha256
        or len(message) != request.signature_message_size_bytes
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signature message binding is invalid")
    return message


def verify_genoffice_worker_image_admission(
    *,
    build_evidence: GenOfficeWorkerImageBuildEvidence,
    policy: GenOfficeSoloFounderPolicy,
    exception_report: GenOfficeSoloFounderExceptionReport,
    request: GenOfficeWorkerBuildSigningRequest,
    response: GenOfficeWorkerBuildSignatureResponse,
    verified_at_utc: datetime,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeWorkerImageAdmissionReport:
    message = verify_genoffice_worker_signing_request(request)
    verified_at = verified_at_utc.astimezone(UTC)
    if not request.payload.issued_at_utc <= verified_at <= request.payload.valid_until_utc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker build attestation is not currently valid")
    if not exception_report.issued_at_utc <= verified_at <= exception_report.valid_until_utc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice solo-founder worker authorization expired")
    if (
        build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash
        or build_genoffice_solo_founder_report_hash(exception_report) != exception_report.report_hash
        or exception_report.signer_policy_hash != policy.policy_hash
        or request.payload.signer_policy_hash != policy.policy_hash
        or request.payload.build_evidence_report_hash != build_evidence.report_hash
        or request.payload.development_authorization_report_hash != exception_report.report_hash
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signed evidence chain drifted")
    assignment = request.signing_assignment
    if (assignment.signer_id, assignment.key_id) != (policy.signer.signer_id, policy.signer.key_id):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signing assignment drifted")
    if (
        response.request_hash != request.request_hash
        or response.signature_message_sha256 != request.signature_message_sha256
        or (response.signer_id, response.key_id) != (assignment.signer_id, assignment.key_id)
    ):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signature response is bound to another request")
    public_key = _decode_canonical_base64(
        policy.signer.ed25519_public_key_base64,
        label="worker public key",
        expected_size=PUBLIC_KEY_SIZE_BYTES,
    )
    signature = _decode_canonical_base64(
        response.signature_base64,
        label="worker detached signature",
        expected_size=SIGNATURE_SIZE_BYTES,
    )
    if not signature_verifier.verify_ed25519(public_key=public_key, signature=signature, message=message):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker detached signature is invalid")
    payload = request.payload
    draft = GenOfficeWorkerImageAdmissionReport(
        attestation_id=payload.attestation_id,
        issued_at_utc=payload.issued_at_utc,
        valid_until_utc=payload.valid_until_utc,
        signer_id=assignment.signer_id,
        key_id=assignment.key_id,
        signer_policy_hash=policy.policy_hash,
        solo_founder_exception_report_hash=exception_report.report_hash,
        image_config_digest=payload.image_config_digest,
        image_archive_sha256=payload.image_archive_sha256,
        build_evidence_report_hash=payload.build_evidence_report_hash,
        development_build_context_report_hash=payload.development_build_context_report_hash,
        development_build_context_tar_sha256=payload.development_build_context_tar_sha256,
        worker_sbom_sha256=payload.worker_sbom_sha256,
        raw_scanner_sbom_sha256=payload.raw_scanner_sbom_sha256,
        sbom_schema_validation_receipt_hash=payload.sbom_schema_validation_receipt_hash,
        vulnerability_report_hash=payload.vulnerability_report_hash,
        trivy_db_metadata_hash=payload.trivy_db_metadata_hash,
        vulnerability_count=payload.vulnerability_count,
        severity_counts=payload.severity_counts,
        signing_request_hash=request.request_hash,
        signature_response_hash=build_genoffice_worker_signature_response_hash(response),
        attestation_payload_hash=payload.payload_hash,
        report_hash=_ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_worker_admission_report_hash(draft)})


def load_genoffice_worker_signing_request(path: Path) -> GenOfficeWorkerBuildSigningRequest:
    try:
        request = GenOfficeWorkerBuildSigningRequest.model_validate(_read_json(path))
    except ValueError as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signing request is invalid") from exc
    verify_genoffice_worker_signing_request(request)
    return request


def load_genoffice_worker_signature_response(path: Path) -> GenOfficeWorkerBuildSignatureResponse:
    try:
        return GenOfficeWorkerBuildSignatureResponse.model_validate(_read_json(path))
    except ValueError as exc:
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker signature response is invalid") from exc


def persist_genoffice_worker_schemas(*, output_directory: Path) -> dict[str, str]:
    schemas = {
        "build_evidence": (
            "genoffice-worker-image-build-evidence.schema.json",
            GenOfficeWorkerImageBuildEvidence.model_json_schema(),
        ),
        "request": (
            "genoffice-worker-build-signing-request.schema.json",
            GenOfficeWorkerBuildSigningRequest.model_json_schema(),
        ),
        "response": (
            "genoffice-worker-build-signature-response.schema.json",
            GenOfficeWorkerBuildSignatureResponse.model_json_schema(),
        ),
        "admission": (
            "genoffice-worker-image-admission-report.schema.json",
            GenOfficeWorkerImageAdmissionReport.model_json_schema(),
        ),
    }
    hashes: dict[str, str] = {}
    for name, (filename, schema) in schemas.items():
        content = _json_bytes(schema)
        _write_new_private(output_directory / filename, content)
        hashes[name] = _sha256_bytes(content)
    return hashes


def _required(env: Mapping[str, str], names: Mapping[str, str]) -> dict[str, str]:
    values = {name: env.get(key, "").strip() for name, key in names.items()}
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeWorkerImageAdmissionError(f"GenOffice worker values are missing: {missing}")
    return values


def _run_evidence(env: Mapping[str, str]) -> GenOfficeWorkerImageBuildEvidence:
    values = _required(
        env,
        {
            "context_report": "SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_REPORT_PATH",
            "context_tar": "SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_PATH",
            "exception_report": "SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH",
            "license_report": "SUITE_GENOFFICE_LICENSE_MATERIAL_REPORT_PATH",
            "dockerfile": "SUITE_GENOFFICE_WORKER_DOCKERFILE_PATH",
            "inspect_a": "SUITE_GENOFFICE_WORKER_INSPECT_A_PATH",
            "inspect_b": "SUITE_GENOFFICE_WORKER_INSPECT_B_PATH",
            "image_archive": "SUITE_GENOFFICE_WORKER_IMAGE_ARCHIVE_PATH",
            "image_ref_a": "SUITE_GENOFFICE_WORKER_IMAGE_REF_A",
            "image_ref_b": "SUITE_GENOFFICE_WORKER_IMAGE_REF_B",
            "observed_at": "SUITE_GENOFFICE_WORKER_OBSERVED_AT_UTC",
            "output": "SUITE_GENOFFICE_WORKER_BUILD_EVIDENCE_PATH",
        },
    )
    report = build_genoffice_worker_image_build_evidence(
        context_report_path=Path(values["context_report"]),
        context_tar_path=Path(values["context_tar"]),
        exception_report_path=Path(values["exception_report"]),
        license_material_report_path=Path(values["license_report"]),
        dockerfile_path=Path(values["dockerfile"]),
        inspect_a_path=Path(values["inspect_a"]),
        inspect_b_path=Path(values["inspect_b"]),
        image_archive_path=Path(values["image_archive"]),
        image_ref_a=values["image_ref_a"],
        image_ref_b=values["image_ref_b"],
        observed_at_utc=_parse_datetime(values["observed_at"], field="worker observation time"),
    )
    _write_new_private(Path(values["output"]), _json_bytes(report))
    return report


def _load_prebuild_sbom_unbound(path: Path) -> Mapping[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict) or value.get("bomFormat") != "CycloneDX":
        raise GenOfficeWorkerImageAdmissionError("GenOffice pre-build SBOM is invalid")
    return value


def _run_request(env: Mapping[str, str]) -> GenOfficeWorkerBuildSigningRequest:
    values = _required(
        env,
        {
            "build_evidence": "SUITE_GENOFFICE_WORKER_BUILD_EVIDENCE_PATH",
            "sbom": "SUITE_GENOFFICE_WORKER_SBOM_PATH",
            "schema_receipt": "SUITE_GENOFFICE_WORKER_SBOM_SCHEMA_RECEIPT_PATH",
            "vulnerability_report": "SUITE_GENOFFICE_WORKER_VULNERABILITY_REPORT_PATH",
            "trivy_db": "SUITE_GENOFFICE_TRIVY_DB_METADATA_PATH",
            "policy": "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH",
            "exception_report": "SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH",
            "attestation_id": "SUITE_GENOFFICE_WORKER_ATTESTATION_ID",
            "issued_at": "SUITE_GENOFFICE_WORKER_ISSUED_AT_UTC",
            "valid_until": "SUITE_GENOFFICE_WORKER_VALID_UNTIL_UTC",
            "request_output": "SUITE_GENOFFICE_WORKER_SIGNING_REQUEST_PATH",
            "message_output": "SUITE_GENOFFICE_WORKER_SIGNATURE_MESSAGE_PATH",
        },
    )
    sbom = _read_json(Path(values["sbom"]))
    if not isinstance(sbom, dict):
        raise GenOfficeWorkerImageAdmissionError("GenOffice worker SBOM must be an object")
    request, message = build_genoffice_worker_signing_request(
        build_evidence=load_genoffice_worker_build_evidence(Path(values["build_evidence"])),
        sbom=sbom,
        sbom_path=Path(values["sbom"]),
        schema_receipt_path=Path(values["schema_receipt"]),
        vulnerability_report_path=Path(values["vulnerability_report"]),
        trivy_db_metadata_path=Path(values["trivy_db"]),
        policy=load_genoffice_solo_founder_policy(Path(values["policy"])),
        exception_report=load_genoffice_solo_founder_report(Path(values["exception_report"])),
        attestation_id=values["attestation_id"],
        issued_at_utc=_parse_datetime(values["issued_at"], field="worker issue time"),
        valid_until_utc=_parse_datetime(values["valid_until"], field="worker expiration time"),
    )
    _write_new_private(Path(values["request_output"]), _json_bytes(request))
    _write_new_private(Path(values["message_output"]), message)
    return request


def _run_verify(env: Mapping[str, str]) -> GenOfficeWorkerImageAdmissionReport:
    values = _required(
        env,
        {
            "build_evidence": "SUITE_GENOFFICE_WORKER_BUILD_EVIDENCE_PATH",
            "policy": "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH",
            "exception_report": "SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH",
            "request": "SUITE_GENOFFICE_WORKER_SIGNING_REQUEST_PATH",
            "response": "SUITE_GENOFFICE_WORKER_SIGNATURE_RESPONSE_PATH",
            "verified_at": "SUITE_GENOFFICE_WORKER_VERIFIED_AT_UTC",
            "output": "SUITE_GENOFFICE_WORKER_ADMISSION_REPORT_PATH",
        },
    )
    report = verify_genoffice_worker_image_admission(
        build_evidence=load_genoffice_worker_build_evidence(Path(values["build_evidence"])),
        policy=load_genoffice_solo_founder_policy(Path(values["policy"])),
        exception_report=load_genoffice_solo_founder_report(Path(values["exception_report"])),
        request=load_genoffice_worker_signing_request(Path(values["request"])),
        response=load_genoffice_worker_signature_response(Path(values["response"])),
        verified_at_utc=_parse_datetime(values["verified_at"], field="worker verification time"),
    )
    _write_new_private(Path(values["output"]), _json_bytes(report))
    return report


def main() -> None:
    try:
        mode = os.environ.get("SUITE_GENOFFICE_WORKER_ADMISSION_MODE", "").strip()
        if mode == "schema":
            output = os.environ.get("SUITE_GENOFFICE_WORKER_SCHEMA_OUTPUT_DIR", "").strip()
            if not output:
                raise GenOfficeWorkerImageAdmissionError("GenOffice worker schema output directory is missing")
            result: Any = persist_genoffice_worker_schemas(output_directory=Path(output))
        elif mode == "evidence":
            result = _run_evidence(os.environ).model_dump(mode="json")
        elif mode == "sbom":
            values = _required(
                os.environ,
                {
                    "raw_sbom": "SUITE_GENOFFICE_WORKER_RAW_SBOM_PATH",
                    "build_evidence": "SUITE_GENOFFICE_WORKER_BUILD_EVIDENCE_PATH",
                    "source_report": "SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH",
                    "prebuild_sbom": "SUITE_GENOFFICE_PREBUILD_SBOM_PATH",
                    "output": "SUITE_GENOFFICE_WORKER_SBOM_PATH",
                },
            )
            raw_sbom = _read_json(Path(values["raw_sbom"]))
            if not isinstance(raw_sbom, dict):
                raise GenOfficeWorkerImageAdmissionError("GenOffice raw image SBOM must be an object")
            raw_hash, _ = _hash_file(Path(values["raw_sbom"]), maximum_size=MAX_SMALL_EVIDENCE_BYTES)
            result = build_genoffice_worker_image_sbom(
                raw_sbom=raw_sbom,
                raw_sbom_sha256=raw_hash,
                build_evidence=load_genoffice_worker_build_evidence(Path(values["build_evidence"])),
                source_report=load_genoffice_docx_source_admission_report(Path(values["source_report"])),
                prebuild_sbom=_load_prebuild_sbom_unbound(Path(values["prebuild_sbom"])),
            )
            _write_new_private(Path(values["output"]), _json_bytes(result))
        elif mode == "request":
            result = _run_request(os.environ).model_dump(mode="json")
        elif mode == "verify":
            result = _run_verify(os.environ).model_dump(mode="json")
        else:
            raise GenOfficeWorkerImageAdmissionError("GenOffice worker admission mode is invalid")
        print(json.dumps(result, sort_keys=True))
    except (GenOfficeWorkerImageAdmissionError, GenOfficeSourceAdmissionError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_WORKER_ADMISSION_REPORT_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
