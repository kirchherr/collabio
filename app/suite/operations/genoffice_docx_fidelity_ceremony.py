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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.signatures import DEFAULT_DETACHED_SIGNATURE_VERIFIER, DetachedSignatureVerifier
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_ENGINE_IDS,
    PUBLIC_KEY_SIZE_BYTES,
    SIGNATURE_SIZE_BYTES,
    EngineId,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSigner,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityStudyPlan,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_payload_hash,
    build_genoffice_docx_fidelity_result_signer_policy_hash,
    build_genoffice_docx_fidelity_signed_result_envelope_hash,
    verify_genoffice_docx_fidelity_signed_result,
)

ZERO_HASH = "sha256:" + "0" * 64
MAX_INPUT_SIZE_BYTES = 2 * 1024 * 1024
MAX_SIGNING_REQUEST_VALIDITY = timedelta(hours=72)


class GenOfficeDocxFidelityCeremonyError(ValueError):
    pass


class GenOfficeDocxFidelitySigningAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signer_id: str
    key_id: str
    engine_id: EngineId
    algorithm: Literal["ed25519"] = "ed25519"

    @model_validator(mode="after")
    def require_identity(self) -> GenOfficeDocxFidelitySigningAssignment:
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice fidelity signing assignment identity is empty")
        return self


class GenOfficeDocxFidelitySigningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_signing_request.v1"] = "genoffice_docx_fidelity_signing_request.v1"
    prepared_at_utc: datetime
    valid_until_utc: datetime
    signer_policy_hash: str
    study_plan_hash: str
    payload: GenOfficeDocxFidelityEngineResultPayload
    signature_message_sha256: str
    signature_message_size_bytes: int = Field(ge=1)
    signing_assignment: GenOfficeDocxFidelitySigningAssignment
    result_accepted: Literal[False] = False
    evidence_verified: Literal[False] = False
    compatibility_claim_allowed: Literal[False] = False
    document_content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    request_hash: str

    @field_validator("prepared_at_utc", "valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GenOffice fidelity signing request time lacks a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_closed_request(self) -> GenOfficeDocxFidelitySigningRequest:
        if not (self.prepared_at_utc < self.valid_until_utc <= self.prepared_at_utc + MAX_SIGNING_REQUEST_VALIDITY):
            raise ValueError("GenOffice fidelity signing request validity window is invalid")
        if self.payload.completed_at_utc > self.prepared_at_utc:
            raise ValueError("GenOffice fidelity result completed after signing request preparation")
        if self.signing_assignment.engine_id != self.payload.engine_id:
            raise ValueError("GenOffice fidelity signing assignment engine drifted")
        for value, field in (
            (self.signer_policy_hash, "signer-policy hash"),
            (self.study_plan_hash, "study-plan hash"),
            (self.signature_message_sha256, "signature-message hash"),
            (self.request_hash, "signing-request hash"),
        ):
            _require_sha256(value, field=field)
        return self


class GenOfficeDocxFidelityExternalSignatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["genoffice_docx_fidelity_external_signature_response.v1"] = (
        "genoffice_docx_fidelity_external_signature_response.v1"
    )
    request_hash: str
    signature_message_sha256: str
    signer_id: str
    key_id: str
    engine_id: EngineId
    algorithm: Literal["ed25519"] = "ed25519"
    signature_base64: str
    document_content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False

    @model_validator(mode="after")
    def require_bound_response(self) -> GenOfficeDocxFidelityExternalSignatureResponse:
        _require_sha256(self.request_hash, field="signing-request hash")
        _require_sha256(self.signature_message_sha256, field="signature-message hash")
        if not self.signer_id.strip() or not self.key_id.strip():
            raise ValueError("GenOffice fidelity external signature identity is empty")
        _decode_canonical_base64(
            self.signature_base64,
            field="external signature",
            expected_size=SIGNATURE_SIZE_BYTES,
        )
        return self


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 71 or not value.startswith("sha256:"):
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} is invalid")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} is invalid") from exc


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _json_bytes(value: BaseModel | Mapping[str, object]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _decode_canonical_base64(value: str, *, field: str, expected_size: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} is not canonical base64") from exc
    if len(decoded) != expected_size or base64.b64encode(decoded).decode("ascii") != value:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} has an invalid size or encoding")
    return decoded


