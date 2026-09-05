from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.genoffice_docx_fidelity_ceremony import (
    GenOfficeDocxFidelityCeremonyError,
    GenOfficeDocxFidelityExternalSignatureResponse,
    GenOfficeDocxFidelitySigningRequest,
    assemble_genoffice_docx_fidelity_signed_result,
    build_genoffice_docx_fidelity_signer_policy,
    build_genoffice_docx_fidelity_signing_request,
    load_genoffice_docx_fidelity_signer_policy,
    persist_genoffice_docx_fidelity_ceremony_schemas,
    persist_genoffice_docx_fidelity_signed_result,
    persist_genoffice_docx_fidelity_signer_policy,
    persist_genoffice_docx_fidelity_signing_request,
    verify_genoffice_docx_fidelity_signing_request,
)
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_ENGINE_IDS,
    EngineId,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelityStudyPlan,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_payload_hash,
    build_genoffice_docx_fidelity_study_plan,
    build_genoffice_docx_fidelity_study_policy,
    verify_genoffice_docx_fidelity_signed_result,
)
from suite.operations.genoffice_docx_quick_edit_preflight import (
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_preflight_policy,
)

ZERO_HASH = "sha256:" + "0" * 64
COMPLETED_AT = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)
PREPARED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _study_plan() -> GenOfficeDocxFidelityStudyPlan:
    preflight = build_genoffice_docx_quick_edit_preflight_policy()
    _, manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight)
    return build_genoffice_docx_fidelity_study_plan(
        policy=build_genoffice_docx_fidelity_study_policy(),
        preflight_policy=preflight,
        corpus_manifest=manifest,
    )


def _keys() -> dict[EngineId, Ed25519PrivateKey]:
    return {
        engine: Ed25519PrivateKey.from_private_bytes(bytes([index]) * 32)
        for index, engine in enumerate(FIDELITY_ENGINE_IDS, start=1)
    }


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _signer_policy(
    keys: dict[EngineId, Ed25519PrivateKey],
) -> GenOfficeDocxFidelityResultSignerPolicy:
    return build_genoffice_docx_fidelity_signer_policy(
        policy_id="fidelity-result-signers-20260813",
        effective_at_utc=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
        microsoft_word_signer_id="word-observer",
        microsoft_word_key_id="word-key-01",
        microsoft_word_public_key=_public_key(keys["microsoft_word"]),
        libreoffice_signer_id="libreoffice-observer",
        libreoffice_key_id="libreoffice-key-01",
        libreoffice_public_key=_public_key(keys["libreoffice"]),
        genoffice_signer_id="genoffice-observer",
        genoffice_key_id="genoffice-key-01",
        genoffice_public_key=_public_key(keys["genoffice"]),
    )


def _payload(plan: GenOfficeDocxFidelityStudyPlan) -> GenOfficeDocxFidelityEngineResultPayload:
    assignment = next(item for item in plan.assignments if item.engine_id == "libreoffice")
    draft = GenOfficeDocxFidelityEngineResultPayload(
        result_id=f"result:{assignment.assignment_id}",
        completed_at_utc=COMPLETED_AT,
        study_plan_hash=plan.plan_hash,
        fidelity_policy_hash=plan.fidelity_policy_hash,
        assignment_id=assignment.assignment_id,
        engine_id=assignment.engine_id,
        runner_mode=assignment.runner_mode,
        fixture_id=assignment.fixture_id,
        source_content_sha256=assignment.source_content_sha256,
        engine_version="LibreOffice 25.8.7.3",
        engine_identity_hash=_hash("libreoffice-engine"),
        executor_environment_hash=_hash("runsc-kvm-runner"),
        output_docx_sha256=_hash("output-docx"),
        output_preflight_report_hash=_hash("output-preflight"),
        output_structural_fingerprint_hash=_hash("output-structure"),
        open_xml_validation_report_hash=_hash("openxml-report"),
        cdr_manifest_hash=_hash("cdr-manifest"),
        font_baseline_hash=_hash("font-baseline"),
        page_count=1,
        visual_comparison_manifest_hash=_hash("visual-comparison"),
        execution_receipt_hash=_hash("execution-receipt"),
        payload_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(draft)})


def _request() -> tuple[
    GenOfficeDocxFidelityStudyPlan,
    dict[EngineId, Ed25519PrivateKey],
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelitySigningRequest,
    bytes,
]:
    plan = _study_plan()
    keys = _keys()
    policy = _signer_policy(keys)
    payload = _payload(plan)
    request, message = build_genoffice_docx_fidelity_signing_request(
        payload=payload,
        signer_policy=policy,
        study_plan=plan,
        prepared_at_utc=PREPARED_AT,
        valid_until_utc=VALID_UNTIL,
    )
    return plan, keys, policy, payload, request, message


