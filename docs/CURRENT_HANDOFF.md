# Current Project Handoff

Updated: 2026-09-17

This is the canonical continuation document for a new Codex chat. It records the current repository, runtime,
security, evidence and roadmap state. Read it together with `AGENTS.md`; where they differ, `AGENTS.md` and the
current code are authoritative.

## Read First

Use this order before changing code:

1. `AGENTS.md` for non-negotiable tenant, AI, RAG, voice and remote-development rules.
2. This document for the current continuation point.
3. `PLANS.md` for the compact implementation sequence.
4. `docs/ROADMAP.md` for the canonical master roadmap and deferred work.
5. `docs/operations/DEV001_OPERATIONS_LOG.md` for append-only runtime evidence.
6. The focused runbook for the work being changed, especially `docs/operations/WORK_E2E.md`,
   `docs/operations/REMOTE_DEVELOPMENT_HOST.md` and `docs/operations/BACKUP_FAILOVER.md`.

Do not infer production readiness from a green development gate. The technical backend foundation and its isolated
development proofs are mature; accountable production evidence, real-user pilot approval and several external
governance controls remain deliberately open.

## Repository State

- Repository: `git@github.com:kirchherr/collabio.git`
- Workstation checkout: `C:\Users\tkirchherr\Documents\suite`
- Active branch: `kirchherr/kb-write-unit-of-work`
- Tracking branch: `origin/kirchherr/kb-write-unit-of-work`
- Implementation baseline before this handoff: `10cb0998ec18b9fe36d97735934da3367fca1737`
- The commit containing this document is the continuation baseline; verify it with `git rev-parse HEAD`.
- The branch was clean and synchronized with origin except for the user's untracked `erp_modul.md` and `review.md`.
  Never stage, rewrite or remove those two files unless the user explicitly requests it.
- Generated files under `e2e/work/artifacts/` are intentionally ignored and must not be committed.
- Pull-request state was not verified because GitHub CLI is not installed on the workstation. Do not assume a PR
  exists; inspect GitHub before discussing merge state.

Recent commits that completed the current slice:

- `b0ce4fb` - initial isolated Work browser E2E proof.
- `2756be9` - real closed-runtime route-policy proof.
- `26bd363` - E2E contract available inside the repository quality gate.
- `487d256` - roadmap and operational E2E closeout.
- `10cb099` - final roadmap/module-contract regression record.

## Runtime Host

All Docker work belongs on `dev001`, not on the operator workstation.

- SSH target: `extern@dev001`
- Dedicated SSH identity: `C:\Users\tkirchherr\.ssh\id_ed25519_collabio_dev001`
- Remote checkout: `/home/extern/collabio`
- Compose project: always pass `-p collabio`
- Shared host rules: read `/home/extern/AGENTS.md` before operating.
- Lock directory: `/home/extern/.codex-coordination`
- Source synchronization uses `git.lock`.
- Heavy builds/tests use `build.lock`.
- Compose lifecycle uses `docker.lock`.
- When both are needed, acquire `build.lock` before `docker.lock`.

Last verified state at 2026-09-17 16:07 UTC:

- Collabio: `running(3)` (`api`, `postgres`, `minio`).
- API health: `{"status":"ok"}`.
- Published Collabio ports: loopback-only `8000`, `5433`, `29000`, `29001`.
- Webcut: `running(7)`, untouched.
- Provider cluster: three `k3d-collabio-provider-server-*` nodes, untouched; API listener `127.0.0.1:26443`.
- Tricert was absent from the Compose inventory and was not changed.
- No `postgres-test`, restore or Work-E2E container was left running.
- No host port changed during the last slice.

Before every container start, stop, recreate or port change, inspect all three views:

```bash
docker compose ls --format json
docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'
ss -ltnH
```

Never use daemon-wide prune commands, broad container matching, plain `docker compose down`, or `down -v` on this
shared host. Never change Webcut, Tricert or provider resources while working on Collabio.

## Non-Negotiable Boundaries

