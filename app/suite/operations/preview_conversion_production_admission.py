from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.derived_preview_recovery_drill import (
    DerivedPreviewRecoveryDrillReport,
    build_derived_preview_recovery_drill_report_hash,
)
from suite.platform.source_object_preview_conversion import (
    PreviewConversionBlocked,
    PreviewConversionCommand,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionGateStatus,
    build_preview_conversion_command_hash,
    build_preview_conversion_execution_gate_hash,
)
from suite.storage.source_objects import sha256_bytes

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[a-f0-9]{40}$")
DSSE_PAYLOAD_TYPE: Literal["application/vnd.in-toto+json"] = "application/vnd.in-toto+json"
IN_TOTO_STATEMENT_TYPE: Literal["https://in-toto.io/Statement/v1"] = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE: Literal["https://collabio.eu/attestation/preview-conversion-production/v1"] = (
    "https://collabio.eu/attestation/preview-conversion-production/v1"
)
SUBJECT_NAME: Literal["preview-conversion-production-evidence"] = "preview-conversion-production-evidence"
REQUIRED_SIGNER_ROLES: tuple[Literal["release", "security", "operations"], ...] = (
    "release",
    "security",
    "operations",
)
REQUIRED_VIEWER_CSP_DIRECTIVES = frozenset(
    {
        "default-src 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "script-src 'self'",
        "worker-src 'self' blob:",
        "connect-src 'self'",
        "img-src 'self' blob: data:",
        "font-src 'self'",
        "style-src 'self' 'unsafe-inline'",
    }
)
REQUIRED_IFRAME_SANDBOX_TOKENS = ("allow-same-origin", "allow-scripts")
MAX_ATTESTATION_PAYLOAD_BYTES = 64 * 1024
ZERO_HASH = "sha256:" + "0" * 64

SignerRole = Literal["release", "security", "operations"]


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, populate_by_name=True)


def _require_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("preview conversion production evidence references must use sha256")
    return value


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("preview conversion production timestamps must include a timezone")
    return value.astimezone(UTC)


def _require_https_origin(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise ValueError("preview conversion production origins must be HTTPS origins without paths")
    if parsed.params or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("preview conversion production origins must not include credentials or URL parameters")
    return normalized


class RuntimeIsolationEvidence(StrictEvidenceModel):
    sandbox_runtime_class: Literal["runsc", "kata", "firecracker"]
    host_profile_ref_hash: str
    runtime_version_ref_hash: str
    conformance_report_hash: str
    isolation_test_report_hash: str
    production_host_profile_verified: bool
    no_network_egress_verified: bool
    read_only_root_filesystem_verified: bool
    non_root_user_verified: bool
    capabilities_dropped_verified: bool
    no_new_privileges_verified: bool
    ephemeral_workspace_verified: bool
    synthetic_runtime_used: bool
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "host_profile_ref_hash",
        "runtime_version_ref_hash",
        "conformance_report_hash",
        "isolation_test_report_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)


class MalwareCdrServiceEvidence(StrictEvidenceModel):
    scanner_profile_ref: str
    scanner_service_deployment_ref_hash: str
    scanner_engine_version_ref_hash: str
    scanner_signature_set_hash: str
    scanner_evidence_hash: str
    scanner_health_report_hash: str
    eicar_detection_report_hash: str
    cdr_profile_ref: str
    cdr_service_deployment_ref_hash: str
    cdr_engine_version_ref_hash: str
    cdr_evidence_hash: str
    active_content_neutralization_report_hash: str
    real_services_invoked: bool
    tenant_routing_verified: bool
    signature_freshness_verified: bool
    quarantine_on_error_verified: bool
    cdr_fail_closed_verified: bool
    synthetic_provider_used: bool
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "scanner_service_deployment_ref_hash",
        "scanner_engine_version_ref_hash",
        "scanner_signature_set_hash",
        "scanner_evidence_hash",
        "scanner_health_report_hash",
        "eicar_detection_report_hash",
        "cdr_service_deployment_ref_hash",
        "cdr_engine_version_ref_hash",
        "cdr_evidence_hash",
        "active_content_neutralization_report_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)

    @field_validator("scanner_profile_ref", "cdr_profile_ref")
    @classmethod
    def require_namespaced_profile(cls, value: str) -> str:
        if ":" not in value or value.startswith(":") or value.endswith(":"):
            raise ValueError("malware and CDR profiles must be namespaced")
        return value


class WorkerImageSupplyChainEvidence(StrictEvidenceModel):
    worker_image_ref: str
    worker_image_digest: str
    source_repository: str
    source_revision: str
    release_workflow_identity: str
    builder_id: str
    provenance_bundle_hash: str
    sbom_bundle_hash: str
    trusted_root_hash: str
    provenance_verification_receipt_hash: str
    sbom_verification_receipt_hash: str
    vulnerability_scan_report_hash: str
    license_scan_report_hash: str
    provenance_signature_verified: bool
    provenance_subject_digest_verified: bool
    provenance_builder_identity_verified: bool
    provenance_source_repository_verified: bool
    sbom_signature_verified: bool
    sbom_subject_digest_verified: bool
    vulnerability_policy_passed: bool
    license_policy_passed: bool
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "worker_image_digest",
        "provenance_bundle_hash",
        "sbom_bundle_hash",
        "trusted_root_hash",
        "provenance_verification_receipt_hash",
        "sbom_verification_receipt_hash",
        "vulnerability_scan_report_hash",
        "license_scan_report_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)

    @field_validator("worker_image_ref")
    @classmethod
    def require_pinned_image(cls, value: str) -> str:
        normalized = value.lower()
        if not IMAGE_REF_PATTERN.fullmatch(normalized):
            raise ValueError("production preview worker image must be digest pinned")
        return normalized

    @field_validator("source_revision")
    @classmethod
    def require_source_revision(cls, value: str) -> str:
        if not SOURCE_REVISION_PATTERN.fullmatch(value):
            raise ValueError("production preview source revision must be a full Git commit hash")
        return value

    @model_validator(mode="after")
    def require_image_digest_binding(self) -> Self:
        if self.worker_image_ref.rsplit("@", maxsplit=1)[1] != self.worker_image_digest:
            raise ValueError("production preview image digest does not match its image reference")
        return self


class ViewerIsolationEvidence(StrictEvidenceModel):
    viewer_origin: str
    application_origin: str
    pdfjs_release_ref: str
    pdfjs_bundle_hash: str
    viewer_deployment_ref_hash: str
    csp_evidence_hash: str
    browser_header_test_report_hash: str
    csp_directives: tuple[str, ...] = Field(min_length=1, max_length=64)
    iframe_sandbox_tokens: tuple[str, ...] = Field(min_length=1, max_length=16)
    separate_origin_verified: bool
    https_tls_verified: bool
    viewer_session_cookie_absent: bool
    viewer_service_worker_disabled: bool
    pdfjs_external_actions_disabled: bool
    browser_smoke_passed: bool
    synthetic_viewer_used: bool
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "pdfjs_bundle_hash",
        "viewer_deployment_ref_hash",
        "csp_evidence_hash",
        "browser_header_test_report_hash",
    )(_require_sha256)
    _validate_origins = field_validator("viewer_origin", "application_origin")(_require_https_origin)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)

    @model_validator(mode="after")
    def require_different_origins(self) -> Self:
        if self.viewer_origin == self.application_origin:
            raise ValueError("PDF.js viewer and application must use separate origins")
        return self


