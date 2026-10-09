from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

from suite.operations.genoffice_docx_fidelity_evidence import (
    GenOfficeDocxFidelityCdrManifest,
    GenOfficeDocxFidelityEvidenceArtifact,
    GenOfficeDocxFidelityEvidenceError,
    GenOfficeDocxFidelityEvidenceVerificationReport,
    GenOfficeDocxFidelityExecutionReceipt,
    GenOfficeDocxFidelityFontBaselineReport,
    GenOfficeDocxFidelityVisualComparisonManifest,
    GenOfficeDocxOpenXmlValidationReport,
    build_genoffice_docx_fidelity_cdr_manifest_hash,
    build_genoffice_docx_fidelity_execution_receipt_hash,
    build_genoffice_docx_fidelity_font_baseline_report_hash,
    build_genoffice_docx_fidelity_visual_comparison_manifest_hash,
    build_genoffice_docx_openxml_validation_report_hash,
    load_genoffice_docx_fidelity_verification_inputs,
    persist_genoffice_docx_fidelity_evidence_schemas,
    verify_genoffice_docx_fidelity_evidence_bundle,
)
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_ENGINE_IDS,
    ZERO_HASH,
    EngineId,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSigner,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityStudyPlan,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_payload_hash,
    build_genoffice_docx_fidelity_result_signer_policy_hash,
    build_genoffice_docx_fidelity_signed_result_envelope_hash,
    build_genoffice_docx_fidelity_study_plan,
    build_genoffice_docx_fidelity_study_policy,
    build_genoffice_docx_structural_fingerprint,
    compare_genoffice_docx_rgb_page,
)
from suite.operations.genoffice_docx_quick_edit_preflight import (
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_preflight_policy,
    inspect_genoffice_docx_quick_edit_candidate,
)
from suite.platform.preview_cdr import PreviewCdrPageManifest


@dataclass(frozen=True)
class EvidenceFixture:
    root: Path
    envelope: GenOfficeDocxFidelitySignedResultEnvelope
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy
    study_plan: GenOfficeDocxFidelityStudyPlan


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _hash(value: str) -> str:
    return _sha256(value.encode())


