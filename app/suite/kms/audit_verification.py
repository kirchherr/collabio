from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils

from suite.kms.signing import AuditCheckpointSignature, AuditSigningAlgorithm


class AuditOfflineSignatureVerificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_offline_audit_checkpoint_signature(signature_record: AuditCheckpointSignature) -> None:
    try:
        public_key_der = base64.b64decode(signature_record.public_key_der_base64, validate=True)
        signature = base64.b64decode(signature_record.signature_base64, validate=True)
        public_key = serialization.load_der_public_key(public_key_der)
        canonical_public_key = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if canonical_public_key != public_key_der:
            raise AuditOfflineSignatureVerificationError("noncanonical_public_key")
        digest = bytes.fromhex(signature_record.signed_digest.removeprefix("sha256:"))
        if signature_record.signing_algorithm is AuditSigningAlgorithm.ECDSA_SHA_256:
            if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
                public_key.curve, (ec.SECP256R1, ec.SECP256K1)
            ):
                raise AuditOfflineSignatureVerificationError("incompatible_ecdsa_public_key")
            public_key.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        elif signature_record.signing_algorithm is AuditSigningAlgorithm.RSASSA_PSS_SHA_256:
            if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
                raise AuditOfflineSignatureVerificationError("incompatible_rsa_public_key")
            public_key.verify(
                signature,
                digest,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                utils.Prehashed(hashes.SHA256()),
            )
        else:
            raise AuditOfflineSignatureVerificationError("unsupported_signing_algorithm")
    except AuditOfflineSignatureVerificationError:
        raise
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise AuditOfflineSignatureVerificationError("signature_invalid") from exc
