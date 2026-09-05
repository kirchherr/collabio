from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_ENGINE_IDS,
    FIDELITY_FIXTURE_IDS,
    READINESS_BLOCKERS,
    RESULT_SIGNATURE_DOMAIN,
    EngineId,
    GenOfficeDocxFidelityBaselineReport,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSigner,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelityRunAssignment,
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityStudyError,
    GenOfficeDocxFidelityStudyPlan,
    GenOfficeDocxFidelityStudyPolicy,
    build_genoffice_docx_fidelity_baseline_report,
    build_genoffice_docx_fidelity_readiness_report,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_payload_hash,
    build_genoffice_docx_fidelity_result_signer_policy_hash,
    build_genoffice_docx_fidelity_signed_result_envelope_hash,
    build_genoffice_docx_fidelity_study_plan,
    build_genoffice_docx_fidelity_study_policy,
    build_genoffice_docx_structural_fingerprint,
    compare_genoffice_docx_rgb_page,
    materialize_genoffice_docx_fidelity_study_bundle,
    persist_genoffice_docx_fidelity_study_schemas,
    verify_genoffice_docx_fidelity_result_matrix_intake,
    verify_genoffice_docx_fidelity_signed_result,
)
from suite.operations.genoffice_docx_quick_edit_preflight import (
    GenOfficeDocxQuickEditCorpusManifest,
    GenOfficeDocxQuickEditPreflightPolicy,
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_preflight_policy,
)

ZERO_HASH = "sha256:" + "0" * 64


def _hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _study() -> tuple[
    GenOfficeDocxFidelityStudyPolicy,
    GenOfficeDocxFidelityStudyPlan,
    GenOfficeDocxFidelityBaselineReport,
    GenOfficeDocxQuickEditPreflightPolicy,
    dict[str, bytes],
    GenOfficeDocxQuickEditCorpusManifest,
]:
    preflight = build_genoffice_docx_quick_edit_preflight_policy()
    files, manifest = build_genoffice_docx_quick_edit_corpus(policy=preflight)
    policy = build_genoffice_docx_fidelity_study_policy()
    plan = build_genoffice_docx_fidelity_study_plan(
        policy=policy,
        preflight_policy=preflight,
        corpus_manifest=manifest,
    )
    baseline = build_genoffice_docx_fidelity_baseline_report(
        study_plan=plan,
        preflight_policy=preflight,
        corpus_manifest=manifest,
        corpus_files=files,
    )
    return policy, plan, baseline, preflight, files, manifest


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
        policy_id="fidelity-test-signers",
        effective_at_utc=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
        signers=signers,
        policy_hash=ZERO_HASH,
    )
    policy = draft.model_copy(update={"policy_hash": build_genoffice_docx_fidelity_result_signer_policy_hash(draft)})
    return policy, keys


