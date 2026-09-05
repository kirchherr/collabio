from __future__ import annotations

from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class DetachedSignatureVerifier(Protocol):
    def verify_ed25519(self, *, public_key: bytes, signature: bytes, message: bytes) -> bool: ...


class PycaDetachedSignatureVerifier:
    def verify_ed25519(self, *, public_key: bytes, signature: bytes, message: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        except (InvalidSignature, ValueError):
            return False
        return True


DEFAULT_DETACHED_SIGNATURE_VERIFIER: DetachedSignatureVerifier = PycaDetachedSignatureVerifier()
