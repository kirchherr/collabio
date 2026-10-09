from __future__ import annotations

import base64
import hashlib
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.genoffice_legal_review_dossier import (
    GenOfficeLegalReviewDossierReport,
    load_genoffice_legal_review_dossier,
)
from suite.operations.genoffice_solo_founder_exception import (
    GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS,
    GenOfficeSoloFounderExceptionError,
    GenOfficeSoloFounderExceptionRequest,
    GenOfficeSoloFounderPolicy,
    GenOfficeSoloFounderSignatureResponse,
    build_genoffice_solo_founder_policy,
    build_genoffice_solo_founder_request,
    build_genoffice_solo_founder_response_hash,
    build_genoffice_solo_founder_signature_message,
    persist_genoffice_solo_founder_request,
    verify_genoffice_solo_founder_exception,
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
    *, valid_for: timedelta = timedelta(days=7)
) -> tuple[
    GenOfficeLegalReviewDossierReport,
    GenOfficeThirdPartyNoticeReport,
    bytes,
    GenOfficeSoloFounderPolicy,
    GenOfficeSoloFounderExceptionRequest,
    GenOfficeSoloFounderSignatureResponse,
    datetime,
]:
    dossier = load_genoffice_legal_review_dossier(EVIDENCE / "genoffice_legal_review_dossier_report.json")
    notice = b"Collabio deterministic third-party notice\n"
    notice_report = _notice_report(dossier=dossier, notice=notice)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    issued_at = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    policy = build_genoffice_solo_founder_policy(
        policy_id="solo-founder-policy-test",
        effective_at_utc=issued_at - timedelta(minutes=1),
        signer_id="founder-1",
        key_id="founder-key-1",
        public_key=public_key,
    )
    request, message = build_genoffice_solo_founder_request(
        dossier=dossier,
        notice_report=notice_report,
        notice_artifact=notice,
        policy=policy,
        exception_id="solo-founder-exception-test",
        issued_at_utc=issued_at,
        valid_until_utc=issued_at + valid_for,
        risk_acceptance_ref="risk:solo-founder-test",
        change_control_ref="change:solo-founder-test",
    )
    response = GenOfficeSoloFounderSignatureResponse(
        request_hash=request.request_hash,
        signature_message_sha256=request.signature_message_sha256,
        signer_id=policy.signer.signer_id,
        key_id=policy.signer.key_id,
        signature_base64=base64.b64encode(private_key.sign(message)).decode("ascii"),
    )
    return dossier, notice_report, notice, policy, request, response, issued_at


def test_solo_founder_exception_opens_only_expiring_build_context_materialization() -> None:
    dossier, notice_report, notice, policy, request, response, issued_at = _signed_fixture()

    report = verify_genoffice_solo_founder_exception(
        dossier=dossier,
        notice_report=notice_report,
        notice_artifact=notice,
        policy=policy,
        request=request,
        response=response,
        verified_at_utc=issued_at + timedelta(hours=1),
    )

    assert report.compensating_controls == GENOFFICE_SOLO_FOUNDER_COMPENSATING_CONTROLS
    assert report.signature_response_hash == build_genoffice_solo_founder_response_hash(response)
    assert report.solo_founder_risk_acceptance_verified is True
    assert report.two_person_control_verified is False
    assert report.development_build_context_materialization_allowed is True
    assert report.reproducible_worker_build_allowed is True
    assert report.source_import_allowed is False
    assert report.engine_execution_allowed is False
    assert report.hosted_service_allowed is False
    assert report.on_prem_distribution_allowed is False
    assert report.production_use_allowed is False
    assert report.tenant_content_allowed is False


def test_solo_founder_exception_rejects_expired_and_overlong_windows() -> None:
    dossier, notice_report, notice, policy, request, response, issued_at = _signed_fixture()

    with pytest.raises(GenOfficeSoloFounderExceptionError, match="not currently valid"):
        verify_genoffice_solo_founder_exception(
            dossier=dossier,
            notice_report=notice_report,
            notice_artifact=notice,
            policy=policy,
            request=request,
            response=response,
            verified_at_utc=issued_at + timedelta(days=8),
        )

    with pytest.raises(ValueError, match="validity window"):
        _signed_fixture(valid_for=timedelta(days=31))


