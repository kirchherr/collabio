from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_source_admission import (
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeRuntimeDependencyEvidence,
    GenOfficeSourceAdmissionError,
    build_genoffice_docx_source_admission_report_hash,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_vendored_provenance_admission import (
    GenOfficeVendoredProvenanceAdmissionReport,
    GenOfficeVendoredProvenanceError,
    build_genoffice_vendored_provenance_report_hash,
    load_genoffice_vendored_provenance_report,
)

GENOFFICE_DOCX_PREBUILD_SBOM_SCHEMA_VERSION = "genoffice_docx_prebuild_sbom.v1"
GENOFFICE_DOCX_CYCLONEDX_SPEC_VERSION = "1.6"
GENOFFICE_DOCX_SBOM_GENERATOR_VERSION = "1"
GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH = "sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d"
GENOFFICE_DOCX_SBOM_TOOL_REF = "pkg:generic/collabio-genoffice-docx-prebuild-sbom@1"


class GenOfficeDocxPrebuildSbomError(ValueError):
    pass


def _hash_content(value: str, *, algorithm: str) -> str:
    prefix = algorithm.lower() + ":"
    if not value.startswith(prefix):
        raise GenOfficeDocxPrebuildSbomError(f"Expected {algorithm.upper()} hash")
    content = value.removeprefix(prefix)
    expected_length = hashlib.new(algorithm).digest_size * 2
    if len(content) != expected_length or any(character not in "0123456789abcdef" for character in content):
        raise GenOfficeDocxPrebuildSbomError(f"Invalid {algorithm.upper()} hash")
    return content


def _integrity_sha512_hex(integrity: str | None) -> str:
    if integrity is None or not integrity.startswith("sha512-") or " " in integrity:
        raise GenOfficeDocxPrebuildSbomError("Runtime dependency does not have one SHA-512 integrity value")
    try:
        decoded = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeDocxPrebuildSbomError("Runtime dependency SHA-512 integrity is malformed") from exc
    if len(decoded) != hashlib.sha512().digest_size:
        raise GenOfficeDocxPrebuildSbomError("Runtime dependency SHA-512 integrity has the wrong length")
    return decoded.hex()


def _npm_identity(name: str) -> tuple[str | None, str]:
    if not name.startswith("@"):
        return None, name
    parts = name.split("/", maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise GenOfficeDocxPrebuildSbomError("Scoped npm dependency name is malformed")
    return parts[0], parts[1]


def _npm_purl(name: str, version: str | None) -> str:
    if not version:
        raise GenOfficeDocxPrebuildSbomError(f"Runtime dependency {name} has no version")
    group, package_name = _npm_identity(name)
    package_path = quote(package_name, safe=".-_~")
    if group is not None:
        package_path = f"{quote(group, safe='.-_~')}/{package_path}"
    return f"pkg:npm/{package_path}@{quote(version, safe='.-_~')}"


def _properties(values: Mapping[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in sorted(values.items())]


def _npm_component(dependency: GenOfficeRuntimeDependencyEvidence) -> dict[str, Any]:
    if not dependency.license_expression:
        raise GenOfficeDocxPrebuildSbomError(f"Runtime dependency {dependency.name} has no license expression")
    if not dependency.resolved_url:
        raise GenOfficeDocxPrebuildSbomError(f"Runtime dependency {dependency.name} has no distribution URL")
    group, package_name = _npm_identity(dependency.name)
    purl = _npm_purl(dependency.name, dependency.version)
    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": purl,
        "name": package_name,
        "version": dependency.version,
        "hashes": [{"alg": "SHA-512", "content": _integrity_sha512_hex(dependency.integrity)}],
        "licenses": [{"expression": dependency.license_expression}],
        "purl": purl,
        "externalReferences": [{"type": "distribution", "url": dependency.resolved_url}],
        "properties": _properties(
            {
                "collabio:genoffice:dependency-relationship": "direct" if dependency.direct else "transitive",
                "collabio:genoffice:install-script-declared": str(dependency.install_script_declared).lower(),
                "collabio:genoffice:requested-range": dependency.requested_range or "transitive",
                "collabio:genoffice:source-evidence": "npm-lock-v3",
            }
        ),
    }
    if group is not None:
        component["group"] = group
    return component


def _vendored_component(provenance: GenOfficeVendoredProvenanceAdmissionReport) -> dict[str, Any]:
    source_manifest_hash = stable_hash(
        canonical_json([item.model_dump(mode="json") for item in provenance.file_comparisons])
    )
    return {
        "type": "library",
        "bom-ref": provenance.package_purl,
        "name": provenance.package_name,
        "version": provenance.package_version,
        "hashes": [
            {
                "alg": "SHA-512",
                "content": _hash_content(provenance.package_tarball_sha512, algorithm="sha512"),
            }
        ],
        "licenses": [{"expression": provenance.package_license_spdx}],
        "purl": provenance.package_purl,
        "externalReferences": [
            {"type": "distribution", "url": provenance.package_tarball_url},
            {"type": "vcs", "url": provenance.package_repository_url.removeprefix("git+")},
        ],
        "properties": _properties(
            {
                "collabio:genoffice:byte-provenance": "verified",
                "collabio:genoffice:legal-review": "required",
                "collabio:genoffice:registry-attestation": "present-unverified",
                "collabio:genoffice:registry-signature": "present-unverified",
                "collabio:genoffice:source-manifest-hash": source_manifest_hash,
                "collabio:genoffice:source-root": provenance.vendored_root,
                "collabio:genoffice:tarball-sha256": provenance.package_tarball_sha256,
            }
        ),
    }


def _require_reviewed_source_report(report: GenOfficeDocxSourceAdmissionReport) -> None:
    if build_genoffice_docx_source_admission_report_hash(report) != report.report_hash:
        raise GenOfficeDocxPrebuildSbomError("GenOffice source admission report hash is invalid")
    if report.report_hash != GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH:
        raise GenOfficeDocxPrebuildSbomError("GenOffice source admission report is not the reviewed snapshot")
    if not report.source_snapshot_verified or report.snapshot_blocking_reasons:
        raise GenOfficeDocxPrebuildSbomError("GenOffice source snapshot is not verified")
    if report.runtime_dependency_count != len(report.runtime_dependencies):
        raise GenOfficeDocxPrebuildSbomError("GenOffice runtime dependency count is inconsistent")
    if not report.vendored_components:
        raise GenOfficeDocxPrebuildSbomError("GenOffice vendored runtime source is not inventoried")


def _require_reviewed_vendored_provenance(
    *, source_report: GenOfficeDocxSourceAdmissionReport, provenance: GenOfficeVendoredProvenanceAdmissionReport
) -> None:
    if build_genoffice_vendored_provenance_report_hash(provenance) != provenance.report_hash:
        raise GenOfficeDocxPrebuildSbomError("Vendored provenance report hash is invalid")
    if provenance.source_report_hash != source_report.report_hash:
        raise GenOfficeDocxPrebuildSbomError("Vendored provenance is not bound to the source report")
    if provenance.source_archive_sha256 != source_report.archive_sha256:
        raise GenOfficeDocxPrebuildSbomError("Vendored provenance is not bound to the source archive")
    if not provenance.byte_provenance_verified or not provenance.vendored_files_exact_match:
        raise GenOfficeDocxPrebuildSbomError("Vendored component byte provenance is not verified")
    if provenance.vendored_root not in {item.root_path for item in source_report.vendored_components}:
        raise GenOfficeDocxPrebuildSbomError("Vendored provenance root is not in the source inventory")


def build_genoffice_docx_prebuild_sbom(
    report: GenOfficeDocxSourceAdmissionReport,
    provenance: GenOfficeVendoredProvenanceAdmissionReport,
) -> dict[str, Any]:
    _require_reviewed_source_report(report)
    _require_reviewed_vendored_provenance(source_report=report, provenance=provenance)
    root_purl = _npm_purl(report.engine_package_name, report.engine_package_version)
    root_group, root_name = _npm_identity(report.engine_package_name)
    root_component: dict[str, Any] = {
        "type": "library",
        "bom-ref": root_purl,
        "name": root_name,
        "version": report.engine_package_version,
        "hashes": [{"alg": "SHA-256", "content": _hash_content(report.source_manifest_hash, algorithm="sha256")}],
        "licenses": [{"expression": report.engine_license_spdx}],
        "purl": root_purl,
        "externalReferences": [
            {
                "type": "vcs",
                "url": (f"{report.repository_url}/tree/{report.upstream_commit}/packages/docx-engine"),
            }
        ],
        "properties": _properties(
            {
                "collabio:genoffice:execution-state": "blocked",
                "collabio:genoffice:source-admission-report-hash": report.report_hash,
                "collabio:genoffice:source-archive-sha256": report.archive_sha256,
                "collabio:genoffice:source-import-state": "blocked",
            }
        ),
    }
    if root_group is not None:
        root_component["group"] = root_group

    npm_components = tuple(_npm_component(item) for item in report.runtime_dependencies)
    vendored_component = _vendored_component(provenance)
    components = tuple(sorted((*npm_components, vendored_component), key=lambda component: str(component["bom-ref"])))
    references = {str(component["bom-ref"]) for component in components}
    dependency_edges: list[dict[str, Any]] = []
    direct_refs = {_npm_purl(item.name, item.version) for item in report.runtime_dependencies if item.direct}
    direct_refs.add(provenance.package_purl)
    dependency_edges.append({"ref": root_purl, "dependsOn": sorted(direct_refs)})
    for dependency in report.runtime_dependencies:
        ref = _npm_purl(dependency.name, dependency.version)
        depends_on = sorted(
            _npm_purl(child_name, next(item.version for item in report.runtime_dependencies if item.name == child_name))
            for child_name in dependency.dependencies
        )
        if not set(depends_on).issubset(references):
            raise GenOfficeDocxPrebuildSbomError("GenOffice dependency graph references an unknown component")
        dependency_edges.append({"ref": ref, "dependsOn": depends_on})
    dependency_edges.append({"ref": provenance.package_purl, "dependsOn": []})

    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": GENOFFICE_DOCX_CYCLONEDX_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "lifecycles": [{"phase": "pre-build"}],
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "bom-ref": GENOFFICE_DOCX_SBOM_TOOL_REF,
                        "author": "Collabio",
                        "name": "genoffice-docx-prebuild-sbom",
                        "version": GENOFFICE_DOCX_SBOM_GENERATOR_VERSION,
                    }
                ]
            },
            "component": root_component,
            "properties": _properties(
                {
                    "collabio:genoffice:dependency-manifest-hash": report.runtime_dependency_manifest_hash,
                    "collabio:genoffice:inventory-completeness": "selected-docx-source-and-runtime-closure",
                    "collabio:genoffice:legal-review-state": "pending",
                    "collabio:genoffice:sbom-schema-version": GENOFFICE_DOCX_PREBUILD_SBOM_SCHEMA_VERSION,
                    "collabio:genoffice:source-admission-report-hash": report.report_hash,
                    "collabio:genoffice:source-manifest-hash": report.source_manifest_hash,
                    "collabio:genoffice:upstream-commit": report.upstream_commit,
                }
            ),
        },
        "components": list(components),
        "dependencies": sorted(dependency_edges, key=lambda edge: str(edge["ref"])),
    }


