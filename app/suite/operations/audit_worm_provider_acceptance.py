from __future__ import annotations

import argparse
import importlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol, Self, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from suite.kms.openbao_transit import OpenBaoTransitHttpClient, OpenBaoTransitSigningKeyInspector
from suite.kms.signing import AuditSigningKeyReference, AuditSigningProviderInspector
from suite.operations.audit_worm_snapshot import AuditSnapshotEvent, AuditWormSnapshotBundle
from suite.operations.audit_worm_verify import (
    AuditSigningTrustPolicy,
    AuditWormSnapshotVerificationReport,
    AuditWormVerificationError,
    build_audit_signing_trust_policy_hash,
    verify_audit_worm_snapshot_bundle,
)
from suite.operations.postgres_restore_drill import (
    PostgresRestoreDrillReport,
    build_postgres_restore_drill_report_hash,
)
from suite.storage.audit_worm_store import AuditWormObjectReceipt
from suite.storage.s3_sdk_client import S3SdkStreamingBody

MAX_POLICY_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_RESTORE_REPORT_BYTES = 4 * 1024 * 1024
MAX_TRUST_POLICY_BYTES = 1024 * 1024
EXECUTION_CONFIRMATION = "I_APPROVE_EXACT_VERSION_DELETE_DENIAL_PROBE"
ACCEPTANCE_CHECKS = (
    "pinned_acceptance_policy",
    "synthetic_tenant_scope",
    "dedicated_bucket_and_prefix",
    "short_active_compliance_retention",
    "legal_hold_off",
    "s3_sse_kms_encryption",
    "versioned_asymmetric_sign_verify_key",
    "exact_version_readback",
    "offline_signature_verification",
    "isolated_postgres_restore",
    "exact_version_delete_denied",
    "post_denial_exact_version_readback",
)


class AuditWormProviderAcceptanceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StrictAcceptanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if len(value) != 71 or not value.startswith("sha256:") or value != value.lower():
        raise ValueError("value must be a lowercase sha256 reference")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except ValueError as exc:
        raise ValueError("value must be a lowercase sha256 reference") from exc
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value.astimezone(UTC)


class AuditWormProviderAcceptancePolicy(StrictAcceptanceModel):
    schema_version: Literal["audit_worm_provider_acceptance_policy.v2"] = "audit_worm_provider_acceptance_policy.v2"
    policy_id: str = Field(min_length=1, max_length=128)
    tenant_id_sha256: str
    synthetic_principal_id_sha256: str
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    s3_signing_region: str = Field(min_length=1, max_length=64)
    object_store_endpoint_sha256: str
    signing_provider_endpoint_sha256: str
    bucket_id: str = Field(min_length=3, max_length=255)
    object_key_prefix: str = Field(min_length=1, max_length=512)
    signing_provider_key_id_sha256: str
    storage_provider_key_id_sha256: str
    expected_bundle_hash: str
    receipt_hash: str
    trust_policy_hash: str
    restore_report_hash: str
    minimum_retention_hours: int = Field(ge=1, le=168)
    maximum_retention_hours: int = Field(ge=1, le=168)
    valid_from_utc: datetime
    valid_until_utc: datetime
    provider_calls_authorized: Literal[True]
    exact_version_delete_denial_probe_authorized: Literal[True]
    synthetic_non_content_tenant_required: Literal[True]
    legal_hold_required_off: Literal[True]

    _validate_hashes = field_validator(
        "tenant_id_sha256",
        "synthetic_principal_id_sha256",
        "object_store_endpoint_sha256",
        "signing_provider_endpoint_sha256",
        "signing_provider_key_id_sha256",
        "storage_provider_key_id_sha256",
        "expected_bundle_hash",
        "receipt_hash",
        "trust_policy_hash",
        "restore_report_hash",
    )(_require_sha256)
    _validate_valid_from = field_validator("valid_from_utc")(_require_utc)
    _validate_valid_until = field_validator("valid_until_utc")(_require_utc)

    @model_validator(mode="after")
    def require_bounded_scope(self) -> Self:
        if self.maximum_retention_hours < self.minimum_retention_hours:
            raise ValueError("maximum retention must not be shorter than minimum retention")
        if self.valid_until_utc <= self.valid_from_utc:
            raise ValueError("acceptance policy validity window is invalid")
        if self.valid_until_utc - self.valid_from_utc > timedelta(days=7):
            raise ValueError("acceptance policy validity must not exceed seven days")
        if self.object_key_prefix.startswith("/") or not self.object_key_prefix.endswith("/"):
            raise ValueError("object_key_prefix must be relative and end with a slash")
        if ".." in self.object_key_prefix.split("/"):
            raise ValueError("object_key_prefix must not traverse paths")
        return self


