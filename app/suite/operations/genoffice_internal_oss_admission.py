from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_docx_source_admission import GENOFFICE_PROHIBITED_SCOPE_PREFIXES
from suite.operations.genoffice_legal_review_dossier import (
    GENOFFICE_REQUIRED_TRADEMARK_POLICY,
    GenOfficeDependencyLicenseEvidence,
    GenOfficeLegalReviewDossierReport,
    load_genoffice_legal_review_dossier,
)
from suite.operations.genoffice_third_party_notice import (
    GENOFFICE_DEVELOPMENT_PROFILE,
    GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH,
    GENOFFICE_SELECTED_SOURCE_SCOPE,
    GenOfficeThirdPartyNoticeReport,
    load_genoffice_third_party_notice_report,
)

GENOFFICE_INTERNAL_OSS_DECISION_SCHEMA_VERSION = "genoffice_internal_oss_decision_envelope.v1"
GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_SCHEMA_VERSION = "genoffice_internal_oss_signer_policy.v1"
GENOFFICE_INTERNAL_OSS_ADMISSION_REPORT_SCHEMA_VERSION = "genoffice_internal_oss_admission_report.v1"
GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES = ("product_owner", "security_compliance_owner")
GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES = ("hosted_service", "on_prem_distribution", "production")
GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES = tuple(f"{prefix}**" for prefix in GENOFFICE_PROHIBITED_SCOPE_PREFIXES)
MAX_INTERNAL_OSS_INPUT_SIZE_BYTES = 4 * 1024 * 1024


class GenOfficeInternalOssAdmissionError(ValueError):
    pass


class GenOfficeInternalOssDependencyResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_name: str
    package_version: str
    declared_license_expression: str
    selected_distribution_license_expression: str
    legal_file_evidence_ids: tuple[str, ...]


class GenOfficeInternalOssDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_decision_payload.v1"] = "genoffice_internal_oss_decision_payload.v1"
    decision_id: str
    decision: Literal["approved_for_development_evaluation", "rejected"]
    decided_at_utc: datetime
    risk_acceptance_ref: str
    change_control_ref: str
    legal_dossier_report_hash: str
    third_party_notice_report_hash: str
    third_party_notice_artifact_sha256: str
    approved_usage_profiles: tuple[str, ...]
    blocked_usage_profiles: tuple[str, ...]
    approved_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    trademark_policy: str
    apache_2_0_terms_accepted: bool
    apache_notice_preservation_required: bool
    apache_patent_terms_acknowledged: bool
    enterprise_scope_excluded: bool
    jszip_selected_license_expression: str
    pako_selected_license_expression: str
    dependency_license_resolutions: tuple[GenOfficeInternalOssDependencyResolution, ...]
    reevaluation_triggers: tuple[str, ...]
    payload_hash: str

    @field_validator("decided_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice internal OSS decision time must include a timezone")
        return value

    @model_validator(mode="after")
    def require_identity_and_hash(self) -> GenOfficeInternalOssDecisionPayload:
        if not all(value.strip() for value in (self.decision_id, self.risk_acceptance_ref, self.change_control_ref)):
            raise ValueError("GenOffice internal OSS decision identity or control reference is empty")
        _require_sha256(self.payload_hash, field="internal OSS decision payload hash")
        return self


class GenOfficeInternalOssDetachedApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: Literal["product_owner", "security_compliance_owner"]
    key_id: str
    signature_base64: str

    @model_validator(mode="after")
    def require_approval_identity(self) -> GenOfficeInternalOssDetachedApproval:
        if not all(value.strip() for value in (self.signer_id, self.key_id, self.signature_base64)):
            raise ValueError("GenOffice internal OSS approval identity or signature is empty")
        return self


class GenOfficeInternalOssDecisionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_decision_envelope.v1"] = (
        "genoffice_internal_oss_decision_envelope.v1"
    )
    payload: GenOfficeInternalOssDecisionPayload
    approvals: tuple[GenOfficeInternalOssDetachedApproval, ...]
    record_hash: str

    @model_validator(mode="after")
    def require_record_hash(self) -> GenOfficeInternalOssDecisionEnvelope:
        _require_sha256(self.record_hash, field="internal OSS decision record hash")
        return self


