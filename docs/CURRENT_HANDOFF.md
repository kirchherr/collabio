# Current Project Handoff

Updated: 2026-09-21

Roadmap 260 / PLANS 121 completes native Office discovery with server-side literal title search and cursor-based
loading beyond the initial 200 entries. Fresh ACL checks precede page limits; filtered list membership never clears
an open document or draft. Full quality and all 190 browser/model checks passed on `5bcb7d2`. Desktop/tablet/mobile
review, API-only rollout and final health/gate checks passed. Office development continues before CRM expansion.

Roadmap 259 / PLANS 120 completes saved-version reuse as an independent new document draft. Source read and create
permission are freshly checked after discard consent; the existing confirmed Create supplies the new identity and
creator ACL. Full quality and all 180 browser/model checks passed on `e7fec24`. Desktop/tablet/mobile visual review,
API-only rollout and final health/gate checks passed. No backend/schema/persistence/dependency change was introduced;
Roadmap 257 recovery evidence is retained, not rerun. Office development continues before CRM expansion.

Roadmap 258 / PLANS 119 completes saved-version print preview and browser print/PDF output. Office development
continues before CRM expansion. Full quality and all 170 browser/model checks passed on `cf2244c`; the final
cleanup-only test guard on `d8300aa` passed its affected browser case. Actual PDF text, dimensions, pagination,
semantic structure and visual output passed independent checks. There is no schema, persistence, dependency or API
change. Roadmap 257 recovery evidence is retained, not rerun. Final host verification is recorded below.

Publication state: on 2026-09-21 the operator explicitly approved publishing the prepared Roadmap 256 documentation,
including its operational metadata, to the public `kirchherr/collabio` repository and instructed work to continue.
Documentation commit `1545bb2` was pushed and synchronized. All 11 module/KB/roadmap contract checks passed in
58.85 seconds; health remained ok at 2026-09-21 06:34:16 UTC. The --no-deps test started no auxiliary service.
That Roadmap 256 publication is complete. Roadmap 257 then continued the authorized Office development below;
implementation `9c17a31` passed full validation, nonempty recovery and API rollout on dev001.
Roadmap 257 closeout `c4176de` was published and synchronized. All 11 documentation/module/roadmap contract tests
passed in 59.02 seconds; health remained ok at 2026-09-21 07:24:18 UTC. The --no-deps check started no auxiliary
service. Final independent evidence review confirmed all counts/hashes and clarified two historical module-document
references; those wording corrections change no implementation or tested contract behavior.
Roadmap 258 closeout `61d7fce` was published and synchronized. All eleven module/KB/roadmap contract checks passed
in 59.62 seconds, with only the known Starlette/AnyIO warning. Health remained ok at 2026-09-21 11:36:53 UTC;
Collabio still running(3), with no auxiliary service started by the --no-deps disposable test. Independent final review
matched all report/PDF/screenshot hashes and runtime evidence. This final evidence-only record changes no runtime or gate.
Roadmap 259 closeout `dd65d5a` was published and synchronized. All eleven documentation/module/roadmap contract checks
passed in 58.98 seconds, with only the known Starlette/AnyIO warning. Health remained ok at 2026-09-21 12:25:37 UTC;
the --no-deps disposable test started no auxiliary service. Independent review matched all report/log/screenshot hashes.
Final wording clarifies cancellation during reads, OpenAPI-definition verification and the absence of a main-database
migration or new recovery drill; isolated test databases did run their required migrations. These evidence-only changes
alter no runtime, tested behavior or gate.
Roadmap 260 closeout `b7b2cba` was published and synchronized. All eleven documentation/module/roadmap contract checks
passed in 59.43 seconds with only the known Starlette/AnyIO warning; health remained ok at 2026-09-21 13:07:23 UTC.
The --no-deps disposable check started no auxiliary service, and Collabio remained running(3). Independent review matched
all twelve checked report/log/screenshot hashes, counts and log-redaction evidence. Final wording updates the module's
continuation pointer, distinguishes matrix duration from full quality, and clarifies the additive existing-API contract.
These evidence-only corrections change no implementation, tested behavior or gate.

This is the canonical continuation document. Read `AGENTS.md` fully first, then this document, `PLANS.md`,
`docs/ROADMAP.md`, the append-only `docs/operations/DEV001_OPERATIONS_LOG.md`, and the relevant runbooks.
AGENTS.md and current code are authoritative. Green development evidence is not production or real-user approval.

## Repository and host

- Repository: `git@github.com:kirchherr/collabio.git`.
- Workstation: `C:\Users\tkirchherr\Documents\suite`; branch `kirchherr/kb-write-unit-of-work` tracks origin.
- Validated implementation: `5bcb7d2` (full Python quality and all 190 browser/model checks, including ten focused
  discovery checks). Backend/API and UI implementation is integrated in `e304b28`; `5bcb7d2` fixes mobile Work navigation.
  The commit containing this handoff is the continuation
  baseline. Verify local and remote HEAD before continuing.
- The user's untracked `erp_modul.md` and `review.md` must never be staged, rewritten or removed without instruction.
- Generated `e2e/work/artifacts/` output is ignored and must not be committed.
- PR/merge state has not been verified; do not assume a PR exists.
- All builds, tests, migrations and service lifecycle work run on `extern@dev001` in `/home/extern/collabio`.
- Use only `C:\Users\tkirchherr\.ssh\id_ed25519_collabio_dev001` for SSH and explicit Compose project `-p collabio`.
- Read `/home/extern/AGENTS.md` before operating. Source sync holds `/home/extern/.codex-coordination/git.lock`.
- Heavy work holds `build.lock`; lifecycle holds `docker.lock`; always acquire build before docker when both apply.
- Before every start, stop, recreate or restore inspect `docker compose ls --format json`, `docker ps`, and `ss -ltnH`.
- Never use daemon-wide prune, broad container matching, plain Compose down or down -v. Never change Webcut,
  Tricert or provider resources. If SSH or locks are unavailable, report the blocker; do not use local Docker.