class AuditWormLiveInspection(StrictAcceptanceModel):
    exact_version_readback_verified: Literal[True] = True
    object_lock_mode: Literal["compliance"] = "compliance"
    retain_until_utc: datetime
    legal_hold_enabled: Literal[False] = False
    server_side_encryption: Literal["aws:kms"] = "aws:kms"
    storage_provider_key_id_sha256: str
    signing_provider_key_id_sha256: str
    signing_public_key_sha256: str
    signing_key_usage: Literal["sign-verify"] = "sign-verify"
    signing_key_type: str = Field(pattern=r"^(ecdsa-p256|rsa-(2048|3072|4096))$")
    signing_key_version: int = Field(ge=1)
    initial_get_request_id_sha256: str
    head_request_id_sha256: str
    signing_key_inspection_request_id_sha256: str

    _validate_hashes = field_validator(
        "storage_provider_key_id_sha256",
        "signing_provider_key_id_sha256",
        "signing_public_key_sha256",
        "initial_get_request_id_sha256",
        "head_request_id_sha256",
        "signing_key_inspection_request_id_sha256",
    )(_require_sha256)
    _validate_retain_until = field_validator("retain_until_utc")(_require_utc)


class AuditWormDeleteDenialProof(StrictAcceptanceModel):
    exact_version_delete_denied: Literal[True] = True
    denial_status_code: Literal[403] = 403
    denial_error_code: Literal["AccessDenied"] = "AccessDenied"
    delete_request_id_sha256: str
    post_denial_readback_verified: Literal[True] = True
    post_denial_get_request_id_sha256: str

    _validate_hashes = field_validator(
        "delete_request_id_sha256",
        "post_denial_get_request_id_sha256",
    )(_require_sha256)


@dataclass(frozen=True)
class AuditWormLiveInspectionResult:
    bundle_body: bytes
    evidence: AuditWormLiveInspection


class AuditWormProviderProbe(Protocol):
    def inspect(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        signing_provider_key_id: str,
        expected_bundle_hash: str,
    ) -> AuditWormLiveInspectionResult: ...

    def prove_exact_version_delete_denied(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        expected_bundle_hash: str,
    ) -> AuditWormDeleteDenialProof: ...


class AuditWormAcceptanceS3Client(Protocol):
    def get_object(self, **kwargs: object) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: object) -> Mapping[str, Any]: ...