def _read_limited(path: Path, *, field: str, expected_size: int | None = None) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        content = path.read_bytes()
    except OSError as exc:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} cannot be read") from exc
    if len(content) > MAX_INPUT_SIZE_BYTES:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} exceeds its size limit")
    if expected_size is not None and len(content) != expected_size:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} has an invalid size")
    return content


def _write_new_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity output already exists: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor: int | None = None
    temporary_created = False
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise GenOfficeDocxFidelityCeremonyError(
            f"GenOffice fidelity output or temporary file already exists: {path.name}"
        ) from exc
    except OSError as exc:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity output cannot be persisted: {path.name}") from exc
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
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity {field} lacks a timezone")
    return parsed.astimezone(UTC)


def build_genoffice_docx_fidelity_signer_policy(
    *,
    policy_id: str,
    effective_at_utc: datetime,
    microsoft_word_signer_id: str,
    microsoft_word_key_id: str,
    microsoft_word_public_key: bytes,
    libreoffice_signer_id: str,
    libreoffice_key_id: str,
    libreoffice_public_key: bytes,
    genoffice_signer_id: str,
    genoffice_key_id: str,
    genoffice_public_key: bytes,
) -> GenOfficeDocxFidelityResultSignerPolicy:
    identities = (
        microsoft_word_signer_id.strip(),
        libreoffice_signer_id.strip(),
        genoffice_signer_id.strip(),
    )
    key_ids = (microsoft_word_key_id.strip(), libreoffice_key_id.strip(), genoffice_key_id.strip())
    public_keys = (microsoft_word_public_key, libreoffice_public_key, genoffice_public_key)
    if not policy_id.strip() or not all(identities) or not all(key_ids):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer-policy identity is empty")
    if len(set(identities)) != 3 or len(set(key_ids)) != 3 or len(set(public_keys)) != 3:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer-policy identities or keys are not distinct")
    if any(len(item) != PUBLIC_KEY_SIZE_BYTES for item in public_keys):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity public key has an invalid size")
    signers = tuple(
        GenOfficeDocxFidelityResultSigner(
            signer_id=identities[index],
            key_id=key_ids[index],
            engine_id=engine_id,
            ed25519_public_key_base64=base64.b64encode(public_keys[index]).decode("ascii"),
        )
        for index, engine_id in enumerate(FIDELITY_ENGINE_IDS)
    )
    draft = GenOfficeDocxFidelityResultSignerPolicy(
        policy_id=policy_id.strip(),
        effective_at_utc=effective_at_utc,
        signers=signers,
        policy_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"policy_hash": build_genoffice_docx_fidelity_result_signer_policy_hash(draft)})


def _active_signer(
    policy: GenOfficeDocxFidelityResultSignerPolicy, engine_id: EngineId
) -> GenOfficeDocxFidelityResultSigner:
    signers = tuple(item for item in policy.signers if item.active and item.engine_id == engine_id)
    if len(signers) != 1:
        raise GenOfficeDocxFidelityCeremonyError(
            "GenOffice fidelity signer policy requires exactly one active signer for the result engine"
        )
    return signers[0]


def _verify_payload_bindings(
    *, payload: GenOfficeDocxFidelityEngineResultPayload, study_plan: GenOfficeDocxFidelityStudyPlan
) -> None:
    if stable_hash(canonical_json(study_plan.model_dump(mode="json", exclude={"plan_hash"}))) != study_plan.plan_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity study plan hash is invalid")
    if build_genoffice_docx_fidelity_result_payload_hash(payload) != payload.payload_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity result payload hash is invalid")
    assignments = {item.assignment_id: item for item in study_plan.assignments}
    assignment = assignments.get(payload.assignment_id)
    if assignment is None:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity result assignment is unknown")
    if (
        payload.study_plan_hash != study_plan.plan_hash
        or payload.fidelity_policy_hash != study_plan.fidelity_policy_hash
        or payload.engine_id != assignment.engine_id
        or payload.fixture_id != assignment.fixture_id
        or payload.runner_mode != assignment.runner_mode
        or payload.source_content_sha256 != assignment.source_content_sha256
    ):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity result assignment binding drifted")