Final item 260 host verification at 2026-09-21 13:04:19 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`6751b0ddada8`) with pilot explicitly 0;
bounded startup retries reached healthy at 13:03:04 UTC. Live verification at 13:04:01 UTC confirmed all thirteen Office
OpenAPI operation definitions, additive query/page_size/cursor parameters, new discovery and existing controls, local
assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned with non-cacheable 404; Office
features closed, KB write false, pilot 0. Six remaining exact Work-E2E containers were removed, with the disposable
runner already absent; postgres-test, postgres-restore and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`),
MinIO (`98ce365f455b`) and retained synthetic recovery data are unchanged. Webcut running(7), all three provider nodes
and listener 26443 unchanged, Tricert absent. No main-database migration, new recovery drill, ordinary tenant/business
content write, indexing, cloud provider or DOCX engine activation occurred; isolated test databases ran their migrations.

Previous item 259 host verification at 2026-09-21 12:22:11 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`a001838868f7`) with pilot explicitly 0;
bounded startup retries reached healthy at 12:21:23 UTC. Live checks confirmed thirteen Office OpenAPI operation definitions,
new reuse and existing controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned with
non-cacheable 404; Office features closed, KB write false, pilot 0. The six remaining exact Work-E2E containers were
removed, with the disposable runner already absent; postgres-test, postgres-restore and minio-restore are stopped.
Main PostgreSQL (`87a6b37942c8`), MinIO (`98ce365f455b`) and retained synthetic recovery data were unchanged.
Webcut running(7), all three provider nodes/listener 26443 unchanged, Tricert absent. No migration, business-content
write, ordinary tenant, indexing, cloud provider or DOCX engine activation occurred.

Previous item 258 host verification at 2026-09-21 11:32:51 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`fc8312db43b7`) with pilot explicitly 0;
bounded startup retries reached healthy at 11:31:16 UTC. Live verification passed thirteen Office operations, new print
and existing editor controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo Office remains unprovisioned
with non-cacheable 404; Office features closed, KB write false, pilot 0. Exact Work-E2E services were removed;
postgres-test, postgres-restore and minio-restore are stopped. Main PostgreSQL (`87a6b37942c8`), MinIO (`98ce365f455b`)
and retained synthetic recovery data were unchanged. Webcut running(7), all three provider nodes/listener 26443 unchanged,
Tricert absent. No migration, business-content write, ordinary tenant, indexing, cloud provider or DOCX engine activation.

Previous item 257 host verification at 2026-09-21 07:18:57 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`b4e2756191a1`); bounded startup retries
reached healthy at 07:17:41 UTC. Live checks verified thirteen Office operations, suggestion controls, previous editor
workflows, local assets/licenses, Work link and no-store/CSP. Tenant-demo remains unprovisioned for Office with
non-cacheable 404; Office features closed, KB write false and pilot 0. Migration 0085 is applied: 85 migrations, 95 tables.
Fresh verified backups, nonempty document/review/suggestion recovery and foundation/business gates passed before rollout.
Exact Work-E2E services were removed; postgres-test, postgres-restore and minio-restore are stopped. The synthetic
`collabio_work_e2e_restore` database and verified ignored dump remain retained; normal `collabio_restore` stays separate.
Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) were not recreated. Webcut running(7), all three provider
nodes/listener26443 unchanged, Tricert absent. No ordinary tenant activation or business-content write occurred.

Previous item 256 host verification at 2026-09-18 13:14:20 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`da71b8ef4e53`); bounded startup retries
reached healthy at 13:12:07 UTC. Live verification at 13:13:43 UTC confirmed nine Office operations, comments and existing
version/find/table controls, local assets/licenses, Work link and no-store/CSP. Tenant-demo remains unprovisioned for
Office with non-cacheable 404; Office features closed, KB write false and pilot 0. Migration 0084 is applied: 84 migrations,
93 tables. Fresh verified backups, nonempty document/review recovery and foundation/business gates passed before rollout.
Exact Work-E2E services were removed; postgres-test, postgres-restore and minio-restore are stopped. The new synthetic
`collabio_work_e2e_restore` database and verified ignored dump remain retained; normal `collabio_restore` stays separate.
Main PostgreSQL (`87a6b37942c8`) and MinIO (`98ce365f455b`) were not recreated. Webcut running(7), all three provider
nodes/listener26443 unchanged, Tricert absent. No ordinary tenant activation or business-content write occurred.

Previous item 255 host verification at 2026-09-18 12:10:34 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
unchanged loopback ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`5414963ff755`); bounded startup retries
reached healthy at 12:08:02 UTC. Live checks verified table, find/replace and version controls in the shell/bundle,
local assets/licenses, Work link, no-store/CSP and five Office operations. Tenant-demo remains unprovisioned for Office
with non-cacheable 404; Office features are closed, KB write false and pilot 0. Exact Work-E2E containers were removed
and postgres-test stopped. Main PostgreSQL/MinIO, stopped restore targets and retained synthetic recovery database were
untouched. Webcut running(7), all three provider nodes/listener26443 unchanged, Tricert absent. No migration was added.

Previous item 254 host verification at 2026-09-18 11:30:20 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only API was rebuilt/recreated (`1f30ae972f77`); bounded startup retries
reached healthy at 11:28:21 UTC. Live verification confirmed find/replace and previous version controls in the shell and
compiled bundle, local assets/licenses, Work link, no-store/CSP and five Office API operations. Tenant-demo Office remains
unprovisioned with non-cacheable 404; Office features are closed, KB write is false and pilot is 0. Exact Work-E2E
containers were removed and postgres-test stopped. Restore targets and retained synthetic recovery database stayed
untouched. Webcut running(7), all three provider nodes/listener26443 unchanged, Tricert absent. No migration was added.

Previous item 253 host verification at 2026-09-18 10:50:07 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated (`765b23c23888`); bounded startup retries
reached healthy at 10:47:56 UTC. Live verification confirmed the new comparison/takeover controls in the shell and
bundle, local styles/notices, Work link, all five Office operations and no-store/CSP. Ordinary tenant Office remains
unprovisioned with a non-cacheable 404; Office features are closed, KB write is false and pilot is 0. Exact Work-E2E
containers were removed and postgres-test stopped after evidence preservation. Restore targets stayed stopped;
the retained item 252 synthetic restore database was untouched. Webcut remains running(7), all three provider nodes
and listener 26443 unchanged, Tricert absent. No migration or new backup/restore was required for this UI-only workflow.

Previous item 252 host verification at 2026-09-18 10:17:19 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated (`e2e37654dd3d`). Live checks verified
`/office`, its local bundle/styles/license notices, the `/work` link and all five Office API operations. The ordinary
tenant is not provisioned for Office; its read returns non-cacheable 404, both Office features stay closed, KB write is
false and the normal pilot is 0. All 73 browser cases and final nonempty recovery passed before this rollout.
Exact Work-E2E containers were removed; postgres-test, postgres-restore and minio-restore are stopped. The synthetic
`collabio_work_e2e_restore` database and its ignored verified dump remain in the stopped restore target as evidence;
the normal restore database is separate `collabio_restore`. A future synthetic restore must account for the existing
target explicitly. Webcut remains running(7); all three provider nodes and listener 26443 are unchanged; Tricert is absent.

Previous item 251 host verification at 2026-09-18 08:43:14 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated. Webcut remains `running(7)` and all three
provider nodes remain unchanged (127.0.0.1:26443). Tricert was absent. Work-E2E containers were removed; postgres-test,
postgres-restore and minio-restore are stopped. Live checks confirmed the CRM workspace and KB content/authoring
routes, CRM detail and KB reader in `/work`, the disabled KB write feature in tenant-demo and pilot runtime 0.
Bounded health retries covered startup connection resets; health and the cold OpenAPI check then passed. The live
CRM read returns 503 with the exact existing dependency error `Productivity pilot authorization evidence is invalid`,
before reaching the CRM repository. The first smoke check expected 403/423 and failed; the repeated check explicitly
verified this fail-closed evidence error. No pilot evidence was repaired or activated. The isolated blocked process
with synthetic valid scope evidence separately proves its expected CRM 403; these are distinct checks.

## Non-negotiable boundaries

- Tenant isolation, authoritative ACL, ABAC, role and module/feature gates stay server-side.
- The normal switch stays `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. Synthetic tests never authorize real users.
- `knowledge_base.articles.write` defaults false. Only the isolated synthetic E2E tenant enabled it for this slice.
- Native Office uses `office_documents.documents.read` and `.write`, both closed by default. Migrations 0083–0085 do not
  provision or activate an ordinary tenant. Native documents do not authorize a DOCX engine or WOPI session.
- No real tenant module activation, KB runtime activation, business article write, pilot admission or traffic
  authorization was performed. Tickets & Incidents remains readiness-only pending separate explicit authorization.
- RAG and keyword indexing remain false. No LLM receives unauthorized data; retrieval requires authoritative ACL
  revalidation. Cloud AI requires tenant policy and all providers remain behind the Local LLM Gateway.
- Article/prompt/output bodies must not enter ordinary logs or audit metadata. LLM output is untrusted.
- Destructive, external and compliance-relevant actions require explicit human confirmation.
- Do not invent accountable principals, legal basis, privacy/workforce approval, independent review, signatures,
  production topology, PITR, offsite recovery, HA promotion or cross-site evidence.
- The project does not use AWS. Preserve provider-neutral/self-hosted architecture. No external legal review exists;
  do not claim certification or production readiness.
- No further Word-runner/account/firewall interventions on the original workstation. The separate disposable
  Windows test path only supplied a manual DOCX check.
- Fidelity private keys stay solely as Windows CurrentUser-DPAPI ciphertext under
  `C:\Users\tkirchherr\.collabio\signing`; never send them to Git, Docker or dev001.

## Development stance

Close coherent, user-visible product loops. Reuse the Platform Module System and the existing tenant, rights,
audit, classification, retention, Legal Hold, KMS, backup, restore, failover and decommission contracts.
Do not start preparation-only infrastructure chains without an immediate product or operating need.
Prefer mature maintained open-source components behind provider-neutral interfaces, reviewing credible alternatives
before adoption. The user's priority is Office development before further CRM expansion. Extend the native Office
workspace next; DOCX Quick Edit, full collaboration and Mail retain their separate extension points and release gates.
Commit and push verified slices; synchronize dev001 only with git pull --ff-only under git.lock.

## Last completed slice: Roadmap 260

The existing document-list operation now supports bounded literal title search and context-bound cursor pagination.
The UI requests 50 entries per page, shows loaded counts, and exposes clear next-page, reset and retry controls.
Current role/ABAC and typed ACL checks precede the page limit and lookahead. Creation time and object ID provide a
stable order across saves and renames; concurrent title/ACL changes remain live and this is not a frozen snapshot.
Cursors bind tenant, actor, roles, normalized query and page size. The per-service HMAC key supports the current
single-worker deployment; restart invalidates cursors and requires a list refresh. No shared multi-worker key is claimed.

Search and pagination preserve open documents and all local drafts independently of list membership. Manual refresh
reauthorizes the exact saved source and updates its write capability without replacing edited content or review drafts.
Actual read denial clears protected state; transient list/read failures preserve drafts. Historical takeover and
suggestion acceptance use fresh exact content permissions instead of filtered-list membership. Existing confirmation,
version/hash validation, CAS and exact save retry remain intact. Query text and cursors are excluded from audit metadata
and ordinary Uvicorn access records. The compact Work navigation now exposes the existing Office link on mobile.

