# ADR-0080: Native Office version-bound reviews

Date: 2026-09-18
Status: accepted for implementation; runtime acceptance recorded separately

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

Reads use current document read access. All mutations use the existing Office write feature, fresh typed parent
write/admin ACL, explicit human confirmation and the same tenant advisory lock as document saves. Thread revisions
provide a separate compare-and-swap boundary. Exact actor-bound retries are checked after fresh authorization and
before stale-revision rejection; a changed payload with a reused mutation reference conflicts. No new role or
independent comment ACL is introduced.

The UI provides a Comments inspector, a memory-only composer and an explicit review-action confirmation. It renders
literal text, paginates discussions and events, preserves drafts on temporary failures and ignores stale responses
after context changes. Source-position highlights appear only on the exact unchanged saved version. Discussion
state is separate from text undo and document save state.

## Consequences and verification

Discussion heads, events, composite tenant/version/source/receipt constraints, forced RLS, append-only restrictions,
column grants and complete authored trigger function bodies join the existing restore gate. A nonempty isolated
PostgreSQL/S3 restore must prove all four operations, exact event bytes, history, receipts and current ACL behavior
before the controlled API rollout. A database rollback after S3 PUT can leave a detectable orphan; there is no claim
of distributed rollback.

This slice adds neither comment deletion/editing, notifications/mentions, tracked text changes nor live collaboration.
Draft crash recovery, DOCX interchange and production/real-user admission remain separate work. Native Office
continues before CRM expansion.
