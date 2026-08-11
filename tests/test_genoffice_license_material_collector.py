from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from suite.operations.genoffice_docx_source_admission import GenOfficeRuntimeDependencyEvidence
from suite.operations.genoffice_license_material_collector import (
    GENOFFICE_NPM_REGISTRY_HOST,
    NODABLE_ENTITIES_REGISTRY_METADATA_URL,
    GenOfficeLicenseMaterialArtifact,
    GenOfficeLicenseMaterialCollectionError,
    _collect_nodable_license_source,
    _package_filename,
    _validated_registry_target,
    _verified_artifact,
    load_genoffice_license_material_collection_report,
    run_genoffice_license_material_collection_from_environment,
)

EVIDENCE = Path("docs/operations")


def _dependency(*, content: bytes = b"reviewed package bytes") -> GenOfficeRuntimeDependencyEvidence:
    integrity = base64.b64encode(hashlib.sha512(content).digest()).decode("ascii")
    return GenOfficeRuntimeDependencyEvidence(
        name="@scope/example",
        requested_range="^1.2.3",
        version="1.2.3",
        license_expression="MIT",
        resolved_url="https://registry.npmjs.org/@scope/example/-/example-1.2.3.tgz",
        integrity=f"sha512-{integrity}",
        dependencies=(),
        direct=True,
        install_script_declared=False,
        registry_source_verified=True,
        integrity_metadata_verified=True,
        license_metadata_present=True,
    )


def test_verified_artifact_binds_exact_lockfile_integrity() -> None:
    content = b"reviewed package bytes"
    artifact = _verified_artifact(dependency=_dependency(content=content), content=content)

    assert artifact.package_name == "@scope/example"
    assert artifact.artifact_filename == "scope__example-1.2.3.tgz"
    assert artifact.sha256 == f"sha256:{hashlib.sha256(content).hexdigest()}"
    assert artifact.integrity_verified is True


def test_verified_artifact_rejects_integrity_drift() -> None:
    with pytest.raises(GenOfficeLicenseMaterialCollectionError, match="integrity"):
        _verified_artifact(dependency=_dependency(), content=b"different bytes")


@pytest.mark.parametrize(
    "url",
    (
        "http://registry.npmjs.org/example/-/example-1.0.0.tgz",
        "https://example.com/example-1.0.0.tgz",
        "https://user:secret@registry.npmjs.org/example/-/example-1.0.0.tgz",
        "https://registry.npmjs.org:444/example/-/example-1.0.0.tgz",
    ),
)
def test_registry_target_rejects_unpinned_network_boundaries(url: str) -> None:
    with pytest.raises(GenOfficeLicenseMaterialCollectionError, match="pinned registry"):
        _validated_registry_target(url)


def test_registry_target_accepts_exact_https_registry() -> None:
    host, target = _validated_registry_target("https://registry.npmjs.org/example/-/example-1.0.0.tgz")

    assert host == GENOFFICE_NPM_REGISTRY_HOST
    assert target == "/example/-/example-1.0.0.tgz"
    assert _package_filename("@scope/example", "1.2.3") == "scope__example-1.2.3.tgz"


def test_environment_runner_requires_source_and_artifact_paths() -> None:
    with pytest.raises(GenOfficeLicenseMaterialCollectionError, match="paths are missing"):
        run_genoffice_license_material_collection_from_environment({})


def test_committed_license_material_report_is_complete_hash_valid_and_closed() -> None:
    report = load_genoffice_license_material_collection_report(
        EVIDENCE / "genoffice_license_material_collection_report.json"
    )

    assert report.report_hash == "sha256:2a75877f68e3e4f9ef11a648f0031bc184e97899c8533a67f4d1bd9c7fa40195"
    assert report.artifact_count == 21
    assert report.total_size_bytes == 997_020
    assert report.all_artifact_integrities_verified is True
    assert len(report.supplemental_source_artifacts) == 1
    assert report.supplemental_source_artifacts[0].source_archive_sha256 == (
        "sha256:2707baf03a5794a2f18d6af04d376561813e8b27a41fd46d43b85b22949f1e44"
    )
    assert report.legal_review_complete is False
    assert report.source_import_allowed is False
    assert report.worker_build_allowed is False
    assert report.production_use_allowed is False


def test_supplemental_source_rejects_registry_git_head_drift(tmp_path: Path) -> None:
    package = GenOfficeLicenseMaterialArtifact(
        package_name="@nodable/entities",
        package_version="3.0.0",
        resolved_url="https://registry.npmjs.org/@nodable/entities/-/entities-3.0.0.tgz",
        expected_integrity="sha512-" + base64.b64encode(hashlib.sha512(b"package").digest()).decode("ascii"),
        artifact_filename="nodable__entities-3.0.0.tgz",
        size_bytes=7,
        sha256=f"sha256:{hashlib.sha256(b'package').hexdigest()}",
        sha512=f"sha512:{hashlib.sha512(b'package').hexdigest()}",
        integrity_verified=True,
    )
    metadata = json.dumps(
        {
            "name": "@nodable/entities",
            "version": "3.0.0",
            "license": "MIT",
            "gitHead": "0" * 40,
            "repository": {"url": "git+https://github.com/nodable/val-parsers.git"},
            "dist": {"tarball": package.resolved_url, "integrity": package.expected_integrity},
        }
    ).encode()

    def metadata_fetcher(url: str, maximum_size: int) -> bytes:
        assert url == NODABLE_ENTITIES_REGISTRY_METADATA_URL
        assert len(metadata) <= maximum_size
        return metadata

    with pytest.raises(GenOfficeLicenseMaterialCollectionError, match="source identity"):
        _collect_nodable_license_source(
            artifact_directory=tmp_path,
            package_artifact=package,
            metadata_fetcher=metadata_fetcher,
            source_fetcher=lambda _url, _limit: pytest.fail("source download must not occur"),
        )


def test_collector_has_no_process_or_package_execution_path() -> None:
    module_source = Path("app/suite/operations/genoffice_license_material_collector.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "os.system", "Popen", "extractall", "npm ci", "node -"):
        assert forbidden not in module_source
    assert "credentials_used=False" in module_source
    assert "lifecycle_execution_performed=False" in module_source


def test_collector_compose_service_is_credentialless_and_narrowly_networked() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  genoffice-license-material-collector:", maxsplit=1)[1].split(
        "\n  genoffice-legal-review-dossier:", maxsplit=1
    )[0]

    assert 'profiles: ["office-supply-chain"]' in service
    assert "genoffice_license_material_download" in service
    assert "read_only: true" in service
    assert "no-new-privileges:true" in service
    assert "/source/genoffice-docx-source-admission-report.json:ro" in service
    assert "license-materials" in service
    assert "NPM_TOKEN" not in service
    assert "credential" not in service.lower()
