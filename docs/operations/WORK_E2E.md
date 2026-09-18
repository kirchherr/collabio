# Work End-to-End Verification

## Purpose

This runbook verifies the first daily-work surface through a real browser, the real Collabio API routes and the real
PostgreSQL task/time/CRM adapters and the Knowledge Base PostgreSQL/S3 unit of work. It covers every source independently
in ready, empty, blocked and unavailable states, the closed productivity-pilot runtime boundary, task reassignment,
time correction and resubmission, Knowledge Base create/edit/read/conflict/failure handling, and desktop/mobile containment.

The profile is test-only. It uses only tenant `tenant-work-e2e`, generated synthetic records and an ephemeral
tmpfs-backed PostgreSQL and MinIO instances. It publishes no host port, joins only the internal `work_e2e_internal` network and
keeps `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. The isolated test override can admit only synthetic traffic in
`tests/work_e2e_server.py`; it is not part of the product API image or normal runtime configuration. The separate
blocked process installs only in-memory, synthetic, hash-valid scope/start fixtures so requests reach the real closed
runtime switch. The guard requires both pilot stores to remain explicitly `memory`; those fixtures are neither durable
pilot evidence nor tenant activation. The proof expects four in-policy task/time reads to return `423`, CRM to return
`403` outside the route scope, inactive Tickets to return `404`, and the non-pilot Knowledge read to remain available.

Knowledge Base approval rows, source manifests, receipts, article versions, source evidence and restore evidence use
the real PostgreSQL adapters; article bytes use exact-version S3 reads/writes through the existing MinIO adapter. The
test-only runtime activation remains in memory, binds an explicitly synthetic restore reference, and checks the actual
provider capabilities and content inventory. It is not a production restore drill or accountable activation approval.
Only the synthetic-traffic API enables `knowledge_base.articles.write`; the blocked API leaves it disabled.

Every Knowledge Base and CRM request resolves readable object IDs from `PgPrincipalDirectory` against the current database
ACLs. Browser-supplied readable IDs are ignored for these requests. Migration `0082` must therefore grant the creating
principal access and copy the article ACL to each new version in the same PostgreSQL transaction. The storage-failure
case injects a request-local exception at the existing object-store adapter before its write and verifies that the
previous body and version remain authoritative. The failure switch exists only in the guarded test harness.

The seeded non-admin `work-reader-e2e` reads through the blocked API with the write feature disabled. A narrow
synthetic store behind the existing authz administration route grants/revokes only read ACLs for that principal and
new synthetic KB article/version objects in the isolated database. The new version must inherit the reader's article
ACL through migration 0082. Request-local read failure injection is limited to the exact synthetic tenant and
`GET /v1/kb/articles/{article_object_id}/content`; it does not require the write/pilot test override.

CRM details use the existing account-workspace route against a real `PgCrmRepository`. Seeded account, contact,
activity and note metadata is restricted to the synthetic tenant. Each reader ACL is a database record; forged
browser-readable IDs cannot reveal an account or child. The fixtures include unrelated readable records, unreadable
children and readable activities with redacted contact links. The real blocked process still rejects CRM reads under
the unchanged pilot policy. Feature and ACL denial tests restore the prior synthetic state in `finally` blocks.
Request-local database failure injection is restricted to synthetic account-workspace GETs; no failure control is
installed in the normal API.

Follow `/home/extern/AGENTS.md`, work in `dev001:/home/extern/collabio`, always use Compose project `collabio`, and
acquire `build.lock` before `docker.lock` whenever both apply.

## Fixed Inputs

- Browser runner: Playwright `1.63.0`.
- Base image: `mcr.microsoft.com/playwright:v1.63.0-noble` pinned by immutable digest in `e2e/work/Dockerfile`.
- npm dependencies: exact versions and integrity hashes in `e2e/work/package-lock.json`.
- Tenant: `tenant-work-e2e` only.
- Database host/name: `work-e2e-postgres/collabio_work_e2e` only.
- Object-store endpoint: `http://work-e2e-minio:9000` only, using fixed synthetic credentials and tmpfs data.
- Runtime policy: production pilot switch remains closed; the second API process proves the ordinary fail-closed path.

