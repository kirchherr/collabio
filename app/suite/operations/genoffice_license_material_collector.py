from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import ssl
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_source_admission import (
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeRuntimeDependencyEvidence,
    build_genoffice_docx_source_admission_report_hash,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_vendored_provenance_admission import (
    GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH,
)

GENOFFICE_LICENSE_MATERIAL_COLLECTION_SCHEMA_VERSION = "genoffice_license_material_collection_report.v1"
GENOFFICE_NPM_REGISTRY_HOST = "registry.npmjs.org"
MAX_PACKAGE_ARCHIVE_SIZE_BYTES = 8 * 1024 * 1024
MAX_COLLECTION_SIZE_BYTES = 64 * 1024 * 1024
PACKAGE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class GenOfficeLicenseMaterialCollectionError(ValueError):
    pass


class GenOfficeLicenseMaterialArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str
    package_version: str
    resolved_url: str
    expected_integrity: str
    artifact_filename: str
    size_bytes: int
    sha256: str
    sha512: str
    integrity_verified: bool


class GenOfficeLicenseMaterialCollectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_license_material_collection_report.v1"] = (
        "genoffice_license_material_collection_report.v1"
    )
    source_report_hash: str
    source_archive_sha256: str
    registry_host: str
    artifact_count: int
    total_size_bytes: int
    artifacts: tuple[GenOfficeLicenseMaterialArtifact, ...]
    all_artifact_integrities_verified: bool
    network_access_used: bool
    credentials_used: bool
    lifecycle_execution_performed: bool
    archive_content_inspected: bool
    legal_review_complete: bool = False
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    worker_build_allowed: bool = False
    production_use_allowed: bool = False
    report_hash: str

    @model_validator(mode="after")
    def require_integrity_only_closed_boundary(self) -> GenOfficeLicenseMaterialCollectionReport:
        if self.registry_host != GENOFFICE_NPM_REGISTRY_HOST:
            raise ValueError("GenOffice license material registry host is not pinned")
        if self.artifact_count != len(self.artifacts):
            raise ValueError("GenOffice license material artifact count is inconsistent")
        if self.total_size_bytes != sum(item.size_bytes for item in self.artifacts):
            raise ValueError("GenOffice license material total size is inconsistent")
        identities = tuple((item.package_name, item.package_version) for item in self.artifacts)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise ValueError("GenOffice license material artifacts are not unique and sorted")
        if not self.artifacts or not self.all_artifact_integrities_verified:
            raise ValueError("GenOffice license material collection is incomplete")
        if not all(item.integrity_verified for item in self.artifacts):
            raise ValueError("GenOffice license material collection contains an unverified artifact")
        if not self.network_access_used or any(
            (
                self.credentials_used,
                self.lifecycle_execution_performed,
                self.archive_content_inspected,
                self.legal_review_complete,
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.worker_build_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice license material collection opened a forbidden boundary")
        return self


PackageFetcher = Callable[[str, int], bytes]


def _package_filename(name: str, version: str) -> str:
    normalized_name = PACKAGE_FILENAME_PATTERN.sub("_", name.lstrip("@").replace("/", "__"))
    normalized_version = PACKAGE_FILENAME_PATTERN.sub("_", version)
    if not normalized_name or not normalized_version:
        raise GenOfficeLicenseMaterialCollectionError("npm package identity cannot form a safe artifact filename")
    return f"{normalized_name}-{normalized_version}.tgz"


def _expected_sha512(integrity: str) -> bytes:
    if not integrity.startswith("sha512-"):
        raise GenOfficeLicenseMaterialCollectionError("npm package integrity is not SHA-512")
    try:
        decoded = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeLicenseMaterialCollectionError("npm package integrity is malformed") from exc
    if len(decoded) != hashlib.sha512().digest_size:
        raise GenOfficeLicenseMaterialCollectionError("npm package integrity has the wrong digest length")
    return decoded


def _validated_registry_target(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != GENOFFICE_NPM_REGISTRY_HOST
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise GenOfficeLicenseMaterialCollectionError("npm package URL is outside the pinned registry boundary")
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return GENOFFICE_NPM_REGISTRY_HOST, target


def _fetch_registry_package(url: str, maximum_size: int) -> bytes:
    host, target = _validated_registry_target(url)
    connection = http.client.HTTPSConnection(
        host,
        port=443,
        timeout=30,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            target,
            headers={"Accept": "application/octet-stream", "User-Agent": "collabio-license-material-collector/1"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise GenOfficeLicenseMaterialCollectionError(
                f"npm registry returned an unexpected package status: {response.status}"
            )
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise GenOfficeLicenseMaterialCollectionError("npm registry returned an invalid content length") from exc
            if declared_size < 0 or declared_size > maximum_size:
                raise GenOfficeLicenseMaterialCollectionError("npm package exceeds the collection size limit")
        content = response.read(maximum_size + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise GenOfficeLicenseMaterialCollectionError("npm package download failed") from exc
    finally:
        connection.close()
    if not content or len(content) > maximum_size:
        raise GenOfficeLicenseMaterialCollectionError("npm package is empty or exceeds the collection size limit")
    return content


def _verified_artifact(
    *, dependency: GenOfficeRuntimeDependencyEvidence, content: bytes
) -> GenOfficeLicenseMaterialArtifact:
    if dependency.version is None or dependency.resolved_url is None or dependency.integrity is None:
        raise GenOfficeLicenseMaterialCollectionError("runtime dependency lacks pinned package material metadata")
    _validated_registry_target(dependency.resolved_url)
    actual_sha512 = hashlib.sha512(content).digest()
    if actual_sha512 != _expected_sha512(dependency.integrity):
        raise GenOfficeLicenseMaterialCollectionError(
            f"npm package integrity does not match the reviewed lockfile: {dependency.name}"
        )
    return GenOfficeLicenseMaterialArtifact(
        package_name=dependency.name,
        package_version=dependency.version,
        resolved_url=dependency.resolved_url,
        expected_integrity=dependency.integrity,
        artifact_filename=_package_filename(dependency.name, dependency.version),
        size_bytes=len(content),
        sha256=f"sha256:{hashlib.sha256(content).hexdigest()}",
        sha512=f"sha512:{actual_sha512.hex()}",
        integrity_verified=True,
    )


def collect_genoffice_license_materials(
    *,
    source_report: GenOfficeDocxSourceAdmissionReport,
    artifact_directory: Path,
    fetcher: PackageFetcher = _fetch_registry_package,
) -> GenOfficeLicenseMaterialCollectionReport:
    if build_genoffice_docx_source_admission_report_hash(source_report) != source_report.report_hash:
        raise GenOfficeLicenseMaterialCollectionError("GenOffice source report hash is invalid")
    if source_report.report_hash != GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH:
        raise GenOfficeLicenseMaterialCollectionError("GenOffice source report is not the reviewed snapshot")
    if not source_report.source_snapshot_verified:
        raise GenOfficeLicenseMaterialCollectionError("GenOffice source snapshot did not pass admission")

    artifact_directory.mkdir(parents=True, exist_ok=True)
    artifacts: list[GenOfficeLicenseMaterialArtifact] = []
    total_size = 0
    for dependency in sorted(source_report.runtime_dependencies, key=lambda item: (item.name, item.version or "")):
        if dependency.resolved_url is None:
            raise GenOfficeLicenseMaterialCollectionError("runtime dependency lacks a resolved package URL")
        content = fetcher(dependency.resolved_url, MAX_PACKAGE_ARCHIVE_SIZE_BYTES)
        artifact = _verified_artifact(dependency=dependency, content=content)
        total_size += artifact.size_bytes
        if total_size > MAX_COLLECTION_SIZE_BYTES:
            raise GenOfficeLicenseMaterialCollectionError("npm license material collection exceeds its total size limit")
        target = artifact_directory / artifact.artifact_filename
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise GenOfficeLicenseMaterialCollectionError("npm package material cannot be persisted") from exc
        artifacts.append(artifact)

    ordered = tuple(artifacts)
    draft = GenOfficeLicenseMaterialCollectionReport(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_report.archive_sha256,
        registry_host=GENOFFICE_NPM_REGISTRY_HOST,
        artifact_count=len(ordered),
        total_size_bytes=total_size,
        artifacts=ordered,
        all_artifact_integrities_verified=True,
        network_access_used=True,
        credentials_used=False,
        lifecycle_execution_performed=False,
        archive_content_inspected=False,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_license_material_collection_report_hash(draft)})


def build_genoffice_license_material_collection_report_hash(
    report: GenOfficeLicenseMaterialCollectionReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_license_material_collection_report(
    *, report: GenOfficeLicenseMaterialCollectionReport, report_path: Path
) -> None:
    if build_genoffice_license_material_collection_report_hash(report) != report.report_hash:
        raise GenOfficeLicenseMaterialCollectionError("GenOffice license material collection report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def load_genoffice_license_material_collection_report(
    report_path: Path,
) -> GenOfficeLicenseMaterialCollectionReport:
    try:
        report = GenOfficeLicenseMaterialCollectionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeLicenseMaterialCollectionError(
            "GenOffice license material collection report is not readable"
        ) from exc
    if build_genoffice_license_material_collection_report_hash(report) != report.report_hash:
        raise GenOfficeLicenseMaterialCollectionError("GenOffice license material collection report hash is invalid")
    return report


def run_genoffice_license_material_collection_from_environment(
    env: Mapping[str, str],
) -> GenOfficeLicenseMaterialCollectionReport:
    required = {
        "source_report": env.get("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH", "").strip(),
        "artifact_directory": env.get("SUITE_GENOFFICE_LICENSE_MATERIAL_DIRECTORY", "").strip(),
    }
    missing = tuple(sorted(name for name, value in required.items() if not value))
    if missing:
        raise GenOfficeLicenseMaterialCollectionError(f"GenOffice license material paths are missing: {missing}")
    source_report = load_genoffice_docx_source_admission_report(Path(required["source_report"]))
    return collect_genoffice_license_materials(
        source_report=source_report,
        artifact_directory=Path(required["artifact_directory"]),
    )


def _remove_unreferenced_temporary_files(artifact_directory: Path) -> None:
    try:
        candidates: Iterable[Path] = artifact_directory.glob("*.tmp")
        for candidate in candidates:
            if candidate.is_file():
                candidate.unlink(missing_ok=True)
    except OSError as exc:
        raise GenOfficeLicenseMaterialCollectionError("temporary license material cleanup failed") from exc


def main() -> None:
    try:
        report = run_genoffice_license_material_collection_from_environment(os.environ)
        report_path_value = os.environ.get("SUITE_GENOFFICE_LICENSE_MATERIAL_REPORT_PATH", "").strip()
        if not report_path_value:
            raise GenOfficeLicenseMaterialCollectionError(
                "SUITE_GENOFFICE_LICENSE_MATERIAL_REPORT_PATH is required"
            )
        report_path = Path(report_path_value)
        persist_genoffice_license_material_collection_report(report=report, report_path=report_path)
        _remove_unreferenced_temporary_files(report_path.parent)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    except GenOfficeLicenseMaterialCollectionError as exc:
        print(
            json.dumps(
                {"error": str(exc), "schema_version": GENOFFICE_LICENSE_MATERIAL_COLLECTION_SCHEMA_VERSION},
                sort_keys=True,
            )
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
