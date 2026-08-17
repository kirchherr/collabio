from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.kms.adapter import KmsPolicyViolation

AUDIT_SIGNING_KEY_REF_PATTERN = re.compile(r"^kms-sign://([^/]+)/audit/v([1-9][0-9]*)$")


@dataclass(frozen=True)
class AuditSigningKeyReference:
    tenant_id: str
    key_version: int

    @property
    def canonical_ref(self) -> str:
        return f"kms-sign://{self.tenant_id}/audit/v{self.key_version}"

    @classmethod
    def parse(cls, value: str) -> AuditSigningKeyReference:
        normalized = value.strip()
        match = AUDIT_SIGNING_KEY_REF_PATTERN.fullmatch(normalized)
        if match is None:
            raise KmsPolicyViolation("audit signing key reference must be kms-sign://<tenant_id>/audit/v<version>")
        tenant_id = match.group(1).strip()
        if not tenant_id:
            raise KmsPolicyViolation("audit signing key tenant must not be empty")
        reference = cls(tenant_id=tenant_id, key_version=int(match.group(2)))
        if reference.canonical_ref != normalized:
            raise KmsPolicyViolation("audit signing key reference must be canonical")
        return reference


class AuditSigningAlgorithm(StrEnum):
    ECDSA_SHA_256 = "ecdsa-sha256"
    RSASSA_PSS_SHA_256 = "rsassa-pss-sha256"

    @property
    def aws_kms_name(self) -> str:
        return {
            AuditSigningAlgorithm.ECDSA_SHA_256: "ECDSA_SHA_256",
            AuditSigningAlgorithm.RSASSA_PSS_SHA_256: "RSASSA_PSS_SHA_256",
        }[self]


class AuditSignatureError(RuntimeError):
    pass


class AuditCheckpointSignature(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["audit_checkpoint_signature.v2"] = "audit_checkpoint_signature.v2"
    tenant_id: str
    signed_digest: str
    signing_algorithm: AuditSigningAlgorithm
    signing_message_type: str = "DIGEST"
    kms_key_ref: str
    kms_key_version: int = Field(ge=1)
    provider_profile: str
    provider_key_id: str
    public_key_der_base64: str
    public_key_sha256: str
    signature_base64: str
    signature_sha256: str
    signed_at_utc: str
    provider_sign_request_id: str
    provider_verify_request_id: str
    provider_verified: bool

    @field_validator(
        "tenant_id",
        "provider_profile",
        "provider_key_id",
        "provider_sign_request_id",
        "provider_verify_request_id",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("signed_digest", "public_key_sha256", "signature_sha256")
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

    @field_validator("public_key_der_base64", "signature_base64")
    @classmethod
    def require_canonical_base64(cls, value: str) -> str:
        normalized = value.strip()
        try:
            decoded = base64.b64decode(normalized, validate=True)
        except ValueError as exc:
            raise ValueError("field must contain canonical base64") from exc
        if not decoded or base64.b64encode(decoded).decode("ascii") != normalized:
            raise ValueError("field must contain canonical base64")
        return normalized

    @field_validator("signed_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError("signed_at_utc must be a UTC timestamp")
        return normalized

    @model_validator(mode="after")
    def require_verified_signature(self) -> AuditCheckpointSignature:
        if self.signing_message_type != "DIGEST":
            raise ValueError("audit checkpoint signatures must sign a digest")
        if not self.provider_verified:
            raise ValueError("audit checkpoint signature must be provider verified")
        key_ref = AuditSigningKeyReference.parse(self.kms_key_ref)
        if key_ref.tenant_id != self.tenant_id:
            raise ValueError("kms_key_ref tenant does not match signature tenant")
        if key_ref.key_version != self.kms_key_version:
            raise ValueError("kms key version does not match kms_key_ref")
        public_key = base64.b64decode(self.public_key_der_base64, validate=True)
        if _sha256_ref(public_key) != self.public_key_sha256:
            raise ValueError("public_key_sha256 does not match public_key_der_base64")
        signature = base64.b64decode(self.signature_base64, validate=True)
        if _sha256_ref(signature) != self.signature_sha256:
            raise ValueError("signature_sha256 does not match signature_base64")
        return self


class AuditCheckpointSigner(Protocol):
    def sign_digest(
        self,
        *,
        tenant_id: str,
        digest: bytes,
        signed_at_utc: str,
    ) -> AuditCheckpointSignature: ...


class AwsKmsSigningClient(Protocol):
    def describe_key(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_public_key(self, **kwargs: object) -> Mapping[str, Any]: ...

    def sign(self, **kwargs: object) -> Mapping[str, Any]: ...

    def verify(self, **kwargs: object) -> Mapping[str, Any]: ...


class AwsKmsAuditCheckpointSigner:
    def __init__(
        self,
        *,
        sdk_client: AwsKmsSigningClient,
        kms_key_ref: str,
        provider_key_id: str,
        signing_algorithm: AuditSigningAlgorithm = AuditSigningAlgorithm.ECDSA_SHA_256,
        provider_profile: str = "aws-kms",
    ) -> None:
        self.sdk_client = sdk_client
        self.key_ref = AuditSigningKeyReference.parse(kms_key_ref)
        if not provider_key_id.strip():
            raise KmsPolicyViolation("provider_key_id must not be empty")
        if not provider_profile.strip():
            raise KmsPolicyViolation("provider_profile must not be empty")
        self.provider_key_id = provider_key_id.strip()
        self.signing_algorithm = signing_algorithm
        self.provider_profile = provider_profile.strip()

    def sign_digest(
        self,
        *,
        tenant_id: str,
        digest: bytes,
        signed_at_utc: str,
    ) -> AuditCheckpointSignature:
        if tenant_id != self.key_ref.tenant_id:
            raise KmsPolicyViolation("audit signing key tenant does not match request tenant")
        if len(digest) != sha256().digest_size:
            raise AuditSignatureError("audit checkpoint signer requires a SHA-256 digest")

        key_id = self._validate_provider_key()
        algorithm = self.signing_algorithm.aws_kms_name
        try:
            sign_response = self.sdk_client.sign(
                KeyId=key_id,
                Message=digest,
                MessageType="DIGEST",
                SigningAlgorithm=algorithm,
            )
        except Exception as exc:
            raise AuditSignatureError("AWS KMS Sign failed") from exc

        signature = sign_response.get("Signature")
        if not isinstance(signature, bytes) or not signature:
            raise AuditSignatureError("AWS KMS Sign did not return signature bytes")
        returned_key_id = str(sign_response.get("KeyId", "")).strip()
        if returned_key_id != key_id:
            raise AuditSignatureError("AWS KMS Sign returned an unexpected key ID")
        if str(sign_response.get("SigningAlgorithm", "")).strip() != algorithm:
            raise AuditSignatureError("AWS KMS Sign returned an unexpected signing algorithm")

        try:
            verify_response = self.sdk_client.verify(
                KeyId=key_id,
                Message=digest,
                MessageType="DIGEST",
                Signature=signature,
                SigningAlgorithm=algorithm,
            )
        except Exception as exc:
            raise AuditSignatureError("AWS KMS Verify failed") from exc
        if verify_response.get("SignatureValid") is not True:
            raise AuditSignatureError("AWS KMS did not verify the generated signature")
        if str(verify_response.get("KeyId", "")).strip() != key_id:
            raise AuditSignatureError("AWS KMS Verify returned an unexpected key ID")

        public_key = self._public_key(key_id=key_id, algorithm=algorithm)
        return AuditCheckpointSignature(
            tenant_id=tenant_id,
            signed_digest=_sha256_ref_from_digest(digest),
            signing_algorithm=self.signing_algorithm,
            kms_key_ref=self.key_ref.canonical_ref,
            kms_key_version=self.key_ref.key_version,
            provider_profile=self.provider_profile,
            provider_key_id=key_id,
            public_key_der_base64=base64.b64encode(public_key).decode("ascii"),
            public_key_sha256=_sha256_ref(public_key),
            signature_base64=base64.b64encode(signature).decode("ascii"),
            signature_sha256=_sha256_ref(signature),
            signed_at_utc=signed_at_utc,
            provider_sign_request_id=_request_id(sign_response),
            provider_verify_request_id=_request_id(verify_response),
            provider_verified=True,
        )

    def _validate_provider_key(self) -> str:
        try:
            response = self.sdk_client.describe_key(KeyId=self.provider_key_id)
        except Exception as exc:
            raise AuditSignatureError("AWS KMS DescribeKey failed") from exc
        metadata = response.get("KeyMetadata")
        if not isinstance(metadata, Mapping):
            raise AuditSignatureError("AWS KMS DescribeKey did not return key metadata")
        if metadata.get("KeyUsage") != "SIGN_VERIFY":
            raise AuditSignatureError("AWS KMS key usage must be SIGN_VERIFY")
        if metadata.get("Enabled") is not True or metadata.get("KeyState") != "Enabled":
            raise AuditSignatureError("AWS KMS signing key must be enabled")
        key_id = str(metadata.get("Arn") or metadata.get("KeyId") or "").strip()
        if not key_id:
            raise AuditSignatureError("AWS KMS key metadata did not contain an ID")
        return key_id

    def _public_key(self, *, key_id: str, algorithm: str) -> bytes:
        try:
            response = self.sdk_client.get_public_key(KeyId=key_id)
        except Exception as exc:
            raise AuditSignatureError("AWS KMS GetPublicKey failed") from exc
        if response.get("KeyUsage") != "SIGN_VERIFY":
            raise AuditSignatureError("AWS KMS public key usage must be SIGN_VERIFY")
        algorithms = response.get("SigningAlgorithms")
        if not isinstance(algorithms, list) or algorithm not in algorithms:
            raise AuditSignatureError("AWS KMS key does not support the configured signing algorithm")
        public_key = response.get("PublicKey")
        if not isinstance(public_key, bytes) or not public_key:
            raise AuditSignatureError("AWS KMS GetPublicKey did not return public key bytes")
        return public_key


def _request_id(response: Mapping[str, Any]) -> str:
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, Mapping):
        raise AuditSignatureError("AWS KMS response did not include response metadata")
    request_id = str(metadata.get("RequestId", "")).strip()
    if not request_id:
        raise AuditSignatureError("AWS KMS response did not include a request ID")
    return request_id


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _sha256_ref_from_digest(digest: bytes) -> str:
    return "sha256:" + digest.hex()