def _response(
    request: GenOfficeDocxFidelitySigningRequest,
    private_key: Ed25519PrivateKey,
) -> GenOfficeDocxFidelityExternalSignatureResponse:
    assignment = request.signing_assignment
    return GenOfficeDocxFidelityExternalSignatureResponse(
        request_hash=request.request_hash,
        signature_message_sha256=request.signature_message_sha256,
        signer_id=assignment.signer_id,
        key_id=assignment.key_id,
        engine_id=assignment.engine_id,
        signature_base64=base64.b64encode(
            private_key.sign(build_genoffice_docx_fidelity_result_message(request.payload))
        ).decode("ascii"),
    )


def test_policy_builder_requires_distinct_engine_keys_and_canonical_order() -> None:
    keys = _keys()
    policy = _signer_policy(keys)

    assert tuple(item.engine_id for item in policy.signers) == FIDELITY_ENGINE_IDS
    assert policy.policy_hash != ZERO_HASH
    assert len({item.ed25519_public_key_base64 for item in policy.signers}) == 3

    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="not distinct"):
        build_genoffice_docx_fidelity_signer_policy(
            policy_id="drifted",
            effective_at_utc=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
            microsoft_word_signer_id="duplicate",
            microsoft_word_key_id="word-key",
            microsoft_word_public_key=_public_key(keys["microsoft_word"]),
            libreoffice_signer_id="duplicate",
            libreoffice_key_id="libreoffice-key",
            libreoffice_public_key=_public_key(keys["libreoffice"]),
            genoffice_signer_id="genoffice",
            genoffice_key_id="genoffice-key",
            genoffice_public_key=_public_key(keys["genoffice"]),
        )


def test_signing_request_is_private_key_free_and_bound_to_result() -> None:
    plan, _, policy, payload, request, message = _request()

    assert request.signing_assignment.engine_id == "libreoffice"
    assert request.signer_policy_hash == policy.policy_hash
    assert request.study_plan_hash == plan.plan_hash
    assert request.payload == payload
    assert request.result_accepted is False
    assert request.evidence_verified is False
    assert request.compatibility_claim_allowed is False
    assert request.private_key_ingestion_allowed is False
    assert request.signature_creation_performed is False
    assert (
        verify_genoffice_docx_fidelity_signing_request(
            request=request,
            signer_policy=policy,
            study_plan=plan,
        )
        == message
    )


def test_request_rejects_policy_effective_after_result_completion() -> None:
    plan = _study_plan()
    keys = _keys()
    policy = build_genoffice_docx_fidelity_signer_policy(
        policy_id="future-policy",
        effective_at_utc=COMPLETED_AT + timedelta(seconds=1),
        microsoft_word_signer_id="word",
        microsoft_word_key_id="word-key",
        microsoft_word_public_key=_public_key(keys["microsoft_word"]),
        libreoffice_signer_id="libreoffice",
        libreoffice_key_id="libreoffice-key",
        libreoffice_public_key=_public_key(keys["libreoffice"]),
        genoffice_signer_id="genoffice",
        genoffice_key_id="genoffice-key",
        genoffice_public_key=_public_key(keys["genoffice"]),
    )

    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="predates"):
        build_genoffice_docx_fidelity_signing_request(
            payload=_payload(plan),
            signer_policy=policy,
            study_plan=plan,
            prepared_at_utc=PREPARED_AT,
            valid_until_utc=VALID_UNTIL,
        )


def test_request_rejects_payload_and_request_hash_drift() -> None:
    plan, _, policy, _, request, _ = _request()
    drifted_payload = request.payload.model_copy(update={"engine_version": "drifted"})
    drifted = request.model_copy(update={"payload": drifted_payload})

    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="payload hash"):
        verify_genoffice_docx_fidelity_signing_request(
            request=drifted,
            signer_policy=policy,
            study_plan=plan,
        )

    drifted = request.model_copy(update={"request_hash": _hash("another-request")})
    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="request hash"):
        verify_genoffice_docx_fidelity_signing_request(
            request=drifted,
            signer_policy=policy,
            study_plan=plan,
        )


def test_external_signature_assembles_existing_verified_envelope() -> None:
    plan, keys, policy, payload, request, _ = _request()
    response = _response(request, keys["libreoffice"])

    envelope = assemble_genoffice_docx_fidelity_signed_result(
        request=request,
        response=response,
        signer_policy=policy,
        study_plan=plan,
        assembled_at_utc=PREPARED_AT + timedelta(minutes=1),
    )

    assert envelope.payload == payload
    assert envelope.private_key_included is False
    assert envelope.document_content_included is False
    assert envelope.envelope_hash != ZERO_HASH
    assert (
        verify_genoffice_docx_fidelity_signed_result(
            envelope=envelope,
            signer_policy=policy,
            study_plan=plan,
        )
        == payload
    )


