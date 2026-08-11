from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.operations.genoffice_development_build_context import GenOfficeDevelopmentBuildContextReport
from suite.operations.genoffice_docx_source_admission import load_genoffice_docx_source_admission_report
from suite.operations.genoffice_internal_oss_admission import (
    GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
    GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
)
from suite.operations.genoffice_solo_founder_exception import (
    GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS,
    GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS,
    GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS,
    GenOfficeSoloFounderExceptionReport,
    GenOfficeSoloFounderPolicy,
    build_genoffice_solo_founder_policy,
    build_genoffice_solo_founder_report_hash,
)
from suite.operations.genoffice_third_party_notice import (
    GENOFFICE_DEVELOPMENT_PROFILE,
    GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH,
    GENOFFICE_SELECTED_SOURCE_SCOPE,
)
from suite.operations.genoffice_worker_image_admission import (
    GenOfficeWorkerBuildSignatureResponse,
    GenOfficeWorkerImageAdmissionError,
    GenOfficeWorkerImageBuildEvidence,
    _inspect_boundary,
    _verify_docker_archive,
    build_genoffice_worker_build_evidence_report_hash,
    build_genoffice_worker_image_sbom,
    build_genoffice_worker_signing_request,
    verify_genoffice_worker_image_admission,
)

EVIDENCE = Path("docs/operations")
ZERO_HASH = "sha256:" + "0" * 64


def _hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _authorization_fixture() -> tuple[
    Ed25519PrivateKey,
    GenOfficeSoloFounderPolicy,
    GenOfficeSoloFounderExceptionReport,
    datetime,
]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    issued_at = datetime(2026, 8, 11, 13, 0, tzinfo=UTC)
    policy = build_genoffice_solo_founder_policy(
        policy_id="worker-policy-test",
        effective_at_utc=issued_at - timedelta(minutes=1),
        signer_id="founder-test",
        key_id="founder-key-test",
        public_key=public_key,
    )
    draft = GenOfficeSoloFounderExceptionReport(
        exception_id="worker-exception-test",
        issued_at_utc=issued_at,
        valid_until_utc=issued_at + timedelta(days=7),
        signer_id=policy.signer.signer_id,
        key_id=policy.signer.key_id,
        signer_policy_hash=policy.policy_hash,
        exception_payload_hash=_hash("exception-payload"),
        signing_request_hash=_hash("exception-request"),
        signature_response_hash=_hash("exception-response"),
        legal_dossier_report_hash=GENOFFICE_REVIEWED_LEGAL_DOSSIER_HASH,
        third_party_notice_report_hash=_hash("notice-report"),
        third_party_notice_artifact_sha256=_hash("notice"),
        approved_usage_profiles=(GENOFFICE_DEVELOPMENT_PROFILE,),
        blocked_usage_profiles=GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
        approved_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        prohibited_source_scopes=GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
        compensating_controls=GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS,
        later_required_approval_roles=GENOFFICE_SOLO_FOUNDER_LATER_APPROVALS,
        blocked_actions=GENOFFICE_SOLO_FOUNDER_BLOCKED_ACTIONS,
        report_hash=ZERO_HASH,
    )
    report = draft.model_copy(update={"report_hash": build_genoffice_solo_founder_report_hash(draft)})
    return private_key, policy, report, issued_at


def _build_evidence(exception: GenOfficeSoloFounderExceptionReport) -> GenOfficeWorkerImageBuildEvidence:
    draft = GenOfficeWorkerImageBuildEvidence(
        observed_at_utc=exception.issued_at_utc + timedelta(minutes=10),
        image_ref_a="collabio/genoffice-docx-worker:verification-a",
        image_ref_b="collabio/genoffice-docx-worker:verification-b",
        image_config_digest=_hash("image-config"),
        image_size_bytes=1024,
        image_archive_size_bytes=2048,
        image_archive_sha256=_hash("image-archive"),
        rootfs_layer_digests=(_hash("layer"),),
        build_a_inspect_sha256=_hash("inspect-a"),
        build_b_inspect_sha256=_hash("inspect-b"),
        dockerfile_sha256=_hash("dockerfile"),
        development_build_context_report_hash=_hash("context-report"),
        development_build_context_tar_sha256=_hash("context-tar"),
        source_archive_sha256=_hash("source-archive"),
        source_manifest_hash=_hash("source-manifest"),
        development_authorization_report_hash=exception.report_hash,
        signer_policy_hash=exception.signer_policy_hash,
        license_material_collection_report_hash=_hash("license-materials"),
        dependency_archive_count=21,
        runtime_package_count=21,
        source_date_epoch=0,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_worker_build_evidence_report_hash(draft)})