def _signed_result(
    *,
    assignment: GenOfficeDocxFidelityRunAssignment,
    plan: GenOfficeDocxFidelityStudyPlan,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    private_key: Ed25519PrivateKey,
) -> GenOfficeDocxFidelitySignedResultEnvelope:
    payload_draft = GenOfficeDocxFidelityEngineResultPayload(
        result_id=f"result:{assignment.assignment_id}",
        completed_at_utc=datetime(2026, 8, 13, 11, 0, tzinfo=UTC),
        study_plan_hash=plan.plan_hash,
        fidelity_policy_hash=plan.fidelity_policy_hash,
        assignment_id=assignment.assignment_id,
        engine_id=assignment.engine_id,
        runner_mode=assignment.runner_mode,
        fixture_id=assignment.fixture_id,
        source_content_sha256=assignment.source_content_sha256,
        engine_version="synthetic-test-identity",
        engine_identity_hash=_hash(f"engine:{assignment.engine_id}"),
        executor_environment_hash=_hash(f"runner:{assignment.engine_id}"),
        output_docx_sha256=_hash(f"output:{assignment.assignment_id}"),
        output_preflight_report_hash=_hash(f"preflight:{assignment.assignment_id}"),
        output_structural_fingerprint_hash=_hash(f"structure:{assignment.assignment_id}"),
        open_xml_validation_report_hash=_hash(f"openxml:{assignment.assignment_id}"),
        cdr_manifest_hash=_hash(f"cdr:{assignment.assignment_id}"),
        font_baseline_hash=_hash(f"fonts:{assignment.engine_id}"),
        page_count=1,
        visual_comparison_manifest_hash=_hash(f"visual:{assignment.assignment_id}"),
        execution_receipt_hash=_hash(f"receipt:{assignment.assignment_id}"),
        payload_hash=ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_docx_fidelity_result_payload_hash(payload_draft)}
    )
    signer = next(item for item in signer_policy.signers if item.engine_id == assignment.engine_id)
    envelope_draft = GenOfficeDocxFidelitySignedResultEnvelope(
        signer_policy_hash=signer_policy.policy_hash,
        payload=payload,
        signer_id=signer.signer_id,
        key_id=signer.key_id,
        signature_base64=base64.b64encode(
            private_key.sign(build_genoffice_docx_fidelity_result_message(payload))
        ).decode("ascii"),
        envelope_hash=ZERO_HASH,
    )
    return envelope_draft.model_copy(
        update={"envelope_hash": build_genoffice_docx_fidelity_signed_result_envelope_hash(envelope_draft)}
    )


def test_policy_separates_interactive_word_from_isolated_unattended_runners() -> None:
    policy = build_genoffice_docx_fidelity_study_policy()
    targets = {target.engine_id: target for target in policy.engine_targets}

    assert tuple(targets) == FIDELITY_ENGINE_IDS
    assert targets["microsoft_word"].runner_mode == "interactive_windows_client"
    assert targets["microsoft_word"].unattended_execution_allowed is False
    assert targets["microsoft_word"].interactive_user_session_required is True
    assert targets["libreoffice"].unattended_execution_allowed is True
    assert targets["genoffice"].runtime_authorization_required is True
    assert policy.calibrated_visual_thresholds_available is False
    assert policy.automated_layout_acceptance_allowed is False
    assert policy.compatibility_claims_allowed is False
    assert policy.tenant_content_allowed is False
    assert policy.production_use_allowed is False


def test_plan_is_deterministic_exact_and_execution_closed() -> None:
    policy, plan, _, _, _, _ = _study()

    assert plan.fidelity_policy_hash == policy.policy_hash
    assert len(plan.assignments) == 9
    assert tuple(item.assignment_id for item in plan.assignments) == tuple(
        f"{engine}:{fixture}" for engine in FIDELITY_ENGINE_IDS for fixture in FIDELITY_FIXTURE_IDS
    )
    assert all(item.execution_authorized is False for item in plan.assignments)
    assert plan.engine_execution_authorized is False
    assert plan.tenant_content_included is False


def test_plan_rejects_noncanonical_corpus_manifest() -> None:
    policy, _, _, preflight, _, manifest = _study()
    drifted = manifest.model_copy(update={"manifest_hash": ZERO_HASH})

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="manifest is not canonical"):
        build_genoffice_docx_fidelity_study_plan(
            policy=policy,
            preflight_policy=preflight,
            corpus_manifest=drifted,
        )


