from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_legal_review_dossier import (
    GenOfficeDependencyLicenseEvidence,
    GenOfficeLegalFileEvidence,
    GenOfficeLegalReviewDossierReport,
    _read_package_legal_files,
    _read_selected_source_legal_files,
    _read_supplemental_source_license,
    load_genoffice_legal_review_dossier,
)
from suite.operations.genoffice_license_material_collector import (
    GenOfficeLicenseMaterialCollectionReport,
    load_genoffice_license_material_collection_report,
)

GENOFFICE_THIRD_PARTY_NOTICE_REPORT_SCHEMA_VERSION = "genoffice_third_party_notice_report.v1"
GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH = "sha256:eb523d13b0cb10fea752c4e0d549a9c06f2736e4f3f38721bb7b0ba948614c5a"
GENOFFICE_DEVELOPMENT_PROFILE = "development_evaluation"
GENOFFICE_SELECTED_SOURCE_SCOPE = "packages/docx-engine/**"
GENOFFICE_VENDORED_LICENSE_PATH = "packages/docx-engine/src/vendor/emf-converter/LICENSE"
MAX_NOTICE_SIZE_BYTES = 4 * 1024 * 1024


class GenOfficeThirdPartyNoticeError(ValueError):
    pass


class GenOfficeThirdPartyNoticeFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    source_sha256: str
    kind: Literal["license", "notice", "copyright", "readme"]


class GenOfficeThirdPartyNoticeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_name: str
    component_version: str
    declared_license_expression: str
    selected_distribution_license_expression: str
    source_artifact_sha256: str
    included_files: tuple[GenOfficeThirdPartyNoticeFile, ...]


class GenOfficeThirdPartyNoticeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_third_party_notice_report.v1"] = "genoffice_third_party_notice_report.v1"
    legal_dossier_report_hash: str
    license_material_collection_report_hash: str
    source_archive_sha256: str
    approved_usage_profile: Literal["development_evaluation"] = "development_evaluation"
    selected_source_scopes: tuple[str, ...]
    enterprise_scope_excluded: bool
    collabio_brand_only: bool
    component_count: int
    included_legal_file_count: int
    components: tuple[GenOfficeThirdPartyNoticeComponent, ...]
    notice_artifact_size_bytes: int
    notice_artifact_sha256: str
    deterministic_render_verified: bool
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    production_use_allowed: bool = False
    on_prem_distribution_allowed: bool = False
    report_hash: str

    @model_validator(mode="after")
    def require_notice_only_closed_boundary(self) -> GenOfficeThirdPartyNoticeReport:
        if self.legal_dossier_report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH:
            raise ValueError("GenOffice third-party notice dossier is not pinned")
        if self.selected_source_scopes != (GENOFFICE_SELECTED_SOURCE_SCOPE,):
            raise ValueError("GenOffice third-party notice source scope is not pinned")
        if self.component_count != len(self.components) or self.component_count != 23:
            raise ValueError("GenOffice third-party notice component inventory is incomplete")
        if self.included_legal_file_count != sum(len(item.included_files) for item in self.components):
            raise ValueError("GenOffice third-party notice legal-file count is inconsistent")
        if not all(
            (
                self.enterprise_scope_excluded,
                self.collabio_brand_only,
                self.deterministic_render_verified,
                self.notice_artifact_size_bytes > 0,
            )
        ):
            raise ValueError("GenOffice third-party notice evidence is incomplete")
        if any(
            (
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.production_use_allowed,
                self.on_prem_distribution_allowed,
            )
        ):
            raise ValueError("GenOffice third-party notice opened a runtime or distribution boundary")
        return self


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _sha256_file(path: Path, *, maximum_size: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_size:
                    raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice input exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice input cannot be read") from exc
    return f"sha256:{digest.hexdigest()}", size


def _selected_distribution_expression(dependency: GenOfficeDependencyLicenseEvidence) -> str:
    if dependency.package_name == "jszip" and dependency.declared_license_expression == "(MIT OR GPL-3.0-or-later)":
        return "MIT"
    if dependency.package_name == "pako" and dependency.declared_license_expression == "(MIT AND Zlib)":
        return "MIT AND Zlib"
    if dependency.expression_semantics == "single" and dependency.declared_license_expression in {"MIT", "ISC"}:
        return dependency.declared_license_expression
    raise GenOfficeThirdPartyNoticeError("GenOffice dependency license expression lacks an internal policy decision")


def _required_dependency_files(
    *,
    dependency: GenOfficeDependencyLicenseEvidence,
    evidence: tuple[GenOfficeLegalFileEvidence, ...],
) -> tuple[GenOfficeLegalFileEvidence, ...]:
    required_markers = set(dependency.required_text_markers)
    selected = [item for item in evidence if item.kind in {"license", "notice", "copyright"}]
    detected = {marker for item in selected for marker in item.detected_markers}
    for item in evidence:
        if item.kind == "readme" and not required_markers.issubset(detected):
            selected.append(item)
            detected.update(item.detected_markers)
    if not required_markers.issubset(detected):
        raise GenOfficeThirdPartyNoticeError("GenOffice dependency notice selection lacks required license text")
    return tuple(sorted(selected, key=lambda item: (item.kind, item.path, item.evidence_id)))


def _render_component(
    *,
    component: GenOfficeThirdPartyNoticeComponent,
    contents: Mapping[str, bytes],
) -> str:
    lines = [
        "=" * 80,
        f"Component: {component.component_name}@{component.component_version}",
        f"Declared license: {component.declared_license_expression}",
        f"Selected distribution license: {component.selected_distribution_license_expression}",
        f"Source artifact: {component.source_artifact_sha256}",
        "",
    ]
    for item in component.included_files:
        content = contents.get(item.source_sha256)
        if content is None or _sha256_bytes(content) != item.source_sha256:
            raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice content is not bound to its evidence")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice content is not UTF-8") from exc
        lines.extend((f"--- {item.source_path} [{item.kind}] ---", text.rstrip(), ""))
    return "\n".join(lines).rstrip() + "\n"


