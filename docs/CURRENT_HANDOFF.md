# Current Project Handoff

Updated: 2026-09-18

This is the canonical continuation document. Read `AGENTS.md` fully first, then this document, `PLANS.md`,
`docs/ROADMAP.md`, the append-only `docs/operations/DEV001_OPERATIONS_LOG.md`, and the relevant runbooks.
AGENTS.md and current code are authoritative. Green development evidence is not production or real-user approval.

## Repository and host

- Repository: `git@github.com:kirchherr/collabio.git`.
- Workstation: `C:\Users\tkirchherr\Documents\suite`; branch `kirchherr/kb-write-unit-of-work` tracks origin.
- Validated implementation: `e3cf88c` (full Python quality and all 142 browser/model checks); the commit containing this handoff is the continuation
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

Final item 255 host verification at 2026-09-18 12:10:34 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
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
- Native Office uses `office_documents.documents.read` and `.write`, both closed by default. Migration 0083 does not
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

## Last completed slice: Roadmap 255

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

- `/office` provides native document authoring with contextual table editing, find/replace, immutable history, saved-version comparison and historical takeover
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

Item 255 is complete. Preserve the 142-check matrix (107 Work/KB/CRM/Office browser cases and 35 comparison/search-model cases)
and the closed normal pilot boundary. Continue user-visible native Office editing/review workflows before CRM expansion;
comments, tracked changes and live collaboration remain open. Preserve fresh current access checks, immutable history,
explicit confirmed CAS saves and memory-only draft semantics. No subsequent roadmap item is declared implemented.
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
