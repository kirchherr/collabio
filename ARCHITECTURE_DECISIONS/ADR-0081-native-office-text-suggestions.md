# ADR-0081: Native Office saved text suggestions

Date: 2026-09-21
Status: accepted; implementation, full quality, browser, recovery and dev001 rollout verified
Scope: Roadmap 257 / PLANS 118, extending ADR-0079 and ADR-0080

## Context

Version-bound discussion is useful for review, but a reviewer also needs to propose a concrete replacement and record
its disposition. The proposal must retain the exact original text, and accepting it must never leave a decision
without its saved document change. Existing immutable versions, current parent ACLs and source recovery remain authoritative.

## Decision

Store proposals in append-only `office.text_suggestions` and one terminal decision per proposal in append-only
`office.text_suggestion_decisions`. Migration 0085 extends the installed Office package without activating any tenant.
Payloads use immutable COMMENT SourceObjects and exact versioned-S3 bytes with source-write receipts. Tables and
audit events contain metadata and hashes, never the proposed text or its quotation.

A proposal selects a nonempty UTF-16 range in one inline text run of the current saved document. The server derives
the original quotation (at most 2,000 Unicode code points) and validates replacement text (at most 4,000). Formatting
boundaries may be crossed; paragraph, hard-break and cell boundaries may not. Surrogate splitting and identical
replacement are invalid. Empty replacement denotes deletion. Replacement inherits the first selected character's
marks, keeps all unaffected content and structure, and must pass the complete native document resource limits.
No proposal is automatically reanchored after a new version; its exact original version remains accessible under
current rights. Creation requires an unchanged current saved version in the editor.

Every read uses fresh parent-document access; every mutation requires the Office write feature, fresh typed write/admin
ACL, explicit human confirmation and the existing shared tenant write lock. Actor-bound exact retries recheck current
authorization before consulting immutable mutation evidence. Reusing a mutation reference with different input conflicts.
Open suggestions have revision 1; one accepted or rejected decision makes revision 2. Rejection is permitted for an old
anchor and never changes the document. Acceptance requires both the expected head and anchor version to be current.

Acceptance writes the new document source/version and immutable decision in **one PostgreSQL transaction**, using
the existing transaction-scoped document commit primitive and tenant advisory lock. The decision binds exact result
version, hash, predecessor and actor. A deferred constraint trigger prevents an internal acceptance version from
committing without its decision. Two competing decisions or an intervening ordinary save cannot silently overwrite
content. S3 PUTs are outside PostgreSQL rollback; failed writes may leave detectable orphan content and must be covered
by reconciliation and exact-version recovery rather than a distributed-transaction claim.

Four operations extend the existing API to thirteen: list/create `/v1/office/documents/{object_id}/suggestions`,
read `/{suggestion_id}` and create `/{suggestion_id}/decisions`. Lists are paginated and optionally version-filtered.
Responses expose current capabilities and use `no-store`; errors are constant and indexing flags remain false.
Successful acceptance returns its exact saved document result. A later head change does not rewrite that receipt.

The fourth inspector tab, Vorschläge, shows literal before/after text, author, original version and decision.
Its composer and retry payload exist only in memory. Explicit confirmation precedes creation, rejection and
“Annehmen und neue Version speichern”. Dirty, historical, loading or uncertain editor state cannot accept a proposal.
Conflicts preserve drafts for deliberate reload; uncertain writes retain their exact request for safe retry. Read
refresh failures after known success cannot manufacture a second mutation. Close and context changes invalidate
late responses, and loss of access clears protected state. Compact layouts keep controls reachable in a closable overlay.

## Verification and limits

The restore gate must pin both new append-only tables, forced RLS, exact grants, constraints, source functions and
the deferred decision requirement. A nonempty isolated PostgreSQL/S3 recovery must read every proposal and decision,
bind exact bytes and receipts to original anchors, verify accepted result content and version lineage, prove rejected
proposals have no result version and recheck current ACLs. Both accepted and rejected proposals are mandatory evidence.
Focused policy/storage/concurrency tests, full Python quality and the complete existing browser/model matrix plus
new suggestion cases are required before rollout. These checks passed on dev001: full quality on `9c17a31`,
688 focused tests and all 162 browser/model checks in 535.956 seconds, without skipped, unexpected or flaky results.
Final desktop/tablet/mobile screenshots were independently reviewed. The nonempty proof restored 67 documents,
109 versions, nine review threads/17 events and ten suggestions/seven decisions (five accepted, two rejected), with
exact receipt, content, unchanged-title, result-lineage, current ACL and read-only checks. Report
`sha256:e1ab971a88c43ff06c12544ba24619731b2b8304908da53ab5b73ad8bb017c53`.
Verified pre-/post-0085 backups, an 85-migration/95-table foundation and the existing three-slice business gate preceded
the API-only rollout. Live checks verified thirteen operations and closed ordinary tenant/pilot state. Health and scoped
cleanup passed at 2026-09-21 07:18:57 UTC; exact hashes are in the module document and append-only operations log.

This is an explicit saved-text proposal workflow. Continuous keystroke tracking, live collaboration, automatic merging,
notifications, proposal editing/deletion and DOCX interchange remain separate work. CRM remains behind Office.
Ordinary tenant activation, pilot, indexing and engine/provider admission stay closed.