class S3CompatibleAuditWormProviderProbe:
    def __init__(
        self,
        *,
        s3_client: AuditWormAcceptanceS3Client,
        signing_key_inspector: AuditSigningProviderInspector,
    ) -> None:
        self.s3_client = s3_client
        self.signing_key_inspector = signing_key_inspector

    def inspect(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        signing_provider_key_id: str,
        expected_bundle_hash: str,
    ) -> AuditWormLiveInspectionResult:
        get_response = self._s3_call(
            "get_object",
            lambda: self.s3_client.get_object(
                Bucket=receipt.bucket_id,
                Key=receipt.object_key,
                VersionId=receipt.object_version_id,
                ChecksumMode="ENABLED",
            ),
        )
        bundle_body = _body_to_bytes(get_response.get("Body"))
        if _sha256_ref(bundle_body) != expected_bundle_hash:
            raise AuditWormProviderAcceptanceError("exact_version_hash_mismatch")

        head_response = self._s3_call(
            "head_object",
            lambda: self.s3_client.head_object(
                Bucket=receipt.bucket_id,
                Key=receipt.object_key,
                VersionId=receipt.object_version_id,
                ChecksumMode="ENABLED",
            ),
        )
        mode = str(head_response.get("ObjectLockMode", "")).strip().lower()
        if mode != "compliance":
            raise AuditWormProviderAcceptanceError("compliance_retention_missing")
        retain_until = _parse_utc(head_response.get("ObjectLockRetainUntilDate"))
        if str(head_response.get("ObjectLockLegalHoldStatus", "")).strip().upper() != "OFF":
            raise AuditWormProviderAcceptanceError("legal_hold_must_be_off")
        if str(head_response.get("ServerSideEncryption", "")).strip() != "aws:kms":
            raise AuditWormProviderAcceptanceError("provider_kms_encryption_missing")
        storage_key_id = str(head_response.get("SSEKMSKeyId", "")).strip()
        if not storage_key_id:
            raise AuditWormProviderAcceptanceError("storage_provider_key_missing")

        try:
            signing_key = self.signing_key_inspector.inspect_provider_key(provider_key_id=signing_provider_key_id)
        except Exception as exc:
            raise AuditWormProviderAcceptanceError("signing_key_inspection_failed") from exc
        if signing_key.provider_key_id != signing_provider_key_id:
            raise AuditWormProviderAcceptanceError("signing_provider_key_mismatch")

        return AuditWormLiveInspectionResult(
            bundle_body=bundle_body,
            evidence=AuditWormLiveInspection(
                retain_until_utc=retain_until,
                storage_provider_key_id_sha256=_sha256_ref(storage_key_id.encode("utf-8")),
                signing_provider_key_id_sha256=_sha256_ref(signing_key.provider_key_id.encode("utf-8")),
                signing_public_key_sha256=_sha256_ref(signing_key.public_key_der),
                signing_key_type=signing_key.key_type,
                signing_key_version=signing_key.key_version,
                initial_get_request_id_sha256=_request_id_hash(get_response),
                head_request_id_sha256=_request_id_hash(head_response),
                signing_key_inspection_request_id_sha256=_sha256_ref(signing_key.request_id.encode("utf-8")),
            ),
        )

    def prove_exact_version_delete_denied(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        expected_bundle_hash: str,
    ) -> AuditWormDeleteDenialProof:
        try:
            self.s3_client.delete_object(
                Bucket=receipt.bucket_id,
                Key=receipt.object_key,
                VersionId=receipt.object_version_id,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            if not isinstance(response, Mapping):
                raise AuditWormProviderAcceptanceError("delete_denial_response_missing") from exc
            error = response.get("Error")
            metadata = response.get("ResponseMetadata")
            if not isinstance(error, Mapping) or not isinstance(metadata, Mapping):
                raise AuditWormProviderAcceptanceError("delete_denial_response_invalid") from exc
            error_code = str(error.get("Code", "")).strip()
            status_code = metadata.get("HTTPStatusCode")
            if error_code != "AccessDenied" or status_code != 403:
                raise AuditWormProviderAcceptanceError("exact_version_delete_not_denied_by_retention") from exc
            delete_request_id_hash = _request_id_hash(response)
        else:
            raise AuditWormProviderAcceptanceError("protected_exact_version_was_deleted")

        get_response = self._s3_call(
            "post_denial_get_object",
            lambda: self.s3_client.get_object(
                Bucket=receipt.bucket_id,
                Key=receipt.object_key,
                VersionId=receipt.object_version_id,
                ChecksumMode="ENABLED",
            ),
        )
        if _sha256_ref(_body_to_bytes(get_response.get("Body"))) != expected_bundle_hash:
            raise AuditWormProviderAcceptanceError("post_denial_readback_hash_mismatch")
        return AuditWormDeleteDenialProof(
            delete_request_id_sha256=delete_request_id_hash,
            post_denial_get_request_id_sha256=_request_id_hash(get_response),
        )

    @staticmethod
    def _s3_call(operation: str, action: Any) -> Mapping[str, Any]:
        return _provider_call("s3", operation, action)


class AuditWormProviderAcceptanceReport(StrictAcceptanceModel):
    schema_version: Literal["audit_worm_provider_acceptance_report.v2"] = "audit_worm_provider_acceptance_report.v2"
    accepted: Literal[True] = True
    checked_at_utc: datetime
    policy_id: str
    acceptance_policy_hash: str
    tenant_id_sha256: str
    synthetic_principal_id_sha256: str
    provider_profile: Literal["self-hosted-ceph-openbao-v1"] = "self-hosted-ceph-openbao-v1"
    s3_signing_region: str
    bucket_id_sha256: str
    object_key_sha256: str
    object_version_id_sha256: str
    bundle_hash: str
    checkpoint_id_sha256: str
    trust_policy_hash: str
    restore_report_hash: str
    source_state_manifest_hash: str
    target_state_manifest_hash: str
    signing_provider_key_id_sha256: str
    storage_provider_key_id_sha256: str
    object_lock_retain_until_utc: datetime
    signing_key_inspection_request_id_sha256: str
    initial_get_request_id_sha256: str
    head_request_id_sha256: str
    delete_request_id_sha256: str
    post_denial_get_request_id_sha256: str
    verified_checks: tuple[str, ...] = ACCEPTANCE_CHECKS
    synthetic_non_content_tenant: Literal[True] = True
    content_included: Literal[False] = False
    signatures_included: Literal[False] = False
    public_keys_included: Literal[False] = False
    secrets_included: Literal[False] = False
    report_hash: str

    _validate_hashes = field_validator(
        "acceptance_policy_hash",
        "tenant_id_sha256",
        "synthetic_principal_id_sha256",
        "bucket_id_sha256",
        "object_key_sha256",
        "object_version_id_sha256",
        "bundle_hash",
        "checkpoint_id_sha256",
        "trust_policy_hash",
        "restore_report_hash",
        "source_state_manifest_hash",
        "target_state_manifest_hash",
        "signing_provider_key_id_sha256",
        "storage_provider_key_id_sha256",
        "signing_key_inspection_request_id_sha256",
        "initial_get_request_id_sha256",
        "head_request_id_sha256",
        "delete_request_id_sha256",
        "post_denial_get_request_id_sha256",
        "report_hash",
    )(_require_sha256)
    _validate_checked_at = field_validator("checked_at_utc")(_require_utc)
    _validate_retain_until = field_validator("object_lock_retain_until_utc")(_require_utc)


class AuditWormProviderAcceptanceFailure(StrictAcceptanceModel):
    schema_version: Literal["audit_worm_provider_acceptance_failure.v2"] = "audit_worm_provider_acceptance_failure.v2"
    accepted: Literal[False] = False
    failure_code: Literal["acceptance_failed"] = "acceptance_failed"
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False


def build_acceptance_policy_hash(policy: AuditWormProviderAcceptancePolicy) -> str:
    return _sha256_ref(_canonical_bytes(policy.model_dump(mode="json")))


def build_audit_worm_object_receipt_hash(receipt: AuditWormObjectReceipt) -> str:
    return _sha256_ref(_canonical_bytes(receipt.model_dump(mode="json")))


def build_acceptance_report_hash(report: AuditWormProviderAcceptanceReport) -> str:
    return _sha256_ref(_canonical_bytes(report.model_dump(mode="json", exclude={"report_hash"})))


def accept_audit_worm_provider(
    *,
    policy: AuditWormProviderAcceptancePolicy,
    expected_policy_hash: str,
    receipt: AuditWormObjectReceipt,
    restore_report: PostgresRestoreDrillReport,
    expected_restore_report_hash: str,
    trust_policy: AuditSigningTrustPolicy,
    expected_trust_policy_hash: str,
    expected_bundle_hash: str,
    expected_tenant_id: str,
    execution_confirmation: str,
    provider_probe: AuditWormProviderProbe,
    checked_at_utc: datetime | None = None,
) -> AuditWormProviderAcceptanceReport:
    checked_at = _require_utc(checked_at_utc or datetime.now(UTC))
    for value in (
        expected_policy_hash,
        expected_restore_report_hash,
        expected_trust_policy_hash,
        expected_bundle_hash,
    ):
        _require_sha256(value)
    if execution_confirmation != EXECUTION_CONFIRMATION:
        raise AuditWormProviderAcceptanceError("execution_confirmation_missing")
    if build_acceptance_policy_hash(policy) != expected_policy_hash:
        raise AuditWormProviderAcceptanceError("acceptance_policy_hash_mismatch")
    if not (policy.valid_from_utc <= checked_at <= policy.valid_until_utc):
        raise AuditWormProviderAcceptanceError("acceptance_policy_outside_validity")
    tenant_hash = _sha256_ref(expected_tenant_id.strip().encode("utf-8"))
    if (
        not expected_tenant_id.strip()
        or tenant_hash != policy.tenant_id_sha256
        or receipt.tenant_id != expected_tenant_id
    ):
        raise AuditWormProviderAcceptanceError("tenant_scope_mismatch")
    if receipt.bucket_id != policy.bucket_id or not receipt.object_key.startswith(policy.object_key_prefix):
        raise AuditWormProviderAcceptanceError("provider_object_scope_mismatch")
    if (
        receipt.bundle_hash != expected_bundle_hash
        or expected_bundle_hash != policy.expected_bundle_hash
        or build_audit_worm_object_receipt_hash(receipt) != policy.receipt_hash
    ):
        raise AuditWormProviderAcceptanceError("receipt_bundle_hash_mismatch")
    if receipt.legal_hold_enabled:
        raise AuditWormProviderAcceptanceError("legal_hold_must_be_off")
    if _sha256_ref(receipt.provider_storage_key_id.encode("utf-8")) != policy.storage_provider_key_id_sha256:
        raise AuditWormProviderAcceptanceError("storage_provider_key_mismatch")
    if (
        build_postgres_restore_drill_report_hash(restore_report) != restore_report.report_hash
        or restore_report.report_hash != expected_restore_report_hash
        or expected_restore_report_hash != policy.restore_report_hash
        or not restore_report.restore_ready
        or not restore_report.source_target_state_verified
        or restore_report.source_state_manifest_hash != restore_report.target_state_manifest_hash
        or not restore_report.append_only_audit_controls_verified
        or not restore_report.metadata_only_evidence_verified
        or restore_report.content_included
    ):
        raise AuditWormProviderAcceptanceError("restore_evidence_not_accepted")
    if (
        build_audit_signing_trust_policy_hash(trust_policy) != expected_trust_policy_hash
        or expected_trust_policy_hash != policy.trust_policy_hash
    ):
        raise AuditWormProviderAcceptanceError("trust_policy_hash_mismatch")

    signing_key = trust_policy.key_for(_signing_key_ref_from_policy(trust_policy, policy))
    if signing_key is None:
        raise AuditWormProviderAcceptanceError("signing_key_not_in_trust_policy")
    if _sha256_ref(signing_key.provider_key_id.encode("utf-8")) != policy.signing_provider_key_id_sha256:
        raise AuditWormProviderAcceptanceError("signing_provider_key_mismatch")

    inspection = provider_probe.inspect(
        receipt=receipt,
        signing_provider_key_id=signing_key.provider_key_id,
        expected_bundle_hash=expected_bundle_hash,
    )
    if (
        inspection.evidence.storage_provider_key_id_sha256 != policy.storage_provider_key_id_sha256
        or inspection.evidence.signing_provider_key_id_sha256 != policy.signing_provider_key_id_sha256
        or inspection.evidence.signing_public_key_sha256 != signing_key.public_key_sha256
        or inspection.evidence.signing_key_version
        != AuditSigningKeyReference.parse(signing_key.kms_key_ref).key_version
        or inspection.evidence.retain_until_utc != _parse_utc(receipt.object_lock_retain_until_utc)
    ):
        raise AuditWormProviderAcceptanceError("live_provider_key_mismatch")
    verification = verify_audit_worm_snapshot_bundle(
        bundle_body=inspection.bundle_body,
        trust_policy=trust_policy,
        expected_bundle_hash=expected_bundle_hash,
        expected_trust_policy_hash=expected_trust_policy_hash,
        expected_tenant_id=expected_tenant_id,
        expected_checkpoint_id=receipt.checkpoint_id,
    )
    synthetic_principal_id_sha256 = _require_synthetic_non_content_bundle(inspection.bundle_body)
    if synthetic_principal_id_sha256 != policy.synthetic_principal_id_sha256:
        raise AuditWormProviderAcceptanceError("synthetic_principal_mismatch")
    _require_short_active_retention(
        policy=policy,
        inspection=inspection.evidence,
        verification=verification,
        now=checked_at,
    )

    deletion = provider_probe.prove_exact_version_delete_denied(
        receipt=receipt,
        expected_bundle_hash=expected_bundle_hash,
    )
    draft = AuditWormProviderAcceptanceReport(
        checked_at_utc=checked_at,
        policy_id=policy.policy_id,
        acceptance_policy_hash=expected_policy_hash,
        tenant_id_sha256=tenant_hash,
        synthetic_principal_id_sha256=synthetic_principal_id_sha256,
        s3_signing_region=policy.s3_signing_region,
        bucket_id_sha256=_sha256_ref(receipt.bucket_id.encode("utf-8")),
        object_key_sha256=_sha256_ref(receipt.object_key.encode("utf-8")),
        object_version_id_sha256=_sha256_ref(receipt.object_version_id.encode("utf-8")),
        bundle_hash=expected_bundle_hash,
        checkpoint_id_sha256=_sha256_ref(receipt.checkpoint_id.encode("utf-8")),
        trust_policy_hash=expected_trust_policy_hash,
        restore_report_hash=expected_restore_report_hash,
        source_state_manifest_hash=restore_report.source_state_manifest_hash,
        target_state_manifest_hash=restore_report.target_state_manifest_hash,
        signing_provider_key_id_sha256=inspection.evidence.signing_provider_key_id_sha256,
        storage_provider_key_id_sha256=inspection.evidence.storage_provider_key_id_sha256,
        object_lock_retain_until_utc=inspection.evidence.retain_until_utc,
        signing_key_inspection_request_id_sha256=(inspection.evidence.signing_key_inspection_request_id_sha256),
        initial_get_request_id_sha256=inspection.evidence.initial_get_request_id_sha256,
        head_request_id_sha256=inspection.evidence.head_request_id_sha256,
        delete_request_id_sha256=deletion.delete_request_id_sha256,
        post_denial_get_request_id_sha256=deletion.post_denial_get_request_id_sha256,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_acceptance_report_hash(draft)})


