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

The expected matrix is 280 passing checks: 233 browser cases and 47 pure comparison/search/style model cases. The original
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

Roadmap 262 development validation is complete on `8b61d8d`. Nine new browser workflows, two responsive runs and
four additional comparison-model cases preserve the previous 200 checks. Coverage includes mixed selection,
targeted table cells, isolated undo, no-op/reset/cancellation, legacy roundtrips and canonical-byte limits; heading
shortcuts, Enter, input rules, lists, replacement and reuse retain exact attributes. Historical comparison/takeover,
fresh write revocation, identical save retry, context cancellation and actual browser PDF remain covered.
The synthetic seed adds one existing-author document with three exact versions: original defaults and two different
format profiles. It creates no additional principal or manual ACL fixture grant; normal Create supplies its creator ACL.
Reports include only counts and hashes.

All 294 focused Python checks passed in 18.05 seconds; all 46 focused browser/model checks passed in 150.538659 seconds,
with zero skipped, unexpected or flaky results. Focused report:
`sha256:312bf9c8d93747ad8ce7e5cb8a99400ee075bc4998b141f1039e711fc61dbe7f`;
focused Python log: `sha256:0c73376a480c923e0e77292ca7ec307c79c76cd2f72c67ca020dd7c29b1145b9`.
Full quality on the same source passed Ruff, formatting across 712 files, Mypy across 557 sources and complete Pytest,
with only the known Starlette/AnyIO warning. All 215 checks passed in 759.313613 seconds: 176 browser and 39 model cases,
zero skipped, unexpected or flaky. Final report:
`sha256:b9d422791168a5f1a8dc710eb1574a28fe373a928c44c11227bbd981380d71a6`;
quality log: `sha256:e60159bdafa33d3854347d8fdf6fc5f55bc4bb87c630f8e6ebdbefe6240d358c`.

The same-page PDF proof checked actual print-media alignment, line height and paragraph margins after fresh exact-version
authorization. Independent Poppler/QPDF checks verified three A4 pages (594.96 × 841.92 points), 5,233 extracted characters,
all 28 numbered paragraphs and both sentinels, H1/H2/P structure, no empty page and no shell/context leakage. The PDF is
`sha256:ab04640d1bb33ad12712de3303fa98037ebad2ae1ff7689baac1419de608222f`;
PDF-QA report: `sha256:b271848bc5b5c2e3f13f6a2c99621d64f69600cb203946d8ee5eb56ae17023b1`.
Independent visual review passed nine artifacts: three paragraph viewports, print preview, two Work viewports and all
three rendered PDF pages. Final, focused and PDF evidence is retained under ignored `e2e/work/artifacts/roadmap-262/`.

Fresh nonempty recovery into the separate `collabio_work_e2e_262_restore` database verified 330 documents, 666 exact
versions, 50 multi-version documents and 721 source objects. All three designated paragraph fixture versions passed:
one unchanged legacy version and two distinct saved formatted versions. Complete pagination and existing current parent
ACLs, source/receipt bindings, read-only restored services and foreign-tenant denial passed. The proof also retained
ten review threads/18 events and eleven suggestions/seven decisions, including five accepted and two rejected proposals.
The embedded recovery `report_hash` is `sha256:bfc720ee2ec275061c5f934369a5864259071d5409f7bd4f99368b431951c7f7`;
the retained `recovery.json` file SHA-256 is `bb02922322b46b09627d9c3f842534fda0cabec5d7ab541c58f0500e60fdd94c`.
Its verified dump is `sha256:a4481417a96ebff0af7070bf817fcf5ad01e975e9f4fa909717c906e947379f7`.
Earlier recovery data and evidence remain retained. No main-database migration was required. Both release gates passed
before the API-only rollout, which reached health at 15:17:23 UTC (`132526da7a34`). Live verification passed at 15:18:18
UTC; exact cleanup completed at 15:18:55 UTC with Collabio running(3), health ok and auxiliary services stopped. Full
host/gate evidence is recorded in `docs/CURRENT_HANDOFF.md`; ordinary tenants, pilot and production remain closed.

