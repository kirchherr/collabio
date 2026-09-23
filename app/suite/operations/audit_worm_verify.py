from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from suite.ai_control_plane.audit import verify_audit_chain
from suite.kms.audit_verification import (
    AuditOfflineSignatureVerificationError,
    verify_offline_audit_checkpoint_signature,
)
from suite.kms.signing import AuditSigningAlgorithm, AuditSigningKeyReference
from suite.operations.audit_worm_snapshot import AuditWormSnapshotBundle

MAX_AUDIT_WORM_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_AUDIT_SIGNING_TRUST_POLICY_BYTES = 1024 * 1024
VERIFIED_CHECKS = (
    "exact_bundle_hash",
    "canonical_v2_bundle",
    "manifest_and_event_hashes",
    "tenant_event_chain",
    "pinned_trust_policy",
    "signing_key_and_validity_window",
    "offline_detached_signature",
)


class AuditWormVerificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StrictVerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError("value must be a sha256 reference")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except ValueError as exc:
        raise ValueError("value must be a sha256 reference") from exc
    if value != value.lower():
        raise ValueError("value must be a lowercase sha256 reference")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


class AuditTrustedSigningKey(StrictVerificationModel):
    kms_key_ref: str
    provider_profile: str = Field(min_length=1, max_length=128)
    provider_key_id: str = Field(min_length=1, max_length=2048)
    public_key_sha256: str
    allowed_signing_algorithms: tuple[AuditSigningAlgorithm, ...] = Field(min_length=1, max_length=2)
    valid_from_utc: datetime
    valid_until_utc: datetime | None = None
    revoked: bool = False

    _validate_public_key_hash = field_validator("public_key_sha256")(_require_sha256)
    _validate_valid_from = field_validator("valid_from_utc")(_require_utc)

    @field_validator("valid_until_utc")
    @classmethod
    def require_optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def require_consistent_key(self) -> Self:
        try:
            AuditSigningKeyReference.parse(self.kms_key_ref)
        except Exception as exc:
            raise ValueError("trusted signing key reference is invalid") from exc
        if len(set(self.allowed_signing_algorithms)) != len(self.allowed_signing_algorithms):
            raise ValueError("trusted signing algorithms must be unique")
        if self.valid_until_utc is not None and self.valid_until_utc <= self.valid_from_utc:
            raise ValueError("trusted signing key validity window is invalid")
        return self


class AuditSigningTrustPolicy(StrictVerificationModel):
    schema_version: Literal["audit_signing_trust_policy.v1"] = "audit_signing_trust_policy.v1"
    policy_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=255)
    issued_at_utc: datetime
    trusted_keys: tuple[AuditTrustedSigningKey, ...] = Field(min_length=1, max_length=64)

    _validate_issued_at = field_validator("issued_at_utc")(_require_utc)

    @model_validator(mode="after")
    def require_tenant_key_roster(self) -> Self:
        key_refs: set[str] = set()
        provider_keys: set[tuple[str, str]] = set()
        public_key_hashes: set[str] = set()
        for trusted_key in self.trusted_keys:
            key_ref = AuditSigningKeyReference.parse(trusted_key.kms_key_ref)
            if key_ref.tenant_id != self.tenant_id:
                raise ValueError("trusted signing key tenant does not match policy tenant")
            provider_key = (trusted_key.provider_profile, trusted_key.provider_key_id)
            if (
                trusted_key.kms_key_ref in key_refs
                or provider_key in provider_keys
                or trusted_key.public_key_sha256 in public_key_hashes
            ):
                raise ValueError("trusted signing key identities must be unique")
            key_refs.add(trusted_key.kms_key_ref)
            provider_keys.add(provider_key)
            public_key_hashes.add(trusted_key.public_key_sha256)
        return self

    def key_for(self, kms_key_ref: str) -> AuditTrustedSigningKey | None:
        return next((key for key in self.trusted_keys if key.kms_key_ref == kms_key_ref), None)


