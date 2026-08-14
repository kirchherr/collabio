from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from suite.ai_control_plane.audit import stable_hash
from suite.operations.genoffice_docx_fidelity_evidence import verify_genoffice_docx_fidelity_evidence_bundle
from suite.operations.genoffice_docx_fidelity_study import (
    FIDELITY_ENGINE_IDS,
    ZERO_HASH,
    GenOfficeDocxFidelityEngineResultPayload,
    GenOfficeDocxFidelityResultSigner,
    GenOfficeDocxFidelityResultSignerPolicy,
    GenOfficeDocxFidelitySignedResultEnvelope,
    GenOfficeDocxFidelityStudyPlan,
    build_genoffice_docx_fidelity_result_message,
    build_genoffice_docx_fidelity_result_signer_policy_hash,
    build_genoffice_docx_fidelity_signed_result_envelope_hash,
)
from suite.operations.genoffice_docx_word_runner import (
    GenOfficeDocxWordHostReadinessReport,
    GenOfficeDocxWordInteractiveReceipt,
    GenOfficeDocxWordRunnerError,
    GenOfficeDocxWordRunRequest,
    RenderedRgbPage,
    WordCollectorIdentity,
    _RawOpenXmlReport,
    collect_genoffice_docx_word_assignment,
    materialize_genoffice_docx_word_assignment,
    persist_genoffice_docx_word_runner_schemas,
)

REQUESTED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
SCRIPT_PATH = Path("tools/windows/Invoke-CollabioWordFidelity.ps1")
BOOTSTRAP_SCRIPT_PATH = Path("tools/windows/Initialize-CollabioWordFidelityHost.ps1")
FONTS = ("Aptos", "Liberation Sans", "Times New Roman")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _write_model(path: Path, model: object) -> None:
    payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host_readiness(*, ready: bool = True) -> GenOfficeDocxWordHostReadinessReport:
    return GenOfficeDocxWordHostReadinessReport(
        observed_at_utc=REQUESTED_AT - timedelta(minutes=5),
        runner_script_sha256=_sha256(SCRIPT_PATH.read_bytes()),
        operator_account_sid_sha256="sha256:" + ("1" * 64),
        word_executable_sha256="sha256:" + ("2" * 64),
        word_version="16.0.20228.20158",
        windows_product_name="Windows 11 Pro",
        windows_display_version="24H2",
        windows_build="26100.4946",
        process_architecture="x64",
        powershell_version="5.1.26100.4652",
        font_inventory=FONTS,
        font_count=len(FONTS),
        normalized_font_inventory_sha256=stable_hash("\n".join(FONTS)),
        network_isolation_rule_sha256="sha256:" + ("3" * 64),
        dedicated_local_account_verified=ready,
        interactive_user_session_verified=True,
        session_zero_absent=True,
        office_identity_absent=True,
        tenant_credentials_available=False,
        signing_custody_accessible=False,
        winword_installed=True,
        outbound_firewall_block_verified=True,
        word_process_absent=True,
        host_ready=ready,
        blocking_reasons=() if ready else ("dedicated_local_account_not_verified",),
    )


class FakeWordCollectorToolchain:
    def __init__(self, *, mismatched_dimensions: bool = False) -> None:
        self.mismatched_dimensions = mismatched_dimensions

    def identity(self) -> WordCollectorIdentity:
        return WordCollectorIdentity(
            rasterizer_version="pdftoppm version 25.12.0",
            validator_version="3.5.1",
            collector_identity_hash="sha256:" + ("4" * 64),
        )

    def rasterize_pdf(self, *, pdf_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]:
        assert pdf_path.is_file()
        assert workspace.is_dir()
        if self.mismatched_dimensions and stage == "candidate":
            return (RenderedRgbPage(1, 1, 1, bytes((255, 255, 255))),)
        return (RenderedRgbPage(1, 2, 1, bytes((255, 255, 255, 0, 0, 0))),)

    def validate_openxml(self, *, docx_path: Path) -> _RawOpenXmlReport:
        assert docx_path.is_file()
        return _RawOpenXmlReport(
            validator_name="DocumentFormat.OpenXml",
            validator_version="3.5.1",
            target_file_format_version="Office2021",
            markup_compatibility_processing_enabled=True,
            findings=(),
        )


