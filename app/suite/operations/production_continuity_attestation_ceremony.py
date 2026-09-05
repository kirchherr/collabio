from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.operations.backup_failover import BackupFailoverPolicy, load_backup_failover_policy
from suite.operations.production_continuity_attestation import (
    DSSE_PAYLOAD_TYPE,
    MAX_ATTESTATION_PAYLOAD_BYTES,
    REQUIRED_SIGNER_ROLES,
    DSSESignature,
    ProductionContinuityApprovalPrincipals,
    ProductionContinuityAttestationEnvelope,
    ProductionContinuityAttestationStatement,
    ProductionContinuitySignerPolicy,
    SignerRole,
    build_dsse_pae,
    build_dsse_payload,
    build_production_continuity_attestation_envelope_hash,
    build_production_continuity_attestation_statement,
    build_production_continuity_signer_policy_hash,
    verify_production_continuity_attestation,
)
from suite.operations.production_continuity_deployment_gate import (
    ProductionContinuityDeploymentEvidenceBundle,
    build_backup_failover_policy_hash,
    build_production_continuity_evidence_bundle_hash,
)
from suite.storage.source_objects import sha256_bytes

SHA256_PREFIX = "sha256:"
MAX_CEREMONY_FILE_BYTES = 1024 * 1024
MAX_PAE_BYTES = MAX_ATTESTATION_PAYLOAD_BYTES + 256


class StrictCeremonyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if not value.startswith(SHA256_PREFIX) or len(value) != 71:
        raise ValueError("ceremony references must use sha256")
    try:
        bytes.fromhex(value.removeprefix(SHA256_PREFIX))
    except ValueError as exc:
        raise ValueError("ceremony references must use sha256") from exc
    if value != value.lower():
        raise ValueError("ceremony references must use lowercase sha256")
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ceremony timestamps must include a timezone")
    return value.astimezone(UTC)