class AuditWormSnapshotVerificationReport(StrictVerificationModel):
    schema_version: Literal["audit_worm_snapshot_verification_report.v2"] = "audit_worm_snapshot_verification_report.v2"
    verified: Literal[True] = True
    tenant_id: str
    checkpoint_id: str
    through_sequence_number: int = Field(ge=1)
    event_count: int = Field(ge=1)
    bundle_hash: str
    manifest_hash: str
    events_hash: str
    trust_policy_id: str
    trust_policy_hash: str
    signing_key_ref: str
    signing_key_version: int = Field(ge=1)
    provider_profile: str
    provider_key_id_hash: str
    public_key_sha256: str
    signature_sha256: str
    signed_at_utc: str
    retain_until_utc: str
    verified_checks: tuple[str, ...] = VERIFIED_CHECKS
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    network_access_required: Literal[False] = False

    _validate_hashes = field_validator(
        "bundle_hash",
        "manifest_hash",
        "events_hash",
        "trust_policy_hash",
        "provider_key_id_hash",
        "public_key_sha256",
        "signature_sha256",
    )(_require_sha256)


class AuditWormSnapshotVerificationFailure(StrictVerificationModel):
    schema_version: Literal["audit_worm_snapshot_verification_failure.v2"] = (
        "audit_worm_snapshot_verification_failure.v2"
    )
    verified: Literal[False] = False
    failure_code: Literal["verification_failed"] = "verification_failed"
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False


def build_audit_signing_trust_policy_hash(policy: AuditSigningTrustPolicy) -> str:
    return _sha256_ref(_canonical_bytes(policy.model_dump(mode="json")))


def verify_audit_worm_snapshot_bundle(
    *,
    bundle_body: bytes,
    trust_policy: AuditSigningTrustPolicy,
    expected_bundle_hash: str,
    expected_trust_policy_hash: str,
    expected_tenant_id: str,
    expected_checkpoint_id: str | None = None,
) -> AuditWormSnapshotVerificationReport:
    _require_expected_hash(expected_bundle_hash, code="invalid_expected_bundle_hash")
    _require_expected_hash(expected_trust_policy_hash, code="invalid_expected_trust_policy_hash")
    if not expected_tenant_id.strip():
        raise AuditWormVerificationError("missing_expected_tenant")
    if _sha256_ref(bundle_body) != expected_bundle_hash:
        raise AuditWormVerificationError("bundle_hash_mismatch")
    trust_policy_hash = build_audit_signing_trust_policy_hash(trust_policy)
    if trust_policy_hash != expected_trust_policy_hash:
        raise AuditWormVerificationError("trust_policy_hash_mismatch")
    if trust_policy.tenant_id != expected_tenant_id:
        raise AuditWormVerificationError("trust_policy_tenant_mismatch")

    try:
        bundle = AuditWormSnapshotBundle.model_validate_json(bundle_body)
    except (ValidationError, ValueError) as exc:
        raise AuditWormVerificationError("invalid_bundle") from exc
    if _canonical_bytes(bundle.model_dump(mode="json")) != bundle_body:
        raise AuditWormVerificationError("noncanonical_bundle")
    manifest = bundle.manifest
    signature = bundle.signature
    if manifest.tenant_id != expected_tenant_id:
        raise AuditWormVerificationError("bundle_tenant_mismatch")
    if expected_checkpoint_id is not None and manifest.checkpoint_id != expected_checkpoint_id:
        raise AuditWormVerificationError("checkpoint_mismatch")
    if any(event.tenant_id != expected_tenant_id for event in bundle.events):
        raise AuditWormVerificationError("event_tenant_mismatch")
    chain = verify_audit_chain(tuple(event.audit_event() for event in bundle.events))
    if not chain.ok or chain.verified_events != manifest.event_count:
        raise AuditWormVerificationError("audit_chain_invalid")

    trusted_key = trust_policy.key_for(signature.kms_key_ref)
    if trusted_key is None:
        raise AuditWormVerificationError("untrusted_signing_key")
    signed_at = _parse_utc_text(signature.signed_at_utc)
    if trusted_key.revoked:
        raise AuditWormVerificationError("revoked_signing_key")
    if signed_at < trusted_key.valid_from_utc or (
        trusted_key.valid_until_utc is not None and signed_at > trusted_key.valid_until_utc
    ):
        raise AuditWormVerificationError("signing_key_outside_validity")
    if signature.signing_algorithm not in trusted_key.allowed_signing_algorithms:
        raise AuditWormVerificationError("untrusted_signing_algorithm")
    if (
        signature.provider_profile != trusted_key.provider_profile
        or signature.provider_key_id != trusted_key.provider_key_id
        or signature.public_key_sha256 != trusted_key.public_key_sha256
    ):
        raise AuditWormVerificationError("signing_key_identity_mismatch")

    try:
        verify_offline_audit_checkpoint_signature(signature)
    except AuditOfflineSignatureVerificationError as exc:
        raise AuditWormVerificationError(exc.code) from exc
    key_ref = AuditSigningKeyReference.parse(signature.kms_key_ref)
    return AuditWormSnapshotVerificationReport(
        tenant_id=manifest.tenant_id,
        checkpoint_id=manifest.checkpoint_id,
        through_sequence_number=manifest.through_sequence_number,
        event_count=manifest.event_count,
        bundle_hash=expected_bundle_hash,
        manifest_hash=bundle.manifest_hash,
        events_hash=manifest.events_hash,
        trust_policy_id=trust_policy.policy_id,
        trust_policy_hash=trust_policy_hash,
        signing_key_ref=signature.kms_key_ref,
        signing_key_version=key_ref.key_version,
        provider_profile=signature.provider_profile,
        provider_key_id_hash=_sha256_ref(signature.provider_key_id.encode("utf-8")),
        public_key_sha256=signature.public_key_sha256,
        signature_sha256=signature.signature_sha256,
        signed_at_utc=signature.signed_at_utc,
        retain_until_utc=manifest.retain_until_utc,
    )


