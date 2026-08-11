from __future__ import annotations

from pathlib import Path

import pytest

from suite.operations.genoffice_legal_review_dossier import load_genoffice_legal_review_dossier
from suite.operations.genoffice_third_party_notice import (
    GenOfficeThirdPartyNoticeError,
    _required_dependency_files,
    _selected_distribution_expression,
    run_genoffice_third_party_notice_from_environment,
)

EVIDENCE = Path("docs/operations")


def test_internal_distribution_choices_are_exact_and_cumulative() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    dependencies = {item.package_name: item for item in dossier.dependency_licenses}

    assert _selected_distribution_expression(dependencies["jszip"]) == "MIT"
    assert _selected_distribution_expression(dependencies["pako"]) == "MIT AND Zlib"
    assert _selected_distribution_expression(dependencies["fast-xml-parser"]) == "MIT"


def test_notice_file_selection_covers_every_required_license_marker() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    dependencies = {item.package_name: item for item in dossier.dependency_licenses}
    evidence_by_package = {
        name: tuple(item for item in dossier.dependency_legal_files if item.package_name == name)
        for name in ("@nodable/entities", "isarray", "pako")
    }

    for name, evidence in evidence_by_package.items():
        selected = _required_dependency_files(dependency=dependencies[name], evidence=evidence)
        detected = {marker for item in selected for marker in item.detected_markers}
        assert set(dependencies[name].required_text_markers).issubset(detected)


def test_notice_environment_runner_requires_all_evidence_paths() -> None:
    with pytest.raises(GenOfficeThirdPartyNoticeError, match="paths are missing"):
        run_genoffice_third_party_notice_from_environment({})


def test_notice_builder_is_offline_and_never_executes_or_extracts_archives() -> None:
    module_source = Path("app/suite/operations/genoffice_third_party_notice.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "extractall", "extract("):
        assert f"import {forbidden}" not in module_source
    assert "source_import_allowed: bool = False" in module_source
    assert "production_use_allowed: bool = False" in module_source


def test_notice_builder_compose_service_is_offline_and_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-third-party-notice-builder:", maxsplit=1)[1].split(
        "\n  genoffice-internal-oss-schema:", maxsplit=1
    )[0]

    assert 'profiles: ["office-supply-chain"]' in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "GENOFFICE_THIRD_PARTY_NOTICES.txt" in service
