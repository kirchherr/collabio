from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel

from suite.operations.derived_preview_recovery_drill import (
    DerivedPreviewRecoveryDrillReport,
    build_derived_preview_recovery_drill_report_hash,
)
from suite.operations.preview_conversion_production_admission import (
    DSSE_PAYLOAD_TYPE,
    DSSESignature,
    MalwareCdrServiceEvidence,
    PreviewConversionAttestationEnvelope,
    PreviewConversionProductionEvidenceBundle,
    PreviewConversionSignerPolicy,
    PreviewConversionTrustedSigner,
    RuntimeIsolationEvidence,
    ViewerIsolationEvidence,
    WorkerImageSupplyChainEvidence,
    bind_preview_conversion_command_to_production_admission,
    build_dsse_pae,
    build_preview_conversion_attestation_statement,
    build_preview_conversion_dsse_payload,
    build_preview_conversion_production_admission_gate,
    build_preview_conversion_production_admission_gate_hash,
    load_and_require_preview_conversion_production_admission,
    require_preview_conversion_production_admission,
)
from suite.platform.source_object_preview_conversion import (
    PreviewConversionBlocked,
    PreviewConversionCommand,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionGateStatus,
    PreviewConversionResourceLimits,
    build_preview_conversion_command_hash,
    build_preview_conversion_execution_gate,
)
from suite.storage.source_objects import SourceObjectType, sha256_bytes

NOW = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
HASHES = tuple("sha256:" + character * 64 for character in "123456789abcdef")
IMAGE_REF = "ghcr.io/kirchherr/collabio-preview-renderer@sha256:" + "a" * 64
VIEWER_ORIGIN = "https://preview.example.com"
APPLICATION_ORIGIN = "https://app.example.com"
SIGNER_ROLES: tuple[Literal["release", "security", "operations"], ...] = ("release", "security", "operations")


def test_production_admission_requires_fresh_bound_three_role_signed_evidence(
    tmp_path: Path,
) -> None:
    recovery_report = _recovery_report()
    execution_gate = _execution_gate(recovery_report=recovery_report)
    bundle = _bundle(execution_gate=execution_gate, recovery_report=recovery_report)
    signer_policy, envelope = _sign_bundle(bundle)

    gate = build_preview_conversion_production_admission_gate(
        bundle=bundle,
        execution_gate=execution_gate,
        recovery_report=recovery_report,
        attestation_envelope=envelope,
        signer_policy=signer_policy,
        checked_at_utc=NOW,
    )

    assert gate.gate_status == PreviewConversionGateStatus.READY
    assert gate.conversion_dispatch_allowed is True
    assert gate.preview_serving_allowed is False
    assert gate.verified_signer_roles == ("operations", "release", "security")
    assert gate.gate_hash == build_preview_conversion_production_admission_gate_hash(gate)

    command = _command(execution_gate=execution_gate)
    with pytest.raises(PreviewConversionBlocked, match="not bound"):
        require_preview_conversion_production_admission(
            command=command,
            execution_gate=execution_gate,
            production_gate=gate,
            checked_at_utc=NOW,
        )

    bound_command = bind_preview_conversion_command_to_production_admission(
        command=command,
        execution_gate=execution_gate,
        production_gate=gate,
        checked_at_utc=NOW,
    )
    assert bound_command.production_admission_gate_hash == gate.gate_hash
    assert bound_command.command_hash == build_preview_conversion_command_hash(bound_command)
    require_preview_conversion_production_admission(
        command=bound_command,
        execution_gate=execution_gate,
        production_gate=gate,
        checked_at_utc=NOW,
    )
    gate_path = tmp_path / "gate.json"
    bundle_path = tmp_path / "evidence.json"
    recovery_path = tmp_path / "recovery.json"
    attestation_path = tmp_path / "attestation.json"
    policy_path = tmp_path / "signers.json"
    _write_model(gate_path, gate)
    _write_model(bundle_path, bundle)
    _write_model(recovery_path, recovery_report)
    _write_model(attestation_path, envelope, by_alias=True)
    _write_model(policy_path, signer_policy)

    loaded_gate = load_and_require_preview_conversion_production_admission(
        command=bound_command,
        execution_gate=execution_gate,
        production_gate_path=gate_path,
        evidence_bundle_path=bundle_path,
        recovery_report_path=recovery_path,
        attestation_path=attestation_path,
        signer_policy_path=policy_path,
        checked_at_utc=NOW,
    )
    assert loaded_gate == gate

    invalid_signature = envelope.signatures[0].model_copy(
        update={"sig": base64.b64encode(b"\x00" * 64).decode("ascii")}
    )
    tampered_envelope = envelope.model_copy(update={"signatures": (invalid_signature, *envelope.signatures[1:])})
    _write_model(attestation_path, tampered_envelope, by_alias=True)
    with pytest.raises(PreviewConversionBlocked, match="could not be reproduced"):
        load_and_require_preview_conversion_production_admission(
            command=bound_command,
            execution_gate=execution_gate,
            production_gate_path=gate_path,
            evidence_bundle_path=bundle_path,
            recovery_report_path=recovery_path,
            attestation_path=attestation_path,
            signer_policy_path=policy_path,
            checked_at_utc=NOW,
        )


