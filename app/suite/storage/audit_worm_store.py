from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import quote

from pydantic import BaseModel, field_validator, model_validator

from suite.storage.s3_sdk_client import S3SdkClient, S3SdkStreamingBody


class AuditWormStorageError(RuntimeError):
    pass


class AuditWormObjectWriteRequest(BaseModel):
    tenant_id: str
    checkpoint_id: str
    bucket_id: str = "evidence-records"
    object_key: str
    bundle_hash: str
    manifest_hash: str
    signature_hash: str
    retain_until_utc: str
    legal_hold_enabled: bool = False
    storage_kms_key_ref: str

    @field_validator("tenant_id", "checkpoint_id", "bucket_id", "object_key", "storage_kms_key_ref")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("bundle_hash", "manifest_hash", "signature_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 71 or not normalized.startswith("sha256:"):
            raise ValueError("field must be a sha256 reference")
        try:
            bytes.fromhex(normalized.removeprefix("sha256:"))
        except ValueError as exc:
            raise ValueError("field must be a sha256 reference") from exc
        return normalized

    @field_validator("retain_until_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        _parse_utc(value)
        return value.strip()


class AuditWormObjectReceipt(BaseModel):
    schema_version: str = "audit_worm_object_receipt.v2"
    tenant_id: str
    checkpoint_id: str
    storage_provider: str
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_uri: str
    bundle_hash: str
    object_lock_mode: str
    object_lock_retain_until_utc: str
    legal_hold_enabled: bool
    server_side_encryption: str
    storage_kms_key_ref: str
    provider_storage_key_id: str
    put_request_id: str
    get_request_id: str
    head_request_id: str
    readback_verified: bool
    object_lock_verified: bool
    encryption_verified: bool

    @field_validator(
        "tenant_id",
        "checkpoint_id",
        "storage_provider",
        "bucket_id",
        "object_key",
        "object_version_id",
        "storage_uri",
        "storage_kms_key_ref",
        "provider_storage_key_id",
        "put_request_id",
        "get_request_id",
        "head_request_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("bundle_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 71 or not normalized.startswith("sha256:"):
            raise ValueError("bundle_hash must be a sha256 reference")
        try:
            bytes.fromhex(normalized.removeprefix("sha256:"))
        except ValueError as exc:
            raise ValueError("bundle_hash must be a sha256 reference") from exc
        return normalized

    @field_validator("object_lock_retain_until_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        _parse_utc(value)
        return value.strip()

    @model_validator(mode="after")
    def require_verified_controls(self) -> AuditWormObjectReceipt:
        if self.object_lock_mode != "compliance":
            raise ValueError("audit WORM objects must use compliance mode")
        if self.server_side_encryption != "aws:kms":
            raise ValueError("audit WORM objects must use provider KMS encryption")
        if not self.readback_verified:
            raise ValueError("audit WORM object readback must be verified")
        if not self.object_lock_verified:
            raise ValueError("audit WORM Object Lock controls must be verified")
        if not self.encryption_verified:
            raise ValueError("audit WORM object encryption must be verified")
        return self


class AuditWormObjectStore(Protocol):
    def put_verified(
        self,
        *,
        request: AuditWormObjectWriteRequest,
        body: bytes,
    ) -> AuditWormObjectReceipt: ...


class Boto3AuditWormObjectStore:
    def __init__(
        self,
        *,
        sdk_client: S3SdkClient,
        provider_storage_key_id: str,
        storage_provider: str = "aws-s3",
    ) -> None:
        if not provider_storage_key_id.strip():
            raise AuditWormStorageError("provider_storage_key_id must not be empty")
        if not storage_provider.strip():
            raise AuditWormStorageError("storage_provider must not be empty")
        self.sdk_client = sdk_client
        self.provider_storage_key_id = provider_storage_key_id.strip()
        self.storage_provider = storage_provider.strip()

    def put_verified(
        self,
        *,
        request: AuditWormObjectWriteRequest,
        body: bytes,
    ) -> AuditWormObjectReceipt:
        if _sha256_ref(body) != request.bundle_hash:
            raise AuditWormStorageError("audit WORM bundle hash does not match body")
        self._require_bucket_controls(bucket_id=request.bucket_id)

        retain_until = _parse_utc(request.retain_until_utc)
        metadata = {
            "collabio-schema-version": "audit-worm-snapshot-bundle-v2",
            "collabio-tenant-sha256": _sha256_ref(request.tenant_id.encode("utf-8")).removeprefix("sha256:"),
            "collabio-checkpoint-id": request.checkpoint_id,
            "collabio-bundle-sha256": request.bundle_hash.removeprefix("sha256:"),
            "collabio-manifest-sha256": request.manifest_hash.removeprefix("sha256:"),
            "collabio-signature-sha256": request.signature_hash.removeprefix("sha256:"),
            "collabio-storage-kms-ref-sha256": _sha256_ref(request.storage_kms_key_ref.encode("utf-8")).removeprefix(
                "sha256:"
            ),
        }
        put_response = self._call(
            "put_object",
            lambda: self.sdk_client.put_object(
                Bucket=request.bucket_id,
                Key=request.object_key,
                Body=body,
                ContentType="application/vnd.collabio.audit-worm-snapshot+json",
                Metadata=metadata,
                ChecksumSHA256=base64.b64encode(sha256(body).digest()).decode("ascii"),
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retain_until,
                ObjectLockLegalHoldStatus="ON" if request.legal_hold_enabled else "OFF",
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.provider_storage_key_id,
            ),
        )
        version_id = str(put_response.get("VersionId", "")).strip()
        if not version_id:
            raise AuditWormStorageError("audit WORM object write did not return a version ID")

        get_response = self._call(
            "get_object",
            lambda: self.sdk_client.get_object(
                Bucket=request.bucket_id,
                Key=request.object_key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            ),
        )
        readback = _body_to_bytes(get_response.get("Body"))
        if _sha256_ref(readback) != request.bundle_hash:
            raise AuditWormStorageError("audit WORM object readback hash mismatch")

        head_response = self._call(
            "head_object",
            lambda: self.sdk_client.head_object(
                Bucket=request.bucket_id,
                Key=request.object_key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            ),
        )
        observed_metadata = head_response.get("Metadata")
        if (
            not isinstance(observed_metadata, Mapping)
            or {str(key): str(value) for key, value in observed_metadata.items()} != metadata
        ):
            raise AuditWormStorageError("audit WORM object metadata verification failed")
        observed_mode = str(head_response.get("ObjectLockMode", "")).strip().lower()
        observed_retain_until = _parse_utc(str(head_response.get("ObjectLockRetainUntilDate", "")))
        observed_legal_hold = str(head_response.get("ObjectLockLegalHoldStatus", "")).strip().upper() == "ON"
        if observed_mode != "compliance" or observed_retain_until < retain_until:
            raise AuditWormStorageError("audit WORM Object Lock verification failed")
        if observed_legal_hold != request.legal_hold_enabled:
            raise AuditWormStorageError("audit WORM legal-hold verification failed")

        observed_sse = str(head_response.get("ServerSideEncryption", "")).strip()
        observed_storage_key_id = str(head_response.get("SSEKMSKeyId", "")).strip()
        if observed_sse != "aws:kms" or observed_storage_key_id != self.provider_storage_key_id:
            raise AuditWormStorageError("audit WORM provider KMS encryption verification failed")

        return AuditWormObjectReceipt(
            tenant_id=request.tenant_id,
            checkpoint_id=request.checkpoint_id,
            storage_provider=self.storage_provider,
            bucket_id=request.bucket_id,
            object_key=request.object_key,
            object_version_id=version_id,
            storage_uri=(
                f"s3://{request.bucket_id}/{quote(request.object_key, safe='/')}?versionId={quote(version_id, safe='')}"
            ),
            bundle_hash=request.bundle_hash,
            object_lock_mode=observed_mode,
            object_lock_retain_until_utc=_utc_text(observed_retain_until),
            legal_hold_enabled=observed_legal_hold,
            server_side_encryption=observed_sse,
            storage_kms_key_ref=request.storage_kms_key_ref,
            provider_storage_key_id=observed_storage_key_id,
            put_request_id=_request_id(put_response),
            get_request_id=_request_id(get_response),
            head_request_id=_request_id(head_response),
            readback_verified=True,
            object_lock_verified=True,
            encryption_verified=True,
        )

    def _require_bucket_controls(self, *, bucket_id: str) -> None:
        versioning = self._call(
            "get_bucket_versioning",
            lambda: self.sdk_client.get_bucket_versioning(Bucket=bucket_id),
        )
        if versioning.get("Status") != "Enabled":
            raise AuditWormStorageError("audit WORM bucket versioning must be enabled")
        lock_config = self._call(
            "get_object_lock_configuration",
            lambda: self.sdk_client.get_object_lock_configuration(Bucket=bucket_id),
        )
        object_lock = lock_config.get("ObjectLockConfiguration")
        if not isinstance(object_lock, Mapping) or object_lock.get("ObjectLockEnabled") != "Enabled":
            raise AuditWormStorageError("audit WORM bucket Object Lock must be enabled")

    def _call(self, operation: str, action: Any) -> Mapping[str, Any]:
        try:
            response = action()
        except Exception as exc:
            raise AuditWormStorageError(f"S3 audit WORM operation failed: {operation}") from exc
        if not isinstance(response, Mapping):
            raise AuditWormStorageError(f"S3 audit WORM operation returned invalid data: {operation}")
        return response


def _body_to_bytes(body: object) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, S3SdkStreamingBody):
        content = body.read()
        if isinstance(content, bytes):
            return content
    raise AuditWormStorageError("audit WORM object body is not readable bytes")


def _request_id(response: Mapping[str, Any]) -> str:
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, Mapping):
        raise AuditWormStorageError("S3 response did not include response metadata")
    request_id = str(metadata.get("RequestId", "")).strip()
    if not request_id:
        raise AuditWormStorageError("S3 response did not include a request ID")
    return request_id


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