The image follows the official Playwright Docker guidance: package and image versions match, the browser image defaults
to non-root `pwuser`, and Chromium receives dedicated shared memory. Compose maps the process to the fixed non-root
`extern` UID/GID `1000:1000` so the checked-in artifact directory remains writable without broad permissions. The
container additionally has a read-only root, no Linux capabilities, no-new-privileges, bounded CPU/memory/PIDs and no
external network. The bind mount refuses automatic host-path creation.

## Preflight

Before every Compose start or lifecycle command, inspect the shared host:

```bash
docker compose -p collabio ls
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -ltnH
```

Confirm that no previous `collabio-work-e2e-*` container is running. Do not stop, recreate or remove regular Collabio,
Webcut, Tricert or provider resources. Verify that `/home/extern/collabio/e2e/work/artifacts` remains owned by
`1000:1000`; do not make it world-writable.

## Run

From `/home/extern/collabio`, validate the rendered model and run the complete browser proof while holding both locks:

```bash
flock -w 900 /home/extern/.codex-coordination/build.lock \
  flock -w 900 /home/extern/.codex-coordination/docker.lock \
  sh -c 'docker compose -p collabio --profile work-e2e config --quiet && \
    docker compose -p collabio --profile work-e2e run --rm --build work-e2e'
```

The expected matrix is 142 passing checks: 107 browser cases and 35 pure comparison/search model cases. The original
73-case browser foundation consists of the original 32 cases (28 independent availability cases, one closed-pilot
case, one real reassignment/correction/resubmission workflow, and two responsive project runs), seven Knowledge Base
workflow cases, and two Knowledge Base editor responsive runs. The Knowledge Base cases cover successful create/edit,
a competing edit conflict, object-store failure, disabled write feature, unauthorized role, approval invalidation
after changing a draft, and rejection of stale responses after a context switch. Other source views use the existing synthetic fixtures in these focused Knowledge Base cases;
the original workflow and route-policy cases retain their real API coverage. Seven reader cases additionally prove
ordinary read with write disabled, exact updated content, literal markup, missing/forged/foreign ACL denial,
article/version ACL revocation, S3 read failure and recovery, delayed responses after close/reopen or context change.
Two additional desktop/mobile reader runs check long text, viewport containment and an accessible close action.
Eight CRM detail cases prove PostgreSQL child filtering/redaction, literal field values, empty children, missing or
forged permissions, foreign tenant and closed pilot, account ACL revocation, disabled contacts feature, database
failure/retry and close/context races. Two more desktop/mobile runs verify the CRM dialog and reachable controls.

Eleven native Office workflow/policy cases and two responsive runs cover real rich-text editing, immutable version
history, concurrent saves, current typed ACLs, forged grants, foreign tenants, feature closure, source read/write failures,
lost-response idempotent retry and late context responses. Office uses its own PostgreSQL/S3 domain service and seeded
editor/reader, always with fresh database ACL resolution. The blocked process permits authorized reads but closes writes.

Roadmap 253 adds thirteen version-workflow cases and two desktop/mobile runs (including a tablet screenshot): exact
saved text/title/format/table comparison, equality, local historical takeover against a freshly loaded head, explicit
save lineage, no-op takeover, a subsequent CAS conflict, read-only comparison, ACL/write-feature removal, cancelled
discard, transient read failure and late close/selection/context/takeover responses. A bounded-history edge case uses
three genuine stored versions and reduces only one real metadata response to its two newest rows; source reads stay
real and demonstrate a visible predecessor outside the returned window. Twelve pure-model cases verify deterministic,
bounded alignment, semantic mark/key ordering and complete ordered before/after projections, including large repeated
blocks and long text. The runner mounts the exact product comparison module read-only; it does not use a second copy.

Roadmap 254 adds nine browser runs and 23 pure search-model cases. Browser checks cover
literal Unicode/cross-mark matches, current/all replacement, isolated undo/redo, real confirmed save/reopen/version
history, complete counts beyond 1,000 matches, read-only/history restrictions, no-op/delete/size limits, context/discard
and delayed reads, plus responsive desktop/mobile/tablet layouts. The product search module is mounted read-only into
the same runner. Model cases validate original UTF-16 positions, word boundaries, literal replacement, preserved marks
and structure, complete result sets and preflight limits; no alternative test implementation substitutes for the product.

Roadmap 255 adds eight table workflow cases and two responsive runs. They cover configurable insertion, row/column
operations, first-row headers, cell selections and preserved marks, actual version saves/reopen/history, isolated
undo/redo, immediate focus, removal confirmation/cancellation, reader/history restrictions, pending and uncertain
saves, context invalidation, keyboard navigation and row creation, 200-row/20-column bounds and the whole-document
canonical byte limit. Desktop, tablet and mobile screenshots show contextual controls and selected cells. The previous
132 cases remain part of the matrix.