- Tenant isolation, authoritative ACL checks, module gates and role checks remain server-side.
- No LLM receives unauthorized data. No vector result becomes context before authoritative ACL revalidation.
- No cloud AI provider is enabled without tenant policy. Provider adapters remain behind the Local LLM Gateway.
- Prompt/output bodies must not enter normal logs. AI output never directly triggers destructive actions.
- The productivity-pilot deployment switch stays `SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED=0` until a fresh,
  accountable evidence chain and required approvals exist.
- Synthetic test scope must never be promoted into pilot, continuity or production evidence.
- Do not fabricate named principals, legal basis, privacy/workforce approval, topology, PITR, offsite restore, HA
  promotion, cross-site recovery, independent review or signatures.
- Tickets & Incidents has an explicitly approved readiness gate only. Tenant activation was not authorized or run.
- The project does not use AWS. Preserve the self-hosted/provider-neutral design.
- There is no external legal review available. Keep legal claims conservative and do not claim certification.
- The original Windows workstation must not receive further Word-runner or account/firewall interventions. A separate
  disposable Windows test path was used for a manual DOCX check only.
- Fidelity private keys may exist only as Windows CurrentUser-DPAPI ciphertext under
  `C:\Users\tkirchherr\.collabio\signing`. They must never enter Docker, `dev001` or Git.
- Destructive, external or compliance-relevant actions require explicit human confirmation.

## Development Stance

- Work in coherent, user-visible product loops and take several connected steps when the risk is understood.
- Before adding a boundary, adapter or automation, ask: **must this be done now?** Defer work that neither protects
  the foundation nor closes the current product workflow.
- Do not return to long chains of preparation-only models or dry-run wrappers without immediate product or operating
  value.
- Prefer mature, maintained open-source components behind provider-neutral interfaces. Compare credible options and
  review the choice before adopting one; do not select the first available project.
- Every durable module or workflow must carry its migration, RLS, audit, classification, retention, Legal Hold,
  backup, restore, failover and decommission responsibilities with it. Backup/failover is a living suite-wide culture,
  not a later add-on.
- All future modules enter through the Platform Module System. Do not create module-specific shortcuts around tenant,
  rights, evidence or continuity controls.
- A complete Office suite and mail client must eventually attach to the same foundation. Preserve those extension
  points, but do not pull their full implementation ahead of the current roadmap item.
- Commit and push completed, verified slices. Keep unrelated user files and concurrent work intact.

## What Is Implemented

### Security and platform foundation

- Request-scoped tenant context, signed JWT/OIDC verification, server-side tenant membership, roles, groups, object
  ACL and ABAC resolution.
- PostgreSQL Forced RLS for durable tenant data and dedicated roles for application, worker, audit and authz admin.
- Append-only audit chains, checkpoints, WORM export evidence and metadata-only operational reports.
- Canonical data classification, retention, Legal Hold, KMS boundary, envelope encryption, rotation evidence and
  cryptographic-shredding guards.
- S3/MinIO-compatible source storage with versioning, Object Lock/Legal Hold profiles, exact-version restore and
  content reconciliation.
- Isolated PostgreSQL backup/restore, migration/catalog verification, row-count comparison, RLS/role/grant checks and
  combined foundation/business release gates.
- Platform Module System with tenant lifecycle, feature gates, migration evidence, backup/restore ownership and
  decommission controls.
- Supply-chain controls including hashed Python locks, digest-pinned images/actions, SBOM, provenance, license and
  vulnerability gates.

Latest durable recovery proof before the browser slice:

- 81 migrations and 89 tables.
- Backup: `sha256:060a533512494089917ad8adb0eb52926c906c9c7ac09ac65126ee4507c45857`.
- PostgreSQL restore: `sha256:ae43607cf60f1e775873cf928758c9a74dd41a0e9a572bb7925f9b95550317cb`.
- Foundation gate: `sha256:9df727336638f1ed9ce5cfb784f3147c7745b1cc2db3e20c8cb938a526bda8f5`.
- Business gate: `sha256:14a680363d1d2c8d6be29c8796f3bbb63577e8a7eaaf2deb68845ea0e8ea1300`.
- Non-executing pilot preflight:
  `sha256:c98754c0dcb114483bfcc7bab8404494b7b70cb576108e68cb321e502fef8789`.

