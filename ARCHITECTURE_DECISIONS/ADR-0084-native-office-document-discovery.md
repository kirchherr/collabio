# ADR-0084: Native Office title search and document discovery

Date: 2026-09-21
Status: accepted design; development validation pending
Scope: Roadmap 260 / PLANS 121, extending ADR-0079 and ADR-0083

## Context

The native document list returned at most 200 records and filtered their titles in the browser. Older readable
documents could therefore remain undiscoverable. List membership also incorrectly represented source authorization
in several client workflows; absence from a filtered or paginated page cannot establish access revocation.

## Decision

Extend the existing GET document list with an optional literal title query, a bounded page size and an opaque cursor.
Keep the existing response fields and add page size, has-more and next-cursor metadata, without a total count or query
echo. Calls without parameters remain bounded to 200 records. The Office UI explicitly requests pages of 50.
Case-insensitive matching uses lowercase substring comparison; percent signs, underscores and backslashes are literal.
Queries are bounded to 200 Unicode codepoints and reject control characters or invalid Unicode.

Order by immutable creation time and object ID, descending. Saving or renaming does not move a document between pages.
Each page rechecks the current module, role, ABAC and typed object ACL before applying its limit and lookahead.
New documents require a refresh; concurrent title or permission changes can alter later results. This is live discovery,
not a frozen snapshot. A cursor never grants access, and no unreadable count or title is returned.

Authenticate cursors with HMAC and bind them to tenant, actor, role set, normalized query and page size. Validate their
shape, size and position before repository access. The signing key belongs to the current service instance and is not
persisted: restart invalidates cursors and requires a list refresh. This supports the current single-worker deployment;
multi-worker/shared-key operation requires a separate deployment decision. No signing secret is exposed or added to Git.

Search, next-page loading and list retry use separate request generations and cancel stale work. They never replace an
editor, discard drafts or infer source permissions from the returned page. A manual refresh separately reauthorizes the
exact opened saved version while preserving local edits; an actual authorization denial clears protected content.
Transient failures preserve drafts. Fresh content responses, rather than list membership, authorize historical takeover
and suggestion acceptance. Existing source/version/hash checks, confirmed writes and exact retries stay intact.

Keep query text and cursors out of audit metadata and ordinary Uvicorn access logs. The narrow access-log filter removes
the list request's query string before handlers format its structured record, retaining path, method and response status.
No content index, RAG path, new endpoint, dependency, schema or durable record is introduced.

## Validation and boundaries

Exercise genuine PostgreSQL authorization before pagination, beyond-200 discovery, literal titles, stable order, current
role/ACL changes, malformed and cross-context cursors, logging redaction, protected drafts, errors/retries, late responses
and desktop/tablet/mobile controls. Preserve all 180 prior browser/model checks and run full Python quality on dev001.
Ordinary tenant, pilot, indexing, cloud provider and DOCX engine gates remain closed. Existing Roadmap 257 recovery
evidence remains retained; this read-only API/UI extension does not claim a new main-database migration or recovery drill.
