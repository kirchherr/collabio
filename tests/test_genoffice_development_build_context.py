from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

import suite.operations.genoffice_development_build_context as build_context
import suite.operations.genoffice_docx_source_admission as source_admission
from suite.operations.genoffice_development_build_context import (
    GENOFFICE_BUILD_CONTEXT_MANIFEST_PATH,
    GENOFFICE_NOTICE_CONTEXT_PATH,
    GenOfficeDevelopmentBuildContextError,
    build_genoffice_development_build_context,
    build_genoffice_development_build_context_report_hash,
    run_genoffice_development_build_context_from_environment,
)
from suite.operations.genoffice_docx_source_admission import (
    GENOFFICE_ARCHIVE_ROOT,
    GenOfficeDocxSourceAdmissionReport,
    build_genoffice_docx_source_admission_report,
    build_genoffice_docx_source_admission_report_hash,
)
from suite.operations.genoffice_docx_supply_chain_admission import (
    GenOfficeDocxSupplyChainAdmissionReport,
    build_genoffice_docx_supply_chain_report_hash,
    load_genoffice_docx_supply_chain_admission_report,
)
from suite.operations.genoffice_internal_oss_admission import (
    GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
    GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
    GenOfficeInternalOssAdmissionReport,
    build_genoffice_internal_oss_admission_report_hash,
)
from suite.operations.genoffice_legal_review_dossier import GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH
from suite.operations.genoffice_npm_provenance_admission import (
    GenOfficeNpmProvenanceAdmissionReport,
    load_genoffice_npm_provenance_admission_report,
)
from suite.operations.genoffice_third_party_notice import GENOFFICE_SELECTED_SOURCE_SCOPE

EVIDENCE = Path("docs/operations")


def _package_lock() -> dict[str, object]:
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
            "node_modules/pako": {
                "version": "1.0.11",
                "resolved": "https://registry.npmjs.org/pako/-/pako-1.0.11.tgz",
                "integrity": "sha512-pako",
                "license": "(MIT AND Zlib)",
            },
            "node_modules/strnum": {
                "version": "2.4.1",
                "resolved": "https://registry.npmjs.org/strnum/-/strnum-2.4.1.tgz",
                "integrity": "sha512-strnum",
                "license": "MIT",
            },
        },
    }


def _source_files() -> dict[str, bytes]:
    return {
        "LICENSE": b"Apache License Version 2.0\n",
        "package.json": json.dumps(
            {
                "name": "genoffice",
                "version": "0.1.0",
                "license": "Apache-2.0",
                "scripts": {"postinstall": "node scripts/install-electron.mjs"},
            }
        ).encode(),
        "package-lock.json": json.dumps(_package_lock()).encode(),
        "packages/docx-engine/package.json": json.dumps(
            {
                "name": "@genoffice/docx-engine",
                "version": "0.1.0",
                "license": "Apache-2.0",
                "dependencies": {"fast-xml-parser": "^5.3.4", "jszip": "^3.10.1"},
            }
        ).encode(),
        "packages/docx-engine/tsconfig.json": b"{}\n",
        "packages/docx-engine/src/index.ts": b"export const fixture = true;\n",
        "packages/docx-engine/src/vendor/emf-converter/LICENSE": b"Apache License Version 2.0\n",
        "packages/docx-engine/src/vendor/emf-converter/index.mjs": b"export default {};\n",
        "packages/docx-engine/tests/parse.test.ts": b"// evaluation fixture\n",
        "ee/LICENSE": b"not selected\n",
    }