def _npm_purl(name: str, version: str) -> str:
    normalized = name.replace("@", "%40", 1) if name.startswith("@") else name
    return f"pkg:npm/{normalized}@{version}"


def _authoritative_sbom(build_evidence: GenOfficeWorkerImageBuildEvidence) -> dict[str, Any]:
    source_report = load_genoffice_docx_source_admission_report(
        EVIDENCE / "genoffice_docx_source_admission_report.json"
    )
    raw_components = [
        {
            "type": "library",
            "name": dependency.name,
            "version": dependency.version,
            "purl": _npm_purl(dependency.name, str(dependency.version)),
        }
        for dependency in source_report.runtime_dependencies
    ]
    raw_components.append(
        {
            "type": "operating-system",
            "name": "debian",
            "version": "13",
            "purl": "pkg:deb/debian/base-files@13.8%2Bdeb13u1?arch=amd64",
        }
    )
    raw_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": raw_components,
    }
    prebuild_sbom = json.loads((EVIDENCE / "genoffice_docx_prebuild.cdx.json").read_text(encoding="utf-8"))
    return build_genoffice_worker_image_sbom(
        raw_sbom=raw_sbom,
        raw_sbom_sha256=_hash("raw-sbom"),
        build_evidence=build_evidence,
        source_report=source_report,
        prebuild_sbom=prebuild_sbom,
    )


