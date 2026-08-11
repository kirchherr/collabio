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
from suite.operations.genoffice_internal_oss_admission import (
    GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES,
    GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
    GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
    GENOFFICE_INTERNAL_OSS_REEVALUATION_TRIGGERS,
    MAX_INTERNAL_OSS_INPUT_SIZE_BYTES,
    GenOfficeInternalOssAdmissionError,
    GenOfficeInternalOssDecisionEnvelope,
    GenOfficeInternalOssDecisionPayload,
    GenOfficeInternalOssDetachedApproval,
    GenOfficeInternalOssSigner,
    GenOfficeInternalOssSignerPolicy,
    build_genoffice_internal_oss_dependency_resolutions,
    build_genoffice_internal_oss_payload_hash,
    build_genoffice_internal_oss_record_hash,
    build_genoffice_internal_oss_signature_message,
    build_genoffice_internal_oss_signer_policy_hash,
    load_genoffice_internal_oss_signer_policy,
    verify_genoffice_internal_oss_envelope_signatures,
)
from suite.operations.genoffice_legal_review_dossier import (
    GENOFFICE_REQUIRED_TRADEMARK_POLICY,
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

GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_SCHEMA_VERSION = "genoffice_internal_oss_signing_request.v1"
GENOFFICE_INTERNAL_OSS_PUBLIC_KEY_SIZE_BYTES = 32
GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES = 64
_ZERO_HASH = "sha256:" + "0" * 64

SignerRole = Literal["product_owner", "security_compliance_owner"]


class GenOfficeInternalOssCeremonyError(ValueError):
    pass


class GenOfficeInternalOssSigningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_signing_request.v1"] = (
        "genoffice_internal_oss_signing_request.v1"
    )
    prepared_at_utc: datetime
    payload: GenOfficeInternalOssDecisionPayload
    signature_message_sha256: str
    signature_message_size_bytes: int
    required_signer_roles: tuple[SignerRole, ...]
    admission_effective: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice internal OSS signing request time must include a timezone")
        return value

    @model_validator(mode="after")
    def require_non_effective_exact_request(self) -> GenOfficeInternalOssSigningRequest:
        _require_sha256(self.signature_message_sha256, field="internal OSS signature message hash")
        _require_sha256(self.request_hash, field="internal OSS signing request hash")
        if self.signature_message_size_bytes <= 0:
            raise ValueError("GenOffice internal OSS signature message is empty")
        if self.required_signer_roles != GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES:
            raise ValueError("GenOffice internal OSS signing request roles are not exact")
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise GenOfficeInternalOssCeremonyError(f"GenOffice {field} is not a SHA-256 evidence hash")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice {field} is not a SHA-256 evidence hash") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _read_limited(path: Path, *, label: str, expected_size: int | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {label} cannot be read") from exc
    if len(content) > MAX_INTERNAL_OSS_INPUT_SIZE_BYTES:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {label} exceeds its size limit")
    if expected_size is not None and len(content) != expected_size:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {label} has an invalid size")
    return content


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _parse_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {field} lacks a timezone")
    return parsed


def build_genoffice_internal_oss_signer_policy(
    *,
    policy_id: str,
    effective_at_utc: datetime,
    product_owner_signer_id: str,
    product_owner_key_id: str,
    product_owner_public_key: bytes,
    security_compliance_owner_signer_id: str,
    security_compliance_owner_key_id: str,
    security_compliance_owner_public_key: bytes,
) -> GenOfficeInternalOssSignerPolicy:
    identities = (product_owner_signer_id.strip(), security_compliance_owner_signer_id.strip())
    key_ids = (product_owner_key_id.strip(), security_compliance_owner_key_id.strip())
    if not policy_id.strip() or not all(identities) or not all(key_ids):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy identity is empty")
    if len(set(identities)) != 2 or len(set(key_ids)) != 2:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy violates two-person separation")
    public_keys = (product_owner_public_key, security_compliance_owner_public_key)
    if any(len(item) != GENOFFICE_INTERNAL_OSS_PUBLIC_KEY_SIZE_BYTES for item in public_keys):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS public key has an invalid size")
    draft = GenOfficeInternalOssSignerPolicy(
        policy_id=policy_id.strip(),
        effective_at_utc=effective_at_utc,
        signers=(
            GenOfficeInternalOssSigner(
                signer_id=identities[0],
                signer_role="product_owner",
                key_id=key_ids[0],
                ed25519_public_key_base64=base64.b64encode(public_keys[0]).decode("ascii"),
                active=True,
            ),
            GenOfficeInternalOssSigner(
                signer_id=identities[1],
                signer_role="security_compliance_owner",
                key_id=key_ids[1],
                ed25519_public_key_base64=base64.b64encode(public_keys[1]).decode("ascii"),
                active=True,
            ),
        ),
        policy_hash=_ZERO_HASH,
    )
    return draft.model_copy(update={"policy_hash": build_genoffice_internal_oss_signer_policy_hash(draft)})