def _prepare(
    tmp_path: Path,
) -> tuple[Path, Path, Path, GenOfficeDocxWordRunRequest, GenOfficeDocxWordHostReadinessReport]:
    assignment = tmp_path / "assignment"
    handoff = tmp_path / "interactive-handoff"
    output = tmp_path / "output"
    host_path = tmp_path / "host-readiness-report.json"
    for directory in (assignment, handoff, output):
        directory.mkdir()
    host = _host_readiness()
    _write_model(host_path, host)
    request = materialize_genoffice_docx_word_assignment(
        output_directory=assignment,
        fixture_id="formatting-table-fidelity",
        host_readiness_report_path=host_path,
        runner_script_path=SCRIPT_PATH,
        requested_at_utc=REQUESTED_AT,
    )
    return assignment, handoff, output, request, host


def _materialize_interactive_handoff(
    *,
    assignment: Path,
    handoff: Path,
    request: GenOfficeDocxWordRunRequest,
    host: GenOfficeDocxWordHostReadinessReport,
) -> GenOfficeDocxWordInteractiveReceipt:
    source = (assignment / "input" / request.source_filename).read_bytes()
    reference_pdf = b"%PDF-1.7\nsynthetic-reference\n%%EOF\n"
    candidate_pdf = b"%PDF-1.7\nsynthetic-candidate\n%%EOF\n"
    (handoff / "output.docx").write_bytes(source)
    (handoff / "reference.pdf").write_bytes(reference_pdf)
    (handoff / "candidate.pdf").write_bytes(candidate_pdf)
    receipt = GenOfficeDocxWordInteractiveReceipt(
        assignment_id=request.assignment_id,
        run_request_hash=request.request_hash,
        host_readiness_report_sha256=request.host_readiness_report_sha256,
        runner_script_sha256=request.runner_script_sha256,
        operator_account_sid_sha256=request.operator_account_sid_sha256,
        word_executable_sha256=request.word_executable_sha256,
        network_isolation_rule_sha256=request.network_isolation_rule_sha256,
        source_content_sha256=request.source_content_sha256,
        output_docx_sha256=_sha256(source),
        reference_pdf_sha256=_sha256(reference_pdf),
        candidate_pdf_sha256=_sha256(candidate_pdf),
        word_version=host.word_version,
        windows_product_name=host.windows_product_name,
        windows_display_version=host.windows_display_version,
        windows_build=host.windows_build,
        process_architecture=host.process_architecture,
        powershell_version=host.powershell_version,
        font_inventory=host.font_inventory,
        font_count=host.font_count,
        normalized_font_inventory_sha256=host.normalized_font_inventory_sha256,
        started_at_utc=REQUESTED_AT + timedelta(minutes=1),
        human_confirmed_at_utc=REQUESTED_AT + timedelta(minutes=2),
        completed_at_utc=REQUESTED_AT + timedelta(minutes=3),
    )
    _write_model(handoff / "word-interactive-receipt.json", receipt)
    return receipt