def test_structural_baseline_is_deterministic_and_feature_specific() -> None:
    _, _, baseline_a, _, _, _ = _study()
    _, _, baseline_b, _, _, _ = _study()

    assert baseline_a == baseline_b
    assert tuple(item.fixture_id for item in baseline_a.fixture_fingerprints) == FIDELITY_FIXTURE_IDS
    features = {
        item.fixture_id: {feature.feature_id: feature.count for feature in item.semantic_features}
        for item in baseline_a.fixture_fingerprints
    }
    assert features["formatting-table-fidelity"]["bold"] > 0
    assert features["formatting-table-fidelity"]["italic"] > 0
    assert features["formatting-table-fidelity"]["tables"] == 1
    assert features["headers-comments-footnotes-fidelity"]["headers"] > 0
    assert features["headers-comments-footnotes-fidelity"]["comments"] > 0
    assert features["headers-comments-footnotes-fidelity"]["footnotes"] > 0
    assert features["unknown-markup-passthrough"]["alternate_content"] > 0
    assert features["unknown-markup-passthrough"]["custom_xml_parts"] > 0
    assert all(item.document_text_included is False for item in baseline_a.fixture_fingerprints)
    assert all(item.engine_executed is False for item in baseline_a.fixture_fingerprints)


def test_structural_fingerprint_rejects_preflight_failure() -> None:
    _, _, _, preflight, files, _ = _study()

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="failed preflight"):
        build_genoffice_docx_structural_fingerprint(
            fixture_id="formatting-table-fidelity",
            content=files["external-hyperlink-relationship.docx"],
            preflight_policy=preflight,
        )


def test_rgb_measurement_is_exact_deterministic_and_never_accepts_layout() -> None:
    exact = compare_genoffice_docx_rgb_page(
        page_number=1,
        width_pixels=2,
        height_pixels=1,
        reference_rgb=bytes((0, 10, 20, 30, 40, 50)),
        candidate_rgb=bytes((0, 10, 20, 30, 40, 50)),
    )
    changed = compare_genoffice_docx_rgb_page(
        page_number=1,
        width_pixels=2,
        height_pixels=1,
        reference_rgb=bytes((0, 10, 20, 30, 40, 50)),
        candidate_rgb=bytes((0, 10, 21, 30, 40, 60)),
    )

    assert exact.exact_pixel_match is True
    assert exact.changed_pixels == 0
    assert changed.exact_pixel_match is False
    assert changed.changed_pixels == 2
    assert changed.changed_pixel_ratio_ppm == 1_000_000
    assert changed.maximum_channel_delta == 10
    assert changed.automated_acceptance_allowed is False

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="dimensions are inconsistent"):
        compare_genoffice_docx_rgb_page(
            page_number=1,
            width_pixels=2,
            height_pixels=1,
            reference_rgb=b"short",
            candidate_rgb=b"short",
        )


def test_signed_result_is_bound_to_engine_signer_assignment_and_plan() -> None:
    _, plan, _, _, _, _ = _study()
    signer_policy, keys = _signer_policy()
    assignment = plan.assignments[0]
    envelope = _signed_result(
        assignment=assignment,
        plan=plan,
        signer_policy=signer_policy,
        private_key=keys[assignment.engine_id],
    )

    verified = verify_genoffice_docx_fidelity_signed_result(
        envelope=envelope,
        signer_policy=signer_policy,
        study_plan=plan,
    )

    assert verified.assignment_id == assignment.assignment_id
    assert verified.source_blind_revalidation_verified is True
    assert verified.tenant_content_processed is False
    assert verified.document_content_in_payload is False
    assert build_genoffice_docx_fidelity_result_message(verified).startswith(RESULT_SIGNATURE_DOMAIN)

    wrong_signer = signer_policy.signers[1]
    drifted = envelope.model_copy(update={"signer_id": wrong_signer.signer_id, "key_id": wrong_signer.key_id})
    drifted = drifted.model_copy(
        update={"envelope_hash": build_genoffice_docx_fidelity_signed_result_envelope_hash(drifted)}
    )
    with pytest.raises(GenOfficeDocxFidelityStudyError, match="not authorized for the engine"):
        verify_genoffice_docx_fidelity_signed_result(
            envelope=drifted,
            signer_policy=signer_policy,
            study_plan=plan,
        )