def build_genoffice_third_party_notice(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    collection: GenOfficeLicenseMaterialCollectionReport,
    source_archive_path: Path,
    artifact_directory: Path,
) -> tuple[bytes, GenOfficeThirdPartyNoticeReport]:
    if dossier.report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH or not dossier.human_review_ready:
        raise GenOfficeThirdPartyNoticeError("GenOffice legal dossier is not ready for internal OSS review")
    if collection.report_hash != dossier.license_material_collection_report_hash:
        raise GenOfficeThirdPartyNoticeError("GenOffice notice collection is not linked to the legal dossier")
    source_hash, _ = _sha256_file(source_archive_path, maximum_size=64 * 1024 * 1024)
    if source_hash != dossier.source_archive_sha256:
        raise GenOfficeThirdPartyNoticeError("GenOffice notice source archive is not pinned")

    source_files = _read_selected_source_legal_files(source_archive_path)
    source_evidence = {item.path: item for item in dossier.source_legal_files}
    components: list[GenOfficeThirdPartyNoticeComponent] = []
    content_by_hash: dict[str, bytes] = {}

    root_files: list[GenOfficeThirdPartyNoticeFile] = []
    for path in ("LICENSE", "NOTICE"):
        evidence = source_evidence[path]
        content = source_files[path]
        if _sha256_bytes(content) != evidence.sha256:
            raise GenOfficeThirdPartyNoticeError("GenOffice root notice evidence hash is inconsistent")
        content_by_hash[evidence.sha256] = content
        root_files.append(
            GenOfficeThirdPartyNoticeFile(source_path=path, source_sha256=evidence.sha256, kind=evidence.kind)
        )
    components.append(
        GenOfficeThirdPartyNoticeComponent(
            component_name="GenOffice selected DOCX engine source",
            component_version=dossier.source_archive_sha256.removeprefix("sha256:")[:12],
            declared_license_expression="Apache-2.0",
            selected_distribution_license_expression="Apache-2.0",
            source_artifact_sha256=dossier.source_archive_sha256,
            included_files=tuple(root_files),
        )
    )

    vendor_evidence = source_evidence[GENOFFICE_VENDORED_LICENSE_PATH]
    vendor_content = source_files[GENOFFICE_VENDORED_LICENSE_PATH]
    if _sha256_bytes(vendor_content) != vendor_evidence.sha256:
        raise GenOfficeThirdPartyNoticeError("GenOffice vendored license evidence hash is inconsistent")
    content_by_hash[vendor_evidence.sha256] = vendor_content
    components.append(
        GenOfficeThirdPartyNoticeComponent(
            component_name="emf-converter",
            component_version="2.0.2",
            declared_license_expression="Apache-2.0",
            selected_distribution_license_expression="Apache-2.0",
            source_artifact_sha256=dossier.vendored_provenance_report_hash,
            included_files=(
                GenOfficeThirdPartyNoticeFile(
                    source_path=GENOFFICE_VENDORED_LICENSE_PATH,
                    source_sha256=vendor_evidence.sha256,
                    kind=vendor_evidence.kind,
                ),
            ),
        )
    )

    artifacts = {(item.package_name, item.package_version): item for item in collection.artifacts}
    evidence_by_identity: dict[tuple[str, str], list[GenOfficeLegalFileEvidence]] = {}
    for item in dossier.dependency_legal_files:
        if item.package_name is None or item.package_version is None:
            raise GenOfficeThirdPartyNoticeError("GenOffice dependency legal evidence lacks package identity")
        evidence_by_identity.setdefault((item.package_name, item.package_version), []).append(item)
    supplemental = collection.supplemental_source_artifacts[0]
    supplemental_content = _read_supplemental_source_license(
        archive_path=artifact_directory / supplemental.source_archive_filename,
        supplemental=supplemental,
    )

    for dependency in dossier.dependency_licenses:
        identity = (dependency.package_name, dependency.package_version)
        artifact = artifacts.get(identity)
        if artifact is None:
            raise GenOfficeThirdPartyNoticeError("GenOffice dependency notice lacks its package archive")
        package_contents = _read_package_legal_files(artifact_directory / artifact.artifact_filename)
        selected_evidence = _required_dependency_files(
            dependency=dependency,
            evidence=tuple(evidence_by_identity.get(identity, ())),
        )
        included_files: list[GenOfficeThirdPartyNoticeFile] = []
        for evidence in selected_evidence:
            if evidence.scope == "supplemental_dependency_source":
                content = supplemental_content
            else:
                content = package_contents.get(evidence.path)
                if content is None:
                    raise GenOfficeThirdPartyNoticeError("GenOffice dependency legal file is absent from its archive")
            if _sha256_bytes(content) != evidence.sha256:
                raise GenOfficeThirdPartyNoticeError("GenOffice dependency legal file hash is inconsistent")
            content_by_hash[evidence.sha256] = content
            included_files.append(
                GenOfficeThirdPartyNoticeFile(
                    source_path=evidence.path,
                    source_sha256=evidence.sha256,
                    kind=evidence.kind,
                )
            )
        components.append(
            GenOfficeThirdPartyNoticeComponent(
                component_name=dependency.package_name,
                component_version=dependency.package_version,
                declared_license_expression=dependency.declared_license_expression,
                selected_distribution_license_expression=_selected_distribution_expression(dependency),
                source_artifact_sha256=artifact.sha256,
                included_files=tuple(included_files),
            )
        )

    ordered_components = tuple(components[:2] + sorted(components[2:], key=lambda item: item.component_name))
    header = (
        "Collabio THIRD_PARTY_NOTICES\n"
        "Usage profile: development_evaluation\n"
        "Selected source scope: packages/docx-engine/**\n"
        "Brand policy: Collabio only; no GenOffice or Genspark marks\n"
        "Excluded source scope: ee/** and all prohibited source paths in the pinned admission report\n"
        f"Legal dossier: {dossier.report_hash}\n\n"
    )
    rendered = header + "".join(
        _render_component(component=item, contents=content_by_hash) for item in ordered_components
    )
    notice = rendered.encode("utf-8")
    if len(notice) > MAX_NOTICE_SIZE_BYTES:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice exceeds its size limit")
    notice_hash = _sha256_bytes(notice)
    draft = GenOfficeThirdPartyNoticeReport(
        legal_dossier_report_hash=dossier.report_hash,
        license_material_collection_report_hash=collection.report_hash,
        source_archive_sha256=dossier.source_archive_sha256,
        selected_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        enterprise_scope_excluded=dossier.enterprise_license_present_and_scope_excluded,
        collabio_brand_only=dossier.upstream_trademark_restriction_verified,
        component_count=len(ordered_components),
        included_legal_file_count=sum(len(item.included_files) for item in ordered_components),
        components=ordered_components,
        notice_artifact_size_bytes=len(notice),
        notice_artifact_sha256=notice_hash,
        deterministic_render_verified=True,
        report_hash="sha256:" + "0" * 64,
    )
    report = draft.model_copy(update={"report_hash": build_genoffice_third_party_notice_report_hash(draft)})
    return notice, report