def build_genoffice_docx_fidelity_signing_request_hash(request: GenOfficeDocxFidelitySigningRequest) -> str:
    return stable_hash(canonical_json(request.model_dump(mode="json", exclude={"request_hash"})))


def build_genoffice_docx_fidelity_signing_request(
    *,
    payload: GenOfficeDocxFidelityEngineResultPayload,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    prepared_at_utc: datetime,
    valid_until_utc: datetime,
) -> tuple[GenOfficeDocxFidelitySigningRequest, bytes]:
    _verify_payload_bindings(payload=payload, study_plan=study_plan)
    if build_genoffice_docx_fidelity_result_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer policy hash is invalid")
    if signer_policy.effective_at_utc > payload.completed_at_utc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity result predates its signer policy")
    signer = _active_signer(signer_policy, payload.engine_id)
    message = build_genoffice_docx_fidelity_result_message(payload)
    draft = GenOfficeDocxFidelitySigningRequest(
        prepared_at_utc=prepared_at_utc,
        valid_until_utc=valid_until_utc,
        signer_policy_hash=signer_policy.policy_hash,
        study_plan_hash=study_plan.plan_hash,
        payload=payload,
        signature_message_sha256=_sha256_bytes(message),
        signature_message_size_bytes=len(message),
        signing_assignment=GenOfficeDocxFidelitySigningAssignment(
            signer_id=signer.signer_id,
            key_id=signer.key_id,
            engine_id=signer.engine_id,
        ),
        request_hash=ZERO_HASH,
    )
    request = draft.model_copy(update={"request_hash": build_genoffice_docx_fidelity_signing_request_hash(draft)})
    return request, message


def verify_genoffice_docx_fidelity_signing_request(
    *,
    request: GenOfficeDocxFidelitySigningRequest,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
) -> bytes:
    _verify_payload_bindings(payload=request.payload, study_plan=study_plan)
    if build_genoffice_docx_fidelity_signing_request_hash(request) != request.request_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing request hash is invalid")
    if request.study_plan_hash != study_plan.plan_hash or request.signer_policy_hash != signer_policy.policy_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing request trust binding drifted")
    if build_genoffice_docx_fidelity_result_signer_policy_hash(signer_policy) != signer_policy.policy_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer policy hash is invalid")
    signer = _active_signer(signer_policy, request.payload.engine_id)
    if (
        request.signing_assignment.signer_id != signer.signer_id
        or request.signing_assignment.key_id != signer.key_id
        or request.signing_assignment.engine_id != signer.engine_id
    ):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing assignment drifted")
    message = build_genoffice_docx_fidelity_result_message(request.payload)
    if (
        _sha256_bytes(message) != request.signature_message_sha256
        or len(message) != request.signature_message_size_bytes
    ):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signature-message binding is invalid")
    return message