After a green matrix, `office-native-recovery-proof` can verify a separately restored synthetic database and exact S3
versions. Only that disposable checker joins both the test and restore networks. It accepts only the fixed work-e2e source
and `collabio_work_e2e_restore` target, with a read-only mount at `/proof-backup`; the normal restore database is rejected.
The dump, checksum and restore receipt must result from a real operator-run pg_dump/pg_restore under the host locks.
Its read path verifies at least one document with two versions, source/receipt hashes and restored current ACLs.
Roadmap 256 extends the proof to nonempty review creation, reply, resolve and reopen events, complete review metadata
hashes and exact COMMENT source versions/receipts; parent ACL denial must still apply after restoration. Never run
it while browser writes are in flight. It neither enables a module nor creates or drops databases. Preserve its JSON report
before removing the exact test services; keep the synthetic dump under ignored `e2e/work/artifacts/office-recovery-backup`.

## Evidence

The ignored directory `e2e/work/artifacts/` receives:

- `results.json`, the Playwright JSON report;
- `work-workflows-complete.png`, the completed real-API workflow;
- `work-desktop-chromium.png` and `work-mobile-chromium.png`, the responsive proof;
- `work-knowledge-complete.png`, the completed PostgreSQL/S3 create/edit workflow;
- `work-knowledge-desktop-chromium.png` and `work-knowledge-mobile-chromium.png`, the editor and confirmation proof;
- `work-knowledge-reader-complete.png`, the ordinary reader after an admin's committed edit;
- `work-knowledge-reader-desktop-chromium.png` and `work-knowledge-reader-mobile-chromium.png`, the reader containment proof;
- `work-crm-detail-complete.png`, the authorized PostgreSQL account detail;
- `work-crm-detail-desktop-chromium.png` and `work-crm-detail-mobile-chromium.png`, CRM detail containment and scrolling;
- traces and failure screenshots only when a test fails.
- `office-editor-desktop-chromium.png`, `office-editor-tablet-chromium.png`, `office-editor-mobile-chromium.png`;
- `office-versions-desktop-chromium.png`, `office-versions-tablet-chromium.png`, `office-versions-mobile-chromium.png`.
- `office-search-desktop-chromium.png`, `office-search-tablet-chromium.png`, `office-search-mobile-chromium.png`.
- `office-tables-desktop-chromium.png`, `office-tables-tablet-chromium.png`, `office-tables-mobile-chromium.png`.

Treat browser output as test evidence, not production evidence. It contains only synthetic data, is not an activation
approval, and does not authorize real-user traffic. Record test counts, SHA-256 hashes and the exact source commit in
`docs/operations/DEV001_OPERATIONS_LOG.md`; do not commit the generated artifacts.

## Cleanup

After preserving hashes or failure diagnostics, repeat the preflight and remove only the profile's exact containers:

```bash
flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile work-e2e rm -f -s \
  work-e2e work-e2e-api work-e2e-blocked-api work-e2e-seed work-e2e-migrate work-e2e-postgres work-e2e-minio
```

Never use `docker compose down` on the shared host. Repeat the preflight, verify that regular services and published
ports are unchanged, and confirm that no `collabio-work-e2e-*` container remains. Because PostgreSQL data lives only
on the removed container's tmpfs and MinIO objects live only on its tmpfs, each proof begins from an empty migrated
database and new object buckets.

## Failure Rules

- A guard rejection, migration or seed failure, browser console error, external browser request, unexpected HTTP
  status, horizontal overflow, duplicate DOM ID or missing accessible button name fails the run.
- Do not enable the regular productivity-pilot runtime to make a test pass.
- Do not point any E2E DSN at `postgres`, `postgres-test`, a host address or a persistent volume.
- Do not point the E2E object store at regular `minio`, a host address or an external provider.
- Do not weaken tenant/module/ACL checks in product routes. Fix either the real product defect or the isolated fixture.
- Preserve diagnostics before cleanup, but never promote synthetic output into accountable pilot evidence.

## Upstream References

- [Playwright Docker](https://playwright.dev/docs/docker)
- [Playwright releases](https://github.com/microsoft/playwright/releases)