### Product surfaces

- `/roadmap`: online foundation and roadmap overview.
- `/workspace`: module cockpit and controlled foundation actions.
- `/work`: daily-work UI over existing domain APIs without an authorization-bypassing aggregate endpoint.

The current `/work` surface provides:

- Tasks and activity reads plus task creation, lifecycle transitions, reassignment and due-date amendments.
- Time-entry creation, submission, maker-checker decisions, correction and resubmission.
- Ticket reads and non-destructive workflow controls where the module is available.
- Knowledge Base and CRM reads.
- Independent loading/error states so one blocked domain cannot bypass or collapse another domain boundary.
- Responsive desktop/mobile behavior.

### Module status

- Tasks & Activities: durable product slice complete, including append-only lifecycle and shared database mutation
  serialization.
- Time Tracking: durable product slice complete, including append-only approvals and versioned corrections.
- Tickets & Incidents: backend vertical slice and activation-readiness evidence exist; controlled tenant activation is
  still open and must not be executed without a new explicit instruction.
- Knowledge Base: read slice and the guarded admin write backend are implemented; create/edit is not yet exposed as a
  coherent `/work` user flow.
- CRM: accounts, contacts, activities and notes are backed by PostgreSQL/RLS; `/work` currently uses account reads.
- ERP: intentionally limited architecture/read slices; do not deepen ERP ahead of the current product roadmap.
- LMS and later module families: shared module/rights/data/continuity contracts exist, but no broad end-user product
  should be pulled ahead of the current product loop.
- AI/RAG/voice: secure control-plane and retrieval foundations exist; productive provider execution remains closed.
- Office/Mail: architecture, parser/CDR/preview and fidelity evidence paths exist. LibreOffice proof is further along
  than Word/GenOffice, but production Quick Edit, WOPI collaboration and a complete mail client remain open. Do not
  represent the current state as full Office compatibility.

## Last Completed Slice: Work Browser Proof

Roadmap item 248 and `PLANS.md` item 109 are complete. The isolated profile uses only tenant `tenant-work-e2e`,
tmpfs-backed PostgreSQL, internal networking and no host ports. The normal pilot switch remains closed. A separate
blocked API process uses only in-memory synthetic scope/start fixtures to reach the real production route policy; it
does not create durable pilot evidence.

Final Playwright result:

- 32/32 passed in 22.859 seconds.
- 28 source-state cases: seven sources, each ready/empty/blocked/unavailable.
- One production route-policy case.
- One real task-reassignment plus time-correction/resubmission workflow against PostgreSQL.
- Separate desktop and mobile responsive cases.
- Zero skipped, unexpected or flaky cases.

Expected blocked-path results were proven:

- Pilot-managed Tasks/Time routes: HTTP 423.
- CRM outside the authorized pilot route scope: HTTP 403.
- Inactive Tickets module: HTTP 404.
- Non-pilot Knowledge Base read: HTTP 200.

Evidence in ignored `e2e/work/artifacts/`:

- `results.json`: `sha256:8caf65bc8efe4f690af0d4652ce5452fd16ee5e4c79d1b42db367da48c233946`.
- `work-desktop-chromium.png`:
  `sha256:b87451895e637438c5aeb2609e3dc319dc16805dabee71f1e3ce99e8dc1b5916`.
- `work-mobile-chromium.png`:
  `sha256:2a25ba5232a3e72d8b5d13194e9af8670b82cc4757f2eea8460a724d8789b067`.
- `work-workflows-complete.png`:
  `sha256:664cb8e2c1792e5be2ed669af3b2682bd6c4f2ae30f66890c787ad066544583a`.