def test_result_signer_policy_rejects_shared_keys_between_engines() -> None:
    signer_policy, _ = _signer_policy()
    shared_key = signer_policy.signers[0].ed25519_public_key_base64
    signers = tuple(
        signer.model_copy(update={"ed25519_public_key_base64": shared_key}) for signer in signer_policy.signers
    )

    with pytest.raises(ValueError, match="public keys are not distinct"):
        GenOfficeDocxFidelityResultSignerPolicy(
            policy_id="shared-key-policy",
            effective_at_utc=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
            signers=signers,
            policy_hash=ZERO_HASH,
        )


def test_exact_signed_matrix_intake_still_cannot_make_compatibility_claim() -> None:
    _, plan, _, _, _, _ = _study()
    signer_policy, keys = _signer_policy()
    envelopes = tuple(
        _signed_result(
            assignment=assignment,
            plan=plan,
            signer_policy=signer_policy,
            private_key=keys[assignment.engine_id],
        )
        for assignment in plan.assignments
    )

    report = verify_genoffice_docx_fidelity_result_matrix_intake(
        envelopes=envelopes,
        signer_policy=signer_policy,
        study_plan=plan,
    )

    assert report.accepted_signed_result_count == 9
    assert report.exact_assignment_matrix_verified is True
    assert report.signatures_verified is True
    assert report.referenced_evidence_hashes_bound is True
    assert report.referenced_evidence_content_verified is False
    assert report.visual_thresholds_calibrated is False
    assert report.human_fidelity_review_verified is False
    assert report.compatibility_claim_allowed is False
    assert report.quick_edit_spike_complete is False

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="matrix is not exact"):
        verify_genoffice_docx_fidelity_result_matrix_intake(
            envelopes=envelopes[:-1],
            signer_policy=signer_policy,
            study_plan=plan,
        )


def test_readiness_remains_hard_closed_without_real_runner_results() -> None:
    policy, plan, baseline, _, _, _ = _study()

    report = build_genoffice_docx_fidelity_readiness_report(
        policy=policy,
        study_plan=plan,
        baseline=baseline,
    )

    assert report.blocking_reasons == READINESS_BLOCKERS
    assert report.structural_baselines_verified is True
    assert report.accepted_signed_result_count == 0
    assert report.engine_executed is False
    assert report.compatibility_claim_allowed is False
    assert report.quick_edit_spike_complete is False


def test_bundle_is_metadata_only_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "fidelity-study"

    readiness = materialize_genoffice_docx_fidelity_study_bundle(output)

    assert readiness.engine_executed is False
    assert sorted(path.name for path in output.iterdir()) == [
        "genoffice-docx-fidelity-baseline-report.json",
        "genoffice-docx-fidelity-readiness-report.json",
        "genoffice-docx-fidelity-study-plan.json",
        "genoffice-docx-fidelity-study-policy.json",
    ]
    assert all(path.stat().st_size > 0 for path in output.iterdir())

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="not empty"):
        materialize_genoffice_docx_fidelity_study_bundle(output)


def test_schema_materialization_is_complete_and_write_once(tmp_path: Path) -> None:
    hashes = persist_genoffice_docx_fidelity_study_schemas(tmp_path)

    assert len(hashes) == 10
    assert all(name.endswith(".schema.json") for name in hashes)
    assert all(value.startswith("sha256:") for value in hashes.values())

    with pytest.raises(GenOfficeDocxFidelityStudyError, match="cannot be persisted"):
        persist_genoffice_docx_fidelity_study_schemas(tmp_path)


def test_compose_control_is_no_network_read_only_and_output_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-docx-fidelity-study-control:", 1)[1].split("\n  api:", 1)[0]

    assert 'profiles: ["office-worker-runtime-proof"]' in service
    assert "python -m suite.operations.genoffice_docx_fidelity_study" in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "cap_drop:\n      - ALL" in service
    assert "no-new-privileges:true" in service
    assert "./app:/workspace/app:ro" in service
    assert "SUITE_GENOFFICE_FIDELITY_STUDY_OUTPUT_DIR: /bundle" in service
    assert "create_host_path: false" in service
    assert "docker.sock" not in service
