import json
import re
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_PATH = WORKFLOW_DIR / "ci.yml"
RELEASE_PATH = WORKFLOW_DIR / "release-provenance.yml"
PROMOTION_PATH = WORKFLOW_DIR / "promote-release.yml"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "SUPPLY_CHAIN.md"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
LOCK_SCRIPT_PATH = REPO_ROOT / "docker" / "regenerate-dependency-locks.sh"
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"
MAIN_BRANCH_RULESET_PATH = REPO_ROOT / ".github" / "rulesets" / "main.json"
VEX_PATH = REPO_ROOT / "security" / "vex" / "collabio.openvex.json"
VEX_REGISTER_PATH = REPO_ROOT / "security" / "vex" / "decision-register.json"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
DEV_REQUIREMENTS_PATH = REPO_ROOT / "requirements-dev.txt"
PREVIEW_REQUIREMENTS_PATH = REPO_ROOT / "requirements-preview.txt"
RUNTIME_LOCK_PATH = REPO_ROOT / "requirements.lock"
DEV_LOCK_PATH = REPO_ROOT / "requirements-dev.lock"
PREVIEW_LOCK_PATH = REPO_ROOT / "requirements-preview.lock"
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
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    dependabot = DEPENDABOT_PATH.read_text(encoding="utf-8")
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    dev_requirements = DEV_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    preview_requirements = PREVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

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
    assert "Pillow==12.3.0" in preview_requirements

    assert dockerfile.count("pip install --require-hashes --requirement") == 3
    assert "COPY requirements.lock ." in dockerfile
    assert "COPY requirements-dev.lock ." in dockerfile
    assert "COPY requirements-preview.lock ." in dockerfile
    assert "pip install --requirement requirements.txt" not in dockerfile
    assert compose.count("ghcr.io/astral-sh/uv:0.12.2-python3.12-alpine@sha256:") == 3
    assert compose.count('profiles: ["tooling"]') == 3
    assert compose.count('entrypoint: ["/usr/local/bin/uv"]') == 3
    assert compose.count('"sh docker/regenerate-dependency-locks.sh"') == 3
    assert "cat /tmp/requirements" not in compose
    assert "./requirements.lock:/workspace/requirements.lock" not in compose
    assert "./requirements-dev.lock:/workspace/requirements-dev.lock" not in compose
    assert "./requirements-preview.lock:/workspace/requirements-preview.lock" not in compose

    preview_release_gate = PREVIEW_RELEASE_GATE_PATH.read_text(encoding="utf-8")
    assert "source_object_preview_renderer_smoke import" not in preview_release_gate
    assert "source_object_preview_renderer_smoke_contract import" in preview_release_gate


def assert_hash_locked(lock_path: Path, minimum_packages: int) -> None:
    lines = lock_path.read_text(encoding="utf-8").splitlines()
    package_indexes = [
        index for index, line in enumerate(lines) if line and not line.startswith((" ", "#", "-")) and "==" in line
    ]

    assert len(package_indexes) >= minimum_packages
    for position, start in enumerate(package_indexes):
        end = package_indexes[position + 1] if position + 1 < len(package_indexes) else len(lines)
        assert re.match(r"^[A-Za-z0-9_.-]+==[^\s;]+", lines[start])
        assert any("--hash=sha256:" in line for line in lines[start:end])


def test_runtime_and_development_dependency_graphs_are_transitively_hash_locked() -> None:
    assert_hash_locked(RUNTIME_LOCK_PATH, minimum_packages=30)
    assert_hash_locked(DEV_LOCK_PATH, minimum_packages=45)
    assert_hash_locked(PREVIEW_LOCK_PATH, minimum_packages=1)

    runtime_lock = RUNTIME_LOCK_PATH.read_text(encoding="utf-8")
    dev_lock = DEV_LOCK_PATH.read_text(encoding="utf-8")
    preview_lock = PREVIEW_LOCK_PATH.read_text(encoding="utf-8")
    assert "sh docker/regenerate-dependency-locks.sh" in runtime_lock
    assert "sh docker/regenerate-dependency-locks.sh" in dev_lock
    assert "sh docker/regenerate-dependency-locks.sh" in preview_lock
    assert "fastapi==0.141.1" in runtime_lock
    assert "cryptography==49.0.0" in runtime_lock
    assert "pytest==9.0.3" in dev_lock
    assert "pillow==12.3.0" in preview_lock


def test_dependency_lock_regeneration_is_atomic_and_host_portable() -> None:
    script = LOCK_SCRIPT_PATH.read_text(encoding="utf-8")

    assert script.count("docker compose -p") == 3
    assert script.count("--profile tooling run -T --rm dependency-lock-") == 3
    assert script.count("mktemp") == 3
    assert script.count("test -s") == 3
    assert script.count("mv -f --") == 3
    assert "compose_project=${COMPOSE_PROJECT_NAME:-collabio}" in script
    assert '> "$runtime_tmp"' in script
    assert '> "$dev_tmp"' in script
    assert '> "$preview_tmp"' in script


