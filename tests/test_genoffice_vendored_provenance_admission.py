from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

import suite.operations.genoffice_vendored_provenance_admission as provenance
from suite.operations.genoffice_vendored_provenance_admission import (
    EMF_CONVERTER_PURL,
    GenOfficeVendoredProvenanceError,
    build_genoffice_vendored_provenance_report_hash,
    load_genoffice_vendored_provenance_report,
)

REPORT_PATH = Path("docs/operations/genoffice_vendored_provenance_report.json")


def test_committed_vendored_provenance_is_byte_exact_and_keeps_trust_boundary_closed() -> None:
    report = load_genoffice_vendored_provenance_report(REPORT_PATH)

    assert report.package_purl == EMF_CONVERTER_PURL
    assert report.package_archive_member_count == 7
    assert len(report.file_comparisons) == 3
    assert all(item.exact_match for item in report.file_comparisons)
    assert report.package_lifecycle_scripts == ()
    assert report.byte_provenance_verified is True
    assert report.registry_signature_metadata_present is True
    assert report.registry_attestation_metadata_present is True
    assert report.registry_signature_verified is False
    assert report.registry_attestation_verified is False
    assert report.legal_review_complete is False
    assert report.source_import_allowed is False
    assert report.production_use_allowed is False
    assert report.report_hash == "sha256:5ac1fdfa83034db3a8da06985b5f96e87a8eb0acfe3614f05b4fb3afe8e3dd04"
    assert report.report_hash == build_genoffice_vendored_provenance_report_hash(report)


def test_vendored_provenance_report_rejects_tampering(tmp_path: Path) -> None:
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    payload["file_comparisons"][0]["exact_match"] = False
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GenOfficeVendoredProvenanceError, match="report hash is invalid"):
        load_genoffice_vendored_provenance_report(changed_path)


def test_vendored_archive_reader_rejects_links(tmp_path: Path) -> None:
    archive_path = tmp_path / "package.tgz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        regular = tarfile.TarInfo("package/LICENSE")
        regular.size = 7
        archive.addfile(regular, io.BytesIO(b"license"))
        link = tarfile.TarInfo("package/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../etc/passwd"
        archive.addfile(link)

    with pytest.raises(GenOfficeVendoredProvenanceError, match="links or special files"):
        provenance._read_selected_archive_files(
            archive_path=archive_path,
            root="package",
            selected_paths=("package/LICENSE",),
            inspect_all_members=True,
        )


def test_vendored_provenance_implementation_has_no_network_or_process_client() -> None:
    module_source = Path(provenance.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib"):
        assert f"import {forbidden}" not in module_source
    assert "extractall" not in module_source
    assert "extract(" not in module_source


def test_vendored_provenance_compose_service_is_offline_and_inputs_are_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-vendored-provenance-admission:", maxsplit=1)[1].split(
        "\n  genoffice-docx-prebuild-sbom:", maxsplit=1
    )[0]

    assert 'profiles: ["office-supply-chain"]' in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "/source/genoffice.tar.gz:ro" in service
    assert "/source/emf-converter-2.0.2-metadata.json:ro" in service
    assert "/source/emf-converter-2.0.2.tgz:ro" in service
