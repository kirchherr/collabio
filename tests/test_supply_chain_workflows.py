import json
import re
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_PATH = WORKFLOW_DIR / "ci.yml"
RELEASE_PATH = WORKFLOW_DIR / "release-provenance.yml"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "SUPPLY_CHAIN.md"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"
VEX_PATH = REPO_ROOT / "security" / "vex" / "collabio.openvex.json"
VEX_REGISTER_PATH = REPO_ROOT / "security" / "vex" / "decision-register.json"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
DEV_REQUIREMENTS_PATH = REPO_ROOT / "requirements-dev.txt"
APP_PATH = REPO_ROOT / "app"
PREVIEW_RELEASE_GATE_PATH = APP_PATH / "suite" / "platform" / "source_object_preview_renderer_release_gate.py"
IMMUTABLE_ACTION_REF = re.compile(r"^[^\s@]+@[a-f0-9]{40}$")


def action_references(workflow: str) -> list[str]:
    return [line.split("uses:", 1)[1].split("#", 1)[0].strip() for line in workflow.splitlines() if "uses:" in line]


def test_all_github_actions_use_immutable_commit_references() -> None:
    references: list[str] = []
    for workflow_path in sorted(WORKFLOW_DIR.glob("*.yml")):
        references.extend(action_references(workflow_path.read_text(encoding="utf-8")))

    assert references
    assert all(IMMUTABLE_ACTION_REF.fullmatch(reference) for reference in references)


def test_runtime_base_image_is_digest_pinned_and_update_managed() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    base_image = dockerfile.splitlines()[0]
    dependabot = DEPENDABOT_PATH.read_text(encoding="utf-8")
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    dev_requirements = DEV_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

    assert re.fullmatch(r"FROM python:3\.12-alpine@sha256:[a-f0-9]{64} AS base", base_image)
    assert 'package-ecosystem: "docker"' in dependabot
    assert 'directory: "/"' in dependabot
    assert 'interval: "weekly"' in dependabot

    assert "USER 10001:10001" in dockerfile
    assert "pip install --upgrade pip" not in dockerfile
    assert "fastapi==0.141.1" in requirements
    assert "httpx==0.28.1" in requirements
    assert "httpx==0.28.1" not in dev_requirements
    assert "httpx2==2.9.1" in dev_requirements

    preview_release_gate = PREVIEW_RELEASE_GATE_PATH.read_text(encoding="utf-8")
    assert "source_object_preview_renderer_smoke import" not in preview_release_gate
    assert "source_object_preview_renderer_smoke_contract import" in preview_release_gate


def test_ci_supply_chain_gate_scans_runtime_and_publishes_sbom() -> None:
    workflow = CI_PATH.read_text(encoding="utf-8")

    assert "supply-chain:" in workflow
    assert "needs: quality" in workflow
    assert "docker build --provenance=false --target runtime" in workflow
    assert "Smoke-test non-root runtime" in workflow
    assert "python -W error -c" in workflow
    assert "scanners: vuln,secret,misconfig" in workflow
    assert "scanners: license" in workflow
    assert "severity: HIGH,CRITICAL" in workflow
    assert "severity: CRITICAL" in workflow
    assert "ignore-unfixed: true" not in workflow
    assert "format: cyclonedx" in workflow
    assert "artifacts/collabio-runtime.cdx.json" in workflow
    assert "retention-days: 30" in workflow
    assert workflow.count("TRIVY_VEX:") == 2
    assert workflow.count("TRIVY_SHOW_SUPPRESSED:") == 2
    assert workflow.count("skip-files:") == 4
    assert workflow.count("version: v0.73.0") == 5


def test_release_tags_require_quality_scans_sbom_and_two_attestations() -> None:
    workflow = RELEASE_PATH.read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "docker compose run --rm quality" in workflow
    assert "docker build --provenance=false --target runtime" in workflow
    assert "Smoke-test non-root runtime" in workflow
    assert "python -W error -c" in workflow
    assert "docker save --output" in workflow
    assert "format: cyclonedx" in workflow
    assert workflow.count("actions/attest@") == 2
    assert "sbom-path: artifacts/collabio-runtime.cdx.json" in workflow
    assert "sha256sum" in workflow
    assert "retention-days: 90" in workflow
    assert workflow.count("TRIVY_VEX:") == 1
    assert workflow.count("TRIVY_SHOW_SUPPRESSED:") == 1
    assert workflow.count("skip-files:") == 3
    assert workflow.count("version: v0.73.0") == 3


def test_supply_chain_runbook_defines_failure_and_exception_culture() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "No scan may silently continue" in runbook
    assert "CycloneDX" in runbook
    assert "immutable commit SHA" in runbook
    assert "owner, reason, exact scope, expiry date" in runbook
    assert "gh attestation verify" in runbook


def test_openvex_decision_is_exact_current_and_code_reachability_guarded() -> None:
    vex = json.loads(VEX_PATH.read_text(encoding="utf-8"))
    register = json.loads(VEX_REGISTER_PATH.read_text(encoding="utf-8"))
    statement = vex["statements"][0]
    decision = register["decisions"][0]

    assert vex["@context"] == "https://openvex.dev/ns/v0.2.0"
    assert statement["vulnerability"]["name"] == "CVE-2026-69247"
    assert statement["products"] == [{"@id": "pkg:pypi/cryptography@49.0.0"}]
    assert statement["status"] == "not_affected"
    assert statement["justification"] == "vulnerable_code_not_in_execute_path"

    assert decision["vulnerability_id"] == statement["vulnerability"]["name"]
    assert decision["product"] == statement["products"][0]["@id"]
    assert decision["owner"]
    assert decision["reviewer"]
    assert decision["upstream_reference"].startswith("https://github.com/pyca/cryptography/")
    assert datetime.fromisoformat(decision["expires_at"]).replace(tzinfo=UTC) > datetime.now(UTC)

    application_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(APP_PATH.rglob("*.py"))).lower()
    assert "pkcs7" not in application_source