Backend implementation `ac250d7` received formatting-only correction `35fdb1e`. Its real PostgreSQL revocation fixture
then required the existing mandatory revoked_at_utc value; `e304b28` corrects that fixture and integrates the UI/tests.
All 180 focused Python checks passed in 23.04 seconds, including genuine PostgreSQL authorization-before-limit tests.
The first browser run passed nine of ten and found the hidden mobile Work link. Product correction `5bcb7d2` preserves
the unchanged real-click test. All ten focused browser checks then passed in 46.602456 seconds, zero skipped/unexpected/flaky.
The separate synthetic author owns 225 real PostgreSQL/S3 documents; a separate reader can see only three oldest entries.
Independent desktop/tablet/mobile visual review passed. Actual Uvicorn logs verified 51 redacted list access records.

- Focused report: `sha256:663d6370c40b38e432000b458ea2f7fb662121fd3a0be3b19ddfdf2b59e42c03`.
- Focused Python log: `sha256:424ede12b4e521f026d5e8535595879e23de559bc4e7cd9cf7d1026d9cd622c5`.
- Failed initial browser report: `sha256:74199fc7e94aaa0580778fcef451c7d7a4f81cf4faf77369672fc404879b37c4`.
- Failed PostgreSQL fixture log: `sha256:0d6509f0c156b72c42c8502a12ac8872fe6ff9c8ad974a1f137bbfc8d328c29c`.

Full acceptance completed on immutable `5bcb7d2` at 2026-09-21 13:01:19 UTC:

- Ruff and formatting across 699 files, Mypy across 547 sources and complete Pytest passed; only the known
  Starlette/AnyIO deprecation warning remains.
- All 190 checks passed in 651.284899 seconds: 155 browser and 35 model cases, zero skipped/unexpected/flaky.
- Final report: `sha256:f11d3d0e6130351760439eec1ea7e71ae85de1fe881d76d2df4c9eee0ac8b8ef`.
- Quality log: `sha256:627d7e5a71376e443db09d5bc78e953c86298b699d3df8a8b2e3feaba1fc446c`.
- Independent final visual review passed all three Office and both Work screenshots, including mobile navigation.
- Office desktop: `sha256:2dc5a26e4a3e5002f221e9d01fc4852de6ac984ea41c7ff240a6310f871ce23e`;
  tablet: `sha256:b05b0ef9fed915953a45a12858b1e12eb70bc2b09f80b7c9091e39facae323b8`;
  mobile: `sha256:7623c55a537cba751d8626bc4a6a4edb03f87e6265ae836e0083390d529909df`.
- Work desktop: `sha256:8280b8ca8309031eefea8d13080c9d0f97d0840a5621d5490869fdeecd5f9796`;
  mobile: `sha256:693614c26b4f68e2ac4558a01d36368ed3c6221f0a702a7bc411e5f6621bc482`.
- Actual Uvicorn logs verified 306 list access records without query/cursor values at 13:01:29 UTC.

Ignored reports and diagnostics remain under `e2e/work/artifacts/roadmap-260/`. API rollout, live verification and
exact cleanup passed as recorded above and in the append-only operations log. No schema, durable storage or dependency
change is introduced and no endpoint is added; the existing read endpoint receives additive parameters/response fields.
No main-database migration or new recovery drill is claimed. Roadmap 257 recovery evidence remains retained.

## Previous completed slice: Roadmap 259

Saved current or historical native Office versions can now become independent memory-only drafts through
"Als neues Dokument". The dialog identifies the saved title/version/date and accepts a bounded new title.
Unsaved source edits are excluded. Canceling or a transient read failure preserves the current document and
discussion/suggestion drafts. Existing discard consent precedes fresh exact-version content and create-capability
reads; validation and detached editor preparation finish before the workspace is replaced.

Source read access plus create capability suffices; source write access is unnecessary. The bounded listing is not
used to authorize the source. Busy, uncertain or conflicting saves cannot be reused; close/context/session changes
reject late responses. The fresh editor has no source object/version, mutation attempt, history, ACL or discussions.
No write occurs until the existing explicit Create confirmation. That operation checks current create rights and
retains exact retry after an unknown outcome. This is a local drafting workflow, not an atomic server-side copy or
a persisted provenance link; later Create does not reauthorize the former source.

Implementation `b4add9d` initially passed nine of ten focused checks. The rich-content fixture omitted standard
unit-span table attributes that the established editor serializes explicitly. Test-only correction `e7fec24` supplies
those attributes without weakening exact content equality. All ten focused checks then passed in 41.694688 seconds.
Full quality and all 180 browser/model checks passed on the same immutable source at 2026-09-21 12:20:09 UTC:

- Ruff and formatting across 691 files, Mypy across 541 sources and the complete Pytest suite passed;
  only the known Starlette/AnyIO deprecation warning remains.
- 180/180 in 664.306054 seconds: 145 browser and 35 model cases; zero skipped, unexpected or flaky results.
- Final desktop/tablet/mobile screenshots passed independent visual review with no clipping, overflow or hidden actions.
- Final report `sha256:9792822a6de9a37b6b92acd67805e3f52ae535ad63836a70be176d72ea8f3237`;
  quality log `sha256:f66e1d0bacac61ebd7625e182d4293791b5b1c4856bd466d6b0a6db0f65a5cfe`.
- Focused report `sha256:95646616c21d7d1d140dfc05ddda7998e035551440cc5a74ef5a203711240385`;
  failed first report `sha256:54fb33988aaa253b66b662fcd19828c499890c43fbfb34554ae9c01f4cf8691b`.
- Final screenshots: desktop `sha256:30606618ab192d770dc04d6a1e1ec3e24c5e58250703d33aa735c712cf841ca2`,
  tablet `sha256:0f2adf14eca0cf9445f9c4051183e72f7855043fef27a9ebcbe8505d29d40b1a`,
  mobile `sha256:1190b026f1d0f7ee0cbfab9d26573a137e56251528bd3f3b89299a82a14819f5`.

Reports, logs, screenshots and failed-run diagnostics remain ignored under `e2e/work/artifacts/roadmap-259/`.
All execution used dev001 Compose project collabio, required locks and fresh lifecycle inventories. Quality and browser
tests used separate test databases. API rollout, live verification and cleanup are recorded above and in the append-only
operations log. Thirteen API operations, schema, storage and gates remain unchanged. No new recovery execution is claimed.

## Previous completed slice: Roadmap 258

Roadmap 258 / PLANS 119 completes native saved-version printing. A clean current or historical version opens a
literal, semantic print preview with A4/Letter and portrait/landscape settings. Readers may print without write rights.
The existing exact-version endpoint freshly rechecks current access both on preview and immediately before the
explicit browser call. Historical output uses its own saved title. Dirty, new and unresolved-save states remain blocked;
no content is implicitly saved or discarded. Prepared output is cleared after printing, close or context invalidation.

The browser controls final pagination, destination and settings; opening its dialog does not prove output completed.
The isolated print surface excludes editor controls, context, comments and suggestions. Other print entry points show
neutral guidance. Native headings, lists and table cells survive PDF structure export; the preview becomes temporarily
nonmodal during the browser call, then returns only for the still-valid session. No PDF/UA or cross-browser fidelity
claim, server export, new receipt, storage derivative, dependency, migration or engine admission is added.

- Full quality on `cf2244c` passed Ruff, formatting across 689 files, Mypy across 541 sources and full Pytest;
  only the known Starlette/AnyIO warning remains.
- All 170 checks passed in 562.234 seconds: 135 browser cases plus 35 comparison/search-model cases, zero skipped,
  unexpected or flaky. The previous 162 checks remain. Twelve targeted error cases passed first. The final
  cleanup-only guard on `d8300aa` passed its affected parallel-revocation case in 9.0 seconds.
- All eight print cases cover exact saved/historical content, ordinary readers, literal markup, all supported native
  structures, paper/orientation, current ACL revocation, transient failures, late responses, dirty/unresolved states,
  output isolation and responsive layout. Same-page Chromium PDF generation exercises the freshly prepared product surface.
- Independent Poppler/QPDF inspection verified all 80 numbered paragraphs and final sentinel across nine Letter
  landscape pages, preserved text and table content, A4 historical output on one page and one guidance-only page.
  Real H1/P/list/table/header/data-cell dictionaries are present; no application-shell or protected-current-version leakage.
  Desktop/tablet/mobile screenshots and all eleven PDF pages were visually reviewed.