def test_production_admission_blocks_invalid_signature_without_trusting_boolean_claims() -> None:
    recovery_report = _recovery_report()
    execution_gate = _execution_gate(recovery_report=recovery_report)
    bundle = _bundle(execution_gate=execution_gate, recovery_report=recovery_report)
    signer_policy, envelope = _sign_bundle(bundle)
    invalid_signature = envelope.signatures[0].model_copy(
        update={"sig": base64.b64encode(b"\x00" * 64).decode("ascii")}
    )
    tampered_envelope = envelope.model_copy(update={"signatures": (invalid_signature, *envelope.signatures[1:])})

    gate = build_preview_conversion_production_admission_gate(
        bundle=bundle,
        execution_gate=execution_gate,
        recovery_report=recovery_report,
        attestation_envelope=tampered_envelope,
        signer_policy=signer_policy,
        checked_at_utc=NOW,
    )

    assert gate.gate_status == PreviewConversionGateStatus.BLOCKED
    assert gate.conversion_dispatch_allowed is False
    assert gate.attestation_signatures_verified is False
    assert "attestation_signatures_not_verified" in gate.blocking_reasons


def test_production_admission_blocks_synthetic_services_stale_evidence_and_binding_drift() -> None:
    recovery_report = _recovery_report()
    execution_gate = _execution_gate(recovery_report=recovery_report)
    base_bundle = _bundle(execution_gate=execution_gate, recovery_report=recovery_report)
    blocked_malware = base_bundle.malware_cdr.model_copy(update={"synthetic_provider_used": True})
    blocked_runtime = base_bundle.runtime.model_copy(update={"observed_at_utc": NOW - timedelta(hours=25)})
    bundle = base_bundle.model_copy(
        update={
            "runtime": blocked_runtime,
            "malware_cdr": blocked_malware,
            "execution_gate_evidence_hash": HASHES[11],
        }
    )
    signer_policy, envelope = _sign_bundle(bundle)

    gate = build_preview_conversion_production_admission_gate(
        bundle=bundle,
        execution_gate=execution_gate,
        recovery_report=recovery_report,
        attestation_envelope=envelope,
        signer_policy=signer_policy,
        checked_at_utc=NOW,
    )

    assert gate.conversion_dispatch_allowed is False
    assert "evidence_bindings_not_verified" in gate.blocking_reasons
    assert "evidence_not_fresh" in gate.blocking_reasons
    assert "real_malware_cdr_services_not_verified" in gate.blocking_reasons


