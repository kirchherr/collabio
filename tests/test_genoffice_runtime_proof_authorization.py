from __future__ import annotations

import base64
import json
import struct
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.genoffice_runtime_proof_authorization import (
    GENOFFICE_RUNTIME_ENGINE_FIXTURE_IDS,
    GENOFFICE_RUNTIME_FIXTURE_IDS,
    GENOFFICE_RUNTIME_PREFLIGHT_ONLY_FIXTURE_IDS,
    GenOfficeRuntimeProofAuthorizationError,
    GenOfficeRuntimeSandboxProfile,
    GenOfficeRuntimeSignatureResponse,
    GenOfficeRuntimeSignerPolicy,
    GenOfficeRuntimeSigningRequest,
    GenOfficeSyntheticCorpusManifest,
    _verify_docker_inspect,
    assemble_genoffice_runtime_authorization_envelope,
    build_genoffice_runtime_sandbox_profile,
    build_genoffice_runtime_signer_policy,
    build_genoffice_runtime_signing_request,
    build_genoffice_synthetic_corpus,
    materialize_genoffice_synthetic_corpus,
    persist_genoffice_runtime_schemas,
    verify_genoffice_runtime_authorization,
    verify_genoffice_runtime_signing_request,
    verify_genoffice_synthetic_corpus,
)
from suite.operations.genoffice_worker_image_admission import (
    GenOfficeWorkerImageAdmissionReport,
    build_genoffice_worker_admission_report_hash,
    load_genoffice_worker_image_admission_report,
)

ZERO_HASH = "sha256:" + "0" * 64


def _hash(value: str) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _worker_admission() -> GenOfficeWorkerImageAdmissionReport:
    draft = GenOfficeWorkerImageAdmissionReport(
        attestation_id="genoffice-worker-test",
        issued_at_utc=datetime(2026, 8, 12, 9, 20, tzinfo=UTC),
        valid_until_utc=datetime(2026, 8, 19, 9, 20, tzinfo=UTC),
        signer_id="founder-risk-owner",
        key_id="founder-key",
        signer_policy_hash=_hash("founder-policy"),
        solo_founder_exception_report_hash=_hash("founder-report"),
        image_config_digest=_hash("image-config"),
        image_archive_sha256=_hash("image-archive"),
        build_evidence_report_hash=_hash("build-evidence"),
        development_build_context_report_hash=_hash("context-report"),
        development_build_context_tar_sha256=_hash("context-tar"),
        worker_sbom_sha256=_hash("worker-sbom"),
        raw_scanner_sbom_sha256=_hash("raw-sbom"),
        sbom_schema_validation_receipt_hash=_hash("sbom-receipt"),
        vulnerability_report_hash=_hash("vulnerability-report"),
        trivy_db_metadata_hash=_hash("trivy-db"),
        vulnerability_count=0,
        severity_counts={"UNKNOWN": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
        signing_request_hash=_hash("worker-request"),
        signature_response_hash=_hash("worker-response"),
        attestation_payload_hash=_hash("worker-payload"),
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_worker_admission_report_hash(draft)})


def _ceremony() -> tuple[
    GenOfficeWorkerImageAdmissionReport,
    GenOfficeSyntheticCorpusManifest,
    GenOfficeRuntimeSandboxProfile,
    GenOfficeRuntimeSignerPolicy,
    Ed25519PrivateKey,
    Ed25519PrivateKey,
]:
    product_key = Ed25519PrivateKey.generate()
    security_key = Ed25519PrivateKey.generate()
    policy = build_genoffice_runtime_signer_policy(
        policy_id="genoffice-runtime-proof-test",
        effective_at_utc=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
        product_owner_signer_id="product-owner-person",
        product_owner_key_id="product-owner-key",
        product_owner_public_key=_public_key(product_key),
        security_compliance_owner_signer_id="security-owner-person",
        security_compliance_owner_key_id="security-owner-key",
        security_compliance_owner_public_key=_public_key(security_key),
    )
    _, manifest = build_genoffice_synthetic_corpus()
    profile = build_genoffice_runtime_sandbox_profile()
    return _worker_admission(), manifest, profile, policy, product_key, security_key


