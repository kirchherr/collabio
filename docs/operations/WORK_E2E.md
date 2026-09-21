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

The expected matrix is 200 passing checks: 165 browser cases and 35 pure comparison/search model cases. The original
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

Roadmap 256 adds eight review workflow cases and two responsive runs. They exercise Unicode text anchors, literal
comment rendering, cancelled and confirmed creation/reply/resolve/reopen, historical discussion after a new document
version, ordinary readers, forged/foreign/revoked access, thread CAS conflicts, exact uncertain retries, storage-read
failures, delayed close/context responses and fresh write-feature removal. The previous 142 checks remain in the matrix.
Comment state uses the same real PostgreSQL/source/receipt repositories as documents; failure injection remains
request-local and restricted to the exact synthetic review routes.

Roadmap 257 adds eight suggestion workflows and two responsive runs, taking the matrix to 162 checks.
They cover saved-selection creation, literal before/after text, explicit accept/reject, accepted version lineage,
immutable history, stale anchors, ordinary readers/current ACLs/foreign tenants, fresh feature closure, exact uncertain
retries, late responses and memory-only draft protection. The real document repository and suggestion adapter share
one transaction for acceptance. Request-local failure controls are restricted to the exact synthetic suggestion routes.
All 162 checks passed on `9c17a31` in 535.956 seconds, with zero skipped, unexpected or flaky results;
all 152 previous checks remain included. Full Python quality and 688 focused tests passed, and final desktop/tablet/mobile
screenshots were independently reviewed. The nonempty recovery restored 67 documents/109 versions, nine review
threads/17 events and ten suggestions/seven decisions, including five accepted and two rejected proposals.
Report `sha256:e1ab971a88c43ff06c12544ba24619731b2b8304908da53ab5b73ad8bb017c53`; ignored artifacts are under
`e2e/work/artifacts/roadmap-257/`. The main migration/foundation/business gates, API-only rollout and cleanup passed;
ordinary tenant, pilot, indexing and engine admission remain closed. Exact evidence is in the operations log and handoff.

Roadmap 258 adds six saved-version print workflows and two responsive runs. A controlled
browser print callback invokes Chromium's real PDF output on the same page while the freshly authorized print surface
is prepared. Tests exercise immutable versions and historical titles, read-only access, literal native structure,
paper/orientation, fresh ACL revocation, failures and late responses, dirty/unresolved drafts and output isolation.
The callback observes the real workflow; it does not replace the API, authorization, renderer or source bytes. Native
OS printer selection is outside headless automation; the application never claims that opening a dialog completed output.
Actual PDF structure dictionaries must include headings/paragraphs, and lists/table cells for the rich fixture. Merely
requesting tagged output is insufficient: modal preview siblings were initially invisible to PDF accessibility export.
The preview becomes nonmodal only during printing and returns to modal only if its session remains valid.
PDF inspection uses the existing project image's Poppler/QPDF tools in a separate disposable Compose service with no network,
read-only artifact input and scoped output. It does not execute LibreOffice or admit any document conversion engine.

Development acceptance on `cf2244c` passed all 170 checks in 562.233916 seconds: 135 browser cases and 35 model cases,
zero skipped, unexpected or flaky; all previous 162 remain included. Full Python quality passed Ruff/format across
689 files, Mypy across 541 sources and full Pytest, with only the known Starlette/AnyIO warning. Final desktop,
tablet and mobile screenshots and all PDF pages passed independent visual review.
The same-page PDFs contain nine rich Letter-landscape pages, one historical A4-portrait page and one unprepared-print
guidance page. Independent Poppler/QPDF checks find all 80 rich paragraphs and the final sentinel, complete literal
content and no application-shell leakage. Both prepared PDFs have actual heading/paragraph tags; the rich fixture
also has two lists/two list items, one table, 20 header cells and 40 data cells. This is tested Chromium evidence,
not a PDF/UA certificate or a guarantee about native OS printer selection and completed user output.
Browser report: `sha256:8198c66138af5af63d6d767ab9e8c4c06acaf18e60013809ed31879f39faa86f`;
PDF QA report: `sha256:598c1e210e3cb3f4920d78120b479d36f42bb8f8d8bfb6cf3677b61a3bedb63b`.
Final artifacts and rendered pages are under ignored `e2e/work/artifacts/roadmap-258/`. Later `d8300aa` changes only
test cleanup and is not the source of the full report; its affected-case recheck and API-only rollout/health/cleanup
are recorded separately in the operations log and current handoff. Item 257 recovery is retained, not newly executed.

