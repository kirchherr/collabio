from __future__ import annotations

import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from production_continuity_attestation_support import (
    build_test_production_continuity_attestation,
    sign_test_production_continuity_message,
)
from suite.operations.backup_failover import BackupFailoverPolicy
from suite.operations.production_continuity_attestation import (
    ProductionContinuityApprovalPrincipals,
    ProductionContinuitySignerPolicy,
    verify_production_continuity_attestation,
)
from suite.operations.production_continuity_attestation_ceremony import (
    ProductionContinuityAttestationSigningRequest,
    ProductionContinuityExternalSignatureResponse,
    assemble_production_continuity_attestation_envelope,
    build_production_continuity_attestation_signing_request,
    build_production_continuity_attestation_signing_request_hash,
    load_production_continuity_attestation_signing_request,
    persist_production_continuity_ceremony_artifact,
)
from suite.operations.production_continuity_attestation_ceremony import (
    main as ceremony_main,
)
from suite.operations.production_continuity_deployment_gate import (
    ProductionContinuityDeploymentEvidenceBundle,
    build_backup_failover_policy_hash,
    build_production_continuity_evidence_bundle_hash,
)
from test_production_continuity_deployment_gate import _bundle as build_test_evidence_bundle
from test_production_continuity_deployment_gate import _policy as load_test_policy

CHECKED_AT = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _principals(bundle: ProductionContinuityDeploymentEvidenceBundle) -> ProductionContinuityApprovalPrincipals:
    approvals = bundle.approvals
    return ProductionContinuityApprovalPrincipals(
        change=approvals.change_approver_principal_hash,
        security=approvals.security_approver_principal_hash,
        operations=approvals.operations_approver_principal_hash,
    )


def _inputs() -> tuple[
    BackupFailoverPolicy, ProductionContinuityDeploymentEvidenceBundle, ProductionContinuitySignerPolicy
]:
    policy = load_test_policy()
    bundle = build_test_evidence_bundle(policy=policy, checked_at=CHECKED_AT)
    signer_policy, _ = build_test_production_continuity_attestation(
        evidence_bundle_hash=build_production_continuity_evidence_bundle_hash(bundle),
        deployment_ref_hash=bundle.deployment_ref_hash,
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=build_backup_failover_policy_hash(policy),
        approval_principals=_principals(bundle),
        issued_at=CHECKED_AT,
    )
    return policy, bundle, signer_policy


def _request() -> tuple[
    BackupFailoverPolicy,
    ProductionContinuityDeploymentEvidenceBundle,
    ProductionContinuitySignerPolicy,
    ProductionContinuityAttestationSigningRequest,
]:
    policy, bundle, signer_policy = _inputs()
    request = build_production_continuity_attestation_signing_request(
        policy=policy,
        bundle=bundle,
        signer_policy=signer_policy,
        selected_key_ids=tuple(signer.key_id for signer in signer_policy.trusted_signers),
        issued_at=CHECKED_AT,
    )
    return policy, bundle, signer_policy, request


def _responses(
    request: ProductionContinuityAttestationSigningRequest,
) -> tuple[ProductionContinuityExternalSignatureResponse, ...]:
    message = base64.b64decode(request.pre_authentication_encoding_base64, validate=True)
    return tuple(
        ProductionContinuityExternalSignatureResponse(
            request_hash=request.request_hash,
            role=assignment.role,
            key_id=assignment.key_id,
            signature_base64=sign_test_production_continuity_message(
                role=assignment.role,
                message=message,
            ),
        )
        for assignment in request.signing_assignments
    )


