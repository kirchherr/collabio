# Current Project Handoff

Updated: 2026-09-18

This is the canonical continuation document. Read `AGENTS.md` fully first, then this document, `PLANS.md`,
`docs/ROADMAP.md`, the append-only `docs/operations/DEV001_OPERATIONS_LOG.md`, and the relevant runbooks.
AGENTS.md and current code are authoritative. Green development evidence is not production or real-user approval.

## Repository and host

- Repository: `git@github.com:kirchherr/collabio.git`.
- Workstation: `C:\Users\tkirchherr\Documents\suite`; branch `kirchherr/kb-write-unit-of-work` tracks origin.
- Validated implementation: `383c001`; the commit containing this handoff is the continuation
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

Final host verification at 2026-09-18 07:22:34 UTC: Collabio `running(3)` (api, postgres, minio), health `ok`,
loopback-only ports 8000/5433/29000/29001. Only the API was rebuilt/recreated. Webcut remains `running(7)` and all three
provider nodes remain unchanged (127.0.0.1:26443). Tricert was absent. Work-E2E containers were removed; postgres-test,
postgres-restore and minio-restore are stopped. Live checks confirmed all new KB routes, `/work`, the disabled KB write
feature in tenant-demo and the closed pilot switch. The initial post-recreate health read hit a connection reset and
the first cold OpenAPI read exceeded 15 seconds; the later read check passed without a code change.

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

## Last completed slice: Roadmap 249

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

On commit `383c001`, full quality passed: Ruff, formatting across 649 files, Mypy on 513 source files and full Pytest
to 100 percent. Only the known Starlette/AnyIO deprecation warning remains. This includes the PostgreSQL concurrency,
atomic ACL, API policy, storage-failure and restore-function tamper tests.
After documentation closeout, commit `1cf06d4` also passed all 11 targeted KB/module-contract/roadmap tests.

Final browser report: 41/41 passed in 51.539 seconds, zero skipped, unexpected or flaky tests. Desktop and mobile
screenshots were visually checked. Ignored artifact hashes:

- `results.json`: `sha256:275f152a1979d7c1de44bf7d435e0a86b7414bd580c982837f93417fd99c2be7`.
- `work-knowledge-complete.png`: `sha256:459e2cba4811ba28538a44a464a8ff5b412e88d76b1c40c342652473a114221e`.
- `work-knowledge-desktop-chromium.png`: `sha256:a77147f5df7dad251f62ea8126d5f0c4dd6e4998bb65cc0025163711e9abd08d`.
- `work-knowledge-mobile-chromium.png`: `sha256:9345dd60148bed75145c40189fb902e7424abd73404a51dc40f52a3ee8a3b248`.

Post-migration recovery and release proofs on dev001:

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
Its request-local storage failure injection is restricted to the exact synthetic tenant and execute route.
No failure injection exists in production API code.

The expected browser matrix is 41 tests: the previous 32 cases, six KB workflow cases, two KB responsive cases and
one delayed-response/context-switch regression. The original 28 independent source-state cases, closed-pilot route
policy proof and real task/time workflow remain intact. Artifacts and their hashes are development evidence only.

Pre-0082 backup: `collabio-20260918T062951Z.dump`,
`sha256:d2724821f35c11cb9de0b023696593f70ce9dab69dbb458d003d4860c373b0e5`, checksum/catalog verified.
Migration 0082 was the only new migration applied; 82 migrations and 89 tables were verified after this slice.

Primary code and runbooks:

- `app/main.py`; `app/suite/platform/knowledge_base.py`; `knowledge_base_runtime.py`.
- `app/suite/persistence/migrations/0082_knowledge_base_version_acls.sql`.
- `app/suite/operations/postgres_restore_drill.py`.
- `app/suite/ui/work/index.html`, `work.js`, `work.css`.
- `tests/test_knowledge_base_product_api.py`, `test_knowledge_base_acl_migration.py`,
  `test_knowledge_base_write_unit_of_work.py`, `test_knowledge_base_pg_repository.py` and `test_postgres_restore_drill.py`.
- `tests/work_e2e_server.py`, `tests/work_e2e_seed.py`, `app/suite/testing/work_e2e_guard.py`, `e2e/work/tests/`.
- `docs/modules/KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md`, `KNOWLEDGE_BASE_WRITE_APPROVAL_LEDGER.md`,
  `KNOWLEDGE_BASE_SOURCE_RESTORE_EVIDENCE.md` and `MODULE_IMPLEMENTATION_CONTRACT.md`.
- `docs/operations/WORK_E2E.md`, `BACKUP_FAILOVER.md`, `REMOTE_DEVELOPMENT_HOST.md`.

## Existing product and platform status

- `/roadmap` presents capabilities; KB now shows guarded product authoring with real API route paths.
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

Item 249 is complete. No item 250 or new tenant activation has been authorized.
Review the current roadmap with the user's next product instruction;
do not repeat this KB implementation or launch another preparation-only series.

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