class GenOfficeInternalOssSigner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: Literal["product_owner", "security_compliance_owner"]
    key_id: str
    ed25519_public_key_base64: str
    active: bool


class GenOfficeInternalOssSignerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_signer_policy.v1"] = "genoffice_internal_oss_signer_policy.v1"
    policy_id: str
    effective_at_utc: datetime
    signers: tuple[GenOfficeInternalOssSigner, ...]
    policy_hash: str

    @field_validator("effective_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice internal OSS signer policy time must include a timezone")
        return value

    @model_validator(mode="after")
    def require_distinct_active_roles(self) -> GenOfficeInternalOssSignerPolicy:
        if not self.policy_id.strip():
            raise ValueError("GenOffice internal OSS signer policy identity is empty")
        _require_sha256(self.policy_hash, field="internal OSS signer policy hash")
        active = tuple(item for item in self.signers if item.active)
        identities = {(item.signer_id, item.key_id) for item in active}
        if len(identities) != len(active):
            raise ValueError("GenOffice internal OSS signer policy contains duplicate active identities")
        if set(item.signer_role for item in active) != set(GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES):
            raise ValueError("GenOffice internal OSS signer policy lacks both required roles")
        return self


class GenOfficeInternalOssAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_admission_report.v1"] = "genoffice_internal_oss_admission_report.v1"
    legal_dossier_report_hash: str
    third_party_notice_report_hash: str
    third_party_notice_artifact_sha256: str
    decision_payload_hash: str
    decision_record_hash: str
    signer_policy_hash: str
    approved_usage_profiles: tuple[str, ...]
    blocked_usage_profiles: tuple[str, ...]
    approved_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    internal_oss_decision_verified: bool
    two_person_control_verified: bool
    detached_signatures_verified: bool
    notice_distribution_artifact_verified: bool
    dependency_license_resolutions_verified: bool
    change_reevaluation_required: bool
    development_build_context_materialization_allowed: bool
    reproducible_worker_build_allowed: bool
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    hosted_service_allowed: bool = False
    on_prem_distribution_allowed: bool = False
    production_use_allowed: bool = False
    tenant_content_allowed: bool = False
    report_hash: str

    @model_validator(mode="after")
    def require_development_only_boundary(self) -> GenOfficeInternalOssAdmissionReport:
        if self.legal_dossier_report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH:
            raise ValueError("GenOffice internal OSS admission dossier is not pinned")
        if self.approved_usage_profiles != (GENOFFICE_DEVELOPMENT_PROFILE,):
            raise ValueError("GenOffice internal OSS admission profile is not development-only")
        if self.blocked_usage_profiles != GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES:
            raise ValueError("GenOffice internal OSS admission blocked profiles are incomplete")
        if not all(
            (
                self.internal_oss_decision_verified,
                self.two_person_control_verified,
                self.detached_signatures_verified,
                self.notice_distribution_artifact_verified,
                self.dependency_license_resolutions_verified,
                self.change_reevaluation_required,
                self.development_build_context_materialization_allowed,
                self.reproducible_worker_build_allowed,
            )
        ):
            raise ValueError("GenOffice internal OSS admission evidence is incomplete")
        if any(
            (
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.hosted_service_allowed,
                self.on_prem_distribution_allowed,
                self.production_use_allowed,
                self.tenant_content_allowed,
            )
        ):
            raise ValueError("GenOffice internal OSS admission opened a production or tenant boundary")
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{field} is not a SHA-256 evidence hash")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field} is not a SHA-256 evidence hash") from exc


def build_genoffice_internal_oss_payload_hash(payload: GenOfficeInternalOssDecisionPayload) -> str:
    return stable_hash(canonical_json(payload.model_dump(mode="json", exclude={"payload_hash"})))