class PreviewConversionProductionEvidenceBundle(StrictEvidenceModel):
    tenant_id: str
    deployment_ref_hash: str
    execution_gate_evidence_hash: str
    recovery_report_hash: str
    runtime: RuntimeIsolationEvidence
    malware_cdr: MalwareCdrServiceEvidence
    supply_chain: WorkerImageSupplyChainEvidence
    viewer: ViewerIsolationEvidence
    release_approval_hash: str
    security_approval_hash: str
    operations_approval_hash: str
    environment: Literal["production"] = "production"
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    destructive_action_requested: Literal[False] = False
    schema_version: Literal["preview_conversion_production_evidence.v1"] = "preview_conversion_production_evidence.v1"

    _validate_hashes = field_validator(
        "deployment_ref_hash",
        "execution_gate_evidence_hash",
        "recovery_report_hash",
        "release_approval_hash",
        "security_approval_hash",
        "operations_approval_hash",
    )(_require_sha256)

    @model_validator(mode="after")
    def require_distinct_approvals(self) -> Self:
        if not self.tenant_id:
            raise ValueError("preview conversion production tenant must not be empty")
        if len({self.release_approval_hash, self.security_approval_hash, self.operations_approval_hash}) != 3:
            raise ValueError("preview conversion production approvals must be distinct")
        return self


class PreviewConversionTrustedSigner(StrictEvidenceModel):
    key_id: str
    principal_ref_hash: str
    role: SignerRole
    algorithm: Literal["ed25519"] = "ed25519"
    public_key_base64: str = Field(min_length=44, max_length=44)
    valid_from_utc: datetime
    valid_until_utc: datetime
    revoked: bool = False

    _validate_hashes = field_validator("key_id", "principal_ref_hash")(_require_sha256)
    _validate_timestamps = field_validator("valid_from_utc", "valid_until_utc")(_require_aware_utc)

    @model_validator(mode="after")
    def require_valid_key(self) -> Self:
        public_key = _decode_base64(self.public_key_base64, expected_length=32)
        if sha256_bytes(public_key) != self.key_id:
            raise ValueError("preview conversion signer key id must match its public key")
        if self.valid_until_utc <= self.valid_from_utc:
            raise ValueError("preview conversion signer validity window is invalid")
        return self


