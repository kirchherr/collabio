# ADR-0080: Native Office version-bound reviews

Date: 2026-09-18
Status: accepted; implementation, full quality, browser, recovery and dev001 rollout verified
Scope: Roadmap 256 / PLANS 117, extending ADR-0079

## Context

Native Office has immutable saved document versions and a memory-only editor draft. A review discussion needs its
own durable history without manufacturing document versions for each comment or silently moving a quotation when
the text changes. Existing tenant, module, document ACL, retention and recovery boundaries still apply.

## Decision

Use `office.review_threads` for discussion heads and append-only `office.review_events` for creation, replies,
resolution and reopening. Migration 0084 adds these tables to the installed Office package without provisioning or
enabling any tenant. Every event has an immutable COMMENT SourceObject and a source-write receipt in the existing
PostgreSQL/versioned-S3 storage contract. The parent is the native document; thread and event IDs identify exact bytes.
Bodies and quotations live in those sources, never ordinary logs or audit metadata.

New discussions target only the current saved document version. A null anchor denotes that entire version; a text
anchor denotes a bounded UTF-16 range in one inline text run. The server validates the exact stored document and
derives the quotation. Formatting boundaries may be crossed, paragraph, hard-break and cell boundaries may not.
An old discussion remains attached to its original version. It can still be discussed under current parent rights;
there is no automatic reanchoring or permission inherited from old ACL snapshots.
The editor requires an unchanged current saved version for a new discussion, including a whole-version comment.
Comment/reply bodies are limited to 4,000 Unicode code points and selected quotations to 2,000. Text across differently
formatted nodes is permitted; surrogate-splitting or structurally ambiguous ranges are rejected before persistence.

Reads use current document read access. All mutations use the existing Office write feature, fresh typed parent
write/admin ACL, explicit human confirmation and the same tenant advisory lock as document saves. Thread revisions
provide a separate compare-and-swap boundary. Exact actor-bound retries are checked after fresh authorization and
before stale-revision rejection; a changed payload with a reused mutation reference conflicts. No new role or
independent comment ACL is introduced.
Read-only users may inspect discussions. API capabilities distinguish creating a thread from replying or changing its
status, including when historical document text is read-only. Resolving and reopening append events; a resolved thread
must be reopened before another reply. These operations never alter the original document or its version history.

Four routes extend the existing document API: list/create under
`/v1/office/documents/{object_id}/review-threads`, exact thread detail under `/{thread_id}`, and event creation under
`/{thread_id}/events`. Lists can filter by exact anchor version and use a thread cursor; event pages use the last
revision. Both default to 20 entries and permit at most 50. Responses expose current capabilities and use `no-store`;
validation and storage errors do not echo submitted text. RAG and search-indexing flags remain false.

The UI provides a Comments inspector, a memory-only composer and an explicit review-action confirmation. It renders
literal text, paginates discussions and events, preserves drafts on temporary failures and ignores stale responses
after context changes. Source-position highlights appear only on the exact unchanged saved version. Discussion
state is separate from text undo and document save state.
There are three inspector tabs, with a wider comments panel on desktop and a closable overlay on compact screens.
The panel shows only threads for the opened saved version. Earlier discussions are reached by explicitly opening that
version, not by placing their highlights in current or dirty text. Text-location navigation freshly verifies the saved
content and exact quotation. Pagination is explicit and does not silently truncate contributions.

Comment draft changes invalidate a prepared command; retries after an uncertain response retain the exact original
command and actor-bound mutation reference. A conflict preserves the draft and requires fresh state before a new
attempt. Once a write succeeds, a failed refresh is a read failure rather than grounds for another mutation. Document
save, version/context switches and closing draft comments account for their possible loss through the existing discard
decision. Closing or superseding a view invalidates its pending reads, and access denial clears protected state.
Neither draft text, quotation nor retry payload is stored in browser localStorage. There is no automatic submission.

## Consequences and verification

Discussion heads, events, composite tenant/version/source/receipt constraints, forced RLS, append-only restrictions,
column grants and complete authored trigger function bodies join the existing restore gate. A nonempty isolated
PostgreSQL/S3 restore must prove all four operations, exact event bytes, history, receipts and current ACL behavior
before the controlled API rollout. A database rollback after S3 PUT can leave a detectable orphan; there is no claim
of distributed rollback.
The completed migration 0083 recovery evidence cannot stand in for verification of the new migration 0084 tables and
events. Review restore evidence must cover create, reply, resolve and reopen, exact source and receipt hashes,
original saved-version anchors, event ordering and access under current parent ACLs.
The hardened verifier also checks all direct Office grantees and effective column grants, legitimate owner rights and runtime privileges,
including MAINTAIN, and pins all nine canonical review CHECK definitions. This prevents identical source/restore drift
from passing merely because both databases contain the same broadened grants or weakened constraints.

Final remote Python quality on `2305a96` passed Ruff, formatting across 674 files, Mypy across 532 source files and
full Pytest, with only the known Starlette/AnyIO warning. All 269 focused restore/recovery/backup checks passed in
23.40 seconds. The full browser/model matrix on `7400b35` passed 152/152 in 432.486 seconds: 117 browser cases and
35 model cases, without skipped, unexpected or flaky results. Final desktop/tablet/mobile screenshots were reviewed.
The subsequent `1cf9ee9`/`552b6b6` restore hardening and `2305a96` fixture correction changed no product/UI/schema
behavior after that browser run.

The new nonempty recovery restored 57 documents, 93 exact versions, 30 multi-version documents and 129 source objects,
plus nine review threads and 17 events. It verified three selected-text anchors, one historical discussion and one
complete create/reply/resolve/reopen lifecycle, source/receipt/quotation bindings, current ACLs, foreign-tenant denial
and read-only restored services. Recovery report:
`sha256:330a544deb64fbcb374d1c23732660cb7c2f80b8a2f2cc14289b8e2fa59fae92`.
Migration 0084 has been applied to the main development database; the foundation check passed with 84 migrations
and 93 tables. These are synthetic/development proofs, not ordinary tenant activation or production admission.
Exact backup, restore and browser hashes are maintained in `docs/modules/OFFICE_NATIVE_DOCUMENTS.md`, the operations
log and current handoff.

This slice adds neither comment deletion/editing, notifications/mentions, tracked text changes nor live collaboration.
Draft crash recovery, DOCX interchange and production/real-user admission remain separate work. Native Office
continues before CRM expansion.

Verified pre-/post-migration backups and the foundation/business gates preceded the API-only rollout on dev001.
The live check verified all nine Office operations, local assets and security headers; ordinary tenant Office remained
unprovisioned with 404, Office features closed, KB write false and pilot 0. Scoped cleanup finished with health ok at
2026-09-18 13:14:20 UTC. Exact reports, backup hashes and unchanged other-project state are in the operations log and
current handoff. This closes Roadmap 256 development acceptance without production or real-user admission.