def _scan_evidence(tmp_path: Path, sbom: dict[str, Any], issued_at: datetime) -> tuple[Path, Path, Path, Path]:
    sbom_path = tmp_path / "genoffice-worker-image.cdx.json"
    sbom_path.write_text(json.dumps(sbom, sort_keys=True) + "\n", encoding="utf-8")
    sbom_hash = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
    receipt_path = tmp_path / "genoffice-worker-image-schema-validation.txt"
    receipt_path.write_text(
        "schema=cyclonedx-1.6\n"
        "validator=cyclonedx-cli-0.32.0@sha256:9a858a15e7b0843606efc0ff19d5f7575011a5428d7f3d343b4f6cf09d8f0d4e\n"
        f"sbom_sha256={sbom_hash}\n"
        "status=valid\n",
        encoding="utf-8",
    )
    npm_components = [
        component
        for component in sbom["components"]
        if isinstance(component, dict) and str(component.get("purl", "")).startswith("pkg:npm/")
    ]
    scan_time = issued_at + timedelta(minutes=20)
    vulnerability_path = tmp_path / "genoffice-worker-image-vulnerability-report.json"
    vulnerability_path.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "CreatedAt": scan_time.isoformat(),
                "ArtifactName": "/evidence/genoffice-worker-image.cdx.json",
                "ArtifactType": "cyclonedx",
                "Trivy": {"Version": "0.73.0"},
                "Results": [
                    {
                        "Packages": [{"Identifier": {"PURL": component["purl"]}} for component in npm_components],
                        "Vulnerabilities": [],
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "metadata.json"
    db_path.write_text(
        json.dumps(
            {
                "Version": 2,
                "UpdatedAt": (scan_time - timedelta(hours=1)).isoformat(),
                "DownloadedAt": (scan_time - timedelta(minutes=5)).isoformat(),
                "NextUpdate": (scan_time + timedelta(hours=5)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return sbom_path, receipt_path, vulnerability_path, db_path


def test_worker_image_admission_binds_reproducible_image_sbom_scan_and_signature(tmp_path: Path) -> None:
    private_key, policy, exception, issued_at = _authorization_fixture()
    build_evidence = _build_evidence(exception)
    sbom = _authoritative_sbom(build_evidence)
    sbom_path, receipt_path, vulnerability_path, db_path = _scan_evidence(tmp_path, sbom, issued_at)

    request, message = build_genoffice_worker_signing_request(
        build_evidence=build_evidence,
        sbom=sbom,
        sbom_path=sbom_path,
        schema_receipt_path=receipt_path,
        vulnerability_report_path=vulnerability_path,
        trivy_db_metadata_path=db_path,
        policy=policy,
        exception_report=exception,
        attestation_id="worker-attestation-test",
        issued_at_utc=issued_at + timedelta(minutes=30),
        valid_until_utc=issued_at + timedelta(days=6),
    )
    response = GenOfficeWorkerBuildSignatureResponse(
        request_hash=request.request_hash,
        signature_message_sha256=request.signature_message_sha256,
        signer_id=policy.signer.signer_id,
        key_id=policy.signer.key_id,
        signature_base64=base64.b64encode(private_key.sign(message)).decode("ascii"),
    )

    report = verify_genoffice_worker_image_admission(
        build_evidence=build_evidence,
        policy=policy,
        exception_report=exception,
        request=request,
        response=response,
        verified_at_utc=issued_at + timedelta(hours=1),
    )

    assert report.reproducible_worker_build_verified is True
    assert report.authoritative_image_sbom_verified is True
    assert report.vulnerability_review_complete is True
    assert report.detached_build_attestation_verified is True
    assert report.development_spike_image_available is True
    assert report.two_person_runtime_authorization_verified is False
    assert report.worker_execution_allowed is False
    assert report.source_import_allowed is False
    assert report.tenant_content_allowed is False
    assert report.production_use_allowed is False


def test_worker_image_admission_rejects_tampered_signature(tmp_path: Path) -> None:
    private_key, policy, exception, issued_at = _authorization_fixture()
    build_evidence = _build_evidence(exception)
    sbom = _authoritative_sbom(build_evidence)
    sbom_path, receipt_path, vulnerability_path, db_path = _scan_evidence(tmp_path, sbom, issued_at)
    request, _ = build_genoffice_worker_signing_request(
        build_evidence=build_evidence,
        sbom=sbom,
        sbom_path=sbom_path,
        schema_receipt_path=receipt_path,
        vulnerability_report_path=vulnerability_path,
        trivy_db_metadata_path=db_path,
        policy=policy,
        exception_report=exception,
        attestation_id="worker-attestation-test",
        issued_at_utc=issued_at + timedelta(minutes=30),
        valid_until_utc=issued_at + timedelta(days=6),
    )
    del private_key
    response = GenOfficeWorkerBuildSignatureResponse(
        request_hash=request.request_hash,
        signature_message_sha256=request.signature_message_sha256,
        signer_id=policy.signer.signer_id,
        key_id=policy.signer.key_id,
        signature_base64=base64.b64encode(b"x" * 64).decode("ascii"),
    )

    with pytest.raises(GenOfficeWorkerImageAdmissionError, match="detached signature is invalid"):
        verify_genoffice_worker_image_admission(
            build_evidence=build_evidence,
            policy=policy,
            exception_report=exception,
            request=request,
            response=response,
            verified_at_utc=issued_at + timedelta(hours=1),
        )


def test_worker_docker_archive_is_bound_to_config_digest_and_tag(tmp_path: Path) -> None:
    config = json.dumps({"architecture": "amd64", "os": "linux"}, sort_keys=True).encode()
    image_id = f"sha256:{hashlib.sha256(config).hexdigest()}"
    config_name = f"{image_id.removeprefix('sha256:')}.json"
    image_ref = "collabio/genoffice-docx-worker:verification-a"
    manifest = json.dumps([{"Config": config_name, "RepoTags": [image_ref], "Layers": ["layer/layer.tar"]}]).encode()
    archive_path = tmp_path / "worker.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name, content in (
            ("manifest.json", manifest),
            (config_name, config),
            ("layer/layer.tar", b"layer"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    archive_hash, archive_size = _verify_docker_archive(
        archive_path,
        image_id=image_id,
        image_ref=image_ref,
    )

    assert archive_hash.startswith("sha256:")
    assert archive_size == archive_path.stat().st_size
    with pytest.raises(GenOfficeWorkerImageAdmissionError, match="identity"):
        _verify_docker_archive(
            archive_path,
            image_id=image_id,
            image_ref="collabio/genoffice-docx-worker:other",
        )


def test_worker_oci_archive_binds_index_manifest_config_layers_and_tag(tmp_path: Path) -> None:
    image_ref = "collabio/genoffice-docx-worker:verification-a"
    config = json.dumps({"architecture": "amd64", "os": "linux"}, sort_keys=True).encode()
    config_digest = f"sha256:{hashlib.sha256(config).hexdigest()}"
    layer = b"reproducible-layer"
    layer_digest = f"sha256:{hashlib.sha256(layer).hexdigest()}"
    config_name = f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
    layer_name = f"blobs/sha256/{layer_digest.removeprefix('sha256:')}"
    oci_manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config_digest,
                "size": len(config),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": layer_digest,
                    "size": len(layer),
                }
            ],
        },
        sort_keys=True,
    ).encode()
    manifest_digest = f"sha256:{hashlib.sha256(oci_manifest).hexdigest()}"
    manifest_name = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
    index = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": manifest_digest,
                    "size": len(oci_manifest),
                    "annotations": {
                        "config.digest": config_digest,
                        "io.containerd.image.name": f"docker.io/{image_ref}",
                        "org.opencontainers.image.ref.name": "verification-a",
                    },
                }
            ],
        },
        sort_keys=True,
    ).encode()
    docker_manifest = json.dumps(
        [{"Config": config_name, "RepoTags": [image_ref], "Layers": [layer_name]}],
        sort_keys=True,
    ).encode()
    archive_path = tmp_path / "worker-oci.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name, content in (
            ("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'),
            ("index.json", index),
            ("manifest.json", docker_manifest),
            (config_name, config),
            (manifest_name, oci_manifest),
            (layer_name, layer),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    archive_hash, _ = _verify_docker_archive(
        archive_path,
        image_id=config_digest,
        image_ref=image_ref,
        manifest_digest=manifest_digest,
    )

    assert archive_hash.startswith("sha256:")


def test_worker_inspect_uses_oci_descriptor_config_digest() -> None:
    config_digest = _hash("image-config")
    manifest_digest = _hash("image-manifest")
    context_report = GenOfficeDevelopmentBuildContextReport.model_construct(
        context_tar_sha256=_hash("context-tar"),
        development_authorization_report_hash=_hash("authorization"),
        report_hash=_hash("context-report"),
    )
    image = {
        "Id": manifest_digest,
        "Descriptor": {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": manifest_digest,
            "annotations": {"config.digest": config_digest},
        },
        "Os": "linux",
        "Architecture": "amd64",
        "Size": 4096,
        "Config": {
            "Labels": {
                "io.collabio.genoffice.authorization-report-sha256": (
                    context_report.development_authorization_report_hash
                ),
                "io.collabio.genoffice.build-context-report-sha256": context_report.report_hash,
                "io.collabio.genoffice.build-context-sha256": context_report.context_tar_sha256,
                "io.collabio.genoffice.execution-state": "blocked",
                "io.collabio.genoffice.production-use-allowed": "false",
                "io.collabio.genoffice.scope": "development_evaluation",
                "io.collabio.genoffice.source-import-allowed": "false",
                "io.collabio.genoffice.tenant-content-allowed": "false",
            },
            "User": "10003:10003",
            "WorkingDir": "/opt/genoffice/packages/docx-engine",
            "Entrypoint": ["node", "/opt/collabio/worker-entrypoint.mjs"],
            "Cmd": ["--status"],
            "Env": ["NODE_ENV=production"],
        },
        "RootFS": {"Type": "layers", "Layers": [_hash("layer")]},
    }

    observed_manifest, observed_digest, size, layers = _inspect_boundary(image, context_report=context_report)

    assert observed_manifest == manifest_digest
    assert observed_digest == config_digest
    assert size == 4096
    assert layers == (_hash("layer"),)
    image["Descriptor"]["annotations"]["config.digest"] = "invalid"
    with pytest.raises(GenOfficeWorkerImageAdmissionError, match="config digest"):
        _inspect_boundary(image, context_report=context_report)


def test_worker_module_does_not_ingest_private_keys_or_open_runtime_boundary() -> None:
    module = Path("app/suite/operations/genoffice_worker_image_admission.py").read_text(encoding="utf-8")
    dockerfile = Path("docker/genoffice-worker/Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    entrypoint = Path("docker/genoffice-worker/worker-entrypoint.mjs").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "cryptography"):
        assert f"import {forbidden}" not in module
    assert "from suite.kms.signatures import" in module
    assert "private_key_ingestion_allowed: Literal[False]" in module
    assert "worker_execution_allowed: Literal[False]" in module
    assert "npm install --offline --ignore-scripts" in dockerfile
    assert "prepare-runtime-manifest.mjs" in dockerfile
    assert "build-runtime-file-inventory.mjs" in dockerfile
    assert "ARG SOURCE_DATE_EPOCH=0" in dockerfile
    assert 'touch -h -d "@${SOURCE_DATE_EPOCH}"' in dockerfile
    assert "--sort=name" in dockerfile
    assert "--numeric-owner" in dockerfile
    assert "source=/opt/collabio,target=/mnt,ro" in dockerfile
    assert "COPY --chown" not in dockerfile
    assert "USER 10003:10003" in dockerfile
    assert "provenance: false" in compose
    assert "worker_execution_allowed: false" in entrypoint


def test_worker_build_context_report_remains_non_runtime() -> None:
    fields = GenOfficeDevelopmentBuildContextReport.model_fields

    assert fields["worker_image_built"].default is False
    assert fields["engine_execution_allowed"].default is False
    assert fields["source_import_allowed"].default is False
    assert fields["tenant_content_allowed"].default is False
    assert fields["production_use_allowed"].default is False