def test_solo_founder_exception_rejects_replay_assignment_and_signature_tampering() -> None:
    dossier, notice_report, notice, policy, request, response, issued_at = _signed_fixture()

    for changed_response, expected_error in (
        (response.model_copy(update={"request_hash": "sha256:" + "f" * 64}), "another request"),
        (response.model_copy(update={"signer_id": "other-founder"}), "violates its assignment"),
        (
            response.model_copy(update={"signature_base64": base64.b64encode(b"x" * 64).decode("ascii")}),
            "detached signature is invalid",
        ),
    ):
        with pytest.raises(GenOfficeSoloFounderExceptionError, match=expected_error):
            verify_genoffice_solo_founder_exception(
                dossier=dossier,
                notice_report=notice_report,
                notice_artifact=notice,
                policy=policy,
                request=request,
                response=changed_response,
                verified_at_utc=issued_at + timedelta(hours=1),
            )


def test_solo_founder_request_persistence_is_private_and_write_once(tmp_path: Path) -> None:
    _, _, _, _, request, _, _ = _signed_fixture()
    request_path = tmp_path / "request.json"
    message_path = tmp_path / "message.json"
    message = build_genoffice_solo_founder_signature_message(request.payload)
    persist_genoffice_solo_founder_request(
        request=request,
        message=message,
        request_path=request_path,
        message_path=message_path,
    )

    assert stat.S_IMODE(request_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(message_path.stat().st_mode) == 0o600
    with pytest.raises(GenOfficeSoloFounderExceptionError, match="already exists"):
        persist_genoffice_solo_founder_request(
            request=request,
            message=message,
            request_path=request_path,
            message_path=tmp_path / "other-message.json",
        )


def test_solo_founder_module_uses_kms_adapter_without_network_process_or_private_key_path() -> None:
    module_source = Path("app/suite/operations/genoffice_solo_founder_exception.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "socket", "httpx", "requests", "urllib", "cryptography"):
        assert f"import {forbidden}" not in module_source
    assert "from suite.kms.signatures import" in module_source
    assert "private_key_ingestion_allowed: Literal[False]" in module_source
    assert "two_person_control_verified: Literal[False]" in module_source


def test_solo_founder_response_schema_rejects_content_secret_and_private_key_flags() -> None:
    _, _, _, _, request, response, _ = _signed_fixture()
    payload = response.model_dump(mode="json")
    payload["private_key_included"] = True

    with pytest.raises(ValueError):
        GenOfficeSoloFounderSignatureResponse.model_validate(payload)
    assert request.private_key_ingestion_allowed is False
    assert json.loads(request.model_dump_json())["content_included"] is False


def test_solo_founder_compose_services_are_offline_read_only_and_fail_closed_on_missing_binds() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("  genoffice-solo-founder-schema:", maxsplit=1)[1].split(
        "\n  genoffice-development-build-context:", maxsplit=1
    )[0]

    assert block.count('network_mode: "none"') == 4
    assert block.count("read_only: true") >= 6
    assert block.count("no-new-privileges:true") == 4
    assert "private" not in block.lower()
    assert "solo-founder.ed25519.pub" in block
    assert "solo-founder.signature-response.json" in block
    assert block.count("create_host_path: false") == 2


def test_committed_solo_founder_schemas_are_hash_bound_without_fake_exception() -> None:
    expected = {
        "genoffice-solo-founder-policy.schema.json": (
            "sha256:cdf92f45582075b0f8243ddaba901fa5b7764bd8a00c8936539a473fc6cd0dc5"
        ),
        "genoffice-solo-founder-exception-request.schema.json": (
            "sha256:c0c60ea6ca9373b7386c80b02f4a8ba1022067e648c4c1de7f0d18cd8364289d"
        ),
        "genoffice-solo-founder-signature-response.schema.json": (
            "sha256:ecc383929958ab0d30c4c494ad43b571436ae337c9161e090872b25109c6e561"
        ),
        "genoffice-solo-founder-exception-report.schema.json": (
            "sha256:ee312047b6a3f20a88caa2a1be37864518f05db59988a6ff3add9bc2ae46921a"
        ),
    }

    for filename, expected_hash in expected.items():
        schema = json.loads((EVIDENCE / filename).read_text(encoding="utf-8"))
        assert stable_hash(canonical_json(schema)) == expected_hash
    assert not (EVIDENCE / "genoffice-solo-founder-policy.json").exists()
    assert not (EVIDENCE / "genoffice-solo-founder-exception-request.json").exists()
    assert not (EVIDENCE / "genoffice-solo-founder-exception-report.json").exists()
