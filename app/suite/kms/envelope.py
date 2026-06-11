from __future__ import annotations

import base64
import hmac
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import (
    KmsAdapter,
    KmsKeyReferenceRequest,
    KmsKeyUse,
    KmsOperationEvidence,
    KmsRotateKeyCommand,
)
from suite.storage.content_hash import compute_content_hash

AUTH_TAG_BYTES = 32
DATA_KEY_BYTES = 32
NONCE_BYTES = 12


class EnvelopeEncryptionError(ValueError):
    pass


class EnvelopeEncryptionAlgorithm(StrEnum):
    LOCAL_DEV_HMAC_SHA256_STREAM_V1 = "local_dev_hmac_sha256_stream_v1"


class EnvelopeEncryptionRequest(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    data_class: DataClass
    kms_key_ref: str
    plaintext: bytes
    aad: dict[str, str] = Field(default_factory=dict)
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str

    @field_validator("tenant_id", "object_id", "source_version_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("plaintext")
    @classmethod
    def require_plaintext(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("plaintext must not be empty")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class EnvelopeEncryptionManifest(BaseModel):
    schema_version: str = "envelope_encryption_manifest.v1"
    tenant_id: str
    object_id: str
    source_version_id: str
    data_class: DataClass
    kms_key_ref: str
    algorithm: EnvelopeEncryptionAlgorithm
    key_wrap_algorithm: str = "local_dev_kms_ref_wrap_v1"
    nonce_b64: str
    aad_hash: str
    plaintext_hash: str
    ciphertext_hash: str
    ciphertext_byte_length: int = Field(ge=1)
    wrapped_data_key_b64: str
    wrapped_data_key_hash: str
    kms_evidence_hash: str
    encrypted_at_utc: str
    previous_manifest_hash: str | None = None
    previous_kms_key_ref: str | None = None
    rotation_evidence_hash: str | None = None
    rotated_at_utc: str | None = None
    rotation_reason: str | None = None
    requested_by: str
    audit_chain_ref: str
    manifest_hash: str

    @field_validator(
        "tenant_id",
        "object_id",
        "source_version_id",
        "kms_key_ref",
        "key_wrap_algorithm",
        "nonce_b64",
        "wrapped_data_key_b64",
        "requested_by",
        "audit_chain_ref",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("previous_manifest_hash", "previous_kms_key_ref", "rotation_evidence_hash", "rotation_reason")
    @classmethod
    def require_optional_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("encrypted_at_utc", "rotated_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _require_utc_timestamp(value)

    @model_validator(mode="after")
    def forbid_raw_key_material(self) -> Self:
        payload = self.model_dump(mode="json")
        forbidden_fields = {"data_key", "raw_key", "plaintext_key", "key_material"}
        if forbidden_fields & set(payload):
            raise ValueError("envelope manifest must not expose raw key material")
        return self


class EnvelopeEncryptedPayload(BaseModel):
    ciphertext: bytes
    manifest: EnvelopeEncryptionManifest
    kms_evidence: KmsOperationEvidence


class EnvelopeDecryptionRequest(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    data_class: DataClass
    kms_key_ref: str
    ciphertext: bytes
    manifest: EnvelopeEncryptionManifest
    aad: dict[str, str] = Field(default_factory=dict)
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str

    @field_validator("tenant_id", "object_id", "source_version_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("ciphertext")
    @classmethod
    def require_ciphertext(cls, value: bytes) -> bytes:
        if len(value) <= AUTH_TAG_BYTES:
            raise ValueError("ciphertext must include encrypted bytes and auth tag")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class EnvelopeDecryptionResult(BaseModel):
    plaintext: bytes
    plaintext_hash: str
    manifest_hash: str
    verified: bool = True
    kms_evidence: KmsOperationEvidence


class EnvelopeRewrapRequest(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    data_class: DataClass
    ciphertext: bytes
    manifest: EnvelopeEncryptionManifest
    aad: dict[str, str] = Field(default_factory=dict)
    current_kms_key_ref: str
    new_kms_key_ref: str
    requested_by: str
    approved_by: str
    audit_chain_ref: str
    occurred_at_utc: str
    reason: str

    @field_validator(
        "tenant_id",
        "object_id",
        "source_version_id",
        "current_kms_key_ref",
        "new_kms_key_ref",
        "requested_by",
        "approved_by",
        "reason",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("ciphertext")
    @classmethod
    def require_ciphertext(cls, value: bytes) -> bytes:
        if len(value) <= AUTH_TAG_BYTES:
            raise ValueError("ciphertext must include encrypted bytes and auth tag")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class EnvelopeRewrapResult(BaseModel):
    manifest: EnvelopeEncryptionManifest
    previous_manifest_hash: str
    previous_kms_key_ref: str
    new_kms_key_ref: str
    kms_rotation_evidence: KmsOperationEvidence
    verified: bool = True


class EnvelopeEncryptionService(Protocol):
    def encrypt(self, request: EnvelopeEncryptionRequest) -> EnvelopeEncryptedPayload: ...

    def decrypt(self, request: EnvelopeDecryptionRequest) -> EnvelopeDecryptionResult: ...

    def rewrap(self, request: EnvelopeRewrapRequest) -> EnvelopeRewrapResult: ...


class LocalEnvelopeEncryptionService:
    def __init__(
        self,
        kms_adapter: KmsAdapter,
        *,
        provider_secret: bytes = b"collabio-local-dev-envelope-provider-secret-v1",
        data_key_generator: Callable[[int], bytes] = secrets.token_bytes,
        nonce_generator: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self.kms_adapter = kms_adapter
        self.provider_secret = provider_secret
        self.data_key_generator = data_key_generator
        self.nonce_generator = nonce_generator

    def encrypt(self, request: EnvelopeEncryptionRequest) -> EnvelopeEncryptedPayload:
        kms_evidence = self.kms_adapter.validate_key_reference(
            KmsKeyReferenceRequest(
                tenant_id=request.tenant_id,
                data_class=request.data_class,
                kms_key_ref=request.kms_key_ref,
                requested_by=request.requested_by,
                audit_chain_ref=request.audit_chain_ref,
                occurred_at_utc=request.occurred_at_utc,
                key_use=KmsKeyUse.ENVELOPE_ENCRYPTION_PREP,
                object_id=request.object_id,
                source_version_id=request.source_version_id,
            )
        )
        data_key = self._generate_bytes(self.data_key_generator, DATA_KEY_BYTES, "data key")
        nonce = self._generate_bytes(self.nonce_generator, NONCE_BYTES, "nonce")
        aad_bytes = canonical_envelope_aad_bytes(
            tenant_id=request.tenant_id,
            object_id=request.object_id,
            source_version_id=request.source_version_id,
            data_class=request.data_class,
            aad=request.aad,
        )
        encrypted_body = _xor_bytes(
            request.plaintext,
            _keystream(data_key=data_key, nonce=nonce, aad_bytes=aad_bytes, size=len(request.plaintext)),
        )
        tag = _auth_tag(data_key=data_key, nonce=nonce, aad_bytes=aad_bytes, ciphertext_body=encrypted_body)
        ciphertext = encrypted_body + tag
        wrapped_data_key = self._wrap_data_key(data_key, request.kms_key_ref)
        draft = EnvelopeEncryptionManifest(
            tenant_id=request.tenant_id,
            object_id=request.object_id,
            source_version_id=request.source_version_id,
            data_class=request.data_class,
            kms_key_ref=request.kms_key_ref,
            algorithm=EnvelopeEncryptionAlgorithm.LOCAL_DEV_HMAC_SHA256_STREAM_V1,
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            aad_hash=compute_content_hash(aad_bytes),
            plaintext_hash=compute_content_hash(request.plaintext),
            ciphertext_hash=compute_content_hash(ciphertext),
            ciphertext_byte_length=len(ciphertext),
            wrapped_data_key_b64=base64.b64encode(wrapped_data_key).decode("ascii"),
            wrapped_data_key_hash=compute_content_hash(wrapped_data_key),
            kms_evidence_hash=kms_evidence.evidence_hash,
            encrypted_at_utc=request.occurred_at_utc,
            requested_by=request.requested_by,
            audit_chain_ref=request.audit_chain_ref,
            manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )
        manifest = draft.model_copy(update={"manifest_hash": build_envelope_encryption_manifest_hash(draft)})
        return EnvelopeEncryptedPayload(ciphertext=ciphertext, manifest=manifest, kms_evidence=kms_evidence)

    def decrypt(self, request: EnvelopeDecryptionRequest) -> EnvelopeDecryptionResult:
        _require_manifest_hash_match(request.manifest)
        _require_request_matches_manifest(request)
        aad_bytes = canonical_envelope_aad_bytes(
            tenant_id=request.tenant_id,
            object_id=request.object_id,
            source_version_id=request.source_version_id,
            data_class=request.data_class,
            aad=request.aad,
        )
        if compute_content_hash(aad_bytes) != request.manifest.aad_hash:
            raise EnvelopeEncryptionError("AAD hash does not match envelope manifest")
        if compute_content_hash(request.ciphertext) != request.manifest.ciphertext_hash:
            raise EnvelopeEncryptionError("ciphertext hash does not match envelope manifest")
        _require_wrapped_data_key_hash_match(request.manifest)

        kms_evidence = self.kms_adapter.validate_key_reference(
            KmsKeyReferenceRequest(
                tenant_id=request.tenant_id,
                data_class=request.data_class,
                kms_key_ref=request.kms_key_ref,
                requested_by=request.requested_by,
                audit_chain_ref=request.audit_chain_ref,
                occurred_at_utc=request.occurred_at_utc,
                key_use=KmsKeyUse.ENVELOPE_DECRYPTION,
                object_id=request.object_id,
                source_version_id=request.source_version_id,
            )
        )
        data_key = self._unwrap_data_key(base64.b64decode(request.manifest.wrapped_data_key_b64), request.kms_key_ref)
        ciphertext_body = request.ciphertext[:-AUTH_TAG_BYTES]
        supplied_tag = request.ciphertext[-AUTH_TAG_BYTES:]
        expected_tag = _auth_tag(
            data_key=data_key,
            nonce=base64.b64decode(request.manifest.nonce_b64),
            aad_bytes=aad_bytes,
            ciphertext_body=ciphertext_body,
        )
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise EnvelopeEncryptionError("ciphertext authentication failed")

        plaintext = _xor_bytes(
            ciphertext_body,
            _keystream(
                data_key=data_key,
                nonce=base64.b64decode(request.manifest.nonce_b64),
                aad_bytes=aad_bytes,
                size=len(ciphertext_body),
            ),
        )
        plaintext_hash = compute_content_hash(plaintext)
        if plaintext_hash != request.manifest.plaintext_hash:
            raise EnvelopeEncryptionError("plaintext hash does not match envelope manifest")

        return EnvelopeDecryptionResult(
            plaintext=plaintext,
            plaintext_hash=plaintext_hash,
            manifest_hash=request.manifest.manifest_hash,
            kms_evidence=kms_evidence,
        )

    def rewrap(self, request: EnvelopeRewrapRequest) -> EnvelopeRewrapResult:
        _require_manifest_hash_match(request.manifest)
        _require_rewrap_request_matches_manifest(request)
        aad_bytes = canonical_envelope_aad_bytes(
            tenant_id=request.tenant_id,
            object_id=request.object_id,
            source_version_id=request.source_version_id,
            data_class=request.data_class,
            aad=request.aad,
        )
        if compute_content_hash(aad_bytes) != request.manifest.aad_hash:
            raise EnvelopeEncryptionError("AAD hash does not match envelope manifest")
        if compute_content_hash(request.ciphertext) != request.manifest.ciphertext_hash:
            raise EnvelopeEncryptionError("ciphertext hash does not match envelope manifest")
        _require_wrapped_data_key_hash_match(request.manifest)

        self.kms_adapter.validate_key_reference(
            KmsKeyReferenceRequest(
                tenant_id=request.tenant_id,
                data_class=request.data_class,
                kms_key_ref=request.current_kms_key_ref,
                requested_by=request.requested_by,
                audit_chain_ref=request.audit_chain_ref,
                occurred_at_utc=request.occurred_at_utc,
                key_use=KmsKeyUse.ENVELOPE_DECRYPTION,
                object_id=request.object_id,
                source_version_id=request.source_version_id,
            )
        )
        data_key = self._unwrap_authenticated_data_key(
            ciphertext=request.ciphertext,
            manifest=request.manifest,
            aad_bytes=aad_bytes,
            kms_key_ref=request.current_kms_key_ref,
        )
        rotation = self.kms_adapter.rotate_key_reference(
            KmsRotateKeyCommand(
                tenant_id=request.tenant_id,
                data_class=request.data_class,
                current_kms_key_ref=request.current_kms_key_ref,
                requested_by=request.requested_by,
                approved_by=request.approved_by,
                audit_chain_ref=request.audit_chain_ref,
                occurred_at_utc=request.occurred_at_utc,
                reason=request.reason,
            )
        )
        if rotation.new_kms_key_ref != request.new_kms_key_ref:
            raise EnvelopeEncryptionError("rotation result does not match requested new_kms_key_ref")

        wrapped_data_key = self._wrap_data_key(data_key, rotation.new_kms_key_ref)
        draft = request.manifest.model_copy(
            update={
                "kms_key_ref": rotation.new_kms_key_ref,
                "wrapped_data_key_b64": base64.b64encode(wrapped_data_key).decode("ascii"),
                "wrapped_data_key_hash": compute_content_hash(wrapped_data_key),
                "kms_evidence_hash": rotation.evidence.evidence_hash,
                "previous_manifest_hash": request.manifest.manifest_hash,
                "previous_kms_key_ref": rotation.previous_kms_key_ref,
                "rotation_evidence_hash": rotation.evidence.evidence_hash,
                "rotated_at_utc": request.occurred_at_utc,
                "rotation_reason": request.reason,
                "requested_by": request.requested_by,
                "audit_chain_ref": request.audit_chain_ref,
                "manifest_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            }
        )
        manifest = draft.model_copy(update={"manifest_hash": build_envelope_encryption_manifest_hash(draft)})
        return EnvelopeRewrapResult(
            manifest=manifest,
            previous_manifest_hash=request.manifest.manifest_hash,
            previous_kms_key_ref=rotation.previous_kms_key_ref,
            new_kms_key_ref=rotation.new_kms_key_ref,
            kms_rotation_evidence=rotation.evidence,
        )

    def _wrap_data_key(self, data_key: bytes, kms_key_ref: str) -> bytes:
        return _xor_bytes(data_key, _wrap_stream(self.provider_secret, kms_key_ref, len(data_key)))

    def _unwrap_data_key(self, wrapped_data_key: bytes, kms_key_ref: str) -> bytes:
        return _xor_bytes(wrapped_data_key, _wrap_stream(self.provider_secret, kms_key_ref, len(wrapped_data_key)))

    def _unwrap_authenticated_data_key(
        self,
        *,
        ciphertext: bytes,
        manifest: EnvelopeEncryptionManifest,
        aad_bytes: bytes,
        kms_key_ref: str,
    ) -> bytes:
        data_key = self._unwrap_data_key(base64.b64decode(manifest.wrapped_data_key_b64), kms_key_ref)
        ciphertext_body = ciphertext[:-AUTH_TAG_BYTES]
        supplied_tag = ciphertext[-AUTH_TAG_BYTES:]
        expected_tag = _auth_tag(
            data_key=data_key,
            nonce=base64.b64decode(manifest.nonce_b64),
            aad_bytes=aad_bytes,
            ciphertext_body=ciphertext_body,
        )
        if not hmac.compare_digest(supplied_tag, expected_tag):
            raise EnvelopeEncryptionError("ciphertext authentication failed")
        return data_key

    def _generate_bytes(self, generator: Callable[[int], bytes], size: int, label: str) -> bytes:
        value = generator(size)
        if len(value) != size:
            raise EnvelopeEncryptionError(f"{label} generator returned {len(value)} bytes, expected {size}")
        return value


def envelope_encryption_manifest_payload(manifest: EnvelopeEncryptionManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json", exclude={"manifest_hash"})


def build_envelope_encryption_manifest_hash(manifest: EnvelopeEncryptionManifest) -> str:
    manifest_bytes = json.dumps(
        envelope_encryption_manifest_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(manifest_bytes)


def canonical_envelope_aad_bytes(
    *,
    tenant_id: str,
    object_id: str,
    source_version_id: str,
    data_class: DataClass,
    aad: dict[str, str],
) -> bytes:
    payload = {
        "aad": aad,
        "data_class": data_class.value,
        "object_id": object_id,
        "source_version_id": source_version_id,
        "tenant_id": tenant_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_manifest_hash_match(manifest: EnvelopeEncryptionManifest) -> None:
    expected_hash = build_envelope_encryption_manifest_hash(manifest)
    if manifest.manifest_hash != expected_hash:
        raise EnvelopeEncryptionError("envelope manifest_hash does not match manifest payload")


def _require_wrapped_data_key_hash_match(manifest: EnvelopeEncryptionManifest) -> None:
    wrapped_data_key = base64.b64decode(manifest.wrapped_data_key_b64)
    if compute_content_hash(wrapped_data_key) != manifest.wrapped_data_key_hash:
        raise EnvelopeEncryptionError("wrapped data key hash does not match envelope manifest")


def _require_request_matches_manifest(request: EnvelopeDecryptionRequest) -> None:
    expected_values = {
        "tenant_id": request.manifest.tenant_id,
        "object_id": request.manifest.object_id,
        "source_version_id": request.manifest.source_version_id,
        "data_class": request.manifest.data_class,
        "kms_key_ref": request.manifest.kms_key_ref,
        "ciphertext_byte_length": request.manifest.ciphertext_byte_length,
    }
    actual_values = {
        "tenant_id": request.tenant_id,
        "object_id": request.object_id,
        "source_version_id": request.source_version_id,
        "data_class": request.data_class,
        "kms_key_ref": request.kms_key_ref,
        "ciphertext_byte_length": len(request.ciphertext),
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise EnvelopeEncryptionError(f"decrypt request does not match envelope manifest: {', '.join(mismatches)}")


def _require_rewrap_request_matches_manifest(request: EnvelopeRewrapRequest) -> None:
    expected_values = {
        "tenant_id": request.manifest.tenant_id,
        "object_id": request.manifest.object_id,
        "source_version_id": request.manifest.source_version_id,
        "data_class": request.manifest.data_class,
        "current_kms_key_ref": request.manifest.kms_key_ref,
        "ciphertext_byte_length": request.manifest.ciphertext_byte_length,
    }
    actual_values = {
        "tenant_id": request.tenant_id,
        "object_id": request.object_id,
        "source_version_id": request.source_version_id,
        "data_class": request.data_class,
        "current_kms_key_ref": request.current_kms_key_ref,
        "ciphertext_byte_length": len(request.ciphertext),
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise EnvelopeEncryptionError(f"rewrap request does not match envelope manifest: {', '.join(mismatches)}")


def _keystream(*, data_key: bytes, nonce: bytes, aad_bytes: bytes, size: int) -> bytes:
    output = bytearray()
    counter = 0
    aad_hash = sha256(aad_bytes).digest()
    while len(output) < size:
        block = hmac.new(
            data_key,
            b"enc" + nonce + aad_hash + counter.to_bytes(8, "big"),
            sha256,
        ).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:size])


def _auth_tag(*, data_key: bytes, nonce: bytes, aad_bytes: bytes, ciphertext_body: bytes) -> bytes:
    return hmac.new(data_key, b"tag" + nonce + aad_bytes + ciphertext_body, sha256).digest()


def _wrap_stream(provider_secret: bytes, kms_key_ref: str, size: int) -> bytes:
    wrapping_key = hmac.new(provider_secret, f"wrap:{kms_key_ref}".encode(), sha256).digest()
    output = bytearray()
    counter = 0
    while len(output) < size:
        output.extend(hmac.new(wrapping_key, counter.to_bytes(8, "big"), sha256).digest())
        counter += 1
    return bytes(output[:size])


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    if len(left) != len(right):
        raise EnvelopeEncryptionError("xor inputs must have the same length")
    return bytes(left_byte ^ right_byte for left_byte, right_byte in zip(left, right, strict=True))


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized
