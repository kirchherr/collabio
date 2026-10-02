import base64
from collections.abc import Mapping
from typing import Any

import pytest

from suite.kms.adapter import KmsPolicyViolation
from suite.kms.signing import (
    AuditSignatureError,
    AuditSigningAlgorithm,
    AwsKmsAuditCheckpointSigner,
)


class FakeKmsSigningClient:
    key_arn = "arn:aws:kms:eu-central-1:123456789012:key/audit-signing-key"

    def __init__(self) -> None:
        self.key_usage = "SIGN_VERIFY"
        self.key_state = "Enabled"
        self.enabled = True
        self.signature_valid = True
        self.sign_calls: list[dict[str, object]] = []
        self.verify_calls: list[dict[str, object]] = []

    def describe_key(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs["KeyId"] == "alias/collabio-audit-signing"
        return {
            "KeyMetadata": {
                "Arn": self.key_arn,
                "KeyUsage": self.key_usage,
                "KeyState": self.key_state,
                "Enabled": self.enabled,
            }
        }

    def get_public_key(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs["KeyId"] == self.key_arn
        return {
            "KeyUsage": "SIGN_VERIFY",
            "SigningAlgorithms": ["ECDSA_SHA_256"],
            "PublicKey": b"public-key-der",
        }

    def sign(self, **kwargs: object) -> Mapping[str, Any]:
        self.sign_calls.append(kwargs)
        return {
            "KeyId": self.key_arn,
            "Signature": b"provider-signature",
            "SigningAlgorithm": "ECDSA_SHA_256",
            "ResponseMetadata": {"RequestId": "kms-sign-request"},
        }

    def verify(self, **kwargs: object) -> Mapping[str, Any]:
        self.verify_calls.append(kwargs)
        return {
            "KeyId": self.key_arn,
            "SignatureValid": self.signature_valid,
            "SigningAlgorithm": "ECDSA_SHA_256",
            "ResponseMetadata": {"RequestId": "kms-verify-request"},
        }


def test_aws_kms_audit_signer_signs_and_verifies_sha256_digest_without_private_key_material() -> None:
    client = FakeKmsSigningClient()
    signer = AwsKmsAuditCheckpointSigner(
        sdk_client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v3",
        provider_key_id="alias/collabio-audit-signing",
    )
    digest = bytes.fromhex("ab" * 32)

    signature = signer.sign_digest(
        tenant_id="tenant-audit",
        digest=digest,
        signed_at_utc="2026-08-17T10:00:00Z",
    )

    assert signature.signed_digest == "sha256:" + ("ab" * 32)
    assert signature.signing_algorithm == AuditSigningAlgorithm.ECDSA_SHA_256
    assert signature.signing_message_type == "DIGEST"
    assert signature.kms_key_version == 3
    assert signature.provider_key_id == client.key_arn
    assert base64.b64decode(signature.public_key_der_base64) == b"public-key-der"
    assert signature.provider_verified is True
    assert signature.public_key_sha256.startswith("sha256:")
    assert signature.signature_sha256.startswith("sha256:")
    assert client.sign_calls == [
        {
            "KeyId": client.key_arn,
            "Message": digest,
            "MessageType": "DIGEST",
            "SigningAlgorithm": "ECDSA_SHA_256",
        }
    ]
    assert client.verify_calls[0]["Signature"] == b"provider-signature"


def test_aws_kms_audit_signer_rejects_cross_tenant_use_and_non_signing_key() -> None:
    client = FakeKmsSigningClient()
    signer = AwsKmsAuditCheckpointSigner(
        sdk_client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v1",
        provider_key_id="alias/collabio-audit-signing",
    )

    with pytest.raises(KmsPolicyViolation, match="tenant"):
        signer.sign_digest(
            tenant_id="tenant-other",
            digest=bytes.fromhex("ab" * 32),
            signed_at_utc="2026-08-17T10:00:00Z",
        )

    client.key_usage = "ENCRYPT_DECRYPT"
    with pytest.raises(AuditSignatureError, match="SIGN_VERIFY"):
        signer.sign_digest(
            tenant_id="tenant-audit",
            digest=bytes.fromhex("ab" * 32),
            signed_at_utc="2026-08-17T10:00:00Z",
        )


def test_aws_kms_audit_signer_fails_when_provider_does_not_verify_signature() -> None:
    client = FakeKmsSigningClient()
    client.signature_valid = False
    signer = AwsKmsAuditCheckpointSigner(
        sdk_client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v1",
        provider_key_id="alias/collabio-audit-signing",
    )

    with pytest.raises(AuditSignatureError, match="did not verify"):
        signer.sign_digest(
            tenant_id="tenant-audit",
            digest=bytes.fromhex("ab" * 32),
            signed_at_utc="2026-08-17T10:00:00Z",
        )


def test_aws_kms_audit_signer_requires_sha256_digest_and_dedicated_signing_key_namespace() -> None:
    client = FakeKmsSigningClient()
    with pytest.raises(KmsPolicyViolation, match="kms-sign"):
        AwsKmsAuditCheckpointSigner(
            sdk_client=client,
            kms_key_ref="kms://tenant-audit/internal/v1",
            provider_key_id="alias/collabio-audit-signing",
        )

    signer = AwsKmsAuditCheckpointSigner(
        sdk_client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v1",
        provider_key_id="alias/collabio-audit-signing",
    )
    with pytest.raises(AuditSignatureError, match="SHA-256"):
        signer.sign_digest(
            tenant_id="tenant-audit",
            digest=b"not-a-digest",
            signed_at_utc="2026-08-17T10:00:00Z",
        )
