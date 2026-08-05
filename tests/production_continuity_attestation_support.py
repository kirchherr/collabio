from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.production_continuity_attestation import (
    DSSE_PAYLOAD_TYPE,
    DSSESignature,
    ProductionContinuityApprovalPrincipals,
    ProductionContinuityAttestationEnvelope,
    ProductionContinuitySignerPolicy,
    ProductionContinuityTrustedSigner,
    SignerRole,
    build_dsse_pae,
    build_dsse_payload,
    build_production_continuity_attestation_statement,
)
from suite.storage.source_objects import sha256_bytes


def _private_key(role: str) -> Ed25519PrivateKey:
    seed = hashlib.sha256(f"collabio-test-only-{role}-signer".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def build_test_production_continuity_attestation(
    *,
    evidence_bundle_hash: str,
    deployment_ref_hash: str,
    backup_policy_schema_version: str,
    backup_policy_hash: str,
    approval_principals: ProductionContinuityApprovalPrincipals,
    issued_at: datetime,
) -> tuple[ProductionContinuitySignerPolicy, ProductionContinuityAttestationEnvelope]:
    principals: dict[SignerRole, str] = {
        "change": approval_principals.change,
        "security": approval_principals.security,
        "operations": approval_principals.operations,
    }
    private_keys = {role: _private_key(role) for role in principals}
    signers: list[ProductionContinuityTrustedSigner] = []
    for role, private_key in private_keys.items():
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        signers.append(
            ProductionContinuityTrustedSigner(
                key_id=sha256_bytes(public_key),
                principal_ref_hash=principals[role],
                role=role,
                public_key_base64=base64.b64encode(public_key).decode("ascii"),
                valid_from_utc=issued_at - timedelta(days=1),
                valid_until_utc=issued_at + timedelta(days=30),
            )
        )
    signer_policy = ProductionContinuitySignerPolicy(trusted_signers=tuple(signers))
    statement = build_production_continuity_attestation_statement(
        evidence_bundle_hash=evidence_bundle_hash,
        deployment_ref_hash=deployment_ref_hash,
        backup_policy_schema_version=backup_policy_schema_version,
        backup_policy_hash=backup_policy_hash,
        approval_principals=approval_principals,
        issued_at=issued_at,
    )
    payload = build_dsse_payload(statement)
    pae = build_dsse_pae(payload_type=DSSE_PAYLOAD_TYPE, payload=payload)
    signatures = tuple(
        DSSESignature(
            keyid=signer.key_id,
            sig=base64.b64encode(private_keys[signer.role].sign(pae)).decode("ascii"),
        )
        for signer in signers
    )
    return signer_policy, ProductionContinuityAttestationEnvelope(
        payload=base64.b64encode(payload).decode("ascii"),
        signatures=signatures,
    )
