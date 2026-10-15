from __future__ import annotations

from pathlib import Path

import pytest

from suite.operations.genoffice_docx_quick_edit_preflight import (
    DOCX_QUICK_EDIT_FIXTURE_IDS,
    HARNESS_BLOCKING_REASONS,
    GenOfficeDocxQuickEditCorpusManifest,
    GenOfficeDocxQuickEditPreflightError,
    GenOfficeDocxQuickEditPreflightPolicy,
    build_genoffice_docx_quick_edit_corpus,
    build_genoffice_docx_quick_edit_corpus_manifest_hash,
    build_genoffice_docx_quick_edit_harness_admission_report,
    build_genoffice_docx_quick_edit_preflight_policy,
    evaluate_genoffice_docx_quick_edit_corpus,
    inspect_genoffice_docx_quick_edit_candidate,
    materialize_genoffice_docx_quick_edit_preflight_bundle,
    persist_genoffice_docx_quick_edit_preflight_schemas,
    revalidate_genoffice_docx_candidate_source_blind,
)


def _materialized_corpus(
    tmp_path: Path,
) -> tuple[
    Path,
    GenOfficeDocxQuickEditPreflightPolicy,
    GenOfficeDocxQuickEditCorpusManifest,
    dict[str, bytes],
]:
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, manifest = build_genoffice_docx_quick_edit_corpus(policy=policy)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, content in files.items():
        (corpus / name).write_bytes(content)
    (corpus / "genoffice-docx-quick-edit-corpus-manifest.json").write_text("{}", encoding="utf-8")
    return corpus, policy, manifest, files


def test_policy_is_hash_bound_and_keeps_all_execution_boundaries_closed() -> None:
    policy = build_genoffice_docx_quick_edit_preflight_policy()

    assert policy.policy_hash.startswith("sha256:")
    assert policy.max_parts == 128
    assert policy.fidelity_comparison_targets == (
        "microsoft_word",
        "libreoffice",
        "genoffice",
        "collabio_revalidator",
    )
    assert policy.engine_execution_enabled is False
    assert policy.tenant_content_allowed is False
    assert policy.network_allowed is False
    assert policy.persistent_document_writes_allowed is False
    assert policy.fidelity_claims_allowed is False


def test_corpus_is_deterministic_exact_and_covers_required_boundaries() -> None:
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files_a, manifest_a = build_genoffice_docx_quick_edit_corpus(policy=policy)
    files_b, manifest_b = build_genoffice_docx_quick_edit_corpus(policy=policy)

    assert files_a == files_b
    assert manifest_a == manifest_b
    assert tuple(artifact.fixture_id for artifact in manifest_a.artifacts) == DOCX_QUICK_EDIT_FIXTURE_IDS
    assert len(manifest_a.artifacts) == 19
    assert build_genoffice_docx_quick_edit_corpus_manifest_hash(manifest_a) == manifest_a.manifest_hash
    assert {artifact.category for artifact in manifest_a.artifacts} == {
        "fidelity",
        "external_relationship",
        "active_content",
        "embedded_object",
        "package_structure",
        "resource_exhaustion",
        "xml_parser",
        "digital_signature",
    }


def test_corpus_evaluation_matches_all_expected_findings(tmp_path: Path) -> None:
    corpus, policy, manifest, _ = _materialized_corpus(tmp_path)

    report = evaluate_genoffice_docx_quick_edit_corpus(
        manifest=manifest,
        corpus_directory=corpus,
        policy=policy,
    )

    assert report.expected_outcomes_matched is True
    assert report.allowed_fixture_count == 3
    assert report.rejected_fixture_count == 16
    assert report.engine_executed is False
    assert report.tenant_content_processed is False
    assert report.document_content_included_in_report is False
    assert all(item.engine_invocation_authorized is False for item in report.fixture_reports)


def test_preflight_detects_external_active_embedded_and_signature_boundaries() -> None:
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, _ = build_genoffice_docx_quick_edit_corpus(policy=policy)

    remote = inspect_genoffice_docx_quick_edit_candidate(files["external-hyperlink-relationship.docx"], policy=policy)
    macro = inspect_genoffice_docx_quick_edit_candidate(files["macro-enabled-vba-project.docm"], policy=policy)
    embedded = inspect_genoffice_docx_quick_edit_candidate(files["ole-embedded-object.docx"], policy=policy)
    signed = inspect_genoffice_docx_quick_edit_candidate(files["signed-package-unverified.docx"], policy=policy)

    assert remote.findings == ("external_relationship",)
    assert remote.external_relationship_count == 1
    assert macro.findings == ("active_content",)
    assert macro.active_content_marker_count > 0
    assert embedded.findings == ("embedded_object",)
    assert embedded.embedded_object_marker_count > 0
    assert signed.findings == ("signature_validation_required",)
    assert signed.signature_state == "present_unverified"
    assert signed.original_bytes_retention_required is True
    assert signed.derived_signature_state == "invalidated_by_edit"


