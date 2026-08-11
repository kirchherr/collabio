from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.ai_control_plane.audit import canonical_json
from suite.operations.genoffice_internal_oss_admission import (
    GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
    GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
    GenOfficeInternalOssAdmissionError,
    GenOfficeInternalOssDecisionEnvelope,
    GenOfficeInternalOssDecisionPayload,
    GenOfficeInternalOssDetachedApproval,
    GenOfficeInternalOssSigner,
    GenOfficeInternalOssSignerPolicy,
    build_genoffice_internal_oss_dependency_resolutions,
    build_genoffice_internal_oss_payload_hash,
    build_genoffice_internal_oss_record_hash,
    build_genoffice_internal_oss_signer_policy_hash,
    run_genoffice_internal_oss_admission_from_environment,
    verify_genoffice_internal_oss_admission,
)
from suite.operations.genoffice_legal_review_dossier import (
    GENOFFICE_REQUIRED_TRADEMARK_POLICY,
    GenOfficeLegalReviewDossierReport,
    load_genoffice_legal_review_dossier,
)
from suite.operations.genoffice_third_party_notice import (
    GENOFFICE_SELECTED_SOURCE_SCOPE,
    GenOfficeThirdPartyNoticeComponent,
    GenOfficeThirdPartyNoticeReport,
    build_genoffice_third_party_notice_report_hash,
)

EVIDENCE = Path("docs/operations")


def _notice_report(*, dossier: GenOfficeLegalReviewDossierReport, notice: bytes) -> GenOfficeThirdPartyNoticeReport:
    components = tuple(
        GenOfficeThirdPartyNoticeComponent(
            component_name=f"component-{index:02d}",
            component_version="1.0.0",
            declared_license_expression="MIT",
            selected_distribution_license_expression="MIT",
            source_artifact_sha256="sha256:" + f"{index:064x}",
            included_files=(),
        )
        for index in range(23)
    )
    draft = GenOfficeThirdPartyNoticeReport(
        legal_dossier_report_hash=dossier.report_hash,
        license_material_collection_report_hash=dossier.license_material_collection_report_hash,
        source_archive_sha256=dossier.source_archive_sha256,
        selected_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        enterprise_scope_excluded=True,
        collabio_brand_only=True,
        component_count=23,
        included_legal_file_count=0,
        components=components,
        notice_artifact_size_bytes=len(notice),
        notice_artifact_sha256=f"sha256:{hashlib.sha256(notice).hexdigest()}",
        deterministic_render_verified=True,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_genoffice_third_party_notice_report_hash(draft)})


