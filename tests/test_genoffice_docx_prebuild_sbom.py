from __future__ import annotations

import json
from pathlib import Path

import pytest

import suite.operations.genoffice_docx_prebuild_sbom as prebuild_sbom
from suite.operations.genoffice_docx_prebuild_sbom import (
    GenOfficeDocxPrebuildSbomError,
    build_genoffice_docx_prebuild_sbom,
    genoffice_docx_prebuild_sbom_hash,
    load_genoffice_docx_prebuild_sbom,
    persist_genoffice_docx_prebuild_sbom,
)
from suite.operations.genoffice_docx_source_admission import load_genoffice_docx_source_admission_report
from suite.operations.genoffice_vendored_provenance_admission import load_genoffice_vendored_provenance_report

SOURCE_REPORT_PATH = Path("docs/operations/genoffice_docx_source_admission_report.json")
VENDORED_PROVENANCE_PATH = Path("docs/operations/genoffice_vendored_provenance_report.json")


def test_prebuild_sbom_is_deterministic_complete_and_keeps_execution_closed() -> None:
    report = load_genoffice_docx_source_admission_report(SOURCE_REPORT_PATH)
    provenance = load_genoffice_vendored_provenance_report(VENDORED_PROVENANCE_PATH)

    first = build_genoffice_docx_prebuild_sbom(report, provenance)
    second = build_genoffice_docx_prebuild_sbom(report, provenance)

    assert first == second
    assert first["specVersion"] == "1.6"
    assert first["metadata"]["lifecycles"] == [{"phase": "pre-build"}]
    assert len(first["components"]) == 22
    assert len(first["dependencies"]) == 23
    assert "timestamp" not in first["metadata"]
    assert "serialNumber" not in first
    root = first["metadata"]["component"]
    assert root["purl"] == "pkg:npm/%40genoffice/docx-engine@0.1.0"
    assert any(
        component["purl"] == "pkg:npm/%40nodable/entities@3.0.0"
        for component in first["components"]
        if "purl" in component
    )
    vendored = [component for component in first["components"] if component["name"] == "emf-converter"]
    assert len(vendored) == 1
    assert vendored[0]["version"] == "2.0.2"
    assert vendored[0]["purl"] == "pkg:npm/emf-converter@2.0.2"
    assert any(
        property_["name"] == "collabio:genoffice:byte-provenance" and property_["value"] == "verified"
        for property_ in vendored[0]["properties"]
    )
    root_edge = next(edge for edge in first["dependencies"] if edge["ref"] == root["bom-ref"])
    assert len(root_edge["dependsOn"]) == 3


def test_prebuild_sbom_round_trip_rejects_extra_component(tmp_path: Path) -> None:
    report = load_genoffice_docx_source_admission_report(SOURCE_REPORT_PATH)
    provenance = load_genoffice_vendored_provenance_report(VENDORED_PROVENANCE_PATH)
    sbom = build_genoffice_docx_prebuild_sbom(report, provenance)
    sbom_path = tmp_path / "genoffice.cdx.json"
    persist_genoffice_docx_prebuild_sbom(sbom=sbom, sbom_path=sbom_path)

    loaded = load_genoffice_docx_prebuild_sbom(
        sbom_path=sbom_path,
        source_report=report,
        vendored_provenance=provenance,
    )
    assert loaded == sbom

    payload = json.loads(sbom_path.read_text(encoding="utf-8"))
    payload["components"].append({"type": "library", "name": "unreviewed"})
    sbom_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GenOfficeDocxPrebuildSbomError, match="does not match"):
        load_genoffice_docx_prebuild_sbom(
            sbom_path=sbom_path,
            source_report=report,
            vendored_provenance=provenance,
        )


def test_prebuild_sbom_rejects_malformed_integrity() -> None:
    with pytest.raises(GenOfficeDocxPrebuildSbomError, match="malformed"):
        prebuild_sbom._integrity_sha512_hex("sha512-not-valid-base64!")


def test_prebuild_sbom_hash_covers_exact_serialization() -> None:
    report = load_genoffice_docx_source_admission_report(SOURCE_REPORT_PATH)
    provenance = load_genoffice_vendored_provenance_report(VENDORED_PROVENANCE_PATH)
    sbom = build_genoffice_docx_prebuild_sbom(report, provenance)

    assert genoffice_docx_prebuild_sbom_hash(sbom).startswith("sha256:")
    assert len(genoffice_docx_prebuild_sbom_hash(sbom)) == 71


def test_committed_prebuild_sbom_matches_reviewed_evidence_hash() -> None:
    report = load_genoffice_docx_source_admission_report(SOURCE_REPORT_PATH)
    provenance = load_genoffice_vendored_provenance_report(VENDORED_PROVENANCE_PATH)
    sbom = load_genoffice_docx_prebuild_sbom(
        sbom_path=Path("docs/operations/genoffice_docx_prebuild.cdx.json"),
        source_report=report,
        vendored_provenance=provenance,
    )

    assert genoffice_docx_prebuild_sbom_hash(sbom) == (
        "sha256:c5e8678efe9b0dc3f8e64a978eacfe43fd9fae6a9e63c8bb74d94b0c1a8b43f0"
    )


def test_prebuild_sbom_implementation_has_no_network_or_process_client() -> None:
    module_source = Path(prebuild_sbom.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib.request"):
        assert f"import {forbidden}" not in module_source


def test_prebuild_sbom_compose_services_separate_offline_generation_and_validation() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    generator = compose.split("  genoffice-docx-prebuild-sbom:", maxsplit=1)[1].split(
        "\n  genoffice-docx-sbom-validator:", maxsplit=1
    )[0]
    validator = compose.split("  genoffice-docx-sbom-validator:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]

    assert 'profiles: ["office-supply-chain"]' in generator
    assert 'network_mode: "none"' in generator
    assert "read_only: true" in generator
    assert "source: ./docs/operations/genoffice_docx_source_admission_report.json" in generator
    validator_image = "cyclonedx/cyclonedx-cli@sha256:9a858a15e7b0843606efc0ff19d5f7575011a5428d7f3d343b4f6cf09d8f0d4e"
    assert validator_image in validator
    assert 'network_mode: "none"' in validator
    assert "--input-version v1_6" in validator
    assert "--fail-on-errors" in validator


def test_prebuild_vulnerability_scan_separates_networked_db_update_from_offline_scan() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    updater = compose.split("  genoffice-trivy-db-update:", maxsplit=1)[1].split(
        "\n  genoffice-docx-sbom-vulnerability-scan:", maxsplit=1
    )[0]
    scanner = compose.split("  genoffice-docx-sbom-vulnerability-scan:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]
    trivy_image = "aquasec/trivy@sha256:7cced7cae583819fc7806d4cbc0dbbc7cad18b99f7d3e235192e6da8c091045c"

    assert trivy_image in updater
    assert "--download-db-only" in updater
    assert "genoffice_supply_chain_updates" in updater
    assert "network_mode" not in updater
    assert trivy_image in scanner
    assert 'network_mode: "none"' in scanner
    assert "--skip-db-update" in scanner
    assert "--skip-java-db-update" in scanner
    assert "--skip-vex-repo-update" in scanner
    assert "--offline-scan" in scanner
    assert "--skip-version-check" in scanner
    assert "--disable-telemetry" in scanner
    assert "target: /trivy-cache\n        read_only: true" in scanner