def _model_bytes(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json")
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _write_model(path: Path, model: BaseModel) -> None:
    path.write_bytes(_model_bytes(model))


def _signer_policy() -> tuple[GenOfficeDocxFidelityResultSignerPolicy, dict[EngineId, Ed25519PrivateKey]]:
    keys = {
        engine: Ed25519PrivateKey.from_private_bytes(bytes([index]) * 32)
        for index, engine in enumerate(FIDELITY_ENGINE_IDS, start=1)
    }
    signers = tuple(
        GenOfficeDocxFidelityResultSigner(
            signer_id=f"{engine}-runner",
            key_id=f"{engine}-key",
            engine_id=engine,
            ed25519_public_key_base64=base64.b64encode(
                keys[engine]
                .public_key()
                .public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii"),
        )
        for engine in FIDELITY_ENGINE_IDS
    )
    draft = GenOfficeDocxFidelityResultSignerPolicy(
        policy_id="fidelity-evidence-test-signers",
        effective_at_utc=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
        signers=signers,
        policy_hash=ZERO_HASH,
    )
    return (
        draft.model_copy(update={"policy_hash": build_genoffice_docx_fidelity_result_signer_policy_hash(draft)}),
        keys,
    )


def _artifact_inventory(root: Path) -> tuple[GenOfficeDocxFidelityEvidenceArtifact, ...]:
    artifacts: list[GenOfficeDocxFidelityEvidenceArtifact] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "execution-receipt.json":
            continue
        content = path.read_bytes()
        artifacts.append(
            GenOfficeDocxFidelityEvidenceArtifact(
                relative_path=path.relative_to(root).as_posix(),
                size_bytes=len(content),
                content_sha256=_sha256(content),
            )
        )
    return tuple(artifacts)


def _build_cdr(
    *,
    root: Path,
    assignment_id: str,
    render_stage: Literal["source_reference", "roundtrip_candidate"],
    docx_sha256: str,
    font_hash: str,
    rgb: bytes,
) -> GenOfficeDocxFidelityCdrManifest:
    root.mkdir()
    page = PreviewCdrPageManifest(
        page_number=1,
        width_pixels=2,
        height_pixels=1,
        rgb_content_hash=_sha256(rgb),
        rgb_byte_length=len(rgb),
    )
    draft = GenOfficeDocxFidelityCdrManifest(
        assignment_id=assignment_id,
        render_stage=render_stage,
        rendered_docx_sha256=docx_sha256,
        rasterizer_engine="pdftoppm",
        rasterizer_version="26.01-test",
        font_baseline_report_hash=font_hash,
        page_count=1,
        raw_rgb_byte_length=len(rgb),
        pages=(page,),
        manifest_hash=ZERO_HASH,
    )
    manifest = draft.model_copy(update={"manifest_hash": build_genoffice_docx_fidelity_cdr_manifest_hash(draft)})
    (root / page.filename).write_bytes(rgb)
    _write_model(root / "manifest.json", manifest)
    return manifest


def _build_evidence_fixture(tmp_path: Path) -> EvidenceFixture:
    root = tmp_path / "evidence"
    root.mkdir()
    preflight_policy = build_genoffice_docx_quick_edit_preflight_policy()
    corpus_files, corpus_manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight_policy)
    policy = build_genoffice_docx_fidelity_study_policy()
    study_plan = build_genoffice_docx_fidelity_study_plan(
        policy=policy,
        preflight_policy=preflight_policy,
        corpus_manifest=corpus_manifest,
    )
    assignment = study_plan.assignments[0]
    source_artifact = next(item for item in corpus_manifest.artifacts if item.fixture_id == assignment.fixture_id)
    output_docx = corpus_files[source_artifact.filename]
    output_sha256 = _sha256(output_docx)
    (root / "output.docx").write_bytes(output_docx)

    preflight = inspect_genoffice_docx_quick_edit_candidate(output_docx, policy=preflight_policy)
    _write_model(root / "output-preflight-report.json", preflight)
    structural = build_genoffice_docx_structural_fingerprint(
        fixture_id=assignment.fixture_id,
        content=output_docx,
        preflight_policy=preflight_policy,
    )
    _write_model(root / "output-structural-fingerprint-report.json", structural)

    openxml_draft = GenOfficeDocxOpenXmlValidationReport(
        assignment_id=assignment.assignment_id,
        engine_id=assignment.engine_id,
        fixture_id=assignment.fixture_id,
        output_docx_sha256=output_sha256,
        validator_version="3.3.0-test",
        target_file_format_version="Office2021",
        findings=(),
        validation_error_count=0,
        schema_conformant=True,
        report_hash=ZERO_HASH,
    )
    openxml = openxml_draft.model_copy(
        update={"report_hash": build_genoffice_docx_openxml_validation_report_hash(openxml_draft)}
    )
    _write_model(root / "openxml-validation-report.json", openxml)

    font_draft = GenOfficeDocxFidelityFontBaselineReport(
        assignment_id=assignment.assignment_id,
        engine_id=assignment.engine_id,
        runner_mode=assignment.runner_mode,
        engine_version="word-test-identity",
        engine_identity_hash=_hash("engine:word"),
        executor_environment_hash=_hash("runner:windows-test"),
        inventory_method="windows_font_inventory",
        font_count=3,
        normalized_inventory_sha256=_hash("font-inventory"),
        report_hash=ZERO_HASH,
    )
    font = font_draft.model_copy(
        update={"report_hash": build_genoffice_docx_fidelity_font_baseline_report_hash(font_draft)}
    )
    _write_model(root / "font-baseline-report.json", font)

    reference_rgb = bytes((0, 10, 20, 30, 40, 50))
    candidate_rgb = bytes((0, 10, 21, 30, 40, 50))
    reference_cdr = _build_cdr(
        root=root / "reference-cdr",
        assignment_id=assignment.assignment_id,
        render_stage="source_reference",
        docx_sha256=assignment.source_content_sha256,
        font_hash=font.report_hash,
        rgb=reference_rgb,
    )
    candidate_cdr = _build_cdr(
        root=root / "candidate-cdr",
        assignment_id=assignment.assignment_id,
        render_stage="roundtrip_candidate",
        docx_sha256=output_sha256,
        font_hash=font.report_hash,
        rgb=candidate_rgb,
    )
    comparison = compare_genoffice_docx_rgb_page(
        page_number=1,
        width_pixels=2,
        height_pixels=1,
        reference_rgb=reference_rgb,
        candidate_rgb=candidate_rgb,
    )
    visual_draft = GenOfficeDocxFidelityVisualComparisonManifest(
        assignment_id=assignment.assignment_id,
        reference_cdr_manifest_hash=reference_cdr.manifest_hash,
        candidate_cdr_manifest_hash=candidate_cdr.manifest_hash,
        page_comparisons=(comparison,),
        page_count=1,
        manifest_hash=ZERO_HASH,
    )
    visual = visual_draft.model_copy(
        update={"manifest_hash": build_genoffice_docx_fidelity_visual_comparison_manifest_hash(visual_draft)}
    )
    _write_model(root / "visual-comparison-manifest.json", visual)

    completed_at = datetime(2026, 8, 13, 11, 5, tzinfo=UTC)
    receipt_draft = GenOfficeDocxFidelityExecutionReceipt(
        assignment_id=assignment.assignment_id,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=policy.policy_hash,
        engine_id=assignment.engine_id,
        runner_mode=assignment.runner_mode,
        source_content_sha256=assignment.source_content_sha256,
        output_docx_sha256=output_sha256,
        engine_identity_hash=font.engine_identity_hash,
        executor_environment_hash=font.executor_environment_hash,
        authorization_evidence_hash=_hash("interactive-runner-authorization"),
        command_hash=_hash("word-runner-command"),
        started_at_utc=datetime(2026, 8, 13, 11, 0, tzinfo=UTC),
        completed_at_utc=completed_at,
        artifacts=_artifact_inventory(root),
        receipt_hash=ZERO_HASH,
    )
    receipt = receipt_draft.model_copy(
        update={"receipt_hash": build_genoffice_docx_fidelity_execution_receipt_hash(receipt_draft)}
    )
    _write_model(root / "execution-receipt.json", receipt)

    payload_draft = GenOfficeDocxFidelityEngineResultPayload(
        result_id=f"result:{assignment.assignment_id}",
        completed_at_utc=completed_at,
        study_plan_hash=study_plan.plan_hash,
        fidelity_policy_hash=policy.policy_hash,
        assignment_id=assignment.assignment_id,
        engine_id=assignment.engine_id,
        runner_mode=assignment.runner_mode,
        fixture_id=assignment.fixture_id,
        source_content_sha256=assignment.source_content_sha256,
        engine_version=font.engine_version,
        engine_identity_hash=font.engine_identity_hash,
        executor_environment_hash=font.executor_environment_hash,
        output_docx_sha256=output_sha256,
        output_preflight_report_hash=preflight.report_hash,
        output_structural_fingerprint_hash=structural.report_hash,
        open_xml_validation_report_hash=openxml.report_hash,
        cdr_manifest_hash=candidate_cdr.manifest_hash,
        font_baseline_hash=font.report_hash,
        page_count=1,
        visual_comparison_manifest_hash=visual.manifest_hash,
        execution_receipt_hash=receipt.receipt_hash,
        payload_hash=ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(payload_draft)}
    )
    signer_policy, keys = _signer_policy()
    signer = signer_policy.signers[0]
    envelope_draft = GenOfficeDocxFidelitySignedResultEnvelope(
        signer_policy_hash=signer_policy.policy_hash,
        payload=payload,
        signer_id=signer.signer_id,
        key_id=signer.key_id,
        signature_base64=base64.b64encode(
            keys[assignment.engine_id].sign(build_genoffice_docx_fidelity_result_message(payload))
        ).decode("ascii"),
        envelope_hash=ZERO_HASH,
    )
    envelope = envelope_draft.model_copy(
        update={"envelope_hash": build_genoffice_docx_fidelity_signed_result_envelope_hash(envelope_draft)}
    )
    return EvidenceFixture(root=root, envelope=envelope, signer_policy=signer_policy, study_plan=study_plan)