def _signing_key_ref_from_policy(
    trust_policy: AuditSigningTrustPolicy,
    policy: AuditWormProviderAcceptancePolicy,
) -> str:
    matches = [
        key.kms_key_ref
        for key in trust_policy.trusted_keys
        if _sha256_ref(key.provider_key_id.encode("utf-8")) == policy.signing_provider_key_id_sha256
    ]
    if len(matches) != 1:
        raise AuditWormProviderAcceptanceError("signing_key_policy_binding_invalid")
    return matches[0]


def _require_short_active_retention(
    *,
    policy: AuditWormProviderAcceptancePolicy,
    inspection: AuditWormLiveInspection,
    verification: AuditWormSnapshotVerificationReport,
    now: datetime,
) -> None:
    generated_at = _parse_utc(verification.signed_at_utc)
    retain_until = inspection.retain_until_utc
    if _parse_utc(verification.retain_until_utc) != retain_until or retain_until <= now:
        raise AuditWormProviderAcceptanceError("retention_not_active_or_manifest_mismatch")
    duration = retain_until - generated_at
    if (
        not timedelta(hours=policy.minimum_retention_hours)
        <= duration
        <= timedelta(hours=policy.maximum_retention_hours)
    ):
        raise AuditWormProviderAcceptanceError("retention_outside_approved_proof_window")