- The first complete runs passed 169/170 on `a939b1b` and 168/170 on `4545d48`; all print cases passed. Existing
  error-body observations failed because Chromium discarded streamed no-store bodies. Test-only buffering preserves
  actual upstream status/headers/bytes and has no retries. A focused 11/12 run then exposed the expected canceled
  sibling request after a parallel 404. Its observer now checks the identical request's ERR_ABORTED and waits for both
  reads before restoring the synthetic ACL. Subsequent focused and full runs passed. Failed reports/traces remain retained.

Ignored final evidence under `e2e/work/artifacts/roadmap-258/`:

- `results.json`: `sha256:8198c66138af5af63d6d767ab9e8c4c06acaf18e60013809ed31879f39faa86f`.
- `quality.log`: `sha256:541ce600a21a8651c99c4cb0182b24c80f5f0b3132b161c7099ea4c164d4de1a`.
- Desktop: `sha256:1cf476412f3b51cc20110eadf1d816b8669e01e19352357c82e4cab8a325f924`.
- Tablet: `sha256:b8e061e59054f8c8b6e35c6e6e569c5de0313ff5c3c5535c08f335010ac99654`.
- Mobile: `sha256:42524d1e6f332e586d4b9e48b631584cc744254ede18120aa979b18265c058c8`.
- Rich PDF: `sha256:15c5bb6c81b7fd75a9b53ad22e1c80496f3b34584ee6bc654a8133b0b7a13785`.
- Historical PDF: `sha256:3e6094137a2b1e78191b7ba08c01d970d0250c78f179f22904e5ac562f428a67`.
- Guidance PDF: `sha256:233a9b4e3b27324c3ed86362813b0fe5f8fa6cb8bbc37dcd9bd0f84eeb1cb495`.
- `pdf-qa/report.json`: `sha256:598c1e210e3cb3f4920d78120b479d36f42bb8f8d8bfb6cf3677b61a3bedb63b`.
- First failed full report: `sha256:18415b02c2ddc62922231905f297ba9dd7dbdf800e0fe64d1171de9d862191f9`.
- Second failed full report: `sha256:0cb6cfd6cad7cc95d1d359f1ba3314e75978d0c4dde43349964bd58a9b1b5cb4`.
- Failed error-focused report: `sha256:8bc6dc421e49ceb88018d48c05dffe94623c0655e64960037ccdaecf2c77d8bf`.

## Previous completed slice: Roadmap 257

Roadmap 257 / PLANS 118 completes explicit saved-text suggestions: select text in a clean current saved version,
propose replacement (including deletion), inspect literal before/after and confirm accept or reject. Acceptance
saves its immutable decision and exact new document version in one PostgreSQL transaction and shared Office tenant
lock. Rejection appends only its decision. Historical anchors never move automatically; stale acceptance conflicts.
Fresh current parent ACLs, write-feature gates, strict revisions and actor-bound exact retries apply to every mutation.
The fourth inspector tab uses memory-only drafts, current capabilities, explicit confirmation, conflict preservation,
uncertain-result retries and close/context invalidation; known success cannot trigger a second write after refresh failure.

Migration 0085 adds append-only `office.text_suggestions` and `office.text_suggestion_decisions`, immutable COMMENT
sources/receipts, forced RLS and exact source/result bindings. A deferred constraint trigger prevents an acceptance
version without its decision. Public saves reject reserved internal acceptance references before any PUT. S3 remains
outside PostgreSQL rollback; focused tests prove metadata rollback and detectable orphans after storage/DB failures.
The restore gate pins all six Office tables, grants, policies, constraints and complete trigger functions, including
the deferred requirement. Continuous keystroke tracking, automatic merge and live collaboration are not implemented.

- On `0d5350d`, all 688 focused backend/API/PostgreSQL/recovery tests passed in 52.37 seconds and ten focused browser
  runs passed in 50.1 seconds. Full Python quality on `9c17a31` passed Ruff, formatting across 684 files, Mypy across
  541 sources and full Pytest; only the known Starlette/AnyIO warning remains.
- The full matrix on `9c17a31` passed 162/162 in 535.956 seconds: 127 browser cases plus 35 model cases, zero skipped,
  unexpected or flaky results. All previous 152 checks remain. Final desktop/tablet/mobile screenshots passed
  independent visual review. Code review and independent recovery review also led to alias-safe success responses,
  preserved-title validation and reserved-reference rejection before the final full run.
- Fresh nonempty recovery restored 67 documents, 109 versions, 36 multi-version documents and 162 source objects.
  Nine review threads/17 events include the complete prior review lifecycle. Ten proposals and seven decisions include
  five acceptances and two rejections. Exact original/replacement bytes, receipts, result content/title/lineage,
  current ACLs, foreign denial and read-only restored services passed. Report
  `sha256:e1ab971a88c43ff06c12544ba24619731b2b8304908da53ab5b73ad8bb017c53`; synthetic backup
  `sha256:06bbf77f9e41db9a7ecbc525bf17fd3e69c08b8dac7840ade2e7f10ecb9f4160`.

Ignored final evidence under `e2e/work/artifacts/roadmap-257/`:

- `results.json`: `sha256:42317e268bb6cd56cff3d85615bc012aed06d28ccd88f99b62228cdc03168e47`.
- Desktop: `sha256:79d78928d16ff5c35fdcbe95640037fbf07e92ba6af8b026b8cf2a6f3108983e`.
- Tablet: `sha256:3325d16574ccea994966ad6e474821595c592a752c99fb0dbac5c7f00000fa79`.
- Mobile: `sha256:199bf6260aea647f747ee875edb8d6b0899598cc87d9ec41786f1ef804ec7e77`.
- `quality.log`: `sha256:6b49b2f2fa706fd0d42baee0a72a19111e404f66309eca3a554830804cd19a21`.

Main migration/release evidence:

- Pre-0085 `collabio-20260921T071612Z.dump`: `sha256:ed83da613feb5792a209bf428630df302804dcfe377af9b89e1e58182de63a83`.
- Post-0085 `collabio-20260921T071618Z.dump`: `sha256:c937926687291d847cd07daaf36034a5318bead0c13926322ac3ba2035934aeb`.
- Foundation-bound PostgreSQL restore: `sha256:1a2d6c846bd5617ffbf20175aed5a97155c85144f5be107b3d64b345a38f5045`.
- Foundation: `sha256:f257c62d06ba81432a909f60161faba69c1d9e3db82f998c4cfdbd02c1294ffd`; 85 migrations/95 tables,
  expanded Office controls and three existing main sources restored, with source seeding explicitly disabled.
- Business release: `sha256:b14e152ee2355a82a1a22cb06457daac58fe2fa0149d32b8df31678e618dca63`; existing CRM/Tasks/Time
  three-slice gate passed without business writes or tenant activation. Office has the separate nonempty proof above.

Primary implementation: `office_suggestions.py`, `office_suggestion_repository.py`, the transaction-scoped document
persist primitive, Office API/UI and migration 0085. Tests include `test_office_suggestion*.py`,
`office_suggestion_recovery.py`, the shared restore gate and `office-suggestions*.spec.mjs`. See ADR-0081,
the Office module document, Work E2E runbook and append-only operations log. The initial restore helper typo stopped
after dump creation and before target modification; its corrected resume verified that dump and completed the proof.

## Previous slice: Roadmap 256

Roadmap 256 / PLANS 117 completes native Office review discussions: comments on an exact saved version or selected
text, replies, resolve/reopen and explicit confirmation. Historical discussions keep their original version and quotation.
The server derives bounded Unicode-safe anchors from exact saved content. Every operation checks current parent rights;
mutations also require the existing write feature, thread revision CAS and actor-bound exact retries. Comments do not
create or modify document versions. Literal bodies/quotations stay in immutable COMMENT SourceObjects, never normal logs.

Migration 0084 adds `office.review_threads` and append-only `office.review_events` with source/receipt bindings, forced
RLS and guarded heads. The comments inspector uses memory-only drafts, paginated discussions, exact-version highlights,
current capabilities, explicit conflict refresh and safe retries after uncertain writes. Late responses are discarded;
compact layouts use a closable scrollable overlay. No editing/deletion of comments, notifications, tracked changes or
live collaboration was introduced. There are now nine Office API operations.

- Initial implementation through `c7cff5d` passed 389 focused backend/API/PostgreSQL/restore tests and full Python quality.
  Ten focused browser cases passed in 44.978 seconds. The first full run passed 150/152; two Chromium response-body
  observation errors affected expected 409/503 cases. `7400b35` captures those real upstream responses unchanged,
  without retrying writes or generating test responses. Final full matrix: 152/152 in 432.486 seconds, zero skipped,
  unexpected or flaky; 117 browser cases plus 35 model cases. All prior 142 checks remain. Final screenshots were
  visually checked by root and an independent UI reviewer.
