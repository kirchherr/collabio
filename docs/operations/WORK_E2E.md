# Work End-to-End Verification

## Purpose

This runbook verifies the first daily-work surface through a real browser, the real Collabio API routes and the real
PostgreSQL task/time adapters. It covers every source independently in ready, empty, blocked and unavailable states,
the closed productivity-pilot boundary, task reassignment, time correction and resubmission, and desktop/mobile
containment.

The profile is test-only. It uses only tenant `tenant-work-e2e`, generated synthetic records and an ephemeral
tmpfs-backed PostgreSQL instance. It publishes no host port, joins only the internal `work_e2e_internal` network and
keeps `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. The isolated test override can admit only synthetic traffic in
`tests/work_e2e_server.py`; it is not part of the product API image or normal runtime configuration.

Follow `/home/extern/AGENTS.md`, work in `dev001:/home/extern/collabio`, always use Compose project `collabio`, and
acquire `build.lock` before `docker.lock` whenever both apply.

## Fixed Inputs

- Browser runner: Playwright `1.63.0`.
- Base image: `mcr.microsoft.com/playwright:v1.63.0-noble` pinned by immutable digest in `e2e/work/Dockerfile`.
- npm dependencies: exact versions and integrity hashes in `e2e/work/package-lock.json`.
- Tenant: `tenant-work-e2e` only.
- Database host/name: `work-e2e-postgres/collabio_work_e2e` only.
- Runtime policy: production pilot switch remains closed; the second API process proves the ordinary fail-closed path.

The image follows the official Playwright Docker guidance: package and image versions match, the browser process runs
as non-root `pwuser`, and Chromium receives dedicated shared memory. The container additionally has a read-only root,
no Linux capabilities, no-new-privileges, bounded CPU/memory/PIDs and no external network.

## Preflight

Before every Compose start or lifecycle command, inspect the shared host:

```bash
docker compose -p collabio ls
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -ltnH
```

Confirm that no previous `collabio-work-e2e-*` container is running. Do not stop, recreate or remove regular Collabio,
Webcut, Tricert or provider resources.

## Run

From `/home/extern/collabio`, validate the rendered model and run the complete browser proof while holding both locks:

```bash
flock -w 900 /home/extern/.codex-coordination/build.lock \
  flock -w 900 /home/extern/.codex-coordination/docker.lock \
  sh -c 'docker compose -p collabio --profile work-e2e config --quiet && \
    docker compose -p collabio --profile work-e2e run --rm --build work-e2e'
```

The expected matrix is 32 passing tests: 28 independent availability cases, one closed-pilot case, one real
reassignment/correction/resubmission workflow, and desktop plus mobile responsive coverage counted as two project
runs for the shared responsive specification.

## Evidence

The ignored directory `e2e/work/artifacts/` receives:

- `results.json`, the Playwright JSON report;
- `work-workflows-complete.png`, the completed real-API workflow;
- `work-desktop-chromium.png` and `work-mobile-chromium.png`, the responsive proof;
- traces and failure screenshots only when a test fails.

Treat browser output as test evidence, not production evidence. It contains only synthetic data, is not an activation
approval, and does not authorize real-user traffic. Record test counts, SHA-256 hashes and the exact source commit in
`docs/operations/DEV001_OPERATIONS_LOG.md`; do not commit the generated artifacts.

## Cleanup

After preserving hashes or failure diagnostics, repeat the preflight and remove only the profile's exact containers:

```bash
flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile work-e2e rm -f -s \
  work-e2e work-e2e-api work-e2e-blocked-api work-e2e-seed work-e2e-migrate work-e2e-postgres
```

Never use `docker compose down` on the shared host. Repeat the preflight, verify that regular services and published
ports are unchanged, and confirm that no `collabio-work-e2e-*` container remains. Because PostgreSQL data lives only
on the removed container's tmpfs, each proof begins from an empty migrated database.

## Failure Rules

- A guard rejection, migration or seed failure, browser console error, external browser request, unexpected HTTP
  status, horizontal overflow, duplicate DOM ID or missing accessible button name fails the run.
- Do not enable the regular productivity-pilot runtime to make a test pass.
- Do not point any E2E DSN at `postgres`, `postgres-test`, a host address or a persistent volume.
- Do not weaken tenant/module/ACL checks in product routes. Fix either the real product defect or the isolated fixture.
- Preserve diagnostics before cleanup, but never promote synthetic output into accountable pilot evidence.

## Upstream References

- [Playwright Docker](https://playwright.dev/docs/docker)
- [Playwright releases](https://github.com/microsoft/playwright/releases)
