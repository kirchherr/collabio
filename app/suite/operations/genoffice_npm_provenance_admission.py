from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.kms.x509_evidence import X509EvidenceError, inspect_der_x509_certificate
from suite.operations.genoffice_vendored_provenance_admission import (
    EMF_CONVERTER_NAME,
    EMF_CONVERTER_PURL,
    EMF_CONVERTER_TARBALL_SRI,
    EMF_CONVERTER_VERSION,
    GenOfficeVendoredProvenanceError,
    load_genoffice_vendored_provenance_report,
)

GENOFFICE_NPM_PROVENANCE_ADMISSION_SCHEMA_VERSION = "genoffice_npm_provenance_admission_report.v1"
GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH = (
    "sha256:5ac1fdfa83034db3a8da06985b5f96e87a8eb0acfe3614f05b4fb3afe8e3dd04"
)
NPM_VERIFIER_IMAGE_REF = (
    "node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d"
)
NPM_VERIFIER_NODE_VERSION = "v24.18.0"
NPM_VERIFIER_VERSION = "11.16.0"
NPM_VERIFICATION_REPORT_HASH = "sha256:f86895f2045f6c9916e04cd43ef46afd5f0741e68c99bc62c4da89fa5b651434"
NPM_VERIFICATION_RECEIPT_HASH = "sha256:b381680a2a6e86d4a23acb1903d2efb3ac9c2d2e4e1f2dbce8d001daebdfa1a1"
FULCIO_CERTIFICATE_SHA256 = "sha256:b26c2c25ff00d5cfd69b3156d66b84e4d13a88e28522227386486405948506d4"
EMF_CONVERTER_TARBALL_SHA512 = (
    "40b52e7dbe393f72e53ae742a22cc1b49a4ef1c070f0b6b21f49a4be446f223b"
    "cc95bea3ba7c0fd045e0524743c9950417641211950f57cacef034b9aec26690"
)
NPM_REGISTRY = "https://registry.npmjs.org/"
NPM_ATTESTATION_URL = "https://registry.npmjs.org/-/npm/v1/attestations/emf-converter@2.0.2"
PUBLISH_PREDICATE_TYPE = "https://github.com/npm/attestation/tree/main/specs/publish/v0.1"
SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
SLSA_BUILD_TYPE = "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1"
SLSA_BUILDER_ID = "https://github.com/actions/runner/github-hosted"
SOURCE_REPOSITORY_URI = "https://github.com/ChristopherVR/emf-converter"
SOURCE_REPOSITORY_ID = "1272919023"
SOURCE_REPOSITORY_OWNER_ID = "28136629"
SOURCE_COMMIT = "9aca5abf16662f93a453a07378768ddd87a8541d"
SOURCE_REF = "refs/heads/main"
WORKFLOW_PATH = ".github/workflows/publish.yml"
WORKFLOW_URI = "https://github.com/ChristopherVR/emf-converter/.github/workflows/publish.yml@refs/heads/main"
INVOCATION_URI = "https://github.com/ChristopherVR/emf-converter/actions/runs/30234322001/attempts/1"
REKOR_LOG_ID = "wNI9atQGlz+VWfO6LRygH4QUfY/8W4RFwiT5i5WRgB0="
MAX_EVIDENCE_SIZE_BYTES = 1024 * 1024
MAX_PAYLOAD_SIZE_BYTES = 256 * 1024

_CERTIFICATE_EXTENSIONS = {
    "1.3.6.1.4.1.57264.1.8": "https://token.actions.githubusercontent.com",
    "1.3.6.1.4.1.57264.1.9": WORKFLOW_URI,
    "1.3.6.1.4.1.57264.1.10": SOURCE_COMMIT,
    "1.3.6.1.4.1.57264.1.11": "github-hosted",
    "1.3.6.1.4.1.57264.1.12": SOURCE_REPOSITORY_URI,
    "1.3.6.1.4.1.57264.1.13": SOURCE_COMMIT,
    "1.3.6.1.4.1.57264.1.14": SOURCE_REF,
    "1.3.6.1.4.1.57264.1.15": SOURCE_REPOSITORY_ID,
    "1.3.6.1.4.1.57264.1.17": SOURCE_REPOSITORY_OWNER_ID,
    "1.3.6.1.4.1.57264.1.18": WORKFLOW_URI,
    "1.3.6.1.4.1.57264.1.19": SOURCE_COMMIT,
    "1.3.6.1.4.1.57264.1.20": "push",
    "1.3.6.1.4.1.57264.1.21": INVOCATION_URI,
    "1.3.6.1.4.1.57264.1.22": "public",
    "1.3.6.1.4.1.57264.1.23": "npm",
    "1.3.6.1.4.1.57264.1.24": "repo:ChristopherVR/emf-converter:environment:npm",
}