def _signed_fixture(
    *,
    same_signer: bool = False,
    jszip_license: str = "MIT",
) -> tuple[
    GenOfficeInternalOssDecisionEnvelope,
    GenOfficeInternalOssSignerPolicy,
    GenOfficeThirdPartyNoticeReport,
    bytes,
]:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    notice = b"Collabio deterministic third-party notice\n"
    notice_report = _notice_report(dossier=dossier, notice=notice)
    resolutions = list(build_genoffice_internal_oss_dependency_resolutions(dossier))
    jszip_index = next(index for index, item in enumerate(resolutions) if item.package_name == "jszip")
    resolutions[jszip_index] = resolutions[jszip_index].model_copy(
        update={"selected_distribution_license_expression": jszip_license}
    )
    payload_draft = GenOfficeInternalOssDecisionPayload(
        decision_id="oss-decision-test",
        decision="approved_for_development_evaluation",
        decided_at_utc=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        risk_acceptance_ref="risk:test",
        change_control_ref="change:test",
        legal_dossier_report_hash=dossier.report_hash,
        third_party_notice_report_hash=notice_report.report_hash,
        third_party_notice_artifact_sha256=notice_report.notice_artifact_sha256,
        approved_usage_profiles=("development_evaluation",),
        blocked_usage_profiles=GENOFFICE_INTERNAL_OSS_BLOCKED_PROFILES,
        approved_source_scopes=(GENOFFICE_SELECTED_SOURCE_SCOPE,),
        prohibited_source_scopes=GENOFFICE_INTERNAL_OSS_PROHIBITED_SCOPES,
        trademark_policy=GENOFFICE_REQUIRED_TRADEMARK_POLICY,
        apache_2_0_terms_accepted=True,
        apache_notice_preservation_required=True,
        apache_patent_terms_acknowledged=True,
        enterprise_scope_excluded=True,
        jszip_selected_license_expression=jszip_license,
        pako_selected_license_expression="MIT AND Zlib",
        dependency_license_resolutions=tuple(resolutions),
        reevaluation_triggers=(
            "source_commit_change",
            "source_scope_change",
            "dependency_or_license_change",
            "notice_artifact_change",
            "trademark_use_change",
            "usage_profile_change",
            "signer_policy_change",
        ),
        payload_hash="sha256:" + "0" * 64,
    )
    payload = payload_draft.model_copy(update={"payload_hash": build_genoffice_internal_oss_payload_hash(payload_draft)})
    private_keys = (Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate())
    signer_ids = ("person-a", "person-a" if same_signer else "person-b")
    roles = ("product_owner", "security_compliance_owner")
    signers = tuple(
        GenOfficeInternalOssSigner(
            signer_id=signer_ids[index],
            signer_role=roles[index],
            key_id=f"key-{index}",
            ed25519_public_key_base64=base64.b64encode(
                private_keys[index].public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii"),
            active=True,
        )
        for index in range(2)
    )
    policy_draft = GenOfficeInternalOssSignerPolicy(
        policy_id="oss-signers-test",
        effective_at_utc=datetime(2026, 8, 11, 11, 0, tzinfo=UTC),
        signers=signers,
        policy_hash="sha256:" + "0" * 64,
    )
    policy = policy_draft.model_copy(
        update={"policy_hash": build_genoffice_internal_oss_signer_policy_hash(policy_draft)}
    )
    message = canonical_json(payload.model_dump(mode="json")).encode("utf-8")
    approvals = tuple(
        GenOfficeInternalOssDetachedApproval(
            signer_id=signer_ids[index],
            signer_role=roles[index],
            key_id=f"key-{index}",
            signature_base64=base64.b64encode(private_keys[index].sign(message)).decode("ascii"),
        )
        for index in range(2)
    )
    envelope_draft = GenOfficeInternalOssDecisionEnvelope(
        payload=payload,
        approvals=approvals,
        record_hash="sha256:" + "0" * 64,
    )
    envelope = envelope_draft.model_copy(
        update={"record_hash": build_genoffice_internal_oss_record_hash(envelope_draft)}
    )
    return envelope, policy, notice_report, notice


def test_internal_oss_admission_opens_only_development_worker_build() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    envelope, policy, notice_report, notice = _signed_fixture()

    report = verify_genoffice_internal_oss_admission(
        dossier=dossier,
        notice_report=notice_report,
        notice_artifact=notice,
        envelope=envelope,
        signer_policy=policy,
    )

    assert report.two_person_control_verified is True
    assert report.detached_signatures_verified is True
    assert report.reproducible_worker_build_allowed is True
    assert report.source_import_allowed is False
    assert report.engine_execution_allowed is False
    assert report.hosted_service_allowed is False
    assert report.on_prem_distribution_allowed is False
    assert report.production_use_allowed is False
    assert report.tenant_content_allowed is False


def test_internal_oss_admission_rejects_same_person_in_both_roles() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    envelope, policy, notice_report, notice = _signed_fixture(same_signer=True)

    with pytest.raises(GenOfficeInternalOssAdmissionError, match="two-person"):
        verify_genoffice_internal_oss_admission(
            dossier=dossier,
            notice_report=notice_report,
            notice_artifact=notice,
            envelope=envelope,
            signer_policy=policy,
        )


def test_internal_oss_admission_rejects_unapproved_compound_license_choice() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    envelope, policy, notice_report, notice = _signed_fixture(jszip_license="GPL-3.0-or-later")

    with pytest.raises(GenOfficeInternalOssAdmissionError, match="scope or policy"):
        verify_genoffice_internal_oss_admission(
            dossier=dossier,
            notice_report=notice_report,
            notice_artifact=notice,
            envelope=envelope,
            signer_policy=policy,
        )


def test_internal_oss_admission_rejects_notice_tampering() -> None:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    envelope, policy, notice_report, notice = _signed_fixture()

    with pytest.raises(GenOfficeInternalOssAdmissionError, match="notice artifact hash"):
        verify_genoffice_internal_oss_admission(
            dossier=dossier,
            notice_report=notice_report,
            notice_artifact=notice + b"tampered",
            envelope=envelope,
            signer_policy=policy,
        )


def test_internal_oss_environment_runner_requires_all_paths() -> None:
    with pytest.raises(GenOfficeInternalOssAdmissionError, match="paths are missing"):
        run_genoffice_internal_oss_admission_from_environment({})


def test_internal_oss_admission_uses_kms_adapter_and_has_no_network_or_process_path() -> None:
    module_source = Path("app/suite/operations/genoffice_internal_oss_admission.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "cryptography"):
        assert f"import {forbidden}" not in module_source
    assert "from suite.kms.signatures import" in module_source
    assert "production_use_allowed: bool = False" in module_source


def test_internal_oss_compose_services_are_offline_and_read_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    schema_service = compose.split("  genoffice-internal-oss-schema:", maxsplit=1)[1].split(
        "\n  genoffice-internal-oss-admission:", maxsplit=1
    )[0]
    admission_service = compose.split("  genoffice-internal-oss-admission:", maxsplit=1)[1].split(
        "\n  genoffice-docx-prebuild-sbom:", maxsplit=1
    )[0]

    for service in (schema_service, admission_service):
        assert 'network_mode: "none"' in service
        assert "read_only: true" in service
        assert "no-new-privileges:true" in service
    assert "genoffice-internal-oss-decision.json" in admission_service
    assert "genoffice-internal-oss-signer-policy.json" in admission_service