def assemble_genoffice_docx_fidelity_signed_result(
    *,
    request: GenOfficeDocxFidelitySigningRequest,
    response: GenOfficeDocxFidelityExternalSignatureResponse,
    signer_policy: GenOfficeDocxFidelityResultSignerPolicy,
    study_plan: GenOfficeDocxFidelityStudyPlan,
    assembled_at_utc: datetime,
    verifier: DetachedSignatureVerifier = DEFAULT_DETACHED_SIGNATURE_VERIFIER,
) -> GenOfficeDocxFidelitySignedResultEnvelope:
    message = verify_genoffice_docx_fidelity_signing_request(
        request=request,
        signer_policy=signer_policy,
        study_plan=study_plan,
    )
    if assembled_at_utc.tzinfo is None or assembled_at_utc.utcoffset() is None:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity assembly time lacks a timezone")
    assembled_at = assembled_at_utc.astimezone(UTC)
    if not request.prepared_at_utc <= assembled_at <= request.valid_until_utc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing request is not currently valid")
    assignment = request.signing_assignment
    if (
        response.request_hash != request.request_hash
        or response.signature_message_sha256 != request.signature_message_sha256
    ):
        raise GenOfficeDocxFidelityCeremonyError(
            "GenOffice fidelity external signature response is bound to another request"
        )
    if (
        response.signer_id != assignment.signer_id
        or response.key_id != assignment.key_id
        or response.engine_id != assignment.engine_id
    ):
        raise GenOfficeDocxFidelityCeremonyError(
            "GenOffice fidelity external signature response violates its signing assignment"
        )
    signature = _decode_canonical_base64(
        response.signature_base64,
        field="external signature",
        expected_size=SIGNATURE_SIZE_BYTES,
    )
    signer = _active_signer(signer_policy, request.payload.engine_id)
    public_key = _decode_canonical_base64(
        signer.ed25519_public_key_base64,
        field="signer public key",
        expected_size=PUBLIC_KEY_SIZE_BYTES,
    )
    if not verifier.verify_ed25519(public_key=public_key, signature=signature, message=message):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity external signature is invalid")
    draft = GenOfficeDocxFidelitySignedResultEnvelope(
        signer_policy_hash=signer_policy.policy_hash,
        payload=request.payload,
        signer_id=response.signer_id,
        key_id=response.key_id,
        signature_base64=response.signature_base64,
        envelope_hash=ZERO_HASH,
    )
    envelope = draft.model_copy(
        update={"envelope_hash": build_genoffice_docx_fidelity_signed_result_envelope_hash(draft)}
    )
    verify_genoffice_docx_fidelity_signed_result(
        envelope=envelope,
        signer_policy=signer_policy,
        study_plan=study_plan,
        verifier=verifier,
    )
    return envelope


def persist_genoffice_docx_fidelity_signer_policy(
    *, policy: GenOfficeDocxFidelityResultSignerPolicy, path: Path
) -> None:
    if build_genoffice_docx_fidelity_result_signer_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer policy hash is invalid")
    _write_new_private(path, _json_bytes(policy))


def persist_genoffice_docx_fidelity_signing_request(
    *, request: GenOfficeDocxFidelitySigningRequest, message: bytes, request_path: Path, message_path: Path
) -> None:
    if (
        build_genoffice_docx_fidelity_signing_request_hash(request) != request.request_hash
        or _sha256_bytes(message) != request.signature_message_sha256
        or len(message) != request.signature_message_size_bytes
    ):
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing request persistence binding is invalid")
    _write_new_private(request_path, _json_bytes(request))
    _write_new_private(message_path, message)


def persist_genoffice_docx_fidelity_signed_result(
    *, envelope: GenOfficeDocxFidelitySignedResultEnvelope, path: Path
) -> None:
    if build_genoffice_docx_fidelity_signed_result_envelope_hash(envelope) != envelope.envelope_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signed-result envelope hash is invalid")
    _write_new_private(path, _json_bytes(envelope))