def test_prepare_builds_a_deterministic_private_key_free_three_role_request() -> None:
    policy, bundle, signer_policy, request = _request()

    repeated = build_production_continuity_attestation_signing_request(
        policy=policy,
        bundle=bundle,
        signer_policy=signer_policy,
        selected_key_ids=tuple(reversed([signer.key_id for signer in signer_policy.trusted_signers])),
        issued_at=CHECKED_AT,
    )

    assert repeated == request
    assert build_production_continuity_attestation_signing_request_hash(request) == request.request_hash
    assert tuple(assignment.role for assignment in request.signing_assignments) == (
        "change",
        "security",
        "operations",
    )
    assert request.private_key_ingestion_allowed is False
    assert request.signature_creation_performed is False
    serialized = request.model_dump_json()
    assert "public_key_base64" not in serialized
    assert "PRIVATE KEY" not in serialized
    assert "collabio-test-only" not in serialized


def test_assemble_accepts_three_external_signatures_and_reverifies_the_envelope() -> None:
    policy, bundle, signer_policy, request = _request()

    envelope = assemble_production_continuity_attestation_envelope(
        policy=policy,
        bundle=bundle,
        signer_policy=signer_policy,
        request=request,
        signature_responses=_responses(request),
        checked_at=CHECKED_AT,
    )

    verification = verify_production_continuity_attestation(
        envelope=envelope,
        signer_policy=signer_policy,
        expected_evidence_bundle_hash=request.evidence_bundle_hash,
        expected_deployment_ref_hash=request.deployment_ref_hash,
        expected_backup_policy_schema_version=request.backup_policy_schema_version,
        expected_backup_policy_hash=request.backup_policy_hash,
        expected_approval_principals=_principals(bundle),
        checked_at=CHECKED_AT,
        maximum_age_hours=policy.production_deployment_gate.maximum_evidence_age_hours,
    )
    assert verification.verified is True
    assert len(envelope.signatures) == 3