def genoffice_docx_prebuild_sbom_bytes(sbom: Mapping[str, Any]) -> bytes:
    return (json.dumps(sbom, indent=2, sort_keys=True) + "\n").encode()


def genoffice_docx_prebuild_sbom_hash(sbom: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(genoffice_docx_prebuild_sbom_bytes(sbom)).hexdigest()


def persist_genoffice_docx_prebuild_sbom(*, sbom: Mapping[str, Any], sbom_path: Path) -> None:
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = sbom_path.with_suffix(sbom_path.suffix + ".tmp")
    temporary_path.write_bytes(genoffice_docx_prebuild_sbom_bytes(sbom))
    temporary_path.replace(sbom_path)


def load_genoffice_docx_prebuild_sbom(
    *,
    sbom_path: Path,
    source_report: GenOfficeDocxSourceAdmissionReport,
    vendored_provenance: GenOfficeVendoredProvenanceAdmissionReport,
) -> dict[str, Any]:
    try:
        payload = json.loads(sbom_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeDocxPrebuildSbomError("GenOffice pre-build SBOM is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise GenOfficeDocxPrebuildSbomError("GenOffice pre-build SBOM must be a JSON object")
    expected = build_genoffice_docx_prebuild_sbom(source_report, vendored_provenance)
    if payload != expected:
        raise GenOfficeDocxPrebuildSbomError("GenOffice pre-build SBOM does not match the reviewed source report")
    return payload


def run_genoffice_docx_prebuild_sbom_from_environment(env: Mapping[str, str]) -> dict[str, Any]:
    source_report_path_value = env.get("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH", "").strip()
    vendored_provenance_path_value = env.get("SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH", "").strip()
    sbom_path_value = env.get("SUITE_GENOFFICE_PREBUILD_SBOM_PATH", "").strip()
    if not source_report_path_value:
        raise GenOfficeDocxPrebuildSbomError("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH is required")
    if not sbom_path_value:
        raise GenOfficeDocxPrebuildSbomError("SUITE_GENOFFICE_PREBUILD_SBOM_PATH is required")
    if not vendored_provenance_path_value:
        raise GenOfficeDocxPrebuildSbomError("SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH is required")
    try:
        report = load_genoffice_docx_source_admission_report(Path(source_report_path_value))
    except (OSError, GenOfficeSourceAdmissionError) as exc:
        raise GenOfficeDocxPrebuildSbomError("GenOffice source admission report cannot be loaded") from exc
    try:
        provenance = load_genoffice_vendored_provenance_report(Path(vendored_provenance_path_value))
    except GenOfficeVendoredProvenanceError as exc:
        raise GenOfficeDocxPrebuildSbomError("Vendored provenance report cannot be loaded") from exc
    sbom = build_genoffice_docx_prebuild_sbom(report, provenance)
    persist_genoffice_docx_prebuild_sbom(sbom=sbom, sbom_path=Path(sbom_path_value))
    return sbom


def main() -> None:
    try:
        sbom = run_genoffice_docx_prebuild_sbom_from_environment(os.environ)
        print(
            json.dumps(
                {
                    "component_count": 1 + len(sbom["components"]),
                    "sbom_hash": genoffice_docx_prebuild_sbom_hash(sbom),
                    "schema_version": GENOFFICE_DOCX_PREBUILD_SBOM_SCHEMA_VERSION,
                },
                sort_keys=True,
            )
        )
    except GenOfficeDocxPrebuildSbomError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_DOCX_PREBUILD_SBOM_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