Repository quality at this point:

- Ruff passed.
- Ruff format passed for 646 files.
- Mypy passed for 511 source files.
- Full Pytest completed to 100 percent with only the known Starlette/AnyIO deprecation warning.
- Seven targeted roadmap, audit-verification and module-contract regressions passed after documentation closeout.

Primary files:

- `docs/operations/WORK_E2E.md`
- `docker-compose.yml` services `work-e2e-*`
- `app/suite/testing/work_e2e_guard.py`
- `tests/work_e2e_server.py`
- `tests/work_e2e_seed.py`
- `tests/test_work_e2e_harness.py`
- `e2e/work/tests/*.spec.mjs`

## Exact Next Product Step

Roadmap item 249 is the active engineering target:

> Make the existing guarded Knowledge Base create/edit contracts usable in `/work`, then prove create, edit,
> conflict, blocked and partial-failure behavior in the isolated browser harness. Reuse the existing approval,
> PostgreSQL/S3 unit-of-work, audit and restore boundaries. Keep RAG/indexing closed.

Do not start a new infrastructure or preparation series. Close this one product loop end to end.

### Existing backend chain

All current mutation endpoints require `tenant-admin` and the Knowledge Base compliance module gate:

1. `POST /v1/admin/kb/articles/write-dry-run`
2. `POST /v1/admin/kb/articles/write-approvals/approve`
3. `POST /v1/admin/kb/articles/write-approvals/refresh-preview`
4. `POST /v1/admin/kb/articles/write-approvals/execution-skeleton`
5. `POST /v1/admin/kb/articles/write-approvals/execute`

The domain/runtime chain already provides approval evidence, expected-version checks, source metadata, explicit
confirmation, append-only receipts, article/source/evidence updates, PostgreSQL transaction boundaries,
recovery/deployment gates and `rag_indexing_allowed=false` plus `search_indexing_allowed=false`.

Important code anchors:

- API routes: `app/main.py`, around `dry_run_knowledge_base_article_write` and
  `execute_knowledge_base_article_write`.
- Domain models and service: `app/suite/platform/knowledge_base.py`.
- Production runtime resolver: `app/suite/platform/knowledge_base_runtime.py`.
- PostgreSQL/S3 unit-of-work tests: `tests/test_knowledge_base_write_unit_of_work.py`.
- Current API chain tests: `tests/test_api.py`, starting at
  `test_knowledge_base_write_dry_run_endpoint_requires_admin_and_does_not_persist`.
- Work UI: `app/suite/ui/work/index.html`, `work.js`, `work.css`.
- Browser harness: `e2e/work/tests/` and `tests/work_e2e_server.py`.

### Concrete gap found during handoff

`KnowledgeBaseArticleService.evaluate_source_object_write_guard(...)` exists, but there is no tenant-safe API route
that returns this authoritative decision. Current API tests construct `KnowledgeBaseSourceObjectWriteGuardDecision`
inside Python and send it to the execution endpoints. A browser must not reproduce that hash-bound canonical guard
logic.

The browser also must not independently reimplement Python canonical manifest/hash construction or accept arbitrary
security metadata from a form. Before wiring the UI, add the narrow server-side product boundary needed to create and
validate the proposed `SourceObjectRecord` and return the authoritative guard decision. Reuse the existing service and
write chain; do not create an aggregate endpoint that skips approval stages.

Other constraints for the next slice:

- `knowledge_base.articles.write` defaults to false. Enable it only for the isolated synthetic E2E tenant while
  testing; do not activate a real tenant.
- The current write APIs are tenant-admin operations. The first UI should expose them only to an authenticated
  tenant-admin unless a deliberate rights-model change is designed and tested.
- Do not display approval hashes as work the user has to manually copy. The UI may carry them between explicit steps
  and show a concise evidence summary.
- Create and edit must use optimistic version checks. A stale edit must fail visibly without overwriting content.
- The final write needs an explicit confirmation action and must remain auditable.
- RAG and keyword indexing remain off after the write. Deletion propagation and citation/version guarantees must be
  closed before indexing is enabled.
