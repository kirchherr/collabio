from __future__ import annotations

import hashlib
import json
import os
import tarfile
from collections import deque
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.office_edit_adapter import (
    GENOFFICE_UPSTREAM_COMMIT,
    GENOFFICE_UPSTREAM_REPOSITORY,
    GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256,
)

GENOFFICE_DOCX_SOURCE_ADMISSION_SCHEMA_VERSION = "genoffice_docx_source_admission_report.v1"
GENOFFICE_ARCHIVE_ROOT = f"genoffice-{GENOFFICE_UPSTREAM_COMMIT}"
GENOFFICE_ENGINE_PACKAGE_PATH = "packages/docx-engine"
GENOFFICE_REQUIRED_EVIDENCE_PATHS = (
    "LICENSE",
    "package-lock.json",
    "package.json",
    f"{GENOFFICE_ENGINE_PACKAGE_PATH}/package.json",
)
GENOFFICE_REQUIRED_DIRECT_DEPENDENCIES = {
    "fast-xml-parser": "^5.3.4",
    "jszip": "^3.10.1",
}
GENOFFICE_PROHIBITED_SCOPE_PREFIXES = (
    "ee/",
    "apps/shell/",
    "packages/ai-provider/",
    "packages/ai-search/",
)
NPM_LIFECYCLE_SCRIPT_NAMES = frozenset(
    {
        "preinstall",
        "install",
        "postinstall",
        "prepack",
        "prepare",
        "prepublish",
        "prepublishOnly",
    }
)
REMAINING_ADMISSION_GATES = (
    "human_legal_notice_trademark_and_vendor_provenance_review",
    "cyclonedx_sbom_and_vulnerability_review",
    "reproducible_isolated_build_and_signed_provenance",
    "malicious_ooxml_and_archive_expansion_corpus",
    "word_libreoffice_genoffice_collabio_fidelity_corpus",
    "isolated_engine_worker_and_resource_limits",
    "candidate_revalidation_preview_confirmation_and_receipt",
    "draft_candidate_receipt_backup_restore_and_failover_drill",
)
MAX_ARCHIVE_SIZE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBER_COUNT = 25_000
MAX_SELECTED_MEMBER_SIZE_BYTES = 16 * 1024 * 1024
MAX_SELECTED_TOTAL_SIZE_BYTES = 64 * 1024 * 1024


class GenOfficeSourceAdmissionError(ValueError):
    pass


class GenOfficeSourceFileEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    role: Literal[
        "upstream_evidence",
        "candidate_build_metadata",
        "candidate_runtime_source",
        "vendored_runtime_source",
        "evaluation_only",
    ]
    size_bytes: int
    sha256: str
    executable_mode_present: bool


class GenOfficeVendoredComponentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_path: str
    file_count: int
    license_files: tuple[str, ...]
    license_file_hashes: tuple[str, ...]


class GenOfficeRuntimeDependencyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    requested_range: str | None
    version: str | None
    license_expression: str | None
    resolved_url: str | None
    integrity: str | None
    dependencies: tuple[str, ...]
    direct: bool
    install_script_declared: bool
    registry_source_verified: bool
    integrity_metadata_verified: bool
    license_metadata_present: bool


class GenOfficeDocxSourceAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_docx_source_admission_report.v1"] = "genoffice_docx_source_admission_report.v1"
    repository_url: str
    upstream_commit: str
    archive_root: str
    archive_size_bytes: int
    archive_sha256: str
    expected_archive_sha256: str
    archive_member_count: int
    selected_file_count: int
    selected_total_size_bytes: int
    source_manifest_hash: str
    source_files: tuple[GenOfficeSourceFileEvidence, ...]
    prohibited_scopes_present_upstream: tuple[str, ...]
    prohibited_scopes_excluded_from_manifest: bool
    root_package_name: str
    root_package_version: str
    root_license_spdx: str
    root_lifecycle_scripts: tuple[str, ...]
    engine_package_name: str
    engine_package_version: str
    engine_license_spdx: str
    engine_lifecycle_scripts: tuple[str, ...]
    lockfile_version: int
    direct_runtime_dependencies: tuple[str, ...]
    runtime_dependency_count: int
    runtime_dependency_manifest_hash: str
    runtime_dependencies: tuple[GenOfficeRuntimeDependencyEvidence, ...]
    vendored_components: tuple[GenOfficeVendoredComponentEvidence, ...]
    exact_archive_verified: bool
    source_scope_manifest_verified: bool
    dependency_lock_verified: bool
    runtime_dependency_closure_verified: bool
    dependency_integrity_metadata_complete: bool
    dependency_license_metadata_complete: bool
    runtime_install_scripts_absent: bool
    vendored_license_files_present: bool
    lifecycle_execution_prevented: bool
    source_snapshot_verified: bool
    snapshot_blocking_reasons: tuple[str, ...]
    legal_review_complete: bool = False
    sbom_complete: bool = False
    vulnerability_review_complete: bool = False
    reproducible_build_and_provenance_complete: bool = False
    engine_execution_allowed: bool = False
    source_import_allowed: bool = False
    production_use_allowed: bool = False
    remaining_admission_gates: tuple[str, ...] = REMAINING_ADMISSION_GATES
    report_hash: str

    @model_validator(mode="after")
    def require_closed_and_pinned_boundary(self) -> GenOfficeDocxSourceAdmissionReport:
        if self.repository_url != GENOFFICE_UPSTREAM_REPOSITORY:
            raise ValueError("GenOffice source report repository is not pinned")
        if self.upstream_commit != GENOFFICE_UPSTREAM_COMMIT:
            raise ValueError("GenOffice source report commit is not pinned")
        if self.archive_root != GENOFFICE_ARCHIVE_ROOT:
            raise ValueError("GenOffice source report archive root is not pinned")
        if self.expected_archive_sha256 != GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256:
            raise ValueError("GenOffice source report expected archive hash is not reviewed")
        if any(
            (
                self.legal_review_complete,
                self.sbom_complete,
                self.vulnerability_review_complete,
                self.reproducible_build_and_provenance_complete,
                self.engine_execution_allowed,
                self.source_import_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice source inventory opened an unreviewed execution boundary")
        if self.remaining_admission_gates != REMAINING_ADMISSION_GATES:
            raise ValueError("GenOffice source report remaining gates changed")
        return self


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_SIZE_BYTES:
                    raise GenOfficeSourceAdmissionError("GenOffice source archive exceeds the admission size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeSourceAdmissionError("GenOffice source archive cannot be read") from exc
    return f"sha256:{digest.hexdigest()}", size


def _open_source_archive(path: Path) -> tarfile.TarFile:
    try:
        return tarfile.open(path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise GenOfficeSourceAdmissionError("GenOffice source archive is not a readable gzip tar archive") from exc


def _relative_archive_path(name: str) -> str | None:
    if not name or "\\" in name or name.startswith("/"):
        raise GenOfficeSourceAdmissionError("GenOffice source archive contains an unsafe member path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise GenOfficeSourceAdmissionError("GenOffice source archive contains a non-canonical member path")
    if not path.parts or path.parts[0] != GENOFFICE_ARCHIVE_ROOT:
        raise GenOfficeSourceAdmissionError("GenOffice source archive root does not match the reviewed commit")
    if len(path.parts) == 1:
        return None
    return PurePosixPath(*path.parts[1:]).as_posix()


def _source_role(path: str) -> str | None:
    if path in {"LICENSE", "package-lock.json", "package.json"}:
        return "upstream_evidence"
    package_prefix = f"{GENOFFICE_ENGINE_PACKAGE_PATH}/"
    if not path.startswith(package_prefix):
        return None
    package_relative = path.removeprefix(package_prefix)
    if package_relative in {"package.json", "tsconfig.json"}:
        return "candidate_build_metadata"
    if package_relative.startswith("src/vendor/"):
        return "vendored_runtime_source"
    if package_relative.startswith("src/"):
        return "candidate_runtime_source"
    return "evaluation_only"


def _json_object(raw: bytes, *, path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeSourceAdmissionError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise GenOfficeSourceAdmissionError(f"{path} must contain a JSON object")
    return value


def _string_mapping(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise GenOfficeSourceAdmissionError(f"{field} must be a string mapping")
    return dict(value)


def _lifecycle_scripts(package: Mapping[str, Any]) -> tuple[str, ...]:
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        raise GenOfficeSourceAdmissionError("package scripts must be an object")
    return tuple(sorted(name for name in scripts if isinstance(name, str) and name in NPM_LIFECYCLE_SCRIPT_NAMES))


def _runtime_dependency_evidence(
    *,
    lock_packages: Mapping[str, Any],
    direct_dependencies: Mapping[str, str],
) -> tuple[tuple[GenOfficeRuntimeDependencyEvidence, ...], tuple[str, ...]]:
    queue = deque(sorted(direct_dependencies))
    queued = set(queue)
    evidence: list[GenOfficeRuntimeDependencyEvidence] = []
    blockers: set[str] = set()

    while queue:
        name = queue.popleft()
        package_key = f"node_modules/{name}"
        raw_entry = lock_packages.get(package_key)
        if not isinstance(raw_entry, dict):
            blockers.add(f"runtime_dependency_missing_from_lock:{name}")
            evidence.append(
                GenOfficeRuntimeDependencyEvidence(
                    name=name,
                    requested_range=direct_dependencies.get(name),
                    version=None,
                    license_expression=None,
                    resolved_url=None,
                    integrity=None,
                    dependencies=(),
                    direct=name in direct_dependencies,
                    install_script_declared=False,
                    registry_source_verified=False,
                    integrity_metadata_verified=False,
                    license_metadata_present=False,
                )
            )
            continue

        dependency_map = _string_mapping(raw_entry.get("dependencies", {}), field=f"{package_key}.dependencies")
        for dependency_name in sorted(dependency_map):
            if dependency_name not in queued:
                queued.add(dependency_name)
                queue.append(dependency_name)

        version = raw_entry.get("version")
        license_expression = raw_entry.get("license")
        resolved_url = raw_entry.get("resolved")
        integrity = raw_entry.get("integrity")
        has_install_script = raw_entry.get("hasInstallScript") is True
        registry_source_verified = isinstance(resolved_url, str) and resolved_url.startswith(
            "https://registry.npmjs.org/"
        )
        integrity_verified = isinstance(integrity, str) and integrity.startswith("sha512-")
        license_present = isinstance(license_expression, str) and bool(license_expression.strip())
        if not isinstance(version, str) or not version:
            blockers.add(f"runtime_dependency_version_missing:{name}")
        if not registry_source_verified:
            blockers.add(f"runtime_dependency_registry_source_unverified:{name}")
        if not integrity_verified:
            blockers.add(f"runtime_dependency_integrity_missing:{name}")
        if not license_present:
            blockers.add(f"runtime_dependency_license_missing:{name}")
        if has_install_script:
            blockers.add(f"runtime_dependency_install_script_declared:{name}")
        evidence.append(
            GenOfficeRuntimeDependencyEvidence(
                name=name,
                requested_range=direct_dependencies.get(name),
                version=version if isinstance(version, str) else None,
                license_expression=license_expression if isinstance(license_expression, str) else None,
                resolved_url=resolved_url if isinstance(resolved_url, str) else None,
                integrity=integrity if isinstance(integrity, str) else None,
                dependencies=tuple(sorted(dependency_map)),
                direct=name in direct_dependencies,
                install_script_declared=has_install_script,
                registry_source_verified=registry_source_verified,
                integrity_metadata_verified=integrity_verified,
                license_metadata_present=license_present,
            )
        )

    return tuple(sorted(evidence, key=lambda item: item.name)), tuple(sorted(blockers))


def _vendored_components(
    source_files: tuple[GenOfficeSourceFileEvidence, ...],
) -> tuple[GenOfficeVendoredComponentEvidence, ...]:
    roots: dict[str, list[GenOfficeSourceFileEvidence]] = {}
    marker = f"{GENOFFICE_ENGINE_PACKAGE_PATH}/src/vendor/"
    for item in source_files:
        if not item.path.startswith(marker):
            continue
        relative = item.path.removeprefix(marker)
        component_name = relative.split("/", maxsplit=1)[0]
        root = f"{marker}{component_name}"
        roots.setdefault(root, []).append(item)

    components: list[GenOfficeVendoredComponentEvidence] = []
    for root, files in sorted(roots.items()):
        license_files = tuple(
            sorted(item.path for item in files if PurePosixPath(item.path).name.upper().startswith("LICENSE"))
        )
        hashes_by_path = {item.path: item.sha256 for item in files}
        components.append(
            GenOfficeVendoredComponentEvidence(
                root_path=root,
                file_count=len(files),
                license_files=license_files,
                license_file_hashes=tuple(hashes_by_path[path] for path in license_files),
            )
        )
    return tuple(components)


def build_genoffice_docx_source_admission_report(
    *,
    archive_path: Path,
    expected_archive_sha256: str = GENOFFICE_UPSTREAM_SOURCE_ARCHIVE_SHA256,
) -> GenOfficeDocxSourceAdmissionReport:
    archive_sha256, archive_size = _sha256_file(archive_path)
    if archive_sha256 != expected_archive_sha256:
        raise GenOfficeSourceAdmissionError("GenOffice source archive SHA-256 does not match the reviewed artifact")

    selected_raw: dict[str, bytes] = {}
    source_files: list[GenOfficeSourceFileEvidence] = []
    seen_paths: set[str] = set()
    prohibited_scopes_present: set[str] = set()
    member_count = 0
    selected_total_size = 0

    with _open_source_archive(archive_path) as archive:
        for member in archive:
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBER_COUNT:
                raise GenOfficeSourceAdmissionError("GenOffice source archive has too many members")
            relative_path = _relative_archive_path(member.name)
            if relative_path is None:
                if not member.isdir():
                    raise GenOfficeSourceAdmissionError("GenOffice archive root must be a directory")
                continue
            if relative_path in seen_paths:
                raise GenOfficeSourceAdmissionError("GenOffice source archive contains duplicate member paths")
            seen_paths.add(relative_path)
            if not (member.isdir() or member.isfile()):
                raise GenOfficeSourceAdmissionError("GenOffice source archive contains links or special files")
            for scope_prefix in GENOFFICE_PROHIBITED_SCOPE_PREFIXES:
                if relative_path == scope_prefix.rstrip("/") or relative_path.startswith(scope_prefix):
                    prohibited_scopes_present.add(scope_prefix + "**")

            role = _source_role(relative_path)
            if role is None or member.isdir():
                continue
            if member.size < 0 or member.size > MAX_SELECTED_MEMBER_SIZE_BYTES:
                raise GenOfficeSourceAdmissionError("GenOffice selected source member exceeds the size limit")
            selected_total_size += member.size
            if selected_total_size > MAX_SELECTED_TOTAL_SIZE_BYTES:
                raise GenOfficeSourceAdmissionError("GenOffice selected source scope exceeds the size limit")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise GenOfficeSourceAdmissionError("GenOffice selected source member cannot be read")
            raw = extracted.read(MAX_SELECTED_MEMBER_SIZE_BYTES + 1)
            if len(raw) != member.size:
                raise GenOfficeSourceAdmissionError("GenOffice selected source member size is inconsistent")
            selected_raw[relative_path] = raw
            source_files.append(
                GenOfficeSourceFileEvidence(
                    path=relative_path,
                    role=role,  # type: ignore[arg-type]
                    size_bytes=member.size,
                    sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
                    executable_mode_present=bool(member.mode & 0o111),
                )
            )

    missing_paths = sorted(set(GENOFFICE_REQUIRED_EVIDENCE_PATHS) - set(selected_raw))
    if missing_paths:
        raise GenOfficeSourceAdmissionError(f"GenOffice source archive is missing required evidence: {missing_paths}")
    sorted_source_files = tuple(sorted(source_files, key=lambda item: item.path))
    if not any(item.role == "candidate_runtime_source" for item in sorted_source_files):
        raise GenOfficeSourceAdmissionError("GenOffice source archive contains no DOCX runtime source")

    root_package = _json_object(selected_raw["package.json"], path="package.json")
    engine_package_path = f"{GENOFFICE_ENGINE_PACKAGE_PATH}/package.json"
    engine_package = _json_object(selected_raw[engine_package_path], path=engine_package_path)
    lock = _json_object(selected_raw["package-lock.json"], path="package-lock.json")
    lock_packages = lock.get("packages")
    if not isinstance(lock_packages, dict):
        raise GenOfficeSourceAdmissionError("package-lock.json packages must be an object")
    workspace_lock = lock_packages.get(GENOFFICE_ENGINE_PACKAGE_PATH)
    if not isinstance(workspace_lock, dict):
        raise GenOfficeSourceAdmissionError("DOCX engine workspace is missing from package-lock.json")

    engine_dependencies = _string_mapping(engine_package.get("dependencies"), field="docx-engine.dependencies")
    workspace_dependencies = _string_mapping(workspace_lock.get("dependencies"), field="lock docx-engine.dependencies")
    dependency_lock_verified = (
        lock.get("lockfileVersion") == 3
        and engine_dependencies == GENOFFICE_REQUIRED_DIRECT_DEPENDENCIES
        and workspace_dependencies == engine_dependencies
    )
    runtime_dependencies, dependency_blockers = _runtime_dependency_evidence(
        lock_packages=lock_packages,
        direct_dependencies=engine_dependencies,
    )
    vendored_components = _vendored_components(sorted_source_files)
    vendored_license_files_present = bool(vendored_components) and all(
        component.license_files for component in vendored_components
    )
    source_manifest_hash = stable_hash(canonical_json([item.model_dump(mode="json") for item in sorted_source_files]))
    runtime_dependency_manifest_hash = stable_hash(
        canonical_json([item.model_dump(mode="json") for item in runtime_dependencies])
    )
    dependency_integrity_complete = all(
        item.registry_source_verified and item.integrity_metadata_verified for item in runtime_dependencies
    )
    dependency_license_complete = all(item.license_metadata_present for item in runtime_dependencies)
    runtime_install_scripts_absent = all(not item.install_script_declared for item in runtime_dependencies)
    closure_blockers = tuple(
        reason
        for reason in dependency_blockers
        if reason.startswith(("runtime_dependency_missing_from_lock:", "runtime_dependency_version_missing:"))
    )
    closure_verified = not closure_blockers and bool(runtime_dependencies)
    prohibited_excluded = all(
        not any(item.path == prefix.rstrip("/") or item.path.startswith(prefix) for item in sorted_source_files)
        for prefix in GENOFFICE_PROHIBITED_SCOPE_PREFIXES
    )

    root_scripts = _lifecycle_scripts(root_package)
    engine_scripts = _lifecycle_scripts(engine_package)
    package_metadata_verified = (
        root_package.get("name") == "genoffice"
        and root_package.get("version") == "0.1.0"
        and root_package.get("license") == "Apache-2.0"
        and engine_package.get("name") == "@genoffice/docx-engine"
        and engine_package.get("version") == "0.1.0"
        and engine_package.get("license") == "Apache-2.0"
    )
    checks = {
        "package_metadata_not_verified": package_metadata_verified,
        "dependency_lock_not_verified": dependency_lock_verified,
        "runtime_dependency_closure_not_verified": closure_verified,
        "dependency_integrity_metadata_incomplete": dependency_integrity_complete,
        "dependency_license_metadata_incomplete": dependency_license_complete,
        "runtime_dependency_install_script_present": runtime_install_scripts_absent,
        "engine_lifecycle_script_present": not engine_scripts,
        "prohibited_scope_selected": prohibited_excluded,
        "vendored_component_license_missing": vendored_license_files_present,
    }
    snapshot_blockers = tuple(
        sorted((*dependency_blockers, *(reason for reason, passed in checks.items() if not passed)))
    )
    source_snapshot_verified = not snapshot_blockers
    draft = GenOfficeDocxSourceAdmissionReport(
        repository_url=GENOFFICE_UPSTREAM_REPOSITORY,
        upstream_commit=GENOFFICE_UPSTREAM_COMMIT,
        archive_root=GENOFFICE_ARCHIVE_ROOT,
        archive_size_bytes=archive_size,
        archive_sha256=archive_sha256,
        expected_archive_sha256=expected_archive_sha256,
        archive_member_count=member_count,
        selected_file_count=len(sorted_source_files),
        selected_total_size_bytes=selected_total_size,
        source_manifest_hash=source_manifest_hash,
        source_files=sorted_source_files,
        prohibited_scopes_present_upstream=tuple(sorted(prohibited_scopes_present)),
        prohibited_scopes_excluded_from_manifest=prohibited_excluded,
        root_package_name=str(root_package.get("name", "")),
        root_package_version=str(root_package.get("version", "")),
        root_license_spdx=str(root_package.get("license", "")),
        root_lifecycle_scripts=root_scripts,
        engine_package_name=str(engine_package.get("name", "")),
        engine_package_version=str(engine_package.get("version", "")),
        engine_license_spdx=str(engine_package.get("license", "")),
        engine_lifecycle_scripts=engine_scripts,
        lockfile_version=int(lock.get("lockfileVersion", 0)),
        direct_runtime_dependencies=tuple(sorted(engine_dependencies)),
        runtime_dependency_count=len(runtime_dependencies),
        runtime_dependency_manifest_hash=runtime_dependency_manifest_hash,
        runtime_dependencies=runtime_dependencies,
        vendored_components=vendored_components,
        exact_archive_verified=True,
        source_scope_manifest_verified=True,
        dependency_lock_verified=dependency_lock_verified,
        runtime_dependency_closure_verified=closure_verified,
        dependency_integrity_metadata_complete=dependency_integrity_complete,
        dependency_license_metadata_complete=dependency_license_complete,
        runtime_install_scripts_absent=runtime_install_scripts_absent,
        vendored_license_files_present=vendored_license_files_present,
        lifecycle_execution_prevented=True,
        source_snapshot_verified=source_snapshot_verified,
        snapshot_blocking_reasons=snapshot_blockers,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_docx_source_admission_report_hash(draft)})


def build_genoffice_docx_source_admission_report_hash(report: GenOfficeDocxSourceAdmissionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_docx_source_admission_report(
    *, report: GenOfficeDocxSourceAdmissionReport, report_path: Path
) -> None:
    if build_genoffice_docx_source_admission_report_hash(report) != report.report_hash:
        raise GenOfficeSourceAdmissionError("GenOffice source admission report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(report_path)


def load_genoffice_docx_source_admission_report(report_path: Path) -> GenOfficeDocxSourceAdmissionReport:
    report = GenOfficeDocxSourceAdmissionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    if build_genoffice_docx_source_admission_report_hash(report) != report.report_hash:
        raise GenOfficeSourceAdmissionError("Persisted GenOffice source admission report hash is invalid")
    return report


def run_genoffice_docx_source_admission_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDocxSourceAdmissionReport:
    archive_path_value = env.get("SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH", "").strip()
    if not archive_path_value:
        raise GenOfficeSourceAdmissionError("SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH is required")
    return build_genoffice_docx_source_admission_report(archive_path=Path(archive_path_value))


def main() -> None:
    try:
        report = run_genoffice_docx_source_admission_from_environment(os.environ)
        report_path_value = os.environ.get("SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH", "").strip()
        if report_path_value:
            persist_genoffice_docx_source_admission_report(report=report, report_path=Path(report_path_value))
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        raise SystemExit(0 if report.source_snapshot_verified else 2)
    except GenOfficeSourceAdmissionError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_DOCX_SOURCE_ADMISSION_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
