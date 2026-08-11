from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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

GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_SCHEMA_VERSION = "genoffice_internal_oss_signing_request.v2"
GENOFFICE_INTERNAL_OSS_EXTERNAL_SIGNATURE_RESPONSE_SCHEMA_VERSION = (
    "genoffice_internal_oss_external_signature_response.v1"
)
GENOFFICE_INTERNAL_OSS_PUBLIC_KEY_SIZE_BYTES = 32
GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES = 64
GENOFFICE_INTERNAL_OSS_MAX_SIGNING_REQUEST_VALIDITY = timedelta(hours=72)
_ZERO_HASH = "sha256:" + "0" * 64

SignerRole = Literal["product_owner", "security_compliance_owner"]


class GenOfficeInternalOssCeremonyError(ValueError):
    pass


class GenOfficeInternalOssSigningAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: SignerRole
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"

    @model_validator(mode="after")
    def require_identity(self) -> GenOfficeInternalOssSigningAssignment:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice internal OSS signing assignment identity is empty")
        return self


class GenOfficeInternalOssSigningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_signing_request.v2"] = "genoffice_internal_oss_signing_request.v2"
    prepared_at_utc: datetime
    valid_until_utc: datetime
    payload: GenOfficeInternalOssDecisionPayload
    signature_message_sha256: str
    signature_message_size_bytes: int
    required_signer_roles: tuple[SignerRole, ...]
    signing_assignments: tuple[GenOfficeInternalOssSigningAssignment, ...]
    admission_effective: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice internal OSS signing request time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_non_effective_exact_request(self) -> GenOfficeInternalOssSigningRequest:
        _require_sha256(self.signature_message_sha256, field="internal OSS signature message hash")
        _require_sha256(self.request_hash, field="internal OSS signing request hash")
        if self.signature_message_size_bytes <= 0:
            raise ValueError("GenOffice internal OSS signature message is empty")
        if self.required_signer_roles != GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES:
            raise ValueError("GenOffice internal OSS signing request roles are not exact")
        if not (
            self.prepared_at_utc < self.valid_until_utc
            <= self.prepared_at_utc + GENOFFICE_INTERNAL_OSS_MAX_SIGNING_REQUEST_VALIDITY
        ):
            raise ValueError("GenOffice internal OSS signing request validity window is invalid")
        if not self.prepared_at_utc <= self.payload.decided_at_utc <= self.valid_until_utc:
            raise ValueError("GenOffice internal OSS proposed decision time is outside the request validity window")
        roles = tuple(item.signer_role for item in self.signing_assignments)
        if roles != GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES:
            raise ValueError("GenOffice internal OSS signing assignments are not in canonical role order")
        if len({item.signer_id for item in self.signing_assignments}) != 2 or len(
            {item.key_id for item in self.signing_assignments}
        ) != 2:
            raise ValueError("GenOffice internal OSS signing assignments violate two-person separation")
        return self


class GenOfficeInternalOssExternalSignatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_internal_oss_external_signature_response.v1"] = (
        "genoffice_internal_oss_external_signature_response.v1"
    )
    request_hash: str
    signature_message_sha256: str
    signer_id: str
    signer_role: SignerRole
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @model_validator(mode="after")
    def require_bound_external_response(self) -> GenOfficeInternalOssExternalSignatureResponse:
        _require_sha256(self.request_hash, field="internal OSS signing request hash")
        _require_sha256(self.signature_message_sha256, field="internal OSS signature message hash")
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice internal OSS external signature identity is empty")
        _decode_canonical_base64(
            self.signature_base64,
            label="external detached signature",
            expected_size=GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES,
        )
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