class GenOfficeNpmProvenanceAdmissionError(ValueError):
    pass


class RekorEntryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicate_type: str
    log_id: str
    log_index: int
    integrated_time: int
    inclusion_promise_present: bool
    inclusion_proof_present: bool


class GenOfficeNpmProvenanceAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["genoffice_npm_provenance_admission_report.v1"] = (
        "genoffice_npm_provenance_admission_report.v1"
    )
    vendored_provenance_report_hash: str
    npm_verification_report_hash: str
    npm_verification_receipt_hash: str
    verifier_image_ref: str
    node_version: str
    npm_version: str
    package_name: str
    package_version: str
    package_purl: str
    package_integrity_sri: str
    package_sha512: str
    registry: str
    package_location: str
    attestation_url: str
    verified_package_count: int
    invalid_package_count: int
    missing_package_count: int
    attestation_predicate_types: tuple[str, ...]
    publish_statement_type: str
    slsa_statement_type: str
    slsa_build_type: str
    slsa_builder_id: str
    source_repository_uri: str
    source_repository_id: str
    source_repository_owner_id: str
    source_commit: str
    source_ref: str
    workflow_path: str
    workflow_uri: str
    invocation_uri: str
    runner_environment: str
    source_repository_visibility: str
    deployment_environment: str
    fulcio_certificate_sha256: str
    fulcio_certificate_issuer_organization: str
    fulcio_certificate_issuer_common_name: str
    fulcio_certificate_serial_hex: str
    fulcio_certificate_not_before_utc: datetime
    fulcio_certificate_not_after_utc: datetime
    rekor_entries: tuple[RekorEntryEvidence, ...]
    registry_signature_verified: bool
    publish_attestation_verified: bool
    slsa_provenance_verified: bool
    certificate_identity_verified: bool
    transparency_log_inclusion_verified: bool
    cryptographic_provenance_gate_passed: bool
    legal_review_complete: bool = False
    reproducible_build_and_provenance_complete: bool = False
    source_import_allowed: bool = False
    engine_execution_allowed: bool = False
    production_use_allowed: bool = False
    remaining_gates: tuple[str, ...] = (
        "human_legal_notice_trademark_and_compound_license_review",
        "reproducible_isolated_build_and_signed_provenance",
        "authoritative_worker_image_sbom_and_vulnerability_review",
        "malicious_ooxml_and_archive_expansion_corpus",
        "word_libreoffice_genoffice_collabio_fidelity_corpus",
        "isolated_engine_worker_and_resource_limits",
        "candidate_revalidation_preview_confirmation_and_receipt",
        "draft_candidate_receipt_backup_restore_and_failover_drill",
    )
    report_hash: str

    @model_validator(mode="after")
    def require_pinned_closed_boundary(self) -> GenOfficeNpmProvenanceAdmissionReport:
        expected = {
            "vendored_provenance_report_hash": GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH,
            "npm_verification_report_hash": NPM_VERIFICATION_REPORT_HASH,
            "npm_verification_receipt_hash": NPM_VERIFICATION_RECEIPT_HASH,
            "verifier_image_ref": NPM_VERIFIER_IMAGE_REF,
            "node_version": NPM_VERIFIER_NODE_VERSION,
            "npm_version": NPM_VERIFIER_VERSION,
            "package_name": EMF_CONVERTER_NAME,
            "package_version": EMF_CONVERTER_VERSION,
            "package_purl": EMF_CONVERTER_PURL,
            "package_integrity_sri": EMF_CONVERTER_TARBALL_SRI,
            "package_sha512": EMF_CONVERTER_TARBALL_SHA512,
            "registry": NPM_REGISTRY,
            "package_location": "node_modules/emf-converter",
            "attestation_url": NPM_ATTESTATION_URL,
            "verified_package_count": 1,
            "invalid_package_count": 0,
            "missing_package_count": 0,
            "publish_statement_type": "https://in-toto.io/Statement/v0.1",
            "slsa_statement_type": "https://in-toto.io/Statement/v1",
            "slsa_build_type": SLSA_BUILD_TYPE,
            "slsa_builder_id": SLSA_BUILDER_ID,
            "source_repository_uri": SOURCE_REPOSITORY_URI,
            "source_repository_id": SOURCE_REPOSITORY_ID,
            "source_repository_owner_id": SOURCE_REPOSITORY_OWNER_ID,
            "source_commit": SOURCE_COMMIT,
            "source_ref": SOURCE_REF,
            "workflow_path": WORKFLOW_PATH,
            "workflow_uri": WORKFLOW_URI,
            "invocation_uri": INVOCATION_URI,
            "runner_environment": "github-hosted",
            "source_repository_visibility": "public",
            "deployment_environment": "npm",
            "fulcio_certificate_sha256": FULCIO_CERTIFICATE_SHA256,
            "fulcio_certificate_issuer_organization": "sigstore.dev",
            "fulcio_certificate_issuer_common_name": "sigstore-intermediate",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"GenOffice npm provenance field {field} is not pinned")
        if self.attestation_predicate_types != tuple(sorted((PUBLISH_PREDICATE_TYPE, SLSA_PREDICATE_TYPE))):
            raise ValueError("GenOffice npm attestation predicates are not the reviewed pair")
        if not all(
            (
                self.registry_signature_verified,
                self.publish_attestation_verified,
                self.slsa_provenance_verified,
                self.certificate_identity_verified,
                self.transparency_log_inclusion_verified,
                self.cryptographic_provenance_gate_passed,
            )
        ):
            raise ValueError("GenOffice npm cryptographic provenance gate is incomplete")
        if any(
            (
                self.legal_review_complete,
                self.reproducible_build_and_provenance_complete,
                self.source_import_allowed,
                self.engine_execution_allowed,
                self.production_use_allowed,
            )
        ):
            raise ValueError("GenOffice npm provenance opened an unreviewed trust or execution boundary")
        return self


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_EVIDENCE_SIZE_BYTES:
                    raise GenOfficeNpmProvenanceAdmissionError("npm provenance evidence exceeds its size limit")
                digest.update(chunk)
    except OSError as exc:
        raise GenOfficeNpmProvenanceAdmissionError("npm provenance evidence cannot be read") from exc
    return f"sha256:{digest.hexdigest()}"


