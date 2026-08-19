from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from suite.kms.adapter import KmsPolicyViolation
from suite.kms.openbao_transit import (
    OpenBaoTransitAuditCheckpointSigner,
    OpenBaoTransitHttpClient,
    OpenBaoTransitKeyReference,
    OpenBaoTransitSigningKeyInspector,
)
from suite.kms.signing import AuditSignatureError, AuditSigningAlgorithm

PROVIDER_KEY_ID = "openbao-transit://transit/collabio-audit-tenant/v3"


class FakeOpenBaoTransitClient:
    def __init__(self) -> None:
        public_key = ec.generate_private_key(ec.SECP256R1()).public_key()
        self.public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        self.deletion_allowed = False
        self.key_type = "ecdsa-p256"
        self.sign_calls: list[dict[str, object]] = []
        self.verify_calls: list[dict[str, object]] = []
        self.signature_valid = True

    def read_key(self, *, mount_path: str, key_name: str) -> Mapping[str, Any]:
        assert mount_path == "transit"
        assert key_name == "collabio-audit-tenant"
        return {
            "request_id": "openbao-key-read-request",
            "data": {
                "deletion_allowed": self.deletion_allowed,
                "type": self.key_type,
                "latest_version": 3,
                "keys": {"3": {"public_key": self.public_key_pem}},
            },
        }

    def sign_digest(self, **kwargs: object) -> Mapping[str, Any]:
        self.sign_calls.append(dict(kwargs))
        return {
            "request_id": "openbao-sign-request",
            "data": {"signature": "vault:v3:" + base64.b64encode(b"openbao-signature").decode("ascii")},
        }

    def verify_digest(self, **kwargs: object) -> Mapping[str, Any]:
        self.verify_calls.append(dict(kwargs))
        return {
            "request_id": "openbao-verify-request",
            "data": {"valid": self.signature_valid},
        }


def test_openbao_transit_signer_uses_versioned_key_and_provider_verification() -> None:
    client = FakeOpenBaoTransitClient()
    signer = OpenBaoTransitAuditCheckpointSigner(
        client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v3",
        provider_key_id=PROVIDER_KEY_ID,
    )
    digest = bytes.fromhex("ab" * 32)

    signature = signer.sign_digest(
        tenant_id="tenant-audit",
        digest=digest,
        signed_at_utc="2026-08-19T08:00:00Z",
    )

    assert signature.provider_profile == "openbao-transit"
    assert signature.provider_key_id == PROVIDER_KEY_ID
    assert signature.kms_key_version == 3
    assert signature.signing_algorithm is AuditSigningAlgorithm.ECDSA_SHA_256
    assert base64.b64decode(signature.signature_base64) == b"openbao-signature"
    assert client.sign_calls == [
        {
            "mount_path": "transit",
            "key_name": "collabio-audit-tenant",
            "key_version": 3,
            "digest_base64": base64.b64encode(digest).decode("ascii"),
            "signature_algorithm": None,
        }
    ]
    assert client.verify_calls[0]["signature"] == "vault:v3:" + base64.b64encode(
        b"openbao-signature"
    ).decode("ascii")


def test_openbao_transit_inspection_rejects_deletable_or_unapproved_keys() -> None:
    client = FakeOpenBaoTransitClient()
    inspector = OpenBaoTransitSigningKeyInspector(client=client)

    client.deletion_allowed = True
    with pytest.raises(AuditSignatureError, match="forbid deletion"):
        inspector.inspect_provider_key(provider_key_id=PROVIDER_KEY_ID)

    client.deletion_allowed = False
    client.key_type = "ed25519"
    with pytest.raises(AuditSignatureError, match="not approved"):
        inspector.inspect_provider_key(provider_key_id=PROVIDER_KEY_ID)


def test_openbao_transit_signer_fails_closed_on_version_algorithm_or_verification_drift() -> None:
    client = FakeOpenBaoTransitClient()
    with pytest.raises(KmsPolicyViolation, match="versions must match"):
        OpenBaoTransitAuditCheckpointSigner(
            client=client,
            kms_key_ref="kms-sign://tenant-audit/audit/v2",
            provider_key_id=PROVIDER_KEY_ID,
        )

    rsa_signer = OpenBaoTransitAuditCheckpointSigner(
        client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v3",
        provider_key_id=PROVIDER_KEY_ID,
        signing_algorithm=AuditSigningAlgorithm.RSASSA_PSS_SHA_256,
    )
    with pytest.raises(AuditSignatureError, match="RSA-PSS"):
        rsa_signer.sign_digest(
            tenant_id="tenant-audit",
            digest=bytes.fromhex("ab" * 32),
            signed_at_utc="2026-08-19T08:00:00Z",
        )

    signer = OpenBaoTransitAuditCheckpointSigner(
        client=client,
        kms_key_ref="kms-sign://tenant-audit/audit/v3",
        provider_key_id=PROVIDER_KEY_ID,
    )
    client.signature_valid = False
    with pytest.raises(AuditSignatureError, match="did not verify"):
        signer.sign_digest(
            tenant_id="tenant-audit",
            digest=bytes.fromhex("ab" * 32),
            signed_at_utc="2026-08-19T08:00:00Z",
        )


def test_openbao_provider_identity_and_http_origin_are_canonical_and_tls_only() -> None:
    assert OpenBaoTransitKeyReference.parse(PROVIDER_KEY_ID).key_version == 3
    with pytest.raises(KmsPolicyViolation, match="provider key reference"):
        OpenBaoTransitKeyReference.parse("transit/collabio-audit-tenant")
    with pytest.raises(KmsPolicyViolation, match="HTTPS origin"):
        OpenBaoTransitHttpClient(address="http://openbao:8200", token="test-token")
