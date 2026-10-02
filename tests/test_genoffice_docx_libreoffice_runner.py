from __future__ import annotations

import base64
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
from suite.operations.genoffice_docx_libreoffice_runner import (
    GenOfficeDocxLibreOfficeRunnerError,
    LibreOfficeToolIdentity,
    RenderedRgbPage,
    SystemLibreOfficeFidelityToolchain,
    _RawOpenXmlReport,
    materialize_genoffice_docx_libreoffice_assignment,
    persist_genoffice_docx_libreoffice_runner_schemas,
    run_genoffice_docx_libreoffice_assignment,
)

REQUESTED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
RUNNER_IMAGE = "collabio/libreoffice-fidelity@sha256:" + ("a" * 64)


class FakeLibreOfficeToolchain:
    def __init__(self, *, mismatched_dimensions: bool = False) -> None:
        self.mismatched_dimensions = mismatched_dimensions

    def identity(self, *, runner_image_ref: str) -> LibreOfficeToolIdentity:
        assert runner_image_ref == RUNNER_IMAGE
        return LibreOfficeToolIdentity(
            engine_version="LibreOffice 25.8.7.3",
            rasterizer_version="pdftoppm 25.12.0",
            validator_version="3.5.1",
            engine_identity_hash="sha256:" + ("b" * 64),
            executor_environment_hash="sha256:" + ("c" * 64),
            font_inventory=("Liberation Sans\tRegular", "Liberation Sans\tBold"),
        )

    def roundtrip_docx(self, *, source_path: Path, output_path: Path, workspace: Path) -> None:
        assert workspace.is_dir()
        output_path.write_bytes(source_path.read_bytes())

    def render_docx(self, *, docx_path: Path, workspace: Path, stage: str) -> tuple[RenderedRgbPage, ...]:
        assert docx_path.is_file()
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


def _prepare(tmp_path: Path) -> tuple[Path, Path]:
    assignment = tmp_path / "assignment"
    output = tmp_path / "output"
    assignment.mkdir()
    output.mkdir()
    materialize_genoffice_docx_libreoffice_assignment(
        output_directory=assignment,
        fixture_id="formatting-table-fidelity",
        runner_image_ref=RUNNER_IMAGE,
        requested_at_utc=REQUESTED_AT,
    )
    return assignment, output


def test_runner_materializes_unsigned_evidence_that_independent_verifier_accepts(tmp_path: Path) -> None:
    assignment, output = _prepare(tmp_path)

    runner_report = run_genoffice_docx_libreoffice_assignment(
        input_root=assignment,
        output_root=output,
        runner_image_ref=RUNNER_IMAGE,
        toolchain=FakeLibreOfficeToolchain(),
        now_utc=REQUESTED_AT + timedelta(minutes=1),
    )

    assert runner_report.engine_executed is True
    assert runner_report.result_signed is False
    assert runner_report.evidence_independently_verified is False
    assert runner_report.compatibility_claim_allowed is False
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
    payload = GenOfficeDocxFidelityEngineResultPayload.model_validate_json(
        (output / "handoff" / "result-payload.json").read_text(encoding="utf-8")
    )
    message = (output / "handoff" / "result-signature-message.bin").read_bytes()
    assert message == build_genoffice_docx_fidelity_result_message(payload)

    private_keys = {
        engine_id: Ed25519PrivateKey.from_private_bytes(bytes((index,)) * 32)
        for index, engine_id in enumerate(FIDELITY_ENGINE_IDS, start=7)
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
    signer = next(item for item in signers if item.engine_id == "libreoffice")
    policy_draft = GenOfficeDocxFidelityResultSignerPolicy(
        policy_id="libreoffice-study-test-signers",
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
        signature_base64=base64.b64encode(private_keys["libreoffice"].sign(message)).decode("ascii"),
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


def test_assignment_materialization_is_exact_and_write_once(tmp_path: Path) -> None:
    assignment = tmp_path / "assignment"
    assignment.mkdir()

    request = materialize_genoffice_docx_libreoffice_assignment(
        output_directory=assignment,
        fixture_id="unknown-markup-passthrough",
        runner_image_ref=RUNNER_IMAGE,
        requested_at_utc=REQUESTED_AT,
    )

    assert request.assignment_id == "libreoffice:unknown-markup-passthrough"
    assert request.engine_execution_allowed is True
    assert request.tenant_content_allowed is False
    assert request.private_key_allowed is False
    assert tuple(sorted(path.name for path in (assignment / "control").iterdir())) == (
        "corpus-manifest.json",
        "run-request.json",
        "study-plan.json",
    )
    assert tuple(path.name for path in (assignment / "input").iterdir()) == ("unknown-markup-passthrough.docx",)
    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="output directory is not empty"):
        materialize_genoffice_docx_libreoffice_assignment(
            output_directory=assignment,
            fixture_id="unknown-markup-passthrough",
            runner_image_ref=RUNNER_IMAGE,
            requested_at_utc=REQUESTED_AT,
        )


def test_runner_rejects_tampered_source_and_extra_control_file(tmp_path: Path) -> None:
    assignment, output = _prepare(tmp_path)
    source = assignment / "input" / "formatting-table-fidelity.docx"
    source.write_bytes(source.read_bytes() + b"tampered")

    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="assignment binding or lifetime drifted"):
        run_genoffice_docx_libreoffice_assignment(
            input_root=assignment,
            output_root=output,
            runner_image_ref=RUNNER_IMAGE,
            toolchain=FakeLibreOfficeToolchain(),
            now_utc=REQUESTED_AT + timedelta(minutes=1),
        )

    source.write_bytes(source.read_bytes()[: -len(b"tampered")])
    (assignment / "control" / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="control inventory is not exact"):
        run_genoffice_docx_libreoffice_assignment(
            input_root=assignment,
            output_root=output,
            runner_image_ref=RUNNER_IMAGE,
            toolchain=FakeLibreOfficeToolchain(),
            now_utc=REQUESTED_AT + timedelta(minutes=1),
        )


