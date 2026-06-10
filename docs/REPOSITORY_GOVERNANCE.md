# Repository Governance

Status: initial
Date: 2026-06-10

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