Roadmap 259 adds eight saved-version reuse workflows and two responsive runs.
Existing real PostgreSQL/S3 APIs prove independent creation from current/historical rich content, unchanged source/history,
new identity and creator ACL without copied reader grants, discussions or suggestions. Cases cover read-only source access
with create permission, ordinary readers, fresh ACL/feature closure, discard consent and preserved drafts, transient failures,
late close/context reads, uncertain-save restrictions, exact create retries and responsive title/source controls.
No new test authorization bypass or failure-injection endpoint is added. Item 257 recovery evidence is retained for this
UI-only workflow; it must not be reported as a fresh restore execution.

The focused reuse run on `e7fec24` passed 10/10 in 41.7 seconds. Its report is
`sha256:95646616c21d7d1d140dfc05ddda7998e035551440cc5a74ef5a203711240385`.
The first run on `b4add9d` passed nine cases; its sole failure compared an API-created table without explicit unit-span
attributes against the editor's normal serialized `colspan: 1` / `rowspan: 1` cells. The synthetic source fixture now
includes those existing canonical attributes. Exact content equality and every source/history/access assertion remain;
the correction changes no runtime behavior. Initial desktop/tablet/mobile screenshots passed visual review.

Full verification on `e7fec24` passed all 180 checks in 664.306054 seconds: 145 browser cases and 35 model cases,
zero skipped, unexpected or flaky; all previous 170 remain included. Full Python quality passed Ruff, formatting across
691 files, Mypy across 541 sources and full Pytest, with only the known Starlette/AnyIO warning.
Browser report: `sha256:9792822a6de9a37b6b92acd67805e3f52ae535ad63836a70be176d72ea8f3237`;
quality log: `sha256:f66e1d0bacac61ebd7625e182d4293791b5b1c4856bd466d6b0a6db0f65a5cfe`.
Final artifacts are under ignored `e2e/work/artifacts/roadmap-259/final/`. Independent review passed all three final
screenshots with no clipping, horizontal overflow or unreachable controls. The API-only `--no-deps` rollout retained
pilot 0 and reached healthy at 2026-09-21 12:21:23 UTC. Live checks confirmed all thirteen Office OpenAPI operation
definitions, new and existing controls, assets/licenses, Work link and no-store/CSP. Cleanup finished healthy at 12:22:11 UTC with only regular
API/PostgreSQL/MinIO running; the exact E2E services were removed and auxiliary test/restore services stopped.
Ordinary Office remains unprovisioned, with its features, KB write and pilot closed. Roadmap 259 development is complete;
no main-database migration or new recovery drill was run, and no ordinary-tenant or production admission follows from this evidence.

Roadmap 260 adds eight title-discovery workflows and two responsive runs. Its dedicated synthetic
owner receives 225 tiny genuine PostgreSQL/S3 documents through the existing document-create service, and a separate
reader receives only three old entries. Existing user fixtures remain separate. The seed runs only after the isolated
environment guard and principal transaction commit, emits counts only, and changes no normal-runtime activation.
The cases prove complete unique pages despite a real saved rename, literal Unicode/wildcard/markup searches, ACL filtering
before limits, preserved document/review drafts, fresh write revocation and read denial, stale query/context cancellation,
and rejected tampered/cross-role cursors. The retry case drops a genuine upstream 200 response once and verifies the
same cursor against a new real read; it introduces neither a fabricated success nor a server failure-control endpoint.
The responsive case follows the real Work-to-Office link, then exercises search, append focus and reachable controls.
The first focused run on `e304b28` passed nine of ten and revealed that Work hid the only Office link on mobile.
The narrow product fix exposes that existing link in compact navigation; the test and its real-click assertions remain unchanged.