def test_runner_rejects_expired_request_image_drift_and_page_dimension_drift(tmp_path: Path) -> None:
    assignment, output = _prepare(tmp_path)

    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="assignment binding or lifetime drifted"):
        run_genoffice_docx_libreoffice_assignment(
            input_root=assignment,
            output_root=output,
            runner_image_ref=RUNNER_IMAGE,
            toolchain=FakeLibreOfficeToolchain(),
            now_utc=REQUESTED_AT + timedelta(hours=5),
        )
    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="assignment binding or lifetime drifted"):
        run_genoffice_docx_libreoffice_assignment(
            input_root=assignment,
            output_root=output,
            runner_image_ref="collabio/libreoffice-fidelity@sha256:" + ("d" * 64),
            toolchain=FakeLibreOfficeToolchain(),
            now_utc=REQUESTED_AT + timedelta(minutes=1),
        )
    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="pages do not align"):
        run_genoffice_docx_libreoffice_assignment(
            input_root=assignment,
            output_root=output,
            runner_image_ref=RUNNER_IMAGE,
            toolchain=FakeLibreOfficeToolchain(mismatched_dimensions=True),
            now_utc=REQUESTED_AT + timedelta(minutes=1),
        )


def test_runner_requires_digest_pinned_image_and_empty_schema_directory(tmp_path: Path) -> None:
    assignment = tmp_path / "assignment"
    assignment.mkdir()
    with pytest.raises(ValueError, match="not digest pinned"):
        materialize_genoffice_docx_libreoffice_assignment(
            output_directory=assignment,
            fixture_id="formatting-table-fidelity",
            runner_image_ref="collabio/libreoffice-fidelity:latest",
            requested_at_utc=REQUESTED_AT,
        )

    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    hashes = persist_genoffice_docx_libreoffice_runner_schemas(schema_dir)
    assert tuple(sorted(hashes)) == (
        "genoffice-docx-libreoffice-run-request.schema.json",
        "genoffice-docx-libreoffice-runner-report.schema.json",
    )
    assert all(value.startswith("sha256:") for value in hashes.values())
    for filename in hashes:
        assert (schema_dir / filename).read_bytes() == (Path("docs/operations") / filename).read_bytes()
    with pytest.raises(GenOfficeDocxLibreOfficeRunnerError, match="schema output directory is not empty"):
        persist_genoffice_docx_libreoffice_runner_schemas(schema_dir)


def test_openxml_tool_and_container_contracts_are_pinned_and_private_key_free() -> None:
    project = Path("tools/openxml-validator/Collabio.OpenXmlValidator.csproj").read_text(encoding="utf-8")
    program = Path("tools/openxml-validator/Program.cs").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'PackageReference Include="DocumentFormat.OpenXml" Version="[3.5.1]"' in project
    assert "RestorePackagesWithLockFile" in project
    assert "MarkupCompatibilityProcessMode.ProcessAllParts" in program
    assert "FileFormatVersions.Office2021" in program
    assert "error.Description" not in program
    assert "AS libreoffice-fidelity-runner" in dockerfile
    service = compose.split("  genoffice-docx-fidelity-libreoffice-runner:", 1)[1].split(
        "\n  genoffice-docx-fidelity-evidence-schema:", 1
    )[0]
    assert 'network_mode: "none"' in service
    assert "read_only: true" in service
    assert 'user: "${SUITE_RUNTIME_UID:-1000}:${SUITE_RUNTIME_GID:-1000}"' in service
    assert "cap_drop:\n      - ALL" in service
    assert "no-new-privileges:true" in service
    assert "create_host_path: false" in service
    assert "docker.sock" not in service
    assert "private" not in service.lower()


def test_system_toolchain_uses_only_the_first_nonempty_version_line(monkeypatch: pytest.MonkeyPatch) -> None:
    toolchain = SystemLibreOfficeFidelityToolchain()
    completed = subprocess.CompletedProcess(
        args=("pdftoppm", "-v"),
        returncode=0,
        stdout="",
        stderr="pdftoppm version 25.12.0\nCopyright 2005-2025 The Poppler Developers\n",
    )
    monkeypatch.setattr(toolchain, "_run_command", lambda *args, **kwargs: completed)

    assert toolchain._safe_version(("pdftoppm", "-v"), "pdftoppm") == "pdftoppm version 25.12.0"
