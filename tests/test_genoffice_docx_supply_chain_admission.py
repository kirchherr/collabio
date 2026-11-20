from __future__ import annotations

import json
from pathlib import Path

import pytest

import suite.operations.genoffice_docx_supply_chain_admission as supply_chain
from suite.operations.genoffice_docx_supply_chain_admission import (
    GenOfficeDocxSupplyChainAdmissionError,
    GenOfficeDocxSupplyChainAdmissionReport,
    build_genoffice_docx_supply_chain_admission_report,
    build_genoffice_docx_supply_chain_report_hash,
    load_genoffice_docx_supply_chain_admission_report,
)

EVIDENCE = Path("docs/operations")


def _build_report(*, vulnerability_report_path: Path | None = None) -> GenOfficeDocxSupplyChainAdmissionReport:
    return build_genoffice_docx_supply_chain_admission_report(
        source_report_path=EVIDENCE / "genoffice_docx_source_admission_report.json",
        vendored_provenance_path=EVIDENCE / "genoffice_vendored_provenance_report.json",
        sbom_path=EVIDENCE / "genoffice_docx_prebuild.cdx.json",
        schema_validation_receipt_path=EVIDENCE / "genoffice_docx_prebuild_schema_validation.txt",
        vulnerability_report_path=(
            vulnerability_report_path or EVIDENCE / "genoffice_docx_prebuild_vulnerability_report.json"
        ),
        trivy_db_metadata_path=EVIDENCE / "genoffice_trivy_db_metadata.json",
    )


def test_supply_chain_admission_matches_exact_inventory_and_keeps_execution_closed() -> None:
    report = _build_report()

    assert report.sbom_component_count == 23
    assert report.scanner_package_count == 23
    assert "pkg:npm/emf-converter@2.0.2" in report.scanner_package_purls
    assert report.vulnerability_count == 0
    assert report.severity_counts == {"UNKNOWN": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    assert report.schema_validation_passed is True
    assert report.trivy_db_fresh_at_scan is True
    assert report.automated_sbom_and_vulnerability_gate_passed is True
    assert report.registry_signature_verified is False
    assert report.legal_review_complete is False
    assert report.source_import_allowed is False
    assert report.engine_execution_allowed is False
    assert report.production_use_allowed is False
    assert report.report_hash == build_genoffice_docx_supply_chain_report_hash(report)


def test_supply_chain_admission_rejects_scanner_inventory_drift(tmp_path: Path) -> None:
    vulnerability_report = json.loads(
        (EVIDENCE / "genoffice_docx_prebuild_vulnerability_report.json").read_text(encoding="utf-8")
    )
    vulnerability_report["Results"][0]["Packages"].pop()
    changed_path = tmp_path / "changed-trivy.json"
    changed_path.write_text(json.dumps(vulnerability_report), encoding="utf-8")

    with pytest.raises(GenOfficeDocxSupplyChainAdmissionError, match="does not exactly match"):
        _build_report(vulnerability_report_path=changed_path)


def test_committed_supply_chain_report_is_hash_valid_and_closed() -> None:
    report = load_genoffice_docx_supply_chain_admission_report(
        EVIDENCE / "genoffice_docx_supply_chain_admission_report.json"
    )

    assert report.automated_sbom_and_vulnerability_gate_passed is True
    assert report.source_import_allowed is False
    assert report.production_use_allowed is False
    assert report.report_hash == "sha256:580bd646106d79b712d42ecef490a8165435525a1feaeb52c10999274584767f"
    assert report.report_hash == build_genoffice_docx_supply_chain_report_hash(report)


def test_supply_chain_implementation_has_no_network_or_process_client() -> None:
    module_source = Path(supply_chain.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib"):
        assert f"import {forbidden}" not in module_source


def test_supply_chain_admission_compose_service_is_offline_and_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-docx-supply-chain-admission:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]

    assert 'profiles: ["office-supply-chain"]' in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "target: /trivy-cache\n        read_only: true" in service
