from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

import suite.operations.genoffice_docx_source_admission as source_admission
from suite.operations.genoffice_docx_source_admission import (
    GENOFFICE_ARCHIVE_ROOT,
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeSourceAdmissionError,
    build_genoffice_docx_source_admission_report,
    build_genoffice_docx_source_admission_report_hash,
    load_genoffice_docx_source_admission_report,
    persist_genoffice_docx_source_admission_report,
)


def _package_lock(*, missing_license: bool = False, install_script: bool = False) -> dict[str, object]:
    pako: dict[str, object] = {
        "version": "1.0.11",
        "resolved": "https://registry.npmjs.org/pako/-/pako-1.0.11.tgz",
        "integrity": "sha512-pako",
        "license": "(MIT AND Zlib)",
    }
    if missing_license:
        pako.pop("license")
    if install_script:
        pako["hasInstallScript"] = True
    return {
        "name": "genoffice",
        "version": "0.1.0",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "name": "genoffice",
                "version": "0.1.0",
                "hasInstallScript": True,
                "license": "Apache-2.0",
            },
            "packages/docx-engine": {
                "name": "@genoffice/docx-engine",
                "version": "0.1.0",
                "license": "Apache-2.0",
                "dependencies": {"fast-xml-parser": "^5.3.4", "jszip": "^3.10.1"},
            },
            "node_modules/fast-xml-parser": {
                "version": "5.10.1",
                "resolved": "https://registry.npmjs.org/fast-xml-parser/-/fast-xml-parser-5.10.1.tgz",
                "integrity": "sha512-fast-xml-parser",
                "license": "MIT",
                "dependencies": {"strnum": "^2.4.1"},
            },
            "node_modules/jszip": {
                "version": "3.10.1",
                "resolved": "https://registry.npmjs.org/jszip/-/jszip-3.10.1.tgz",
                "integrity": "sha512-jszip",
                "license": "(MIT OR GPL-3.0-or-later)",
                "dependencies": {"pako": "~1.0.2"},
            },
            "node_modules/pako": pako,
            "node_modules/strnum": {
                "version": "2.4.1",
                "resolved": "https://registry.npmjs.org/strnum/-/strnum-2.4.1.tgz",
                "integrity": "sha512-strnum",
                "license": "MIT",
            },
        },
    }


def _archive_files(*, missing_license: bool = False, install_script: bool = False) -> dict[str, bytes]:
    root_package = {
        "name": "genoffice",
        "version": "0.1.0",
        "license": "Apache-2.0",
        "scripts": {"postinstall": "node scripts/install-electron.mjs", "test": "npm run test"},
    }
    engine_package = {
        "name": "@genoffice/docx-engine",
        "version": "0.1.0",
        "license": "Apache-2.0",
        "scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"},
        "dependencies": {"fast-xml-parser": "^5.3.4", "jszip": "^3.10.1"},
    }
    return {
        "LICENSE": b"Apache License Version 2.0\n",
        "package.json": json.dumps(root_package).encode(),
        "package-lock.json": json.dumps(
            _package_lock(missing_license=missing_license, install_script=install_script)
        ).encode(),
        "packages/docx-engine/package.json": json.dumps(engine_package).encode(),
        "packages/docx-engine/tsconfig.json": b"{}\n",
        "packages/docx-engine/src/index.ts": b"export const fixture = true;\n",
        "packages/docx-engine/src/vendor/emf-converter/LICENSE": b"Apache License Version 2.0\n",
        "packages/docx-engine/src/vendor/emf-converter/index.mjs": b"export default {};\n",
        "packages/docx-engine/tests/parse.test.ts": b"// evaluation fixture\n",
        "ee/LICENSE": b"not selected\n",
        "apps/shell/package.json": b"{}\n",
    }


def _write_archive(
    path: Path,
    *,
    files: dict[str, bytes] | None = None,
    unsafe_link: bool = False,
) -> str:
    with tarfile.open(path, mode="w:gz") as archive:
        root = tarfile.TarInfo(GENOFFICE_ARCHIVE_ROOT)
        root.type = tarfile.DIRTYPE
        root.mtime = 0
        archive.addfile(root)
        for relative_path, content in sorted((files or _archive_files()).items()):
            member = tarfile.TarInfo(f"{GENOFFICE_ARCHIVE_ROOT}/{relative_path}")
            member.size = len(content)
            member.mtime = 0
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
        if unsafe_link:
            member = tarfile.TarInfo(f"{GENOFFICE_ARCHIVE_ROOT}/packages/docx-engine/src/escape")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../../../etc/passwd"
            member.mtime = 0
            archive.addfile(member)
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _build_fixture_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing_license: bool = False,
    install_script: bool = False,
) -> GenOfficeDocxSourceAdmissionReport:
    archive_path = tmp_path / "genoffice.tar.gz"
    expected_hash = _write_archive(
        archive_path,
        files=_archive_files(missing_license=missing_license, install_script=install_script),
    )
    monkeypatch.setattr(source_admission, "GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256", expected_hash)
    return build_genoffice_docx_source_admission_report(
        archive_path=archive_path,
        expected_archive_sha256=expected_hash,
    )