def _verify(fixture: EvidenceFixture) -> GenOfficeDocxFidelityEvidenceVerificationReport:
    return verify_genoffice_docx_fidelity_evidence_bundle(
        evidence_root=fixture.root,
        envelope=fixture.envelope,
        signer_policy=fixture.signer_policy,
        study_plan=fixture.study_plan,
    )


def test_complete_signed_evidence_bundle_recomputes_every_content_binding(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)

    report = _verify(fixture)

    assert report.signed_result_verified is True
    assert report.artifact_inventory_exact is True
    assert report.artifact_bytes_verified is True
    assert report.output_preflight_recomputed is True
    assert report.structural_fingerprint_verified is True
    assert report.open_xml_evidence_verified is True
    assert report.open_xml_schema_conformant is True
    assert report.reference_cdr_bytes_verified is True
    assert report.candidate_cdr_bytes_verified is True
    assert report.visual_measurements_recomputed is True
    assert report.referenced_evidence_content_verified is True
    assert report.thresholds_calibrated is False
    assert report.human_fidelity_review_verified is False
    assert report.compatibility_claim_allowed is False
    assert report.quick_edit_spike_complete is False
    assert report.tenant_content_processed is False
    assert report.document_content_in_report is False


def test_evidence_verifier_rejects_tampered_output_docx(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    (fixture.root / "output.docx").write_bytes(b"tampered")

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="output DOCX bytes drifted"):
        _verify(fixture)


