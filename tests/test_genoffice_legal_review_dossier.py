from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from suite.operations.genoffice_legal_review_dossier import (
    GENOFFICE_APPROVABLE_SOURCE_SCOPES,
    GENOFFICE_LEGAL_DECISION_RECORD_SCHEMA_VERSION,
    GENOFFICE_REQUIRED_TRADEMARK_POLICY,
    GenOfficeLegalDecisionRecord,
    GenOfficeLegalReviewDossierError,
    _license_semantics,
    _read_package_legal_files,
    _read_supplemental_source_license,
    _required_markers,
    _text_markers,
    run_genoffice_legal_review_dossier_from_environment,
)
from suite.operations.genoffice_license_material_collector import GenOfficeSupplementalLicenseSourceArtifact


def _package_archive(path: Path, *, unsafe_link: bool = False) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        root = tarfile.TarInfo("package")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        license_text = (
            b"Permission is hereby granted, free of charge, to any person obtaining a copy.\n"
            b"Altered source versions must be plainly marked.\n"
        )
        license_file = tarfile.TarInfo("package/LICENSE")
        license_file.size = len(license_text)
        archive.addfile(license_file, io.BytesIO(license_text))
        if unsafe_link:
            link = tarfile.TarInfo("package/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)


def test_package_legal_reader_selects_text_without_extracting(tmp_path: Path) -> None:
    archive_path = tmp_path / "package.tgz"
    _package_archive(archive_path)

    files = _read_package_legal_files(archive_path)

    assert tuple(files) == ("LICENSE",)
    assert set(_text_markers(files["LICENSE"])) == {"mit_grant_text", "zlib_terms_text"}


def test_package_legal_reader_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "package.tgz"
    _package_archive(archive_path, unsafe_link=True)

    with pytest.raises(GenOfficeLegalReviewDossierError, match="links or special files"):
        _read_package_legal_files(archive_path)


def test_supplemental_source_reader_binds_root_license_to_commit(tmp_path: Path) -> None:
    commit = "d2070d76a8ba07e6c7fa142caeb51ffd756e47eb"
    archive_path = tmp_path / "source.tar.gz"
    license_text = b"Permission is hereby granted, free of charge, to any person obtaining a copy.\n"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo(f"val-parsers-{commit}")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        license_file = tarfile.TarInfo(f"val-parsers-{commit}/LICENSE")
        license_file.size = len(license_text)
        archive.addfile(license_file, io.BytesIO(license_text))
    supplemental = GenOfficeSupplementalLicenseSourceArtifact(
        package_name="@nodable/entities",
        package_version="3.0.0",
        reason="published_package_omits_full_license_text",
        repository_url="git+https://github.com/nodable/val-parsers.git",
        source_commit=commit,
        registry_metadata_url="https://registry.npmjs.org/@nodable%2Fentities/3.0.0",
        registry_metadata_filename="metadata.json",
        registry_metadata_sha256="sha256:" + "0" * 64,
        source_archive_url=f"https://codeload.github.com/nodable/val-parsers/tar.gz/{commit}",
        source_archive_filename="source.tar.gz",
        source_archive_size_bytes=archive_path.stat().st_size,
        source_archive_sha256="sha256:" + "1" * 64,
        source_archive_integrity_verified=True,
    )

    assert (
        _read_supplemental_source_license(
            archive_path=archive_path,
            supplemental=supplemental,
        )
        == license_text
    )


def test_compound_license_semantics_are_explicit() -> None:
    assert _license_semantics("(MIT OR GPL-3.0-or-later)") == "choice"
    assert _required_markers("(MIT OR GPL-3.0-or-later)") == ("mit_grant_text",)
    assert _license_semantics("(MIT AND Zlib)") == "cumulative"
    assert _required_markers("(MIT AND Zlib)") == ("mit_grant_text", "zlib_terms_text")

    with pytest.raises(GenOfficeLegalReviewDossierError, match="unreviewed"):
        _license_semantics("LicenseRef-Unknown")


def test_human_decision_schema_requires_separate_signed_record() -> None:
    schema = GenOfficeLegalDecisionRecord.model_json_schema()
    required = set(schema["required"])

    assert GENOFFICE_LEGAL_DECISION_RECORD_SCHEMA_VERSION == "genoffice_legal_decision_record.v1"
    assert GENOFFICE_APPROVABLE_SOURCE_SCOPES == ("packages/docx-engine/**",)
    assert GENOFFICE_REQUIRED_TRADEMARK_POLICY == "collabio_brand_only_no_genoffice_or_genspark_marks"
    assert {
        "dossier_report_hash",
        "decision",
        "reviewer_id",
        "reviewer_professional_role",
        "legal_opinion_ref",
        "approved_source_scopes",
        "prohibited_source_scopes",
        "trademark_policy",
        "notice_distribution_artifact_sha256",
        "question_resolutions",
        "dependency_license_resolutions",
        "detached_signature_verification_evidence_hash",
        "record_hash",
    }.issubset(required)


def test_environment_runner_requires_every_evidence_path() -> None:
    with pytest.raises(GenOfficeLegalReviewDossierError, match="paths are missing"):
        run_genoffice_legal_review_dossier_from_environment({})


def test_legal_dossier_module_is_offline_and_never_executes_or_extracts_archives() -> None:
    module_source = Path("app/suite/operations/genoffice_legal_review_dossier.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "extractall", "extract("):
        assert f"import {forbidden}" not in module_source
    assert "source_import_allowed: bool = False" in module_source
    assert "reproducible_worker_build_allowed: bool = False" in module_source


def test_legal_dossier_compose_service_is_offline_and_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-legal-review-dossier:", maxsplit=1)[1].split(
        "\n  genoffice-docx-prebuild-sbom:", maxsplit=1
    )[0]

    assert 'profiles: ["office-supply-chain"]' in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "/source/genoffice.tar.gz:ro" in service
    assert "genoffice-legal-decision-record.schema.json" in service
