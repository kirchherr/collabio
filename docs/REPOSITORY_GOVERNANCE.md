# Repository Governance

Status: initial
Date: 2026-06-10

## Current Status

Implemented:

- Docker Compose quality gate.
- GitHub Actions CI workflow.
- Dependabot configuration.
- Repository-local Deploy Key for Git push.

Blocked from this workspace:

- Branch Protection cannot be applied with the Deploy Key because Deploy Keys cannot change repository settings.
- The GitHub CLI is not installed on this machine.
- The connected GitHub app does not currently have access to `kirchherr/collabio`.
- No `GH_TOKEN` or `GITHUB_TOKEN` is available locally.

Manual fallback:

1. Open `kirchherr/collabio` repository settings in GitHub.
2. Go to Branches and add a ruleset or branch protection rule for `main`.
3. Require status check `quality`.
4. Require branches to be up to date before merge.
5. Disable force pushes and branch deletion.

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

- Require status check `quality`.
- Require branches to be up to date before merge.
- Block force pushes.
- Block branch deletion.
- Require linear history when supported by repository settings.
- Prefer pull requests over direct pushes once protection is active.

## Local Git SSH

This workspace uses a repository-local SSH command pointing to:

```text
C:/Users/tkirchherr/.ssh/id_ed25519_collabio_deploy
```

The key is intended only for `kirchherr/collabio`.
