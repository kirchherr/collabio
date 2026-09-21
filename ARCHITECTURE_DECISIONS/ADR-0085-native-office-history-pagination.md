# ADR-0085: Native Office saved-version history pagination

Date: 2026-09-21
Status: accepted design; development validation pending
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

Transient failures preserve already loaded metadata, selections and drafts; retries use the same page cursor. Invalid
cursors offer a fresh history read. Actual access denial clears protected state. Close, context change and superseding
requests invalidate late responses. No schema, durable format, write endpoint, dependency, index or engine is added.

## Validation and boundaries

Prove beyond-200 genuine PostgreSQL/S3 history, connected complete pagination with equal timestamps, concurrent saves,
context-bound cursor rejection, current authorization, literal content, selected-source comparison and local takeover.
Exercise draft/selection preservation, transport failures and exact retries, stale responses and responsive controls.
Preserve all 190 existing browser/model cases and run focused tests plus full quality on dev001. Existing Roadmap 257
recovery evidence is retained; this metadata/UI extension introduces no main-database migration or new recovery drill.
Ordinary tenant, pilot, indexing, cloud provider and DOCX engine admission remain closed.