class PreviewConversionSignerPolicy(StrictEvidenceModel):
    trust_domain: Literal["collabio.preview-conversion-production"] = "collabio.preview-conversion-production"
    required_roles: tuple[SignerRole, ...] = REQUIRED_SIGNER_ROLES
    minimum_distinct_signatures: Literal[3] = 3
    trusted_signers: tuple[PreviewConversionTrustedSigner, ...] = Field(min_length=3, max_length=64)
    schema_version: Literal["preview_conversion_signer_policy.v1"] = "preview_conversion_signer_policy.v1"

    @model_validator(mode="after")
    def require_trusted_roles(self) -> Self:
        if tuple(self.required_roles) != REQUIRED_SIGNER_ROLES:
            raise ValueError("preview conversion signer policy requires release, security and operations")
        if len({signer.key_id for signer in self.trusted_signers}) != len(self.trusted_signers):
            raise ValueError("preview conversion signer keys must be unique")
        active_roles = {signer.role for signer in self.trusted_signers if not signer.revoked}
        if not set(REQUIRED_SIGNER_ROLES).issubset(active_roles):
            raise ValueError("preview conversion signer policy lacks an active required role")
        return self

    def signer(self, key_id: str) -> PreviewConversionTrustedSigner | None:
        return next((signer for signer in self.trusted_signers if signer.key_id == key_id), None)