- Independent restore review found omitted unrelated Office grants/MAINTAIN and unpinned review CHECKs. `1cf9ee9` and
  `552b6b6` capture all direct Office grantees and effective column grants, exact owner/runtime rights and nine canonical state/anchor/byte
  CHECKs. Thirty-seven regressions include three real PostgreSQL grant cases. One old fixture assumed the first grant
  belonged to the runtime; `2305a96` selects that role explicitly. All 269 focused restore/recovery/backup checks passed
  in 23.40 seconds. Full quality on `2305a96`: Ruff/format 674 files, Mypy 532 sources and full Pytest passed, with only
  the known Starlette/AnyIO warning. No product/UI/schema behavior changed after the successful browser run.
- Fresh nonempty PostgreSQL/S3 recovery on `2305a96` restored 57 documents, 93 exact versions, 30 multi-version
  documents and 129 total sources. Nine discussions and 17 events include three selected-text anchors, one historical
  discussion and one complete create/reply/resolve/reopen lifecycle. Exact bytes/quotations/receipts, current ACLs,
  foreign-tenant denial and read-only restored services passed. Report
  `sha256:330a544deb64fbcb374d1c23732660cb7c2f80b8a2f2cc14289b8e2fa59fae92`; synthetic backup
  `sha256:3d9fe80e786c501967d30a5b1e75614cd55e60bfb46e815d926fcb2093e64af6`.

Ignored final evidence under `e2e/work/artifacts/roadmap-256/`:

- `results.json`: `sha256:96f4a596d21e395073967745c1811448fdbc2e04bc7f2f7e20ae4e4075fe156f`.
- Desktop: `sha256:a09972a0509a51e31f1a62e3cb33e966d5d29d728dbc80c96966fe47c1fc6827`.
- Tablet: `sha256:f499a343c87bd0c735c15ce38726b28cc6331a3a2b8f431e9217943f0e2b4452`.
- Mobile: `sha256:4783a6257d6db4f312449298c7ec207682122028aa9a49e088724d3f73564e28`.
- Final quality log: `sha256:4274b75408916a13e6ef41885ce7f3dc2c1a89d21a73cc85a7d3cd5416f3769e`.

Main database migration/release evidence:

- Pre-0084 `collabio-20260918T131039Z.dump`: `sha256:ec98cd064b010c2d905ed64ab97a84a0edc186ed9c1d99ef19499140a0abfc06`.
- Post-0084 `collabio-20260918T131046Z.dump`: `sha256:b3058ce54bb3a0b36ef97af1c031fcca1c0315797a930b0531fb6602ac27602b`.
- Foundation-bound PostgreSQL restore: `sha256:14dfaf92e80eef0a9a6967a06f2a666d79445e03dea423e4e452ec48bab09b68`.
- Foundation: `sha256:4ee5691940bec2e1b2b48623bf8a671e67efaaa8232057a01e913c3ab820b4ce`; 84 migrations, 93 tables,
  expanded Office controls verified and three existing main sources restored. Source seeding was explicitly disabled.
- Business release: `sha256:e8109c8e126d80fd4bd55f16a5c432e8841e5c44a374de654b8e1eaaa354faa4`; existing CRM/Tasks/Time
  three-slice gate passed without business writes or tenant activation. Office has the separate nonempty proof above.

Primary implementation: `office_reviews.py`, `office_review_repository.py`, `office_api.py`, Office UI, migration 0084;
`tests/test_office_review*.py`, the expanded restore verifier/product proof and review E2E cases. See ADR-0080,
`docs/modules/OFFICE_NATIVE_DOCUMENTS.md`, `docs/operations/WORK_E2E.md` and the append-only operations log.

## Previous slice: Roadmap 255

Roadmap 255 / PLANS 116 completes contextual table editing in `/office`: custom size and optional header on insertion,
rows above/below, columns left/right, first-row header toggle and cell/row/column/table selection. Removal requires
explicit confirmation, including whole-table Delete/Backspace; cancellation preserves the draft. Each structural edit
is one undo step separated from typing. Tab moves between cells and creates a bounded new row from its first cell;
when extension is unavailable, focus leaves the table for an available control. Legacy menu actions share the same path.

Native ProseMirror transactions are staged before dispatch. A global document guard also checks keyboard/paste/undo
changes against schema, rectangular geometry, 200 rows/20 columns and existing codepoint/node/depth/canonical-byte
limits. Read-only/history/loading/saving/restoring/uncertain states prohibit edits. Dialogs bind session, revision,
document and selection; context changes discard pending actions. Existing confirmed CAS save alone persists changes.
The inspector closes on entry to tablet width to avoid covering the table; explicit reopening remains available.

- Initial `93cbd71` focused run passed 9/10; the remaining test asserted a disabled option with an unsuitable control
  matcher. `a27c433` checks its native disabled property; all ten focused cases passed in 38.975 seconds. No product
  permission or size check was weakened. Visual review then prompted the tablet fix and regression in `e3cf88c`.
- Full quality on `e3cf88c`: Ruff/format across 665 files, Mypy across 526 source files and full Pytest passed; only the
  known Starlette/AnyIO warning remains. Full matrix: 142/142 in 359.156 seconds, zero skipped/unexpected/flaky,
  consisting of 107 browser cases and 35 model cases. All previous 132 checks remain; eight workflows and two
  responsive runs are new. Final desktop/tablet/mobile screenshots were visually reviewed.
- Proof includes real version saves/reopen/immutable history, preserved marks, structure and cell selections,
  isolated undo/redo, immediate focus, removal cancellation, keyboard-created rows, blocked final-row expansion,
  valid-dimension but excessive canonical bytes, reader/history, pending/uncertain saves with retry and context changes.
- Documentation closeout `58b9f9e` passed all 11 targeted module/KB/roadmap contracts in 59.83 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 12:13:31 UTC.
- No dependency, schema, API, storage or tenant activation change. Item 252 migration/backup/nonempty recovery/
  foundation/business proofs remain retained, not rerun. Primary implementation is the existing Office JS/HTML/CSS;
  tests are `office-tables.spec.mjs` and `office-tables-responsive.spec.mjs`.

Ignored final evidence under `e2e/work/artifacts/roadmap-255/`:

- `results.json`: `sha256:89c132f192d7a3302ab3a48dc201dfdc0f60c007e8334c993e79be9f7df9d2d8`.
- Desktop: `sha256:e939f0f5d8fe69b8536e4c8d23b0a0b85625c33ee3cd74f985dbb41bfb3584c0`.
- Tablet: `sha256:46f02424be9de63d73e4941e1443fa77d975a655c0b466410facf84652335c39`.
- Mobile: `sha256:8c97a0b58cae3e26d342db1bfc17e9257f6aee14b9b871b1b202fe367cc29500`.

## Previous slice: Roadmap 254

Roadmap 254 / PLANS 115 completes literal find/replace in `/office`: Unicode-safe original positions, case and whole-word
options, complete counts, previous/next navigation, current/all replacement, keyboard shortcuts and responsive controls.
Matches span adjacent formatting nodes but never cross paragraphs, hard breaks or cells. Untouched text/structure stays
intact; replacement inherits the first matched character's marks. A labelled 200-match highlight window follows the
active result; all results remain navigable and replaceable. Character/node/depth/canonical-byte limits are checked
before applying changes. No regex/HTML interpretation, background request, new dependency, index or persistence format.

Replacement affects only the local draft as one undo step isolated from adjacent typing. Read-only/history and busy or
uncertain-save states prohibit replacement. Existing confirmed CAS save persists a new version. Loading a document is
excluded from undo history, so undoing its first edit cannot erase the loaded source. Context/panel/workspace clearing,
cancelled discard, no-op, source history and safe retry contracts remain intact.

- Source `1142642` first passed 24 focused checks; one test incorrectly ignored a lowercase match, and undo exposed
  initial content loading as a history event. Both were corrected in `f4c37e5`. All 32 focused checks then passed.
- Full quality on `f4c37e5`: Ruff/format across 665 files, Mypy across 526 source files and full Pytest passed; only the
  known Starlette/AnyIO warning remains. Full matrix: 132/132 in 291.588 seconds, zero skipped/unexpected/flaky,
  consisting of 97 browser cases and 35 model cases. All prior 100 checks remain; nine browser and 23 model cases are new.
- New proof includes actual saved replacements/reopen/version comparison, isolated undo/redo, current/history reader
  restrictions, literal hostile text, complete large result sets, no-op/delete/expansion limits and late context reads.
  Model proof reaches 100,000 matches and checks original Unicode positions, mark boundaries and resource preflight.
  Final desktop/tablet/mobile screenshots were visually reviewed.