def build_genoffice_third_party_notice_report_hash(report: GenOfficeThirdPartyNoticeReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_third_party_notice(
    *,
    notice: bytes,
    report: GenOfficeThirdPartyNoticeReport,
    notice_path: Path,
    report_path: Path,
) -> None:
    if _sha256_bytes(notice) != report.notice_artifact_sha256:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice artifact hash is invalid")
    if build_genoffice_third_party_notice_report_hash(report) != report.report_hash:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice report hash is invalid")
    notice_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    notice_temporary = notice_path.with_suffix(notice_path.suffix + ".tmp")
    report_temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    notice_temporary.write_bytes(notice)
    report_temporary.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    notice_temporary.replace(notice_path)
    report_temporary.replace(report_path)


def load_genoffice_third_party_notice_report(report_path: Path) -> GenOfficeThirdPartyNoticeReport:
    try:
        report = GenOfficeThirdPartyNoticeReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice report is not readable") from exc
    if build_genoffice_third_party_notice_report_hash(report) != report.report_hash:
        raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice report hash is invalid")
    return report


def run_genoffice_third_party_notice_from_environment(
    env: Mapping[str, str],
) -> tuple[bytes, GenOfficeThirdPartyNoticeReport]:
    values = {
        "dossier": env.get("SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH", "").strip(),
        "collection": env.get("SUITE_GENOFFICE_LICENSE_MATERIAL_REPORT_PATH", "").strip(),
        "source_archive": env.get("SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH", "").strip(),
        "artifact_directory": env.get("SUITE_GENOFFICE_LICENSE_MATERIAL_DIRECTORY", "").strip(),
    }
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeThirdPartyNoticeError(f"GenOffice third-party notice paths are missing: {missing}")
    return build_genoffice_third_party_notice(
        dossier=load_genoffice_legal_review_dossier(Path(values["dossier"])),
        collection=load_genoffice_license_material_collection_report(Path(values["collection"])),
        source_archive_path=Path(values["source_archive"]),
        artifact_directory=Path(values["artifact_directory"]),
    )


def main() -> None:
    try:
        notice, report = run_genoffice_third_party_notice_from_environment(os.environ)
        notice_path = os.environ.get("SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH", "").strip()
        report_path = os.environ.get("SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH", "").strip()
        if not notice_path or not report_path:
            raise GenOfficeThirdPartyNoticeError("GenOffice third-party notice output paths are required")
        persist_genoffice_third_party_notice(
            notice=notice,
            report=report,
            notice_path=Path(notice_path),
            report_path=Path(report_path),
        )
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    except GenOfficeThirdPartyNoticeError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_THIRD_PARTY_NOTICE_REPORT_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