Roadmap 263 adds character formatting, caret/mixed/reset/undo, exact text/cell selection, comparison/replacement/reuse,
fresh write revocation and uncertain retry checks, with responsive screenshots and actual multipage PDF output.
The additional seed creates one normal creator-owned document with three versions: legacy and two distinct saved size/
color profiles. No additional principal or manual ACL fixture grant is introduced.

Development acceptance is complete through test-only `75f381a`; product code is unchanged since `d235b6b`.
Full quality on `a0b3001` passed Ruff, formatting, Mypy on 562 sources and complete Pytest. Both complete 231-case runs
retained 230 successes and one history-fixture setup failure. The first took 876.201937 seconds, the second 1020.268560.
The trace and immediate assertion show that the inherited rich-table fixture never acquired its draft before history
navigation. Keyboard input alone did not fix setup. After giving that case its own current head, all eight history
cases passed in 31.423815 seconds. Passing evidence covers all 231 distinct cases (188 browser, 43 model); this is
not a single 231-pass run, and both raw failure reports remain retained. No product guard or assertion was weakened.
Whole-document keyboard replacement across rich tables was left as a separate usability follow-up;
Roadmap 264 now exercises that path directly in `office-keyboard.spec.mjs` and the rich-head history regression.

Second full report: `sha256:2c902182d91ffe224d63d70c503ae28e1ad509ae15acbd4bca76afbd17abbec0`;
corrected history report: `sha256:35d3111f2630f7b699ef822942f29484237d1604707db12e2f2cac3e49d165d0`;
quality log: `sha256:50dc41d7ef0d6193a0a6552292e4efad0de6d4cedf9ff14934bbe55bce99e754`.
The ignored `roadmap-263/acceptance.json` summary explicitly binds these reports and their passing case identities.
The `final/results.json` filename is historical: it contains the second full run's one retained setup failure.

Root reviewed six final Office/Work screenshots and both rendered PDF pages. The actual A4 portrait PDF has two
nonempty pages, all 24 numbered paragraphs and both sentinels, 2,108 extracted characters and H1/H2/P structure.
PDF: `sha256:caf2da90f8834ad3f10ea054929f318c5dca4db3dfefbcc65c8d9effafed761a`;
PDF-QA report: `sha256:0330e6e9c8247b984db31452675a564d642630323034f8ffdbbfd73cba4845d3`.
Actual logs verified 752 document-list and 445 history records without query/cursor values.

Fresh recovery verified 460 documents, 935 exact versions, 116 multi-version documents and 1,045 source objects,
including all three character fixture versions and retained paragraph/review/suggestion proofs. Twenty review threads,
36 events, 22 suggestions and 14 decisions (ten accepted, four rejected) passed, with current ACLs, exact receipts,
read-only capabilities and foreign-tenant denial. Embedded recovery hash:
`sha256:9321026e05318ef59d6bd52216fa46c5a20bd9dc3532fd8a8c39ebf296deb0fd`; report file hash:
`sha256:f8b3f4fdd2545ce3ea5fc240d8d9701ce0569b3b0d24314dad7bae4d7e19ca64`.
Both release gates, API-only rollout and live verification passed; exact cleanup completed at 2026-09-22 07:17:20 UTC.
Full host details and backup/gate hashes are in `docs/CURRENT_HANDOFF.md`. No ordinary tenant/pilot admission occurred.

After a green matrix, `office-native-recovery-proof` can verify a separately restored synthetic database and exact S3
versions. Only that disposable checker joins both the test and restore networks. It accepts only the fixed work-e2e source
and a fixed `collabio_work_e2e_restore`, `collabio_work_e2e_262_restore`, `collabio_work_e2e_263_restore`,
`collabio_work_e2e_267_restore` or `collabio_work_e2e_268_restore` target,
with a read-only mount at `/proof-backup`;
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
before removing the exact test services. Keep the prior synthetic dump under ignored
`e2e/work/artifacts/office-recovery-backup` and the separate 262 dump under
`e2e/work/artifacts/office-262-recovery-backup`. The character proof uses `e2e/work/artifacts/office-263-recovery-backup`;
do not overwrite any earlier database, dump or receipt.

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
- `office-paragraph-desktop-chromium.png`, `office-paragraph-tablet-chromium.png`, `office-paragraph-mobile-chromium.png`;
- `office-paragraph-print-preview.png`, `office-paragraph-a4-portrait.pdf` and the independent PDF-QA report/rendered pages.