def _write_source_archive(path: Path, files: dict[str, bytes] | None = None) -> str:
    with tarfile.open(path, mode="w:gz") as archive:
        root = tarfile.TarInfo(GENOFFICE_ARCHIVE_ROOT)
        root.type = tarfile.DIRTYPE
        root.mtime = 0
        archive.addfile(root)
        for relative_path, content in sorted((files or _source_files()).items()):
            member = tarfile.TarInfo(f"{GENOFFICE_ARCHIVE_ROOT}/{relative_path}")
            member.size = len(content)
            member.mode = 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(content))
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _internal_admission(notice: bytes) -> GenOfficeInternalOssAdmissionReport:
    draft = GenOfficeInternalOssAdmissionReport(
        legal_dossier_report_hash=GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH,
        third_party_notice_report_hash="sha256:" + "1" * 64,
        third_party_notice_artifact_sha256=f"sha256:{hashlib.sha256(notice).hexdigest()}",
        decision_payload_hash="sha256:" + "2" * 64,
        decision_record_hash="sha256:" + "3" * 64,
        signer_policy_hash="sha256:" + "4" * 64,
        approved_usage_profiles=("development_evaluation",),
        blocked_usage_profiles=GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
        approved_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        prohibited_source_scopes=GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
        internal_oss_decision_verified=True,
        two_person_control_verified=True,
        detached_signatures_verified=True,
        notice_distribution_artifact_verified=True,
        dependency_license_resolutions_verified=True,
        change_reevaluation_required=True,
        development_build_context_materialization_allowed=True,
        reproducible_worker_build_allowed=True,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(
        update={"report_hash": build_genoffice_internal_oss_admission_report_hash(draft)}
    )


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    Path,
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeDocxSupplyChainAdmissionReport,
    GenOfficeNpmProvenanceAdmissionReport,
    GenOfficeInternalOssAdmissionReport,
    bytes,
]:
    archive_path = tmp_path / "genoffice.tar.gz"
    archive_hash = _write_source_archive(archive_path)
    monkeypatch.setattr(source_admission, "GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256", archive_hash)
    source_report = build_genoffice_docx_source_admission_report(
        archive_path=archive_path,
        expected_archive_sha256=archive_hash,
    )
    monkeypatch.setattr(build_context, "GENOFFICE_REVIEWED_SOURCE_REPORT_HASH", source_report.report_hash)
    supply = load_genoffice_docx_supply_chain_admission_report(
        EVIDENCE / "genoffice_docx_supply_chain_admission_report.json"
    )
    supply_draft = supply.model_copy(
        update={
            "source_report_hash": source_report.report_hash,
            "source_archive_sha256": source_report.archive_sha256,
            "report_hash": "sha256:" + "0" * 64,
        }
    )
    supply = supply_draft.model_copy(
        update={"report_hash": build_genoffice_docx_supply_chain_report_hash(supply_draft)}
    )
    monkeypatch.setattr(build_context, "GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH", supply.report_hash)
    npm_provenance = load_genoffice_npm_provenance_admission_report(
        EVIDENCE / "genoffice_npm_provenance_admission_report.json"
    )
    notice = b"Collabio deterministic development notice\n"
    return archive_path, source_report, supply, npm_provenance, _internal_admission(notice), notice


def test_build_context_is_deterministic_normalized_and_non_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, source, supply, npm_provenance, admission, notice = _fixture(tmp_path, monkeypatch)

    first_context, first_report = build_genoffice_development_build_context(
        archive_path=archive,
        source_report=source,
        supply_chain_report=supply,
        npm_provenance_report=npm_provenance,
        internal_oss_admission_report=admission,
        notice_artifact=notice,
        source_date_epoch=0,
    )
    second_context, second_report = build_genoffice_development_build_context(
        archive_path=archive,
        source_report=source,
        supply_chain_report=supply,
        npm_provenance_report=npm_provenance,
        internal_oss_admission_report=admission,
        notice_artifact=notice,
        source_date_epoch=0,
    )

    assert first_context == second_context
    assert first_report == second_report
    assert first_report.report_hash == build_genoffice_development_build_context_report_hash(first_report)
    assert first_report.context_file_count == source.selected_file_count + 2
    assert first_report.worker_image_built is False
    assert first_report.engine_execution_allowed is False
    with tarfile.open(fileobj=io.BytesIO(first_context), mode="r:") as context_archive:
        members = context_archive.getmembers()
        assert tuple(item.name for item in members) == tuple(sorted(item.name for item in members))
        assert GENOFFICE_BUILD_CONTEXT_MANIFEST_PATH in {item.name for item in members}
        assert GENOFFICE_NOTICE_CONTEXT_PATH in {item.name for item in members}
        assert "package.json" not in {item.name for item in members}
        assert ".collabio/upstream/package.json" in {item.name for item in members}
        assert all((item.uid, item.gid, item.mode, item.mtime) == (0, 0, 0o644, 0) for item in members)