def _require_expected_hash(value: str, *, code: str) -> None:
    try:
        _require_sha256(value)
    except ValueError as exc:
        raise AuditWormVerificationError(code) from exc


def _parse_utc_text(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _require_utc(parsed)
    except ValueError as exc:
        raise AuditWormVerificationError("invalid_signature_timestamp") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _read_bounded(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            raise AuditWormVerificationError("input_file_invalid")
        value = path.read_bytes()
    except OSError as exc:
        raise AuditWormVerificationError("input_file_invalid") from exc
    if not value:
        raise AuditWormVerificationError("input_file_invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a Collabio audit WORM snapshot without provider access")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--trust-policy", required=True, type=Path)
    parser.add_argument("--expected-bundle-hash", required=True)
    parser.add_argument("--expected-trust-policy-hash", required=True)
    parser.add_argument("--expected-tenant-id", required=True)
    parser.add_argument("--expected-checkpoint-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        bundle_body = _read_bounded(args.bundle, maximum_bytes=MAX_AUDIT_WORM_BUNDLE_BYTES)
        policy_body = _read_bounded(
            args.trust_policy,
            maximum_bytes=MAX_AUDIT_SIGNING_TRUST_POLICY_BYTES,
        )
        policy = AuditSigningTrustPolicy.model_validate_json(policy_body)
        report = verify_audit_worm_snapshot_bundle(
            bundle_body=bundle_body,
            trust_policy=policy,
            expected_bundle_hash=args.expected_bundle_hash,
            expected_trust_policy_hash=args.expected_trust_policy_hash,
            expected_tenant_id=args.expected_tenant_id,
            expected_checkpoint_id=args.expected_checkpoint_id,
        )
    except (AuditWormVerificationError, ValidationError, ValueError):
        print(_canonical_bytes(AuditWormSnapshotVerificationFailure().model_dump(mode="json")).decode("ascii"))
        return 1
    print(_canonical_bytes(report.model_dump(mode="json")).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