def _request_and_responses() -> tuple[
    GenOfficeWorkerImageAdmissionReport,
    GenOfficeSyntheticCorpusManifest,
    GenOfficeRuntimeSandboxProfile,
    GenOfficeRuntimeSignerPolicy,
    GenOfficeRuntimeSigningRequest,
    bytes,
    tuple[GenOfficeRuntimeSignatureResponse, ...],
]:
    admission, manifest, profile, policy, product_key, security_key = _ceremony()
    request, message = build_genoffice_runtime_signing_request(
        worker_admission=admission,
        manifest=manifest,
        sandbox_profile=profile,
        signer_policy=policy,
        authorization_id="genoffice-synthetic-runtime-20260812-01",
        issued_at_utc=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
        valid_until_utc=datetime(2026, 8, 12, 18, 0, tzinfo=UTC),
        risk_acceptance_ref="ADR-0070:synthetic-runtime-proof",
        change_control_ref="git:test",
    )
    keys = {
        "product_owner": product_key,
        "security_compliance_owner": security_key,
    }
    responses = tuple(
        GenOfficeRuntimeSignatureResponse(
            request_hash=request.request_hash,
            signature_message_sha256=request.signature_message_sha256,
            signer_id=assignment.signer_id,
            signer_role=assignment.signer_role,
            key_id=assignment.key_id,
            signature_base64=base64.b64encode(keys[assignment.signer_role].sign(message)).decode("ascii"),
        )
        for assignment in request.signing_assignments
    )
    return admission, manifest, profile, policy, request, message, responses


def test_synthetic_corpus_is_deterministic_exact_and_write_once(tmp_path: Path) -> None:
    files, manifest = build_genoffice_synthetic_corpus()
    duplicate_files, duplicate_manifest = build_genoffice_synthetic_corpus()

    assert files == duplicate_files
    assert manifest == duplicate_manifest
    assert tuple(item.fixture_id for item in manifest.artifacts) == GENOFFICE_RUNTIME_FIXTURE_IDS
    assert tuple(item.fixture_id for item in manifest.artifacts if item.engine_invocation_allowed) == (
        GENOFFICE_RUNTIME_ENGINE_FIXTURE_IDS
    )
    assert tuple(item.fixture_id for item in manifest.artifacts if not item.engine_invocation_allowed) == (
        GENOFFICE_RUNTIME_PREFLIGHT_ONLY_FIXTURE_IDS
    )
    bomb = files["declared-zip-bomb.docx"]
    central = bomb.index(b"PK\x01\x02")
    assert struct.unpack_from("<I", bomb, central + 24)[0] == 600 * 1024 * 1024
    with zipfile.ZipFile(BytesIO(files["remote-relationship-no-egress.docx"])) as remote_archive:
        relationships = remote_archive.read("word/_rels/document.xml.rels")
    with zipfile.ZipFile(BytesIO(files["active-content-preflight-rejection.docm"])) as macro_archive:
        macro_marker = macro_archive.read("word/vbaProject.bin")
    assert b"https://example.com/collabio-synthetic-proof" in relationships
    assert b"COLLABIO-SYNTHETIC-NONEXECUTABLE-VBA-FIXTURE" in macro_marker

    output = tmp_path / "corpus"
    assert materialize_genoffice_synthetic_corpus(output) == manifest
    verify_genoffice_synthetic_corpus(manifest=manifest, corpus_directory=output)
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="not empty"):
        materialize_genoffice_synthetic_corpus(output)


def test_sandbox_profile_and_docker_inspect_are_exact() -> None:
    profile = build_genoffice_runtime_sandbox_profile()
    inspect: list[dict[str, Any]] = [
        {
            "Config": {"User": "10003:10003"},
            "HostConfig": {
                "Runtime": "runsc-kvm",
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "PidsLimit": 32,
                "NanoCpus": 500_000_000,
                "Memory": 536_870_912,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Tmpfs": {"/scratch": "size=64m,noexec,nosuid,nodev,uid=10003,gid=10003,mode=0700"},
            },
            "Mounts": [{"Destination": "/corpus", "RW": False}],
        }
    ]

    _verify_docker_inspect(inspect, profile)
    inspect[0]["HostConfig"]["Runtime"] = "runc"
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="configuration drifted"):
        _verify_docker_inspect(inspect, profile)


def test_sandbox_probe_compose_keeps_evidence_read_only_and_reports_via_logs() -> None:
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    probe = compose.split("\n  genoffice-runtime-sandbox-probe:\n", maxsplit=1)[1].split("\n  api:\n", maxsplit=1)[0]

    assert "runtime: runsc-kvm" in probe
    assert 'network_mode: "none"' in probe
    assert 'user: "10003:10003"' in probe
    assert "read_only: true" in probe
    assert "target: /evidence\n        read_only: true" in probe
    assert "SUITE_GENOFFICE_RUNTIME_SANDBOX_PROBE_REPORT_PATH" not in probe