def test_build_context_rejects_missing_or_closed_internal_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, source, supply, npm_provenance, admission, notice = _fixture(tmp_path, monkeypatch)
    closed = admission.model_copy(update={"development_build_context_materialization_allowed": False})
    closed = closed.model_copy(update={"report_hash": build_genoffice_internal_oss_admission_report_hash(closed)})

    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="does not authorize"):
        build_genoffice_development_build_context(
            archive_path=archive,
            source_report=source,
            supply_chain_report=supply,
            npm_provenance_report=npm_provenance,
            internal_oss_admission_report=closed,
            notice_artifact=notice,
            source_date_epoch=0,
        )
    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="values are missing"):
        run_genoffice_development_build_context_from_environment({})


def test_build_context_rejects_archive_and_selected_file_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, source, supply, npm_provenance, admission, notice = _fixture(tmp_path, monkeypatch)
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="archive bytes drifted"):
        build_genoffice_development_build_context(
            archive_path=archive,
            source_report=source,
            supply_chain_report=supply,
            npm_provenance_report=npm_provenance,
            internal_oss_admission_report=admission,
            notice_artifact=notice,
            source_date_epoch=0,
        )

    archive_hash = _write_source_archive(archive)
    source_files = list(source.source_files)
    source_files[0] = source_files[0].model_copy(update={"sha256": "sha256:" + "f" * 64})
    drifted_source = source.model_copy(
        update={
            "archive_sha256": archive_hash,
            "expected_archive_sha256": archive_hash,
            "source_files": tuple(source_files),
            "report_hash": "sha256:" + "0" * 64,
        }
    )
    drifted_source = drifted_source.model_copy(
        update={"report_hash": build_genoffice_docx_source_admission_report_hash(drifted_source)}
    )
    monkeypatch.setattr(build_context, "GENOFFICE_REVIEWED_SOURCE_REPORT_HASH", drifted_source.report_hash)
    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="source manifest is invalid"):
        build_genoffice_development_build_context(
            archive_path=archive,
            source_report=drifted_source,
            supply_chain_report=supply,
            npm_provenance_report=npm_provenance,
            internal_oss_admission_report=admission,
            notice_artifact=notice,
            source_date_epoch=0,
        )


def test_build_context_rejects_supply_chain_and_notice_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, source, supply, npm_provenance, admission, notice = _fixture(tmp_path, monkeypatch)
    failed_supply = supply.model_copy(update={"automated_sbom_and_vulnerability_gate_passed": False})
    failed_supply = failed_supply.model_copy(
        update={"report_hash": build_genoffice_docx_supply_chain_report_hash(failed_supply)}
    )
    monkeypatch.setattr(build_context, "GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH", failed_supply.report_hash)

    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="does not match"):
        build_genoffice_development_build_context(
            archive_path=archive,
            source_report=source,
            supply_chain_report=failed_supply,
            npm_provenance_report=npm_provenance,
            internal_oss_admission_report=admission,
            notice_artifact=notice,
            source_date_epoch=0,
        )
    monkeypatch.setattr(build_context, "GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH", supply.report_hash)
    with pytest.raises(GenOfficeDevelopmentBuildContextError, match="notice"):
        build_genoffice_development_build_context(
            archive_path=archive,
            source_report=source,
            supply_chain_report=supply,
            npm_provenance_report=npm_provenance,
            internal_oss_admission_report=admission,
            notice_artifact=notice + b"tampered",
            source_date_epoch=0,
        )


def test_build_context_implementation_has_no_execution_network_or_unsafe_extraction() -> None:
    source = Path(build_context.__file__).read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "npm", "node_modules/.bin"):
        assert f"import {forbidden}" not in source
    assert "extractall" not in source
    assert ".extract(" not in source
    assert "extractfile" in source


def test_build_context_compose_service_is_offline_read_only_and_admission_bound() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-development-build-context:", maxsplit=1)[1].split(
        "\n  genoffice-docx-prebuild-sbom:", maxsplit=1
    )[0]

    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "genoffice-internal-oss-admission-report.json" in service
    assert "genoffice-development-build-context.tar" in service
    assert "SUITE_GENOFFICE_SOURCE_ARCHIVE_HOST_PATH" in service