def _json_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("npm provenance evidence is not readable JSON") from exc
    if not isinstance(value, dict):
        raise GenOfficeNpmProvenanceAdmissionError("npm provenance evidence must be a JSON object")
    return value


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise GenOfficeNpmProvenanceAdmissionError(f"{field} must be an object")
    return value


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise GenOfficeNpmProvenanceAdmissionError(f"{field} must be an array")
    return value


def _decode_payload(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, str):
        raise GenOfficeNpmProvenanceAdmissionError("DSSE payload must be base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("DSSE payload is not canonical base64") from exc
    if len(decoded) > MAX_PAYLOAD_SIZE_BYTES:
        raise GenOfficeNpmProvenanceAdmissionError("DSSE payload exceeds its size limit")
    try:
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("DSSE payload is not readable JSON") from exc
    return _mapping(payload, field="DSSE payload")


def _subject(payload: Mapping[str, Any]) -> None:
    expected = [{"name": EMF_CONVERTER_PURL, "digest": {"sha512": EMF_CONVERTER_TARBALL_SHA512}}]
    if payload.get("subject") != expected:
        raise GenOfficeNpmProvenanceAdmissionError("Attestation subject is not the reviewed npm tarball")


def _rekor_entry(bundle: Mapping[str, Any], *, predicate_type: str) -> RekorEntryEvidence:
    material = _mapping(bundle.get("verificationMaterial"), field="Sigstore verification material")
    entries = _list(material.get("tlogEntries"), field="Sigstore transparency log entries")
    if len(entries) != 1:
        raise GenOfficeNpmProvenanceAdmissionError("Attestation must have exactly one transparency log entry")
    entry = _mapping(entries[0], field="Sigstore transparency log entry")
    log_id = _mapping(entry.get("logId"), field="Sigstore log ID").get("keyId")
    inclusion_promise = _mapping(entry.get("inclusionPromise"), field="Sigstore inclusion promise")
    inclusion_proof = _mapping(entry.get("inclusionProof"), field="Sigstore inclusion proof")
    expected = {
        PUBLISH_PREDICATE_TYPE: (2256827554, 1785122374),
        SLSA_PREDICATE_TYPE: (2256827526, 1785122372),
    }[predicate_type]
    raw_log_index = entry.get("logIndex")
    raw_integrated_time = entry.get("integratedTime")
    if (
        isinstance(raw_log_index, bool)
        or not isinstance(raw_log_index, (str, int))
        or isinstance(raw_integrated_time, bool)
        or not isinstance(raw_integrated_time, (str, int))
    ):
        raise GenOfficeNpmProvenanceAdmissionError("Sigstore log position is malformed")
    try:
        log_index = int(raw_log_index)
        integrated_time = int(raw_integrated_time)
    except ValueError as exc:
        raise GenOfficeNpmProvenanceAdmissionError("Sigstore log position is malformed") from exc
    if (log_index, integrated_time) != expected or log_id != REKOR_LOG_ID:
        raise GenOfficeNpmProvenanceAdmissionError("Sigstore transparency log identity changed")
    promise_present = isinstance(inclusion_promise.get("signedEntryTimestamp"), str) and bool(
        inclusion_promise["signedEntryTimestamp"]
    )
    proof_present = isinstance(inclusion_proof.get("rootHash"), str) and isinstance(inclusion_proof.get("hashes"), list)
    if not promise_present or not proof_present:
        raise GenOfficeNpmProvenanceAdmissionError("Sigstore transparency log proof is incomplete")
    return RekorEntryEvidence(
        predicate_type=predicate_type,
        log_id=str(log_id),
        log_index=log_index,
        integrated_time=integrated_time,
        inclusion_promise_present=True,
        inclusion_proof_present=True,
    )


def _der_utf8(value: bytes) -> str:
    if len(value) < 2 or value[0] != 0x0C:
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio extension is not a DER UTF8String")
    length_byte = value[1]
    if length_byte < 0x80:
        offset, length = 2, length_byte
    else:
        length_octets = length_byte & 0x7F
        if length_octets == 0 or length_octets > 4 or len(value) < 2 + length_octets:
            raise GenOfficeNpmProvenanceAdmissionError("Fulcio extension has an invalid DER length")
        offset = 2 + length_octets
        length = int.from_bytes(value[2:offset], "big")
    if offset + length != len(value):
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio extension DER length is inconsistent")
    try:
        return value[offset:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio extension is not valid UTF-8") from exc


def _certificate_identity(bundle: Mapping[str, Any]) -> tuple[str, str, str, str, datetime, datetime]:
    material = _mapping(bundle.get("verificationMaterial"), field="SLSA verification material")
    certificate_value = _mapping(material.get("certificate"), field="Fulcio certificate").get("rawBytes")
    if not isinstance(certificate_value, str):
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio certificate is missing")
    try:
        certificate_der = base64.b64decode(certificate_value, validate=True)
        evidence = inspect_der_x509_certificate(certificate_der)
    except (binascii.Error, X509EvidenceError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio certificate is malformed") from exc
    certificate_hash = evidence.der_sha256
    if certificate_hash != FULCIO_CERTIFICATE_SHA256:
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio certificate is not the reviewed certificate")
    if evidence.uri_subject_alternative_names != (WORKFLOW_URI,):
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio certificate workflow identity changed")
    for oid, expected in _CERTIFICATE_EXTENSIONS.items():
        extension = evidence.unrecognized_extension(oid)
        if extension is None:
            raise GenOfficeNpmProvenanceAdmissionError(f"Fulcio certificate identity extension {oid} is missing")
        if _der_utf8(extension) != expected:
            raise GenOfficeNpmProvenanceAdmissionError(f"Fulcio certificate identity extension {oid} changed")
    if len(evidence.issuer_organizations) != 1 or len(evidence.issuer_common_names) != 1:
        raise GenOfficeNpmProvenanceAdmissionError("Fulcio certificate issuer is incomplete")
    return (
        certificate_hash,
        evidence.issuer_organizations[0],
        evidence.issuer_common_names[0],
        evidence.serial_hex,
        evidence.not_before_utc,
        evidence.not_after_utc,
    )


def _receipt(path: Path) -> tuple[str, str, str, str]:
    receipt_hash = _file_hash(path)
    if receipt_hash != NPM_VERIFICATION_RECEIPT_HASH:
        raise GenOfficeNpmProvenanceAdmissionError("npm verification receipt is not the reviewed receipt")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("npm verification receipt cannot be read") from exc
    entries: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or key in entries:
            raise GenOfficeNpmProvenanceAdmissionError("npm verification receipt is malformed")
        entries[key] = value
    expected = {
        "image": NPM_VERIFIER_IMAGE_REF,
        "node_version": NPM_VERIFIER_NODE_VERSION,
        "npm_version": NPM_VERIFIER_VERSION,
        "status": "verified",
    }
    if entries != expected:
        raise GenOfficeNpmProvenanceAdmissionError("npm verification receipt identity changed")
    return receipt_hash, entries["image"], entries["node_version"], entries["npm_version"]


def build_genoffice_npm_provenance_admission_report(
    *, vendored_provenance_path: Path, npm_verification_path: Path, npm_verification_receipt_path: Path
) -> GenOfficeNpmProvenanceAdmissionReport:
    try:
        vendored = load_genoffice_vendored_provenance_report(vendored_provenance_path)
    except GenOfficeVendoredProvenanceError as exc:
        raise GenOfficeNpmProvenanceAdmissionError("Vendored provenance evidence is invalid") from exc
    if vendored.report_hash != GENOFFICE_REVIEWED_VENDORED_PROVENANCE_REPORT_HASH:
        raise GenOfficeNpmProvenanceAdmissionError("Vendored provenance evidence is not reviewed")
    verification_hash = _file_hash(npm_verification_path)
    if verification_hash != NPM_VERIFICATION_REPORT_HASH:
        raise GenOfficeNpmProvenanceAdmissionError("npm verification output is not the reviewed snapshot")
    receipt_hash, image_ref, node_version, npm_version = _receipt(npm_verification_receipt_path)
    verification = _json_object(npm_verification_path)
    if set(verification) != {"invalid", "missing", "verified"}:
        raise GenOfficeNpmProvenanceAdmissionError("npm verification output has unexpected fields")
    invalid = _list(verification["invalid"], field="npm invalid packages")
    missing = _list(verification["missing"], field="npm missing packages")
    verified = _list(verification["verified"], field="npm verified packages")
    if invalid or missing or len(verified) != 1:
        raise GenOfficeNpmProvenanceAdmissionError("npm did not verify exactly the reviewed package")
    package = _mapping(verified[0], field="npm verified package")
    expected_identity = {
        "name": EMF_CONVERTER_NAME,
        "version": EMF_CONVERTER_VERSION,
        "registry": NPM_REGISTRY,
        "location": "node_modules/emf-converter",
    }
    if any(package.get(field) != value for field, value in expected_identity.items()):
        raise GenOfficeNpmProvenanceAdmissionError("npm verified package identity changed")
    if package.get("attestations") != {
        "url": NPM_ATTESTATION_URL,
        "provenance": {"predicateType": SLSA_PREDICATE_TYPE},
    }:
        raise GenOfficeNpmProvenanceAdmissionError("npm attestation metadata changed")
    raw_bundles = _list(package.get("attestationBundles"), field="npm attestation bundles")
    bundles: dict[str, Mapping[str, Any]] = {}
    payloads: dict[str, Mapping[str, Any]] = {}
    rekor_entries: list[RekorEntryEvidence] = []
    expected_media_types = {
        PUBLISH_PREDICATE_TYPE: "application/vnd.dev.sigstore.bundle+json;version=0.2",
        SLSA_PREDICATE_TYPE: "application/vnd.dev.sigstore.bundle.v0.3+json",
    }
    for raw_bundle in raw_bundles:
        attestation = _mapping(raw_bundle, field="npm attestation bundle")
        predicate_type = attestation.get("predicateType")
        if predicate_type not in expected_media_types or predicate_type in bundles:
            raise GenOfficeNpmProvenanceAdmissionError("npm attestation predicate set changed")
        bundle = _mapping(attestation.get("bundle"), field="Sigstore bundle")
        if bundle.get("mediaType") != expected_media_types[str(predicate_type)]:
            raise GenOfficeNpmProvenanceAdmissionError("Sigstore bundle media type changed")
        envelope = _mapping(bundle.get("dsseEnvelope"), field="DSSE envelope")
        signatures = _list(envelope.get("signatures"), field="DSSE signatures")
        if envelope.get("payloadType") != "application/vnd.in-toto+json" or len(signatures) != 1:
            raise GenOfficeNpmProvenanceAdmissionError("DSSE envelope is not the reviewed signed statement")
        payload = _decode_payload(envelope.get("payload"))
        if payload.get("predicateType") != predicate_type:
            raise GenOfficeNpmProvenanceAdmissionError("DSSE predicate type does not match its wrapper")
        _subject(payload)
        bundles[str(predicate_type)] = bundle
        payloads[str(predicate_type)] = payload
        rekor_entries.append(_rekor_entry(bundle, predicate_type=str(predicate_type)))
    if set(bundles) != {PUBLISH_PREDICATE_TYPE, SLSA_PREDICATE_TYPE}:
        raise GenOfficeNpmProvenanceAdmissionError("npm attestation bundle pair is incomplete")

    publish = payloads[PUBLISH_PREDICATE_TYPE]
    if publish.get("_type") != "https://in-toto.io/Statement/v0.1" or publish.get("predicate") != {
        "name": EMF_CONVERTER_NAME,
        "version": EMF_CONVERTER_VERSION,
        "registry": NPM_REGISTRY.removesuffix("/"),
    }:
        raise GenOfficeNpmProvenanceAdmissionError("npm publish attestation changed")
    slsa = payloads[SLSA_PREDICATE_TYPE]
    expected_slsa_predicate = {
        "buildDefinition": {
            "buildType": SLSA_BUILD_TYPE,
            "externalParameters": {
                "workflow": {"ref": SOURCE_REF, "repository": SOURCE_REPOSITORY_URI, "path": WORKFLOW_PATH}
            },
            "internalParameters": {
                "github": {
                    "event_name": "push",
                    "repository_id": SOURCE_REPOSITORY_ID,
                    "repository_owner_id": SOURCE_REPOSITORY_OWNER_ID,
                }
            },
            "resolvedDependencies": [
                {
                    "uri": f"git+{SOURCE_REPOSITORY_URI}@{SOURCE_REF}",
                    "digest": {"gitCommit": SOURCE_COMMIT},
                }
            ],
        },
        "runDetails": {"builder": {"id": SLSA_BUILDER_ID}, "metadata": {"invocationId": INVOCATION_URI}},
    }
    if slsa.get("_type") != "https://in-toto.io/Statement/v1" or slsa.get("predicate") != expected_slsa_predicate:
        raise GenOfficeNpmProvenanceAdmissionError("SLSA provenance identity changed")
    certificate_hash, issuer_org, issuer_cn, serial_hex, not_before, not_after = _certificate_identity(
        bundles[SLSA_PREDICATE_TYPE]
    )
    ordered_rekor = tuple(sorted(rekor_entries, key=lambda item: item.predicate_type))
    draft = GenOfficeNpmProvenanceAdmissionReport(
        vendored_provenance_report_hash=vendored.report_hash,
        npm_verification_report_hash=verification_hash,
        npm_verification_receipt_hash=receipt_hash,
        verifier_image_ref=image_ref,
        node_version=node_version,
        npm_version=npm_version,
        package_name=EMF_CONVERTER_NAME,
        package_version=EMF_CONVERTER_VERSION,
        package_purl=EMF_CONVERTER_PURL,
        package_integrity_sri=EMF_CONVERTER_TARBALL_SRI,
        package_sha512=EMF_CONVERTER_TARBALL_SHA512,
        registry=NPM_REGISTRY,
        package_location="node_modules/emf-converter",
        attestation_url=NPM_ATTESTATION_URL,
        verified_package_count=len(verified),
        invalid_package_count=len(invalid),
        missing_package_count=len(missing),
        attestation_predicate_types=tuple(sorted(bundles)),
        publish_statement_type=str(publish["_type"]),
        slsa_statement_type=str(slsa["_type"]),
        slsa_build_type=SLSA_BUILD_TYPE,
        slsa_builder_id=SLSA_BUILDER_ID,
        source_repository_uri=SOURCE_REPOSITORY_URI,
        source_repository_id=SOURCE_REPOSITORY_ID,
        source_repository_owner_id=SOURCE_REPOSITORY_OWNER_ID,
        source_commit=SOURCE_COMMIT,
        source_ref=SOURCE_REF,
        workflow_path=WORKFLOW_PATH,
        workflow_uri=WORKFLOW_URI,
        invocation_uri=INVOCATION_URI,
        runner_environment="github-hosted",
        source_repository_visibility="public",
        deployment_environment="npm",
        fulcio_certificate_sha256=certificate_hash,
        fulcio_certificate_issuer_organization=issuer_org,
        fulcio_certificate_issuer_common_name=issuer_cn,
        fulcio_certificate_serial_hex=serial_hex,
        fulcio_certificate_not_before_utc=not_before,
        fulcio_certificate_not_after_utc=not_after,
        rekor_entries=ordered_rekor,
        registry_signature_verified=True,
        publish_attestation_verified=True,
        slsa_provenance_verified=True,
        certificate_identity_verified=True,
        transparency_log_inclusion_verified=True,
        cryptographic_provenance_gate_passed=True,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_npm_provenance_report_hash(draft)})


def build_genoffice_npm_provenance_report_hash(report: GenOfficeNpmProvenanceAdmissionReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_genoffice_npm_provenance_admission_report(
    *, report: GenOfficeNpmProvenanceAdmissionReport, report_path: Path
) -> None:
    if build_genoffice_npm_provenance_report_hash(report) != report.report_hash:
        raise GenOfficeNpmProvenanceAdmissionError("GenOffice npm provenance report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_path.replace(report_path)


def load_genoffice_npm_provenance_admission_report(
    report_path: Path,
) -> GenOfficeNpmProvenanceAdmissionReport:
    try:
        report = GenOfficeNpmProvenanceAdmissionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GenOfficeNpmProvenanceAdmissionError("GenOffice npm provenance report cannot be loaded") from exc
    if build_genoffice_npm_provenance_report_hash(report) != report.report_hash:
        raise GenOfficeNpmProvenanceAdmissionError("GenOffice npm provenance report hash is invalid")
    return report


def run_genoffice_npm_provenance_admission_from_environment(
    env: Mapping[str, str],
) -> GenOfficeNpmProvenanceAdmissionReport:
    keys = {
        "vendored_provenance_path": "SUITE_GENOFFICE_VENDORED_PROVENANCE_REPORT_PATH",
        "npm_verification_path": "SUITE_GENOFFICE_NPM_VERIFICATION_PATH",
        "npm_verification_receipt_path": "SUITE_GENOFFICE_NPM_VERIFICATION_RECEIPT_PATH",
        "output_path": "SUITE_GENOFFICE_NPM_PROVENANCE_ADMISSION_REPORT_PATH",
    }
    values = {name: env.get(key, "").strip() for name, key in keys.items()}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise GenOfficeNpmProvenanceAdmissionError(f"GenOffice npm provenance paths are missing: {missing}")
    report = build_genoffice_npm_provenance_admission_report(
        vendored_provenance_path=Path(values["vendored_provenance_path"]),
        npm_verification_path=Path(values["npm_verification_path"]),
        npm_verification_receipt_path=Path(values["npm_verification_receipt_path"]),
    )
    persist_genoffice_npm_provenance_admission_report(report=report, report_path=Path(values["output_path"]))
    return report


def main() -> None:
    try:
        report = run_genoffice_npm_provenance_admission_from_environment(os.environ)
        print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
        raise SystemExit(0 if report.cryptographic_provenance_gate_passed else 2)
    except GenOfficeNpmProvenanceAdmissionError as exc:
        print(json.dumps({"error": str(exc), "schema_version": GENOFFICE_NPM_PROVENANCE_ADMISSION_SCHEMA_VERSION}))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