- Documentation closeout `d63139c` passed all 11 targeted module/KB/roadmap contracts in 61.97 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 11:32:44 UTC.
- No schema or durable contract change; the item 252 migration/backup/restore/foundation/business evidence below
  remains retained, not rerun. No tenant/pilot/indexing/engine activation. Main code is `office-search.mjs` and the
  existing Office UI; tests are `office-search-model.spec.mjs`, `office-search.spec.mjs`, `office-search-responsive.spec.mjs`.

Ignored final evidence under `e2e/work/artifacts/roadmap-254/`:

- `results.json`: `sha256:e12cf71865e5a013852d6482b6a96a33d5a37c4c031157721d0d980324d32b71`.
- Desktop: `sha256:301e7030dd649df94023e5ac4d2e81d2385cbf10b7fb530ab44b832eeaa91350`.
- Tablet: `sha256:32174cead5fdc1d292439d6633fe2f71f350a73984de4d9c7100287662094ccc`.
- Mobile: `sha256:0cfac05e9a82fd705655c7e9831e868ac334afb313e4f48d24f14e489d508613`.

## Previous slice: Roadmap 253

Roadmap 253 / PLANS 114 adds saved-version comparison and historical takeover to `/office`, using the existing five
Office APIs. Text, titles, format-only changes, lists and tables are compared as literal block content. Bounded alignment
preserves every input block; large approximate results are labelled and paginated. The last 200 history entries may form
a connected partial chain; relative labels avoid invented absolute version numbers.

Historical takeover freshly reads exact historical content, the current head and current write capabilities. It produces
only an in-memory draft based on that fresh head; explicit confirmed CAS save appends a successor without rewriting
history. Read-only users can compare. Access denial clears protected state; transient failure, cancelled discard and a
later competing save preserve existing drafts. Closing, changing selection/context or superseding an operation invalidates
pending responses. Identical takeover creates no dirty state or redundant save. This is block comparison, not tracked
changes or automatic merging.

- Implementation `3aa0069` passed full Ruff/format (665 files), Mypy (526 source files) and Pytest. Only the known
  Starlette/AnyIO warning remains. The focused 27 checks passed before the complete matrix.
- Full matrix: 100/100 in 249.923 seconds, zero skipped, unexpected or flaky; 88 browser cases plus 12 pure model cases.
  All previous 73 browser cases remain green. New coverage includes large/duplicate model inputs, exact comparison,
  fresh-head takeover, CAS conflicts, current ACL/feature removal, cancelled discard, failure retry, bounded real history,
  no-op takeover and late responses. Final desktop/tablet/mobile screenshots passed visual review.
- Documentation closeout `5a15195` passed all 11 targeted module/KB/roadmap contracts in 61.94 seconds, with only the
  known warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 10:52:56 UTC.
- No new schema, durable record or save endpoint. Item 252's migration 0083, verified backups, nonempty recovery and
  foundation/business proofs below remain retained, not newly rerun. No new engine, tenant or pilot admission.
- Primary changes: `app/suite/ui/office/office.js`, `office-comparison.mjs`, `office.css`, `index.html`;
  `e2e/work/tests/office-comparison-model.spec.mjs`, `office-versions.spec.mjs`, `office-versions-responsive.spec.mjs`;
  Docker bundle/module mounts and metadata-only roadmap capability evidence.

Ignored final evidence under `e2e/work/artifacts/roadmap-253/`:

- `results.json`: `sha256:42448945e2d326b56552c886d3603d69d1dcaf4d416ca4c727bf2e66e3ce8859`.
- Desktop: `sha256:0d28f346e40703ee5aae43f1b97f1d935af540d3757fbe2fc881c6a33037ca24`.
- Tablet: `sha256:7df8d3dd56d2f4b9d5ef1df12664a75ad7dbafc9e0d89ca5cd7f8670b8b9b53e`.
- Mobile: `sha256:33024e5aed9b0ac0b9c68787839cca0fdfe7856c7950cb8f61359e84685c5a3c`.

## Previous slice: Roadmap 252

Roadmap 252 / PLANS 113 delivers `/office`, linked from `/work`: native rich text, headings, lists, tables, templates,
outline, local text search, word count, focus mode, explicit version saves and historical reads. Desktop, tablet and
mobile controls were visually checked. Formatting returns focus synchronously for immediate mouse/keyboard input.
Conflicts and storage failures preserve drafts; context changes and close/reopen discard late responses. Drafts are
memory-only and do not promise crash recovery. DOCX interchange, comments, tracked changes, live collaboration,
spreadsheets, presentations and mail remain open product work; no claim of Office feature parity is made.

- Native content is bounded `collabio_document.v1` JSON. Server-side schema validation rejects unsupported nodes,
  remote resources, arbitrary attributes and excessive size/depth. CSP allows only local assets; no content enters logs.
- Five operations under `/v1/office/documents` enforce tenant/module/read/write gates, current typed object ACLs and
  server-derived ABAC. Read permission does not grant writing. Historical reads and retries recheck current access.
- Migration `0083_office_native_documents.sql` adds document heads and append-only versions with forced RLS, narrow
  column grants, atomic creator ACLs and source/receipt/head binding triggers. Canonical bytes use shared versioned S3.
  Tenant serialization precedes stale-head validation and PUT. PostgreSQL rollback does not roll back S3; post-PUT
  database failure can leave an orphan, covered by reconciliation tests. CAS and exact retry keys prevent lost updates
  and duplicate versions. Explicit human confirmation remains mandatory for each persisted save.
- ProseMirror/Tiptap 3.31.3 is bundled locally using a pinned image and locked dependencies. The runtime retains license
  notices and dependency inventory, without Node execution. Dependency audit reported no vulnerabilities.
- Full quality on `7bba74f`: Ruff and formatting across 665 files, Mypy across 526 source files, full Pytest green;
  only the known Starlette/AnyIO warning remains. The focused Office/API/PostgreSQL/restore/guard matrix passed 246 tests.
- Final browser proof on `5917bdf`: 73/73 in 160.237 seconds, zero skipped, unexpected or flaky cases. It preserves all
  60 Work/KB/CRM regressions and adds 13 Office workflow/policy/responsive cases. Earlier failures and corrections are
  retained in the operations log. The final focus regression checks focus during the control event, without sleeps.
- Documentation closeout `39980c5` passed all 11 targeted module/KB/roadmap contract tests in 59.58 seconds, with only
  the same warning. The disposable `test --no-deps` run started no auxiliary service; health remained ok at 10:19:15 UTC.
- Final nonempty recovery on `5917bdf`: 13 documents, 18 exact versions, five multi-version documents and 37 total source
  objects restored to separate PostgreSQL/S3 targets. Historical reads, canonical content/receipt hashes, current ACLs
  and foreign-tenant denial pass. Report `sha256:e61e7a26da539fa5a974a4faff62c31eb68502bd5c30f8f941df3effc2ae4cda`;
  synthetic backup `sha256:149e45637e20bafdaf93a76c7643b2ce77f7d1f23d2430888b77b951ea23c7ab`.

Ignored final evidence under `e2e/work/artifacts/roadmap-252/`:

- `results.json`: `sha256:ee074eca0c0897a8da5f232fc694d505b51ddb7413ccda4db4a8c9ee1e7e8792`.
- Desktop: `sha256:3201c529a199e88c6293672846fa66d24c7abc7bce40c7f15ca17a45f7c97c70`.
- Tablet: `sha256:23fb6d65e8d74e6d153f0ef828c23a059a01b1a167b419c434cfe085090d1ed9`.
- Mobile: `sha256:4321a07003b9729d069351d7f4f75f4b1b350482791d6f588e4317749325f144`.

Main database migration/recovery evidence:

- Pre-0083 backup `collabio-20260918T101259Z.dump`,
  `sha256:d0e243c70dcb6dbf6e3503331ee37ddc830059729edea44d67786f83e8b8314a`.
- Post-0083 backup `collabio-20260918T101306Z.dump`,
  `sha256:d82aadb4f0400282df0a4e6e036cf0fc3e60b53032eaf1810d51c1407f581f73`.
- Foundation-bound PostgreSQL restore `sha256:f659f89867d09e483c75ff046b3e0c7632590ad2d1603284c1a27294264e78f1`.
- Foundation `sha256:4fbba77852cc9e625aacc069d54495f69ddbd517f0e539fd49705c1ef47ae3fd`: 83 migrations, 91 tables,
  Office controls verified and three existing main source objects restored. Source seeding was explicitly disabled.
- Business release `sha256:a364a91a0044a62444fd69bfa95280cf01b7375389bd692e862948e32599b835` passed the existing
  three CRM/Tasks/Time slices without business writes or tenant activation. Native Office has the separate proof above.

