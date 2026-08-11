from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.genoffice_internal_oss_admission import (
    GenOfficeInternalOssSignerPolicy,
    build_genoffice_internal_oss_signer_policy_hash,
)
from suite.operations.genoffice_internal_oss_ceremony import (
    GenOfficeInternalOssCeremonyError,
    GenOfficeInternalOssSigningRequest,
    assemble_genoffice_internal_oss_decision_envelope,
    build_genoffice_internal_oss_signer_policy,
    build_genoffice_internal_oss_signing_request,
    verify_genoffice_internal_oss_signing_request,
)
from suite.operations.genoffice_legal_review_dossier import load_genoffice_legal_review_dossier
from suite.operations.genoffice_third_party_notice import load_genoffice_third_party_notice_report

EVIDENCE = Path("docs/operations")


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _ceremony_fixture() -> tuple[
    GenOfficeInternalOssSigningRequest,
    bytes,
    GenOfficeInternalOssSignerPolicy,
    Ed25519PrivateKey,
    Ed25519PrivateKey,
]:
    product_owner_key = Ed25519PrivateKey.generate()
    security_owner_key = Ed25519PrivateKey.generate()
    policy = build_genoffice_internal_oss_signer_policy(
        policy_id="genoffice-signers-2026-08",
        effective_at_utc=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        product_owner_signer_id="product-owner-person",
        product_owner_key_id="product-owner-key-2026-08",
        product_owner_public_key=_public_key(product_owner_key),
        security_compliance_owner_signer_id="security-owner-person",
        security_compliance_owner_key_id="security-owner-key-2026-08",
        security_compliance_owner_public_key=_public_key(security_owner_key),
    )
    request, message = build_genoffice_internal_oss_signing_request(
        dossier=load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json"),
        notice_report=load_genoffice_third_party_notice_report(
            EVIDENCE / "genoffice_third_party_notice_report.json"
        ),
        notice_artifact=(EVIDENCE / "GENOFFICE_THIRD_PARTY_NOTICES.txt").read_bytes(),
        signer_policy=policy,
        decision_id="genoffice-development-evaluation-20260811-01",
        decided_at_utc=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        prepared_at_utc=datetime(2026, 8, 11, 9, 30, tzinfo=UTC),
        risk_acceptance_ref="ADR-0066:development-risk-acceptance",
        change_control_ref="git:d536110",
    )
    return request, message, policy, product_owner_key, security_owner_key


def test_signing_request_is_deterministic_non_effective_and_policy_bound() -> None:
    request, message, policy, _, _ = _ceremony_fixture()
    duplicate, duplicate_message = build_genoffice_internal_oss_signing_request(
        dossier=load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json"),
        notice_report=load_genoffice_third_party_notice_report(
            EVIDENCE / "genoffice_third_party_notice_report.json"
        ),
        notice_artifact=(EVIDENCE / "GENOFFICE_THIRD_PARTY_NOTICES.txt").read_bytes(),
        signer_policy=policy,
        decision_id="genoffice-development-evaluation-20260811-01",
        decided_at_utc=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        prepared_at_utc=datetime(2026, 8, 11, 9, 30, tzinfo=UTC),
        risk_acceptance_ref="ADR-0066:development-risk-acceptance",
        change_control_ref="git:d536110",
    )

    assert request == duplicate
    assert message == duplicate_message == verify_genoffice_internal_oss_signing_request(request)
    assert request.admission_effective is False
    assert request.payload.signer_policy_hash == policy.policy_hash
    assert request.required_signer_roles == ("product_owner", "security_compliance_owner")


def test_envelope_assembler_accepts_two_authorized_detached_signatures() -> None:
    request, message, policy, product_owner_key, security_owner_key = _ceremony_fixture()

    envelope = assemble_genoffice_internal_oss_decision_envelope(
        request=request,
        signer_policy=policy,
        product_owner_signature=product_owner_key.sign(message),
        security_compliance_owner_signature=security_owner_key.sign(message),
    )

    assert envelope.payload == request.payload
    assert tuple(item.signer_role for item in envelope.approvals) == (
        "product_owner",
        "security_compliance_owner",
    )