def test_viewer_evidence_rejects_same_origin_and_gate_remains_metadata_only() -> None:
    with pytest.raises(ValueError, match="separate origins"):
        _viewer().model_copy(update={"application_origin": VIEWER_ORIGIN}, deep=True).__class__.model_validate(
            {**_viewer().model_dump(mode="json"), "application_origin": VIEWER_ORIGIN}
        )

    recovery_report = _recovery_report()
    execution_gate = _execution_gate(recovery_report=recovery_report)
    bundle = _bundle(execution_gate=execution_gate, recovery_report=recovery_report)
    payload = json.dumps(bundle.model_dump(mode="json"), sort_keys=True)
    forbidden_keys = ("document_content", "source_bytes", "output_bytes", "private_key", "provider_credential")

    assert not any(key in payload for key in forbidden_keys)
    assert bundle.content_included is False
    assert bundle.secrets_included is False


def test_compose_worker_and_release_workflow_enforce_production_boundary() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    worker = compose.split("  preview-conversion-worker:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]
    admission = compose.split("  preview-conversion-production-admission-gate:", maxsplit=1)[1].split(
        "\n  preview-conversion-engine-smoke:", maxsplit=1
    )[0]
    workflow = Path(".github/workflows/release-provenance.yml").read_text(encoding="utf-8")

    assert "--production-admission-required" in worker
    assert "preview-conversion-production-admission-gate.json" in worker
    assert "./backups:/evidence:ro" in worker
    assert "--production-evidence" in worker
    assert "--production-recovery-report" in worker
    assert "--production-attestation" in worker
    assert "--production-signer-policy" in worker
    assert "./security:/trust:ro" in worker
    assert 'network_mode: "none"' in admission
    assert "read_only: true" in admission
    assert "cap_drop:\n      - ALL" in admission
    assert "./security:/trust:ro" in admission
    assert "Build preview renderer image" in workflow
    assert "collabio-preview-renderer.cdx.json" in workflow
    assert "Attest preview renderer provenance" in workflow
    assert "Attest preview renderer SBOM" in workflow
    assert "steps.preview-publish.outputs.digest" in workflow


def _recovery_report() -> DerivedPreviewRecoveryDrillReport:
    draft = DerivedPreviewRecoveryDrillReport(
        checked_at_utc=(NOW - timedelta(minutes=5)).isoformat(),
        backend_foundation_gate_hash=HASHES[0],
        postgres_restore_drill_report_hash=HASHES[1],
        backend_storage_foundation_gate_hash=HASHES[2],
        tenant_ids=("tenant-demo",),
        derived_preview_receipt_count=1,
        conversion_job_evidence_count=1,
        reconciled_item_count=1,
        recovery_item_evidence_hashes=(HASHES[3],),
        failed_job_evidence_hashes=(),
        orphaned_derived_preview_receipt_hashes=(),
        backend_foundation_verified=True,
        tenant_scope_verified=True,
        empty_state_verified=False,
        non_empty_recovery_verified=True,
        metadata_only_evidence_verified=True,
        recovery_ready=True,
        production_admission_evidence_ready=True,
        blocking_reasons=(),
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_derived_preview_recovery_drill_report_hash(draft)})


def _execution_gate(
    *, recovery_report: DerivedPreviewRecoveryDrillReport
) -> PreviewConversionExecutionGateEvidence:
    return build_preview_conversion_execution_gate(
        tenant_id="tenant-demo",
        worker_image_ref=IMAGE_REF,
        sandbox_runtime_class="runsc",
        sandbox_runtime_evidence_hash=HASHES[4],
        malware_scanner_profile_ref="clamav-clamd:production-v1",
        malware_scanner_evidence_hash=HASHES[5],
        cdr_profile_ref="cdr:pixel-reconstruction-v1",
        cdr_evidence_hash=HASHES[6],
        pdf_validator_profile_ref="qpdf-pdfinfo:production-v1",
        pdf_validator_evidence_hash=HASHES[7],
        font_baseline_hash=HASHES[8],
        backup_restore_evidence_hash=recovery_report.report_hash,
        viewer_origin=VIEWER_ORIGIN,
        viewer_csp_evidence_hash=HASHES[9],
        evaluated_at_utc=NOW - timedelta(minutes=10),
    )


