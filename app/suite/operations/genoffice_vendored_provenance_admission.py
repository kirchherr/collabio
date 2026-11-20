from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_source_admission import (
    GENOFFICE_ARCHIVE_ROOT,
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeSourceAdmissionError,
    build_genoffice_docx_source_admission_report_hash,
    load_genoffice_docx_source_admission_report,
)

GENOFFICE_VENDORED_PROVENANCE_SCHEMA_VERSION = "genoffice_vendored_provenance_admission_report.v1"
GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH = "sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d"
EMF_CONVERTER_NAME = "emf-converter"
EMF_CONVERTER_VERSION = "2.0.2"
EMF_CONVERTER_PURL = "pkg:npm/emf-converter@2.0.2"
EMF_CONVERTER_LICENSE = "Apache-2.0"
EMF_CONVERTER_REPOSITORY = "git+https://github.com/ChristopherVR/emf-converter.git"
EMF_CONVERTER_TARBALL_URL = "https://registry.npmjs.org/emf-converter/-/emf-converter-2.0.2.tgz"
EMF_CONVERTER_TARBALL_SRI = (
    "sha512-QLUufb45P3LlOudCoizBtJpO8cBw8LayH0mkvkRvIjvMlb6junwP0EXgUkdDyZUEF2QSEZUPV8rO8DS5rsJmkA=="
)
EMF_CONVERTER_TARBALL_SHA256 = "sha256:acf0927871d783efe2defe4fdf4e66d09915776570aa81c23781199e58424e9b"
EMF_CONVERTER_VENDOR_ROOT = "packages/docx-engine/src/vendor/emf-converter"
EMF_CONVERTER_EXPECTED_ARCHIVE_FILES = (
    "package/LICENSE",
    "package/README.md",
    "package/dist/index.d.mts",
    "package/dist/index.d.ts",
    "package/dist/index.js",
    "package/dist/index.mjs",
    "package/package.json",
)
EMF_CONVERTER_SOURCE_MAPPINGS = (
    (f"{EMF_CONVERTER_VENDOR_ROOT}/LICENSE", "package/LICENSE"),
    (f"{EMF_CONVERTER_VENDOR_ROOT}/index.d.mts", "package/dist/index.d.mts"),
    (f"{EMF_CONVERTER_VENDOR_ROOT}/index.mjs", "package/dist/index.mjs"),
)
MAX_METADATA_SIZE_BYTES = 1024 * 1024
MAX_TARBALL_SIZE_BYTES = 4 * 1024 * 1024
MAX_MEMBER_SIZE_BYTES = 2 * 1024 * 1024


class GenOfficeVendoredProvenanceError(ValueError):
    pass


class VendoredFileComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    package_path: str
    source_sha256: str
    package_sha256: str
    exact_match: bool


class GenOfficeVendoredProvenanceAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_vendored_provenance_admission_report.v1"] = (
        "genoffice_vendored_provenance_admission_report.v1"
    )
    source_report_hash: str
    source_archive_sha256: str
    vendored_root: str
    package_name: str
    package_version: str
    package_purl: str
    package_license_spdx: str
    package_repository_url: str
    package_tarball_url: str
    package_tarball_sha256: str
    package_tarball_sha512: str
    package_tarball_sri: str
    registry_metadata_sha256: str
    registry_signature_key_ids: tuple[str, ...]
    registry_attestation_url: str
    registry_attestation_predicate_type: str
    package_archive_member_count: int
    package_archive_files: tuple[str, ...]
    package_lifecycle_scripts: tuple[str, ...]
    file_comparisons: tuple[VendoredFileComparison, ...]
    source_archive_verified: bool
    package_tarball_integrity_verified: bool
    package_metadata_verified: bool
    vendored_files_exact_match: bool
    byte_provenance_verified: bool
    registry_signature_metadata_present: bool
    registry_attestation_metadata_present: bool
    registry_signature_verified: bool = False
    registry_attestation_verified: bool = False
    legal_review_complete: bool = False
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    production_use_allowed: bool = False
    remaining_gates: tuple[str, ...] = (
        "human_legal_notice_trademark_and_compound_license_review",
        "npm_registry_signature_and_slsa_attestation_verification",
        "reproducible_isolated_build_and_signed_provenance",
    )
    report_hash: str

    @model_validator(mode="after")
    def require_pinned_closed_boundary(self) -> GenOfficeVendoredProvenanceAdmissionReport:
        expected = {
            "source_report_hash": GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH,
            "vendored_root": EMF_CONVERTER_VENDOR_ROOT,
            "package_name": EMF_CONVERTER_NAME,
            "package_version": EMF_CONVERTER_VERSION,
            "package_purl": EMF_CONVERTER_PURL,
            "package_license_spdx": EMF_CONVERTER_LICENSE,
            "package_repository_url": EMF_CONVERTER_REPOSITORY,
            "package_tarball_url": EMF_CONVERTER_TARBALL_URL,
            "package_tarball_sha256": EMF_CONVERTER_TARBALL_SHA256,
            "package_tarball_sri": EMF_CONVERTER_TARBALL_SRI,
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"Vendored provenance field {field} is not pinned")
        if any(
            (
                self.registry_signature_verified,
                self.registry_attestation_verified,
                self.legal_review_complete,
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("Vendored byte provenance opened an unreviewed trust or execution boundary")
        return self


def _hash_file(path: Path, *, algorithm: str, maximum_size: int) -> tuple[str, int]:
    digest = hashlib.new(algorithm)
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_size:
                    raise GenOfficeVendoredProvenanceError("Vendored provenance input exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeVendoredProvenanceError("Vendored provenance input cannot be read") from exc
    return f"{algorithm}:{digest.hexdigest()}", size


def _read_json(path: Path) -> tuple[Mapping[str, Any], str]:
    digest, _ = _hash_file(path, algorithm="sha256", maximum_size=MAX_METADATA_SIZE_BYTES)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeVendoredProvenanceError("npm registry metadata is not readable JSON") from exc
    if not isinstance(value, dict):
        raise GenOfficeVendoredProvenanceError("npm registry metadata must be an object")
    return value, digest


def _safe_archive_path(name: str, *, root: str) -> str:
    if not name or name.startswith("/") or "\\" in name:
        raise GenOfficeVendoredProvenanceError("Vendored provenance archive contains an unsafe path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts) or path.parts[0] != root:
        raise GenOfficeVendoredProvenanceError("Vendored provenance archive path is not canonical")
    return path.as_posix()


def _read_selected_archive_files(
    *, archive_path: Path, root: str, selected_paths: tuple[str, ...], inspect_all_members: bool
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    selected: dict[str, bytes] = {}
    files: list[str] = []
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                path = _safe_archive_path(member.name, root=root)
                if path in seen:
                    raise GenOfficeVendoredProvenanceError("Vendored provenance archive contains duplicate paths")
                seen.add(path)
                if not (member.isfile() or member.isdir()):
                    raise GenOfficeVendoredProvenanceError(
                        "Vendored provenance archive contains links or special files"
                    )
                if member.isfile():
                    files.append(path)
                if path not in selected_paths or not member.isfile():
                    continue
                if member.size < 0 or member.size > MAX_MEMBER_SIZE_BYTES:
                    raise GenOfficeVendoredProvenanceError("Vendored provenance member exceeds its size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise GenOfficeVendoredProvenanceError("Vendored provenance member cannot be read")
                content = source.read(MAX_MEMBER_SIZE_BYTES + 1)
                if len(content) != member.size:
                    raise GenOfficeVendoredProvenanceError("Vendored provenance member size is inconsistent")
                selected[path] = content
    except (OSError, tarfile.TarError) as exc:
        raise GenOfficeVendoredProvenanceError("Vendored provenance archive is not readable") from exc
    missing = sorted(set(selected_paths) - set(selected))
    if missing:
        raise GenOfficeVendoredProvenanceError(f"Vendored provenance archive is missing files: {missing}")
    return selected, tuple(sorted(files if inspect_all_members else selected))


def _sha512_hex_from_sri(value: str) -> str:
    if not value.startswith("sha512-"):
        raise GenOfficeVendoredProvenanceError("npm package integrity is not SHA-512")
    try:
        decoded = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeVendoredProvenanceError("npm package integrity is malformed") from exc
    if len(decoded) != hashlib.sha512().digest_size:
        raise GenOfficeVendoredProvenanceError("npm package integrity has the wrong length")
    return decoded.hex()


def _string_field(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise GenOfficeVendoredProvenanceError(f"npm registry metadata field {field} is missing")
    return item


def _metadata_evidence(metadata: Mapping[str, Any]) -> tuple[tuple[str, ...], str, str, Mapping[str, Any]]:
    dist = metadata.get("dist")
    if not isinstance(dist, dict):
        raise GenOfficeVendoredProvenanceError("npm registry dist metadata is missing")
    signatures = dist.get("signatures")
    if not isinstance(signatures, list):
        raise GenOfficeVendoredProvenanceError("npm registry signature metadata is missing")
    key_ids = tuple(
        sorted(
            signature["keyid"]
            for signature in signatures
            if isinstance(signature, dict) and isinstance(signature.get("keyid"), str)
        )
    )
    attestations = dist.get("attestations")
    if not isinstance(attestations, dict):
        raise GenOfficeVendoredProvenanceError("npm registry attestation metadata is missing")
    provenance = attestations.get("provenance")
    if not isinstance(provenance, dict):
        raise GenOfficeVendoredProvenanceError("npm registry provenance metadata is missing")
    return key_ids, _string_field(attestations, "url"), _string_field(provenance, "predicateType"), dist


def build_genoffice_vendored_provenance_admission_report(
    *,
    source_report: GenOfficeDocxSourceAdmissionReport,
    source_archive_path: Path,
    registry_metadata_path: Path,
    package_archive_path: Path,
) -> GenOfficeVendoredProvenanceAdmissionReport:
    if build_genoffice_docx_source_admission_report_hash(source_report) != source_report.report_hash:
        raise GenOfficeVendoredProvenanceError("GenOffice source report hash is invalid")
    if source_report.report_hash != GENOFFICE_DOCX_REVIEWED_SOURCE_REPORT_HASH:
        raise GenOfficeVendoredProvenanceError("GenOffice source report is not the reviewed snapshot")
    source_archive_sha256, _ = _hash_file(source_archive_path, algorithm="sha256", maximum_size=64 * 1024 * 1024)
    if source_archive_sha256 != source_report.archive_sha256:
        raise GenOfficeVendoredProvenanceError("GenOffice source archive does not match its admission report")

    metadata, metadata_sha256 = _read_json(registry_metadata_path)
    key_ids, attestation_url, predicate_type, dist = _metadata_evidence(metadata)
    repository = metadata.get("repository")
    repository_url = repository.get("url") if isinstance(repository, dict) else None
    metadata_verified = (
        metadata.get("name") == EMF_CONVERTER_NAME
        and metadata.get("version") == EMF_CONVERTER_VERSION
        and metadata.get("license") == EMF_CONVERTER_LICENSE
        and repository_url == EMF_CONVERTER_REPOSITORY
        and dist.get("tarball") == EMF_CONVERTER_TARBALL_URL
        and dist.get("integrity") == EMF_CONVERTER_TARBALL_SRI
        and dist.get("fileCount") == len(EMF_CONVERTER_EXPECTED_ARCHIVE_FILES)
    )
    if not metadata_verified:
        raise GenOfficeVendoredProvenanceError("npm registry metadata does not match the reviewed component")

    tarball_sha256, _ = _hash_file(package_archive_path, algorithm="sha256", maximum_size=MAX_TARBALL_SIZE_BYTES)
    tarball_sha512, _ = _hash_file(package_archive_path, algorithm="sha512", maximum_size=MAX_TARBALL_SIZE_BYTES)
    integrity_verified = (
        tarball_sha256 == EMF_CONVERTER_TARBALL_SHA256
        and tarball_sha512 == f"sha512:{_sha512_hex_from_sri(EMF_CONVERTER_TARBALL_SRI)}"
    )
    if not integrity_verified:
        raise GenOfficeVendoredProvenanceError("npm package tarball does not match the reviewed integrity")

    package_paths = (*EMF_CONVERTER_EXPECTED_ARCHIVE_FILES,)
    package_files, package_archive_files = _read_selected_archive_files(
        archive_path=package_archive_path,
        root="package",
        selected_paths=package_paths,
        inspect_all_members=True,
    )
    if package_archive_files != EMF_CONVERTER_EXPECTED_ARCHIVE_FILES:
        raise GenOfficeVendoredProvenanceError("npm package archive file inventory changed")
    package_json = json.loads(package_files["package/package.json"].decode("utf-8"))
    if not isinstance(package_json, dict):
        raise GenOfficeVendoredProvenanceError("npm package manifest must be an object")
    lifecycle_scripts = tuple(
        sorted(
            name
            for name in package_json.get("scripts", {})
            if name in {"preinstall", "install", "postinstall", "prepare", "prepack", "prepublishOnly"}
        )
    )
    if (
        package_json.get("name") != EMF_CONVERTER_NAME
        or package_json.get("version") != EMF_CONVERTER_VERSION
        or package_json.get("license") != EMF_CONVERTER_LICENSE
        or lifecycle_scripts
    ):
        raise GenOfficeVendoredProvenanceError("npm package manifest is not the reviewed install-safe component")

    source_paths = tuple(f"{GENOFFICE_ARCHIVE_ROOT}/{source}" for source, _ in EMF_CONVERTER_SOURCE_MAPPINGS)
    source_files, _ = _read_selected_archive_files(
        archive_path=source_archive_path,
        root=GENOFFICE_ARCHIVE_ROOT,
        selected_paths=source_paths,
        inspect_all_members=False,
    )
    comparisons: list[VendoredFileComparison] = []
    for source_path, package_path in EMF_CONVERTER_SOURCE_MAPPINGS:
        source_content = source_files[f"{GENOFFICE_ARCHIVE_ROOT}/{source_path}"]
        package_content = package_files[package_path]
        comparisons.append(
            VendoredFileComparison(
                source_path=source_path,
                package_path=package_path,
                source_sha256=f"sha256:{hashlib.sha256(source_content).hexdigest()}",
                package_sha256=f"sha256:{hashlib.sha256(package_content).hexdigest()}",
                exact_match=source_content == package_content,
            )
        )
    exact_match = all(item.exact_match for item in comparisons)
    byte_provenance_verified = integrity_verified and metadata_verified and exact_match
    draft = GenOfficeVendoredProvenanceAdmissionReport(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_archive_sha256,
        vendored_root=EMF_CONVERTER_VENDOR_ROOT,
        package_name=EMF_CONVERTER_NAME,
        package_version=EMF_CONVERTER_VERSION,
        package_purl=EMF_CONVERTER_PURL,
        package_license_spdx=EMF_CONVERTER_LICENSE,
        package_repository_url=EMF_CONVERTER_REPOSITORY,
        package_tarball_url=EMF_CONVERTER_TARBALL_URL,
        package_tarball_sha256=tarball_sha256,
        package_tarball_sha512=tarball_sha512,
        package_tarball_sri=EMF_CONVERTER_TARBALL_SRI,
        registry_metadata_sha256=metadata_sha256,
        registry_signature_key_ids=key_ids,
        registry_attestation_url=attestation_url,
        registry_attestation_predicate_type=predicate_type,
        package_archive_member_count=len(package_archive_files),
        package_archive_files=package_archive_files,
        package_lifecycle_scripts=lifecycle_scripts,
        file_comparisons=tuple(comparisons),
        source_archive_verified=True,
        package_tarball_integrity_verified=integrity_verified,
        package_metadata_verified=metadata_verified,
        vendored_files_exact_match=exact_match,
        byte_provenance_verified=byte_provenance_verified,
        registry_signature_metadata_present=bool(key_ids),
        registry_attestation_metadata_present=bool(attestation_url and predicate_type),
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_vendored_provenance_report_hash(draft)})


def build_genoffice_vendored_provenance_report_hash(
    report: GenOfficeVendoredProvenanceAdmissionReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_vendored_provenance_report(
    *, report: GenOfficeVendoredProvenanceAdmissionReport, report_path: Path
) -> None:
    if build_genoffice_vendored_provenance_report_hash(report) != report.report_hash:
        raise GenOfficeVendoredProvenanceError("Vendored provenance report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(report_path)


def load_genoffice_vendored_provenance_report(
    report_path: Path,
) -> GenOfficeVendoredProvenanceAdmissionReport:
    try:
        report = GenOfficeVendoredProvenanceAdmissionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GenOfficeVendoredProvenanceError("Vendored provenance report cannot be loaded") from exc
    if build_genoffice_vendored_provenance_report_hash(report) != report.report_hash:
        raise GenOfficeVendoredProvenanceError("Vendored provenance report hash is invalid")
    return report


def run_genoffice_vendored_provenance_from_environment(
    env: Mapping[str, str],
) -> GenOfficeVendoredProvenanceAdmissionReport:
    required = {
        "source_report": env.get("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH", "").strip(),
        "source_archive": env.get("SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH", "").strip(),
        "registry_metadata": env.get("SUITE_EMF_CONVERTER_REGISTRY_METADATA_PATH", "").strip(),
        "package_archive": env.get("SUITE_EMF_CONVERTER_PACKAGE_ARCHIVE_PATH", "").strip(),
        "report": env.get("SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH", "").strip(),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise GenOfficeVendoredProvenanceError(f"Vendored provenance environment paths are missing: {missing}")
    try:
        source_report = load_genoffice_docx_source_admission_report(Path(required["source_report"]))
    except (OSError, GenOfficeSourceAdmissionError) as exc:
        raise GenOfficeVendoredProvenanceError("GenOffice source report cannot be loaded") from exc
    report = build_genoffice_vendored_provenance_admission_report(
        source_report=source_report,
        source_archive_path=Path(required["source_archive"]),
        registry_metadata_path=Path(required["registry_metadata"]),
        package_archive_path=Path(required["package_archive"]),
    )
    persist_genoffice_vendored_provenance_report(report=report, report_path=Path(required["report"]))
    return report


def main() -> None:
    try:
        report = run_genoffice_vendored_provenance_from_environment(os.environ)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        raise SystemExit(0 if report.byte_provenance_verified else 2)
    except GenOfficeVendoredProvenanceError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_VENDORED_PROVENANCE_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