Treat browser output as test evidence, not production evidence. It contains only synthetic data, is not an activation
approval, and does not authorize real-user traffic. Record test counts, SHA-256 hashes and the exact source commit in
`docs/operations/DEV001_OPERATIONS_LOG.md`; do not commit the generated artifacts.

## Cleanup

After preserving hashes or failure diagnostics, repeat the preflight and remove only the profile's exact containers:

```bash
flock -w 300 /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio --profile work-e2e rm -f -s \
  work-e2e work-e2e-api work-e2e-blocked-api work-e2e-image-decoder work-e2e-seed work-e2e-migrate work-e2e-postgres work-e2e-minio
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

## Roadmap 264 whole-document keyboard acceptance

On d7270a7, all 241 browser/model cases (198 browser plus 43 model) passed in a single run in 873.553288 seconds,
with zero skipped, unexpected or flaky results, finishing at 2026-09-22 08:00:32 UTC. Full Python quality also passed:
Ruff, 722-file formatting, Mypy on 562 sources and complete Pytest, with only the known Starlette/AnyIO warning.
The earlier focused keyboard/table/history run on 460d632 passed all 26 cases in 94.556794 seconds. Ten new cases
exercise replacement across rich/table-only/multiple-table documents, cancel, exact undo/redo, confirmed real saves,
Unicode/literal multiline input, canonical-byte/character/control limits, cut, Ctrl/Meta selection, read/history gates
and invalidated context. The existing history case now owns a rich head ending in a table and confirms replacement
before checking preservation of document and review drafts across concurrent history operations.

The original failing reproduction remains in ignored roadmap-264/repro. AllSelection alone did not stop native DOM
mutation; cancelable beforeinput plus a validated full-document transaction fixes the keyboard path. The strict guard
was not weakened. Clipboard cases use browser ClipboardEvents and synthetic DataTransfer objects, without claiming
an OS clipboard roundtrip. Root reviewed desktop/mobile confirmation screenshots. No new IME, non-Chromium, PDF or
independent subagent proof is claimed. The prior Roadmap 263 recovery remains retained; the UI-only correction changes
no schema, persistence format, dependency or backend. Operational rollout details are in CURRENT_HANDOFF.md.

Evidence under ignored e2e/work/artifacts/roadmap-264/final:

- Report: sha256:a40528f367d8a032d2d2d2a0ae53304d5172b58e7c7c621a8bccdcaa0bf63efc.
- Browser log: sha256:2c78d8b26e6ceddf22b4e3a80a1b771e21a3c3d44d2ca2ca24c3268f0695df61.
- Quality log: sha256:fa15e300bf3abc15289f6b91106e0085a63428d696806007097e570105e681c8.
- Desktop screenshot: sha256:503846f9e257ec45d99b92807609639fa9887cd7208852116c296bda54ca0543.
- Mobile screenshot: sha256:f3ce324e6d6f8b0b3b4c9fff089c235ac1602718e93b32cfb4154dc094a3662f.

This is a single complete green run; the historical combined Roadmap 263 acceptance remains documented above.

## Roadmap 265 format-transfer acceptance

The new `office-format-transfer.spec.mjs` has nine workflow/boundary cases; the responsive specification runs on
desktop and mobile, with an additional tablet screenshot. They cover combined and separate scopes, exact Unicode
ranges, selected table cells, code exclusion, default clearing, mixed-source rejection, capture/discard/no-op,
pending typing marks, isolated undo/redo, real confirmed versions, canonical-byte rejection, context invalidation
and reader/historical views. The full matrix now has 252 cases: 209 browser and 43 model cases.

The first focused run on 655a00c passed nine of ten cases and found that a context change cleared the in-memory
sample but left its accessible DOM description stale. The correction clears both and retains pending character
choices during paragraph-only application. All 40 focused format-transfer/character/paragraph/keyboard cases passed
on 068152f in 147.939598 seconds, with zero skipped, unexpected or flaky results. The focused report hash is
sha256:0fcb8da497f6c863a0ecb7f1857373109389321af40bc627c132ed1ef89ad336. The original failure remains in ignored
`e2e/work/artifacts/roadmap-265/failed-focused/`; the corrected report is under `roadmap-265/focused/`.

Commit 2d42293 adds ADR-0088 and an explicit historical-view assertion to the already corrected product. Root reviewed
desktop, tablet and mobile screenshots for readable content, wrapping controls and absence of horizontal overflow.
This transfers direct formatting inside one editable document; it does not copy content, computed styles, block types
or code, and does not use the system clipboard or browser storage. There is no backend, schema, dependency or durable
format change. Roadmap 263 recovery and release evidence remain retained; no new recovery drill is claimed.
Full-run and rollout evidence is recorded in CURRENT_HANDOFF.md.

The first full run on 2d42293 passed Python quality and 251 of 252 cases in 919.852864 seconds. Its single failure
was the existing mobile review quote viewport assertion: the extra wrapping toolbar row shortened the inspector.
Correction ac70c29 gives mobile comments/suggestions the viewport between app bar and footer, retaining history and
outline placement. The first layout correction fa00102 passed 41/43 but covered history controls, so it was narrowed
to review drawers with their own close actions. That failed layout report/trace is retained under
`roadmap-265/failed-layout-focused/`, report sha256:acd6dd9bca3c25882359248c4ff835e5a7574fadca281395e4901c0ad8ed2e72.
Existing assertions are unchanged. Failed full report, logs and trace are retained under `roadmap-265/failed-full/`, report
sha256:b2ce2c257f2575a0285f581886f3e752f80be890946728a1c005fa761505ccf9. It is not an accepted full run.

All 43 responsive/format-transfer cases subsequently passed on ac70c29 in 235.258831 seconds, with zero skipped,
unexpected or flaky cases. Report under `roadmap-265/layout-focused/`:
sha256:60cdcd6a89e42b3afe5b04adec05ec035c48334b65e9c00a14ef493f73eeebba. Root reviewed the corrected mobile comments
and desktop/tablet/mobile format-transfer screenshots.

The final full ac70c29 run passed all 252 cases (209 browser + 43 model) in 908.294889 seconds, zero skipped,
unexpected or flaky, finishing at 2026-09-22 10:04:02 UTC. Full Python quality passed Ruff, 727-file formatting,
Mypy on 562 sources and all Pytest tests, with only the known Starlette/AnyIO warning. Both process exits were 0.
Root reviewed final transfer desktop/tablet/mobile and mobile comments and matched all nine artifact hashes locally.
Final ignored evidence under `roadmap-265/final/`:

- Report: sha256:41e8cc172dbdba55b580f75e76ca09245b933f279b07fb806fce52e5d293a899.
- Browser log: sha256:65cf557db8954241b6ac18ef6b5e9d065e87aff990908f1106ce93c87da43a4c.
- Quality log: sha256:c79ea12ebf98aad1a48fcc5275cf8bd2e9c5f83cd2b5b50e2a2cbadf87bb2586.
- Transfer desktop/tablet/mobile: sha256:099ebc2c36efc61c17b3b25150c631985f151ba30cce0fd994589bd34d908cec,
  sha256:410ad13975e17cae399d9ab3099f5a11d50f9080ccf65796882f0256e57d2a41,
  sha256:9c4743191e4357c33494899363226112a4adbca8b4cf34a3f158cf611f5ca136.
- Review desktop/tablet/mobile: sha256:f90bfaaf675178988772e5e7382dd59ae10bf63466be6d8fd2370db7387b77bf,
  sha256:7ae0506bfa275e0d2bc71c76335c875895ce98d008c56f7fdf4959723937f9aa,
  sha256:6d10fc148dd04166d73ec7c983cf94758f31ab55b5b3e503852230f1d7dd23ab.

API-only rollout, live verification and exact cleanup passed. Ordinary Office remains unprovisioned/features closed,
KB write false and pilot 0. No main migration or new recovery drill was required or claimed. This is a single green
full run on the final product, with all unsuccessful exploratory reports retained separately.

## Roadmap 266 native list levels and numbering

Commit fb8dbd3 adds ten list workflow cases and two responsive projects. They cover selected sibling indentation,
nested and outer-level outdent, exact text/mark/paragraph/sublist preservation, isolated undo/redo and immutable
confirmed versions; nearest ordered-list start values survive saved comparison and print preview. Cancellation,
invalid numbers and unchanged values remain clean. Pending typing marks, keyboard actions, table Tab priority,
unsupported selections, reader/history/context invalidation and pending/uncertain saves are directly exercised.
Depth and canonical-byte boundary fixtures prove that rejected candidate changes leave the draft unchanged.

All twelve focused cases passed in 31.591574 seconds on fb8dbd3, starting at 2026-09-22 10:26:00.778 UTC, with zero
skipped, unexpected or flaky results. Root reviewed desktop/tablet/mobile screenshots for visible and reachable
controls and absence of horizontal overflow. Focused evidence is retained under ignored
`e2e/work/artifacts/roadmap-266/focused/`; report sha256:a46840d97f7170b1bee7718e02bbb147f87b4840fc226eca2ac4b52e9cb80893.
This uses the existing list format and changes no backend, schema, dependency or durable contract. Roadmap 263
recovery/release evidence is retained; no new recovery or PDF-generation check is claimed for this UI-only slice.
Full quality passed Ruff, formatting across 728 files, Mypy on 562 sources and complete Pytest, with only the known
Starlette/AnyIO warning. The single full matrix on fb8dbd3 passed all 264 cases (221 browser + 43 model) in
967.211454 seconds, zero skipped/unexpected/flaky, finishing at 2026-09-22 10:46:48 UTC. Both process exits were 0.
Root reviewed final list desktop/tablet/mobile and mobile comments and matched all nine final hashes locally.
Final ignored evidence is under `roadmap-266/final/`:

- Report: sha256:7ae92a1f0dcdf8a9ede01bde58ab50ac460b534058a359963fd0d11220e86df8.
- Browser log: sha256:78c9ecfddb0d714a9e7422dc433775b6c67c56382e65f5a21d5054008ee4b9ad.
- Quality log: sha256:f86a759834d1f1adc1de1d063482db07b499767521a5e889bbaa0af28eabba4b.
- List desktop/tablet/mobile: sha256:d099d8eb920c87ad1162e51649199da4bb8c9ce85328ccca6339d5d0f55e08bf,
  sha256:16e167b29bc69ef07ca65930d1d5a680005ae0da8981160bf1c008565213b599,
  sha256:12be4be53d18dc1f95bd26abe63d7b53755e92f0d3d4038a04d52be86850c841.
- Review desktop/tablet/mobile: sha256:80b3f6a55f11b1dbf849b0e4f539afd8d06fe84ad10ca24b021df1c894764609,
  sha256:54d20f45d54cb147486805307c8f6e0546f851995bca9b3ff6caba3cfeef61d0,
  sha256:53ef3cb5f20f9d3ede79d9cf22e2e178802edc03654c7d0359fb0cf41d387225.

API-only rollout and closed-gate evidence is recorded in CURRENT_HANDOFF.md.

## Roadmap 267 document-owned format styles

Four style-model cases and ten browser workflows plus two responsive projects exercise the version-owned catalog.
Cases cover custom/preset creation, literal unique names, shared updates across nested paragraphs, inline and direct
paragraph overrides, pending typing marks, heading/list/split/cell transforms, cancel/no-op/remove/undo, 20-entry and
canonical-byte limits, readers/history/context, pending and uncertain saves, immutable history, replacement/comparison,
real tagged PDF output and independent document reuse. The runner mounts the exact product office-styles.mjs read-only.

Focused Python schema/API/PostgreSQL/recovery and related suites passed 414 cases on f7dcd55. All 16 focused browser/model
cases passed on 94af79a in 39.855151s. The initial full run passed 270/280, including every browser case, but ten existing
comparison-model cases rejected unnecessary copies of unchanged blocks. Commit 1e09a10 preserves unchanged subtree
references, and all 20 comparison/style model cases passed in 7.250867s. Existing assertions remain intact. Failed reports,
logs and traces remain under ignored roadmap-267/failed-focused and failed-full; the latter report hash is
sha256:bb63aa048babb8003f74516e643d805141bab9fa97c735467ea8643f24d23401. The corrected full run on 1e09a10 passed all 280 cases in 1029.824630s, with zero skipped/unexpected/flaky. Full quality also passed. Final reports, visual/PDF and operational evidence are in CURRENT_HANDOFF.md.

This adds durable native metadata. The synthetic seed includes one legacy and two different styled versions with an
unused definition. A fresh nonempty restore must use collabio_work_e2e_267_restore and its own backup directory/receipt;
all older synthetic targets remain retained. Verification includes exact catalogs, bindings, direct overrides, canonical
hashes, source receipts and read-only authoritative access, alongside all prior review/suggestion/formatting checks.
Main backup/restore and both release gates must precede the API-only rollout. Ordinary tenants, pilot, indexing and
engines remain closed. The separate image/object proposal is design only.

Final corrected acceptance is bound to 1e09a106be3505457d5eca9060797a132dc80f1e. Full report:
sha256:0306d0e3226d31275a52d11d667e4c2d9f011804905dba73c1e08053d5fded88. Actual one-page A4 PDF:
sha256:d85daa38834ea64bb9fc78a3f762cc11d32c39233e38ecd2099acf3221e64389. Root reviewed final desktop/tablet/mobile
styles, mobile comments and rendered PDF. Fresh recovery verified 392 documents,763 Office versions and 818 sources,
including legacy and both named-style states; recovery reporthashsha256:79d0a9f472f8cdefb7e854c882703126ae8c3f19c1240a1c2913985a72396a59.
Main backup/isolated restore and both gates passed; API-only rollout, live checks and exact cleanup completed at
2026-09-22 13:50:27 UTC. Collabio running(3), healthok, ordinary gates closed. See CURRENT_HANDOFF.md and the append-only
operations log for hashes, preserved unsuccessful runs and exact host scope. The then-planned Roadmap 268 native images is completed below.

## Roadmap 268 native images

The matrix adds three pure-model cases and seven browser workflows in each of desktop and mobile Chromium (17 new
cases). It exercises real PNG/JPEG normalization, upload/insert/edit/undo/save/history, independent copied assets,
current parent ACLs, revocation between document and print-image fetch, foreign/wrong-parent references, malformed
and oversized input, decorative images, cancellation, moving/removing nodes, responsive dialogs and actual PDFs.
The product image model is mounted read-only into the runner. The complete matrix now contains 297 cases.

`work-e2e-image-decoder` inherits the product decoder's network-none, credential-free, non-root/read-only restrictions
and resource limits, but owns `work_e2e_image_socket` and never restarts automatically. The test API waits for its health
and mounts only that socket. The normal `office-images` profile uses `office_image_socket` instead. Neither decoder
exposes a host port. The explicit cleanup list above includes the test decoder and preserves the regular image service.

For this durable image slice, retain a separate checked dump/catalog/receipt and restore target
`collabio_work_e2e_268_restore`. Do not overwrite the 257/262/263/267 targets. The recovery checker requires nonempty
image assets and saved references, then compares every retained rendition, parent ownership, exact metadata and
write receipt plus all image bindings across every saved version. Unattached uploads are included in the inventory.
Existing document, paragraph, character, style, discussion and suggestion evidence remains mandatory. Run main
backup/isolated restore and both release gates before the controlled decoder/API rollout; no main migration is needed.
Acceptance hashes, reviewed PDFs and actual counts are recorded in CURRENT_HANDOFF.md and the operations log.

Final acceptance: all297 cases passed in1157.649996s on96a299f, zero skipped/unexpected/flaky. Full quality passed on
5d3eb35; only Python test formatting and additional ACL/replay assertions differ, with identical runtime/browser sources.
Reportsha256:70439ccf0416762c42befb4c037ff413ee64a72cf1ec2fb74519907b213280bb. Both actual PDFs passed image/text/tag
checks and root visual review; all three responsive dialog views passed. Fresh recovery verified410 documents,
787 Office versions,858 sources,16 image assets and8 saved references. Recoveryhashsha256:
c40f85de4b5e11725eec576286ab16546f5eb57aba30d11271f3ebd457713eb3. Both release gates, controlled decoder/API rollout,
live verification and exact cleanup passed. Final2026-09-23 07:29:06 UTC: healthok, Collabio running(4), gatesclosed.
Roadmap269 non-destructive image cropping is the next proposed slice. Full evidence is in CURRENT_HANDOFF.md.
