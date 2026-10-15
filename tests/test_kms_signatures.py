from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.kms.signatures import PycaDetachedSignatureVerifier


def test_pyca_detached_signature_adapter_verifies_ed25519_and_rejects_tampering() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    message = b"collabio-attestation"
    signature = private_key.sign(message)
    verifier = PycaDetachedSignatureVerifier()

    assert verifier.verify_ed25519(public_key=public_key, signature=signature, message=message) is True
    assert verifier.verify_ed25519(public_key=public_key, signature=signature, message=b"tampered") is False
    assert verifier.verify_ed25519(public_key=b"invalid", signature=signature, message=message) is False