class InTotoSubjectDigest(StrictEvidenceModel):
    sha256: str

    @field_validator("sha256")
    @classmethod
    def require_hex_digest(cls, value: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("preview conversion in-toto subject digest must use sha256 hex")
        return value


class InTotoSubject(StrictEvidenceModel):
    name: Literal["preview-conversion-production-evidence"] = SUBJECT_NAME
    digest: InTotoSubjectDigest


class PreviewConversionAttestationPredicate(StrictEvidenceModel):
    tenant_id: str
    deployment_ref_hash: str
    execution_gate_evidence_hash: str
    worker_image_digest: str
    issued_at_utc: datetime

    _validate_hashes = field_validator(
        "deployment_ref_hash",
        "execution_gate_evidence_hash",
        "worker_image_digest",
    )(_require_sha256)
    _validate_timestamp = field_validator("issued_at_utc")(_require_aware_utc)


class PreviewConversionAttestationStatement(StrictEvidenceModel):
    type_: Literal["https://in-toto.io/Statement/v1"] = Field(default=IN_TOTO_STATEMENT_TYPE, alias="_type")
    subject: tuple[InTotoSubject, ...] = Field(min_length=1, max_length=1)
    predicate_type: Literal["https://collabio.eu/attestation/preview-conversion-production/v1"] = Field(
        default=PREDICATE_TYPE,
        alias="predicateType",
    )
    predicate: PreviewConversionAttestationPredicate


class DSSESignature(StrictEvidenceModel):
    keyid: str
    sig: str = Field(min_length=88, max_length=88)

    _validate_key_id = field_validator("keyid")(_require_sha256)

    @field_validator("sig")
    @classmethod
    def require_signature(cls, value: str) -> str:
        _decode_base64(value, expected_length=64)
        return value


class PreviewConversionAttestationEnvelope(StrictEvidenceModel):
    payload_type: Literal["application/vnd.in-toto+json"] = Field(default=DSSE_PAYLOAD_TYPE, alias="payloadType")
    payload: str = Field(min_length=4, max_length=MAX_ATTESTATION_PAYLOAD_BYTES * 2)
    signatures: tuple[DSSESignature, ...] = Field(min_length=3, max_length=3)

    @field_validator("payload")
    @classmethod
    def require_bounded_payload(cls, value: str) -> str:
        if len(_decode_base64(value)) > MAX_ATTESTATION_PAYLOAD_BYTES:
            raise ValueError("preview conversion attestation payload is too large")
        return value

    @model_validator(mode="after")
    def require_distinct_signers(self) -> Self:
        if len({signature.keyid for signature in self.signatures}) != 3:
            raise ValueError("preview conversion attestation requires three distinct keys")
        return self


class PreviewConversionAttestationVerification(StrictEvidenceModel):
    verified: bool
    signer_policy_hash: str
    envelope_hash: str
    verified_roles: tuple[SignerRole, ...] = ()
    verified_key_ids: tuple[str, ...] = ()
    issued_at_utc: datetime | None = None

    _validate_hashes = field_validator("signer_policy_hash", "envelope_hash")(_require_sha256)


class PreviewConversionProductionAdmissionGate(StrictEvidenceModel):
    tenant_id: str
    deployment_ref_hash: str
    execution_gate_evidence_hash: str
    recovery_report_hash: str
    worker_image_ref: str
    worker_image_digest: str
    viewer_origin: str
    evidence_bundle_hash: str
    signer_policy_hash: str
    attestation_envelope_hash: str
    checked_at_utc: datetime
    valid_until_utc: datetime
    maximum_evidence_age_hours: int = Field(ge=1, le=168)
    evidence_bindings_verified: bool
    evidence_freshness_verified: bool
    runtime_isolation_verified: bool
    malware_cdr_services_verified: bool
    worker_supply_chain_verified: bool
    non_empty_recovery_verified: bool
    viewer_isolation_verified: bool
    attestation_signatures_verified: bool
    verified_signer_roles: tuple[SignerRole, ...]
    verified_signer_key_ids: tuple[str, ...]
    metadata_only_evidence_verified: bool
    conversion_dispatch_allowed: bool
    preview_serving_allowed: Literal[False] = False
    blocking_reasons: tuple[str, ...]
    gate_status: PreviewConversionGateStatus
    gate_hash: str
    schema_version: Literal["preview_conversion_production_admission_gate.v1"] = (
        "preview_conversion_production_admission_gate.v1"
    )

    _validate_hashes = field_validator(
        "deployment_ref_hash",
        "execution_gate_evidence_hash",
        "recovery_report_hash",
        "worker_image_digest",
        "evidence_bundle_hash",
        "signer_policy_hash",
        "attestation_envelope_hash",
        "gate_hash",
    )(_require_sha256)
    _validate_timestamps = field_validator("checked_at_utc", "valid_until_utc")(_require_aware_utc)
    _validate_viewer_origin = field_validator("viewer_origin")(_require_https_origin)

    @field_validator("worker_image_ref")
    @classmethod
    def require_pinned_worker_image(cls, value: str) -> str:
        if not IMAGE_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion admission image must be digest pinned")
        return value

    @model_validator(mode="after")
    def require_consistent_gate(self) -> Self:
        checks = (
            self.evidence_bindings_verified,
            self.evidence_freshness_verified,
            self.runtime_isolation_verified,
            self.malware_cdr_services_verified,
            self.worker_supply_chain_verified,
            self.non_empty_recovery_verified,
            self.viewer_isolation_verified,
            self.attestation_signatures_verified,
            self.metadata_only_evidence_verified,
        )
        ready = all(checks) and not self.blocking_reasons
        if self.conversion_dispatch_allowed != ready:
            raise ValueError("preview conversion production admission state is inconsistent")
        expected = PreviewConversionGateStatus.READY if ready else PreviewConversionGateStatus.BLOCKED
        if self.gate_status != expected:
            raise ValueError("preview conversion production admission status is inconsistent")
        if self.valid_until_utc <= self.checked_at_utc:
            raise ValueError("preview conversion production admission must have a positive validity window")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ValueError("preview conversion production admission reasons must be unique")
        return self


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _model_hash(value: BaseModel, *, exclude: set[str] | None = None) -> str:
    return sha256_bytes(_canonical_bytes(value.model_dump(mode="json", by_alias=True, exclude=exclude or set())))


def _decode_base64(value: str, *, expected_length: int | None = None) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("preview conversion attestation values must use canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("preview conversion attestation values must use canonical base64")
    if expected_length is not None and len(decoded) != expected_length:
        raise ValueError("preview conversion attestation value has an invalid length")
    return decoded


def build_preview_conversion_production_evidence_hash(
    bundle: PreviewConversionProductionEvidenceBundle,
) -> str:
    return _model_hash(bundle)


def build_preview_conversion_signer_policy_hash(policy: PreviewConversionSignerPolicy) -> str:
    return _model_hash(policy)


def build_preview_conversion_attestation_envelope_hash(
    envelope: PreviewConversionAttestationEnvelope,
) -> str:
    return _model_hash(envelope)


def build_preview_conversion_production_admission_gate_hash(
    gate: PreviewConversionProductionAdmissionGate,
) -> str:
    return _model_hash(gate, exclude={"gate_hash"})


def build_preview_conversion_attestation_statement(
    *,
    bundle: PreviewConversionProductionEvidenceBundle,
    issued_at_utc: datetime,
) -> PreviewConversionAttestationStatement:
    bundle_hash = build_preview_conversion_production_evidence_hash(bundle)
    return PreviewConversionAttestationStatement(
        subject=(InTotoSubject(digest=InTotoSubjectDigest(sha256=bundle_hash.removeprefix("sha256:"))),),
        predicate=PreviewConversionAttestationPredicate(
            tenant_id=bundle.tenant_id,
            deployment_ref_hash=bundle.deployment_ref_hash,
            execution_gate_evidence_hash=bundle.execution_gate_evidence_hash,
            worker_image_digest=bundle.supply_chain.worker_image_digest,
            issued_at_utc=issued_at_utc,
        ),
    )


def build_preview_conversion_dsse_payload(statement: PreviewConversionAttestationStatement) -> bytes:
    return _canonical_bytes(statement.model_dump(mode="json", by_alias=True))


def build_dsse_pae(*, payload_type: str, payload: bytes) -> bytes:
    payload_type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 %d %b %d %b" % (len(payload_type_bytes), payload_type_bytes, len(payload), payload)


def verify_preview_conversion_attestation(
    *,
    bundle: PreviewConversionProductionEvidenceBundle,
    envelope: PreviewConversionAttestationEnvelope,
    signer_policy: PreviewConversionSignerPolicy,
    checked_at_utc: datetime,
    maximum_age_hours: int,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> PreviewConversionAttestationVerification:
    policy_hash = build_preview_conversion_signer_policy_hash(signer_policy)
    envelope_hash = build_preview_conversion_attestation_envelope_hash(envelope)
    invalid = PreviewConversionAttestationVerification(
        verified=False,
        signer_policy_hash=policy_hash,
        envelope_hash=envelope_hash,
    )
    try:
        checked_at = _require_aware_utc(checked_at_utc)
        payload = _decode_base64(envelope.payload)
        statement = PreviewConversionAttestationStatement.model_validate_json(payload)
        if payload != build_preview_conversion_dsse_payload(statement):
            return invalid
        bundle_hash = build_preview_conversion_production_evidence_hash(bundle)
        predicate = statement.predicate
        expected = (
            "sha256:" + statement.subject[0].digest.sha256 == bundle_hash
            and predicate.tenant_id == bundle.tenant_id
            and predicate.deployment_ref_hash == bundle.deployment_ref_hash
            and predicate.execution_gate_evidence_hash == bundle.execution_gate_evidence_hash
            and predicate.worker_image_digest == bundle.supply_chain.worker_image_digest
            and checked_at - timedelta(hours=maximum_age_hours) <= predicate.issued_at_utc <= checked_at
        )
        if not expected:
            return invalid
        pae = build_dsse_pae(payload_type=envelope.payload_type, payload=payload)
        roles: list[SignerRole] = []
        principals: set[str] = set()
        key_ids: list[str] = []
        for signature in envelope.signatures:
            signer = signer_policy.signer(signature.keyid)
            if signer is None or signer.revoked:
                return invalid
            if not (
                signer.valid_from_utc <= predicate.issued_at_utc <= signer.valid_until_utc
                and signer.valid_from_utc <= checked_at <= signer.valid_until_utc
            ):
                return invalid
            if not signature_verifier.verify_ed25519(
                public_key=_decode_base64(signer.public_key_base64, expected_length=32),
                signature=_decode_base64(signature.sig, expected_length=64),
                message=pae,
            ):
                return invalid
            roles.append(signer.role)
            principals.add(signer.principal_ref_hash)
            key_ids.append(signer.key_id)
        if set(roles) != set(REQUIRED_SIGNER_ROLES) or len(principals) != 3:
            return invalid
    except ValueError:
        return invalid
    return PreviewConversionAttestationVerification(
        verified=True,
        signer_policy_hash=policy_hash,
        envelope_hash=envelope_hash,
        verified_roles=tuple(sorted(roles)),
        verified_key_ids=tuple(sorted(key_ids)),
        issued_at_utc=predicate.issued_at_utc,
    )


def build_preview_conversion_production_admission_gate(
    *,
    bundle: PreviewConversionProductionEvidenceBundle,
    execution_gate: PreviewConversionExecutionGateEvidence,
    recovery_report: DerivedPreviewRecoveryDrillReport,
    attestation_envelope: PreviewConversionAttestationEnvelope,
    signer_policy: PreviewConversionSignerPolicy,
    checked_at_utc: datetime | None = None,
    maximum_evidence_age_hours: int = 24,
) -> PreviewConversionProductionAdmissionGate:
    checked_at = _require_aware_utc(checked_at_utc or datetime.now(UTC))
    if maximum_evidence_age_hours < 1 or maximum_evidence_age_hours > 168:
        raise ValueError("preview conversion production evidence age must be between 1 and 168 hours")
    recovery_checked_at = _parse_utc_timestamp(recovery_report.checked_at_utc)
    attestation = verify_preview_conversion_attestation(
        bundle=bundle,
        envelope=attestation_envelope,
        signer_policy=signer_policy,
        checked_at_utc=checked_at,
        maximum_age_hours=maximum_evidence_age_hours,
    )
    execution_hash_valid = build_preview_conversion_execution_gate_hash(execution_gate) == execution_gate.evidence_hash
    recovery_hash_valid = (
        build_derived_preview_recovery_drill_report_hash(recovery_report) == recovery_report.report_hash
    )
    evidence_bindings_verified = all(
        (
            execution_hash_valid,
            recovery_hash_valid,
            bundle.tenant_id == execution_gate.tenant_id,
            bundle.tenant_id in recovery_report.tenant_ids,
            bundle.execution_gate_evidence_hash == execution_gate.evidence_hash,
            bundle.recovery_report_hash == recovery_report.report_hash,
            bundle.runtime.sandbox_runtime_class == execution_gate.sandbox_runtime_class,
            bundle.runtime.conformance_report_hash == execution_gate.sandbox_runtime_evidence_hash,
            bundle.malware_cdr.scanner_profile_ref == execution_gate.malware_scanner_profile_ref,
            bundle.malware_cdr.scanner_evidence_hash == execution_gate.malware_scanner_evidence_hash,
            bundle.malware_cdr.cdr_profile_ref == execution_gate.cdr_profile_ref,
            bundle.malware_cdr.cdr_evidence_hash == execution_gate.cdr_evidence_hash,
            bundle.supply_chain.worker_image_ref == execution_gate.worker_image_ref,
            bundle.supply_chain.worker_image_digest == execution_gate.worker_image_digest,
            bundle.viewer.viewer_origin == execution_gate.viewer_origin,
            bundle.viewer.csp_evidence_hash == execution_gate.viewer_csp_evidence_hash,
            execution_gate.backup_restore_evidence_hash == recovery_report.report_hash,
        )
    )
    observed_at = (
        bundle.runtime.observed_at_utc,
        bundle.malware_cdr.observed_at_utc,
        bundle.supply_chain.observed_at_utc,
        bundle.viewer.observed_at_utc,
        recovery_checked_at,
    )
    oldest_allowed = checked_at - timedelta(hours=maximum_evidence_age_hours)
    evidence_freshness_verified = (
        all(oldest_allowed <= timestamp <= checked_at for timestamp in observed_at)
        and execution_gate.evaluated_at_utc <= checked_at <= execution_gate.expires_at_utc
    )
    runtime = bundle.runtime
    runtime_isolation_verified = all(
        (
            runtime.production_host_profile_verified,
            runtime.no_network_egress_verified,
            runtime.read_only_root_filesystem_verified,
            runtime.non_root_user_verified,
            runtime.capabilities_dropped_verified,
            runtime.no_new_privileges_verified,
            runtime.ephemeral_workspace_verified,
            not runtime.synthetic_runtime_used,
            execution_gate.gate_status == PreviewConversionGateStatus.READY,
            execution_gate.stronger_sandbox_attested,
            execution_gate.network_egress_denied,
            execution_gate.read_only_root_filesystem,
            execution_gate.non_root_user,
            execution_gate.all_capabilities_dropped,
            execution_gate.no_new_privileges,
            execution_gate.ephemeral_workspace,
        )
    )
    malware_cdr = bundle.malware_cdr
    malware_cdr_services_verified = all(
        (
            malware_cdr.real_services_invoked,
            malware_cdr.tenant_routing_verified,
            malware_cdr.signature_freshness_verified,
            malware_cdr.quarantine_on_error_verified,
            malware_cdr.cdr_fail_closed_verified,
            not malware_cdr.synthetic_provider_used,
            execution_gate.malware_cdr_ready,
        )
    )
    supply_chain = bundle.supply_chain
    worker_supply_chain_verified = all(
        (
            supply_chain.provenance_signature_verified,
            supply_chain.provenance_subject_digest_verified,
            supply_chain.provenance_builder_identity_verified,
            supply_chain.provenance_source_repository_verified,
            supply_chain.sbom_signature_verified,
            supply_chain.sbom_subject_digest_verified,
            supply_chain.vulnerability_policy_passed,
            supply_chain.license_policy_passed,
        )
    )
    non_empty_recovery_verified = all(
        (
            recovery_report.recovery_ready,
            recovery_report.non_empty_recovery_verified,
            recovery_report.production_admission_evidence_ready,
            recovery_report.metadata_only_evidence_verified,
            not recovery_report.content_included,
            recovery_report.derived_preview_receipt_count > 0,
            recovery_report.conversion_job_evidence_count > 0,
            not recovery_report.blocking_reasons,
        )
    )
    viewer = bundle.viewer
    viewer_csp_verified = REQUIRED_VIEWER_CSP_DIRECTIVES.issubset(viewer.csp_directives) and any(
        directive == f"frame-ancestors {viewer.application_origin}" for directive in viewer.csp_directives
    )
    viewer_isolation_verified = all(
        (
            viewer.separate_origin_verified,
            viewer.https_tls_verified,
            viewer.viewer_session_cookie_absent,
            viewer.viewer_service_worker_disabled,
            viewer.pdfjs_external_actions_disabled,
            viewer.browser_smoke_passed,
            not viewer.synthetic_viewer_used,
            viewer_csp_verified,
            tuple(sorted(viewer.iframe_sandbox_tokens)) == tuple(sorted(REQUIRED_IFRAME_SANDBOX_TOKENS)),
            execution_gate.separate_viewer_origin_ready,
            execution_gate.strict_viewer_csp_ready,
        )
    )
    metadata_only_evidence_verified = all(
        (
            not bundle.content_included,
            not bundle.secrets_included,
            not bundle.destructive_action_requested,
            not recovery_report.content_included,
        )
    )
    checks = {
        "evidence_bindings_not_verified": evidence_bindings_verified,
        "evidence_not_fresh": evidence_freshness_verified,
        "runtime_isolation_not_verified": runtime_isolation_verified,
        "real_malware_cdr_services_not_verified": malware_cdr_services_verified,
        "worker_supply_chain_not_verified": worker_supply_chain_verified,
        "non_empty_recovery_not_verified": non_empty_recovery_verified,
        "viewer_isolation_not_verified": viewer_isolation_verified,
        "attestation_signatures_not_verified": attestation.verified,
        "metadata_only_boundary_not_verified": metadata_only_evidence_verified,
    }
    blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
    ready = not blocking_reasons
    valid_until = min(
        execution_gate.expires_at_utc,
        *(timestamp + timedelta(hours=maximum_evidence_age_hours) for timestamp in observed_at),
    )
    if valid_until <= checked_at:
        blocking_reasons = tuple(sorted({*blocking_reasons, "production_admission_validity_window_empty"}))
        ready = False
        valid_until = checked_at + timedelta(seconds=1)
    draft = PreviewConversionProductionAdmissionGate(
        tenant_id=bundle.tenant_id,
        deployment_ref_hash=bundle.deployment_ref_hash,
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        recovery_report_hash=recovery_report.report_hash,
        worker_image_ref=supply_chain.worker_image_ref,
        worker_image_digest=supply_chain.worker_image_digest,
        viewer_origin=viewer.viewer_origin,
        evidence_bundle_hash=build_preview_conversion_production_evidence_hash(bundle),
        signer_policy_hash=attestation.signer_policy_hash,
        attestation_envelope_hash=attestation.envelope_hash,
        checked_at_utc=checked_at,
        valid_until_utc=valid_until,
        maximum_evidence_age_hours=maximum_evidence_age_hours,
        evidence_bindings_verified=evidence_bindings_verified,
        evidence_freshness_verified=evidence_freshness_verified,
        runtime_isolation_verified=runtime_isolation_verified,
        malware_cdr_services_verified=malware_cdr_services_verified,
        worker_supply_chain_verified=worker_supply_chain_verified,
        non_empty_recovery_verified=non_empty_recovery_verified,
        viewer_isolation_verified=viewer_isolation_verified,
        attestation_signatures_verified=attestation.verified,
        verified_signer_roles=attestation.verified_roles,
        verified_signer_key_ids=attestation.verified_key_ids,
        metadata_only_evidence_verified=metadata_only_evidence_verified,
        conversion_dispatch_allowed=ready,
        blocking_reasons=blocking_reasons,
        gate_status=PreviewConversionGateStatus.READY if ready else PreviewConversionGateStatus.BLOCKED,
        gate_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"gate_hash": build_preview_conversion_production_admission_gate_hash(draft)})


def bind_preview_conversion_command_to_production_admission(
    *,
    command: PreviewConversionCommand,
    execution_gate: PreviewConversionExecutionGateEvidence,
    production_gate: PreviewConversionProductionAdmissionGate,
    checked_at_utc: datetime | None = None,
) -> PreviewConversionCommand:
    _require_preview_conversion_production_admission(
        command=command,
        execution_gate=execution_gate,
        production_gate=production_gate,
        checked_at_utc=checked_at_utc,
        require_command_binding=False,
    )
    draft = command.model_copy(
        update={
            "production_admission_gate_hash": production_gate.gate_hash,
            "command_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"command_hash": build_preview_conversion_command_hash(draft)})


def require_preview_conversion_production_admission(
    *,
    command: PreviewConversionCommand,
    execution_gate: PreviewConversionExecutionGateEvidence,
    production_gate: PreviewConversionProductionAdmissionGate,
    checked_at_utc: datetime | None = None,
) -> None:
    _require_preview_conversion_production_admission(
        command=command,
        execution_gate=execution_gate,
        production_gate=production_gate,
        checked_at_utc=checked_at_utc,
        require_command_binding=True,
    )


def _require_preview_conversion_production_admission(
    *,
    command: PreviewConversionCommand,
    execution_gate: PreviewConversionExecutionGateEvidence,
    production_gate: PreviewConversionProductionAdmissionGate,
    checked_at_utc: datetime | None,
    require_command_binding: bool,
) -> None:
    checked_at = _require_aware_utc(checked_at_utc or datetime.now(UTC))
    if build_preview_conversion_production_admission_gate_hash(production_gate) != production_gate.gate_hash:
        raise PreviewConversionBlocked("preview conversion production admission hash is invalid")
    bindings = (
        production_gate.tenant_id == command.tenant_id == execution_gate.tenant_id
        and production_gate.execution_gate_evidence_hash == execution_gate.evidence_hash
        and command.execution_gate_evidence_hash == execution_gate.evidence_hash
        and production_gate.worker_image_ref == command.worker_image_ref == execution_gate.worker_image_ref
        and production_gate.worker_image_digest == execution_gate.worker_image_digest
    )
    if require_command_binding:
        bindings = bindings and command.production_admission_gate_hash == production_gate.gate_hash
    if not bindings:
        raise PreviewConversionBlocked("preview conversion command is not bound to production admission")
    if (
        production_gate.gate_status != PreviewConversionGateStatus.READY
        or not production_gate.conversion_dispatch_allowed
    ):
        raise PreviewConversionBlocked("preview conversion production admission is blocked")
    if checked_at < production_gate.checked_at_utc or checked_at > production_gate.valid_until_utc:
        raise PreviewConversionBlocked("preview conversion production admission is stale")


def load_preview_conversion_production_evidence_bundle(
    path: Path,
) -> PreviewConversionProductionEvidenceBundle:
    return PreviewConversionProductionEvidenceBundle.model_validate_json(path.read_text(encoding="utf-8"))


def load_preview_conversion_signer_policy(path: Path) -> PreviewConversionSignerPolicy:
    return PreviewConversionSignerPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def load_preview_conversion_attestation_envelope(path: Path) -> PreviewConversionAttestationEnvelope:
    return PreviewConversionAttestationEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def load_preview_conversion_production_admission_gate(
    path: Path,
) -> PreviewConversionProductionAdmissionGate:
    gate = PreviewConversionProductionAdmissionGate.model_validate_json(path.read_text(encoding="utf-8"))
    if build_preview_conversion_production_admission_gate_hash(gate) != gate.gate_hash:
        raise ValueError("preview conversion production admission gate hash is invalid")
    return gate


def load_and_require_preview_conversion_production_admission(
    *,
    command: PreviewConversionCommand,
    execution_gate: PreviewConversionExecutionGateEvidence,
    production_gate_path: Path,
    evidence_bundle_path: Path,
    recovery_report_path: Path,
    attestation_path: Path,
    signer_policy_path: Path,
    checked_at_utc: datetime | None = None,
) -> PreviewConversionProductionAdmissionGate:
    checked_at = _require_aware_utc(checked_at_utc or datetime.now(UTC))
    production_gate = load_preview_conversion_production_admission_gate(production_gate_path)
    bundle = load_preview_conversion_production_evidence_bundle(evidence_bundle_path)
    recovery_report = DerivedPreviewRecoveryDrillReport.model_validate_json(
        recovery_report_path.read_text(encoding="utf-8")
    )
    attestation_envelope = load_preview_conversion_attestation_envelope(attestation_path)
    signer_policy = load_preview_conversion_signer_policy(signer_policy_path)
    reproduced_gate = build_preview_conversion_production_admission_gate(
        bundle=bundle,
        execution_gate=execution_gate,
        recovery_report=recovery_report,
        attestation_envelope=attestation_envelope,
        signer_policy=signer_policy,
        checked_at_utc=production_gate.checked_at_utc,
        maximum_evidence_age_hours=production_gate.maximum_evidence_age_hours,
    )
    if reproduced_gate != production_gate:
        raise PreviewConversionBlocked("preview conversion production admission could not be reproduced")
    current_attestation = verify_preview_conversion_attestation(
        bundle=bundle,
        envelope=attestation_envelope,
        signer_policy=signer_policy,
        checked_at_utc=checked_at,
        maximum_age_hours=production_gate.maximum_evidence_age_hours,
    )
    current_trust_verified = all(
        (
            current_attestation.verified,
            current_attestation.signer_policy_hash == production_gate.signer_policy_hash,
            current_attestation.envelope_hash == production_gate.attestation_envelope_hash,
            build_preview_conversion_production_evidence_hash(bundle) == production_gate.evidence_bundle_hash,
        )
    )
    if not current_trust_verified:
        raise PreviewConversionBlocked("preview conversion production admission trust is no longer valid")
    require_preview_conversion_production_admission(
        command=command,
        execution_gate=execution_gate,
        production_gate=production_gate,
        checked_at_utc=checked_at,
    )
    return production_gate


def run_preview_conversion_production_admission_from_environment(
    environ: Mapping[str, str] | None = None,
) -> PreviewConversionProductionAdmissionGate:
    env = os.environ if environ is None else environ
    bundle = load_preview_conversion_production_evidence_bundle(
        Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_EVIDENCE_PATH"))
    )
    execution_gate = PreviewConversionExecutionGateEvidence.model_validate_json(
        Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_EXECUTION_GATE_PATH")).read_text(encoding="utf-8")
    )
    recovery_report = DerivedPreviewRecoveryDrillReport.model_validate_json(
        Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_RECOVERY_REPORT_PATH")).read_text(encoding="utf-8")
    )
    envelope = load_preview_conversion_attestation_envelope(
        Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_ATTESTATION_PATH"))
    )
    signer_policy = load_preview_conversion_signer_policy(
        Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_SIGNER_POLICY_PATH"))
    )
    gate = build_preview_conversion_production_admission_gate(
        bundle=bundle,
        execution_gate=execution_gate,
        recovery_report=recovery_report,
        attestation_envelope=envelope,
        signer_policy=signer_policy,
        maximum_evidence_age_hours=int(env.get("SUITE_PREVIEW_PRODUCTION_MAX_EVIDENCE_AGE_HOURS", "24")),
    )
    output_path = Path(_required_env(env, "SUITE_PREVIEW_PRODUCTION_GATE_REPORT_PATH"))
    _write_json_atomically(output_path, gate.model_dump(mode="json"))
    return gate


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _require_aware_utc(parsed)


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary_path.replace(path)


def main() -> int:
    try:
        gate = run_preview_conversion_production_admission_from_environment()
    except (OSError, ValueError):
        print("preview conversion production admission failed closed", file=sys.stderr)
        return 2
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
    return 0 if gate.conversion_dispatch_allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
