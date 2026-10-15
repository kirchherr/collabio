# Repository Governance

Status: ruleset policy ready; GitHub enforcement pending
Date: 2026-08-14

## Current Status

Implemented:

- Docker Compose quality gate.
- GitHub Actions CI workflow.
- Dependabot configuration.
- Repository-local Deploy Key for Git push.
- Importable default-branch ruleset in `.github/rulesets/main.json`.
- Required checks bound to GitHub Actions application ID `15368` to prevent an unrelated status producer from
  satisfying the gate.

Blocked from this workspace:

- The ruleset has not yet been imported into GitHub repository settings.
- Branch protection cannot be applied with the Deploy Key because Deploy Keys cannot change repository settings.
- The GitHub CLI is not installed on this machine.
- The connected GitHub app can inspect `kirchherr/collabio`, but its available write tools do not include repository
  rules administration.
- No administration-scoped `GH_TOKEN` or `GITHUB_TOKEN` is available locally.

Manual fallback:

1. Open `kirchherr/collabio` repository settings in GitHub.
2. Go to **Rules**, then **Rulesets**, select **New ruleset**, and import `.github/rulesets/main.json`.
3. Verify enforcement is **Active** and the target is the default branch.
4. Verify required checks are `quality` and `supply-chain`, both sourced from **GitHub Actions**.
5. Verify pull requests, resolved review threads, an up-to-date branch, linear history, and zero bypass actors are
   required while force pushes and deletion are blocked.
6. Create the ruleset and verify `GET /repos/kirchherr/collabio/rules/branches/main` returns all five rule types.

The repository currently has one human administrator. Requiring one approving review would make that administrator
unable to merge their own pull requests, so the ruleset intentionally requires zero approvals while still requiring a
pull request and green checks. Increase `required_approving_review_count` to `1`, enable stale-review dismissal and
last-push approval, and add CODEOWNERS review as soon as a second independent maintainer is available.

## Required Gates

The repository quality gate is:

```bash
docker compose run --rm quality
```

This command runs:

- `ruff check .`
- `ruff format --check .`
- `mypy app tests`
- `pytest -q`

## GitHub Actions

The default CI workflow is `.github/workflows/ci.yml`.

Security posture:

- Workflow permissions default to `contents: read`.
- CI runs through Docker Compose, matching the local development path.
- Workflow runs are concurrency-limited per ref.
- Dependabot is enabled for GitHub Actions and Python dependencies.

## Main Branch Protection Target

Target branch: `main`

Required controls:

- Require status checks `quality` and `supply-chain` from GitHub Actions.
- Require branches to be up to date before merge.
- Block force pushes.
- Block branch deletion.
- Require linear history.
- Require pull requests and resolved review threads.
- Allow squash and rebase merges only.
- Define no bypass actors.

## Local Git SSH

This workspace uses a repository-local SSH command pointing to:

```text
C:/Users/tkirchherr/.ssh/id_ed25519_collabio_deploy
```

The key is intended only for `kirchherr/collabio`.
