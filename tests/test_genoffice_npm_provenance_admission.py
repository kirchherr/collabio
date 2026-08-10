from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from suite.operations.genoffice_npm_provenance_admission import (
    FULCIO_CERTIFICATE_SHA256,
    INVOCATION_URI,
    NPM_VERIFIER_IMAGE_REF,
    SOURCE_COMMIT,
    WORKFLOW_URI,
    GenOfficeNpmProvenanceAdmissionError,
    GenOfficeNpmProvenanceAdmissionReport,
    build_genoffice_npm_provenance_admission_report,
    load_genoffice_npm_provenance_admission_report,
    persist_genoffice_npm_provenance_admission_report,
    run_genoffice_npm_provenance_admission_from_environment,
)

ROOT = Path(__file__).resolve().parents[1]
VENDORED_REPORT = ROOT / "docs/operations/genoffice_vendored_provenance_report.json"
NPM_VERIFICATION = ROOT / "docs/operations/genoffice_emf_converter_npm_verification.json"
NPM_RECEIPT = ROOT / "docs/operations/genoffice_emf_converter_npm_verification_receipt.txt"


def _build() -> GenOfficeNpmProvenanceAdmissionReport:
    return build_genoffice_npm_provenance_admission_report(
        vendored_provenance_path=VENDORED_REPORT,
        npm_verification_path=NPM_VERIFICATION,
        npm_verification_receipt_path=NPM_RECEIPT,
    )


def test_builds_pinned_cryptographic_provenance_admission() -> None:
    report = _build()

    assert report.cryptographic_provenance_gate_passed is True
    assert report.registry_signature_verified is True
    assert report.publish_attestation_verified is True
    assert report.slsa_provenance_verified is True
    assert report.certificate_identity_verified is True
    assert report.transparency_log_inclusion_verified is True
    assert report.verifier_image_ref == NPM_VERIFIER_IMAGE_REF
    assert report.source_commit == SOURCE_COMMIT
    assert report.workflow_uri == WORKFLOW_URI
    assert report.invocation_uri == INVOCATION_URI
    assert report.fulcio_certificate_sha256 == FULCIO_CERTIFICATE_SHA256
    assert len(report.rekor_entries) == 2
    assert report.legal_review_complete is False
    assert report.source_import_allowed is False
    assert report.engine_execution_allowed is False
    assert report.production_use_allowed is False


def test_persist_and_load_round_trip(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = _build()

    persist_genoffice_npm_provenance_admission_report(report=report, report_path=output)

    assert load_genoffice_npm_provenance_admission_report(output) == report


def test_rejects_tampered_npm_verification(tmp_path: Path) -> None:
    tampered = tmp_path / "npm-verification.json"
    payload = json.loads(NPM_VERIFICATION.read_text(encoding="utf-8"))
    payload["verified"][0]["version"] = "2.0.3"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GenOfficeNpmProvenanceAdmissionError, match="reviewed snapshot"):
        build_genoffice_npm_provenance_admission_report(
            vendored_provenance_path=VENDORED_REPORT,
            npm_verification_path=tampered,
            npm_verification_receipt_path=NPM_RECEIPT,
        )


def test_rejects_tampered_verifier_receipt(tmp_path: Path) -> None:
    tampered = tmp_path / "receipt.txt"
    tampered.write_text(NPM_RECEIPT.read_text(encoding="utf-8").replace("11.16.0", "99.0.0"), encoding="utf-8")

    with pytest.raises(GenOfficeNpmProvenanceAdmissionError, match="reviewed receipt"):
        build_genoffice_npm_provenance_admission_report(
            vendored_provenance_path=VENDORED_REPORT,
            npm_verification_path=NPM_VERIFICATION,
            npm_verification_receipt_path=tampered,
        )


def test_report_cannot_open_execution_boundary() -> None:
    payload = _build().model_dump(mode="json")
    payload["engine_execution_allowed"] = True

    with pytest.raises(ValidationError, match="unreviewed trust or execution boundary"):
        GenOfficeNpmProvenanceAdmissionReport.model_validate(payload)


def test_environment_runner_requires_all_paths() -> None:
    with pytest.raises(GenOfficeNpmProvenanceAdmissionError, match="paths are missing"):
        run_genoffice_npm_provenance_admission_from_environment({})