Primary implementation: `office_document_schema.py`, `office_documents.py`, `office_document_repository.py`,
`office_api.py` under `app/suite/platform/`; `app/suite/ui/office/`; `frontend/office/`; migration 0083;
`tests/test_office_documents*.py`, `tests/office_recovery_proof.py`, `tests/test_office_recovery_proof.py` and Office E2E
cases. See `docs/modules/OFFICE_NATIVE_DOCUMENTS.md`, ADR-0079 and `docs/operations/WORK_E2E.md`.

## Previous slice: Roadmap 251

Roadmap item 251 and PLANS item 112 are complete. The existing account workspace is available in `/work` as an
account-detail dialog with associated contacts and activities. It reuses
`GET /v1/crm/accounts/{account_object_id}/workspace`; no new CRM mutation or schema is added.

- All three CRM feature gates and the existing pilot traffic-scope dependency remain mandatory. Account access is
  checked before child queries; every child requires its own current ACL and a relation to the selected account.
- Unreadable linked IDs remain redacted. JWT/OIDC ignores browser-provided grants. Contact names, email and phone
  remain personal data; the API's metadata-only contract does not make these fields anonymous.
- Successful responses and route-local errors are non-cacheable. Database failures return a constant 503 message;
  audit metadata contains IDs/counts, never CRM field values or note bodies. The UI does not display notes.
- Refresh clears old details before checking permissions again. Close/reopen and context changes invalidate late
  responses. Fields render as literal text; empty contacts and activities have independent messages.
- The guarded browser harness uses real PostgreSQL CRM rows and fresh database ACLs for the synthetic reader.
  Its narrowly scoped ACL administration and request-local database failure controls exist only in test code.
- Quality on `e966989` passed Ruff, formatting across 653 files, Mypy on 516 source files and full Pytest. Only the
  existing Starlette/AnyIO deprecation warning remains.
- All 60 browser cases passed in 130.014 seconds, with zero skipped, unexpected or flaky tests. The ten new CRM cases
  cover child filtering/redaction, literal fields, empty children, missing/forged/foreign permissions, closed pilot,
  account ACL revocation, disabled contacts feature, database failure/retry, late responses and desktop/mobile layout.
  Both viewport screenshots passed visual review; the previous 50 Work/KB cases remain green.
- After the operator approved publishing the described development evidence to the public repository, documentation
  commit `43149aa` was pushed and synchronized to dev001. All 11 targeted KB/module-contract/roadmap tests passed in
  19.88 seconds; health remained ok at 09:01:01 UTC. The disposable test used --no-deps and started no persistent
  service or auxiliary database. The final evidence-only update changes no runtime code or pilot state.

Current proof artifacts are ignored under `e2e/work/artifacts/roadmap-251/`:

- `results.json`: `sha256:64a245368f0e6a4e3665c761550a34e3477ed27ad47eccd56e16680087575455`.
- `work-crm-detail-complete.png`: `sha256:848fe140a83488d340c5f6e5c0f01a8aa58308c639da84d9448c672a3081e8f0`.
- `work-crm-detail-desktop-chromium.png`: `sha256:5587442989c9c890d8250349e20e13beeb92f2e554640c2bd3e6b51088a77a23`.
- `work-crm-detail-mobile-chromium.png`: `sha256:b1bf72c13d9928dd609f8f3f0ad27135c8c4e61603ef6469707e5f48cfd9c910`.

## Previous slice: Roadmap 250

Roadmap item 250 and PLANS item 111 are complete. Authorized ordinary readers can open published Knowledge Base
articles in `/work` with `knowledge_base.articles.read`, without an admin role or write feature.

- `GET /v1/kb/articles/{article_object_id}/content` returns the current article, exact source version, plain-text body,
  audit event ID and false RAG/search flags. Successful content responses and route-local errors use `no-store`.
- Article, current-version and source ACLs are checked before source access. JWT/OIDC ignores forged browser grants.
  Metadata preflight and loaded-byte validation bind exact identity, manifest/content hashes and security metadata.
- Only published article/lifecycle and WIKI/text/plain saved-version sources are supported, bounded to 400,000 bytes
  and 100,000 characters. Missing/denied, corrupt and unavailable sources return generic 404/400/503 responses.
- The read audit includes IDs and evidence hashes, never the article body. The editor shares the integrity helper;
  all existing write gates and approval stages remain intact.
- The dialog displays title, version and change date; literal markup stays plain text. Refresh clears old content
  before revalidation. Closing/reopening or changing context invalidates late responses. Desktop and mobile fit.
- The isolated browser proof uses a seeded ordinary reader, current PostgreSQL ACLs and the blocked API with write
  disabled. New-version access proves migration 0082 ACL inheritance without an extra version grant. Article/version
  revocation, S3 read failure/retry, foreign tenant, malicious markup and delayed-response cases pass.

No schema or durable business-data change was added. The migration 0082 backup/restore/release evidence below is
retained from item 249 and was not rerun for this read slice. No real tenant/runtime activation or pilot opening occurred.

## Previous slice: Roadmap 249 authoring foundation

Roadmap item 249 and PLANS item 110 are complete. The original Work browser slice (item 248/PLANS 109) remains intact.

Knowledge Base create/edit is available in `/work` for tenant-admins with an enabled module and write feature.
The narrow product endpoints construct trusted source metadata and expose the existing authoritative guard:

- `POST /v1/admin/kb/articles/prepare-write`
- `GET /v1/admin/kb/articles/{article_object_id}/edit-content`
- `POST /v1/admin/kb/articles/source-object-write-guard`

The existing dry-run, approve, refresh-preview, execution-skeleton and execute stages remain separate and hash-bound.
The UI carries their evidence between explicit preview, approval and final confirmation; users do not copy hashes.
Draft changes invalidate approval. Stale versions fail with conflict; failed writes preserve the draft and other
Work sources remain independent. Context generations discard old tenant responses and write capabilities.

Security and durability:

- Product metadata is server-created: internal classification, rp-standard, WIKI/text/plain, bounded title/body,
  fresh source/version identity, authenticated creator/owner and canonical security fields.
- Every stage rechecks module/feature, tenant-admin role and authoritative article/current-version/source access.
  Disabled compliance evidence reads remain available through their existing read gate.
- Migration `0082_knowledge_base_version_acls.sql` bootstraps the new article creator's ACL and copies active article
  ACLs to new versions in the same transaction. Trigger functions have pinned search_path and no PUBLIC/runtime
  execute grant; identity collisions and inappropriate preexisting objects fail closed.
- A tenant advisory transaction lock serializes all KB writes, including two first creates in an empty tenant.
  Approved restore state and expected version are checked under that lock before receipts/content writes.
- Source and restore evidence are verified inside the transaction and returned from its committed snapshot; a later
  write cannot cause a committed success to be reported as failed during post-commit evidence refresh.
- PostgreSQL metadata, approval lineage, receipt and exact S3 source versions remain bound. S3 is not part of the
  PostgreSQL transaction: an unexpected database failure after PUT can leave orphaned content, which the existing
  reconciliation/recovery controls detect. Never claim cross-system transactional rollback.
- Audits contain metadata/hashes, and storage/database errors return safe errors without logging article bodies.
- Restore verification binds both KB ACL triggers and their complete function definitions, owners, signatures,
  security mode, search_path, enablement and grants to migration 0082 and compares source/restore snapshots.

## Retained Knowledge Base validation and recovery evidence

On commit `d8d0386`, full quality passed: Ruff, formatting across 652 files, Mypy on 515 source files and full Pytest
to 100 percent. Only the known Starlette/AnyIO deprecation warning remains. This includes the PostgreSQL concurrency,
atomic ACL, API policy, storage-failure and restore-function tamper tests.
The new normal-reader API and isolated-harness policy tests are included. After documentation closeout, `6b1b82f`
passed all 11 targeted KB/module-contract/roadmap tests in 19.99 seconds; health remained ok at 08:19:34 UTC.
Item 249 implementation quality, documentation checks and 41-case browser evidence remain in the operations log.

Item 250 browser report: 50/50 passed in 120.480 seconds, zero skipped, unexpected or flaky tests. Desktop and mobile
reader screenshots were visually checked. Ignored local artifacts are retained under `e2e/work/artifacts/roadmap-250/`:

- `results.json`: `sha256:3dfb92a96f8cd61ec353c96e438ba94608476abc7321da223ea4f65f2b0f0a11`.
- `work-knowledge-reader-complete.png`: `sha256:98e0885f2a1370fa259fddf61dd518ae89dd672bf3f7e625716f913819d0db61`.
- `work-knowledge-reader-desktop-chromium.png`: `sha256:4e61218844b82d6f320a53bdbe9a49485de77273f4128ed0c78e10818dadd07a`.
- `work-knowledge-reader-mobile-chromium.png`: `sha256:9241af34e5fc7011298b80bbbf1544aca505d4828ff12529ec233873cb0c5ef6`.