def load_genoffice_docx_fidelity_signer_policy(path: Path) -> GenOfficeDocxFidelityResultSignerPolicy:
    try:
        policy = GenOfficeDocxFidelityResultSignerPolicy.model_validate_json(_read_limited(path, field="signer policy"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer policy is not readable") from exc
    if build_genoffice_docx_fidelity_result_signer_policy_hash(policy) != policy.policy_hash:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signer policy hash is invalid")
    return policy


def load_genoffice_docx_fidelity_study_plan(path: Path) -> GenOfficeDocxFidelityStudyPlan:
    try:
        return GenOfficeDocxFidelityStudyPlan.model_validate_json(_read_limited(path, field="study plan"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity study plan is not readable") from exc


def load_genoffice_docx_fidelity_result_payload(path: Path) -> GenOfficeDocxFidelityEngineResultPayload:
    try:
        return GenOfficeDocxFidelityEngineResultPayload.model_validate_json(_read_limited(path, field="result payload"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity result payload is not readable") from exc


def load_genoffice_docx_fidelity_signing_request(path: Path) -> GenOfficeDocxFidelitySigningRequest:
    try:
        return GenOfficeDocxFidelitySigningRequest.model_validate_json(_read_limited(path, field="signing request"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity signing request is not readable") from exc


def load_genoffice_docx_fidelity_signature_response(
    path: Path,
) -> GenOfficeDocxFidelityExternalSignatureResponse:
    try:
        return GenOfficeDocxFidelityExternalSignatureResponse.model_validate_json(
            _read_limited(path, field="external signature response")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GenOfficeDocxFidelityCeremonyError(
            "GenOffice fidelity external signature response is not readable"
        ) from exc


def persist_genoffice_docx_fidelity_ceremony_schemas(output_directory: Path) -> dict[str, str]:
    schemas: tuple[tuple[str, type[BaseModel]], ...] = (
        ("genoffice-docx-fidelity-signing-request.schema.json", GenOfficeDocxFidelitySigningRequest),
        (
            "genoffice-docx-fidelity-external-signature-response.schema.json",
            GenOfficeDocxFidelityExternalSignatureResponse,
        ),
    )
    hashes: dict[str, str] = {}
    for filename, model in schemas:
        content = _json_bytes(model.model_json_schema())
        _write_new_private(output_directory / filename, content)
        hashes[filename] = _sha256_bytes(content)
    return hashes


def _required_environment(env: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    values = {name: env.get(name, "").strip() for name in names}
    missing = tuple(sorted(name for name, value in values.items() if not value))
    if missing:
        raise GenOfficeDocxFidelityCeremonyError(f"GenOffice fidelity ceremony values are missing: {missing}")
    return values


def run_genoffice_docx_fidelity_policy_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDocxFidelityResultSignerPolicy:
    names = (
        "SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_ID",
        "SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_EFFECTIVE_AT_UTC",
        "SUITE_GENOFFICE_FIDELITY_WORD_SIGNER_ID",
        "SUITE_GENOFFICE_FIDELITY_WORD_KEY_ID",
        "SUITE_GENOFFICE_FIDELITY_WORD_PUBLIC_KEY_PATH",
        "SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_SIGNER_ID",
        "SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_KEY_ID",
        "SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_PUBLIC_KEY_PATH",
        "SUITE_GENOFFICE_FIDELITY_GENOFFICE_SIGNER_ID",
        "SUITE_GENOFFICE_FIDELITY_GENOFFICE_KEY_ID",
        "SUITE_GENOFFICE_FIDELITY_GENOFFICE_PUBLIC_KEY_PATH",
        "SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH",
    )
    values = _required_environment(env, names)
    policy = build_genoffice_docx_fidelity_signer_policy(
        policy_id=values["SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_ID"],
        effective_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_EFFECTIVE_AT_UTC"], field="policy effective time"
        ),
        microsoft_word_signer_id=values["SUITE_GENOFFICE_FIDELITY_WORD_SIGNER_ID"],
        microsoft_word_key_id=values["SUITE_GENOFFICE_FIDELITY_WORD_KEY_ID"],
        microsoft_word_public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_FIDELITY_WORD_PUBLIC_KEY_PATH"]),
            field="Word public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        ),
        libreoffice_signer_id=values["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_SIGNER_ID"],
        libreoffice_key_id=values["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_KEY_ID"],
        libreoffice_public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_FIDELITY_LIBREOFFICE_PUBLIC_KEY_PATH"]),
            field="LibreOffice public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        ),
        genoffice_signer_id=values["SUITE_GENOFFICE_FIDELITY_GENOFFICE_SIGNER_ID"],
        genoffice_key_id=values["SUITE_GENOFFICE_FIDELITY_GENOFFICE_KEY_ID"],
        genoffice_public_key=_read_limited(
            Path(values["SUITE_GENOFFICE_FIDELITY_GENOFFICE_PUBLIC_KEY_PATH"]),
            field="GenOffice public key",
            expected_size=PUBLIC_KEY_SIZE_BYTES,
        ),
    )
    persist_genoffice_docx_fidelity_signer_policy(
        policy=policy,
        path=Path(values["SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH"]),
    )
    return policy


def run_genoffice_docx_fidelity_request_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDocxFidelitySigningRequest:
    values = _required_environment(
        env,
        (
            "SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_FIDELITY_STUDY_PLAN_PATH",
            "SUITE_GENOFFICE_FIDELITY_RESULT_PAYLOAD_PATH",
            "SUITE_GENOFFICE_FIDELITY_PREPARED_AT_UTC",
            "SUITE_GENOFFICE_FIDELITY_VALID_UNTIL_UTC",
            "SUITE_GENOFFICE_FIDELITY_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_FIDELITY_SIGNATURE_MESSAGE_PATH",
        ),
    )
    request, message = build_genoffice_docx_fidelity_signing_request(
        payload=load_genoffice_docx_fidelity_result_payload(
            Path(values["SUITE_GENOFFICE_FIDELITY_RESULT_PAYLOAD_PATH"])
        ),
        signer_policy=load_genoffice_docx_fidelity_signer_policy(
            Path(values["SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH"])
        ),
        study_plan=load_genoffice_docx_fidelity_study_plan(Path(values["SUITE_GENOFFICE_FIDELITY_STUDY_PLAN_PATH"])),
        prepared_at_utc=_parse_datetime(
            values["SUITE_GENOFFICE_FIDELITY_PREPARED_AT_UTC"], field="request preparation time"
        ),
        valid_until_utc=_parse_datetime(
            values["SUITE_GENOFFICE_FIDELITY_VALID_UNTIL_UTC"], field="request expiration time"
        ),
    )
    persist_genoffice_docx_fidelity_signing_request(
        request=request,
        message=message,
        request_path=Path(values["SUITE_GENOFFICE_FIDELITY_SIGNING_REQUEST_PATH"]),
        message_path=Path(values["SUITE_GENOFFICE_FIDELITY_SIGNATURE_MESSAGE_PATH"]),
    )
    return request


def run_genoffice_docx_fidelity_assembly_from_environment(
    env: Mapping[str, str],
) -> GenOfficeDocxFidelitySignedResultEnvelope:
    values = _required_environment(
        env,
        (
            "SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH",
            "SUITE_GENOFFICE_FIDELITY_STUDY_PLAN_PATH",
            "SUITE_GENOFFICE_FIDELITY_SIGNING_REQUEST_PATH",
            "SUITE_GENOFFICE_FIDELITY_SIGNATURE_RESPONSE_PATH",
            "SUITE_GENOFFICE_FIDELITY_SIGNED_RESULT_PATH",
        ),
    )
    envelope = assemble_genoffice_docx_fidelity_signed_result(
        request=load_genoffice_docx_fidelity_signing_request(
            Path(values["SUITE_GENOFFICE_FIDELITY_SIGNING_REQUEST_PATH"])
        ),
        response=load_genoffice_docx_fidelity_signature_response(
            Path(values["SUITE_GENOFFICE_FIDELITY_SIGNATURE_RESPONSE_PATH"])
        ),
        signer_policy=load_genoffice_docx_fidelity_signer_policy(
            Path(values["SUITE_GENOFFICE_FIDELITY_SIGNER_POLICY_PATH"])
        ),
        study_plan=load_genoffice_docx_fidelity_study_plan(Path(values["SUITE_GENOFFICE_FIDELITY_STUDY_PLAN_PATH"])),
        assembled_at_utc=datetime.now(UTC),
    )
    persist_genoffice_docx_fidelity_signed_result(
        envelope=envelope,
        path=Path(values["SUITE_GENOFFICE_FIDELITY_SIGNED_RESULT_PATH"]),
    )
    return envelope


def main() -> None:
    mode = os.environ.get("SUITE_GENOFFICE_FIDELITY_CEREMONY_MODE", "").strip()
    try:
        if mode == "schema":
            output = _required_environment(os.environ, ("SUITE_GENOFFICE_FIDELITY_CEREMONY_OUTPUT_DIR",))
            result: BaseModel | Mapping[str, object] = persist_genoffice_docx_fidelity_ceremony_schemas(
                Path(output["SUITE_GENOFFICE_FIDELITY_CEREMONY_OUTPUT_DIR"])
            )
        elif mode == "policy":
            result = run_genoffice_docx_fidelity_policy_from_environment(os.environ)
        elif mode == "request":
            result = run_genoffice_docx_fidelity_request_from_environment(os.environ)
        elif mode == "assemble":
            result = run_genoffice_docx_fidelity_assembly_from_environment(os.environ)
        else:
            raise GenOfficeDocxFidelityCeremonyError("GenOffice fidelity ceremony mode is invalid")
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        print(json.dumps(payload, sort_keys=True))
    except (GenOfficeDocxFidelityCeremonyError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "schema_version": "genoffice_docx_fidelity_ceremony_error.v1"}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
