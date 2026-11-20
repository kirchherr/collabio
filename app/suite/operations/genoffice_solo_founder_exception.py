from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_internal_oss_admission import (
    GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
    GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
    MAX_INTERNAL_OSS_INPUT_SIZE_BYTES,
)
from suite.operations.genoffice_legal_review_dossier import (
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

GENOFFICE_SOLO_FOUNDER_POLICY_SCHEMA_VERSION = "genoffice_solo_founder_policy.v1"
GENOFFICE_SOLO_FOUNDER_REQUEST_SCHEMA_VERSION = "genoffice_solo_founder_exception_request.v1"
GENOFFICE_SOLO_FOUNDER_RESPONSE_SCHEMA_VERSION = "genoffice_solo_founder_signature_response.v1"
GENOFFICE_SOLO_FOUNDER_REPORT_SCHEMA_VERSION = "genoffice_solo_founder_exception_report.v1"
GENOFFICE_SOLO_FOUNDER_ROLE = "founder_risk_owner"
GENOFFICE_SOLO_FOUNDER_MAX_VALIDITY = timedelta(days=30)
GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS = (
    "pinned_public_evidence_chain",
    "single_founder_ed25519_risk_acceptance",
    "write_once_private_exception_evidence",
    "maximum_30_day_validity",
    "development_build_context_only",
    "no_network_materialization",
    "no_tenant_content",
    "two_person_reauthorization_before_runtime",
)
GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS = ("product_owner", "security_compliance_owner")
GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS = (
    "source_import",
    "engine_execution",
    "tenant_content_processing",
    "hosted_service",
    "on_prem_distribution",
    "production_use",
)
PUBLIC_KEY_SIZE_BYTES = 32
SIGNATURE_SIZE_BYTES = 64
_ZERO_HASH = "sha256:" + "0" * 64


class GenOfficeSoloFounderExceptionError(ValueError):
    pass


class GenOfficeSoloFounderSigner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: Literal["founder_risk_owner"] = "founder_risk_owner"
    key_id: str
    ed25519_public_key_base64: str

    @model_validator(mode="after")
    def require_identity_and_key(self) -> GenOfficeSoloFounderSigner:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice solo-founder signer identity is empty")
        _decode_canonical_base64(
            self.ed25519_public_key_base64,
            label="solo-founder public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        )
        return self


class GenOfficeSoloFounderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_solo_founder_policy.v1"] = "genoffice_solo_founder_policy.v1"
    policy_id: str
    effective_at_utc: datetime
    signer: GenOfficeSoloFounderSigner
    policy_hash: str

    @field_validator("effective_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice solo-founder policy time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_identity_and_hash(self) -> GenOfficeSoloFounderPolicy:
        if not self.policy_id.strip():
            raise ValueError("GenOffice solo-founder policy identity is empty")
        _require_sha256(self.policy_hash, field="solo-founder policy hash")
        return self


class GenOfficeSoloFounderExceptionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_solo_founder_exception_payload.v1"] = (
        "genoffice_solo_founder_exception_payload.v1"
    )
    exception_id: str
    issued_at_utc: datetime
    valid_until_utc: datetime
    risk_acceptance_ref: str
    change_control_ref: str
    signer_policy_hash: str
    legal_dossier_report_hash: str
    third_party_notice_report_hash: str
    third_party_notice_artifact_sha256: str
    approved_usage_profiles: tuple[str, ...]
    blocked_usage_profiles: tuple[str, ...]
    approved_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    compensating_controls: tuple[str, ...]
    later_required_approval_roles: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    source_import_allowed: Literal[False] = False
    engine_execution_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    payload_hash: str

    @field_validator("issued_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice solo-founder exception time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_development_exception(self) -> GenOfficeSoloFounderExceptionPayload:
        if not all(value.strip() for value in (self.exception_id, self.risk_acceptance_ref, self.change_control_ref)):
            raise ValueError("GenOffice solo-founder exception identity or control reference is empty")
        if not (self.issued_at_utc < self.valid_until_utc <= self.issued_at_utc + GENOFFICE_SOLO_FOUNDER_MAX_VALIDITY):
            raise ValueError("GenOffice solo-founder exception validity window is invalid")
        _require_sha256(self.signer_policy_hash, field="solo-founder policy hash")
        _require_sha256(self.payload_hash, field="solo-founder payload hash")
        expected = (
            (self.legal_dossier_report_hash, GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH),
            (self.approved_usage_profiles, (GENOFFICE_DEVELOPMENT_PROFILE,)),
            (self.blocked_usage_profiles, GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES),
            (self.approved_source_scopes, (GENOFFICE_SELECTED_SOURCE_SCOPE,)),
            (self.prohibited_source_scopes, GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES),
            (self.compensating_controls, GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS),
            (self.later_required_approval_roles, GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS),
            (self.blocked_actions, GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS),
        )
        if any(actual != required for actual, required in expected):
            raise ValueError("GenOffice solo-founder exception boundary is not exact")
        return self


class GenOfficeSoloFounderSigningAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signer_id: str
    signer_role: Literal["founder_risk_owner"] = "founder_risk_owner"
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"


class GenOfficeSoloFounderExceptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_solo_founder_exception_request.v1"] = (
        "genoffice_solo_founder_exception_request.v1"
    )
    prepared_at_utc: datetime
    payload: GenOfficeSoloFounderExceptionPayload
    signing_assignment: GenOfficeSoloFounderSigningAssignment
    signature_message_sha256: str
    signature_message_size_bytes: int
    exception_effective: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice solo-founder request time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_bound_request(self) -> GenOfficeSoloFounderExceptionRequest:
        if self.prepared_at_utc != self.payload.issued_at_utc:
            raise ValueError("GenOffice solo-founder request and issue times differ")
        if not self.signing_assignment.signer_id.strip() or not self.signing_assignment.key_id.strip():
            raise ValueError("GenOffice solo-founder signing assignment identity is empty")
        if self.signature_message_size_bytes <= 0:
            raise ValueError("GenOffice solo-founder signature message is empty")
        _require_sha256(self.signature_message_sha256, field="solo-founder signature message hash")
        _require_sha256(self.request_hash, field="solo-founder request hash")
        return self


class GenOfficeSoloFounderSignatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_solo_founder_signature_response.v1"] = (
        "genoffice_solo_founder_signature_response.v1"
    )
    request_hash: str
    signature_message_sha256: str
    signer_id: str
    signer_role: Literal["founder_risk_owner"] = "founder_risk_owner"
    key_id: str
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @model_validator(mode="after")
    def require_bound_response(self) -> GenOfficeSoloFounderSignatureResponse:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice solo-founder response identity is empty")
        _require_sha256(self.request_hash, field="solo-founder request hash")
        _require_sha256(self.signature_message_sha256, field="solo-founder signature message hash")
        _decode_canonical_base64(
            self.signature_base64,
            label="solo-founder detached signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        return self


class GenOfficeSoloFounderExceptionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_solo_founder_exception_report.v1"] = "genoffice_solo_founder_exception_report.v1"
    exception_id: str
    issued_at_utc: datetime
    valid_until_utc: datetime
    signer_id: str
    key_id: str
    signer_policy_hash: str
    exception_payload_hash: str
    signing_request_hash: str
    signature_response_hash: str
    legal_dossier_report_hash: str
    third_party_notice_report_hash: str
    third_party_notice_artifact_sha256: str
    approved_usage_profiles: tuple[str, ...]
    blocked_usage_profiles: tuple[str, ...]
    approved_source_scopes: tuple[str, ...]
    prohibited_source_scopes: tuple[str, ...]
    compensating_controls: tuple[str, ...]
    later_required_approval_roles: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    solo_founder_risk_acceptance_verified: Literal[True] = True
    detached_signature_verified: Literal[True] = True
    compensating_controls_verified: Literal[True] = True
    write_once_evidence_required: Literal[True] = True
    two_person_control_verified: Literal[False] = False
    development_build_context_materialization_allowed: Literal[True] = True
    reproducible_worker_build_allowed: Literal[True] = True
    source_import_allowed: Literal[False] = False
    engine_execution_allowed: Literal[False] = False
    hosted_service_allowed: Literal[False] = False
    on_prem_distribution_allowed: Literal[False] = False
    production_use_allowed: Literal[False] = False
    tenant_content_allowed: Literal[False] = False
    report_hash: str

    @field_validator("issued_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice solo-founder report time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_exact_boundary(self) -> GenOfficeSoloFounderExceptionReport:
        if not self.exception_id.strip() or not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice solo-founder report identity is empty")
        if not (self.issued_at_utc < self.valid_until_utc <= self.issued_at_utc + GENOFFICE_SOLO_FOUNDER_MAX_VALIDITY):
            raise ValueError("GenOffice solo-founder report validity window is invalid")
        for field, value in (
            ("solo-founder policy hash", self.signer_policy_hash),
            ("solo-founder payload hash", self.exception_payload_hash),
            ("solo-founder request hash", self.signing_request_hash),
            ("solo-founder response hash", self.signature_response_hash),
            ("solo-founder report hash", self.report_hash),
        ):
            _require_sha256(value, field=field)
        expected = (
            (self.legal_dossier_report_hash, GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH),
            (self.approved_usage_profiles, (GENOFFICE_DEVELOPMENT_PROFILE,)),
            (self.blocked_usage_profiles, GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES),
            (self.approved_source_scopes, (GENOFFICE_SELECTED_SOURCE_SCOPE,)),
            (self.prohibited_source_scopes, GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES),
            (self.compensating_controls, GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS),
            (self.later_required_approval_roles, GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS),
            (self.blocked_actions, GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS),
        )
        if any(actual != required for actual, required in expected):
            raise ValueError("GenOffice solo-founder report boundary is not exact")
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {field} is not a SHA-256 evidence hash")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {field} is not a SHA-256 evidence hash") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _decode_canonical_base64(value: str, *, label: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {label} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {label} has an invalid size or encoding")
    return decoded


def _read_limited(path: Path, *, label: str, expected_size: int | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {label} cannot be read") from exc
    if len(content) > MAX_INTERNAL_OSS_INPUT_SIZE_BYTES:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {label} exceeds its size limit")
    if expected_size is not None and len(content) != expected_size:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {label} has an invalid size")
    return content


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GenOfficeSoloFounderExceptionError(f"GenOffice solo-founder output already exists: {path.name}")
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
        raise GenOfficeSoloFounderExceptionError(
            f"GenOffice solo-founder output or temporary file already exists: {path.name}"
        ) from exc
    except OSError as exc:
        raise GenOfficeSoloFounderExceptionError(
            f"GenOffice solo-founder output cannot be persisted: {path.name}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_created:
            with suppress(FileNotFoundError):
                temporary.unlink()


def _parse_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice {field} lacks a timezone")
    return parsed.astimezone(UTC)


def build_genoffice_solo_founder_policy_hash(policy: GenOfficeSoloFounderPolicy) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json", exclude={"policy_hash"})))


def build_genoffice_solo_founder_payload_hash(payload: GenOfficeSoloFounderExceptionPayload) -> str:
    return stable_hash(canonical_json(payload.model_dump(mode="json", exclude={"payload_hash"})))


def build_genoffice_solo_founder_request_hash(request: GenOfficeSoloFounderExceptionRequest) -> str:
    return stable_hash(canonical_json(request.model_dump(mode="json", exclude={"request_hash"})))


def build_genoffice_solo_founder_response_hash(response: GenOfficeSoloFounderSignatureResponse) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json")))


def build_genoffice_solo_founder_report_hash(report: GenOfficeSoloFounderExceptionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_genoffice_solo_founder_signature_message(payload: GenOfficeSoloFounderExceptionPayload) -> bytes:
    return canonical_json(payload.model_dump(mode="json")).encode("utf-8")


def build_genoffice_solo_founder_policy(
    *, policy_id: str, effective_at_utc: datetime, signer_id: str, key_id: str, public_key: bytes
) -> GenOfficeSoloFounderPolicy:
    if len(public_key) != PUBLIC_KEY_SIZE_BYTES:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder public key has an invalid size")
    draft = GenOfficeSoloFounderPolicy(
        policy_id=policy_id,
        effective_at_utc=effective_at_utc,
        signer=GenOfficeSoloFounderSigner(
            signer_id=signer_id,
            key_id=key_id,
            ed25519_public_key_base64=base64.b64encode(public_key).decode("ascii"),
        ),
        policy_hash=_ZERO_HASH,
    )
    return draft.model_copy(update={"policy_hash": build_genoffice_solo_founder_policy_hash(draft)})


def _verify_evidence_chain(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
) -> None:
    if dossier.report_hash != GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH or not dossier.human_review_ready:
        raise GenOfficeSoloFounderExceptionError("GenOffice legal dossier is not ready for founder risk acceptance")
    if notice_report.legal_dossier_report_hash != dossier.report_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice third-party notice is not linked to the legal dossier")
    if (
        notice_report.license_material_collection_report_hash != dossier.license_material_collection_report_hash
        or notice_report.source_archive_sha256 != dossier.source_archive_sha256
    ):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder public evidence chain is not pinned")
    if _sha256_bytes(notice_artifact) != notice_report.notice_artifact_sha256:
        raise GenOfficeSoloFounderExceptionError("GenOffice third-party notice artifact hash is invalid")


def build_genoffice_solo_founder_request(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
    policy: GenOfficeSoloFounderPolicy,
    exception_id: str,
    issued_at_utc: datetime,
    valid_until_utc: datetime,
    risk_acceptance_ref: str,
    change_control_ref: str,
) -> tuple[GenOfficeSoloFounderExceptionRequest, bytes]:
    _verify_evidence_chain(dossier=dossier, notice_report=notice_report, notice_artifact=notice_artifact)
    if build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy hash is invalid")
    if policy.effective_at_utc > issued_at_utc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy is not yet effective")
    payload_draft = GenOfficeSoloFounderExceptionPayload(
        exception_id=exception_id,
        issued_at_utc=issued_at_utc,
        valid_until_utc=valid_until_utc,
        risk_acceptance_ref=risk_acceptance_ref,
        change_control_ref=change_control_ref,
        signer_policy_hash=policy.policy_hash,
        legal_dossier_report_hash=dossier.report_hash,
        third_party_notice_report_hash=notice_report.report_hash,
        third_party_notice_artifact_sha256=notice_report.notice_artifact_sha256,
        approved_usage_profiles=(GENOFFICE_DEVELOPMENT_PROFILE,),
        blocked_usage_profiles=GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
        approved_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        prohibited_source_scopes=GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
        compensating_controls=GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS,
        later_required_approval_roles=GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS,
        blocked_actions=GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS,
        payload_hash=_ZERO_HASH,
    )
    payload = payload_draft.model_copy(
        update={"payload_hash": build_genoffice_solo_founder_payload_hash(payload_draft)}
    )
    message = build_genoffice_solo_founder_signature_message(payload)
    request_draft = GenOfficeSoloFounderExceptionRequest(
        prepared_at_utc=issued_at_utc,
        payload=payload,
        signing_assignment=GenOfficeSoloFounderSigningAssignment(
            signer_id=policy.signer.signer_id,
            key_id=policy.signer.key_id,
        ),
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        request_hash=_ZERO_HASH,
    )
    request = request_draft.model_copy(
        update={"request_hash": build_genoffice_solo_founder_request_hash(request_draft)}
    )
    return request, message


def verify_genoffice_solo_founder_request(request: GenOfficeSoloFounderExceptionRequest) -> bytes:
    if build_genoffice_solo_founder_payload_hash(request.payload) != request.payload.payload_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder payload hash is invalid")
    if build_genoffice_solo_founder_request_hash(request) != request.request_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder request hash is invalid")
    message = build_genoffice_solo_founder_signature_message(request.payload)
    if (
        _sha256_bytes(message) != request.signature_message_sha256
        or len(message) != request.signature_message_size_bytes
    ):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder signature message binding is invalid")
    return message


def verify_genoffice_solo_founder_exception(
    *,
    dossier: GenOfficeLegalReviewDossierReport,
    notice_report: GenOfficeThirdPartyNoticeReport,
    notice_artifact: bytes,
    policy: GenOfficeSoloFounderPolicy,
    request: GenOfficeSoloFounderExceptionRequest,
    response: GenOfficeSoloFounderSignatureResponse,
    verified_at_utc: datetime,
    signature_verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeSoloFounderExceptionReport:
    _verify_evidence_chain(dossier=dossier, notice_report=notice_report, notice_artifact=notice_artifact)
    message = verify_genoffice_solo_founder_request(request)
    if verified_at_utc.tzinfo is None or verified_at_utc.utcoffset() is None:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder verification time lacks a timezone")
    verified_at = verified_at_utc.astimezone(UTC)
    if not request.payload.issued_at_utc <= verified_at <= request.payload.valid_until_utc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder exception is not currently valid")
    if build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy hash is invalid")
    if request.payload.signer_policy_hash != policy.policy_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy drifted after request creation")
    assignment = request.signing_assignment
    if (assignment.signer_id, assignment.key_id) != (policy.signer.signer_id, policy.signer.key_id):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder signing assignment drifted from policy")
    if (
        response.request_hash != request.request_hash
        or response.signature_message_sha256 != request.signature_message_sha256
    ):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder response is bound to another request")
    if (response.signer_id, response.key_id) != (assignment.signer_id, assignment.key_id):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder response violates its assignment")
    public_key = _decode_canonical_base64(
        policy.signer.ed25519_public_key_base64,
        label="solo-founder public key",
        expected_size=PUBLIC_KEY_SIZE_BYTES,
    )
    signature = _decode_canonical_base64(
        response.signature_base64,
        label="solo-founder detached signature",
        expected_size=SIGNATURE_SIZE_BYTES,
    )
    if not signature_verifier.verify_ed25519(public_key=public_key, signature=signature, message=message):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder detached signature is invalid")
    payload = request.payload
    expected_evidence = (
        (payload.legal_dossier_report_hash, dossier.report_hash),
        (payload.third_party_notice_report_hash, notice_report.report_hash),
        (payload.third_party_notice_artifact_sha256, notice_report.notice_artifact_sha256),
    )
    if any(actual != expected for actual, expected in expected_evidence):
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder signed evidence chain drifted")
    draft = GenOfficeSoloFounderExceptionReport(
        exception_id=payload.exception_id,
        issued_at_utc=payload.issued_at_utc,
        valid_until_utc=payload.valid_until_utc,
        signer_id=policy.signer.signer_id,
        key_id=policy.signer.key_id,
        signer_policy_hash=policy.policy_hash,
        exception_payload_hash=payload.payload_hash,
        signing_request_hash=request.request_hash,
        signature_response_hash=build_genoffice_solo_founder_response_hash(response),
        legal_dossier_report_hash=payload.legal_dossier_report_hash,
        third_party_notice_report_hash=payload.third_party_notice_report_hash,
        third_party_notice_artifact_sha256=payload.third_party_notice_artifact_sha256,
        approved_usage_profiles=payload.approved_usage_profiles,
        blocked_usage_profiles=payload.blocked_usage_profiles,
        approved_source_scopes=payload.approved_source_scopes,
        prohibited_source_scopes=payload.prohibited_source_scopes,
        compensating_controls=payload.compensating_controls,
        later_required_approval_roles=payload.later_required_approval_roles,
        blocked_actions=payload.blocked_actions,
        report_hash=_ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_solo_founder_report_hash(draft)})


def load_genoffice_solo_founder_policy(path: Path) -> GenOfficeSoloFounderPolicy:
    try:
        policy = GenOfficeSoloFounderPolicy.model_validate_json(_read_limited(path, label="solo-founder policy"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy is not readable") from exc
    if build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy hash is invalid")
    return policy


def load_genoffice_solo_founder_request(path: Path) -> GenOfficeSoloFounderExceptionRequest:
    try:
        request = GenOfficeSoloFounderExceptionRequest.model_validate_json(
            _read_limited(path, label="solo-founder request")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder request is not readable") from exc
    verify_genoffice_solo_founder_request(request)
    return request


def load_genoffice_solo_founder_response(path: Path) -> GenOfficeSoloFounderSignatureResponse:
    try:
        return GenOfficeSoloFounderSignatureResponse.model_validate_json(
            _read_limited(path, label="solo-founder signature response")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder response is not readable") from exc


def load_genoffice_solo_founder_report(path: Path) -> GenOfficeSoloFounderExceptionReport:
    try:
        report = GenOfficeSoloFounderExceptionReport.model_validate_json(
            _read_limited(path, label="solo-founder exception report")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder report is not readable") from exc
    if build_genoffice_solo_founder_report_hash(report) != report.report_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder report hash is invalid")
    return report


def persist_genoffice_solo_founder_policy(*, policy: GenOfficeSoloFounderPolicy, path: Path) -> None:
    if build_genoffice_solo_founder_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder policy hash is invalid")
    _write_new_private(path, _json_bytes(policy))


def persist_genoffice_solo_founder_request(
    *, request: GenOfficeSoloFounderExceptionRequest, message: bytes, request_path: Path, message_path: Path
) -> None:
    if verify_genoffice_solo_founder_request(request) != message:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder signature message changed before persistence")
    _write_new_private(request_path, _json_bytes(request))
    _write_new_private(message_path, message)


def persist_genoffice_solo_founder_report(*, report: GenOfficeSoloFounderExceptionReport, path: Path) -> None:
    if build_genoffice_solo_founder_report_hash(report) != report.report_hash:
        raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder report hash is invalid")
    _write_new_private(path, _json_bytes(report))


def persist_genoffice_solo_founder_schemas(*, output_directory: Path) -> dict[str, str]:
    schemas = {
        "policy": ("genoffice-solo-founder-policy.schema.json", GenOfficeSoloFounderPolicy.model_json_schema()),
        "request": (
            "genoffice-solo-founder-exception-request.schema.json",
            GenOfficeSoloFounderExceptionRequest.model_json_schema(),
        ),
        "response": (
            "genoffice-solo-founder-signature-response.schema.json",
            GenOfficeSoloFounderSignatureResponse.model_json_schema(),
        ),
        "report": (
            "genoffice-solo-founder-exception-report.schema.json",
            GenOfficeSoloFounderExceptionReport.model_json_schema(),
        ),
    }
    hashes: dict[str, str] = {}
    for name, (filename, schema) in schemas.items():
        _write_new_private(
            output_directory / filename,
            (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        hashes[f"{name}_schema_hash"] = stable_hash(canonical_json(schema))
    return hashes


def _json_bytes(value: BaseModel) -> bytes:
    return (json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_environment(env: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    values = {name: env.get(name, "").strip() for name in names}
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeSoloFounderExceptionError(f"GenOffice solo-founder values are missing: {missing}")
    return values


def run_policy_from_environment(env: Mapping[str, str]) -> GenOfficeSoloFounderPolicy:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_ID",
            "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_EFFECTIVE_AT_UTC",
            "SUITE_GENOFFICE_SOLO_FOUNDER_SIGNER_ID",
            "SUITE_GENOFFICE_SOLO_FOUNDER_KEY_ID",
            "SUITE_GENOFFICE_SOLO_FOUNDER_PUBLIC_KEY_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH",
        ),
    )
    policy = build_genoffice_solo_founder_policy(
        policy_id=values["SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_ID"],
        effective_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_EFFECTIVE_AT_UTC"], field="solo-founder policy time"
        ),
        signer_id=values["SUITE_GENOFFICE_SOLO_FOUNDER_SIGNER_ID"],
        key_id=values["SUITE_GENOFFICE_SOLO_FOUNDER_KEY_ID"],
        public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_PUBLIC_KEY_PATH"]),
            label="solo-founder public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        ),
    )
    persist_genoffice_solo_founder_policy(
        policy=policy,
        path=Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH"]),
    )
    return policy


def run_request_from_environment(env: Mapping[str, str]) -> GenOfficeSoloFounderExceptionRequest:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_ID",
            "SUITE_GENOFFICE_SOLO_FOUNDER_ISSUED_AT_UTC",
            "SUITE_GENOFFICE_SOLO_FOUNDER_VALID_UNTIL_UTC",
            "SUITE_GENOFFICE_SOLO_FOUNDER_RISK_ACCEPTANCE_REF",
            "SUITE_GENOFFICE_SOLO_FOUNDER_CHANGE_CONTROL_REF",
            "SUITE_GENOFFICE_SOLO_FOUNDER_REQUEST_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_SIGNATURE_MESSAGE_PATH",
        ),
    )
    request, message = build_genoffice_solo_founder_request(
        dossier=load_genoffice_legal_review_dossier(Path(values["SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH"])),
        notice_report=load_genoffice_third_party_notice_report(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH"])
        ),
        notice_artifact=_read_limited(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH"]), label="third-party notice"
        ),
        policy=load_genoffice_solo_founder_policy(Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH"])),
        exception_id=values["SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_ID"],
        issued_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_SOLO_FOUNDER_ISSUED_AT_UTC"], field="solo-founder issue time"
        ),
        valid_until_utc=_parse_datetime(
            values["SUITE_GENOFFICE_SOLO_FOUNDER_VALID_UNTIL_UTC"], field="solo-founder expiration time"
        ),
        risk_acceptance_ref=values["SUITE_GENOFFICE_SOLO_FOUNDER_RISK_ACCEPTANCE_REF"],
        change_control_ref=values["SUITE_GENOFFICE_SOLO_FOUNDER_CHANGE_CONTROL_REF"],
    )
    persist_genoffice_solo_founder_request(
        request=request,
        message=message,
        request_path=Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_REQUEST_PATH"]),
        message_path=Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_SIGNATURE_MESSAGE_PATH"]),
    )
    return request


def run_verification_from_environment(env: Mapping[str, str]) -> GenOfficeSoloFounderExceptionReport:
    values = _require_environment(
        env,
        (
            "SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH",
            "SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_REQUEST_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_SIGNATURE_RESPONSE_PATH",
            "SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH",
        ),
    )
    report = verify_genoffice_solo_founder_exception(
        dossier=load_genoffice_legal_review_dossier(Path(values["SUITE_GENOFFICE_LEGAL_DOSSIER_REPORT_PATH"])),
        notice_report=load_genoffice_third_party_notice_report(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_REPORT_PATH"])
        ),
        notice_artifact=_read_limited(
            Path(values["SUITE_GENOFFICE_THIRD_PARTY_NOTICE_PATH"]), label="third-party notice"
        ),
        policy=load_genoffice_solo_founder_policy(Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_POLICY_PATH"])),
        request=load_genoffice_solo_founder_request(Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_REQUEST_PATH"])),
        response=load_genoffice_solo_founder_response(
            Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_SIGNATURE_RESPONSE_PATH"])
        ),
        verified_at_utc=datetime.now(UTC),
    )
    persist_genoffice_solo_founder_report(
        report=report,
        path=Path(values["SUITE_GENOFFICE_SOLO_FOUNDER_EXCEPTION_REPORT_PATH"]),
    )
    return report


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_SOLO_FOUNDER_MODE", "").strip()
    try:
        if mode == "schema":
            output_directory = os.environ.get("SUITE_GENOFFICE_SOLO_FOUNDER_SCHEMA_OUTPUT_DIR", "").strip()
            if not output_directory:
                raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder schema output path is required")
            result: BaseModel | dict[str, str] = persist_genoffice_solo_founder_schemas(
                output_directory=Path(output_directory)
            )
        elif mode == "policy":
            result = run_policy_from_environment(os.environ)
        elif mode == "request":
            result = run_request_from_environment(os.environ)
        elif mode == "verify":
            result = run_verification_from_environment(os.environ)
        else:
            raise GenOfficeSoloFounderExceptionError("GenOffice solo-founder execution mode is invalid")
        if isinstance(result, BaseModel):
            print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        else:
            print(json.dumps(result, sort_keys=True))
    except (GenOfficeSoloFounderExceptionError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_SOLO_FOUNDER_REPORT_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