- Partial KB failure must not break Tasks, Time, Tickets or CRM on `/work`.
- Prefer the existing PostgreSQL/S3 runtime path. If the isolated E2E profile needs an object-store dependency, add it
  only as the concrete requirement of this workflow, keep it internal/ephemeral and publish no host port.

### Acceptance criteria for item 249

- Tenant-admin can create an internal, `rp-standard` Knowledge Base article from `/work` through all existing gates.
- Tenant-admin can edit an authorized article using the exact current version.
- Stale version, disabled feature/module, unauthorized role, invalid metadata and failed storage/UoW paths fail closed.
- No prompt, output or article body appears in ordinary logs or metadata-only audit events.
- Source content, metadata, approval lineage, receipt and restore evidence remain bound after commit.
- RAG/search indexing flags remain false.
- Focused unit/API/PostgreSQL tests pass.
- Work E2E covers create, edit, conflict, blocked and responsive behavior with no external requests or console errors.
- Full quality passes on `dev001`.
- If durable schema or runtime data changes, run backup, isolated restore and release gates before rollout.
- Update `PLANS.md`, `docs/ROADMAP.md` and the append-only operations log only after the proof is green.

## Standard Remote Workflow

Synchronize only after committing and pushing from the workstation:

```bash
flock /home/extern/.codex-coordination/git.lock \
  git -C /home/extern/collabio pull --ff-only
```

Full quality, after the required host preflight:

```bash
cd /home/extern/collabio
flock /home/extern/.codex-coordination/build.lock \
  flock /home/extern/.codex-coordination/docker.lock \
  docker compose -p collabio run --rm --build quality
```

Work browser proof:

```bash
cd /home/extern/collabio
flock -w 900 /home/extern/.codex-coordination/build.lock \
  flock -w 900 /home/extern/.codex-coordination/docker.lock \
  sh -c 'docker compose -p collabio --profile work-e2e config --quiet && \
    docker compose -p collabio --profile work-e2e run --rm --build work-e2e'
```

After preserving result hashes, repeat the preflight and remove only the exact Work-E2E services as documented in
`docs/operations/WORK_E2E.md`. Stop `postgres-test` separately if quality started it. Verify API health and the final
Compose/container/port state. Append the operation to `docs/operations/DEV001_OPERATIONS_LOG.md`.

## Open Human or External Lanes

These are real open controls, not coding gaps to fill with placeholders:

- Import and activate `.github/rulesets/main.json` for `main`; repository enforcement is still documented as pending
  in `docs/REPOSITORY_GOVERNANCE.md`.
- Configure protected GitHub `staging` and `production` environments and their reviewer/bypass policy.
- Supply accountable real-user pilot principals, purpose, legal basis, privacy/workforce evidence and fresh four-eyes
  approvals before any real pilot.
- Supply real production topology, PITR, immutable offsite, fenced promotion and cross-site recovery evidence plus
  required independent signatures before production continuity can pass.
- Execute Tickets & Incidents controlled activation only after a separate explicit authorization.
- Finish Word and GenOffice fidelity rows, threshold calibration and human review before claiming Office
  compatibility.
- Complete Quick Edit and later WOPI/mail-client product work behind their independent gates.

## New Chat Bootstrap

The first request in a new chat can be:

```text
Read AGENTS.md and docs/CURRENT_HANDOFF.md completely. Continue the existing
kirchherr/kb-write-unit-of-work branch at roadmap item 249. Keep the workstation as chat/control plane, run all
Docker work on dev001 under its coordination rules, preserve the closed pilot runtime, and implement the guarded
Knowledge Base create/edit product loop in /work end to end. Commit and push completed work.
```

The new chat should first verify local and remote Git state, read `/home/extern/AGENTS.md`, inspect Compose projects,
containers and ports, and then review the listed KB code anchors. It should continue from this state, not rebuild the
project plan from scratch.