def test_envelope_assembler_rejects_signature_tampering_and_wrong_size() -> None:
    request, message, policy, product_owner_key, security_owner_key = _ceremony_fixture()
    tampered = bytearray(product_owner_key.sign(message))
    tampered[0] ^= 1

    with pytest.raises(GenOfficeInternalOssCeremonyError, match="invalid size"):
        assemble_genoffice_internal_oss_decision_envelope(
            request=request,
            signer_policy=policy,
            product_owner_signature=b"short",
            security_compliance_owner_signature=security_owner_key.sign(message),
        )
    with pytest.raises(ValueError, match="detached signature is invalid"):
        assemble_genoffice_internal_oss_decision_envelope(
            request=request,
            signer_policy=policy,
            product_owner_signature=bytes(tampered),
            security_compliance_owner_signature=security_owner_key.sign(message),
        )


def test_envelope_assembler_rejects_payload_and_signer_policy_drift() -> None:
    request, message, policy, product_owner_key, security_owner_key = _ceremony_fixture()
    tampered_payload = request.payload.model_copy(update={"change_control_ref": "git:tampered"})
    tampered_request = request.model_copy(update={"payload": tampered_payload})
    drifted_policy = policy.model_copy(update={"policy_id": "unauthorized-policy-drift"})
    drifted_policy = drifted_policy.model_copy(
        update={"policy_hash": build_genoffice_internal_oss_signer_policy_hash(drifted_policy)}
    )

    with pytest.raises(GenOfficeInternalOssCeremonyError, match="payload hash"):
        assemble_genoffice_internal_oss_decision_envelope(
            request=tampered_request,
            signer_policy=policy,
            product_owner_signature=product_owner_key.sign(message),
            security_compliance_owner_signature=security_owner_key.sign(message),
        )
    with pytest.raises(GenOfficeInternalOssCeremonyError, match="policy drifted"):
        assemble_genoffice_internal_oss_decision_envelope(
            request=request,
            signer_policy=drifted_policy,
            product_owner_signature=product_owner_key.sign(message),
            security_compliance_owner_signature=security_owner_key.sign(message),
        )


def test_signer_policy_builder_requires_two_people_and_raw_ed25519_public_keys() -> None:
    key = Ed25519PrivateKey.generate()
    public_key = _public_key(key)

    with pytest.raises(GenOfficeInternalOssCeremonyError, match="two-person"):
        build_genoffice_internal_oss_signer_policy(
            policy_id="policy",
            effective_at_utc=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
            product_owner_signer_id="same-person",
            product_owner_key_id="key-a",
            product_owner_public_key=public_key,
            security_compliance_owner_signer_id="same-person",
            security_compliance_owner_key_id="key-b",
            security_compliance_owner_public_key=public_key,
        )
    with pytest.raises(GenOfficeInternalOssCeremonyError, match="public key"):
        build_genoffice_internal_oss_signer_policy(
            policy_id="policy",
            effective_at_utc=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
            product_owner_signer_id="person-a",
            product_owner_key_id="key-a",
            product_owner_public_key=b"not-32-bytes",
            security_compliance_owner_signer_id="person-b",
            security_compliance_owner_key_id="key-b",
            security_compliance_owner_public_key=public_key,
        )


def test_ceremony_has_no_network_process_direct_crypto_or_secret_key_path() -> None:
    source = Path("app/suite/operations/genoffice_internal_oss_ceremony.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "cryptography", "PRIVATE_KEY"):
        assert forbidden not in source
    assert "verify_genoffice_internal_oss_envelope_signatures" in source


def test_ceremony_compose_services_are_offline_read_only_and_public_input_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    names = (
        "genoffice-internal-oss-signer-policy-builder",
        "genoffice-internal-oss-signing-request",
        "genoffice-internal-oss-envelope-assembler",
    )

    for index, name in enumerate(names):
        start = compose.index(f"  {name}:")
        end = compose.find("\n  genoffice-", start + 2)
        service = compose[start : end if end >= 0 else None]
        assert 'network_mode: "none"' in service
        assert "read_only: true" in service
        assert "no-new-privileges:true" in service
        assert "PRIVATE_KEY" not in service
        if index == 0:
            assert "PUBLIC_KEY" in service