On `5bcb7d2`, all ten focused checks passed in 46.602456 seconds, with zero skipped, unexpected or flaky results.
Focused report: `sha256:663d6370c40b38e432000b458ea2f7fb662121fd3a0be3b19ddfdf2b59e42c03`.
Independent visual review passed desktop, tablet and mobile screenshots. Focused API log inspection found 51 list access
records with query/cursor values redacted.

Final verification on immutable `5bcb7d2` completed with quality and browser status 0 at 2026-09-21 13:01:19 UTC.
Ruff, formatting across 699 files, Mypy across 547 sources and full Pytest passed; only the known Starlette/AnyIO warning
remains. All 190 checks passed in 651.284899 seconds: 155 browser and 35 model cases, zero skipped, unexpected or flaky;
the previous 180 checks remain included. Independent visual review passed all five final screenshots: three Office
discovery viewports and two Work viewports. At 13:01:29 UTC, inspection of 306 actual list access records confirmed
query/cursor redaction. Final browser report:
`sha256:f11d3d0e6130351760439eec1ea7e71ae85de1fe881d76d2df4c9eee0ac8b8ef`;
quality log: `sha256:627d7e5a71376e443db09d5bc78e953c86298b699d3df8a8b2e3feaba1fc446c`.
The API-only `--no-deps` rollout retained pilot 0 and reached healthy at 2026-09-21 13:03:04 UTC (`6751b0ddada8`).
Live verification at 13:04:01 UTC checked all existing/new controls, the query/page-size/cursor contract, thirteen Office
OpenAPI operation definitions, assets/licenses, Work navigation and no-store/CSP; it did not execute all thirteen operations.
Ordinary Office remains unprovisioned with a 404; Office features, KB write and pilot remain closed.
Cleanup completed healthy at 13:04:19 UTC with Collabio running(3): the six remaining exact E2E containers were removed,
with the disposable runner already absent, and test/restore services stopped. Main PostgreSQL `87a6b37942c8` and MinIO
`98ce365f455b` were unchanged. Webcut remained running(7), three provider nodes and listener 26443 were unchanged,
and Tricert was absent. Roadmap 260 development is complete; no main-database migration or new recovery drill ran.
Roadmap 257 recovery evidence is retained. These checks authorize no ordinary tenant or production admission.

Roadmap 261 adds eight older-history workflows and two responsive runs; full validation has passed. A dedicated synthetic
author creates one genuine PostgreSQL/S3 document with 225 confirmed immutable versions, and a dedicated reader has
only its parent read grant. These principals are separate from the existing 225-document discovery fixture. The cases
exercise complete history, earliest rich content, current reader access, exact comparison/takeover/CAS, concurrent
heads, preserved document/review/suggestion drafts, lost genuine responses with same-cursor retry, invalid cursors and
late reads after comparison close, inspector hide, tab switch, focus mode and principal change.
The legacy bounded-history case now uses its own real 51-version chain and genuine 50-entry response, preserving its
partial-history, exact comparison and no-write takeover checks. No fabricated pagination response replaces the API.
Focused backend verification on `0bdd522` passed all 249 Python/API/PostgreSQL checks in 40.58 seconds. The focused
browser run on `46a83b4` passed 23 checks in 94.693441 seconds: ten new cases and thirteen existing version-workflow
cases, zero skipped, unexpected or flaky. Root and independent desktop/tablet/mobile visual review passed.
Actual Uvicorn logs verified 63 list and 110 history access records with query/cursor values redacted. Report:
`sha256:ef46cb8c44612e6dcb6261f784d42a5dbfbeaca1e1bf9604e3f6869bf5e464b3`, under ignored
`e2e/work/artifacts/roadmap-261/focused/`.
Full quality and all 200 checks passed on `46a83b4` at 2026-09-21 14:24:43 UTC. Ruff, formatting across 705 files,
Mypy across 551 sources and complete Pytest passed, with only the known Starlette/AnyIO warning. The matrix passed
in 688.743181 seconds: 165 browser and 35 model cases, zero skipped, unexpected or flaky. Root and independent
review passed all five final screenshots. Actual Uvicorn logs at 14:25:11 UTC confirmed query/cursor redaction across
322 list and 205 history access records. Final report:
`sha256:926b3a0c808d6baed3c65d904257cabc85996da6eb956f58eb5d7d03fb747e79`;
quality log: `sha256:296215f2c5250e1199918099f88565806f30b1a49276e818f457b312e1508025`.
The API-only rollout reached healthy at 14:25:53 UTC (`1585ccedc940`). Live verification at 14:27:03 UTC confirmed
thirteen Office OpenAPI operation definitions, history page_size/cursor parameters, new and existing controls, local
assets/licenses, Work navigation and no-store/CSP; it did not execute all thirteen operations. Tenant-demo Office
remains unprovisioned with a non-cacheable 404; Office features, KB write and pilot remain closed.
Cleanup completed healthy at 14:27:43 UTC: six remaining exact E2E containers were removed, with the disposable runner
already absent; postgres-test/postgres-restore/minio-restore were stopped. Collabio remained running(3), with unchanged
loopback ports 8000/5433/29000/29001. Main PostgreSQL `87a6b37942c8`, MinIO `98ce365f455b`, Webcut running(7) and provider
services were unchanged; Tricert was absent. Roadmap 261 development is complete. No main-database migration, new
recovery drill, ordinary-tenant write, indexing, cloud provider or engine activation occurred. Roadmap 257 recovery
evidence remains retained; these checks grant no ordinary-tenant or production admission.