def _bundle(
    *,
    execution_gate: PreviewConversionExecutionGateEvidence,
    recovery_report: DerivedPreviewRecoveryDrillReport,
) -> PreviewConversionProductionEvidenceBundle:
    return PreviewConversionProductionEvidenceBundle(
        tenant_id="tenant-demo",
        deployment_ref_hash=HASHES[10],
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        recovery_report_hash=recovery_report.report_hash,
        runtime=RuntimeIsolationEvidence(
            sandbox_runtime_class="runsc",
            host_profile_ref_hash=HASHES[0],
            runtime_version_ref_hash=HASHES[1],
            conformance_report_hash=execution_gate.sandbox_runtime_evidence_hash,
            isolation_test_report_hash=HASHES[2],
            production_host_profile_verified=True,
            no_network_egress_verified=True,
            read_only_root_filesystem_verified=True,
            non_root_user_verified=True,
            capabilities_dropped_verified=True,
            no_new_privileges_verified=True,
            ephemeral_workspace_verified=True,
            synthetic_runtime_used=False,
            observed_at_utc=NOW - timedelta(minutes=5),
        ),
        malware_cdr=MalwareCdrServiceEvidence(
            scanner_profile_ref=execution_gate.malware_scanner_profile_ref,
            scanner_service_deployment_ref_hash=HASHES[0],
            scanner_engine_version_ref_hash=HASHES[1],
            scanner_signature_set_hash=HASHES[2],
            scanner_evidence_hash=execution_gate.malware_scanner_evidence_hash,
            scanner_health_report_hash=HASHES[3],
            eicar_detection_report_hash=HASHES[4],
            cdr_profile_ref=execution_gate.cdr_profile_ref,
            cdr_service_deployment_ref_hash=HASHES[5],
            cdr_engine_version_ref_hash=HASHES[6],
            cdr_evidence_hash=execution_gate.cdr_evidence_hash,
            active_content_neutralization_report_hash=HASHES[7],
            real_services_invoked=True,
            tenant_routing_verified=True,
            signature_freshness_verified=True,
            quarantine_on_error_verified=True,
            cdr_fail_closed_verified=True,
            synthetic_provider_used=False,
            observed_at_utc=NOW - timedelta(minutes=5),
        ),
        supply_chain=WorkerImageSupplyChainEvidence(
            worker_image_ref=execution_gate.worker_image_ref,
            worker_image_digest=execution_gate.worker_image_digest,
            source_repository="https://github.com/kirchherr/collabio",
            source_revision="b" * 40,
            release_workflow_identity="kirchherr/collabio/.github/workflows/release-provenance.yml@refs/tags/v1.0.0",
            builder_id="https://github.com/actions/runner/github-hosted",
            provenance_bundle_hash=HASHES[0],
            sbom_bundle_hash=HASHES[1],
            trusted_root_hash=HASHES[2],
            provenance_verification_receipt_hash=HASHES[3],
            sbom_verification_receipt_hash=HASHES[4],
            vulnerability_scan_report_hash=HASHES[5],
            license_scan_report_hash=HASHES[6],
            provenance_signature_verified=True,
            provenance_subject_digest_verified=True,
            provenance_builder_identity_verified=True,
            provenance_source_repository_verified=True,
            sbom_signature_verified=True,
            sbom_subject_digest_verified=True,
            vulnerability_policy_passed=True,
            license_policy_passed=True,
            observed_at_utc=NOW - timedelta(minutes=5),
        ),
        viewer=_viewer(),
        release_approval_hash=HASHES[0],
        security_approval_hash=HASHES[1],
        operations_approval_hash=HASHES[2],
    )


