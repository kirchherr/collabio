# ADR-0085: Native Office saved-version history pagination

Date: 2026-09-21
Status: accepted; development validation and controlled dev001 rollout complete
Scope: Roadmap 261 / PLANS 122, extending ADR-0079, ADR-0083 and ADR-0084

## Context

The existing history endpoint returns at most 200 saved versions. Older exact versions remain stored and authorized
but cannot be selected through the history or comparison controls. Sorting by creation time cannot reliably represent
the predecessor chain when versions share timestamps. Loading another page must preserve selections and local drafts.

## Decision

Extend the existing GET versions endpoint with page_size (1 through 200, default 200) and an optional bounded opaque
cursor. Preserve the existing fields and add page_size, has_more, next_cursor, history_head_version_id and
current_version_id. The Office UI requests 50 entries. Return saved versions newest first by following previous_version_id,
with a bounded predecessor traversal and lookahead. Validate missing links and repeated IDs within each page; the client
also validates the connection and uniqueness across all loaded pages. Existing append-only storage guarantees lineage.

The first read fixes history_head_version_id for this navigation. Later saves may change current_version_id without
inserting entries into that loaded chain; an explicit refresh begins from the new head. This is a stable immutable
lineage, not a frozen permission snapshot. Recheck current parent role, ABAC and typed ACL access for every page and
before exact content reads. Pagination reads metadata only and does not retrieve source bytes.

Authenticate history cursors with a distinct domain and bind tenant, actor, roles, document and page size, plus the fixed
history head and next predecessor. Reuse the current per-service secret; restart invalidates cursors and requires a
history refresh. The deployment has one API worker; no shared multi-worker signing-key arrangement is introduced.
A cursor never authorizes access. Invalid requests return bounded generic errors, without cursor values in audit or
ordinary Uvicorn access records. Keep the existing non-cacheable responses and security headers.

History and comparison receive explicit older-version, refresh, retry and loaded-count controls. Appending preserves
selected exact versions, rendered comparisons, editor content and document/review/suggestion drafts. Newer saved heads
are identified without silently replacing content. Successful comparison refresh may retain its two previous exact
selections as separately labelled choices outside the loaded window; these entries never enter chain validation.
Each comparison or takeover still performs fresh exact source reads and existing validation/confirmation checks.
Opening history pauses an existing discussion or suggestion composer without discarding its draft; returning resumes
that same version-bound state. Document/context changes and explicit close keep their existing discard confirmation.

Transient failures preserve already loaded metadata, selections and drafts; retries use the same page cursor. Invalid
cursors offer a fresh history read. Actual access denial clears protected state. Close, context change and superseding
requests invalidate late responses. No schema, durable format, write endpoint, dependency, index or engine is added.
Hiding history, switching inspector tabs or entering focus mode also cancels its pending read and restores the last
confirmed loaded-count status. A canceled request cannot clear or repopulate a subsequently opened workspace.

## Validation and boundaries

Prove beyond-200 genuine PostgreSQL/S3 history, connected complete pagination with equal timestamps, concurrent saves,
context-bound cursor rejection, current authorization, literal content, selected-source comparison and local takeover.
Exercise draft/selection preservation, transport failures and exact retries, stale responses and responsive controls.
Preserve all 190 existing browser/model cases and run focused tests plus full quality on dev001. Existing Roadmap 257
recovery evidence is retained; this metadata/UI extension introduces no main-database migration or new recovery drill.
Ordinary tenant, pilot, indexing, cloud provider and DOCX engine admission remain closed.

Focused backend verification on `0bdd522` passed 249 Python/API/PostgreSQL checks in 40.58 seconds. On `46a83b4`,
all 23 focused browser checks passed in 94.693441 seconds: ten new cases and thirteen existing version-workflow cases,
with zero skipped, unexpected or flaky results. Root and independent desktop/tablet/mobile visual review passed;
actual Uvicorn logs verified redaction across 63 list and 110 history access records. Focused report:
`sha256:ef46cb8c44612e6dcb6261f784d42a5dbfbeaca1e1bf9604e3f6869bf5e464b3`.
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
Cleanup completed healthy at 14:27:43 UTC, with Collabio running(3) on unchanged loopback ports. The six remaining
exact E2E containers were removed, the disposable runner was already absent, and test/restore services were stopped.
Main PostgreSQL and MinIO, Webcut and provider services were unchanged; Tricert was absent. Roadmap 261 development
is complete. No main-database migration, new recovery drill, ordinary-tenant write, indexing, cloud provider or engine
activation occurred. Roadmap 257 recovery evidence remains retained; no ordinary-tenant or production admission follows.
