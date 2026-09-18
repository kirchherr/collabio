# Current Project Handoff

Updated: 2026-09-18

This is the canonical continuation document. Read `AGENTS.md` fully first, then this document, `PLANS.md`,
`docs/ROADMAP.md`, the append-only `docs/operations/DEV001_OPERATIONS_LOG.md`, and the relevant runbooks.
AGENTS.md and current code are authoritative. Green development evidence is not production or real-user approval.

## Repository and host

- Repository: `git@github.com:kirchherr/collabio.git`.
- Workstation: `C:\Users\tkirchherr\Documents\suite`; branch `kirchherr/kb-write-unit-of-work` tracks origin.
- Validated implementation: `d8d0386`; the commit containing this handoff is the continuation
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

Final host verification at 2026-09-18 08:17:16 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated. Webcut remains `running(7)` and all three
provider nodes remain unchanged (127.0.0.1:26443). Tricert was absent. Work-E2E containers were removed; postgres-test,
postgres-restore and minio-restore are stopped. Live checks confirmed the new normal KB content route and existing
authoring routes, the reader in `/work`, the disabled KB write feature in tenant-demo and the closed pilot switch.
Bounded health retries covered startup connection resets; health and the cold OpenAPI check then passed.

## Non-negotiable boundaries

- Tenant isolation, authoritative ACL, ABAC, role and module/feature gates stay server-side.
- The normal switch stays `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0`. Synthetic tests never authorize real users.
- `knowledge_base.articles.write` defaults false. Only the isolated synthetic E2E tenant enabled it for this slice.
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
before adoption. Office and Mail retain their extension points; do not pull a full suite ahead of the agreed roadmap.
Commit and push verified slices; synchronize dev001 only with git pull --ff-only under git.lock.

## Last completed slice: Roadmap 250

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

## Validation and recovery evidence

On commit `d8d0386`, full quality passed: Ruff, formatting across 652 files, Mypy on 515 source files and full Pytest
to 100 percent. Only the known Starlette/AnyIO deprecation warning remains. This includes the PostgreSQL concurrency,
atomic ACL, API policy, storage-failure and restore-function tamper tests.
The new normal-reader API and isolated-harness policy tests are included. Prior item 249 documentation checks passed
on `1cf06d4`; its implementation quality and 41-case browser evidence remain in the operations log.

Final browser report: 50/50 passed in 120.480 seconds, zero skipped, unexpected or flaky tests. Desktop and mobile
reader screenshots were visually checked. Ignored local artifacts are retained under `e2e/work/artifacts/roadmap-250/`:

- `results.json`: `sha256:3dfb92a96f8cd61ec353c96e438ba94608476abc7321da223ea4f65f2b0f0a11`.
- `work-knowledge-reader-complete.png`: `sha256:98e0885f2a1370fa259fddf61dd518ae89dd672bf3f7e625716f913819d0db61`.
- `work-knowledge-reader-desktop-chromium.png`: `sha256:4e61218844b82d6f320a53bdbe9a49485de77273f4128ed0c78e10818dadd07a`.
- `work-knowledge-reader-mobile-chromium.png`: `sha256:9241af34e5fc7011298b80bbbf1544aca505d4828ff12529ec233873cb0c5ef6`.

Retained item 249 post-migration recovery and release proofs on dev001 (not newly executed for item 250):

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
It ignores browser-supplied KB readable IDs and resolves current database ACLs on every KB request.
Its request-local storage failure injection is restricted to the exact synthetic tenant and execute or content-read route.
No failure injection exists in production API code.

The browser matrix is 50 tests: the previous 41 cases plus seven reader workflow/policy/race cases and two reader
responsive runs. The original 28 independent source-state cases, closed-pilot route policy proof, real task/time
workflow and guarded authoring remain intact. Artifacts and their hashes are development evidence only.

Pre-0082 backup: `collabio-20260918T062951Z.dump`,
`sha256:d2724821f35c11cb9de0b023696593f70ce9dab69dbb458d003d4860c373b0e5`, checksum/catalog verified.
Migration 0082 was the only new migration applied; 82 migrations and 89 tables were verified after this slice.

Primary code and runbooks:

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

- `/roadmap` presents capabilities; KB shows guarded authoring and ordinary reading with real API route paths.
- `/workspace` provides the module cockpit and controlled foundation workflows.
- `/work` provides Tasks/activity, Time, Tickets, KB and CRM with independent loading/error states and responsive UI.
- Tasks include durable lifecycle, reassignment and due-date changes with append-only evidence and shared mutation
  serialization. Time includes submission, maker-checker decisions, correction and resubmission.
- CRM has PostgreSQL/RLS accounts, contacts, activities and notes; Work currently uses account reads.
- ERP remains deliberately limited. LMS and later modules have contracts, not broad user-facing products.
- AI/RAG/voice control planes exist; productive provider execution remains closed.
- Office/Mail architecture, parser/CDR/preview and fidelity paths exist. LibreOffice evidence is ahead of
  Word/GenOffice; production Quick Edit, WOPI and a complete mail client remain open.
- Platform foundation includes signed OIDC/JWT, server-side principals/roles/groups/ACL/ABAC, Forced RLS, append-only
  audit/checkpoints/WORM evidence, classification/retention/Legal Hold/KMS, versioned S3 recovery, module lifecycle,
  isolated PG restore and combined foundation/business release gates.
- Supply-chain controls retain hashed locks, pinned images/actions, SBOM/provenance, license and vulnerability gates.

## Continuation point

Item 250 is complete. No item 251 implementation has been authorized. The recommended next coherent product loop is
CRM account detail with associated contacts and activities in `/work`, using the existing backend and platform gates.
Treat that as a recommendation until the user selects it. No CRM expansion, new tenant activation, pilot opening or
indexing is part of item 250.

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