def test_evidence_verifier_rejects_tampered_cdr_page(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    (fixture.root / "candidate-cdr" / "page-000001.rgb").write_bytes(bytes((0, 0, 0, 0, 0, 0)))

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="CDR page bytes drifted"):
        _verify(fixture)


def test_evidence_verifier_rejects_unexpected_file_and_symlink(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    (fixture.root / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="top-level inventory is not exact"):
        _verify(fixture)

    (fixture.root / "unexpected.txt").unlink()
    link = fixture.root / "candidate-cdr" / "unexpected.rgb"
    try:
        link.symlink_to(fixture.root / "candidate-cdr" / "page-000001.rgb")
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="page inventory is not exact"):
        _verify(fixture)


def test_evidence_verifier_rejects_receipt_inventory_drift(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    receipt_path = fixture.root / "execution-receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["artifacts"] = payload["artifacts"][:-1]
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="execution receipt hash is invalid"):
        _verify(fixture)


def test_evidence_verifier_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    path = fixture.root / "openxml-validation-report.json"
    path.write_text('{"schema_version":"a","schema_version":"b"}', encoding="utf-8")

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="duplicate keys"):
        _verify(fixture)


def test_signed_result_verification_rejects_tampered_study_plan_hash(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    drifted_plan = fixture.study_plan.model_copy(update={"corpus_manifest_hash": _hash("drift")})

    with pytest.raises(ValueError, match="study plan hash is invalid"):
        verify_genoffice_docx_fidelity_evidence_bundle(
            evidence_root=fixture.root,
            envelope=fixture.envelope,
            signer_policy=fixture.signer_policy,
            study_plan=drifted_plan,
        )


def test_evidence_schema_materialization_is_complete_and_write_once(tmp_path: Path) -> None:
    hashes = persist_genoffice_docx_fidelity_evidence_schemas(tmp_path)

    assert len(hashes) == 6
    assert all(name.endswith(".schema.json") for name in hashes)
    assert all(value.startswith("sha256:") for value in hashes.values())
    for filename, content_hash in hashes.items():
        generated = (tmp_path / filename).read_bytes()
        published = (Path("docs/operations") / filename).read_bytes()
        assert generated == published
        assert _sha256(published) == content_hash

    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="output directory is not empty"):
        persist_genoffice_docx_fidelity_evidence_schemas(tmp_path)


def test_public_input_loader_requires_exact_regular_file_inventory(tmp_path: Path) -> None:
    fixture = _build_evidence_fixture(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_model(inputs / "result-envelope.json", fixture.envelope)
    _write_model(inputs / "signer-policy.json", fixture.signer_policy)
    _write_model(inputs / "study-plan.json", fixture.study_plan)

    envelope, policy, plan = load_genoffice_docx_fidelity_verification_inputs(inputs)

    assert envelope == fixture.envelope
    assert policy == fixture.signer_policy
    assert plan == fixture.study_plan

    (inputs / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(GenOfficeDocxFidelityEvidenceError, match="public input inventory is not exact"):
        load_genoffice_docx_fidelity_verification_inputs(inputs)


def test_compose_evidence_controls_are_no_network_read_only_and_mount_inputs_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    schema_service = compose.split("  genoffice-docx-fidelity-evidence-schema:", 1)[1].split(
        "\n  genoffice-docx-fidelity-evidence-verifier:", 1
    )[0]
    verifier_service = compose.split("  genoffice-docx-fidelity-evidence-verifier:", 1)[1].split("\n  api:", 1)[0]

    for service in (schema_service, verifier_service):
        assert 'profiles: ["office-worker-runtime-proof"]' in service
        assert "python -m suite.operations.genoffice_docx_fidelity_evidence" in service
        assert 'network_mode: "none"' in service
        assert "read_only: true" in service
        assert "cap_drop:\n      - ALL" in service
        assert "no-new-privileges:true" in service
        assert "./app:/workspace/app:ro" in service
        assert "create_host_path: false" in service
        assert "docker.sock" not in service

    assert "SUITE_GENOFFICE_FIDELITY_EVIDENCE_MODE: schema" in schema_service
    assert "SUITE_GENOFFICE_FIDELITY_EVIDENCE_MODE: verify" in verifier_service
    assert "SUITE_GENOFFICE_FIDELITY_INPUT_DIR: /inputs" in verifier_service
    assert "target: /evidence\n        read_only: true" in verifier_service
    assert "target: /inputs\n        read_only: true" in verifier_service