def _viewer() -> ViewerIsolationEvidence:
    return ViewerIsolationEvidence(
        viewer_origin=VIEWER_ORIGIN,
        application_origin=APPLICATION_ORIGIN,
        pdfjs_release_ref="mozilla-pdfjs:5.4.149",
        pdfjs_bundle_hash=HASHES[0],
        viewer_deployment_ref_hash=HASHES[1],
        csp_evidence_hash=HASHES[9],
        browser_header_test_report_hash=HASHES[2],
        csp_directives=(
            "default-src 'none'",
            "base-uri 'none'",
            "object-src 'none'",
            "form-action 'none'",
            "script-src 'self'",
            "worker-src 'self' blob:",
            "connect-src 'self'",
            "img-src 'self' blob: data:",
            "font-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            f"frame-ancestors {APPLICATION_ORIGIN}",
        ),
        iframe_sandbox_tokens=("allow-scripts", "allow-same-origin"),
        separate_origin_verified=True,
        https_tls_verified=True,
        viewer_session_cookie_absent=True,
        viewer_service_worker_disabled=True,
        pdfjs_external_actions_disabled=True,
        browser_smoke_passed=True,
        synthetic_viewer_used=False,
        observed_at_utc=NOW - timedelta(minutes=5),
    )


def _sign_bundle(
    bundle: PreviewConversionProductionEvidenceBundle,
) -> tuple[PreviewConversionSignerPolicy, PreviewConversionAttestationEnvelope]:
    private_keys: dict[str, Ed25519PrivateKey] = {}
    signers: list[PreviewConversionTrustedSigner] = []
    for index, role in enumerate(SIGNER_ROLES, start=1):
        private_key = Ed25519PrivateKey.from_private_bytes(bytes([index]) * 32)
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        private_keys[role] = private_key
        signers.append(
            PreviewConversionTrustedSigner(
                key_id=sha256_bytes(public_key),
                principal_ref_hash="sha256:" + f"{index:x}" * 64,
                role=role,
                public_key_base64=base64.b64encode(public_key).decode("ascii"),
                valid_from_utc=NOW - timedelta(days=1),
                valid_until_utc=NOW + timedelta(days=1),
            )
        )
    policy = PreviewConversionSignerPolicy(trusted_signers=tuple(signers))
    statement = build_preview_conversion_attestation_statement(bundle=bundle, issued_at_utc=NOW)
    payload = build_preview_conversion_dsse_payload(statement)
    pae = build_dsse_pae(payload_type=DSSE_PAYLOAD_TYPE, payload=payload)
    signatures = tuple(
        DSSESignature(
            keyid=signer.key_id,
            sig=base64.b64encode(private_keys[signer.role].sign(pae)).decode("ascii"),
        )
        for signer in signers
    )
    return policy, PreviewConversionAttestationEnvelope(
        payload=base64.b64encode(payload).decode("ascii"),
        signatures=signatures,
    )


def _command(*, execution_gate: PreviewConversionExecutionGateEvidence) -> PreviewConversionCommand:
    draft = PreviewConversionCommand(
        tenant_id="tenant-demo",
        source_object_id="document-1",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        source_mime_type="application/rtf",
        source_manifest_hash=HASHES[0],
        source_content_hash=HASHES[1],
        source_content_byte_length=128,
        source_acl_version=1,
        preview_slot_id="document-body",
        preview_policy_id="document-preview.v1",
        adapter_id="canonical-pdf-libreoffice-pdfjs.v1",
        adapter_descriptor_hash=HASHES[2],
        adapter_plan_hash=HASHES[3],
        conversion_route="isolated_office_to_pdf",
        renderer_release_gate_evidence_hash=HASHES[4],
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        source_preflight_evidence_hash=HASHES[5],
        worker_image_ref=execution_gate.worker_image_ref,
        resource_limits=PreviewConversionResourceLimits(),
        input_filename="source.rtf",
        requested_by="user-demo",
        requested_at_utc=NOW,
        reason_hash=HASHES[6],
        idempotency_key_hash=HASHES[7],
        command_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"command_hash": build_preview_conversion_command_hash(draft)})


def _write_model(path: Path, model: BaseModel, *, by_alias: bool = False) -> None:
    path.write_text(
        json.dumps(model.model_dump(mode="json", by_alias=by_alias), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