def _decode_canonical_base64(value: str, *, label: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {label} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS {label} has an invalid size or encoding")
    return decoded


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


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS output already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    temporary_created = False
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise GenOfficeInternalOssCeremonyError(
            f"GenOffice internal OSS output or temporary file already exists: {path.name}"
        ) from exc
    except OSError as exc:
        raise GenOfficeInternalOssCeremonyError(f"GenOffice internal OSS output cannot be persisted: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_created:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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
    _write_new_private(
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
    valid_until_utc: datetime,
    risk_acceptance_ref: str,
    change_control_ref: str,
) -> tuple[GenOfficeInternalOssSigningRequest, bytes]:
    _verify_evidence_chain(dossier=dossier, notice_report=notice_report, notice_artifact=notice_artifact)
    if build_genoffice_internal_oss_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy hash is invalid")
    signers = _active_signers_by_role(signer_policy)
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
        valid_until_utc=valid_until_utc,
        payload=payload,
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        required_signer_roles=GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES,
        signing_assignments=tuple(
            GenOfficeInternalOssSigningAssignment(
                signer_id=signers[role].signer_id,
                signer_role=role,
                key_id=signers[role].key_id,
            )
            for role in GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES
        ),
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
    if (
        _sha256_bytes(message) != request.signature_message_sha256
        or len(message) != request.signature_message_size_bytes
    ):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signature message binding is invalid")
    return message


def persist_genoffice_internal_oss_signing_request(
    *, request: GenOfficeInternalOssSigningRequest, request_path: Path, message_path: Path
) -> None:
    message = verify_genoffice_internal_oss_signing_request(request)
    _write_new_private(
        request_path,
        (json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _write_new_private(message_path, message)


def load_genoffice_internal_oss_signing_request(path: Path) -> GenOfficeInternalOssSigningRequest:
    try:
        request = GenOfficeInternalOssSigningRequest.model_validate_json(_read_limited(path, label="signing request"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing request is not readable") from exc
    verify_genoffice_internal_oss_signing_request(request)
    return request


def load_genoffice_internal_oss_external_signature_response(
    path: Path,
) -> GenOfficeInternalOssExternalSignatureResponse:
    try:
        return GenOfficeInternalOssExternalSignatureResponse.model_validate_json(
            _read_limited(path, label="external signature response")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeInternalOssCeremonyError(
            "GenOffice internal OSS external signature response is not readable"
        ) from exc


def _active_signers_by_role(policy: GenOfficeInternalOssSignerPolicy) -> dict[SignerRole, GenOfficeInternalOssSigner]:
    active = tuple(item for item in policy.signers if item.active)
    if len(active) != 2 or {item.signer_role for item in active} != set(GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES):
        raise GenOfficeInternalOssCeremonyError(
            "GenOffice internal OSS signer policy requires exactly one active signer per role"
        )
    if len({item.signer_id for item in active}) != 2 or len({item.key_id for item in active}) != 2:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy violates two-person separation")
    return {item.signer_role: item for item in active}


def assemble_genoffice_internal_oss_decision_envelope(
    *,
    request: GenOfficeInternalOssSigningRequest,
    signer_policy: GenOfficeInternalOssSignerPolicy,
    signature_responses: tuple[GenOfficeInternalOssExternalSignatureResponse, ...],
    assembled_at_utc: datetime,
) -> GenOfficeInternalOssDecisionEnvelope:
    message = verify_genoffice_internal_oss_signing_request(request)
    if assembled_at_utc.tzinfo is None or assembled_at_utc.utcoffset() is None:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS assembly time lacks a timezone")
    assembled_at = assembled_at_utc.astimezone(UTC)
    if not request.prepared_at_utc <= assembled_at <= request.valid_until_utc:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing request is not currently valid")
    if build_genoffice_internal_oss_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy hash is invalid")
    if request.payload.signer_policy_hash != signer_policy.policy_hash:
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signer policy drifted after request creation")
    signers = _active_signers_by_role(signer_policy)
    assignments = {item.signer_role: item for item in request.signing_assignments}
    if any(
        (
            assignments[role].signer_id != signers[role].signer_id
            or assignments[role].key_id != signers[role].key_id
        )
        for role in GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES
    ):
        raise GenOfficeInternalOssCeremonyError("GenOffice internal OSS signing assignment drifted from signer policy")
    if len(signature_responses) != 2 or {item.signer_role for item in signature_responses} != set(
        GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES
    ):
        raise GenOfficeInternalOssCeremonyError(
            "GenOffice internal OSS assembly requires one external response per role"
        )
    responses = {item.signer_role: item for item in signature_responses}
    approvals_list: list[GenOfficeInternalOssDetachedApproval] = []
    for role in GENOFFICE_INTERNAL_OSS_APPROVAL_ROLES:
        response = responses[role]
        assignment = assignments[role]
        if (
            response.request_hash != request.request_hash
            or response.signature_message_sha256 != request.signature_message_sha256
        ):
            raise GenOfficeInternalOssCeremonyError(
                "GenOffice internal OSS external signature response is bound to another request"
            )
        if response.signer_id != assignment.signer_id or response.key_id != assignment.key_id:
            raise GenOfficeInternalOssCeremonyError(
                "GenOffice internal OSS external signature response violates its signing assignment"
            )
        signature = _decode_canonical_base64(
            response.signature_base64,
            label="external detached signature",
            expected_size=GENOFFICE_INTERNAL_OSS_SIGNATURE_SIZE_BYTES,
        )
        approvals_list.append(_approval(signers[role], signature))
    approvals = tuple(approvals_list)
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
    _write_new_private(
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
            "SUITE_GENOFFICE_INTERNAL_OSS_VALID_UNTIL_UTC",
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
        valid_until_utc=_parse_datetime(
            values["SUITE_GENOFFICE_INTERNAL_OSS_VALID_UNTIL_UTC"], field="request expiration time"
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


def run_genoffice_internal_oss_assembly_from_environment(
    env: Mapping[str, str],
) -> GenOfficeInternalOssDecisionEnvelope:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_INTERNAL_OSS_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_RESPONSE_PATH",
            "SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_RESPONSE_PATH",
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
        signature_responses=(
            load_genoffice_internal_oss_external_signature_response(
                Path(values["SUITE_GENOFFICE_PRODUCT_OWNER_SIGNATURE_RESPONSE_PATH"])
            ),
            load_genoffice_internal_oss_external_signature_response(
                Path(values["SUITE_GENOFFICE_SECURITY_COMPLIANCE_OWNER_SIGNATURE_RESPONSE_PATH"])
            ),
        ),
        assembled_at_utc=datetime.now(UTC),
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