Retained item 249 post-migration recovery and release proofs on dev001 (not newly executed for read-only items 250/251):

- Backup `collabio-20260918T070901Z.dump`:
  `sha256:9de68a2febdaa66c5f880ee1478d03bf343bea9004da67ee1b34966a875fb253`.
- PostgreSQL restore bound by the foundation gate:
  `sha256:a563ec0e557fe0c83e775c0a776e496b555b77f76015488fb0d8f3c854c283b3`.
- Foundation gate: `sha256:bf17fc1797e44b7a0a54ba6a0155313e7e5686a0537fac8ef22b4a6b0d3f5c06`.
- Business release gate: `sha256:8794acf1da3725851beaccba00adafed108166cf99966e24bec9dc3596fe2def`.

The foundation verified 82 migrations, 89 tables, tenant/IAM and trigger integrity, and exact restoration of three
existing source objects. The business gate remains the existing CRM/Tasks/Time three-slice gate; the KB product proof
is the separate API/PostgreSQL/browser matrix above. No new real-user pilot preflight/admission was created.

The isolated browser profile has tmpfs PostgreSQL and MinIO, internal networking, no host ports, tenant
`tenant-work-e2e` only, memory-only synthetic runtime activation and the normal pilot switch closed.
It ignores browser-supplied KB/CRM readable IDs and resolves current database ACLs on every KB/CRM request.
Its request-local storage failure injection is restricted to the exact synthetic tenant and execute or content-read route.
No failure injection exists in production API code.

The browser matrix is now 60 tests: the previous 41 cases, seven KB reader workflow/policy/race cases, two reader
responsive runs, eight CRM detail cases and two CRM responsive runs. The original 28 independent source-state cases,
closed-pilot route policy proof, real task/time workflow and guarded authoring remain intact. Artifacts and their
hashes are development evidence only.

Pre-0082 backup: `collabio-20260918T062951Z.dump`,
`sha256:d2724821f35c11cb9de0b023696593f70ce9dab69dbb458d003d4860c373b0e5`, checksum/catalog verified.
Migration 0082 was the only new migration applied; 82 migrations and 89 tables were verified after this slice.

Primary code and runbooks:

- `app/suite/platform/crm_workspace.py`, `crm_runtime.py`, `tests/test_crm_workspace_api.py`,
  `tests/work_e2e_crm.py` and `docs/modules/CRM_ACCOUNT_WORKSPACE_VERTICAL_SLICE.md`.
- `app/main.py`; `app/suite/platform/knowledge_base.py`; `knowledge_base_runtime.py`.
- `app/suite/persistence/migrations/0082_knowledge_base_version_acls.sql`.
- `app/suite/operations/postgres_restore_drill.py`.
- `app/suite/ui/work/index.html`, `work.js`, `work.css`.
- `tests/test_knowledge_base_read_api.py`, `test_knowledge_base_product_api.py`, `test_knowledge_base_acl_migration.py`,
  `test_knowledge_base_write_unit_of_work.py`, `test_knowledge_base_pg_repository.py` and `test_postgres_restore_drill.py`.
- `tests/work_e2e_server.py`, `tests/work_e2e_seed.py`, `tests/work_e2e_controls.py`,
  `app/suite/testing/work_e2e_guard.py`, `e2e/work/tests/`.
- `docs/modules/KNOWLEDGE_BASE_READER_VERTICAL_SLICE.md`, `KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md`,
  `KNOWLEDGE_BASE_WRITE_APPROVAL_LEDGER.md`,
  `KNOWLEDGE_BASE_SOURCE_RESTORE_EVIDENCE.md` and `MODULE_IMPLEMENTATION_CONTRACT.md`.
- `docs/operations/WORK_E2E.md`, `BACKUP_FAILOVER.md`, `REMOTE_DEVELOPMENT_HOST.md`.

## Existing product and platform status

- `/office` provides native document authoring with explicit saved-text suggestions and atomic acceptance, version-bound review discussions, contextual table editing, find/replace, immutable history, saved-version comparison and historical takeover
  into an unsaved local draft. Explicitly confirmed save appends a new version, under the closed tenant gates.
- `/roadmap` presents capabilities, including guarded native Office; KB shows authoring and ordinary reading, and CRM includes Work account
  details, with real API route paths.
- `/workspace` provides the module cockpit and controlled foundation workflows.
- `/work` provides Tasks/activity, Time, Tickets, KB and CRM with independent loading/error states and responsive UI.
- Tasks include durable lifecycle, reassignment and due-date changes with append-only evidence and shared mutation
  serialization. Time includes submission, maker-checker decisions, correction and resubmission.
- CRM has PostgreSQL/RLS accounts, contacts, activities and notes; Work exposes account details with authorized
  contacts and activities through the existing account workspace.
- ERP remains deliberately limited. LMS and later modules have contracts, not broad user-facing products.
- AI/RAG/voice control planes exist; productive provider execution remains closed.
- Office/Mail architecture, parser/CDR/preview and fidelity paths exist. LibreOffice evidence is ahead of
  Word/GenOffice; production Quick Edit, WOPI and a complete mail client remain open.
- Platform foundation includes signed OIDC/JWT, server-side principals/roles/groups/ACL/ABAC, Forced RLS, append-only
  audit/checkpoints/WORM evidence, classification/retention/Legal Hold/KMS, versioned S3 recovery, module lifecycle,
  isolated PG restore and combined foundation/business release gates.
- Supply-chain controls retain hashed locks, pinned images/actions, SBOM/provenance, license and vulnerability gates.

## Continuation point

Item 260 is complete. Preserve the 190-check matrix (155 Work/KB/CRM/Office browser cases and 35 comparison/search-model cases)
and the closed normal pilot boundary. Continue user-visible native Office editing/review workflows before CRM expansion;
version-bound comments, explicit saved-text suggestions, browser printing, independent saved-version reuse and paginated
title discovery are complete. A suitable next bounded workflow is loading older saved versions: the current history route
still returns at most 200 versions. Make older exact versions reachable for reading, comparison and takeover, preserving
fresh parent ACL checks, connected history validation, stable selection and all drafts across pages and concurrent saves.
This is a recommendation, not an implemented item. Continuous tracked changes and live collaboration remain open.
Preserve fresh current access checks, immutable history, atomic accepted versions, explicit confirmed CAS saves and
memory-only draft semantics. No subsequent roadmap item is declared implemented.
Continue DOCX interchange separately through the existing Quick Edit spike, synthetic corpus and source-blind/CDR validation.
Real Word/GenOffice fidelity results, calibrated thresholds and human review remain outstanding; current runtime
authorization and executable-image admission must precede an engine proof. Productive saves and WOPI remain separate
later release steps. The prohibition on Word/account/firewall interventions on the original workstation still applies.

CRM account onboarding in `/work` through `POST /v1/crm/account-onboardings` and subsequent CRM mutations are deferred
behind Office development. Preserve the completed CRM read workflow and its existing atomic backend contracts.
This priority update changes the implementation order; it does not activate any engine, tenant, pilot or indexing.

For any subsequent code change, run the appropriate focused tests and full quality remotely. For durable schema or
data changes, obtain a verified backup and isolated restore/release proofs before the controlled API rollout.
Restore loader runs with --no-deps against isolated postgres-restore only; foundation checks use
`SUITE_SOURCE_OBJECT_RUNTIME_SEED_DEMO=0` to avoid implicit seed writes. Prefer --no-deps where prerequisites have
already been explicitly started and checked, so Compose cannot silently migrate, bootstrap or recreate the API.
After recording hashes, remove only exact Work-E2E services per the runbook and stop auxiliary test/restore services.
Verify health, ports and other projects, then append the complete operation to the owning project's log.

## Open human/external lanes

- Import/activate `.github/rulesets/main.json` for main; enforcement remains pending in REPOSITORY_GOVERNANCE.md.
- Configure protected GitHub staging/production environments and reviewer/bypass policy.
- Supply accountable real-user purpose/principals/legal basis/privacy/workforce evidence and fresh four-eyes approval.
- Supply actual production topology, PITR, immutable offsite, fenced promotion and cross-site recovery evidence plus
  independent signatures before production continuity can pass.
- Separately authorize any Tickets tenant activation.
- Complete Word/GenOffice fidelity rows, calibration and human review; then separately gated Quick Edit/WOPI/mail work.

## New chat bootstrap

Read AGENTS.md and this document completely; inspect local/remote Git and dev001 rules/state before acting.
Continue the same branch from its verified current HEAD, preserve the user's untracked files and the closed pilot,
and follow the user's next product instruction without inferring permission to activate a tenant.