@pytest.mark.parametrize(
    ("filename", "finding"),
    (
        ("path-traversal-part.docx", "unsafe_part_name"),
        ("duplicate-part-name.docx", "duplicate_part_name"),
        ("case-colliding-part-name.docx", "case_colliding_part_name"),
        ("high-compression-ratio.docx", "compression_ratio_limit"),
        ("xml-doctype-entity.docx", "xml_dtd_or_entity"),
        ("xml-depth-limit.docx", "xml_depth_limit"),
        ("malformed-xml.docx", "malformed_xml"),
        ("encrypted-entry-flag.docx", "encrypted_zip_entry"),
        ("unsupported-compression-method.docx", "unsupported_compression_method"),
        ("oversized-declared-part.docx", "part_size_limit"),
        ("too-many-parts.docx", "part_count_limit"),
    ),
)
def test_preflight_rejects_malicious_package_and_parser_cases(filename: str, finding: str) -> None:
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, _ = build_genoffice_docx_quick_edit_corpus(policy=policy)

    report = inspect_genoffice_docx_quick_edit_candidate(files[filename], policy=policy)

    assert report.decision == "reject_before_engine"
    assert finding in report.findings
    assert report.archive_extracted_to_filesystem is False
    assert report.engine_executed is False


def test_invalid_zip_fails_closed_without_content_or_engine_claims() -> None:
    report = inspect_genoffice_docx_quick_edit_candidate(b"not-a-zip")

    assert report.findings == ("invalid_zip",)
    assert report.decision == "reject_before_engine"
    assert report.document_content_included_in_report is False
    assert report.engine_executed is False


def test_source_blind_revalidation_accepts_only_hash_bound_clean_candidate() -> None:
    policy = build_genoffice_docx_quick_edit_preflight_policy()
    files, manifest = build_genoffice_docx_quick_edit_corpus(policy=policy)
    artifact = manifest.artifacts[0]

    report = revalidate_genoffice_docx_candidate_source_blind(
        files[artifact.filename],
        expected_candidate_sha256=artifact.content_sha256,
        policy=policy,
    )

    assert report.source_bytes_available is False
    assert report.source_object_accessed is False
    assert report.candidate_only_validation is True
    assert report.independent_preflight_passed is True
    assert report.engine_executed is False

    with pytest.raises(GenOfficeDocxQuickEditPreflightError, match="hash drifted"):
        revalidate_genoffice_docx_candidate_source_blind(
            files[artifact.filename],
            expected_candidate_sha256="sha256:" + "f" * 64,
            policy=policy,
        )
    with pytest.raises(GenOfficeDocxQuickEditPreflightError, match="failed independent preflight"):
        revalidate_genoffice_docx_candidate_source_blind(
            files["external-hyperlink-relationship.docx"],
            expected_candidate_sha256=next(
                item.content_sha256
                for item in manifest.artifacts
                if item.filename == "external-hyperlink-relationship.docx"
            ),
            policy=policy,
        )


def test_harness_admission_remains_hard_closed_after_preflight_success(tmp_path: Path) -> None:
    corpus, policy, manifest, files = _materialized_corpus(tmp_path)
    evaluation = evaluate_genoffice_docx_quick_edit_corpus(
        manifest=manifest,
        corpus_directory=corpus,
        policy=policy,
    )
    clean = manifest.artifacts[0]
    source_blind = revalidate_genoffice_docx_candidate_source_blind(
        files[clean.filename],
        expected_candidate_sha256=clean.content_sha256,
        policy=policy,
    )

    report = build_genoffice_docx_quick_edit_harness_admission_report(
        policy=policy,
        corpus_evaluation=evaluation,
        source_blind_revalidation=source_blind,
    )

    assert report.blocking_reasons == HARNESS_BLOCKING_REASONS
    assert report.corpus_contract_verified is True
    assert report.source_blind_revalidator_verified is True
    assert report.two_person_runtime_authorization_present is False
    assert report.attested_executable_proof_harness_image_present is False
    assert report.status_only_worker_entrypoint_verified is True
    assert report.harness_execution_allowed is False
    assert report.engine_executed is False


def test_bundle_is_write_once_and_contains_metadata_only_evidence(tmp_path: Path) -> None:
    output = tmp_path / "bundle"

    harness = materialize_genoffice_docx_quick_edit_preflight_bundle(output)

    assert harness.harness_execution_allowed is False
    assert (output / "corpus" / "formatting-table-fidelity.docx").is_file()
    assert (output / "genoffice-docx-quick-edit-preflight-policy.json").is_file()
    assert (output / "genoffice-docx-quick-edit-corpus-evaluation-report.json").is_file()
    assert (output / "genoffice-docx-source-blind-revalidation-report.json").is_file()
    assert (output / "genoffice-docx-quick-edit-harness-admission-report.json").is_file()

    with pytest.raises(GenOfficeDocxQuickEditPreflightError, match="not empty"):
        materialize_genoffice_docx_quick_edit_preflight_bundle(output)


def test_schema_materialization_is_complete_and_write_once(tmp_path: Path) -> None:
    hashes = persist_genoffice_docx_quick_edit_preflight_schemas(tmp_path)

    assert len(hashes) == 6
    assert all(name.endswith(".schema.json") for name in hashes)
    assert all(value.startswith("sha256:") for value in hashes.values())

    with pytest.raises(GenOfficeDocxQuickEditPreflightError, match="cannot be persisted"):
        persist_genoffice_docx_quick_edit_preflight_schemas(tmp_path)