Roadmap 262 adds paragraph alignment/spacing workflows and format-only comparison model cases. Acceptance includes
mixed selection, targeted table cells, undo, strict legacy roundtrips, historical comparison/takeover, write revocation,
exact save retry, context cancellation, responsive layout and a real multipage browser PDF. Validation is pending.
The synthetic seed adds one existing-author document with three exact versions: original defaults and two different
format profiles. It creates no additional principal or ACL grant. Reports include only counts and hashes.

After a green matrix, `office-native-recovery-proof` can verify a separately restored synthetic database and exact S3
versions. Only that disposable checker joins both the test and restore networks. It accepts only the fixed work-e2e source
and the fixed `collabio_work_e2e_restore` or `collabio_work_e2e_262_restore` target, with a read-only mount at `/proof-backup`;
both target DSNs must name the same database and the normal restore database is rejected. The separate 262 database
preserves the earlier synthetic snapshot. Its dump, checksum and receipt use a separate host directory mounted at the
same read-only container path.
The dump, checksum and restore receipt must result from a real operator-run pg_dump/pg_restore under the host locks.
Its read path verifies at least one document with two versions, source/receipt hashes and restored current ACLs.
Roadmap 256 extends the proof to nonempty review creation, reply, resolve and reopen events, complete review metadata
hashes and exact COMMENT source versions/receipts; parent ACL denial must still apply after restoration.
The Roadmap 257 extension also requires nonempty accepted and rejected suggestions, complete
proposal/decision inventory, exact original/replacement bytes and receipts, accepted result versions and current ACLs.
Roadmap 262 follows all document/history pages under existing active, currently ACL-authorized principals. Global
inventory equality, immutable predecessor chains and read-only capabilities remain mandatory. The original unformatted
fixture and both historical format profiles are pinned to exact canonical bytes, hashes and receipts after restoration.
Never run it while browser writes are in flight. It neither enables a module nor creates or drops databases. Preserve its JSON report
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
- `office-review-desktop-chromium.png`, `office-review-tablet-chromium.png`, `office-review-mobile-chromium.png`.
- `office-suggestions-desktop-chromium.png`, `office-suggestions-tablet-chromium.png`, `office-suggestions-mobile-chromium.png`.
- `office-print-desktop-chromium.png`, `office-print-tablet-chromium.png`, `office-print-mobile-chromium.png`;
- `office-print-rich-letter-landscape.pdf`, `office-print-history-a4-portrait.pdf`, `office-print-unprepared.pdf`;
- `pdf-qa/report.json`, extracted PDF text and rendered page PNGs from independent inspection.
- `office-reuse-desktop-chromium.png`, `office-reuse-tablet-chromium.png`, `office-reuse-mobile-chromium.png`.
- `office-discovery-desktop-chromium.png`, `office-discovery-tablet-chromium.png`, `office-discovery-mobile-chromium.png`.
- `office-history-pagination-desktop-chromium.png`, `office-history-pagination-tablet-chromium.png`, `office-history-pagination-mobile-chromium.png`.

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
