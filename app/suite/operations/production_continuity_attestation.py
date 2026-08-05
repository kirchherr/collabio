from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.kms.signatures import (
    DEFAULT_DETACHED_SIGNATURE_VERIFIER,
    DetachedSignatureVerifier,
)
from suite.storage.source_objects import sha256_bytes

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
SHA256_HEX_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DSSE_PAYLOAD_TYPE: Literal["application/vnd.in-toto+json"] = "application/vnd.in-toto+json"
IN_TOTO_STATEMENT_TYPE: Literal["https://in-toto.io/Statement/v1"] = "https://in-toto.io/Statement/v1"
PRODUCTION_CONTINUITY_PREDICATE_TYPE: Literal["https://collabio.eu/attestation/production-continuity/v1"] = (
    "https://collabio.eu/attestation/production-continuity/v1"
)
PRODUCTION_CONTINUITY_SUBJECT_NAME: Literal["production-continuity-evidence"] = "production-continuity-evidence"
REQUIRED_SIGNER_ROLES: tuple[Literal["change", "security", "operations"], ...] = (
    "change",
    "security",
    "operations",
)
MAX_ATTESTATION_PAYLOAD_BYTES = 64 * 1024

SignerRole = Literal["change", "security", "operations"]


class StrictAttestationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


def _require_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("attestation references must use sha256")
    return value


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("attestation timestamps must include a timezone")
    return value.astimezone(UTC)


def _decode_base64(value: str, *, expected_length: int | None = None) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("attestation values must use canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("attestation values must use canonical base64")
    if expected_length is not None and len(decoded) != expected_length:
        raise ValueError("attestation value has an invalid length")
    return decoded


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _model_canonical_bytes(value: BaseModel) -> bytes:
    return _canonical_json_bytes(value.model_dump(mode="json", by_alias=True))


def _model_hash(value: BaseModel) -> str:
    return sha256_bytes(_model_canonical_bytes(value))


class ProductionContinuityTrustedSigner(StrictAttestationModel):
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
    def validate_key_and_window(self) -> Self:
        public_key = _decode_base64(self.public_key_base64, expected_length=32)
        if sha256_bytes(public_key) != self.key_id:
            raise ValueError("attestation key id must be the sha256 digest of the public key")
        if self.valid_until_utc <= self.valid_from_utc:
            raise ValueError("attestation signer validity window is invalid")
        return self


class ProductionContinuitySignerPolicy(StrictAttestationModel):
    trust_domain: Literal["collabio.production-continuity"] = "collabio.production-continuity"
    required_roles: tuple[SignerRole, ...] = REQUIRED_SIGNER_ROLES
    minimum_distinct_signatures: Literal[3] = 3
    trusted_signers: tuple[ProductionContinuityTrustedSigner, ...] = Field(min_length=3, max_length=64)
    schema_version: Literal["production_continuity_signer_policy.v1"] = "production_continuity_signer_policy.v1"

    @model_validator(mode="after")
    def validate_trust_roster(self) -> Self:
        if tuple(self.required_roles) != REQUIRED_SIGNER_ROLES:
            raise ValueError("attestation signer policy must require change, security and operations")
        key_ids = [signer.key_id for signer in self.trusted_signers]
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("attestation signer key ids must be unique")
        available_roles = {signer.role for signer in self.trusted_signers if not signer.revoked}
        if not set(REQUIRED_SIGNER_ROLES).issubset(available_roles):
            raise ValueError("attestation signer policy must contain an active key for every required role")
        return self

    def signer(self, key_id: str) -> ProductionContinuityTrustedSigner | None:
        return next((signer for signer in self.trusted_signers if signer.key_id == key_id), None)


class ProductionContinuityApprovalPrincipals(StrictAttestationModel):
    change: str
    security: str
    operations: str

    _validate_hashes = field_validator("change", "security", "operations")(_require_sha256)

    @model_validator(mode="after")
    def require_distinct_principals(self) -> Self:
        if len({self.change, self.security, self.operations}) != 3:
            raise ValueError("attestation approvals require three distinct principals")
        return self

    def for_role(self, role: SignerRole) -> str:
        return {"change": self.change, "security": self.security, "operations": self.operations}[role]


class ProductionContinuityAttestationPredicate(StrictAttestationModel):
    deployment_ref_hash: str
    backup_policy_schema_version: str
    backup_policy_hash: str
    evidence_schema_version: Literal["production_continuity_deployment_evidence.v1"] = (
        "production_continuity_deployment_evidence.v1"
    )
    approval_principals: ProductionContinuityApprovalPrincipals
    issued_at_utc: datetime
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False

    _validate_hashes = field_validator("deployment_ref_hash", "backup_policy_hash")(_require_sha256)
    _validate_timestamp = field_validator("issued_at_utc")(_require_aware_utc)


class InTotoSubjectDigest(StrictAttestationModel):
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256_hex(cls, value: str) -> str:
        if not SHA256_HEX_PATTERN.fullmatch(value):
            raise ValueError("in-toto subject digest must use lowercase sha256 hex")
        return value


class InTotoSubject(StrictAttestationModel):
    name: Literal["production-continuity-evidence"] = PRODUCTION_CONTINUITY_SUBJECT_NAME
    digest: InTotoSubjectDigest


class ProductionContinuityAttestationStatement(StrictAttestationModel):
    type_: Literal["https://in-toto.io/Statement/v1"] = Field(default=IN_TOTO_STATEMENT_TYPE, alias="_type")
    subject: tuple[InTotoSubject, ...] = Field(min_length=1, max_length=1)
    predicate_type: Literal["https://collabio.eu/attestation/production-continuity/v1"] = Field(
        default=PRODUCTION_CONTINUITY_PREDICATE_TYPE,
        alias="predicateType",
    )
    predicate: ProductionContinuityAttestationPredicate


class DSSESignature(StrictAttestationModel):
    keyid: str
    sig: str = Field(min_length=88, max_length=88)

    _validate_key_id = field_validator("keyid")(_require_sha256)

    @field_validator("sig")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        _decode_base64(value, expected_length=64)
        return value


class ProductionContinuityAttestationEnvelope(StrictAttestationModel):
    payload_type: Literal["application/vnd.in-toto+json"] = Field(
        default=DSSE_PAYLOAD_TYPE,
        alias="payloadType",
    )
    payload: str = Field(min_length=4, max_length=MAX_ATTESTATION_PAYLOAD_BYTES * 2)
    signatures: tuple[DSSESignature, ...] = Field(min_length=3, max_length=3)

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, value: str) -> str:
        payload = _decode_base64(value)
        if len(payload) > MAX_ATTESTATION_PAYLOAD_BYTES:
            raise ValueError("attestation payload exceeds the size limit")
        return value

    @model_validator(mode="after")
    def require_distinct_key_ids(self) -> Self:
        if len({signature.keyid for signature in self.signatures}) != 3:
            raise ValueError("attestation signatures must use three distinct keys")
        return self


