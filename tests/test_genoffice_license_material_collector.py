from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from suite.operations.genoffice_docx_source_admission import GenOfficeRuntimeDependencyEvidence
from suite.operations.genoffice_license_material_collector import (
    GENOFFICE_NPM_REGISTRY_HOST,
    GenOfficeLicenseMaterialCollectionError,
    _package_filename,
    _validated_registry_target,
    _verified_artifact,
    run_genoffice_license_material_collection_from_environment,
)


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
