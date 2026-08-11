from __future__ import annotations

import hashlib
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_source_admission import (
    GENOFFICE_ARCHIVE_ROOT,
    GENOFFICE_ENGINE_PACKAGE_PATH,
    GENOFFICE_PROHIBITED_SCOPE_PREFIXES,
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeRuntimeDependencyEvidence,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_docx_supply_chain_admission import (
    GenOfficeDocxSupplyChainAdmissionReport,
    load_genoffice_docx_supply_chain_admission_report,
)
from suite.operations.genoffice_license_material_collector import (
    GenOfficeLicenseMaterialArtifact,
    GenOfficeLicenseMaterialCollectionReport,
    GenOfficeSupplementalLicenseSourceArtifact,
    build_genoffice_license_material_collection_report_hash,
    load_genoffice_license_material_collection_report,
)
from suite.operations.genoffice_npm_provenance_admission import (
    GenOfficeNpmProvenanceAdmissionReport,
    load_genoffice_npm_provenance_admission_report,
)
from suite.operations.genoffice_vendored_provenance_admission import (
    EMF_CONVERTER_VENDOR_ROOT,
    GenOfficeVendoredProvenanceAdmissionReport,
    load_genoffice_vendored_provenance_report,
)

GENOFFICE_LEGAL_REVIEW_DOSSIER_SCHEMA_VERSION = "genoffice_legal_review_dossier_report.v1"
GENOFFICE_LEGAL_DECISION_RECORD_SCHEMA_VERSION = "genoffice_legal_decision_record.v1"
GENOFFICE_REVIEWED_SOURCE_REPORT_HASH = "sha256:7a4eb66cfeefbf6defad574f33b07c904b62c7f076ecb21277e99ae87e2b951d"
GENOFFICE_REVIEWED_VENDORED_REPORT_HASH = "sha256:5ac1fdfa83034db3a8da06985b5f96e87a8eb0acfe3614f05b4fb3afe8e3dd04"
GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH = "sha256:580bd646106d79b712d42ecef490a8165435525a1feaeb52c10999274584767f"
GENOFFICE_REVIEWED_NPM_PROVENANCE_REPORT_HASH = (
    "sha256:c85feac5fa9788ef10a4076034d2443c230e8536ee5c02de61b8cfe9ea114aa3"
)
GENOFFICE_REQUIRED_SOURCE_LEGAL_PATHS = (
    "LICENSE",
    "NOTICE",
    "README.md",
    "ee/LICENSE",
    f"{EMF_CONVERTER_VENDOR_ROOT}/LICENSE",
)
GENOFFICE_APPROVABLE_SOURCE_SCOPES = (f"{GENOFFICE_ENGINE_PACKAGE_PATH}/**",)
GENOFFICE_REQUIRED_TRADEMARK_POLICY = "collabio_brand_only_no_genoffice_or_genspark_marks"
MAX_SOURCE_ARCHIVE_SIZE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBER_COUNT = 25_000
MAX_LEGAL_FILE_SIZE_BYTES = 512 * 1024
MAX_PACKAGE_MEMBER_COUNT = 5_000
MAX_PACKAGE_LEGAL_TOTAL_SIZE_BYTES = 4 * 1024 * 1024
LEGAL_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT")
README_PREFIXES = ("README",)


class GenOfficeLegalReviewDossierError(ValueError):
    pass


class GenOfficeLegalFileEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    path: str
    scope: Literal[
        "root",
        "selected_engine",
        "vendored_component",
        "excluded_enterprise",
        "runtime_dependency",
        "supplemental_dependency_source",
    ]
    kind: Literal["license", "notice", "copyright", "readme"]
    package_name: str | None = None
    package_version: str | None = None
    size_bytes: int
    sha256: str
    utf8_verified: bool
    detected_markers: tuple[str, ...]


class GenOfficeDependencyLicenseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str
    package_version: str
    declared_license_expression: str
    expression_semantics: Literal["single", "choice", "cumulative"]
    required_text_markers: tuple[str, ...]
    detected_text_markers: tuple[str, ...]
    legal_file_evidence_ids: tuple[str, ...]
    package_archive_sha256: str
    package_archive_integrity_verified: bool
    license_text_evidence_complete: bool
    human_license_choice_required: bool


class GenOfficeLegalReviewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    category: Literal["license", "notice", "trademark", "scope", "patent", "distribution"]
    evidence_refs: tuple[str, ...]
    required_decision: str


class GenOfficeLegalQuestionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    resolution: str
    evidence_refs: tuple[str, ...]


class GenOfficeDependencyLicenseResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str
    package_version: str
    declared_license_expression: str
    selected_distribution_license_expression: str
    legal_file_evidence_ids: tuple[str, ...]


class GenOfficeLegalDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_legal_decision_record.v1"] = "genoffice_legal_decision_record.v1"
    dossier_report_hash: str
    decision_id: str
    decision: Literal["approved", "rejected"]
    reviewer_id: str
    reviewer_professional_role: str
    reviewed_at_utc: datetime
    legal_opinion_ref: str
    change_control_ref: str
    approved_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    trademark_policy: str
    notice_distribution_artifact_sha256: str
    question_resolutions: tuple[GenOfficeLegalQuestionResolution, ...]
    dependency_license_resolutions: tuple[GenOfficeDependencyLicenseResolution, ...]
    detached_signature_verification_evidence_hash: str
    record_hash: str

    @field_validator("reviewed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice legal decision reviewed_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_nonempty_decision_evidence(self) -> GenOfficeLegalDecisionRecord:
        required_text = (
            self.decision_id,
            self.reviewer_id,
            self.reviewer_professional_role,
            self.legal_opinion_ref,
            self.change_control_ref,
        )
        if not all(value.strip() for value in required_text):
            raise ValueError("GenOffice legal decision contains an empty review identity or reference")
        for value in (
            self.dossier_report_hash,
            self.notice_distribution_artifact_sha256,
            self.detached_signature_verification_evidence_hash,
            self.record_hash,
        ):
            _require_sha256(value, field="legal decision evidence hash")
        return self


class GenOfficeLegalReviewDossierReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_legal_review_dossier_report.v1"] = "genoffice_legal_review_dossier_report.v1"
    source_report_hash: str
    source_archive_sha256: str
    vendored_provenance_report_hash: str
    supply_chain_admission_report_hash: str
    npm_provenance_admission_report_hash: str
    license_material_collection_report_hash: str
    legal_decision_record_schema_version: str
    legal_decision_record_schema_hash: str
    source_legal_files: tuple[GenOfficeLegalFileEvidence, ...]
    dependency_legal_files: tuple[GenOfficeLegalFileEvidence, ...]
    dependency_licenses: tuple[GenOfficeDependencyLicenseEvidence, ...]
    runtime_dependency_count: int
    runtime_dependency_license_file_count: int
    compound_license_packages: tuple[str, ...]
    root_apache_2_license_text_marker_verified: bool
    root_notice_present: bool
    upstream_trademark_restriction_verified: bool
    upstream_trademark_owner: str
    enterprise_license_present_and_scope_excluded: bool
    vendored_apache_2_license_text_marker_verified: bool
    supplemental_dependency_source_license_verified: bool
    all_runtime_package_integrities_verified: bool
    all_runtime_license_text_evidence_complete: bool
    automated_legal_evidence_complete: bool
    human_review_ready: bool
    review_questions: tuple[GenOfficeLegalReviewQuestion, ...]
    human_decision_record_created: bool = False
    legal_review_complete: bool = False
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    reproducible_worker_build_allowed: bool = False
    authoritative_image_sbom_allowed: bool = False
    production_use_allowed: bool = False
    report_hash: str

    @model_validator(mode="after")
    def require_review_ready_closed_boundary(self) -> GenOfficeLegalReviewDossierReport:
        expected_hashes = {
            "source_report_hash": GENOFFICE_REVIEWED_SOURCE_REPORT_HASH,
            "vendored_provenance_report_hash": GENOFFICE_REVIEWED_VENDORED_REPORT_HASH,
            "supply_chain_admission_report_hash": GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH,
            "npm_provenance_admission_report_hash": GENOFFICE_REVIEWED_NPM_PROVENANCE_REPORT_HASH,
        }
        for field, expected in expected_hashes.items():
            if getattr(self, field) != expected:
                raise ValueError(f"GenOffice legal dossier field {field} is not pinned")
        if self.runtime_dependency_count != len(self.dependency_licenses):
            raise ValueError("GenOffice legal dossier dependency count is inconsistent")
        if self.runtime_dependency_license_file_count != len(self.dependency_legal_files):
            raise ValueError("GenOffice legal dossier dependency legal-file count is inconsistent")
        if self.human_review_ready != self.automated_legal_evidence_complete:
            raise ValueError("GenOffice legal dossier review-ready state is inconsistent")
        if any(
            (
                self.human_decision_record_created,
                self.legal_review_complete,
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.reproducible_worker_build_allowed,
                self.authoritative_image_sbom_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice legal dossier opened an unapproved boundary")
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{field} is not a SHA-256 evidence hash")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a SHA-256 evidence hash") from exc


def _sha256_file(path: Path, *, maximum_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_size:
                    raise GenOfficeLegalReviewDossierError("GenOffice legal evidence input exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeLegalReviewDossierError("GenOffice legal evidence input cannot be read") from exc
    return f"sha256:{digest.hexdigest()}", size


def _safe_archive_path(name: str, *, root: str) -> str:
    if not name or name.startswith("/") or "\\" in name:
        raise GenOfficeLegalReviewDossierError("GenOffice legal evidence archive contains an unsafe path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts) or not path.parts or path.parts[0] != root:
        raise GenOfficeLegalReviewDossierError("GenOffice legal evidence archive path is not canonical")
    return path.as_posix()


def _read_selected_source_legal_files(archive_path: Path) -> dict[str, bytes]:
    selected_paths = {f"{GENOFFICE_ARCHIVE_ROOT}/{path}": path for path in GENOFFICE_REQUIRED_SOURCE_LEGAL_PATHS}
    selected: dict[str, bytes] = {}
    seen: set[str] = set()
    member_count = 0
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                member_count += 1
                if member_count > MAX_ARCHIVE_MEMBER_COUNT:
                    raise GenOfficeLegalReviewDossierError("GenOffice source archive has too many members")
                path = _safe_archive_path(member.name, root=GENOFFICE_ARCHIVE_ROOT)
                if path in seen:
                    raise GenOfficeLegalReviewDossierError("GenOffice source archive contains duplicate paths")
                seen.add(path)
                if not (member.isfile() or member.isdir()):
                    raise GenOfficeLegalReviewDossierError("GenOffice source archive contains links or special files")
                relative = selected_paths.get(path)
                if relative is None or not member.isfile():
                    continue
                if member.size < 0 or member.size > MAX_LEGAL_FILE_SIZE_BYTES:
                    raise GenOfficeLegalReviewDossierError("GenOffice source legal file exceeds its size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise GenOfficeLegalReviewDossierError("GenOffice source legal file cannot be read")
                content = source.read(MAX_LEGAL_FILE_SIZE_BYTES + 1)
                if len(content) != member.size:
                    raise GenOfficeLegalReviewDossierError("GenOffice source legal file size is inconsistent")
                selected[relative] = content
    except (OSError, tarfile.TarError) as exc:
        raise GenOfficeLegalReviewDossierError("GenOffice source archive is not readable") from exc
    missing = tuple(sorted(set(GENOFFICE_REQUIRED_SOURCE_LEGAL_PATHS) - set(selected)))
    if missing:
        raise GenOfficeLegalReviewDossierError(f"GenOffice source archive is missing legal evidence: {missing}")
    return selected


def _legal_kind(path: str) -> Literal["license", "notice", "copyright", "readme"] | None:
    name = PurePosixPath(path).name.upper()
    if name.startswith(("LICENSE", "LICENCE", "COPYING")):
        return "license"
    if name.startswith("NOTICE"):
        return "notice"
    if name.startswith("COPYRIGHT"):
        return "copyright"
    if name.startswith(README_PREFIXES):
        return "readme"
    return None


def _text_markers(content: bytes) -> tuple[str, ...]:
    try:
        text = " ".join(content.decode("utf-8").lower().split())
    except UnicodeDecodeError as exc:
        raise GenOfficeLegalReviewDossierError("GenOffice legal evidence file is not UTF-8 text") from exc
    markers: list[str] = []
    patterns = {
        "apache_2_text": ("apache license", "version 2.0"),
        "mit_grant_text": ("permission is hereby granted, free of charge",),
        "isc_grant_text": ("permission to use, copy, modify, and/or distribute this software",),
        "zlib_terms_text": ("altered source versions must be plainly marked",),
        "gpl_3_text": ("gnu general public license", "version 3"),
        "genoffice_notice_attribution": ("genoffice", "mainfunc"),
        "genoffice_trademark_restriction": (
            "genoffice and genspark names and logos are trademarks",
            "does not grant permission to use them",
        ),
        "mainfunc_trademark_owner": ("mainfunc, inc.",),
        "enterprise_license_terms": ("genoffice enterprise license",),
    }
    for marker, required in patterns.items():
        if all(value in text for value in required):
            markers.append(marker)
    return tuple(markers)


def _source_scope(path: str) -> Literal["root", "selected_engine", "vendored_component", "excluded_enterprise"]:
    if path.startswith("ee/"):
        return "excluded_enterprise"
    if path.startswith(f"{EMF_CONVERTER_VENDOR_ROOT}/"):
        return "vendored_component"
    if path.startswith(f"{GENOFFICE_ENGINE_PACKAGE_PATH}/"):
        return "selected_engine"
    return "root"


def _file_evidence(
    *,
    path: str,
    content: bytes,
    scope: Literal[
        "root",
        "selected_engine",
        "vendored_component",
        "excluded_enterprise",
        "runtime_dependency",
        "supplemental_dependency_source",
    ],
    package_name: str | None = None,
    package_version: str | None = None,
) -> GenOfficeLegalFileEvidence:
    markers = _text_markers(content)
    identity = f"{package_name}@{package_version}:{path}" if package_name and package_version else path
    evidence_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
    return GenOfficeLegalFileEvidence(
        evidence_id=stable_hash(canonical_json({"identity": identity, "sha256": evidence_hash})),
        path=path,
        scope=scope,
        kind=_legal_kind(path) or "readme",
        package_name=package_name,
        package_version=package_version,
        size_bytes=len(content),
        sha256=evidence_hash,
        utf8_verified=True,
        detected_markers=markers,
    )


def _read_package_legal_files(archive_path: Path) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    seen: set[str] = set()
    member_count = 0
    total_size = 0
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                member_count += 1
                if member_count > MAX_PACKAGE_MEMBER_COUNT:
                    raise GenOfficeLegalReviewDossierError("npm package archive has too many members")
                path = _safe_archive_path(member.name, root="package")
                if path in seen:
                    raise GenOfficeLegalReviewDossierError("npm package archive contains duplicate paths")
                seen.add(path)
                if not (member.isfile() or member.isdir()):
                    raise GenOfficeLegalReviewDossierError("npm package archive contains links or special files")
                if not member.isfile() or _legal_kind(path) is None:
                    continue
                if member.size < 0 or member.size > MAX_LEGAL_FILE_SIZE_BYTES:
                    raise GenOfficeLegalReviewDossierError("npm package legal file exceeds its size limit")
                total_size += member.size
                if total_size > MAX_PACKAGE_LEGAL_TOTAL_SIZE_BYTES:
                    raise GenOfficeLegalReviewDossierError("npm package legal evidence exceeds its total size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise GenOfficeLegalReviewDossierError("npm package legal file cannot be read")
                content = source.read(MAX_LEGAL_FILE_SIZE_BYTES + 1)
                if len(content) != member.size:
                    raise GenOfficeLegalReviewDossierError("npm package legal file size is inconsistent")
                selected[path.removeprefix("package/")] = content
    except (OSError, tarfile.TarError) as exc:
        raise GenOfficeLegalReviewDossierError("npm package archive is not readable") from exc
    return selected


def _read_supplemental_source_license(
    *, archive_path: Path, supplemental: GenOfficeSupplementalLicenseSourceArtifact
) -> bytes:
    root = f"val-parsers-{supplemental.source_commit}"
    expected_path = f"{root}/LICENSE"
    selected: bytes | None = None
    seen: set[str] = set()
    member_count = 0
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                member_count += 1
                if member_count > MAX_ARCHIVE_MEMBER_COUNT:
                    raise GenOfficeLegalReviewDossierError("supplemental source archive has too many members")
                path = _safe_archive_path(member.name, root=root)
                if path in seen:
                    raise GenOfficeLegalReviewDossierError("supplemental source archive contains duplicate paths")
                seen.add(path)
                if not (member.isfile() or member.isdir()):
                    raise GenOfficeLegalReviewDossierError(
                        "supplemental source archive contains links or special files"
                    )
                if path != expected_path or not member.isfile():
                    continue
                if member.size < 0 or member.size > MAX_LEGAL_FILE_SIZE_BYTES:
                    raise GenOfficeLegalReviewDossierError("supplemental source license exceeds its size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise GenOfficeLegalReviewDossierError("supplemental source license cannot be read")
                content = source.read(MAX_LEGAL_FILE_SIZE_BYTES + 1)
                if len(content) != member.size:
                    raise GenOfficeLegalReviewDossierError("supplemental source license size is inconsistent")
                selected = content
    except (OSError, tarfile.TarError) as exc:
        raise GenOfficeLegalReviewDossierError("supplemental source archive is not readable") from exc
    if selected is None:
        raise GenOfficeLegalReviewDossierError("supplemental source archive lacks its root license")
    return selected


def _verify_package_artifact(path: Path, artifact: GenOfficeLicenseMaterialArtifact) -> None:
    sha256, size = _sha256_file(path, maximum_size=8 * 1024 * 1024)
    if sha256 != artifact.sha256 or size != artifact.size_bytes:
        raise GenOfficeLegalReviewDossierError("npm package archive does not match its collection report")
    digest = hashlib.sha512()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeLegalReviewDossierError("npm package archive cannot be read") from exc
    if f"sha512:{digest.hexdigest()}" != artifact.sha512:
        raise GenOfficeLegalReviewDossierError("npm package SHA-512 does not match its collection report")


def _license_semantics(expression: str) -> Literal["single", "choice", "cumulative"]:
    if expression == "(MIT OR GPL-3.0-or-later)":
        return "choice"
    if expression == "(MIT AND Zlib)":
        return "cumulative"
    if expression in {"MIT", "ISC"}:
        return "single"
    raise GenOfficeLegalReviewDossierError(f"unreviewed runtime license expression: {expression}")


def _required_markers(expression: str) -> tuple[str, ...]:
    expected = {
        "MIT": ("mit_grant_text",),
        "ISC": ("isc_grant_text",),
        "(MIT OR GPL-3.0-or-later)": ("mit_grant_text",),
        "(MIT AND Zlib)": ("mit_grant_text", "zlib_terms_text"),
    }
    try:
        return expected[expression]
    except KeyError as exc:
        raise GenOfficeLegalReviewDossierError(f"unreviewed runtime license expression: {expression}") from exc


def _dependency_license_evidence(
    *,
    dependency: GenOfficeRuntimeDependencyEvidence,
    artifact: GenOfficeLicenseMaterialArtifact,
    artifact_directory: Path,
    supplemental_files: tuple[GenOfficeLegalFileEvidence, ...] = (),
) -> tuple[GenOfficeDependencyLicenseEvidence, tuple[GenOfficeLegalFileEvidence, ...]]:
    if dependency.version is None or dependency.license_expression is None:
        raise GenOfficeLegalReviewDossierError("runtime dependency lacks legal identity metadata")
    if (dependency.name, dependency.version) != (artifact.package_name, artifact.package_version):
        raise GenOfficeLegalReviewDossierError("runtime dependency and license artifact identity differ")
    archive_path = artifact_directory / artifact.artifact_filename
    _verify_package_artifact(archive_path, artifact)
    package_files = _read_package_legal_files(archive_path)
    package_legal_files = tuple(
        _file_evidence(
            path=path,
            content=content,
            scope="runtime_dependency",
            package_name=dependency.name,
            package_version=dependency.version,
        )
        for path, content in sorted(package_files.items())
    )
    legal_files = (*package_legal_files, *supplemental_files)
    detected_markers = tuple(sorted({marker for item in legal_files for marker in item.detected_markers}))
    required_markers = _required_markers(dependency.license_expression)
    complete = bool(legal_files) and set(required_markers).issubset(detected_markers)
    return (
        GenOfficeDependencyLicenseEvidence(
            package_name=dependency.name,
            package_version=dependency.version,
            declared_license_expression=dependency.license_expression,
            expression_semantics=_license_semantics(dependency.license_expression),
            required_text_markers=required_markers,
            detected_text_markers=detected_markers,
            legal_file_evidence_ids=tuple(item.evidence_id for item in legal_files),
            package_archive_sha256=artifact.sha256,
            package_archive_integrity_verified=artifact.integrity_verified,
            license_text_evidence_complete=complete,
            human_license_choice_required=dependency.license_expression == "(MIT OR GPL-3.0-or-later)",
        ),
        tuple(legal_files),
    )


def _review_questions(
    *,
    source_files: tuple[GenOfficeLegalFileEvidence, ...],
    dependencies: tuple[GenOfficeDependencyLicenseEvidence, ...],
) -> tuple[GenOfficeLegalReviewQuestion, ...]:
    by_path = {item.path: item.evidence_id for item in source_files}
    dependency_refs = tuple(
        evidence_id for dependency in dependencies for evidence_id in dependency.legal_file_evidence_ids
    )
    return (
        GenOfficeLegalReviewQuestion(
            question_id="apache-2-distribution-obligations",
            category="license",
            evidence_refs=(by_path["LICENSE"],),
            required_decision=(
                "Confirm Apache-2.0 redistribution, modification notice, attribution, patent and termination "
                "obligations for the approved Collabio distribution model."
            ),
        ),
        GenOfficeLegalReviewQuestion(
            question_id="upstream-notice-preservation",
            category="notice",
            evidence_refs=(by_path["NOTICE"],),
            required_decision=(
                "Approve the exact upstream NOTICE preservation and the Collabio third-party notice artifact."
            ),
        ),
        GenOfficeLegalReviewQuestion(
            question_id="upstream-trademark-exclusion",
            category="trademark",
            evidence_refs=(by_path["README.md"],),
            required_decision=(
                "Confirm Collabio-only branding and prohibit GenOffice, Genspark and upstream logos in product "
                "identity."
            ),
        ),
        GenOfficeLegalReviewQuestion(
            question_id="enterprise-tree-exclusion",
            category="scope",
            evidence_refs=(by_path["ee/LICENSE"],),
            required_decision="Confirm that ee/** remains excluded from source, build context, image and distribution.",
        ),
        GenOfficeLegalReviewQuestion(
            question_id="runtime-compound-license-resolution",
            category="distribution",
            evidence_refs=dependency_refs,
            required_decision=(
                "Resolve each runtime SPDX expression, including the jszip OR choice and cumulative pako MIT AND Zlib "
                "obligations, against the exact package license texts."
            ),
        ),
        GenOfficeLegalReviewQuestion(
            question_id="vendored-emf-license-and-provenance",
            category="license",
            evidence_refs=(by_path[f"{EMF_CONVERTER_VENDOR_ROOT}/LICENSE"],),
            required_decision=(
                "Confirm the vendored emf-converter Apache-2.0 obligations against byte, npm and SLSA provenance "
                "evidence."
            ),
        ),
    )


def _require_linked_reports(
    *,
    source: GenOfficeDocxSourceAdmissionReport,
    vendored: GenOfficeVendoredProvenanceAdmissionReport,
    supply_chain: GenOfficeDocxSupplyChainAdmissionReport,
    npm_provenance: GenOfficeNpmProvenanceAdmissionReport,
    collection: GenOfficeLicenseMaterialCollectionReport,
) -> None:
    expected = (
        (source.report_hash, GENOFFICE_REVIEWED_SOURCE_REPORT_HASH),
        (vendored.report_hash, GENOFFICE_REVIEWED_VENDORED_REPORT_HASH),
        (supply_chain.report_hash, GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH),
        (npm_provenance.report_hash, GENOFFICE_REVIEWED_NPM_PROVENANCE_REPORT_HASH),
        (vendored.source_report_hash, source.report_hash),
        (supply_chain.source_report_hash, source.report_hash),
        (supply_chain.vendored_provenance_report_hash, vendored.report_hash),
        (npm_provenance.vendored_provenance_report_hash, vendored.report_hash),
        (collection.source_report_hash, source.report_hash),
        (collection.source_archive_sha256, source.archive_sha256),
    )
    if any(actual != required for actual, required in expected):
        raise GenOfficeLegalReviewDossierError("GenOffice legal dossier evidence chain is not pinned")
    if not (
        source.source_snapshot_verified
        and vendored.byte_provenance_verified
        and supply_chain.automated_sbom_and_vulnerability_gate_passed
        and npm_provenance.cryptographic_provenance_gate_passed
        and collection.all_artifact_integrities_verified
    ):
        raise GenOfficeLegalReviewDossierError("GenOffice legal dossier prerequisite evidence is incomplete")


def build_genoffice_legal_review_dossier(
    *,
    source_report: GenOfficeDocxSourceAdmissionReport,
    source_archive_path: Path,
    vendored_report: GenOfficeVendoredProvenanceAdmissionReport,
    supply_chain_report: GenOfficeDocxSupplyChainAdmissionReport,
    npm_provenance_report: GenOfficeNpmProvenanceAdmissionReport,
    collection_report: GenOfficeLicenseMaterialCollectionReport,
    artifact_directory: Path,
) -> GenOfficeLegalReviewDossierReport:
    if build_genoffice_license_material_collection_report_hash(collection_report) != collection_report.report_hash:
        raise GenOfficeLegalReviewDossierError("GenOffice license material collection report hash is invalid")
    _require_linked_reports(
        source=source_report,
        vendored=vendored_report,
        supply_chain=supply_chain_report,
        npm_provenance=npm_provenance_report,
        collection=collection_report,
    )
    archive_sha256, _ = _sha256_file(source_archive_path, maximum_size=MAX_SOURCE_ARCHIVE_SIZE_BYTES)
    if archive_sha256 != source_report.archive_sha256:
        raise GenOfficeLegalReviewDossierError("GenOffice source archive does not match its admission report")

    selected_source = _read_selected_source_legal_files(source_archive_path)
    source_files = tuple(
        _file_evidence(path=path, content=content, scope=_source_scope(path))
        for path, content in sorted(selected_source.items())
    )
    source_by_path = {item.path: item for item in source_files}
    supplemental = collection_report.supplemental_source_artifacts[0]
    metadata_hash, _ = _sha256_file(
        artifact_directory / supplemental.registry_metadata_filename,
        maximum_size=1024 * 1024,
    )
    if metadata_hash != supplemental.registry_metadata_sha256:
        raise GenOfficeLegalReviewDossierError("supplemental registry metadata hash is inconsistent")
    supplemental_archive_path = artifact_directory / supplemental.source_archive_filename
    supplemental_archive_hash, supplemental_archive_size = _sha256_file(
        supplemental_archive_path,
        maximum_size=8 * 1024 * 1024,
    )
    if (
        supplemental_archive_hash != supplemental.source_archive_sha256
        or supplemental_archive_size != supplemental.source_archive_size_bytes
    ):
        raise GenOfficeLegalReviewDossierError("supplemental source archive does not match its collection report")
    supplemental_license = _read_supplemental_source_license(
        archive_path=supplemental_archive_path,
        supplemental=supplemental,
    )
    supplemental_evidence = _file_evidence(
        path=f"supplemental/{supplemental.package_name}@{supplemental.package_version}/LICENSE",
        content=supplemental_license,
        scope="supplemental_dependency_source",
        package_name=supplemental.package_name,
        package_version=supplemental.package_version,
    )
    supplemental_verified = "mit_grant_text" in supplemental_evidence.detected_markers
    supplemental_by_identity = {
        (supplemental.package_name, supplemental.package_version): (supplemental_evidence,)
    }
    artifact_by_identity = {(item.package_name, item.package_version): item for item in collection_report.artifacts}
    dependency_licenses: list[GenOfficeDependencyLicenseEvidence] = []
    dependency_files: list[GenOfficeLegalFileEvidence] = []
    for dependency in sorted(source_report.runtime_dependencies, key=lambda item: (item.name, item.version or "")):
        if dependency.version is None:
            raise GenOfficeLegalReviewDossierError("runtime dependency lacks a version")
        artifact = artifact_by_identity.get((dependency.name, dependency.version))
        if artifact is None:
            raise GenOfficeLegalReviewDossierError("runtime dependency lacks collected license material")
        license_evidence, legal_files = _dependency_license_evidence(
            dependency=dependency,
            artifact=artifact,
            artifact_directory=artifact_directory,
            supplemental_files=supplemental_by_identity.get((dependency.name, dependency.version), ()),
        )
        dependency_licenses.append(license_evidence)
        dependency_files.extend(legal_files)
    if len(artifact_by_identity) != len(dependency_licenses):
        raise GenOfficeLegalReviewDossierError("license material collection contains unexpected runtime packages")

    ordered_dependencies = tuple(dependency_licenses)
    ordered_dependency_files = tuple(
        sorted(dependency_files, key=lambda item: (item.package_name or "", item.package_version or "", item.path))
    )
    root_apache_verified = "apache_2_text" in source_by_path["LICENSE"].detected_markers
    notice_present = source_by_path["NOTICE"].kind == "notice"
    readme_markers = set(source_by_path["README.md"].detected_markers)
    trademark_verified = {
        "genoffice_trademark_restriction",
        "mainfunc_trademark_owner",
    }.issubset(readme_markers)
    enterprise_excluded = (
        "enterprise_license_terms" in source_by_path["ee/LICENSE"].detected_markers
        and "ee/" in GENOFFICE_PROHIBITED_SCOPE_PREFIXES
        and source_report.prohibited_scopes_excluded_from_manifest
    )
    vendored_apache_verified = (
        "apache_2_text" in source_by_path[f"{EMF_CONVERTER_VENDOR_ROOT}/LICENSE"].detected_markers
    )
    all_integrities = all(item.package_archive_integrity_verified for item in ordered_dependencies)
    all_license_text = all(item.license_text_evidence_complete for item in ordered_dependencies)
    automated_complete = all(
        (
            root_apache_verified,
            notice_present,
            trademark_verified,
            enterprise_excluded,
            vendored_apache_verified,
            supplemental_verified,
            all_integrities,
            all_license_text,
            len(ordered_dependencies) == source_report.runtime_dependency_count,
        )
    )
    decision_schema_hash = stable_hash(canonical_json(GenOfficeLegalDecisionRecord.model_json_schema()))
    questions = _review_questions(source_files=source_files, dependencies=ordered_dependencies)
    draft = GenOfficeLegalReviewDossierReport(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_report.archive_sha256,
        vendored_provenance_report_hash=vendored_report.report_hash,
        supply_chain_admission_report_hash=supply_chain_report.report_hash,
        npm_provenance_admission_report_hash=npm_provenance_report.report_hash,
        license_material_collection_report_hash=collection_report.report_hash,
        legal_decision_record_schema_version=GENOFFICE_LEGAL_DECISION_RECORD_SCHEMA_VERSION,
        legal_decision_record_schema_hash=decision_schema_hash,
        source_legal_files=source_files,
        dependency_legal_files=ordered_dependency_files,
        dependency_licenses=ordered_dependencies,
        runtime_dependency_count=len(ordered_dependencies),
        runtime_dependency_license_file_count=len(ordered_dependency_files),
        compound_license_packages=tuple(
            item.package_name for item in ordered_dependencies if item.expression_semantics != "single"
        ),
        root_apache_2_license_text_marker_verified=root_apache_verified,
        root_notice_present=notice_present,
        upstream_trademark_restriction_verified=trademark_verified,
        upstream_trademark_owner="Mainfunc, Inc.",
        enterprise_license_present_and_scope_excluded=enterprise_excluded,
        vendored_apache_2_license_text_marker_verified=vendored_apache_verified,
        supplemental_dependency_source_license_verified=supplemental_verified,
        all_runtime_package_integrities_verified=all_integrities,
        all_runtime_license_text_evidence_complete=all_license_text,
        automated_legal_evidence_complete=automated_complete,
        human_review_ready=automated_complete,
        review_questions=questions,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_legal_review_dossier_hash(draft)})


def build_genoffice_legal_review_dossier_hash(report: GenOfficeLegalReviewDossierReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_genoffice_legal_decision_record_hash(record: GenOfficeLegalDecisionRecord) -> str:
    return stable_hash(canonical_json(record.model_dump(mode="json", exclude={"record_hash"})))


def persist_genoffice_legal_review_dossier(*, report: GenOfficeLegalReviewDossierReport, report_path: Path) -> None:
    if build_genoffice_legal_review_dossier_hash(report) != report.report_hash:
        raise GenOfficeLegalReviewDossierError("GenOffice legal dossier report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def persist_genoffice_legal_decision_record_schema(schema_path: Path) -> None:
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = schema_path.with_suffix(schema_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(GenOfficeLegalDecisionRecord.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(schema_path)


def load_genoffice_legal_review_dossier(report_path: Path) -> GenOfficeLegalReviewDossierReport:
    try:
        report = GenOfficeLegalReviewDossierReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeLegalReviewDossierError("GenOffice legal dossier report is not readable") from exc
    if build_genoffice_legal_review_dossier_hash(report) != report.report_hash:
        raise GenOfficeLegalReviewDossierError("GenOffice legal dossier report hash is invalid")
    return report


def run_genoffice_legal_review_dossier_from_environment(
    env: dict[str, str] | os._Environ[str],
) -> GenOfficeLegalReviewDossierReport:
    values = {
        "source_report": env.get("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH", "").strip(),
        "source_archive": env.get("SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH", "").strip(),
        "vendored_report": env.get("SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH", "").strip(),
        "supply_chain_report": env.get("SUITE_GENOFFICE_SUPPLY_CHAIN_ADMISSION_REPORT_PATH", "").strip(),
        "npm_provenance_report": env.get("SUITE_GENOFFICE_NPM_PROVENANCE_ADMISSION_REPORT_PATH", "").strip(),
        "collection_report": env.get("SUITE_GENOFFICE_LICENSE_MATERIAL_REPORT_PATH", "").strip(),
        "artifact_directory": env.get("SUITE_GENOFFICE_LICENSE_MATERIAL_DIRECTORY", "").strip(),
    }
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeLegalReviewDossierError(f"GenOffice legal dossier paths are missing: {missing}")
    return build_genoffice_legal_review_dossier(
        source_report=load_genoffice_docx_source_admission_report(Path(values["source_report"])),
        source_archive_path=Path(values["source_archive"]),
        vendored_report=load_genoffice_vendored_provenance_report(Path(values["vendored_report"])),
        supply_chain_report=load_genoffice_docx_supply_chain_admission_report(Path(values["supply_chain_report"])),
        npm_provenance_report=load_genoffice_npm_provenance_admission_report(Path(values["npm_provenance_report"])),
        collection_report=load_genoffice_license_material_collection_report(Path(values["collection_report"])),
        artifact_directory=Path(values["artifact_directory"]),
    )


def main() -> None:
    try:
        report = run_genoffice_legal_review_dossier_from_environment(os.environ)
        report_path_value = os.environ.get("SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH", "").strip()
        schema_path_value = os.environ.get("SUITE_GENOFFICE_LEGAL_DECISION_SCHEMA_PATH", "").strip()
        if not report_path_value or not schema_path_value:
            raise GenOfficeLegalReviewDossierError("GenOffice legal dossier output paths are required")
        persist_genoffice_legal_review_dossier(report=report, report_path=Path(report_path_value))
        persist_genoffice_legal_decision_record_schema(Path(schema_path_value))
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        raise SystemExit(0 if report.human_review_ready else 2)
    except GenOfficeLegalReviewDossierError as exc:
        print(
            json.dumps(
                {"error": str(exc), "schema_version": GENOFFICE_LEGAL_REVIEW_DOSSIER_SCHEMA_VERSION},
                sort_keys=True,
            )
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