class ProductionContinuityAttestationVerification(StrictAttestationModel):
    verified: bool
    signer_policy_hash: str
    envelope_hash: str
    verified_roles: tuple[SignerRole, ...] = ()
    verified_key_ids: tuple[str, ...] = ()
    issued_at_utc: str | None = None

    _validate_hashes = field_validator("signer_policy_hash", "envelope_hash")(_require_sha256)


def build_production_continuity_signer_policy_hash(policy: ProductionContinuitySignerPolicy) -> str:
    return _model_hash(policy)


def build_production_continuity_attestation_envelope_hash(
    envelope: ProductionContinuityAttestationEnvelope,
) -> str:
    return _model_hash(envelope)


def build_production_continuity_attestation_statement(
    *,
    evidence_bundle_hash: str,
    deployment_ref_hash: str,
    backup_policy_schema_version: str,
    backup_policy_hash: str,
    approval_principals: ProductionContinuityApprovalPrincipals,
    issued_at: datetime,
) -> ProductionContinuityAttestationStatement:
    _require_sha256(evidence_bundle_hash)
    return ProductionContinuityAttestationStatement(
        subject=(InTotoSubject(digest=InTotoSubjectDigest(sha256=evidence_bundle_hash.removeprefix("sha256:"))),),
        predicate=ProductionContinuityAttestationPredicate(
            deployment_ref_hash=deployment_ref_hash,
            backup_policy_schema_version=backup_policy_schema_version,
            backup_policy_hash=backup_policy_hash,
            approval_principals=approval_principals,
            issued_at_utc=issued_at,
        ),
    )


def build_dsse_payload(statement: ProductionContinuityAttestationStatement) -> bytes:
    return _model_canonical_bytes(statement)


def build_dsse_pae(*, payload_type: str, payload: bytes) -> bytes:
    payload_type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 %d %b %d %b" % (len(payload_type_bytes), payload_type_bytes, len(payload), payload)


def verify_production_continuity_attestation(
    *,
    envelope: ProductionContinuityAttestationEnvelope,
    signer_policy: ProductionContinuitySignerPolicy,
    expected_evidence_bundle_hash: str,
    expected_deployment_ref_hash: str,
    expected_backup_policy_schema_version: str,
    expected_backup_policy_hash: str,
    checked_at: datetime,
    maximum_age_hours: int,
    expected_approval_principals: ProductionContinuityApprovalPrincipals | None = None,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> ProductionContinuityAttestationVerification:
    policy_hash = build_production_continuity_signer_policy_hash(signer_policy)
    envelope_hash = build_production_continuity_attestation_envelope_hash(envelope)
    invalid = ProductionContinuityAttestationVerification(
        verified=False,
        signer_policy_hash=policy_hash,
        envelope_hash=envelope_hash,
    )
    try:
        checked = _require_aware_utc(checked_at)
        payload = _decode_base64(envelope.payload)
        statement = ProductionContinuityAttestationStatement.model_validate_json(payload)
        if payload != build_dsse_payload(statement):
            return invalid
        predicate = statement.predicate
        subject_hash = "sha256:" + statement.subject[0].digest.sha256
        if not all(
            (
                subject_hash == expected_evidence_bundle_hash,
                predicate.deployment_ref_hash == expected_deployment_ref_hash,
                predicate.backup_policy_schema_version == expected_backup_policy_schema_version,
                predicate.backup_policy_hash == expected_backup_policy_hash,
                predicate.issued_at_utc <= checked,
                predicate.issued_at_utc >= checked - timedelta(hours=maximum_age_hours),
                expected_approval_principals is None or predicate.approval_principals == expected_approval_principals,
            )
        ):
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
                and signer.valid_from_utc <= checked <= signer.valid_until_utc
            ):
                return invalid
            if signer.principal_ref_hash != predicate.approval_principals.for_role(signer.role):
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

    return ProductionContinuityAttestationVerification(
        verified=True,
        signer_policy_hash=policy_hash,
        envelope_hash=envelope_hash,
        verified_roles=tuple(sorted(roles)),
        verified_key_ids=tuple(sorted(key_ids)),
        issued_at_utc=predicate.issued_at_utc.isoformat(),
    )


def load_production_continuity_signer_policy(path: Path) -> ProductionContinuitySignerPolicy:
    return ProductionContinuitySignerPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def load_production_continuity_attestation_envelope(path: Path) -> ProductionContinuityAttestationEnvelope:
    return ProductionContinuityAttestationEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