def _require_synthetic_non_content_bundle(bundle_body: bytes) -> str:
    try:
        bundle = AuditWormSnapshotBundle.model_validate_json(bundle_body)
    except (ValidationError, ValueError) as exc:
        raise AuditWormProviderAcceptanceError("synthetic_bundle_invalid") from exc
    return _require_synthetic_non_content_events(
        generated_by=bundle.manifest.generated_by,
        events=bundle.events,
    )


def _require_synthetic_non_content_events(
    *,
    generated_by: str,
    events: Sequence[AuditSnapshotEvent],
) -> str:
    if len(events) != 1:
        raise AuditWormProviderAcceptanceError("synthetic_proof_requires_one_event")
    event = events[0]
    if (
        event.user_id != generated_by
        or event.event_type != "audit.worm_provider_acceptance.synthetic"
        or event.source_object_ids
        or event.input_hash is not None
        or event.output_hash is not None
        or event.model_id is not None
        or event.prompt_template_id is not None
        or event.metadata != {"purpose": "audit_worm_provider_acceptance", "synthetic": True}
    ):
        raise AuditWormProviderAcceptanceError("synthetic_non_content_scope_invalid")
    return _sha256_ref(generated_by.encode("utf-8"))


def _provider_call(provider: str, operation: str, action: Any) -> Mapping[str, Any]:
    try:
        response = action()
    except Exception as exc:
        raise AuditWormProviderAcceptanceError(f"{provider}_{operation}_failed") from exc
    if not isinstance(response, Mapping):
        raise AuditWormProviderAcceptanceError(f"{provider}_{operation}_invalid")
    return response