def test_assemble_rejects_tampering_response_rebinding_and_expiry() -> None:
    policy, bundle, signer_policy, request = _request()
    responses = list(_responses(request))
    responses[0] = responses[0].model_copy(update={"signature_base64": responses[1].signature_base64})
    with pytest.raises(ValueError, match="could not be verified"):
        assemble_production_continuity_attestation_envelope(
            policy=policy,
            bundle=bundle,
            signer_policy=signer_policy,
            request=request,
            signature_responses=tuple(responses),
            checked_at=CHECKED_AT,
        )

    rebound = list(_responses(request))
    rebound[0] = rebound[0].model_copy(update={"request_hash": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="not bound"):
        assemble_production_continuity_attestation_envelope(
            policy=policy,
            bundle=bundle,
            signer_policy=signer_policy,
            request=request,
            signature_responses=tuple(rebound),
            checked_at=CHECKED_AT,
        )
    forged = request.model_copy(update={"valid_until_utc": request.valid_until_utc + timedelta(hours=1)})
    forged = forged.model_copy(
        update={"request_hash": build_production_continuity_attestation_signing_request_hash(forged)}
    )
    with pytest.raises(ValueError, match="no longer matches"):
        assemble_production_continuity_attestation_envelope(
            policy=policy,
            bundle=bundle,
            signer_policy=signer_policy,
            request=forged,
            signature_responses=_responses(forged),
            checked_at=CHECKED_AT,
        )

    with pytest.raises(ValueError, match="not currently valid"):
        assemble_production_continuity_attestation_envelope(
            policy=policy,
            bundle=bundle,
            signer_policy=signer_policy,
            request=request,
            signature_responses=_responses(request),
            checked_at=request.valid_until_utc + timedelta(seconds=1),
        )


def test_prepare_rejects_unknown_revoked_and_principal_mismatched_keys() -> None:
    policy, bundle, signer_policy = _inputs()
    selected_key_ids = tuple(signer.key_id for signer in signer_policy.trusted_signers)
    with pytest.raises(ValueError, match="unknown signer"):
        build_production_continuity_attestation_signing_request(
            policy=policy,
            bundle=bundle,
            signer_policy=signer_policy,
            selected_key_ids=("sha256:" + "f" * 64, *selected_key_ids[1:]),
            issued_at=CHECKED_AT,
        )

    revoked = signer_policy.model_copy(
        update={
            "trusted_signers": (
                signer_policy.trusted_signers[0].model_copy(update={"revoked": True}),
                *signer_policy.trusted_signers[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="revoked or inactive"):
        build_production_continuity_attestation_signing_request(
            policy=policy,
            bundle=bundle,
            signer_policy=revoked,
            selected_key_ids=selected_key_ids,
            issued_at=CHECKED_AT,
        )

    mismatched = signer_policy.model_copy(
        update={
            "trusted_signers": (
                signer_policy.trusted_signers[0].model_copy(update={"principal_ref_hash": "sha256:" + "e" * 64}),
                *signer_policy.trusted_signers[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="does not match"):
        build_production_continuity_attestation_signing_request(
            policy=policy,
            bundle=bundle,
            signer_policy=mismatched,
            selected_key_ids=selected_key_ids,
            issued_at=CHECKED_AT,
        )


def test_request_persistence_is_hash_validated_and_never_overwrites(tmp_path: Path) -> None:
    _, _, _, request = _request()
    output = tmp_path / "request.json"

    persist_production_continuity_ceremony_artifact(artifact=request, path=output)

    assert load_production_continuity_attestation_signing_request(output) == request
    with pytest.raises(FileExistsError):
        persist_production_continuity_ceremony_artifact(artifact=request, path=output)
    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["deployment_ref_hash"] = "sha256:" + "f" * 64
    tampered_path = output.parent / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError):
        load_production_continuity_attestation_signing_request(tampered_path)


def test_prepare_cli_writes_only_a_request_and_fails_closed_on_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime.now(UTC)
    policy = load_test_policy()
    bundle = build_test_evidence_bundle(policy=policy, checked_at=now)
    signer_policy, _ = build_test_production_continuity_attestation(
        evidence_bundle_hash=build_production_continuity_evidence_bundle_hash(bundle),
        deployment_ref_hash=bundle.deployment_ref_hash,
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=build_backup_failover_policy_hash(policy),
        approval_principals=_principals(bundle),
        issued_at=now,
    )
    policy_path = tmp_path / "policy.json"
    evidence_path = tmp_path / "evidence.json"
    signer_policy_path = tmp_path / "signers.json"
    output_path = tmp_path / "request.json"
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    evidence_path.write_text(bundle.model_dump_json(), encoding="utf-8")
    signer_policy_path.write_text(signer_policy.model_dump_json(), encoding="utf-8")
    arguments = [
        "ceremony",
        "prepare",
        "--policy",
        str(policy_path),
        "--evidence",
        str(evidence_path),
        "--signer-policy",
        str(signer_policy_path),
        "--output",
        str(output_path),
    ]
    for signer in signer_policy.trusted_signers:
        arguments.extend(("--key-id", signer.key_id))
    monkeypatch.setattr(sys, "argv", arguments)

    ceremony_main()

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["signature_count_required"] == 3
    assert receipt["private_key_ingestion_allowed"] is False
    assert output_path.is_file()
    with pytest.raises(SystemExit) as error:
        ceremony_main()
    assert error.value.code == 2
    assert json.loads(capsys.readouterr().out)["ceremony_ready"] is False


def test_operator_runbook_preserves_the_external_private_key_boundary() -> None:
    runbook = (REPO_ROOT / "docs" / "operations" / "PRODUCTION_CONTINUITY_SIGNING_CEREMONY.md").read_text(
        encoding="utf-8"
    )

    assert "production_continuity_attestation_signing_request.v1" in runbook
    assert "production_continuity_external_signature_response.v1" in runbook
    assert "production-continuity-attestation-ceremony prepare" in runbook
    assert "production-continuity-attestation-ceremony assemble" in runbook
    assert "There is deliberately no `sign`" in runbook
    assert "Never mount private keys" in runbook
    assert "private_key_ingestion_allowed=false" in runbook
    assert ":/inputs/request.json:ro" in runbook
