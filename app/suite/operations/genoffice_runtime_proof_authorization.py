from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import socket
import stat
import struct
import zipfile
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_worker_image_admission import (
    GenOfficeWorkerImageAdmissionReport,
    build_genoffice_worker_admission_report_hash,
    load_genoffice_worker_image_admission_report,
)

GENOFFICE_RUNTIME_ROLES: tuple[Literal["product_owner", "security_compliance_owner"], ...] = (
    "product_owner",
    "security_compliance_owner",
)
GENOFFICE_RUNTIME_MAX_VALIDITY = timedelta(hours=24)
GENOFFICE_RUNTIME_PURPOSE: Literal["synthetic_docx_fidelity_proof"] = "synthetic_docx_fidelity_proof"
GENOFFICE_RUNTIME_FIXTURE_IDS = (
    "minimal-formatting",
    "deep-xml-passthrough",
    "remote-relationship-no-egress",
    "declared-zip-bomb",
    "active-content-preflight-rejection",
)
GENOFFICE_RUNTIME_ENGINE_FIXTURE_IDS = GENOFFICE_RUNTIME_FIXTURE_IDS[:-1]
GENOFFICE_RUNTIME_PREFLIGHT_ONLY_FIXTURE_IDS = GENOFFICE_RUNTIME_FIXTURE_IDS[-1:]
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
PUBLIC_KEY_SIZE_BYTES = 32
SIGNATURE_SIZE_BYTES = 64
ZERO_HASH = "sha256:" + "0" * 64
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

SignerRole = Literal["product_owner", "security_compliance_owner"]
CorpusCategory = Literal["fidelity", "parser_resilience", "no_egress", "resource_exhaustion", "active_content"]
ExpectedBoundary = Literal[
    "parse_save_roundtrip",
    "byte_preserving_passthrough",
    "no_external_fetch",
    "engine_rejection",
    "preflight_rejection",
]


class GenOfficeRuntimeProofAuthorizationError(ValueError):
    pass


class GenOfficeSyntheticCorpusArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    filename: str
    category: CorpusCategory
    expected_boundary: ExpectedBoundary
    engine_invocation_allowed: bool
    content_sha256: str
    size_bytes: int

    @model_validator(mode="after")
    def require_safe_artifact(self) -> GenOfficeSyntheticCorpusArtifact:
        if not self.fixture_id.strip() or not self.filename.endswith((".docx", ".docm")):
            raise ValueError("GenOffice synthetic fixture identity is invalid")
        if PurePosixPath(self.filename).name != self.filename or self.size_bytes <= 0:
            raise ValueError("GenOffice synthetic fixture path or size is invalid")
        _require_sha256(self.content_sha256, field="synthetic fixture hash")
        if (self.expected_boundary == "preflight_rejection") == self.engine_invocation_allowed:
            raise ValueError("GenOffice synthetic fixture execution boundary is inconsistent")
        return self


class GenOfficeSyntheticCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_synthetic_docx_corpus_manifest.v1"] = (
        "genoffice_synthetic_docx_corpus_manifest.v1"
    )
    source_date_epoch: Literal[0] = 0
    classification: Literal["synthetic_public_non_personal"] = "synthetic_public_non_personal"
    artifacts: tuple[GenOfficeSyntheticCorpusArtifact, ...]
    total_size_bytes: int
    tenant_content_included: Literal[False] = False
    personal_data_included: Literal[False] = False
    customer_content_included: Literal[False] = False
    external_fetch_required: Literal[False] = False
    manifest_hash: str

    @model_validator(mode="after")
    def require_exact_corpus(self) -> GenOfficeSyntheticCorpusManifest:
        if tuple(item.fixture_id for item in self.artifacts) != GENOFFICE_RUNTIME_FIXTURE_IDS:
            raise ValueError("GenOffice synthetic fixture inventory is not exact")
        if len({item.filename for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("GenOffice synthetic fixture filenames are not unique")
        if self.total_size_bytes != sum(item.size_bytes for item in self.artifacts):
            raise ValueError("GenOffice synthetic corpus size is inconsistent")
        _require_sha256(self.manifest_hash, field="synthetic corpus manifest hash")
        return self


class GenOfficeRuntimeSandboxProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_sandbox_profile.v1"] = "genoffice_runtime_sandbox_profile.v1"
    profile_id: Literal["genoffice-synthetic-proof-runsc-v1"] = "genoffice-synthetic-proof-runsc-v1"
    runtime_class: Literal["runsc-kvm"] = "runsc-kvm"
    network_mode: Literal["none"] = "none"
    user: Literal["10003:10003"] = "10003:10003"
    read_only_root_filesystem: Literal[True] = True
    cap_drop: tuple[Literal["ALL"], ...] = ("ALL",)
    no_new_privileges: Literal[True] = True
    pids_limit: Literal[32] = 32
    nano_cpus: Literal[500_000_000] = 500_000_000
    memory_bytes: Literal[536_870_912] = 536_870_912
    scratch_tmpfs: Literal["/scratch:size=64m,noexec,nosuid,nodev,uid=10003,gid=10003,mode=0700"] = (
        "/scratch:size=64m,noexec,nosuid,nodev,uid=10003,gid=10003,mode=0700"
    )
    corpus_mount_read_only: Literal[True] = True
    docker_socket_mounted: Literal[False] = False
    host_devices_mounted: Literal[False] = False
    credentials_mounted: Literal[False] = False
    tenant_storage_mounted: Literal[False] = False
    host_runtime_inspection_required: Literal[True] = True
    outbound_socket_probe_required: Literal[True] = True
    dns_probe_required: Literal[True] = True
    transient_cleanup_required: Literal[True] = True
    profile_hash: str

    @model_validator(mode="after")
    def require_closed_profile(self) -> GenOfficeRuntimeSandboxProfile:
        _require_sha256(self.profile_hash, field="runtime sandbox profile hash")
        return self


class GenOfficeRuntimeSandboxProbeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_sandbox_probe_report.v1"] = "genoffice_runtime_sandbox_probe_report.v1"
    observed_at_utc: datetime
    sandbox_profile_hash: str
    corpus_manifest_hash: str
    docker_inspect_sha256: str
    runtime_class_verified: Literal[True] = True
    network_mode_none_verified: Literal[True] = True
    read_only_root_verified: Literal[True] = True
    read_only_corpus_verified: Literal[True] = True
    capabilities_empty_verified: Literal[True] = True
    no_new_privileges_verified: Literal[True] = True
    resource_limits_verified: Literal[True] = True
    outbound_socket_blocked: Literal[True] = True
    dns_resolution_blocked: Literal[True] = True
    scratch_write_cleanup_verified: Literal[True] = True
    engine_executed: Literal[False] = False
    content_included: Literal[False] = False
    tenant_content_included: Literal[False] = False
    external_network_used: Literal[False] = False
    runtime_authorization_granted: Literal[False] = False
    report_hash: str

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice sandbox observation time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_fail_closed_probe(self) -> GenOfficeRuntimeSandboxProbeReport:
        for field, value in (
            ("runtime sandbox profile hash", self.sandbox_profile_hash),
            ("synthetic corpus manifest hash", self.corpus_manifest_hash),
            ("Docker inspect hash", self.docker_inspect_sha256),
            ("runtime sandbox probe report hash", self.report_hash),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeRuntimeSigner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signer_id: str
    signer_role: SignerRole
    key_id: str
    ed25519_public_key_base64: str
    active: bool = True

    @model_validator(mode="after")
    def require_signer(self) -> GenOfficeRuntimeSigner:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice runtime signer identity is empty")
        _decode_canonical_base64(
            self.ed25519_public_key_base64,
            field="runtime signer public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        )
        return self


class GenOfficeRuntimeSignerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_signer_policy.v1"] = "genoffice_runtime_signer_policy.v1"
    policy_id: str
    purpose: Literal["synthetic_docx_fidelity_proof"] = GENOFFICE_RUNTIME_PURPOSE
    effective_at_utc: datetime
    signers: tuple[GenOfficeRuntimeSigner, ...]
    policy_hash: str

    @field_validator("effective_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice runtime signer policy time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_two_person_policy(self) -> GenOfficeRuntimeSignerPolicy:
        active = tuple(item for item in self.signers if item.active)
        if not self.policy_id.strip() or tuple(item.signer_role for item in active) != GENOFFICE_RUNTIME_ROLES:
            raise ValueError("GenOffice runtime signer policy roles are not exact")
        if len({item.signer_id for item in active}) != 2 or len({item.key_id for item in active}) != 2:
            raise ValueError("GenOffice runtime signer policy violates two-person separation")
        _require_sha256(self.policy_hash, field="runtime signer policy hash")
        return self


class GenOfficeRuntimeAuthorizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_authorization_payload.v1"] = "genoffice_runtime_authorization_payload.v1"
    authorization_id: str
    purpose: Literal["synthetic_docx_fidelity_proof"] = GENOFFICE_RUNTIME_PURPOSE
    issued_at_utc: datetime
    valid_until_utc: datetime
    risk_acceptance_ref: str
    change_control_ref: str
    signer_policy_hash: str
    worker_admission_report_hash: str
    worker_image_config_digest: str
    worker_image_archive_sha256: str
    worker_sbom_sha256: str
    worker_vulnerability_report_hash: str
    corpus_manifest_hash: str
    sandbox_profile_hash: str
    engine_fixture_ids: tuple[str, ...]
    preflight_only_fixture_ids: tuple[str, ...]
    synthetic_worker_execution_allowed: Literal[True] = True
    tenant_content_allowed: Literal[False] = False
    source_import_allowed: Literal[False] = False
    persistent_document_write_allowed: Literal[False] = False
    external_network_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    payload_hash: str

    @field_validator("issued_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice runtime authorization time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_narrow_runtime_scope(self) -> GenOfficeRuntimeAuthorizationPayload:
        identity = (self.authorization_id, self.risk_acceptance_ref, self.change_control_ref)
        if not all(value.strip() for value in identity):
            raise ValueError("GenOffice runtime authorization identity is empty")
        if not self.issued_at_utc < self.valid_until_utc <= self.issued_at_utc + GENOFFICE_RUNTIME_MAX_VALIDITY:
            raise ValueError("GenOffice runtime authorization validity window is invalid")
        if self.engine_fixture_ids != GENOFFICE_RUNTIME_ENGINE_FIXTURE_IDS:
            raise ValueError("GenOffice runtime engine fixture scope is not exact")
        if self.preflight_only_fixture_ids != GENOFFICE_RUNTIME_PREFLIGHT_ONLY_FIXTURE_IDS:
            raise ValueError("GenOffice runtime preflight fixture scope is not exact")
        for field, value in (
            ("runtime signer policy hash", self.signer_policy_hash),
            ("worker admission report hash", self.worker_admission_report_hash),
            ("worker image config digest", self.worker_image_config_digest),
            ("worker image archive hash", self.worker_image_archive_sha256),
            ("worker SBOM hash", self.worker_sbom_sha256),
            ("worker vulnerability report hash", self.worker_vulnerability_report_hash),
            ("synthetic corpus manifest hash", self.corpus_manifest_hash),
            ("runtime sandbox profile hash", self.sandbox_profile_hash),
            ("runtime authorization payload hash", self.payload_hash),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeRuntimeSigningAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signer_id: str
    signer_role: SignerRole
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"


class GenOfficeRuntimeSigningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_signing_request.v1"] = "genoffice_runtime_signing_request.v1"
    prepared_at_utc: datetime
    valid_until_utc: datetime
    payload: GenOfficeRuntimeAuthorizationPayload
    signature_message_sha256: str
    signature_message_size_bytes: int
    required_signer_roles: tuple[SignerRole, ...]
    signing_assignments: tuple[GenOfficeRuntimeSigningAssignment, ...]
    authorization_effective: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice runtime signing request time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_assignments(self) -> GenOfficeRuntimeSigningRequest:
        if self.required_signer_roles != GENOFFICE_RUNTIME_ROLES:
            raise ValueError("GenOffice runtime signing request roles are not exact")
        if tuple(item.signer_role for item in self.signing_assignments) != GENOFFICE_RUNTIME_ROLES:
            raise ValueError("GenOffice runtime signing assignments are not in canonical order")
        if len({item.signer_id for item in self.signing_assignments}) != 2:
            raise ValueError("GenOffice runtime signing request violates two-person separation")
        if self.prepared_at_utc != self.payload.issued_at_utc or self.valid_until_utc != self.payload.valid_until_utc:
            raise ValueError("GenOffice runtime signing request validity drifted from its payload")
        if self.signature_message_size_bytes <= 0:
            raise ValueError("GenOffice runtime signature message is empty")
        _require_sha256(self.signature_message_sha256, field="runtime signature message hash")
        _require_sha256(self.request_hash, field="runtime signing request hash")
        return self


class GenOfficeRuntimeSignatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_signature_response.v1"] = "genoffice_runtime_signature_response.v1"
    request_hash: str
    signature_message_sha256: str
    signer_id: str
    signer_role: SignerRole
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @model_validator(mode="after")
    def require_bound_response(self) -> GenOfficeRuntimeSignatureResponse:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice runtime signature response identity is empty")
        _require_sha256(self.request_hash, field="runtime signing request hash")
        _require_sha256(self.signature_message_sha256, field="runtime signature message hash")
        _decode_canonical_base64(
            self.signature_base64,
            field="runtime detached signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        return self


class GenOfficeRuntimeDetachedApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signer_id: str
    signer_role: SignerRole
    key_id: str
    signature_base64: str


class GenOfficeRuntimeAuthorizationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_authorization_envelope.v1"] = (
        "genoffice_runtime_authorization_envelope.v1"
    )
    payload: GenOfficeRuntimeAuthorizationPayload
    approvals: tuple[GenOfficeRuntimeDetachedApproval, ...]
    record_hash: str

    @model_validator(mode="after")
    def require_two_approvals(self) -> GenOfficeRuntimeAuthorizationEnvelope:
        if tuple(item.signer_role for item in self.approvals) != GENOFFICE_RUNTIME_ROLES:
            raise ValueError("GenOffice runtime authorization approvals are not exact")
        if len({item.signer_id for item in self.approvals}) != 2 or len({item.key_id for item in self.approvals}) != 2:
            raise ValueError("GenOffice runtime authorization violates two-person separation")
        _require_sha256(self.record_hash, field="runtime authorization record hash")
        return self


class GenOfficeRuntimeAuthorizationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_runtime_authorization_report.v1"] = "genoffice_runtime_authorization_report.v1"
    authorization_id: str
    verified_at_utc: datetime
    valid_until_utc: datetime
    signer_policy_hash: str
    authorization_record_hash: str
    worker_admission_report_hash: str
    worker_image_config_digest: str
    corpus_manifest_hash: str
    sandbox_profile_hash: str
    two_person_control_verified: Literal[True] = True
    detached_signatures_verified: Literal[True] = True
    signed_worker_binding_verified: Literal[True] = True
    synthetic_corpus_verified: Literal[True] = True
    no_egress_profile_verified: Literal[True] = True
    synthetic_proof_execution_allowed: Literal[True] = True
    general_worker_execution_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    source_import_allowed: Literal[False] = False
    persistent_document_write_allowed: Literal[False] = False
    external_network_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    report_hash: str

    @field_validator("verified_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice runtime authorization report time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_narrow_report(self) -> GenOfficeRuntimeAuthorizationReport:
        if self.verified_at_utc > self.valid_until_utc:
            raise ValueError("GenOffice runtime authorization report is expired")
        for field, value in (
            ("runtime signer policy hash", self.signer_policy_hash),
            ("runtime authorization record hash", self.authorization_record_hash),
            ("worker admission report hash", self.worker_admission_report_hash),
            ("worker image config digest", self.worker_image_config_digest),
            ("synthetic corpus manifest hash", self.corpus_manifest_hash),
            ("runtime sandbox profile hash", self.sandbox_profile_hash),
            ("runtime authorization report hash", self.report_hash),
        ):
            _require_sha256(value, field=field)
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} is not a SHA-256 hash")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except ValueError as exc:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} is not a SHA-256 hash") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _json_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_limited(path: Path) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice runtime input cannot be read: {path.name}") from exc
    if len(content) > MAX_EVIDENCE_BYTES:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice runtime input exceeds its size limit: {path.name}")
    return content


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice runtime output already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except (FileExistsError, OSError) as exc:
        raise GenOfficeRuntimeProofAuthorizationError(
            f"GenOffice runtime output cannot be persisted: {path.name}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()


def _decode_canonical_base64(value: str, *, field: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} has an invalid size or encoding")
    return decoded


def _zip_bytes(parts: Mapping[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, parts[name])
    return output.getvalue()


def _document_parts(body: str, *, relationships: str | None = None, macro: bool = False) -> dict[str, bytes]:
    content_type = (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
        if macro
        else ("application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
    )
    overrides = (
        f'<Override PartName="/word/document.xml" ContentType="{content_type}"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    )
    if macro:
        overrides += '<Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/>'
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{overrides}</Types>"
        ).encode(),
        "_rels/.rels": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" '
            b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            b'Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<w:body>{body}<w:sectPr/></w:body></w:document>"
        ).encode(),
        "word/styles.xml": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            b'<w:name w:val="Normal"/></w:style></w:styles>'
        ),
    }
    if relationships is not None:
        parts["word/_rels/document.xml.rels"] = relationships.encode()
    if macro:
        parts["word/vbaProject.bin"] = b"COLLABIO-SYNTHETIC-NONEXECUTABLE-VBA-FIXTURE\x00"
    return parts


def _patch_declared_uncompressed_sizes(content: bytes, declared_size: int) -> bytes:
    patched = bytearray(content)
    index = 0
    count = 0
    while True:
        index = patched.find(b"PK\x01\x02", index)
        if index < 0:
            break
        struct.pack_into("<I", patched, index + 24, declared_size)
        count += 1
        index += 46
    if count == 0:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice ZIP-bomb fixture has no central directory")
    return bytes(patched)


def build_genoffice_synthetic_corpus() -> tuple[dict[str, bytes], GenOfficeSyntheticCorpusManifest]:
    normal_body = (
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Collabio synthetic bold</w:t></w:r>"
        '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> and italic</w:t></w:r></w:p>'
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    deep_body = (
        "<w:p>" + "<w:smartTag>" * 3000 + "<w:r><w:t>deep synthetic</w:t></w:r>" + "</w:smartTag>" * 3000 + "</w:p>"
        "<w:p><w:r><w:t>safe tail</w:t></w:r></w:p>"
    )
    remote_body = '<w:p><w:hyperlink r:id="rIdRemote"><w:r><w:t>offline target</w:t></w:r></w:hyperlink></w:p>'
    remote_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdRemote" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.com/collabio-synthetic-proof" TargetMode="External"/></Relationships>'
    )
    plain = _zip_bytes(_document_parts("<w:p><w:r><w:t>zip limit</w:t></w:r></w:p>"))
    files = {
        "minimal-formatting.docx": _zip_bytes(_document_parts(normal_body)),
        "deep-xml-passthrough.docx": _zip_bytes(_document_parts(deep_body)),
        "remote-relationship-no-egress.docx": _zip_bytes(
            _document_parts(remote_body, relationships=remote_relationships)
        ),
        "declared-zip-bomb.docx": _patch_declared_uncompressed_sizes(plain, 600 * 1024 * 1024),
        "active-content-preflight-rejection.docm": _zip_bytes(
            _document_parts("<w:p><w:r><w:t>macro marker</w:t></w:r></w:p>", macro=True)
        ),
    }
    definitions: tuple[tuple[str, str, CorpusCategory, ExpectedBoundary, bool], ...] = (
        ("minimal-formatting", "minimal-formatting.docx", "fidelity", "parse_save_roundtrip", True),
        (
            "deep-xml-passthrough",
            "deep-xml-passthrough.docx",
            "parser_resilience",
            "byte_preserving_passthrough",
            True,
        ),
        (
            "remote-relationship-no-egress",
            "remote-relationship-no-egress.docx",
            "no_egress",
            "no_external_fetch",
            True,
        ),
        ("declared-zip-bomb", "declared-zip-bomb.docx", "resource_exhaustion", "engine_rejection", True),
        (
            "active-content-preflight-rejection",
            "active-content-preflight-rejection.docm",
            "active_content",
            "preflight_rejection",
            False,
        ),
    )
    artifacts = tuple(
        GenOfficeSyntheticCorpusArtifact(
            fixture_id=fixture_id,
            filename=filename,
            category=category,
            expected_boundary=boundary,
            engine_invocation_allowed=engine_allowed,
            content_sha256=_sha256_bytes(files[filename]),
            size_bytes=len(files[filename]),
        )
        for fixture_id, filename, category, boundary, engine_allowed in definitions
    )
    draft = GenOfficeSyntheticCorpusManifest(
        artifacts=artifacts,
        total_size_bytes=sum(len(content) for content in files.values()),
        manifest_hash=ZERO_HASH,
    )
    return files, draft.model_copy(update={"manifest_hash": build_genoffice_synthetic_corpus_manifest_hash(draft)})


def build_genoffice_synthetic_corpus_manifest_hash(manifest: GenOfficeSyntheticCorpusManifest) -> str:
    return stable_hash(canonical_json(manifest.model_dump(mode="json", exclude={"manifest_hash"})))


def verify_genoffice_synthetic_corpus(*, manifest: GenOfficeSyntheticCorpusManifest, corpus_directory: Path) -> None:
    expected_files, expected_manifest = build_genoffice_synthetic_corpus()
    manifest_hash_valid = build_genoffice_synthetic_corpus_manifest_hash(manifest) == manifest.manifest_hash
    if manifest != expected_manifest or not manifest_hash_valid:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus manifest is not canonical")
    actual_names = tuple(sorted(path.name for path in corpus_directory.iterdir() if path.is_file()))
    expected_names = tuple(sorted((*expected_files, "genoffice-synthetic-corpus-manifest.json")))
    if actual_names != expected_names:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus directory inventory drifted")
    for name, expected_content in expected_files.items():
        if _read_limited(corpus_directory / name) != expected_content:
            raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice synthetic fixture drifted: {name}")


def materialize_genoffice_synthetic_corpus(output_directory: Path) -> GenOfficeSyntheticCorpusManifest:
    files, manifest = build_genoffice_synthetic_corpus()
    output_directory.mkdir(parents=True, exist_ok=True)
    if any(output_directory.iterdir()):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus output directory is not empty")
    for name, content in files.items():
        _write_new_private(output_directory / name, content)
    _write_new_private(output_directory / "genoffice-synthetic-corpus-manifest.json", _json_bytes(manifest))
    verify_genoffice_synthetic_corpus(manifest=manifest, corpus_directory=output_directory)
    return manifest


def build_genoffice_runtime_sandbox_profile() -> GenOfficeRuntimeSandboxProfile:
    draft = GenOfficeRuntimeSandboxProfile(profile_hash=ZERO_HASH)
    return draft.model_copy(update={"profile_hash": build_genoffice_runtime_sandbox_profile_hash(draft)})


def build_genoffice_runtime_sandbox_profile_hash(profile: GenOfficeRuntimeSandboxProfile) -> str:
    return stable_hash(canonical_json(profile.model_dump(mode="json", exclude={"profile_hash"})))


def _load_model(path: Path, model: type[BaseModel], *, label: str) -> BaseModel:
    try:
        return model.model_validate_json(_read_limited(path))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {label} is invalid") from exc


def load_genoffice_synthetic_corpus_manifest(path: Path) -> GenOfficeSyntheticCorpusManifest:
    manifest = _load_model(path, GenOfficeSyntheticCorpusManifest, label="synthetic corpus manifest")
    assert isinstance(manifest, GenOfficeSyntheticCorpusManifest)
    if build_genoffice_synthetic_corpus_manifest_hash(manifest) != manifest.manifest_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus manifest hash is invalid")
    return manifest


def load_genoffice_runtime_sandbox_profile(path: Path) -> GenOfficeRuntimeSandboxProfile:
    profile = _load_model(path, GenOfficeRuntimeSandboxProfile, label="runtime sandbox profile")
    assert isinstance(profile, GenOfficeRuntimeSandboxProfile)
    if profile != build_genoffice_runtime_sandbox_profile():
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime sandbox profile is not canonical")
    return profile


def _verify_docker_inspect(inspect: Any, profile: GenOfficeRuntimeSandboxProfile) -> None:
    if not isinstance(inspect, list) or len(inspect) != 1 or not isinstance(inspect[0], dict):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox Docker inspect evidence is invalid")
    config = inspect[0].get("Config", {})
    host = inspect[0].get("HostConfig", {})
    expected = (
        (config.get("User"), profile.user),
        (host.get("Runtime"), profile.runtime_class),
        (host.get("NetworkMode"), profile.network_mode),
        (host.get("ReadonlyRootfs"), profile.read_only_root_filesystem),
        (host.get("PidsLimit"), profile.pids_limit),
        (host.get("NanoCpus"), profile.nano_cpus),
        (host.get("Memory"), profile.memory_bytes),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox Docker host configuration drifted")
    if set(host.get("CapDrop") or ()) != {"ALL"}:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox capabilities are not dropped")
    if "no-new-privileges:true" not in set(host.get("SecurityOpt") or ()):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox no-new-privileges is absent")
    tmpfs = host.get("Tmpfs") or {}
    if tmpfs.get("/scratch") != profile.scratch_tmpfs.split(":", 1)[1]:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox scratch tmpfs drifted")
    mounts = inspect[0].get("Mounts") or []
    corpus_mount = tuple(item for item in mounts if item.get("Destination") == "/corpus")
    if len(corpus_mount) != 1 or corpus_mount[0].get("RW") is not False:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox corpus mount is not read-only")


def run_genoffice_runtime_sandbox_probe(
    *,
    profile: GenOfficeRuntimeSandboxProfile,
    manifest: GenOfficeSyntheticCorpusManifest,
    corpus_directory: Path,
    docker_inspect_path: Path,
    observed_at_utc: datetime,
) -> GenOfficeRuntimeSandboxProbeReport:
    if profile != build_genoffice_runtime_sandbox_profile():
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime sandbox profile is not canonical")
    verify_genoffice_synthetic_corpus(manifest=manifest, corpus_directory=corpus_directory)
    inspect_bytes = _read_limited(docker_inspect_path)
    try:
        inspect = json.loads(inspect_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox Docker inspect evidence is invalid") from exc
    _verify_docker_inspect(inspect, profile)

    try:
        Path("/opt/collabio-sandbox-root-write").write_bytes(b"blocked")
    except OSError as exc:
        if exc.errno not in {errno.EROFS, errno.EACCES, errno.EPERM}:
            raise
    else:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox root filesystem is writable")
    fixture_path = corpus_directory / manifest.artifacts[0].filename
    try:
        fixture_path.write_bytes(b"blocked")
    except OSError as exc:
        if exc.errno not in {errno.EROFS, errno.EACCES, errno.EPERM}:
            raise
    else:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox corpus mount is writable")
    scratch = Path("/scratch/probe.tmp")
    scratch.write_bytes(b"synthetic-probe")
    scratch.unlink()
    if any(Path("/scratch").iterdir()):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox scratch cleanup is incomplete")

    outbound_blocked = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("1.1.1.1", 53))
        except OSError as exc:
            outbound_blocked = exc.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}
    if not outbound_blocked:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox outbound socket is not fail-closed")
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        pass
    else:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice sandbox DNS resolution is not blocked")

    draft = GenOfficeRuntimeSandboxProbeReport(
        observed_at_utc=observed_at_utc,
        sandbox_profile_hash=profile.profile_hash,
        corpus_manifest_hash=manifest.manifest_hash,
        docker_inspect_sha256=_sha256_bytes(inspect_bytes),
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_runtime_sandbox_probe_report_hash(draft)})


def build_genoffice_runtime_sandbox_probe_report_hash(report: GenOfficeRuntimeSandboxProbeReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_genoffice_runtime_signer_policy(
    *,
    policy_id: str,
    effective_at_utc: datetime,
    product_owner_signer_id: str,
    product_owner_key_id: str,
    product_owner_public_key: bytes,
    security_compliance_owner_signer_id: str,
    security_compliance_owner_key_id: str,
    security_compliance_owner_public_key: bytes,
) -> GenOfficeRuntimeSignerPolicy:
    signers = (
        GenOfficeRuntimeSigner(
            signer_id=product_owner_signer_id,
            signer_role="product_owner",
            key_id=product_owner_key_id,
            ed25519_public_key_base64=base64.b64encode(product_owner_public_key).decode("ascii"),
        ),
        GenOfficeRuntimeSigner(
            signer_id=security_compliance_owner_signer_id,
            signer_role="security_compliance_owner",
            key_id=security_compliance_owner_key_id,
            ed25519_public_key_base64=base64.b64encode(security_compliance_owner_public_key).decode("ascii"),
        ),
    )
    draft = GenOfficeRuntimeSignerPolicy(
        policy_id=policy_id,
        effective_at_utc=effective_at_utc,
        signers=signers,
        policy_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"policy_hash": build_genoffice_runtime_signer_policy_hash(draft)})


def build_genoffice_runtime_signer_policy_hash(policy: GenOfficeRuntimeSignerPolicy) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json", exclude={"policy_hash"})))


def build_genoffice_runtime_payload_hash(payload: GenOfficeRuntimeAuthorizationPayload) -> str:
    return stable_hash(canonical_json(payload.model_dump(mode="json", exclude={"payload_hash"})))


def build_genoffice_runtime_signature_message(payload: GenOfficeRuntimeAuthorizationPayload) -> bytes:
    return canonical_json(payload.model_dump(mode="json")).encode("utf-8")


def build_genoffice_runtime_signing_request_hash(request: GenOfficeRuntimeSigningRequest) -> str:
    return stable_hash(canonical_json(request.model_dump(mode="json", exclude={"request_hash"})))


def build_genoffice_runtime_authorization_record_hash(envelope: GenOfficeRuntimeAuthorizationEnvelope) -> str:
    return stable_hash(canonical_json(envelope.model_dump(mode="json", exclude={"record_hash"})))


def build_genoffice_runtime_authorization_report_hash(report: GenOfficeRuntimeAuthorizationReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def _verify_worker_admission(report: GenOfficeWorkerImageAdmissionReport, at_utc: datetime) -> None:
    if build_genoffice_worker_admission_report_hash(report) != report.report_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice worker admission report hash is invalid")
    if not report.issued_at_utc <= at_utc <= report.valid_until_utc:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice worker admission is not currently valid")
    forbidden = (
        report.two_person_runtime_authorization_verified,
        report.worker_execution_allowed,
        report.source_import_allowed,
        report.tenant_content_allowed,
        report.hosted_service_allowed,
        report.on_prem_distribution_allowed,
        report.production_use_allowed,
    )
    if any(forbidden):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice worker admission already opened a runtime boundary")


def build_genoffice_runtime_signing_request(
    *,
    worker_admission: GenOfficeWorkerImageAdmissionReport,
    manifest: GenOfficeSyntheticCorpusManifest,
    sandbox_profile: GenOfficeRuntimeSandboxProfile,
    signer_policy: GenOfficeRuntimeSignerPolicy,
    authorization_id: str,
    issued_at_utc: datetime,
    valid_until_utc: datetime,
    risk_acceptance_ref: str,
    change_control_ref: str,
) -> tuple[GenOfficeRuntimeSigningRequest, bytes]:
    issued_at = issued_at_utc.astimezone(UTC)
    _verify_worker_admission(worker_admission, issued_at)
    if build_genoffice_synthetic_corpus_manifest_hash(manifest) != manifest.manifest_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus manifest hash is invalid")
    if sandbox_profile != build_genoffice_runtime_sandbox_profile():
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime sandbox profile is not canonical")
    if build_genoffice_runtime_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy hash is invalid")
    if signer_policy.effective_at_utc > issued_at:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy is not yet effective")
    if valid_until_utc.astimezone(UTC) > worker_admission.valid_until_utc:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization exceeds worker admission")
    payload_draft = GenOfficeRuntimeAuthorizationPayload(
        authorization_id=authorization_id,
        issued_at_utc=issued_at,
        valid_until_utc=valid_until_utc,
        risk_acceptance_ref=risk_acceptance_ref,
        change_control_ref=change_control_ref,
        signer_policy_hash=signer_policy.policy_hash,
        worker_admission_report_hash=worker_admission.report_hash,
        worker_image_config_digest=worker_admission.image_config_digest,
        worker_image_archive_sha256=worker_admission.image_archive_sha256,
        worker_sbom_sha256=worker_admission.worker_sbom_sha256,
        worker_vulnerability_report_hash=worker_admission.vulnerability_report_hash,
        corpus_manifest_hash=manifest.manifest_hash,
        sandbox_profile_hash=sandbox_profile.profile_hash,
        engine_fixture_ids=GENOFFICE_RUNTIME_ENGINE_FIXTURE_IDS,
        preflight_only_fixture_ids=GENOFFICE_RUNTIME_PREFLIGHT_ONLY_FIXTURE_IDS,
        payload_hash=ZERO_HASH,
    )
    payload = payload_draft.model_copy(update={"payload_hash": build_genoffice_runtime_payload_hash(payload_draft)})
    message = build_genoffice_runtime_signature_message(payload)
    active = tuple(item for item in signer_policy.signers if item.active)
    request_draft = GenOfficeRuntimeSigningRequest(
        prepared_at_utc=issued_at,
        valid_until_utc=valid_until_utc,
        payload=payload,
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        required_signer_roles=GENOFFICE_RUNTIME_ROLES,
        signing_assignments=tuple(
            GenOfficeRuntimeSigningAssignment(
                signer_id=item.signer_id,
                signer_role=item.signer_role,
                key_id=item.key_id,
            )
            for item in active
        ),
        request_hash=ZERO_HASH,
    )
    request = request_draft.model_copy(
        update={"request_hash": build_genoffice_runtime_signing_request_hash(request_draft)}
    )
    return request, message


def verify_genoffice_runtime_signing_request(request: GenOfficeRuntimeSigningRequest) -> bytes:
    if build_genoffice_runtime_payload_hash(request.payload) != request.payload.payload_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization payload hash is invalid")
    if build_genoffice_runtime_signing_request_hash(request) != request.request_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signing request hash is invalid")
    message = build_genoffice_runtime_signature_message(request.payload)
    message_hash_valid = _sha256_bytes(message) == request.signature_message_sha256
    if not message_hash_valid or len(message) != request.signature_message_size_bytes:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signature message binding is invalid")
    return message


def assemble_genoffice_runtime_authorization_envelope(
    *,
    request: GenOfficeRuntimeSigningRequest,
    signer_policy: GenOfficeRuntimeSignerPolicy,
    signature_responses: tuple[GenOfficeRuntimeSignatureResponse, ...],
    assembled_at_utc: datetime,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeRuntimeAuthorizationEnvelope:
    message = verify_genoffice_runtime_signing_request(request)
    assembled_at = assembled_at_utc.astimezone(UTC)
    if not request.prepared_at_utc <= assembled_at <= request.valid_until_utc:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signing request is not currently valid")
    if build_genoffice_runtime_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy hash is invalid")
    if request.payload.signer_policy_hash != signer_policy.policy_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy drifted")
    if tuple(item.signer_role for item in signature_responses) != GENOFFICE_RUNTIME_ROLES:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signatures are incomplete or unordered")
    assignments = {item.signer_role: item for item in request.signing_assignments}
    signers = {item.signer_role: item for item in signer_policy.signers if item.active}
    approvals: list[GenOfficeRuntimeDetachedApproval] = []
    for response in signature_responses:
        assignment = assignments[response.signer_role]
        signer = signers[response.signer_role]
        if (
            response.request_hash != request.request_hash
            or response.signature_message_sha256 != request.signature_message_sha256
            or (response.signer_id, response.key_id) != (assignment.signer_id, assignment.key_id)
            or (response.signer_id, response.key_id) != (signer.signer_id, signer.key_id)
        ):
            raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signature response binding is invalid")
        signature = _decode_canonical_base64(
            response.signature_base64,
            field="runtime detached signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        public_key = _decode_canonical_base64(
            signer.ed25519_public_key_base64,
            field="runtime signer public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        )
        if not signature_verifier.verify_ed25519(public_key=public_key, signature=signature, message=message):
            raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime detached signature is invalid")
        approvals.append(
            GenOfficeRuntimeDetachedApproval(
                signer_id=response.signer_id,
                signer_role=response.signer_role,
                key_id=response.key_id,
                signature_base64=response.signature_base64,
            )
        )
    draft = GenOfficeRuntimeAuthorizationEnvelope(
        payload=request.payload,
        approvals=tuple(approvals),
        record_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"record_hash": build_genoffice_runtime_authorization_record_hash(draft)})


def verify_genoffice_runtime_authorization(
    *,
    worker_admission: GenOfficeWorkerImageAdmissionReport,
    manifest: GenOfficeSyntheticCorpusManifest,
    sandbox_profile: GenOfficeRuntimeSandboxProfile,
    signer_policy: GenOfficeRuntimeSignerPolicy,
    envelope: GenOfficeRuntimeAuthorizationEnvelope,
    verified_at_utc: datetime,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeRuntimeAuthorizationReport:
    verified_at = verified_at_utc.astimezone(UTC)
    _verify_worker_admission(worker_admission, verified_at)
    if not envelope.payload.issued_at_utc <= verified_at <= envelope.payload.valid_until_utc:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization is not currently valid")
    if build_genoffice_runtime_payload_hash(envelope.payload) != envelope.payload.payload_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization payload hash is invalid")
    if build_genoffice_runtime_authorization_record_hash(envelope) != envelope.record_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization record hash is invalid")
    if build_genoffice_runtime_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy hash is invalid")
    if manifest.manifest_hash != build_genoffice_synthetic_corpus_manifest_hash(manifest):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice synthetic corpus manifest hash is invalid")
    if sandbox_profile != build_genoffice_runtime_sandbox_profile():
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime sandbox profile is not canonical")
    payload = envelope.payload
    expected = (
        (payload.signer_policy_hash, signer_policy.policy_hash),
        (payload.worker_admission_report_hash, worker_admission.report_hash),
        (payload.worker_image_config_digest, worker_admission.image_config_digest),
        (payload.worker_image_archive_sha256, worker_admission.image_archive_sha256),
        (payload.worker_sbom_sha256, worker_admission.worker_sbom_sha256),
        (payload.worker_vulnerability_report_hash, worker_admission.vulnerability_report_hash),
        (payload.corpus_manifest_hash, manifest.manifest_hash),
        (payload.sandbox_profile_hash, sandbox_profile.profile_hash),
    )
    if any(actual != required for actual, required in expected):
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization evidence chain drifted")
    if tuple(item.signer_role for item in envelope.approvals) != GENOFFICE_RUNTIME_ROLES:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization lacks both approval roles")
    signers = {item.signer_role: item for item in signer_policy.signers if item.active}
    message = build_genoffice_runtime_signature_message(payload)
    for approval in envelope.approvals:
        signer = signers.get(approval.signer_role)
        if signer is None or (approval.signer_id, approval.key_id) != (signer.signer_id, signer.key_id):
            raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime approval signer is unauthorized")
        if not signature_verifier.verify_ed25519(
            public_key=_decode_canonical_base64(
                signer.ed25519_public_key_base64,
                field="runtime signer public key",
                expected_size=PUBLIC_KEY_SIZE_BYTES,
            ),
            signature=_decode_canonical_base64(
                approval.signature_base64,
                field="runtime detached signature",
                expected_size=SIGNATURE_SIZE_BYTES,
            ),
            message=message,
        ):
            raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime detached signature is invalid")
    draft = GenOfficeRuntimeAuthorizationReport(
        authorization_id=payload.authorization_id,
        verified_at_utc=verified_at,
        valid_until_utc=payload.valid_until_utc,
        signer_policy_hash=signer_policy.policy_hash,
        authorization_record_hash=envelope.record_hash,
        worker_admission_report_hash=worker_admission.report_hash,
        worker_image_config_digest=worker_admission.image_config_digest,
        corpus_manifest_hash=manifest.manifest_hash,
        sandbox_profile_hash=sandbox_profile.profile_hash,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_runtime_authorization_report_hash(draft)})


def load_genoffice_runtime_signer_policy(path: Path) -> GenOfficeRuntimeSignerPolicy:
    policy = _load_model(path, GenOfficeRuntimeSignerPolicy, label="runtime signer policy")
    assert isinstance(policy, GenOfficeRuntimeSignerPolicy)
    if build_genoffice_runtime_signer_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime signer policy hash is invalid")
    return policy


def load_genoffice_runtime_signing_request(path: Path) -> GenOfficeRuntimeSigningRequest:
    request = _load_model(path, GenOfficeRuntimeSigningRequest, label="runtime signing request")
    assert isinstance(request, GenOfficeRuntimeSigningRequest)
    verify_genoffice_runtime_signing_request(request)
    return request


def load_genoffice_runtime_signature_response(path: Path) -> GenOfficeRuntimeSignatureResponse:
    response = _load_model(path, GenOfficeRuntimeSignatureResponse, label="runtime signature response")
    assert isinstance(response, GenOfficeRuntimeSignatureResponse)
    return response


def load_genoffice_runtime_authorization_envelope(path: Path) -> GenOfficeRuntimeAuthorizationEnvelope:
    envelope = _load_model(path, GenOfficeRuntimeAuthorizationEnvelope, label="runtime authorization envelope")
    assert isinstance(envelope, GenOfficeRuntimeAuthorizationEnvelope)
    if build_genoffice_runtime_authorization_record_hash(envelope) != envelope.record_hash:
        raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime authorization record hash is invalid")
    return envelope


def _parse_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice {field} lacks a timezone")
    return parsed.astimezone(UTC)


def _required_environment(env: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    values = {name: env.get(name, "").strip() for name in names}
    missing = tuple(name for name, value in values.items() if not value)
    if missing:
        raise GenOfficeRuntimeProofAuthorizationError(f"GenOffice runtime values are missing: {missing}")
    return values


def run_genoffice_runtime_request_from_environment(env: Mapping[str, str]) -> GenOfficeRuntimeSigningRequest:
    values = _required_environment(
        env,
        (
            "SUITE_GENOFFICE_WORKER_ADMISSION_REPORT_PATH",
            "SUITE_GENOFFICE_RUNTIME_CORPUS_MANIFEST_PATH",
            "SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH",
            "SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ID",
            "SUITE_GENOFFICE_RUNTIME_ISSUED_AT_UTC",
            "SUITE_GENOFFICE_RUNTIME_VALID_UNTIL_UTC",
            "SUITE_GENOFFICE_RUNTIME_RISK_ACCEPTANCE_REF",
            "SUITE_GENOFFICE_RUNTIME_CHANGE_CONTROL_REF",
            "SUITE_GENOFFICE_RUNTIME_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_RUNTIME_SIGNATURE_MESSAGE_PATH",
        ),
    )
    request, message = build_genoffice_runtime_signing_request(
        worker_admission=load_genoffice_worker_image_admission_report(
            Path(values["SUITE_GENOFFICE_WORKER_ADMISSION_REPORT_PATH"])
        ),
        manifest=load_genoffice_synthetic_corpus_manifest(Path(values["SUITE_GENOFFICE_RUNTIME_CORPUS_MANIFEST_PATH"])),
        sandbox_profile=load_genoffice_runtime_sandbox_profile(
            Path(values["SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH"])
        ),
        signer_policy=load_genoffice_runtime_signer_policy(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH"])),
        authorization_id=values["SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ID"],
        issued_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_RUNTIME_ISSUED_AT_UTC"], field="runtime authorization issue time"
        ),
        valid_until_utc=_parse_datetime(
            values["SUITE_GENOFFICE_RUNTIME_VALID_UNTIL_UTC"], field="runtime authorization expiry time"
        ),
        risk_acceptance_ref=values["SUITE_GENOFFICE_RUNTIME_RISK_ACCEPTANCE_REF"],
        change_control_ref=values["SUITE_GENOFFICE_RUNTIME_CHANGE_CONTROL_REF"],
    )
    _write_new_private(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNING_REQUEST_PATH"]), _json_bytes(request))
    _write_new_private(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNATURE_MESSAGE_PATH"]), message)
    return request


def run_genoffice_runtime_assembly_from_environment(env: Mapping[str, str]) -> GenOfficeRuntimeAuthorizationEnvelope:
    values = _required_environment(
        env,
        (
            "SUITE_GENOFFICE_RUNTIME_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_RESPONSE_PATH",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_RESPONSE_PATH",
            "SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ENVELOPE_PATH",
        ),
    )
    envelope = assemble_genoffice_runtime_authorization_envelope(
        request=load_genoffice_runtime_signing_request(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNING_REQUEST_PATH"])),
        signer_policy=load_genoffice_runtime_signer_policy(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH"])),
        signature_responses=(
            load_genoffice_runtime_signature_response(
                Path(values["SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_RESPONSE_PATH"])
            ),
            load_genoffice_runtime_signature_response(
                Path(values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_RESPONSE_PATH"])
            ),
        ),
        assembled_at_utc=datetime.now(UTC),
    )
    _write_new_private(Path(values["SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ENVELOPE_PATH"]), _json_bytes(envelope))
    return envelope


def run_genoffice_runtime_verification_from_environment(env: Mapping[str, str]) -> GenOfficeRuntimeAuthorizationReport:
    values = _required_environment(
        env,
        (
            "SUITE_GENOFFICE_WORKER_ADMISSION_REPORT_PATH",
            "SUITE_GENOFFICE_RUNTIME_CORPUS_MANIFEST_PATH",
            "SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH",
            "SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ENVELOPE_PATH",
            "SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_REPORT_PATH",
        ),
    )
    report = verify_genoffice_runtime_authorization(
        worker_admission=load_genoffice_worker_image_admission_report(
            Path(values["SUITE_GENOFFICE_WORKER_ADMISSION_REPORT_PATH"])
        ),
        manifest=load_genoffice_synthetic_corpus_manifest(Path(values["SUITE_GENOFFICE_RUNTIME_CORPUS_MANIFEST_PATH"])),
        sandbox_profile=load_genoffice_runtime_sandbox_profile(
            Path(values["SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH"])
        ),
        signer_policy=load_genoffice_runtime_signer_policy(Path(values["SUITE_GENOFFICE_RUNTIME_SIGNER_POLICY_PATH"])),
        envelope=load_genoffice_runtime_authorization_envelope(
            Path(values["SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_ENVELOPE_PATH"])
        ),
        verified_at_utc=datetime.now(UTC),
    )
    _write_new_private(Path(values["SUITE_GENOFFICE_RUNTIME_AUTHORIZATION_REPORT_PATH"]), _json_bytes(report))
    return report


def persist_genoffice_runtime_schemas(output_directory: Path) -> dict[str, str]:
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-synthetic-corpus-manifest.schema.json", GenOfficeSyntheticCorpusManifest),
        ("genoffice-runtime-sandbox-profile.schema.json", GenOfficeRuntimeSandboxProfile),
        ("genoffice-runtime-sandbox-probe-report.schema.json", GenOfficeRuntimeSandboxProbeReport),
        ("genoffice-runtime-signer-policy.schema.json", GenOfficeRuntimeSignerPolicy),
        ("genoffice-runtime-signing-request.schema.json", GenOfficeRuntimeSigningRequest),
        ("genoffice-runtime-signature-response.schema.json", GenOfficeRuntimeSignatureResponse),
        ("genoffice-runtime-authorization-envelope.schema.json", GenOfficeRuntimeAuthorizationEnvelope),
        ("genoffice-runtime-authorization-report.schema.json", GenOfficeRuntimeAuthorizationReport),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(output_directory / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_RUNTIME_PROOF_MODE", "").strip()
    try:
        if mode == "schema":
            result: BaseModel | Mapping[str, Any] = persist_genoffice_runtime_schemas(
                Path(os.environ["SUITE_GENOFFICE_RUNTIME_SCHEMA_OUTPUT_DIR"])
            )
        elif mode == "corpus":
            result = materialize_genoffice_synthetic_corpus(
                Path(os.environ["SUITE_GENOFFICE_RUNTIME_CORPUS_OUTPUT_DIR"])
            )
        elif mode == "sandbox-profile":
            result = build_genoffice_runtime_sandbox_profile()
            _write_new_private(
                Path(os.environ["SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH"]),
                _json_bytes(result),
            )
        elif mode == "sandbox-probe":
            result = run_genoffice_runtime_sandbox_probe(
                profile=load_genoffice_runtime_sandbox_profile(
                    Path(os.environ["SUITE_GENOFFICE_RUNTIME_SANDBOX_PROFILE_PATH"])
                ),
                manifest=load_genoffice_synthetic_corpus_manifest(
                    Path(os.environ["SUITE_GENOFFICE_RUNTIME_CORPUS_MANIFEST_PATH"])
                ),
                corpus_directory=Path(os.environ["SUITE_GENOFFICE_RUNTIME_CORPUS_DIR"]),
                docker_inspect_path=Path(os.environ["SUITE_GENOFFICE_RUNTIME_DOCKER_INSPECT_PATH"]),
                observed_at_utc=datetime.now(UTC),
            )
            report_path = os.environ.get("SUITE_GENOFFICE_RUNTIME_SANDBOX_PROBE_REPORT_PATH", "").strip()
            if report_path:
                _write_new_private(Path(report_path), _json_bytes(result))
        elif mode == "request":
            result = run_genoffice_runtime_request_from_environment(os.environ)
        elif mode == "assemble":
            result = run_genoffice_runtime_assembly_from_environment(os.environ)
        elif mode == "verify":
            result = run_genoffice_runtime_verification_from_environment(os.environ)
        else:
            raise GenOfficeRuntimeProofAuthorizationError("GenOffice runtime proof mode is invalid")
        print(json.dumps(result.model_dump(mode="json") if isinstance(result, BaseModel) else result, sort_keys=True))
    except (GenOfficeRuntimeProofAuthorizationError, KeyError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_runtime_proof_error.v1"}, sort_keys=True))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