def test_two_person_runtime_authorization_is_worker_corpus_and_sandbox_bound() -> None:
    admission, manifest, profile, policy, request, message, responses = _request_and_responses()

    assert verify_genoffice_runtime_signing_request(request) == message
    assert request.authorization_effective is False
    assert request.payload.synthetic_worker_execution_allowed is True
    assert request.payload.tenant_content_allowed is False
    assert request.required_signer_roles == ("product_owner", "security_compliance_owner")
    envelope = assemble_genoffice_runtime_authorization_envelope(
        request=request,
        signer_policy=policy,
        signature_responses=responses,
        assembled_at_utc=datetime(2026, 8, 12, 10, 15, tzinfo=UTC),
    )
    report = verify_genoffice_runtime_authorization(
        worker_admission=admission,
        manifest=manifest,
        sandbox_profile=profile,
        signer_policy=policy,
        envelope=envelope,
        verified_at_utc=datetime(2026, 8, 12, 10, 20, tzinfo=UTC),
    )

    assert report.two_person_control_verified is True
    assert report.synthetic_proof_execution_allowed is True
    assert report.general_worker_execution_allowed is False
    assert report.external_network_allowed is False
    assert report.production_use_allowed is False


def test_runtime_authorization_rejects_signature_corpus_and_expiry_drift() -> None:
    admission, manifest, profile, policy, request, _, responses = _request_and_responses()
    signature = bytearray(base64.b64decode(responses[0].signature_base64))
    signature[0] ^= 1
    tampered_response = responses[0].model_copy(
        update={"signature_base64": base64.b64encode(bytes(signature)).decode("ascii")}
    )
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="signature is invalid"):
        assemble_genoffice_runtime_authorization_envelope(
            request=request,
            signer_policy=policy,
            signature_responses=(tampered_response, responses[1]),
            assembled_at_utc=datetime(2026, 8, 12, 10, 15, tzinfo=UTC),
        )

    drifted_manifest = manifest.model_copy(update={"total_size_bytes": manifest.total_size_bytes + 1})
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="manifest hash"):
        build_genoffice_runtime_signing_request(
            worker_admission=admission,
            manifest=drifted_manifest,
            sandbox_profile=profile,
            signer_policy=policy,
            authorization_id="drift",
            issued_at_utc=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
            valid_until_utc=datetime(2026, 8, 12, 11, 0, tzinfo=UTC),
            risk_acceptance_ref="ADR-0070",
            change_control_ref="git:test",
        )

    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="not currently valid"):
        build_genoffice_runtime_signing_request(
            worker_admission=admission,
            manifest=manifest,
            sandbox_profile=profile,
            signer_policy=policy,
            authorization_id="expired",
            issued_at_utc=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
            valid_until_utc=datetime(2026, 8, 20, 11, 0, tzinfo=UTC),
            risk_acceptance_ref="ADR-0070",
            change_control_ref="git:test",
        )


def test_runtime_policy_rejects_one_person_in_two_roles() -> None:
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="two-person separation"):
        build_genoffice_runtime_signer_policy(
            policy_id="invalid-one-person-policy",
            effective_at_utc=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
            product_owner_signer_id="same-person",
            product_owner_key_id="key-a",
            product_owner_public_key=_public_key(key_a),
            security_compliance_owner_signer_id="same-person",
            security_compliance_owner_key_id="key-b",
            security_compliance_owner_public_key=_public_key(key_b),
        )


def test_runtime_schemas_and_worker_admission_loader_are_write_once(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    hashes = persist_genoffice_runtime_schemas(schema_dir)

    assert len(hashes) == 8
    assert all(value.startswith("sha256:") for value in hashes.values())
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="already exists"):
        persist_genoffice_runtime_schemas(schema_dir)

    admission = _worker_admission()
    path = tmp_path / "worker-admission.json"
    path.write_text(json.dumps(admission.model_dump(mode="json")), encoding="utf-8")
    assert load_genoffice_worker_image_admission_report(path) == admission
    path.write_text(json.dumps(admission.model_copy(update={"attestation_id": "drifted"}).model_dump(mode="json")))
    with pytest.raises(ValueError, match="report hash"):
        load_genoffice_worker_image_admission_report(path)


def test_runtime_authorization_window_is_bounded_by_24_hours_and_worker_admission() -> None:
    admission, manifest, profile, policy, _, _ = _ceremony()
    issued_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="validity window"):
        build_genoffice_runtime_signing_request(
            worker_admission=admission,
            manifest=manifest,
            sandbox_profile=profile,
            signer_policy=policy,
            authorization_id="too-long",
            issued_at_utc=issued_at,
            valid_until_utc=issued_at + timedelta(hours=25),
            risk_acceptance_ref="ADR-0070",
            change_control_ref="git:test",
        )
    with pytest.raises(GenOfficeRuntimeProofAuthorizationError, match="exceeds worker admission"):
        build_genoffice_runtime_signing_request(
            worker_admission=admission,
            manifest=manifest,
            sandbox_profile=profile,
            signer_policy=policy,
            authorization_id="past-admission",
            issued_at_utc=datetime(2026, 8, 18, 10, 0, tzinfo=UTC),
            valid_until_utc=datetime(2026, 8, 19, 10, 0, tzinfo=UTC),
            risk_acceptance_ref="ADR-0070",
            change_control_ref="git:test",
        )