def _body_to_bytes(body: object) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, S3SdkStreamingBody):
        value = body.read()
        if isinstance(value, bytes):
            return value
    raise AuditWormProviderAcceptanceError("exact_version_body_invalid")


def _request_id_hash(response: Mapping[str, Any]) -> str:
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, Mapping):
        raise AuditWormProviderAcceptanceError("provider_request_id_missing")
    request_id = str(metadata.get("RequestId", "")).strip()
    if not request_id:
        raise AuditWormProviderAcceptanceError("provider_request_id_missing")
    return _sha256_ref(request_id.encode("utf-8"))


def _parse_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        return _require_utc(value)
    try:
        return _require_utc(datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")))
    except ValueError as exc:
        raise AuditWormProviderAcceptanceError("invalid_utc_timestamp") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _read_bounded(path: Path, maximum_bytes: int) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            raise AuditWormProviderAcceptanceError("input_file_invalid")
        value = path.read_bytes()
    except OSError as exc:
        raise AuditWormProviderAcceptanceError("input_file_invalid") from exc
    if not value:
        raise AuditWormProviderAcceptanceError("input_file_invalid")
    return value


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip().rstrip("/")
    if not value:
        raise AuditWormProviderAcceptanceError("provider_configuration_missing")
    return value


def _required_self_hosted_s3_origin(env: Mapping[str, str]) -> str:
    value = _required_env(env, "SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_S3_ENDPOINT_URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise AuditWormProviderAcceptanceError("object_store_endpoint_invalid")
    hostname = parsed.hostname.lower()
    if hostname.endswith(".amazonaws.com") or hostname.endswith(".amazonaws.com.cn"):
        raise AuditWormProviderAcceptanceError("object_store_must_be_self_hosted")
    return value


def _read_secret_text(path: Path) -> str:
    value = _read_bounded(path, 16_384)
    try:
        decoded = value.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AuditWormProviderAcceptanceError("provider_secret_file_invalid") from exc
    if not decoded:
        raise AuditWormProviderAcceptanceError("provider_secret_file_invalid")
    return decoded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fail-closed self-hosted audit WORM provider acceptance gate")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--expected-policy-hash", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--restore-report", required=True, type=Path)
    parser.add_argument("--expected-restore-report-hash", required=True)
    parser.add_argument("--trust-policy", required=True, type=Path)
    parser.add_argument("--expected-trust-policy-hash", required=True)
    parser.add_argument("--expected-bundle-hash", required=True)
    parser.add_argument("--expected-tenant-id", required=True)
    parser.add_argument("--execution-confirmation", required=True)
    return parser


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime_env = os.environ if env is None else env
    try:
        if runtime_env.get("SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_ENABLED", "").strip() != "1":
            raise AuditWormProviderAcceptanceError("provider_acceptance_not_enabled")
        policy = AuditWormProviderAcceptancePolicy.model_validate_json(_read_bounded(args.policy, MAX_POLICY_BYTES))
        receipt = AuditWormObjectReceipt.model_validate_json(_read_bounded(args.receipt, MAX_RECEIPT_BYTES))
        restore_report = PostgresRestoreDrillReport.model_validate_json(
            _read_bounded(args.restore_report, MAX_RESTORE_REPORT_BYTES)
        )
        trust_policy = AuditSigningTrustPolicy.model_validate_json(
            _read_bounded(args.trust_policy, MAX_TRUST_POLICY_BYTES)
        )
        object_store_endpoint = _required_self_hosted_s3_origin(runtime_env)
        signing_provider_endpoint = _required_env(
            runtime_env,
            "SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_ADDR",
        )
        if (
            _sha256_ref(object_store_endpoint.encode("utf-8")) != policy.object_store_endpoint_sha256
            or _sha256_ref(signing_provider_endpoint.encode("utf-8")) != policy.signing_provider_endpoint_sha256
        ):
            raise AuditWormProviderAcceptanceError("provider_endpoint_policy_mismatch")
        boto3_module = importlib.import_module("boto3")
        client_factory: Any = boto3_module.client
        openbao_client = OpenBaoTransitHttpClient(
            address=signing_provider_endpoint,
            token=_read_secret_text(
                Path(_required_env(runtime_env, "SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_TOKEN_FILE"))
            ),
            namespace=runtime_env.get("SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_NAMESPACE") or None,
            tls_ca_file=runtime_env.get("SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_TLS_CA_FILE") or None,
            client_cert_file=(runtime_env.get("SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_CLIENT_CERT_FILE") or None),
            client_key_file=(runtime_env.get("SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_OPENBAO_CLIENT_KEY_FILE") or None),
        )
        probe = S3CompatibleAuditWormProviderProbe(
            s3_client=cast(
                AuditWormAcceptanceS3Client,
                client_factory(
                    "s3",
                    endpoint_url=object_store_endpoint,
                    region_name=policy.s3_signing_region,
                ),
            ),
            signing_key_inspector=OpenBaoTransitSigningKeyInspector(client=openbao_client),
        )
        report = accept_audit_worm_provider(
            policy=policy,
            expected_policy_hash=args.expected_policy_hash,
            receipt=receipt,
            restore_report=restore_report,
            expected_restore_report_hash=args.expected_restore_report_hash,
            trust_policy=trust_policy,
            expected_trust_policy_hash=args.expected_trust_policy_hash,
            expected_bundle_hash=args.expected_bundle_hash,
            expected_tenant_id=args.expected_tenant_id,
            execution_confirmation=args.execution_confirmation,
            provider_probe=probe,
        )
    except (
        AuditWormProviderAcceptanceError,
        AuditWormVerificationError,
        ModuleNotFoundError,
        ValidationError,
        ValueError,
    ):
        print(_canonical_bytes(AuditWormProviderAcceptanceFailure().model_dump(mode="json")).decode("ascii"))
        return 1
    print(_canonical_bytes(report.model_dump(mode="json")).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
