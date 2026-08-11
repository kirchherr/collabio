from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_docx_source_admission import (
    MAX_ARCHIVE_MEMBER_COUNT,
    MAX_ARCHIVE_SIZE_BYTES,
    MAX_SELECTED_MEMBER_SIZE_BYTES,
    GenOfficeDocxSourceAdmissionReport,
    GenOfficeSourceFileEvidence,
    build_genoffice_docx_source_admission_report_hash,
    load_genoffice_docx_source_admission_report,
)
from suite.operations.genoffice_docx_supply_chain_admission import (
    GenOfficeDocxSupplyChainAdmissionReport,
    build_genoffice_docx_supply_chain_report_hash,
    load_genoffice_docx_supply_chain_admission_report,
)
from suite.operations.genoffice_internal_oss_admission import (
    GenOfficeInternalOssAdmissionReport,
    build_genoffice_internal_oss_admission_report_hash,
    load_genoffice_internal_oss_admission_report,
)
from suite.operations.genoffice_legal_review_dossier import (
    GENOFFICE_REVIEWED_NPM_PROVENANCE_REPORT_HASH,
    GENOFFICE_REVIEWED_SOURCE_REPORT_HASH,
    GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH,
)
from suite.operations.genoffice_npm_provenance_admission import (
    GenOfficeNpmProvenanceAdmissionReport,
    build_genoffice_npm_provenance_report_hash,
    load_genoffice_npm_provenance_admission_report,
)
from suite.operations.genoffice_solo_founder_exception import (
    GenOfficeSoloFounderExceptionReport,
    build_genoffice_solo_founder_report_hash,
    load_genoffice_solo_founder_report,
)

GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_MANIFEST_SCHEMA_VERSION = "genoffice_development_build_context_manifest.v2"
GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_REPORT_SCHEMA_VERSION = "genoffice_development_build_context_report.v2"
GENOFFICE_BUILD_CONTEXT_MANIFEST_PATH = ".collabio/build-context-manifest.json"
GENOFFICE_NOTICE_CONTEXT_PATH = "THIRD_PARTY_NOTICES.txt"
GENOFFICE_QUARANTINED_ROOT_METADATA = {
    "package-lock.json": ".collabio/upstream/package-lock.json",
    "package.json": ".collabio/upstream/package.json",
}
MAX_BUILD_CONTEXT_SIZE_BYTES = 80 * 1024 * 1024
_ZERO_HASH = "sha256:" + "0" * 64


class GenOfficeDevelopmentBuildContextError(ValueError):
    pass


class GenOfficeDevelopmentBuildContextFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    context_path: str
    role: Literal[
        "upstream_evidence",
        "candidate_build_metadata",
        "candidate_runtime_source",
        "vendored_runtime_source",
        "evaluation_only",
        "third_party_notice",
    ]
    size_bytes: int
    sha256: str


class GenOfficeDevelopmentBuildContextManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_development_build_context_manifest.v2"] = (
        "genoffice_development_build_context_manifest.v2"
    )
    source_report_hash: str
    source_archive_sha256: str
    source_manifest_hash: str
    supply_chain_admission_report_hash: str
    npm_provenance_admission_report_hash: str
    authorization_mode: Literal["two_person_internal_oss_admission", "solo_founder_development_exception"]
    development_authorization_report_hash: str
    internal_oss_admission_report_hash: str | None
    solo_founder_exception_report_hash: str | None
    third_party_notice_artifact_sha256: str
    source_date_epoch: int
    payload_file_count: int
    payload_total_size_bytes: int
    files: tuple[GenOfficeDevelopmentBuildContextFile, ...]


class GenOfficeDevelopmentBuildContextReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_development_build_context_report.v2"] = (
        "genoffice_development_build_context_report.v2"
    )
    source_report_hash: str
    source_archive_sha256: str
    source_manifest_hash: str
    supply_chain_admission_report_hash: str
    npm_provenance_admission_report_hash: str
    authorization_mode: Literal["two_person_internal_oss_admission", "solo_founder_development_exception"]
    development_authorization_report_hash: str
    internal_oss_admission_report_hash: str | None
    solo_founder_exception_report_hash: str | None
    signer_policy_hash: str
    authorization_record_hash: str
    decision_record_hash: str | None
    third_party_notice_artifact_sha256: str
    source_date_epoch: int
    selected_source_file_count: int
    payload_file_count: int
    context_file_count: int
    context_tar_size_bytes: int
    context_manifest_sha256: str
    context_tar_sha256: str
    exact_source_files_verified: bool
    normalized_tar_metadata_verified: bool
    network_used: bool = False
    upstream_code_executed: bool = False
    dependency_install_performed: bool = False
    worker_image_built: bool = False
    build_context_materialized: bool
    isolated_worker_image_build_authorized: bool
    engine_execution_allowed: bool = False
    source_import_allowed: bool = False
    tenant_content_allowed: bool = False
    production_use_allowed: bool = False
    report_hash: str

    @model_validator(mode="after")
    def require_pinned_non_runtime_boundary(self) -> GenOfficeDevelopmentBuildContextReport:
        if self.source_report_hash != GENOFFICE_REVIEWED_SOURCE_REPORT_HASH:
            raise ValueError("GenOffice development build context source report is not pinned")
        if not all(
            (
                self.exact_source_files_verified,
                self.normalized_tar_metadata_verified,
                self.build_context_materialized,
                self.isolated_worker_image_build_authorized,
            )
        ):
            raise ValueError("GenOffice development build context evidence is incomplete")
        if any(
            (
                self.network_used,
                self.upstream_code_executed,
                self.dependency_install_performed,
                self.worker_image_built,
                self.engine_execution_allowed,
                self.source_import_allowed,
                self.tenant_content_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice development build context opened a runtime boundary")
        if self.authorization_mode == "two_person_internal_oss_admission":
            if (
                self.internal_oss_admission_report_hash != self.development_authorization_report_hash
                or self.solo_founder_exception_report_hash is not None
                or self.decision_record_hash != self.authorization_record_hash
            ):
                raise ValueError("GenOffice two-person build authorization binding is invalid")
        elif (
            self.solo_founder_exception_report_hash != self.development_authorization_report_hash
            or self.internal_oss_admission_report_hash is not None
            or self.decision_record_hash is not None
        ):
            raise ValueError("GenOffice solo-founder build authorization binding is invalid")
        return self


class _DevelopmentAuthorizationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["two_person_internal_oss_admission", "solo_founder_development_exception"]
    report_hash: str
    signer_policy_hash: str
    authorization_record_hash: str
    internal_oss_admission_report_hash: str | None
    solo_founder_exception_report_hash: str | None
    decision_record_hash: str | None
    third_party_notice_artifact_sha256: str


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_SIZE_BYTES:
                    raise GenOfficeDevelopmentBuildContextError(
                        "GenOffice development source archive exceeds its size limit"
                    )
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development source archive cannot be read") from exc
    return f"sha256:{digest.hexdigest()}", size


def _read_limited(path: Path, *, label: str, max_size: int = MAX_BUILD_CONTEXT_SIZE_BYTES) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeDevelopmentBuildContextError(f"GenOffice {label} cannot be read") from exc
    if len(content) > max_size:
        raise GenOfficeDevelopmentBuildContextError(f"GenOffice {label} exceeds its size limit")
    return content


def _archive_relative_path(name: str, *, archive_root: str) -> str | None:
    if not name or "\\" in name or name.startswith("/"):
        raise GenOfficeDevelopmentBuildContextError("GenOffice development archive contains an unsafe path")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise GenOfficeDevelopmentBuildContextError("GenOffice development archive contains a non-canonical path")
    if not path.parts or path.parts[0] != archive_root:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development archive root is not pinned")
    if len(path.parts) == 1:
        return None
    return PurePosixPath(*path.parts[1:]).as_posix()


def _verify_input_evidence(
    *,
    source_report: GenOfficeDocxSourceAdmissionReport,
    supply_chain_report: GenOfficeDocxSupplyChainAdmissionReport,
    npm_provenance_report: GenOfficeNpmProvenanceAdmissionReport,
    internal_oss_admission_report: GenOfficeInternalOssAdmissionReport | None,
    solo_founder_exception_report: GenOfficeSoloFounderExceptionReport | None,
    notice_artifact: bytes,
    authorization_verified_at_utc: datetime,
) -> _DevelopmentAuthorizationEvidence:
    if build_genoffice_docx_source_admission_report_hash(source_report) != source_report.report_hash:
        raise GenOfficeDevelopmentBuildContextError("GenOffice source admission report hash is invalid")
    if source_report.report_hash != GENOFFICE_REVIEWED_SOURCE_REPORT_HASH:
        raise GenOfficeDevelopmentBuildContextError("GenOffice source admission report is not reviewed")
    if not all(
        (
            source_report.exact_archive_verified,
            source_report.source_scope_manifest_verified,
            source_report.source_snapshot_verified,
            source_report.prohibited_scopes_excluded_from_manifest,
            source_report.lifecycle_execution_prevented,
        )
    ):
        raise GenOfficeDevelopmentBuildContextError("GenOffice source admission is not complete")
    if source_report.archive_sha256 != source_report.expected_archive_sha256:
        raise GenOfficeDevelopmentBuildContextError("GenOffice source archive is not the reviewed archive")
    source_files = tuple(sorted(source_report.source_files, key=lambda item: item.path))
    source_manifest_hash = stable_hash(canonical_json([item.model_dump(mode="json") for item in source_files]))
    if (
        source_manifest_hash != source_report.source_manifest_hash
        or len(source_files) != source_report.selected_file_count
        or sum(item.size_bytes for item in source_files) != source_report.selected_total_size_bytes
    ):
        raise GenOfficeDevelopmentBuildContextError("GenOffice selected source manifest is invalid")
    if any(item.executable_mode_present for item in source_report.source_files):
        raise GenOfficeDevelopmentBuildContextError("GenOffice selected source contains executable file modes")
    if build_genoffice_docx_supply_chain_report_hash(supply_chain_report) != supply_chain_report.report_hash:
        raise GenOfficeDevelopmentBuildContextError("GenOffice supply-chain admission report hash is invalid")
    if supply_chain_report.report_hash != GENOFFICE_REVIEWED_SUPPLY_CHAIN_REPORT_HASH:
        raise GenOfficeDevelopmentBuildContextError("GenOffice supply-chain admission report is not reviewed")
    if (
        supply_chain_report.source_report_hash != source_report.report_hash
        or supply_chain_report.source_archive_sha256 != source_report.archive_sha256
        or not supply_chain_report.automated_sbom_and_vulnerability_gate_passed
        or not supply_chain_report.high_and_critical_findings_absent
    ):
        raise GenOfficeDevelopmentBuildContextError("GenOffice supply-chain admission does not match the source")
    if build_genoffice_npm_provenance_report_hash(npm_provenance_report) != npm_provenance_report.report_hash:
        raise GenOfficeDevelopmentBuildContextError("GenOffice npm provenance admission report hash is invalid")
    if (
        npm_provenance_report.report_hash != GENOFFICE_REVIEWED_NPM_PROVENANCE_REPORT_HASH
        or not npm_provenance_report.cryptographic_provenance_gate_passed
    ):
        raise GenOfficeDevelopmentBuildContextError("GenOffice npm provenance admission is not reviewed")
    if authorization_verified_at_utc.tzinfo is None or authorization_verified_at_utc.utcoffset() is None:
        raise GenOfficeDevelopmentBuildContextError("GenOffice authorization verification time lacks a timezone")
    if (internal_oss_admission_report is None) == (solo_founder_exception_report is None):
        raise GenOfficeDevelopmentBuildContextError("GenOffice development requires exactly one authorization mode")
    if internal_oss_admission_report is not None:
        if (
            build_genoffice_internal_oss_admission_report_hash(internal_oss_admission_report)
            != internal_oss_admission_report.report_hash
        ):
            raise GenOfficeDevelopmentBuildContextError("GenOffice internal OSS admission report hash is invalid")
        if not all(
            (
                internal_oss_admission_report.internal_oss_decision_verified,
                internal_oss_admission_report.two_person_control_verified,
                internal_oss_admission_report.detached_signatures_verified,
                internal_oss_admission_report.development_build_context_materialization_allowed,
                internal_oss_admission_report.reproducible_worker_build_allowed,
            )
        ):
            raise GenOfficeDevelopmentBuildContextError(
                "GenOffice internal OSS admission does not authorize materialization"
            )
        authorization = _DevelopmentAuthorizationEvidence(
            mode="two_person_internal_oss_admission",
            report_hash=internal_oss_admission_report.report_hash,
            signer_policy_hash=internal_oss_admission_report.signer_policy_hash,
            authorization_record_hash=internal_oss_admission_report.decision_record_hash,
            internal_oss_admission_report_hash=internal_oss_admission_report.report_hash,
            solo_founder_exception_report_hash=None,
            decision_record_hash=internal_oss_admission_report.decision_record_hash,
            third_party_notice_artifact_sha256=internal_oss_admission_report.third_party_notice_artifact_sha256,
        )
    else:
        assert solo_founder_exception_report is not None
        if (
            build_genoffice_solo_founder_report_hash(solo_founder_exception_report)
            != solo_founder_exception_report.report_hash
        ):
            raise GenOfficeDevelopmentBuildContextError("GenOffice solo-founder exception report hash is invalid")
        now = authorization_verified_at_utc.astimezone(UTC)
        if not solo_founder_exception_report.issued_at_utc <= now <= solo_founder_exception_report.valid_until_utc:
            raise GenOfficeDevelopmentBuildContextError("GenOffice solo-founder exception is expired or not active")
        if not all(
            (
                solo_founder_exception_report.solo_founder_risk_acceptance_verified,
                solo_founder_exception_report.detached_signature_verified,
                solo_founder_exception_report.compensating_controls_verified,
                solo_founder_exception_report.write_once_evidence_required,
                solo_founder_exception_report.development_build_context_materialization_allowed,
                solo_founder_exception_report.reproducible_worker_build_allowed,
            )
        ) or solo_founder_exception_report.two_person_control_verified:
            raise GenOfficeDevelopmentBuildContextError(
                "GenOffice solo-founder exception does not authorize materialization"
            )
        authorization = _DevelopmentAuthorizationEvidence(
            mode="solo_founder_development_exception",
            report_hash=solo_founder_exception_report.report_hash,
            signer_policy_hash=solo_founder_exception_report.signer_policy_hash,
            authorization_record_hash=solo_founder_exception_report.signing_request_hash,
            internal_oss_admission_report_hash=None,
            solo_founder_exception_report_hash=solo_founder_exception_report.report_hash,
            decision_record_hash=None,
            third_party_notice_artifact_sha256=solo_founder_exception_report.third_party_notice_artifact_sha256,
        )
    if _sha256_bytes(notice_artifact) != authorization.third_party_notice_artifact_sha256:
        raise GenOfficeDevelopmentBuildContextError(
            "GenOffice third-party notice does not match development authorization"
        )
    return authorization


def _read_selected_source_files(
    *, archive_path: Path, source_report: GenOfficeDocxSourceAdmissionReport
) -> dict[str, bytes]:
    archive_hash, archive_size = _sha256_file(archive_path)
    if archive_hash != source_report.archive_sha256 or archive_size != source_report.archive_size_bytes:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development source archive bytes drifted")
    expected = {item.path: item for item in source_report.source_files}
    if len(expected) != source_report.selected_file_count or len(expected) != len(source_report.source_files):
        raise GenOfficeDevelopmentBuildContextError("GenOffice selected source manifest contains duplicate paths")
    materialized: dict[str, bytes] = {}
    observed: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBER_COUNT:
                raise GenOfficeDevelopmentBuildContextError("GenOffice development archive has too many members")
            for member in members:
                relative = _archive_relative_path(member.name, archive_root=source_report.archive_root)
                if relative is None:
                    if not member.isdir():
                        raise GenOfficeDevelopmentBuildContextError(
                            "GenOffice development archive root is not a directory"
                        )
                    continue
                if relative in observed:
                    raise GenOfficeDevelopmentBuildContextError(
                        "GenOffice development archive contains duplicate paths"
                    )
                observed.add(relative)
                if not member.isfile() and not member.isdir():
                    raise GenOfficeDevelopmentBuildContextError(
                        "GenOffice development archive contains links or special files"
                    )
                evidence = expected.get(relative)
                if evidence is None:
                    continue
                if (
                    not member.isfile()
                    or member.size != evidence.size_bytes
                    or member.size > MAX_SELECTED_MEMBER_SIZE_BYTES
                ):
                    raise GenOfficeDevelopmentBuildContextError("GenOffice selected source file metadata drifted")
                source = archive.extractfile(member)
                if source is None:
                    raise GenOfficeDevelopmentBuildContextError("GenOffice selected source file cannot be read")
                content = source.read(MAX_SELECTED_MEMBER_SIZE_BYTES + 1)
                if len(content) != evidence.size_bytes or _sha256_bytes(content) != evidence.sha256:
                    raise GenOfficeDevelopmentBuildContextError("GenOffice selected source file bytes drifted")
                materialized[relative] = content
    except (OSError, tarfile.TarError) as exc:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development source archive cannot be opened") from exc
    if set(materialized) != set(expected):
        raise GenOfficeDevelopmentBuildContextError("GenOffice selected source files are incomplete")
    return materialized


def _context_file(evidence: GenOfficeSourceFileEvidence) -> GenOfficeDevelopmentBuildContextFile:
    return GenOfficeDevelopmentBuildContextFile(
        source_path=evidence.path,
        context_path=GENOFFICE_QUARANTINED_ROOT_METADATA.get(evidence.path, evidence.path),
        role=evidence.role,
        size_bytes=evidence.size_bytes,
        sha256=evidence.sha256,
    )


def _build_normalized_tar(*, files: Mapping[str, bytes], source_date_epoch: int) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path, content in sorted(files.items()):
            safe_path = _archive_relative_path(f"context/{path}", archive_root="context")
            if safe_path != path:
                raise GenOfficeDevelopmentBuildContextError("GenOffice build context path is not canonical")
            member = tarfile.TarInfo(path)
            member.size = len(content)
            member.mode = 0o644
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mtime = source_date_epoch
            archive.addfile(member, io.BytesIO(content))
    context = output.getvalue()
    if len(context) > MAX_BUILD_CONTEXT_SIZE_BYTES:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development build context exceeds its size limit")
    return context


def build_genoffice_development_build_context(
    *,
    archive_path: Path,
    source_report: GenOfficeDocxSourceAdmissionReport,
    supply_chain_report: GenOfficeDocxSupplyChainAdmissionReport,
    npm_provenance_report: GenOfficeNpmProvenanceAdmissionReport,
    internal_oss_admission_report: GenOfficeInternalOssAdmissionReport | None = None,
    solo_founder_exception_report: GenOfficeSoloFounderExceptionReport | None = None,
    notice_artifact: bytes,
    source_date_epoch: int,
    authorization_verified_at_utc: datetime | None = None,
) -> tuple[bytes, GenOfficeDevelopmentBuildContextReport]:
    if source_date_epoch < 0:
        raise GenOfficeDevelopmentBuildContextError("GenOffice SOURCE_DATE_EPOCH must not be negative")
    authorization = _verify_input_evidence(
        source_report=source_report,
        supply_chain_report=supply_chain_report,
        npm_provenance_report=npm_provenance_report,
        internal_oss_admission_report=internal_oss_admission_report,
        solo_founder_exception_report=solo_founder_exception_report,
        notice_artifact=notice_artifact,
        authorization_verified_at_utc=authorization_verified_at_utc or datetime.now(UTC),
    )
    selected = _read_selected_source_files(archive_path=archive_path, source_report=source_report)
    source_evidence = tuple(
        _context_file(item) for item in sorted(source_report.source_files, key=lambda item: item.path)
    )
    notice_evidence = GenOfficeDevelopmentBuildContextFile(
        source_path=GENOFFICE_NOTICE_CONTEXT_PATH,
        context_path=GENOFFICE_NOTICE_CONTEXT_PATH,
        role="third_party_notice",
        size_bytes=len(notice_artifact),
        sha256=_sha256_bytes(notice_artifact),
    )
    payload_evidence = (*source_evidence, notice_evidence)
    manifest = GenOfficeDevelopmentBuildContextManifest(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_report.archive_sha256,
        source_manifest_hash=source_report.source_manifest_hash,
        supply_chain_admission_report_hash=supply_chain_report.report_hash,
        npm_provenance_admission_report_hash=npm_provenance_report.report_hash,
        authorization_mode=authorization.mode,
        development_authorization_report_hash=authorization.report_hash,
        internal_oss_admission_report_hash=authorization.internal_oss_admission_report_hash,
        solo_founder_exception_report_hash=authorization.solo_founder_exception_report_hash,
        third_party_notice_artifact_sha256=notice_evidence.sha256,
        source_date_epoch=source_date_epoch,
        payload_file_count=len(payload_evidence),
        payload_total_size_bytes=sum(item.size_bytes for item in payload_evidence),
        files=payload_evidence,
    )
    manifest_bytes = (canonical_json(manifest.model_dump(mode="json")) + "\n").encode("utf-8")
    context_files = {item.context_path: selected[item.source_path] for item in source_evidence}
    context_files[GENOFFICE_NOTICE_CONTEXT_PATH] = notice_artifact
    context_files[GENOFFICE_BUILD_CONTEXT_MANIFEST_PATH] = manifest_bytes
    context = _build_normalized_tar(files=context_files, source_date_epoch=source_date_epoch)
    draft = GenOfficeDevelopmentBuildContextReport(
        source_report_hash=source_report.report_hash,
        source_archive_sha256=source_report.archive_sha256,
        source_manifest_hash=source_report.source_manifest_hash,
        supply_chain_admission_report_hash=supply_chain_report.report_hash,
        npm_provenance_admission_report_hash=npm_provenance_report.report_hash,
        authorization_mode=authorization.mode,
        development_authorization_report_hash=authorization.report_hash,
        internal_oss_admission_report_hash=authorization.internal_oss_admission_report_hash,
        solo_founder_exception_report_hash=authorization.solo_founder_exception_report_hash,
        signer_policy_hash=authorization.signer_policy_hash,
        authorization_record_hash=authorization.authorization_record_hash,
        decision_record_hash=authorization.decision_record_hash,
        third_party_notice_artifact_sha256=notice_evidence.sha256,
        source_date_epoch=source_date_epoch,
        selected_source_file_count=len(source_evidence),
        payload_file_count=len(payload_evidence),
        context_file_count=len(context_files),
        context_tar_size_bytes=len(context),
        context_manifest_sha256=_sha256_bytes(manifest_bytes),
        context_tar_sha256=_sha256_bytes(context),
        exact_source_files_verified=True,
        normalized_tar_metadata_verified=True,
        build_context_materialized=True,
        isolated_worker_image_build_authorized=True,
        report_hash=_ZERO_HASH,
    )
    report = draft.model_copy(update={"report_hash": build_genoffice_development_build_context_report_hash(draft)})
    return context, report


def build_genoffice_development_build_context_report_hash(
    report: GenOfficeDevelopmentBuildContextReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_development_build_context(
    *,
    context: bytes,
    report: GenOfficeDevelopmentBuildContextReport,
    context_path: Path,
    report_path: Path,
) -> None:
    if _sha256_bytes(context) != report.context_tar_sha256 or len(context) != report.context_tar_size_bytes:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development build context hash is invalid")
    if build_genoffice_development_build_context_report_hash(report) != report.report_hash:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development build context report hash is invalid")
    context_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    context_temporary = context_path.with_suffix(context_path.suffix + ".tmp")
    report_temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    context_temporary.write_bytes(context)
    report_temporary.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    context_temporary.replace(context_path)
    report_temporary.replace(report_path)


def run_genoffice_development_build_context_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDevelopmentBuildContextReport:
    keys = {
        "archive": "SUITE_GENOFFICE_SOURCE_ARCHIVE_PATH",
        "source_report": "SUITE_GENOFFICE_SOURCE_ADMISSION_REPORT_PATH",
        "supply_chain_report": "SUITE_GENOFFICE_SUPPLY_CHAIN_ADMISSION_REPORT_PATH",
        "npm_provenance_report": "SUITE_GENOFFICE_NPM_PROVENANCE_ADMISSION_REPORT_PATH",
        "notice": "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH",
        "context": "SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_PATH",
        "report": "SUITE_GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_REPORT_PATH",
        "source_date_epoch": "SOURCE_DATE_EPOCH",
    }
    values = {name: env.get(key, "").strip() for name, key in keys.items()}
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeDevelopmentBuildContextError(
            f"GenOffice development build context values are missing: {missing}"
        )
    try:
        source_date_epoch = int(values["source_date_epoch"])
    except ValueError as exc:
        raise GenOfficeDevelopmentBuildContextError("GenOffice SOURCE_DATE_EPOCH is invalid") from exc
    authorization_mode = env.get("SUITE_GENOFFICE_DEVELOPMENT_AUTHORIZATION_MODE", "").strip()
    if authorization_mode == "two_person_internal_oss_admission":
        authorization_path = env.get("SUITE_GENOFFICE_INTERNAL_OSS_ADMISSION_REPORT_PATH", "").strip()
        if not authorization_path:
            raise GenOfficeDevelopmentBuildContextError("GenOffice two-person authorization path is missing")
        internal_oss_admission_report = load_genoffice_internal_oss_admission_report(Path(authorization_path))
        solo_founder_exception_report = None
    elif authorization_mode == "solo_founder_development_exception":
        authorization_path = env.get("SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH", "").strip()
        if not authorization_path:
            raise GenOfficeDevelopmentBuildContextError("GenOffice solo-founder authorization path is missing")
        internal_oss_admission_report = None
        solo_founder_exception_report = load_genoffice_solo_founder_report(Path(authorization_path))
    else:
        raise GenOfficeDevelopmentBuildContextError("GenOffice development authorization mode is invalid")
    context, report = build_genoffice_development_build_context(
        archive_path=Path(values["archive"]),
        source_report=load_genoffice_docx_source_admission_report(Path(values["source_report"])),
        supply_chain_report=load_genoffice_docx_supply_chain_admission_report(Path(values["supply_chain_report"])),
        npm_provenance_report=load_genoffice_npm_provenance_admission_report(Path(values["npm_provenance_report"])),
        internal_oss_admission_report=internal_oss_admission_report,
        solo_founder_exception_report=solo_founder_exception_report,
        notice_artifact=_read_limited(Path(values["notice"]), label="third-party notice"),
        source_date_epoch=source_date_epoch,
    )
    persist_genoffice_development_build_context(
        context=context,
        report=report,
        context_path=Path(values["context"]),
        report_path=Path(values["report"]),
    )
    return report


def main() -> None:
    try:
        report = run_genoffice_development_build_context_from_environment(os.environ)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    except (GenOfficeDevelopmentBuildContextError, ValueError) as exc:
        print(
            json.dumps({"error": str(exc), "schema_version": GENOFFICE_DEVELOPMENT_BUILD_CONTEXT_REPORT_SCHEMA_VERSION})
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