def test_source_admission_verifies_snapshot_without_opening_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _build_fixture_report(tmp_path, monkeypatch)

    assert report.source_snapshot_verified is True
    assert report.snapshot_blocking_reasons == ()
    assert report.root_lifecycle_scripts == ("postinstall",)
    assert report.engine_lifecycle_scripts == ()
    assert report.direct_runtime_dependencies == ("fast-xml-parser", "jszip")
    assert report.runtime_dependency_count == 4
    assert report.prohibited_scopes_present_upstream == ("apps/shell/**", "ee/**")
    assert report.prohibited_scopes_excluded_from_manifest is True
    assert report.vendored_components[0].license_files == ("packages/docx-engine/src/vendor/emf-converter/LICENSE",)
    assert report.lifecycle_execution_prevented is True
    assert report.engine_execution_allowed is False
    assert report.source_import_allowed is False
    assert report.production_use_allowed is False
    assert report.legal_review_complete is False
    assert report.sbom_complete is False
    assert report.report_hash == build_genoffice_docx_source_admission_report_hash(report)


def test_source_admission_report_round_trip_detects_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = _build_fixture_report(tmp_path, monkeypatch)
    report_path = tmp_path / "report.json"
    persist_genoffice_docx_source_admission_report(report=report, report_path=report_path)

    loaded = load_genoffice_docx_source_admission_report(report_path)
    assert loaded == report

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["selected_file_count"] += 1
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GenOfficeSourceAdmissionError, match="report hash is invalid"):
        load_genoffice_docx_source_admission_report(report_path)


def test_committed_exact_source_admission_report_is_hash_valid_and_closed() -> None:
    report = load_genoffice_docx_source_admission_report(
        Path("docs/operations/genoffice_docx_source_admission_report.json")
    )

    assert report.archive_member_count == 1396
    assert report.archive_size_bytes == 15_530_618
    assert report.selected_file_count == 93
    assert report.selected_total_size_bytes == 1_605_672
    assert report.runtime_dependency_count == 21
    assert report.source_manifest_hash == "sha256:27b3ff723354bf3dad848b0f3f781b0c54712fbbb8c1942ceddc346066a4636d"
    assert report.runtime_dependency_manifest_hash == (
        "sha256:821aa8dd4d1b647dca34f7f0e8f2daf033ff1cea5b47dd40979ed0d5caffd733"
    )
    assert report.source_snapshot_verified is True
    assert report.engine_execution_allowed is False
    assert report.source_import_allowed is False
    assert report.production_use_allowed is False
    assert report.report_hash == "sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d"


def test_source_admission_rejects_unreviewed_archive_hash(tmp_path: Path) -> None:
    archive_path = tmp_path / "genoffice.tar.gz"
    _write_archive(archive_path)

    with pytest.raises(GenOfficeSourceAdmissionError, match="SHA-256 does not match"):
        build_genoffice_docx_source_admission_report(archive_path=archive_path)


def test_source_admission_rejects_links_even_with_matching_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = tmp_path / "genoffice.tar.gz"
    expected_hash = _write_archive(archive_path, unsafe_link=True)
    monkeypatch.setattr(source_admission, "GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256", expected_hash)

    with pytest.raises(GenOfficeSourceAdmissionError, match="links or special files"):
        build_genoffice_docx_source_admission_report(
            archive_path=archive_path,
            expected_archive_sha256=expected_hash,
        )


@pytest.mark.parametrize(
    ("missing_license", "install_script", "expected_reason"),
    [
        (True, False, "runtime_dependency_license_missing:pako"),
        (False, True, "runtime_dependency_install_script_declared:pako"),
    ],
)
def test_source_admission_reports_dependency_policy_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_license: bool,
    install_script: bool,
    expected_reason: str,
) -> None:
    report = _build_fixture_report(
        tmp_path,
        monkeypatch,
        missing_license=missing_license,
        install_script=install_script,
    )

    assert report.source_snapshot_verified is False
    assert expected_reason in report.snapshot_blocking_reasons


def test_source_admission_implementation_has_no_execution_or_network_client() -> None:
    module_source = Path(source_admission.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "npm", "node_modules/.bin"):
        assert f"import {forbidden}" not in module_source
    assert "extractall" not in module_source
    assert "extract(" not in module_source


def test_source_admission_compose_profile_is_read_only_and_offline() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-docx-source-admission:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]

    assert 'profiles: ["office-source-admission"]' in service
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "cap_drop:" in service
    assert "SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH: /source/genoffice.tar.gz" in service
    assert "target: /source/genoffice.tar.gz" in service
    assert "SUITE_GENOFFICE_SOURCE_ARCHIVE_HOST_PATH" in service