def _sign_and_verify(assignment: Path, output: Path) -> None:
    payload = GenOfficeDocxFidelityEngineResultPayload.model_validate_json(
        (output / "handoff" / "result-payload.json").read_text(encoding="utf-8")
    )
    message = (output / "handoff" / "result-signature-message.bin").read_bytes()
    assert message == build_genoffice_docx_fidelity_result_message(payload)
    private_keys = {
        engine_id: Ed25519PrivateKey.from_private_bytes(bytes((index,)) * 32)
        for index, engine_id in enumerate(FIDELITY_ENGINE_IDS, start=17)
    }
    signers = tuple(
        GenOfficeDocxFidelityResultSigner(
            signer_id=f"{engine_id}-study-runner",
            key_id=f"{engine_id}-study-key-01",
            engine_id=engine_id,
            ed25519_public_key_base64=base64.b64encode(
                private_keys[engine_id]
                .public_key()
                .public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii"),
        )
        for engine_id in FIDELITY_ENGINE_IDS
    )
    signer = next(item for item in signers if item.engine_id == "microsoft_word")
    policy_draft = GenOfficeDocxFidelityResultSignerPolicy(
        policy_id="word-study-test-signers",
        effective_at_utc=REQUESTED_AT,
        signers=signers,
        policy_hash=ZERO_HASH,
    )
    policy = policy_draft.model_copy(
        update={"policy_hash": build_genoffice_docx_fidelity_result_signer_policy_hash(policy_draft)}
    )
    envelope_draft = GenOfficeDocxFidelitySignedResultEnvelope(
        signer_policy_hash=policy.policy_hash,
        payload=payload,
        signer_id=signer.signer_id,
        key_id=signer.key_id,
        signature_base64=base64.b64encode(private_keys["microsoft_word"].sign(message)).decode("ascii"),
        envelope_hash=ZERO_HASH,
    )
    envelope = envelope_draft.model_copy(
        update={"envelope_hash": build_genoffice_docx_fidelity_signed_result_envelope_hash(envelope_draft)}
    )
    study_plan = GenOfficeDocxFidelityStudyPlan.model_validate_json(
        (assignment / "control" / "study-plan.json").read_text(encoding="utf-8")
    )
    verified = verify_genoffice_docx_fidelity_evidence_bundle(
        evidence_root=output / "evidence",
        envelope=envelope,
        signer_policy=policy,
        study_plan=study_plan,
    )
    assert verified.referenced_evidence_content_verified is True
    assert verified.open_xml_schema_conformant is True
    assert verified.compatibility_claim_allowed is False


def test_word_collector_materializes_unsigned_evidence_for_independent_verification(tmp_path: Path) -> None:
    assignment, handoff, output, request, host = _prepare(tmp_path)
    _materialize_interactive_handoff(assignment=assignment, handoff=handoff, request=request, host=host)

    report = collect_genoffice_docx_word_assignment(
        input_root=assignment,
        interactive_handoff_root=handoff,
        output_root=output,
        toolchain=FakeWordCollectorToolchain(),
        now_utc=REQUESTED_AT + timedelta(minutes=4),
    )

    assert report.interactive_engine_execution_verified is True
    assert report.source_blind_collection_verified is True
    assert report.result_signed is False
    assert report.compatibility_claim_allowed is False
    assert tuple(sorted(path.name for path in output.iterdir())) == ("evidence", "handoff")
    assert tuple(sorted(path.name for path in (output / "evidence").iterdir())) == (
        "candidate-cdr",
        "execution-receipt.json",
        "font-baseline-report.json",
        "openxml-validation-report.json",
        "output-preflight-report.json",
        "output-structural-fingerprint-report.json",
        "output.docx",
        "reference-cdr",
        "visual-comparison-manifest.json",
    )
    _sign_and_verify(assignment, output)


def test_word_assignment_is_exact_write_once_and_requires_ready_host(tmp_path: Path) -> None:
    assignment, _, _, request, _ = _prepare(tmp_path)

    assert request.assignment_id == "microsoft_word:formatting-table-fidelity"
    assert request.interactive_user_session_required is True
    assert request.unattended_execution_allowed is False
    assert request.tenant_content_allowed is False
    assert request.private_key_allowed is False
    assert tuple(sorted(path.name for path in assignment.iterdir())) == ("control", "input", "runner")
    assert tuple(path.name for path in (assignment / "runner").iterdir()) == (SCRIPT_PATH.name,)
    with pytest.raises(GenOfficeDocxWordRunnerError, match="output directory is not empty"):
        materialize_genoffice_docx_word_assignment(
            output_directory=assignment,
            fixture_id="formatting-table-fidelity",
            host_readiness_report_path=tmp_path / "host-readiness-report.json",
            runner_script_path=SCRIPT_PATH,
            requested_at_utc=REQUESTED_AT,
        )

    blocked_path = tmp_path / "blocked-host.json"
    blocked_output = tmp_path / "blocked-output"
    blocked_output.mkdir()
    _write_model(blocked_path, _host_readiness(ready=False))
    with pytest.raises(GenOfficeDocxWordRunnerError, match="host is not ready"):
        materialize_genoffice_docx_word_assignment(
            output_directory=blocked_output,
            fixture_id="formatting-table-fidelity",
            host_readiness_report_path=blocked_path,
            runner_script_path=SCRIPT_PATH,
            requested_at_utc=REQUESTED_AT,
        )


def test_word_collector_rejects_tampering_expiry_and_page_drift(tmp_path: Path) -> None:
    assignment, handoff, output, request, host = _prepare(tmp_path)
    _materialize_interactive_handoff(assignment=assignment, handoff=handoff, request=request, host=host)
    (handoff / "candidate.pdf").write_bytes(b"tampered")
    with pytest.raises(GenOfficeDocxWordRunnerError, match="handoff binding drifted"):
        collect_genoffice_docx_word_assignment(
            input_root=assignment,
            interactive_handoff_root=handoff,
            output_root=output,
            toolchain=FakeWordCollectorToolchain(),
            now_utc=REQUESTED_AT + timedelta(minutes=4),
        )

    (handoff / "candidate.pdf").write_bytes(b"%PDF-1.7\nsynthetic-candidate\n%%EOF\n")
    with pytest.raises(GenOfficeDocxWordRunnerError, match="assignment binding or lifetime drifted"):
        collect_genoffice_docx_word_assignment(
            input_root=assignment,
            interactive_handoff_root=handoff,
            output_root=output,
            toolchain=FakeWordCollectorToolchain(),
            now_utc=REQUESTED_AT + timedelta(hours=9),
        )
    with pytest.raises(GenOfficeDocxWordRunnerError, match="pages do not align"):
        collect_genoffice_docx_word_assignment(
            input_root=assignment,
            interactive_handoff_root=handoff,
            output_root=output,
            toolchain=FakeWordCollectorToolchain(mismatched_dimensions=True),
            now_utc=REQUESTED_AT + timedelta(minutes=4),
        )

    (assignment / "control" / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(GenOfficeDocxWordRunnerError, match="control inventory is not exact"):
        collect_genoffice_docx_word_assignment(
            input_root=assignment,
            interactive_handoff_root=handoff,
            output_root=output,
            toolchain=FakeWordCollectorToolchain(),
            now_utc=REQUESTED_AT + timedelta(minutes=4),
        )


def test_word_schemas_match_versioned_operations_contracts(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()

    hashes = persist_genoffice_docx_word_runner_schemas(schema_dir)

    assert tuple(sorted(hashes)) == (
        "genoffice-docx-word-collector-report.schema.json",
        "genoffice-docx-word-host-readiness-report.schema.json",
        "genoffice-docx-word-interactive-receipt.schema.json",
        "genoffice-docx-word-run-request.schema.json",
    )
    for filename, digest in hashes.items():
        assert digest == _sha256((schema_dir / filename).read_bytes())
        assert (schema_dir / filename).read_bytes() == (Path("docs/operations") / filename).read_bytes()
    with pytest.raises(GenOfficeDocxWordRunnerError, match="schema output directory is not empty"):
        persist_genoffice_docx_word_runner_schemas(schema_dir)


def test_word_runner_and_collector_are_interactive_isolated_and_key_free() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    git_attributes = Path(".gitattributes").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "$word.AutomationSecurity = 3" in script
    assert "$word.Visible = $true" in script
    assert "$ExpectedFixtureHashes" in script
    assert "$ExpectedStudyPlanHash" in script
    assert "Get-ModelHash -Value $corpus" in script
    assert "Get-ModelHash -Value $studyPlan" in script
    assert "Documents.Open($SourcePath, $false, $true, $false)" in script
    assert "MessageBox]::Show" in script
    assert ".SaveAs2(" in script
    assert script.count(".ExportAsFixedFormat(") == 2
    assert "Start-Job" not in script
    assert "Register-ScheduledTask" not in script
    assert "Ed25519" not in script
    assert "*.ps1 text eol=crlf" in git_attributes
    assert "tools/windows/Invoke-CollabioWordFidelity.ps1 text eol=lf" in git_attributes
    assert "AS word-fidelity-collector" in dockerfile
    prepare = compose.split("  genoffice-docx-fidelity-word-prepare:", 1)[1].split(
        "\n  genoffice-docx-fidelity-word-collector-image:", 1
    )[0]
    collector = compose.split("  genoffice-docx-fidelity-word-collector:", 1)[1].split(
        "\n  genoffice-docx-fidelity-evidence-schema:", 1
    )[0]
    assert 'network_mode: "none"' in prepare
    assert "Invoke-CollabioWordFidelity.ps1" in prepare
    assert "runtime: ${SUITE_GENOFFICE_FIDELITY_WORD_SANDBOX_RUNTIME:-runsc-kvm}" in collector
    assert 'network_mode: "none"' in collector
    assert "read_only: true" in collector
    assert "cap_drop:\n      - ALL" in collector
    assert "no-new-privileges:true" in collector
    assert collector.count("read_only: true") == 3
    assert "create_host_path: false" in collector
    assert "docker.sock" not in collector
    assert "signing" not in collector.lower()


def test_word_host_bootstrap_is_explicit_idempotent_and_secret_free() -> None:
    script = BOOTSTRAP_SCRIPT_PATH.read_text(encoding="utf-8")
    purpose = re.search(r'^\$PurposeDescription = "([^"]+)"$', script, flags=re.MULTILINE)

    assert '[ValidateSet("Audit", "Apply")]' in script
    assert purpose is not None
    assert len(purpose.group(1)) <= 48
    assert 'Read-Host "Enter the dedicated local runner password" -AsSecureString' in script
    assert 'Read-Host "Confirm the dedicated local runner password" -AsSecureString' in script
    assert "SecureStringToBSTR" in script
    assert "ZeroFreeBSTR" in script
    assert "GetNetworkCredential" not in script
    assert "ConvertFrom-SecureString" not in script
    assert "password_included = $false" in script
    assert 'throw "Apply mode requires an elevated Windows PowerShell session."' in script
    assert "-AdoptExistingAccount after manual review" in script
    assert "-ReplaceDriftedFirewallRule after manual review" in script
    assert "Remove-LocalGroupMember" in script
    assert "-Member $account.SID" not in script
    assert script.count("-Member $account") == 2
    assert 'SecurityIdentifier]::new("S-1-5-32-545")' in script
    assert 'SecurityIdentifier]::new("S-1-5-32-544")' in script
    assert "SetAccessRuleProtection($true, $false)" in script
    assert "$normalizedModifyRights" in script
    assert ").FileSystemRights)" in script
    assert "PurgeAccessRules($RunnerSid)" in script
    assert "AccessControlType]::Deny" in script
    assert '$FirewallRuleName = "Collabio Word fidelity outbound deny"' in script
    assert "New-NetFirewallRule" in script
    assert "-Direction Outbound -Action Block" in script
    assert "-RemoteAddress Any -Profile Any -Enabled True" in script
    assert "[IO.FileMode]::CreateNew" in script
    assert 'schema_version = "genoffice_docx_word_host_bootstrap_report.v1"' in script
    assert "tenant_content_included = $false" in script
    assert "private_key_included = $false" in script
    assert "Register-ScheduledTask" not in script
    assert "Start-Process" not in script