def test_ci_supply_chain_gate_scans_runtime_and_publishes_sbom() -> None:
    workflow = CI_PATH.read_text(encoding="utf-8")

    assert "supply-chain:" in workflow
    assert "Verify dependency locks are current" in workflow
    assert "sh docker/regenerate-dependency-locks.sh" in workflow
    assert "git diff --exit-code -- requirements.lock requirements-dev.lock requirements-preview.lock" in workflow
    assert "needs: quality" in workflow
    assert "docker build --provenance=false --target runtime" in workflow
    assert "Smoke-test non-root runtime" in workflow
    assert "python -W error -c" in workflow
    assert "scanners: vuln,secret,misconfig" in workflow
    assert "scanners: license" in workflow
    assert "severity: HIGH,CRITICAL" in workflow
    assert "severity: CRITICAL" in workflow
    assert "ignore-unfixed: true" not in workflow
    assert workflow.count("trivyignores: .trivyignore.yaml") == 1
    assert "format: cyclonedx" in workflow
    assert "artifacts/collabio-runtime.cdx.json" in workflow
    assert "retention-days: 30" in workflow
    assert workflow.count("TRIVY_VEX:") == 2
    assert workflow.count("TRIVY_SHOW_SUPPRESSED:") == 2
    assert workflow.count("skip-files:") == 4
    assert workflow.count("version: v0.73.0") == 5


def test_default_branch_ruleset_requires_pr_and_both_github_actions_checks() -> None:
    ruleset = json.loads(MAIN_BRANCH_RULESET_PATH.read_text(encoding="utf-8"))
    rules = {rule["type"]: rule for rule in ruleset["rules"]}

    assert ruleset["target"] == "branch"
    assert ruleset["enforcement"] == "active"
    assert ruleset["bypass_actors"] == []
    assert ruleset["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert {"deletion", "non_fast_forward", "required_linear_history"} <= rules.keys()

    pull_request = rules["pull_request"]["parameters"]
    assert pull_request["allowed_merge_methods"] == ["squash", "rebase"]
    assert pull_request["required_approving_review_count"] == 0
    assert pull_request["required_review_thread_resolution"] is True
    assert pull_request["require_last_push_approval"] is False

    status_checks = rules["required_status_checks"]["parameters"]
    assert status_checks["strict_required_status_checks_policy"] is True
    assert status_checks["required_status_checks"] == [
        {"context": "quality", "integration_id": 15368},
        {"context": "supply-chain", "integration_id": 15368},
    ]


def test_release_tags_require_quality_scans_sboms_and_attestations_for_both_images() -> None:
    workflow = RELEASE_PATH.read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "packages: write" in workflow
    assert "Verify dependency locks are current" in workflow
    assert "docker compose run --rm quality" in workflow
    assert "docker build --provenance=false --target runtime" in workflow
    assert "docker push" in workflow
    assert "artifacts/image-digest.txt" in workflow
    assert 'IMAGE_DIGEST="${IMAGE_REFERENCE##*@}"' in workflow
    assert "Smoke-test non-root runtime" in workflow
    assert "python -W error -c" in workflow
    assert "docker save --output" in workflow
    assert "format: cyclonedx" in workflow
    assert "docker build --provenance=false --target preview-renderer" in workflow
    assert "Smoke-test isolated preview renderer" in workflow
    assert "artifacts/preview-image-digest.txt" in workflow
    assert "collabio-preview-renderer.cdx.json" in workflow
    assert "steps.preview-publish.outputs.digest" in workflow
    assert workflow.count("actions/attest@") == 4
    assert "sbom-path: artifacts/collabio-runtime.cdx.json" in workflow
    assert "sbom-path: artifacts/collabio-preview-renderer.cdx.json" in workflow
    assert workflow.count("subject-name:") == 4
    assert workflow.count("subject-digest:") == 4
    assert workflow.count("push-to-registry: true") == 4
    assert "subject-path:" not in workflow
    assert "sha256sum" in workflow
    assert "retention-days: 90" in workflow
    assert workflow.count("TRIVY_VEX:") == 2
    assert workflow.count("TRIVY_SHOW_SUPPRESSED:") == 2
    assert workflow.count("skip-files:") == 6
    assert workflow.count("version: v0.73.0") == 6


def test_promotion_is_digest_bound_attested_and_environment_protected() -> None:
    workflow = PROMOTION_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "environment:\n      name: ${{ inputs.target_environment }}" in workflow
    assert '[[ "${GITHUB_REF}" == "refs/heads/main" ]]' in workflow
    assert '[[ "${PROMOTION_POLICY_CONFIGURED}" == "true" ]]' in workflow
    assert '[[ "${IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]' in workflow
    assert "Require release tag to resolve to requested digest" in workflow
    assert workflow.count("gh attestation verify") == 3
    assert 'predicate-type "https://cyclonedx.org/bom"' in workflow
    assert "--signer-workflow" in workflow
    assert "--source-ref" in workflow
    assert "--deny-self-hosted-runners" in workflow
    assert "Require prior staging admission for production" in workflow
    assert '.target_environment == "staging"' in workflow
    assert 'decision: "admitted"' in workflow
    assert "approval_evidence_system" in workflow
    assert "content_included: false" in workflow
    assert "secrets_included: false" in workflow
    assert "Attest promotion admission" in workflow
    assert "push-to-registry: true" in workflow
    assert 'docker tag "${IMAGE_NAME}@${IMAGE_DIGEST}"' in workflow
    assert "retention-days: 90" in workflow


def test_supply_chain_runbook_defines_failure_and_exception_culture() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "No scan may silently continue" in runbook
    assert "CycloneDX" in runbook
    assert "requirements.lock" in runbook
    assert "protected GitHub Environments" in runbook
    assert "OCI digest" in runbook
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