def persist_genoffice_internal_oss_signer_policy(
    *, policy: GenOfficeInternalOssSignerPolicy, policy_path: Path
) -> None:
    if build_genoffice_internal_oss_signer_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy hash is invalid")
    _active_signers_by_role(policy)
    _atomic_write(
        policy_path,
        (json.dumps(policy.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _verify_evidence_chain(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
) -> None:
    if dossier.report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH or not dossier.human_review_ready:
        raise GenOfficeInternalOssCeremonyError("GenOffice legal dossier is not ready for internal OSS signing")
    if notice_report.legal_dossier_report_hash != dossier.report_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice third-party notice is not linked to the legal dossier")
    if (
        notice_report.license_material_collection_report_hash != dossier.license_material_collection_report_hash
        or notice_report.source_archive_sha256 != dossier.source_archive_sha256
    ):
        raise GenOfficeInternalOssCeremonyError("GenOffice third-party notice evidence chain is not pinned")
    if _sha256_bytes(notice_artifact) != notice_report.notice_artifact_sha256:
        raise GenOfficeInternalOssCeremonyError("GenOffice third-party notice artifact hash is invalid")


def build_genoffice_internal_oss_signing_request(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
    signer_policy: GenOfficeInternalOssSignerPolicy,
    decision_id: str,
    decided_at_utc: datetime,
    prepared_at_utc: datetime,
    risk_acceptance_ref: str,
    change_control_ref: str,
) -> tuple[GenOfficeInternalOssSigningRequest, bytes]:
    _verify_evidence_chain(dossier=dossier, notice_report=notice_report, notice_artifact=notice_artifact)
    if build_genoffice_internal_oss_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy hash is invalid")
    _active_signers_by_role(signer_policy)
    if signer_policy.effective_at_utc > decided_at_utc:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy is not yet effective")
    payload_draft = GenOfficeInternalOssDecisionPayload(
        decision_id=decision_id,
        decision="approved_for_development_evaluation",
        decided_at_utc=decided_at_utc,
        risk_acceptance_ref=risk_acceptance_ref,
        change_control_ref=change_control_ref,
        signer_policy_hash=signer_policy.policy_hash,
        legal_dossier_report_hash=dossier.report_hash,
        third_party_notice_report_hash=notice_report.report_hash,
        third_party_notice_artifact_sha256=notice_report.notice_artifact_sha256,
        approved_usage_profiles=(GENOFFICE_DEVELOPMENT_PROFILE,),
        blocked_usage_profiles=GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
        approved_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        prohibited_source_scopes=GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
        trademark_policy=GENOFFICE_REQUIRED_TRADEMARK_POLICY,
        apache_2_0_terms_accepted=True,
        apache_notice_preservation_required=True,
        apache_patent_terms_acknowledged=True,
        enterprise_scope_excluded=True,
        jszip_selected_license_expression="MIT",
        pako_selected_license_expression="MIT AND Zlib",
        dependency_license_resolutions=build_genoffice_internal_oss_dependency_resolutions(dossier),
        reevaluation_triggers=GENOFFICE_INTERNAL_OSS_REEVALUATION_TRIGGERS,
        payload_hash=_ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_internal_oss_payload_hash(payload_draft)}
    )
    message = build_genoffice_internal_oss_signature_message(payload)
    request_draft = GenOfficeInternalOssSigningRequest(
        prepared_at_utc=prepared_at_utc,
        payload=payload,
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        required_signer_roles=GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES,
        request_hash=_ZERO_HASH,
    )
    request = request_draft.model_copy(
        update={"request_hash": build_genoffice_internal_oss_signing_request_hash(request_draft)}
    )
    return request, message


def build_genoffice_internal_oss_signing_request_hash(request: GenOfficeInternalOssSigningRequest) -> str:
    return stable_hash(canonical_json(request.model_dump(mode="json", exclude={"request_hash"})))


def verify_genoffice_internal_oss_signing_request(request: GenOfficeInternalOssSigningRequest) -> bytes:
    if build_genoffice_internal_oss_payload_hash(request.payload) != request.payload.payload_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing request payload hash is invalid")
    if build_genoffice_internal_oss_signing_request_hash(request) != request.request_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing request hash is invalid")
    message = build_genoffice_internal_oss_signature_message(request.payload)
    if _sha256_bytes(message) != request.signature_message_sha256 or len(message) != request.signature_message_size_bytes:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signature message binding is invalid")
    return message


def persist_genoffice_internal_oss_signing_request(
    *, request: GenOfficeInternalOssSigningRequest, request_path: Path, message_path: Path
) -> None:
    message = verify_genoffice_internal_oss_signing_request(request)
    _atomic_write(
        request_path,
        (json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(message_path, message)


def load_genoffice_internal_oss_signing_request(path: Path) -> GenOfficeInternalOssSigningRequest:
    try:
        request = GenOfficeInternalOssSigningRequest.model_validate_json(_read_limited(path, label="signing request"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing request is not readable") from exc
    verify_genoffice_internal_oss_signing_request(request)
    return request


def _active_signers_by_role(policy: GenOfficeInternalOssSignerPolicy) -> dict[SignerRole, GenOfficeInternalOssSigner]:
    active = tuple(item for item in policy.signers if item.active)
    if len(active) != 2 or {item.signer_role for item in active} != set(GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy requires exactly one active signer per role")
    if len({item.signer_id for item in active}) != 2 or len({item.key_id for item in active}) != 2:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy violates two-person separation")
    return {item.signer_role: item for item in active}


def assemble_genoffice_internal_oss_decision_envelope(
    *,
    request: GenOfficeInternalOssSigningRequest,
    signer_policy: GenOfficeInternalOssSignerPolicy,
    product_owner_signature: bytes,
    security_compliance_owner_signature: bytes,
) -> GenOfficeInternalOssDecisionEnvelope:
    verify_genoffice_internal_oss_signing_request(request)
    if build_genoffice_internal_oss_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy hash is invalid")
    if request.payload.signer_policy_hash != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy drifted after request creation")
    signatures = (product_owner_signature, security_compliance_owner_signature)
    if any(len(item) != GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES for item in signatures):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS detached signature has an invalid size")
    signers = _active_signers_by_role(signer_policy)
    approvals = (
        _approval(signers["product_owner"], product_owner_signature),
        _approval(signers["security_compliance_owner"], security_compliance_owner_signature),
    )
    draft = GenOfficeInternalOssDecisionEnvelope(
        payload=request.payload,
        approvals=approvals,
        record_hash=_ZERO_HASH,
    )
    envelope = draft.model_copy(update={"record_hash": build_genoffice_internal_oss_record_hash(draft)})
    verify_genoffice_internal_oss_envelope_signatures(envelope=envelope, signer_policy=signer_policy)
    return envelope


def _approval(signer: GenOfficeInternalOssSigner, signature: bytes) -> GenOfficeInternalOssDetachedApproval:
    return GenOfficeInternalOssDetachedApproval(
        signer_id=signer.signer_id,
        signer_role=signer.signer_role,
        key_id=signer.key_id,
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def persist_genoffice_internal_oss_decision_envelope(
    *, envelope: GenOfficeInternalOssDecisionEnvelope, envelope_path: Path
) -> None:
    if build_genoffice_internal_oss_record_hash(envelope) != envelope.record_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS decision record hash is invalid")
    _atomic_write(
        envelope_path,
        (json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _require_environment(env: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    values = {name: env.get(name, "").strip() for name in names}
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS ceremony values are missing: {missing}")
    return values


def run_genoffice_internal_oss_policy_from_environment(env: Mapping[str, str]) -> GenOfficeInternalOssSignerPolicy:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_ID",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_EFFECTIVE_AT_UTC",
            "SUITE_GENOFFICE_PRODUCT_OWNER_SIGNER_ID",
            "SUITE_GENOFFICE_PRODUCT_OWNER_KEY_ID",
            "SUITE_GENOFFICE_PRODUCT_OWNER_PUBLIC_KEY_PATH",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNER_ID",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_KEY_ID",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_PUBLIC_KEY_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH",
        ),
    )
    policy = build_genoffice_internal_oss_signer_policy(
        policy_id=values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_ID"],
        effective_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_EFFECTIVE_AT_UTC"], field="policy effective time"
        ),
        product_owner_signer_id=values["SUITE_GENOFFICE_PRODUCT_OWNER_SIGNER_ID"],
        product_owner_key_id=values["SUITE_GENOFFICE_PRODUCT_OWNER_KEY_ID"],
        product_owner_public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_PRODUCT_OWNER_PUBLIC_KEY_PATH"]),
            label="product owner public key",
            expected_size=GENOFFICE_INTERNAL_OSS_PUBLIC_KEY_SIZE_BYTES,
        ),
        security_compliance_owner_signer_id=values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNER_ID"],
        security_compliance_owner_key_id=values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_KEY_ID"],
        security_compliance_owner_public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_PUBLIC_KEY_PATH"]),
            label="security compliance owner public key",
            expected_size=GENOFFICE_INTERNAL_OSS_PUBLIC_KEY_SIZE_BYTES,
        ),
    )
    persist_genoffice_internal_oss_signer_policy(
        policy=policy,
        policy_path=Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH"]),
    )
    return policy


def run_genoffice_internal_oss_request_from_environment(env: Mapping[str, str]) -> GenOfficeInternalOssSigningRequest:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_DECISION_ID",
            "SUITE_GENOFFICE_INTERNAL_OSS_DECIDED_AT_UTC",
            "SUITE_GENOFFICE_INTERNAL_OSS_PREPARED_AT_UTC",
            "SUITE_GENOFFICE_INTERNAL_OSS_RISK_ACCEPTANCE_REF",
            "SUITE_GENOFFICE_INTERNAL_OSS_CHANGE_CONTROL_REF",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNATURE_MESSAGE_PATH",
        ),
    )
    request, message = build_genoffice_internal_oss_signing_request(
        dossier=load_genoffice_legal_review_dossier(Path(values["SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH"])),
        notice_report=load_genoffice_third_party_notice_report(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH"])
        ),
        notice_artifact=_read_limited(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH"]), label="third-party notice"
        ),
        signer_policy=load_genoffice_internal_oss_signer_policy(
            Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH"])
        ),
        decision_id=values["SUITE_GENOFFICE_INTERNAL_OSS_DECISION_ID"],
        decided_at_utc=_parse_datetime(values["SUITE_GENOFFICE_INTERNAL_OSS_DECIDED_AT_UTC"], field="decision time"),
        prepared_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_INTERNAL_OSS_PREPARED_AT_UTC"], field="request preparation time"
        ),
        risk_acceptance_ref=values["SUITE_GENOFFICE_INTERNAL_OSS_RISK_ACCEPTANCE_REF"],
        change_control_ref=values["SUITE_GENOFFICE_INTERNAL_OSS_CHANGE_CONTROL_REF"],
    )
    persist_genoffice_internal_oss_signing_request(
        request=request,
        request_path=Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_PATH"]),
        message_path=Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNATURE_MESSAGE_PATH"]),
    )
    if message != build_genoffice_internal_oss_signature_message(request.payload):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signature message changed before persistence")
    return request


def run_genoffice_internal_oss_assembly_from_environment(env: Mapping[str, str]) -> GenOfficeInternalOssDecisionEnvelope:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_PATH",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_DECISION_PATH",
        ),
    )
    envelope = assemble_genoffice_internal_oss_decision_envelope(
        request=load_genoffice_internal_oss_signing_request(
            Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_PATH"])
        ),
        signer_policy=load_genoffice_internal_oss_signer_policy(
            Path(values["SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH"])
        ),
        product_owner_signature=_read_limited(
            Path(values["SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_PATH"]),
            label="product owner signature",
            expected_size=GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES,
        ),
        security_compliance_owner_signature=_read_limited(
            Path(values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_PATH"]),
            label="security compliance owner signature",
            expected_size=GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES,
        ),
    )
    persist_genoffice_internal_oss_decision_envelope(
        envelope=envelope,
        envelope_path=Path(values["SUITE_GENOFFICE_INTERNAL_OSS_DECISION_PATH"]),
    )
    return envelope


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_INTERNAL_OSS_CEREMONY_MODE", "").strip()
    try:
        if mode == "policy":
            result: BaseModel = run_genoffice_internal_oss_policy_from_environment(os.environ)
        elif mode == "request":
            result = run_genoffice_internal_oss_request_from_environment(os.environ)
        elif mode == "assemble":
            result = run_genoffice_internal_oss_assembly_from_environment(os.environ)
        else:
            raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS ceremony mode is invalid")
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    except (GenOfficeInternalOssCeremonyError, GenOfficeInternalOssAdmissionError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