def build_genoffice_internal_oss_record_hash(envelope: GenOfficeInternalOssDecisionEnvelope) -> str:
    return stable_hash(canonical_json(envelope.model_dump(mode="json", exclude={"record_hash"})))


def build_genoffice_internal_oss_signer_policy_hash(policy: GenOfficeInternalOssSignerPolicy) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json", exclude={"policy_hash"})))


def build_genoffice_internal_oss_admission_report_hash(report: GenOfficeInternalOssAdmissionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def _selected_expression(dependency: GenOfficeDependencyLicenseEvidence) -> str:
    if dependency.package_name == "jszip" and dependency.declared_license_expression == "(MIT OR GPL-3.0-or-later)":
        return "MIT"
    if dependency.package_name == "pako" and dependency.declared_license_expression == "(MIT AND Zlib)":
        return "MIT AND Zlib"
    if dependency.expression_semantics == "single" and dependency.declared_license_expression in {"MIT", "ISC"}:
        return dependency.declared_license_expression
    raise GenOfficeInternalOssAdmissionError("GenOffice dependency license expression is not internally resolvable")


def build_genoffice_internal_oss_dependency_resolutions(
    dossier: GenOfficeLegalReviewDossierReport,
) -> tuple[GenOfficeInternalOssDependencyResolution, ...]:
    return tuple(
        GenOfficeInternalOssDependencyResolution(
            package_name=item.package_name,
            package_version=item.package_version,
            declared_license_expression=item.declared_license_expression,
            selected_distribution_license_expression=_selected_expression(item),
            legal_file_evidence_ids=item.legal_file_evidence_ids,
        )
        for item in dossier.dependency_licenses
    )


def _read_limited(path: Path) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS evidence input cannot be read") from exc
    if len(content) > MAX_INTERNAL_OSS_INPUT_SIZE_BYTES:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS evidence input exceeds its size limit")
    return content


def _decode_base64(value: str, *, field: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise GenOfficeInternalOssAdmissionError(f"GenOffice {field} is not canonical base64") from exc
    if len(decoded) != expected_size:
        raise GenOfficeInternalOssAdmissionError(f"GenOffice {field} has an invalid size")
    return decoded


def _verify_decision_scope(
    *,
    payload: GenOfficeInternalOssDecisionPayload,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
) -> None:
    if build_genoffice_internal_oss_payload_hash(payload) != payload.payload_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision payload hash is invalid")
    if payload.decision != "approved_for_development_evaluation":
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision does not approve development")
    expected = (
        (payload.legal_dossier_report_hash, dossier.report_hash),
        (payload.third_party_notice_report_hash, notice_report.report_hash),
        (payload.third_party_notice_artifact_sha256, notice_report.notice_artifact_sha256),
        (payload.approved_usage_profiles, (GENOFFICE_DEVELOPMENT_PROFILE,)),
        (payload.blocked_usage_profiles, GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES),
        (payload.approved_source_scopes, (GENOFFICE_SELECTED_SOURCE_SCOPE,)),
        (payload.prohibited_source_scopes, GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES),
        (payload.trademark_policy, GENOFFICE_REQUIRED_TRADEMARK_POLICY),
        (payload.jszip_selected_license_expression, "MIT"),
        (payload.pako_selected_license_expression, "MIT AND Zlib"),
    )
    if any(actual != required for actual, required in expected):
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision scope or policy is not exact")
    if not all(
        (
            payload.apache_2_0_terms_accepted,
            payload.apache_notice_preservation_required,
            payload.apache_patent_terms_acknowledged,
            payload.enterprise_scope_excluded,
        )
    ):
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision lacks a mandatory acceptance")
    required_resolutions = build_genoffice_internal_oss_dependency_resolutions(dossier)
    if payload.dependency_license_resolutions != required_resolutions:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS dependency resolutions are incomplete")
    required_triggers = {
        "source_commit_change",
        "source_scope_change",
        "dependency_or_license_change",
        "notice_artifact_change",
        "trademark_use_change",
        "usage_profile_change",
        "signer_policy_change",
    }
    if set(payload.reevaluation_triggers) != required_triggers or len(payload.reevaluation_triggers) != len(
        required_triggers
    ):
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS reevaluation triggers are incomplete")


def verify_genoffice_internal_oss_admission(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
    envelope: GenOfficeInternalOssDecisionEnvelope,
    signer_policy: GenOfficeInternalOssSignerPolicy,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeInternalOssAdmissionReport:
    if dossier.report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH or not dossier.human_review_ready:
        raise GenOfficeInternalOssAdmissionError("GenOffice legal dossier is not ready for internal OSS admission")
    if notice_report.legal_dossier_report_hash != dossier.report_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice third-party notice is not linked to the legal dossier")
    if (
        notice_report.license_material_collection_report_hash != dossier.license_material_collection_report_hash
        or notice_report.source_archive_sha256 != dossier.source_archive_sha256
    ):
        raise GenOfficeInternalOssAdmissionError("GenOffice third-party notice evidence chain is not pinned")
    notice_hash = f"sha256:{hashlib.sha256(notice_artifact).hexdigest()}"
    if notice_hash != notice_report.notice_artifact_sha256:
        raise GenOfficeInternalOssAdmissionError("GenOffice third-party notice artifact hash is invalid")
    if build_genoffice_internal_oss_record_hash(envelope) != envelope.record_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision record hash is invalid")
    if build_genoffice_internal_oss_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS signer policy hash is invalid")
    if signer_policy.effective_at_utc > envelope.payload.decided_at_utc:
        raise GenOfficeInternalOssAdmissionError(
            "GenOffice internal OSS signer policy was not effective at decision time"
        )
    _verify_decision_scope(payload=envelope.payload, dossier=dossier, notice_report=notice_report)

    if len(envelope.approvals) != 2:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission requires exactly two approvals")
    if set(item.signer_role for item in envelope.approvals) != set(GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES):
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission lacks both required approval roles")
    if len({item.signer_id for item in envelope.approvals}) != 2:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission violates two-person control")
    policy_signers = {
        (item.signer_id, item.signer_role, item.key_id): item for item in signer_policy.signers if item.active
    }
    message = canonical_json(envelope.payload.model_dump(mode="json")).encode("utf-8")
    for approval in envelope.approvals:
        policy_signer = policy_signers.get((approval.signer_id, approval.signer_role, approval.key_id))
        if policy_signer is None:
            raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS approval signer is not authorized")
        public_key = _decode_base64(
            policy_signer.ed25519_public_key_base64,
            field="internal OSS public key",
            expected_size=32,
        )
        signature = _decode_base64(
            approval.signature_base64,
            field="internal OSS detached signature",
            expected_size=64,
        )
        if not signature_verifier.verify_ed25519(public_key=public_key, signature=signature, message=message):
            raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS detached signature is invalid")

    draft = GenOfficeInternalOssAdmissionReport(
        legal_dossier_report_hash=dossier.report_hash,
        third_party_notice_report_hash=notice_report.report_hash,
        third_party_notice_artifact_sha256=notice_report.notice_artifact_sha256,
        decision_payload_hash=envelope.payload.payload_hash,
        decision_record_hash=envelope.record_hash,
        signer_policy_hash=signer_policy.policy_hash,
        approved_usage_profiles=envelope.payload.approved_usage_profiles,
        blocked_usage_profiles=envelope.payload.blocked_usage_profiles,
        approved_source_scopes=envelope.payload.approved_source_scopes,
        prohibited_source_scopes=envelope.payload.prohibited_source_scopes,
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
    return draft.model_copy(update={"report_hash": build_genoffice_internal_oss_admission_report_hash(draft)})


def load_genoffice_internal_oss_decision(path: Path) -> GenOfficeInternalOssDecisionEnvelope:
    try:
        envelope = GenOfficeInternalOssDecisionEnvelope.model_validate_json(_read_limited(path))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS decision is not readable") from exc
    return envelope


def load_genoffice_internal_oss_signer_policy(path: Path) -> GenOfficeInternalOssSignerPolicy:
    try:
        policy = GenOfficeInternalOssSignerPolicy.model_validate_json(_read_limited(path))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS signer policy is not readable") from exc
    return policy


def load_genoffice_internal_oss_admission_report(path: Path) -> GenOfficeInternalOssAdmissionReport:
    try:
        report = GenOfficeInternalOssAdmissionReport.model_validate_json(_read_limited(path))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission report is not readable") from exc
    if build_genoffice_internal_oss_admission_report_hash(report) != report.report_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission report hash is invalid")
    return report


def persist_genoffice_internal_oss_admission_report(
    *, report: GenOfficeInternalOssAdmissionReport, report_path: Path
) -> None:
    if build_genoffice_internal_oss_admission_report_hash(report) != report.report_hash:
        raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)


def persist_genoffice_internal_oss_schemas(*, decision_schema_path: Path, signer_policy_schema_path: Path) -> None:
    outputs = (
        (decision_schema_path, GenOfficeInternalOssDecisionEnvelope.model_json_schema()),
        (signer_policy_schema_path, GenOfficeInternalOssSignerPolicy.model_json_schema()),
    )
    for path, schema in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)


def run_genoffice_internal_oss_admission_from_environment(
    env: Mapping[str, str],
) -> GenOfficeInternalOssAdmissionReport:
    values = {
        "dossier": env.get("SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH", "").strip(),
        "notice_report": env.get("SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH", "").strip(),
        "notice_artifact": env.get("SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH", "").strip(),
        "decision": env.get("SUITE_GENOFFICE_INTERNAL_OSS_DECISION_PATH", "").strip(),
        "signer_policy": env.get("SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH", "").strip(),
    }
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeInternalOssAdmissionError(f"GenOffice internal OSS admission paths are missing: {missing}")
    return verify_genoffice_internal_oss_admission(
        dossier=load_genoffice_legal_review_dossier(Path(values["dossier"])),
        notice_report=load_genoffice_third_party_notice_report(Path(values["notice_report"])),
        notice_artifact=_read_limited(Path(values["notice_artifact"])),
        envelope=load_genoffice_internal_oss_decision(Path(values["decision"])),
        signer_policy=load_genoffice_internal_oss_signer_policy(Path(values["signer_policy"])),
    )


def main() -> None:
    try:
        mode = os.environ.get("SUITE_GENOFFICE_INTERNAL_OSS_MODE", "verify").strip()
        decision_schema_path = os.environ.get("SUITE_GENOFFICE_INTERNAL_OSS_DECISION_SCHEMA_PATH", "").strip()
        signer_policy_schema_path = os.environ.get("SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_SCHEMA_PATH", "").strip()
        if not decision_schema_path or not signer_policy_schema_path:
            raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS schema output paths are required")
        persist_genoffice_internal_oss_schemas(
            decision_schema_path=Path(decision_schema_path),
            signer_policy_schema_path=Path(signer_policy_schema_path),
        )
        if mode == "schema":
            print(
                json.dumps(
                    {
                        "decision_schema_hash": stable_hash(
                            canonical_json(GenOfficeInternalOssDecisionEnvelope.model_json_schema())
                        ),
                        "signer_policy_schema_hash": stable_hash(
                            canonical_json(GenOfficeInternalOssSignerPolicy.model_json_schema())
                        ),
                    },
                    sort_keys=True,
                )
            )
            return
        if mode != "verify":
            raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS execution mode is invalid")
        report = run_genoffice_internal_oss_admission_from_environment(os.environ)
        report_path = os.environ.get("SUITE_GENOFFICE_INTERNAL_OSS_ADMISSION_REPORT_PATH", "").strip()
        if not report_path:
            raise GenOfficeInternalOssAdmissionError("GenOffice internal OSS admission output path is required")
        persist_genoffice_internal_oss_admission_report(report=report, report_path=Path(report_path))
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    except GenOfficeInternalOssAdmissionError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_INTERNAL_OSS_ADMISSION_REPORT_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
