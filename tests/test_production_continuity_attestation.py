from __future__ import annotations

from datetime import UTC, datetime, timedelta

from production_continuity_attestation_support import (
    build_test_production_continuity_attestation,
)
from suite.operations.production_continuity_attestation import (
    ProductionContinuityApprovalPrincipals,
    ProductionContinuityAttestationEnvelope,
    ProductionContinuityAttestationVerification,
    ProductionContinuitySignerPolicy,
    verify_production_continuity_attestation,
)
from suite.storage.source_objects import sha256_bytes

CHECKED_AT = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _inputs() -> tuple[
    ProductionContinuityApprovalPrincipals,
    ProductionContinuitySignerPolicy,
    ProductionContinuityAttestationEnvelope,
]:
    principals = ProductionContinuityApprovalPrincipals(
        change=_hash("change-principal"),
        security=_hash("security-principal"),
        operations=_hash("operations-principal"),
    )
    signer_policy, envelope = build_test_production_continuity_attestation(
        evidence_bundle_hash=_hash("evidence"),
        deployment_ref_hash=_hash("deployment"),
        backup_policy_schema_version="backup_failover_policy.v4",
        backup_policy_hash=_hash("backup-policy"),
        approval_principals=principals,
        issued_at=CHECKED_AT - timedelta(minutes=5),
    )
    return principals, signer_policy, envelope


def _verify(
    *,
    signer_policy: ProductionContinuitySignerPolicy,
    envelope: ProductionContinuityAttestationEnvelope,
    evidence_bundle_hash: str | None = None,
) -> ProductionContinuityAttestationVerification:
    principals, _, _ = _inputs()
    return verify_production_continuity_attestation(
        envelope=envelope,
        signer_policy=signer_policy,
        expected_evidence_bundle_hash=evidence_bundle_hash or _hash("evidence"),
        expected_deployment_ref_hash=_hash("deployment"),
        expected_backup_policy_schema_version="backup_failover_policy.v4",
        expected_backup_policy_hash=_hash("backup-policy"),
        checked_at=CHECKED_AT,
        maximum_age_hours=168,
        expected_approval_principals=principals,
    )


def test_three_role_dsse_attestation_verifies_without_private_key_ingestion() -> None:
    _, signer_policy, envelope = _inputs()

    result = _verify(signer_policy=signer_policy, envelope=envelope)

    assert result.verified is True
    assert result.verified_roles == ("change", "operations", "security")
    assert len(result.verified_key_ids) == 3


def test_attestation_rejects_a_validly_encoded_but_tampered_signature() -> None:
    _, signer_policy, envelope = _inputs()
    signatures = list(envelope.signatures)
    signatures[0] = signatures[0].model_copy(update={"sig": signatures[1].sig})
    tampered = envelope.model_copy(update={"signatures": tuple(signatures)})

    assert _verify(signer_policy=signer_policy, envelope=tampered).verified is False


def test_attestation_rejects_subject_substitution() -> None:
    _, signer_policy, envelope = _inputs()

    assert (
        _verify(
            signer_policy=signer_policy,
            envelope=envelope,
            evidence_bundle_hash=_hash("different-evidence"),
        ).verified
        is False
    )


def test_attestation_rejects_a_revoked_signing_key() -> None:
    _, signer_policy, envelope = _inputs()
    revoked_signer = signer_policy.trusted_signers[0].model_copy(update={"revoked": True})
    revoked_policy = signer_policy.model_copy(
        update={"trusted_signers": (revoked_signer, *signer_policy.trusted_signers[1:])}
    )

    assert _verify(signer_policy=revoked_policy, envelope=envelope).verified is False