def _encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_base64(value: str, *, maximum_length: int, expected_length: int | None = None) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("ceremony values must use canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("ceremony values must use canonical base64")
    if len(decoded) > maximum_length:
        raise ValueError("ceremony value exceeds its size limit")
    if expected_length is not None and len(decoded) != expected_length:
        raise ValueError("ceremony value has an invalid length")
    return decoded


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class ProductionContinuitySigningAssignment(StrictCeremonyModel):
    role: SignerRole
    key_id: str
    principal_ref_hash: str
    algorithm: Literal["ed25519"] = "ed25519"

    _validate_hashes = field_validator("key_id", "principal_ref_hash")(_require_sha256)


class ProductionContinuityAttestationSigningRequest(StrictCeremonyModel):
    request_hash: str
    payload_type: Literal["application/vnd.in-toto+json"] = DSSE_PAYLOAD_TYPE
    payload_base64: str = Field(min_length=4, max_length=MAX_ATTESTATION_PAYLOAD_BYTES * 2)
    pre_authentication_encoding_base64: str = Field(min_length=4, max_length=MAX_PAE_BYTES * 2)
    payload_hash: str
    pre_authentication_encoding_hash: str
    evidence_bundle_hash: str
    deployment_ref_hash: str
    backup_policy_schema_version: str
    backup_policy_hash: str
    signer_policy_schema_version: Literal["production_continuity_signer_policy.v1"]
    signer_policy_hash: str
    signing_assignments: tuple[ProductionContinuitySigningAssignment, ...] = Field(min_length=3, max_length=3)
    issued_at_utc: datetime
    valid_until_utc: datetime
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_ingestion_allowed: Literal[False] = False
    signature_creation_performed: Literal[False] = False
    schema_version: Literal["production_continuity_attestation_signing_request.v1"] = (
        "production_continuity_attestation_signing_request.v1"
    )

    _validate_hashes = field_validator(
        "request_hash",
        "payload_hash",
        "pre_authentication_encoding_hash",
        "evidence_bundle_hash",
        "deployment_ref_hash",
        "backup_policy_hash",
        "signer_policy_hash",
    )(_require_sha256)
    _validate_timestamps = field_validator("issued_at_utc", "valid_until_utc")(_aware_utc)

    @model_validator(mode="after")
    def validate_canonical_signing_contract(self) -> Self:
        if self.valid_until_utc <= self.issued_at_utc:
            raise ValueError("ceremony request validity window is invalid")
        roles = tuple(assignment.role for assignment in self.signing_assignments)
        if roles != REQUIRED_SIGNER_ROLES:
            raise ValueError("ceremony request must assign change, security and operations in canonical order")
        if len({assignment.key_id for assignment in self.signing_assignments}) != 3:
            raise ValueError("ceremony request requires three distinct signing keys")
        if len({assignment.principal_ref_hash for assignment in self.signing_assignments}) != 3:
            raise ValueError("ceremony request requires three distinct signing principals")

        payload = _decode_base64(self.payload_base64, maximum_length=MAX_ATTESTATION_PAYLOAD_BYTES)
        pae = _decode_base64(self.pre_authentication_encoding_base64, maximum_length=MAX_PAE_BYTES)
        statement = ProductionContinuityAttestationStatement.model_validate_json(payload)
        if payload != build_dsse_payload(statement):
            raise ValueError("ceremony request payload must use canonical JSON")
        if pae != build_dsse_pae(payload_type=self.payload_type, payload=payload):
            raise ValueError("ceremony request pre-authentication encoding is invalid")
        if self.payload_hash != sha256_bytes(payload):
            raise ValueError("ceremony request payload hash is invalid")
        if self.pre_authentication_encoding_hash != sha256_bytes(pae):
            raise ValueError("ceremony request pre-authentication encoding hash is invalid")

        predicate = statement.predicate
        subject_hash = SHA256_PREFIX + statement.subject[0].digest.sha256
        if not all(
            (
                subject_hash == self.evidence_bundle_hash,
                predicate.deployment_ref_hash == self.deployment_ref_hash,
                predicate.backup_policy_schema_version == self.backup_policy_schema_version,
                predicate.backup_policy_hash == self.backup_policy_hash,
                predicate.issued_at_utc == self.issued_at_utc,
            )
        ):
            raise ValueError("ceremony request statement binding is invalid")
        for assignment in self.signing_assignments:
            if assignment.principal_ref_hash != predicate.approval_principals.for_role(assignment.role):
                raise ValueError("ceremony request signer assignment does not match approval evidence")
        return self


class ProductionContinuityExternalSignatureResponse(StrictCeremonyModel):
    request_hash: str
    role: SignerRole
    key_id: str
    signature_base64: str = Field(min_length=88, max_length=88)
    algorithm: Literal["ed25519"] = "ed25519"
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    private_key_included: Literal[False] = False
    schema_version: Literal["production_continuity_external_signature_response.v1"] = (
        "production_continuity_external_signature_response.v1"
    )

    _validate_hashes = field_validator("request_hash", "key_id")(_require_sha256)

    @field_validator("signature_base64")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        _decode_base64(value, maximum_length=64, expected_length=64)
        return value


def build_production_continuity_attestation_signing_request_hash(
    request: ProductionContinuityAttestationSigningRequest,
) -> str:
    return sha256_bytes(_canonical_json_bytes(request.model_dump(mode="json", exclude={"request_hash"})))


def _approval_principals(
    bundle: ProductionContinuityDeploymentEvidenceBundle,
) -> ProductionContinuityApprovalPrincipals:
    return ProductionContinuityApprovalPrincipals(
        change=bundle.approvals.change_approver_principal_hash,
        security=bundle.approvals.security_approver_principal_hash,
        operations=bundle.approvals.operations_approver_principal_hash,
    )


def _evidence_observation_times(
    bundle: ProductionContinuityDeploymentEvidenceBundle,
) -> tuple[datetime, ...]:
    return (
        bundle.postgres_pitr.observed_at_utc,
        bundle.encrypted_offsite_backup.observed_at_utc,
        bundle.ha_promotion.observed_at_utc,
        bundle.cross_site_failover.observed_at_utc,
        bundle.approvals.reviewed_at_utc,
    )


def _validate_evidence_request_boundary(
    *,
    policy: BackupFailoverPolicy,
    bundle: ProductionContinuityDeploymentEvidenceBundle,
    issued_at: datetime,
) -> datetime:
    if bundle.backup_policy_schema_version != policy.schema_version:
        raise ValueError("ceremony evidence does not reference the current backup policy")
    deployment_refs = (
        bundle.postgres_pitr.deployment_ref_hash,
        bundle.encrypted_offsite_backup.deployment_ref_hash,
        bundle.ha_promotion.deployment_ref_hash,
        bundle.cross_site_failover.deployment_ref_hash,
        bundle.approvals.deployment_ref_hash,
    )
    if any(reference != bundle.deployment_ref_hash for reference in deployment_refs):
        raise ValueError("ceremony evidence is not bound to one deployment")
    maximum_age = timedelta(hours=policy.production_deployment_gate.maximum_evidence_age_hours)
    observed_at = tuple(_aware_utc(value) for value in _evidence_observation_times(bundle))
    if not all(issued_at - maximum_age <= value <= issued_at for value in observed_at):
        raise ValueError("ceremony evidence is stale or future dated")
    return min(observed_at) + maximum_age


def build_production_continuity_attestation_signing_request(
    *,
    policy: BackupFailoverPolicy,
    bundle: ProductionContinuityDeploymentEvidenceBundle,
    signer_policy: ProductionContinuitySignerPolicy,
    selected_key_ids: tuple[str, ...],
    issued_at: datetime,
) -> ProductionContinuityAttestationSigningRequest:
    issued = _aware_utc(issued_at)
    valid_until = _validate_evidence_request_boundary(policy=policy, bundle=bundle, issued_at=issued)
    if len(selected_key_ids) != 3 or len(set(selected_key_ids)) != 3:
        raise ValueError("ceremony requires exactly three distinct selected key ids")

    principals = _approval_principals(bundle)
    selected_signers = []
    for key_id in selected_key_ids:
        signer = signer_policy.signer(key_id)
        if signer is None:
            raise ValueError("ceremony selected an unknown signer")
        if signer.revoked or not signer.valid_from_utc <= issued <= signer.valid_until_utc:
            raise ValueError("ceremony selected a revoked or inactive signer")
        if signer.principal_ref_hash != principals.for_role(signer.role):
            raise ValueError("ceremony signer does not match the evidence approval principal")
        selected_signers.append(signer)
    signers_by_role = {signer.role: signer for signer in selected_signers}
    if set(signers_by_role) != set(REQUIRED_SIGNER_ROLES):
        raise ValueError("ceremony requires one signer for each required role")

    evidence_hash = build_production_continuity_evidence_bundle_hash(bundle)
    valid_until = min(valid_until, *(signer.valid_until_utc for signer in selected_signers))
    if valid_until <= issued:
        raise ValueError("ceremony signer validity does not cover the request window")
    policy_hash = build_backup_failover_policy_hash(policy)
    statement = build_production_continuity_attestation_statement(
        evidence_bundle_hash=evidence_hash,
        deployment_ref_hash=bundle.deployment_ref_hash,
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=policy_hash,
        approval_principals=principals,
        issued_at=issued,
    )
    payload = build_dsse_payload(statement)
    pae = build_dsse_pae(payload_type=DSSE_PAYLOAD_TYPE, payload=payload)
    assignments = tuple(
        ProductionContinuitySigningAssignment(
            role=role,
            key_id=signers_by_role[role].key_id,
            principal_ref_hash=signers_by_role[role].principal_ref_hash,
        )
        for role in REQUIRED_SIGNER_ROLES
    )
    draft = ProductionContinuityAttestationSigningRequest(
        request_hash=SHA256_PREFIX + "0" * 64,
        payload_base64=_encode_base64(payload),
        pre_authentication_encoding_base64=_encode_base64(pae),
        payload_hash=sha256_bytes(payload),
        pre_authentication_encoding_hash=sha256_bytes(pae),
        evidence_bundle_hash=evidence_hash,
        deployment_ref_hash=bundle.deployment_ref_hash,
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=policy_hash,
        signer_policy_schema_version=signer_policy.schema_version,
        signer_policy_hash=build_production_continuity_signer_policy_hash(signer_policy),
        signing_assignments=assignments,
        issued_at_utc=issued,
        valid_until_utc=valid_until,
    )
    return draft.model_copy(
        update={"request_hash": build_production_continuity_attestation_signing_request_hash(draft)}
    )


def assemble_production_continuity_attestation_envelope(
    *,
    policy: BackupFailoverPolicy,
    bundle: ProductionContinuityDeploymentEvidenceBundle,
    signer_policy: ProductionContinuitySignerPolicy,
    request: ProductionContinuityAttestationSigningRequest,
    signature_responses: tuple[ProductionContinuityExternalSignatureResponse, ...],
    checked_at: datetime,
) -> ProductionContinuityAttestationEnvelope:
    checked = _aware_utc(checked_at)
    if build_production_continuity_attestation_signing_request_hash(request) != request.request_hash:
        raise ValueError("ceremony signing request hash is invalid")
    expected_request = build_production_continuity_attestation_signing_request(
        policy=policy,
        bundle=bundle,
        signer_policy=signer_policy,
        selected_key_ids=tuple(assignment.key_id for assignment in request.signing_assignments),
        issued_at=request.issued_at_utc,
    )
    if expected_request != request:
        raise ValueError("ceremony signing request no longer matches evidence or policy")
    if not request.issued_at_utc <= checked <= request.valid_until_utc:
        raise ValueError("ceremony signing request is not currently valid")
    if len(signature_responses) != 3:
        raise ValueError("ceremony requires exactly three signature responses")

    responses_by_role = {response.role: response for response in signature_responses}
    if len(responses_by_role) != 3:
        raise ValueError("ceremony signature response roles must be distinct")
    signatures: list[DSSESignature] = []
    for assignment in request.signing_assignments:
        response = responses_by_role.get(assignment.role)
        if response is None:
            raise ValueError("ceremony signature response role is missing")
        if response.request_hash != request.request_hash or response.key_id != assignment.key_id:
            raise ValueError("ceremony signature response is not bound to its assignment")
        signatures.append(DSSESignature(keyid=response.key_id, sig=response.signature_base64))

    envelope = ProductionContinuityAttestationEnvelope(
        payload=request.payload_base64,
        signatures=tuple(signatures),
    )
    verification = verify_production_continuity_attestation(
        envelope=envelope,
        signer_policy=signer_policy,
        expected_evidence_bundle_hash=request.evidence_bundle_hash,
        expected_deployment_ref_hash=request.deployment_ref_hash,
        expected_backup_policy_schema_version=request.backup_policy_schema_version,
        expected_backup_policy_hash=request.backup_policy_hash,
        checked_at=checked,
        maximum_age_hours=policy.production_deployment_gate.maximum_evidence_age_hours,
        expected_approval_principals=_approval_principals(bundle),
    )
    if not verification.verified:
        raise ValueError("ceremony external signatures could not be verified")
    return envelope


def _read_bounded(path: Path) -> bytes:
    if path.stat().st_size > MAX_CEREMONY_FILE_BYTES:
        raise ValueError("ceremony input exceeds its size limit")
    value = path.read_bytes()
    if len(value) > MAX_CEREMONY_FILE_BYTES:
        raise ValueError("ceremony input exceeds its size limit")
    return value


def load_production_continuity_attestation_signing_request(
    path: Path,
) -> ProductionContinuityAttestationSigningRequest:
    request = ProductionContinuityAttestationSigningRequest.model_validate_json(_read_bounded(path))
    if build_production_continuity_attestation_signing_request_hash(request) != request.request_hash:
        raise ValueError("persisted ceremony signing request hash is invalid")
    return request


def load_production_continuity_external_signature_response(
    path: Path,
) -> ProductionContinuityExternalSignatureResponse:
    return ProductionContinuityExternalSignatureResponse.model_validate_json(_read_bounded(path))


def persist_production_continuity_ceremony_artifact(*, artifact: BaseModel, path: Path) -> None:
    if not path.parent.is_dir():
        raise ValueError("ceremony output directory must already exist")
    payload = _canonical_json_bytes(artifact.model_dump(mode="json")) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def _load_inputs(
    *,
    policy_path: Path,
    evidence_path: Path,
    signer_policy_path: Path,
) -> tuple[BackupFailoverPolicy, ProductionContinuityDeploymentEvidenceBundle, ProductionContinuitySignerPolicy]:
    policy = load_backup_failover_policy(policy_path)
    bundle = ProductionContinuityDeploymentEvidenceBundle.model_validate_json(_read_bounded(evidence_path))
    signer_policy = ProductionContinuitySignerPolicy.model_validate_json(_read_bounded(signer_policy_path))
    return policy, bundle, signer_policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or assemble a private-key-free continuity attestation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create canonical bytes for three external signers")
    prepare.add_argument("--policy", type=Path, required=True)
    prepare.add_argument("--evidence", type=Path, required=True)
    prepare.add_argument("--signer-policy", type=Path, required=True)
    prepare.add_argument("--key-id", action="append", required=True)
    prepare.add_argument("--output", type=Path, required=True)

    assemble = subparsers.add_parser("assemble", help="Verify three external signatures and emit a DSSE envelope")
    assemble.add_argument("--policy", type=Path, required=True)
    assemble.add_argument("--evidence", type=Path, required=True)
    assemble.add_argument("--signer-policy", type=Path, required=True)
    assemble.add_argument("--request", type=Path, required=True)
    assemble.add_argument("--signature", type=Path, action="append", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        policy, bundle, signer_policy = _load_inputs(
            policy_path=args.policy,
            evidence_path=args.evidence,
            signer_policy_path=args.signer_policy,
        )
        if args.command == "prepare":
            request = build_production_continuity_attestation_signing_request(
                policy=policy,
                bundle=bundle,
                signer_policy=signer_policy,
                selected_key_ids=tuple(args.key_id),
                issued_at=datetime.now(UTC),
            )
            persist_production_continuity_ceremony_artifact(artifact=request, path=args.output)
            result = {
                "schema_version": "production_continuity_attestation_ceremony_prepare_receipt.v1",
                "request_hash": request.request_hash,
                "signature_count_required": 3,
                "private_key_ingestion_allowed": False,
                "signature_creation_performed": False,
                "content_included": False,
                "secrets_included": False,
            }
        else:
            request = load_production_continuity_attestation_signing_request(args.request)
            responses = tuple(load_production_continuity_external_signature_response(path) for path in args.signature)
            envelope = assemble_production_continuity_attestation_envelope(
                policy=policy,
                bundle=bundle,
                signer_policy=signer_policy,
                request=request,
                signature_responses=responses,
                checked_at=datetime.now(UTC),
            )
            persist_production_continuity_ceremony_artifact(artifact=envelope, path=args.output)
            result = {
                "schema_version": "production_continuity_attestation_ceremony_assemble_receipt.v1",
                "attestation_envelope_hash": build_production_continuity_attestation_envelope_hash(envelope),
                "signature_count_verified": 3,
                "private_key_ingestion_allowed": False,
                "content_included": False,
                "secrets_included": False,
            }
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "schema_version": "production_continuity_attestation_ceremony_error.v1",
                    "ceremony_ready": False,
                    "blocking_reasons": ["production_continuity_attestation_ceremony_input_invalid"],
                    "private_key_ingestion_allowed": False,
                    "content_included": False,
                    "secrets_included": False,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