def test_assembly_rejects_response_binding_signature_and_expiration() -> None:
    plan, keys, policy, _, request, _ = _request()
    response = _response(request, keys["libreoffice"])

    wrong_request = response.model_copy(update={"request_hash": _hash("wrong-request")})
    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="another request"):
        assemble_genoffice_docx_fidelity_signed_result(
            request=request,
            response=wrong_request,
            signer_policy=policy,
            study_plan=plan,
            assembled_at_utc=PREPARED_AT,
        )

    wrong_signature = _response(request, keys["microsoft_word"])
    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="signature is invalid"):
        assemble_genoffice_docx_fidelity_signed_result(
            request=request,
            response=wrong_signature,
            signer_policy=policy,
            study_plan=plan,
            assembled_at_utc=PREPARED_AT,
        )

    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="not currently valid"):
        assemble_genoffice_docx_fidelity_signed_result(
            request=request,
            response=response,
            signer_policy=policy,
            study_plan=plan,
            assembled_at_utc=VALID_UNTIL + timedelta(seconds=1),
        )


def test_request_window_is_bounded_and_result_must_precede_preparation() -> None:
    plan = _study_plan()
    keys = _keys()
    policy = _signer_policy(keys)
    payload = _payload(plan)

    with pytest.raises(ValueError, match="validity window"):
        build_genoffice_docx_fidelity_signing_request(
            payload=payload,
            signer_policy=policy,
            study_plan=plan,
            prepared_at_utc=PREPARED_AT,
            valid_until_utc=PREPARED_AT + timedelta(hours=73),
        )

    future_payload = payload.model_copy(update={"completed_at_utc": PREPARED_AT + timedelta(seconds=1)})
    future_payload = future_payload.model_copy(
        update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(future_payload)}
    )
    with pytest.raises(ValueError, match="completed after"):
        build_genoffice_docx_fidelity_signing_request(
            payload=future_payload,
            signer_policy=policy,
            study_plan=plan,
            prepared_at_utc=PREPARED_AT,
            valid_until_utc=VALID_UNTIL,
        )


def test_artifacts_and_schemas_are_private_write_once(tmp_path: Path) -> None:
    plan, keys, policy, _, request, message = _request()
    response = _response(request, keys["libreoffice"])
    envelope = assemble_genoffice_docx_fidelity_signed_result(
        request=request,
        response=response,
        signer_policy=policy,
        study_plan=plan,
        assembled_at_utc=PREPARED_AT,
    )
    policy_path = tmp_path / "policy.json"
    request_path = tmp_path / "request.json"
    message_path = tmp_path / "message.bin"
    envelope_path = tmp_path / "envelope.json"

    persist_genoffice_docx_fidelity_signer_policy(policy=policy, path=policy_path)
    persist_genoffice_docx_fidelity_signing_request(
        request=request,
        message=message,
        request_path=request_path,
        message_path=message_path,
    )
    persist_genoffice_docx_fidelity_signed_result(envelope=envelope, path=envelope_path)

    assert load_genoffice_docx_fidelity_signer_policy(policy_path) == policy
    assert json.loads(request_path.read_text())["private_key_ingestion_allowed"] is False
    assert json.loads(envelope_path.read_text())["private_key_included"] is False
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in tmp_path.iterdir())
    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="already exists"):
        persist_genoffice_docx_fidelity_signer_policy(policy=policy, path=policy_path)

    schema_dir = tmp_path / "schemas"
    hashes = persist_genoffice_docx_fidelity_ceremony_schemas(schema_dir)
    assert tuple(sorted(hashes)) == (
        "genoffice-docx-fidelity-external-signature-response.schema.json",
        "genoffice-docx-fidelity-signing-request.schema.json",
    )
    assert all(value.startswith("sha256:") for value in hashes.values())
    with pytest.raises(GenOfficeDocxFidelityCeremonyError, match="already exists"):
        persist_genoffice_docx_fidelity_ceremony_schemas(schema_dir)


def test_compose_ceremony_services_are_no_network_and_private_key_free() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("  genoffice-docx-fidelity-ceremony-schema:", 1)[1].split("\n  api:", 1)[0]

    assert "  genoffice-docx-fidelity-ceremony-schema:" in compose
    for service in ("policy", "request", "assemble"):
        assert f"genoffice-docx-fidelity-ceremony-{service}:" in block
    assert block.count('network_mode: "none"') == 4
    assert block.count("read_only: true") >= 10
    assert block.count("no-new-privileges:true") == 4
    assert block.count("- ALL") == 4
    assert "private" not in block.casefold()
    assert "/keys/word.ed25519.pub" in block
    assert "/keys/libreoffice.ed25519.pub" in block
    assert "/keys/genoffice.ed25519.pub" in block
    assert "/approvals/result.signature-response.json" in block


def test_runbook_keeps_claims_closed_and_keys_external() -> None:
    runbook = Path("docs/operations/GENOFFICE_DOCX_FIDELITY_SIGNING_CEREMONY.md").read_text(encoding="utf-8")

    assert "Never mount private keys" in runbook
    assert "does not prove compatibility" in runbook
    assert "Microsoft Word" in runbook
    assert "GenOffice" in runbook
    assert "ADR-0073" in runbook
