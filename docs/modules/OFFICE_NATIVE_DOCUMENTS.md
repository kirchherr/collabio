# Native Office Documents

Status: product foundation, version workflow and find/replace complete; remote quality/browser acceptance passed; foundation recovery retained
Roadmap: 252 / PLANS 113 foundation; 253 / PLANS 114 version workflow; 254 / PLANS 115 find and replace
Module: `office_documents` / version 0.1.0
Decision: `ARCHITECTURE_DECISIONS/ADR-0079-native-office-document-workspace.md`

## User workflow and scope

`/office` is a focused writing workspace linked from `/work`. Users can start from an empty document or a local template,
apply text styles, headings, lists and tables, navigate an outline, search within text, inspect word count, use focus mode,
save a confirmed version, compare saved versions and take a historical version into a new local draft. Search covers
the current document or loaded document titles; it does not enable a global content index. Desktop, tablet and mobile layouts support keyboard controls and keep reload
available. Formatting returns focus to the editor before immediate typing.

This slice stores native structured documents. DOCX interchange, tracked changes, comments, live collaboration, spreadsheets,
presentations and mail remain separate product work. Existing DOCX engine fidelity and admission gates are unchanged.

## Features and authoritative access

| Feature | Normal behavior | Default |
| --- | --- | --- |
| `office_documents.documents.read` | List authorized documents, open exact content, read and compare saved versions | false |
| `office_documents.documents.write` | Create a native document or explicitly save a successor | false |

The package is installed in the module catalog; no ordinary tenant is provisioned or enabled by migration 0083.
Every route requires tenant context, an enabled module and the read feature. Writes also require the write feature and
explicit confirmation. Create requires `office-editor` or `tenant-admin`; save requires an explicit current write/admin
ACL on object type `office.document`. Role membership does not replace object authorization. Current PostgreSQL ACLs
and server-resolved ABAC scope are rechecked, including on replay and historical reads. JWT ignores browser grant headers.

| Route | Result |
| --- | --- |
| `GET /v1/office/documents` | Authorized heads and server-derived capabilities |
| `POST /v1/office/documents` | Create document and first immutable version |
| `GET /v1/office/documents/{object_id}/content` | Exact current or requested historical native content |
| `GET /v1/office/documents/{object_id}/versions` | Authorized metadata-only version history |
| `POST /v1/office/documents/{object_id}/versions` | Compare expected head and append a confirmed successor |

Content and error responses use `no-store`. Invalid JSON/schema errors do not echo submitted content. Storage/database
failures use constant messages. The UI uses local assets under a restrictive CSP, retains drafts after transient failures
or stale-head conflicts, clears content when access is denied, preserves exact retry keys and drops late responses after
closing or changing context. Only connection context,
never content or credentials, is stored in browser localStorage.

## Version comparison and local takeover

Roadmap 253 extends the existing five APIs without another persistence model. Users explicitly select two saved
versions in the history dialog and load their comparison. Both exact source versions are read through the normal
authoritative content route; no stored browser copy substitutes for a new authorization check. The comparison is local
and uses literal text, showing added, removed, changed and unchanged document blocks plus both saved titles. It detects
format/structure differences even when visible text is unchanged. Tables and lists retain readable row/cell/item
boundaries. Large comparisons use bounded alignment work and paginated rendering without silently dropping blocks;
an approximate alignment is labelled. It is a block comparison, not tracked changes or automatic merging.
The existing history route returns at most 200 recent versions. A connected partial history is accepted and labelled;
relative labels do not invent absolute version numbers for older unloaded entries.

An authorized reader may compare but cannot take over content for editing. Taking a historical version into a draft
refreshes its exact content, the current head and current document capabilities. The new draft uses historical content
and title while preserving the fresh head as its expected save base. Current write permission is required; historical
write capability alone is insufficient. No POST occurs until the existing explicit save confirmation. The original
versions remain immutable. An intervening save produces the ordinary CAS conflict and preserves the draft.

Comparison selection changes, close, context switches and superseding editor operations invalidate pending responses.
Access denial clears protected state; a temporary read failure clears partial comparison output but preserves the
existing draft. Cancelling the discard decision preserves edits. Unsaved takeover content stays only in memory, and
unchanged content/title does not manufacture a dirty version. No schema, retention, backup format or engine permission
changes. Existing migration 0083 and exact-version recovery contracts remain applicable.

## Find and replace

Roadmap 254 extends search within the already opened native document. Search terms and replacement text are literal;
no regex syntax, markup evaluation, global search index or network lookup is involved. Matching uses original UTF-16
positions, including text split by formatting marks. Case-insensitive matching uses Unicode simple case folding;
it does not expand sharp-s to `ss` or normalize accents. Whole-word matching treats Unicode letters, numbers, combining
marks, connector punctuation and join controls as word characters. Matches do not cross paragraph, hard-break, list-item
or table-cell boundaries. All matches are counted and navigable; only a labelled window of highlights is rendered.

Current or all replacements affect only the local draft and form one undo step separated from adjacent typing.
Untouched text keeps its formatting; replacement text takes the first matched character's marks. Empty replacement
deletes the selected text while preserving structural nodes. Identical replacement leaves content and undo state alone.
Size, character, node and depth limits are checked before changing the editor. Read-only or historical documents may
be searched but not replaced; loading, saving, restoration and an uncertain save also block replacement. Search inputs
are memory-only and cleared with the workspace/context. The existing confirmed CAS save alone persists a successor.

Ctrl/Cmd+F opens the search field; Ctrl/Cmd+H focuses replacement. Enter/Shift+Enter move forward/backward and Escape
closes the panel and returns focus to the editor. A 200-match highlight window follows the active match while the
count/navigation/replacement set stays complete. If a replacement removes the final match, keyboard focus remains in
the replacement field. Loaded content is excluded from undo history; undoing the first actual edit returns to the
loaded version instead of erasing it. Search/case/whole-word settings are reset when the panel or workspace closes.

## Records, retention and recovery

Migration `0083_office_native_documents.sql` creates `office.documents` and `office.document_versions`. Heads carry
tenant/object identity, owner/creator, timestamps, internal classification, `rp-standard`, Legal Hold state, lifecycle,
KMS reference, source system and schema version. Version rows bind source identity, content/manifest hashes, exact
write-receipt hash, creator and mutation reference; they are append-only. The head changes only to a validated successor.
Immutable shared SourceObjects carry the exact canonical JSON bytes and full security metadata in versioned S3 storage.

The initial slice accepts ordinary internal saved versions under the shared retention/KMS contracts. It does not implement
classification changes, Legal Hold administration, record declaration or deletion; unsupported source state fails closed.
Existing hold/retention and compliance workers remain independent of normal module availability. No new deletion bypass,
index, AI provider or export path is created. Drafts are transient and have no claim of crash recovery.

A creator ACL is inserted atomically with the head. Versions, source metadata, receipts and head updates share one database
transaction. A tenant advisory lock precedes S3 PUT and stale-head validation. An unexpected database failure after PUT
can leave a detectable orphan object; PostgreSQL rollback is not a cross-system rollback claim.

Backup covers both Office tables, current ACLs, module/features, migration state, trigger functions, narrow column grants,
source metadata/receipts and exact S3 versions. Restore must validate forced RLS, append-only versions, creator ACL trigger,
source binding, head guard and all associated function bodies against migration 0083, even when source and target have
the same unexpected drift. Disabled normal features do not stop backups or compliance recovery. The isolated nonempty
recovery proof must preserve native content, source hashes, historical reads and current ACL behavior.

## Foundation acceptance evidence (Roadmap 252)

Domain, PostgreSQL and API tests cover strict content limits, authoritative access, CAS races, exact idempotency,
failure rollback, orphan detection, safe errors and module gates. Full backend quality on `7bba74f` passed Ruff checks
and formatting across 665 files, Mypy across 526 source files and the full Pytest suite.

The final browser run on `5917bdf` passed all 73 cases in 160.237 seconds, with zero skipped, unexpected or flaky tests.
The previous 60 Work/KB/CRM cases remain green. Thirteen Office cases cover actual rich-text/table authoring, confirmed
saves, reopen and historical reads, concurrent conflict, read-only access, forged/foreign grants, ACL revocation, feature
removal, pre-PUT and read failures, idempotent retry after a lost successful response, literal markup and delayed
close/context responses. Desktop, tablet and mobile screenshots were visually reviewed. The earlier complete run's
toolbar-focus failure was fixed in `5917bdf` and the existing rich-authoring test now checks immediate focus restoration.

The nonempty recovery proof on `5917bdf` verified 13 Office documents, 18 versions, five documents with multiple versions
and an inventory of 37 source objects, including exact content, historical reads and current ACL behavior. Its report is
`sha256:e61e7a26da539fa5a974a4faff62c31eb68502bd5c30f8f941df3effc2ae4cda`.
Migration 0083 has been applied to the main development database. The foundation gate passed with 83 migrations,
91 tables and `office_document_controls_verified=true`. The existing three-slice business release gate also passed
without business writes or tenant activation. The API-only development rollout returned healthy; final live checks
and cleanup are recorded in the operations log and current handoff.

All browser and nonempty Office recovery data use the isolated synthetic tenant `tenant-work-e2e`, real PostgreSQL/S3
and fresh ACL resolution. No ordinary tenant was enabled; the normal pilot switch, indexing and DOCX engine gates remain
closed. These results complete Roadmap 252 / PLANS 113 as a product foundation, not a production or real-user admission.

## Version workflow acceptance (Roadmap 253)

Implementation `3aa0069` passed full remote Ruff checks/formatting (665 files), Mypy (526 source files) and Pytest.
The focused 27 checks passed, followed by the complete 100-check matrix in 249.923 seconds: 88 browser cases and
12 pure comparison-model cases, with zero skipped, unexpected or flaky results. All previous 73 browser cases remain.
The model suite checks bounded alignment, semantic mark/key ordering and complete ordered projections for long text,
large unique/repeated blocks and duplicate edit patterns. Browser proof covers exact version/title/format/table changes,
read-only access, fresh-head takeover, confirmed successor lineage, later CAS conflict, current ACL/feature removal,
cancelled discard, transient storage failure and late close/selection/context/takeover responses. A partial history
window uses three real saved versions and one reduced metadata response. Identical takeover creates no dirty version.
Desktop, tablet and mobile screenshots passed visual review.

Final report: `sha256:42448945e2d326b56552c886d3603d69d1dcaf4d416ca4c727bf2e66e3ce8859`.
Evidence lives under ignored `e2e/work/artifacts/roadmap-253/`; hashes and controlled API rollout are recorded in the
operations log and current handoff. No new schema, durable record, storage format or write API was added. Roadmap 252's
verified migration/backup/nonempty recovery/foundation/business proofs remain retained; they were not rerun for 253.

## Find/replace acceptance (Roadmap 254)

Implementation `f4c37e5` passed full remote Ruff/format (665 files), Mypy (526 source files) and Pytest; only the known
Starlette/AnyIO warning remains. All 32 focused checks passed after correcting an initial undo-history defect and one
case-sensitive test expectation. Loaded content is now explicitly excluded from history, so the first typed edit cannot
merge with document loading. The full matrix passed 132/132 in 291.588 seconds: 97 browser cases and 35 pure model cases,
zero skipped, unexpected or flaky. All prior 100 checks remain green. Twenty-three new model tests cover Unicode,
exact positions, format/run boundaries, literal/no-op replacement and limits, including 100,000 matches and preflight
rejection of explosive expansion. Nine browser runs prove actual save/reopen/immutable versions, undo/redo separated
from adjacent typing, full counts above 1,000, read-only/history, literal hostile markup, size/no-op/deletion behavior,
cancelled discard/context/late reads and responsive controls. Final desktop/tablet/mobile screenshots passed visual review.

Results: `sha256:e12cf71865e5a013852d6482b6a96a33d5a37c4c031157721d0d980324d32b71`, under ignored
`e2e/work/artifacts/roadmap-254/`. API rollout, cleanup and exact screenshot hashes are in the operations log/handoff.
No new schema, storage format, write endpoint or tenant capability; item 252 recovery proofs remain retained, not rerun.

## Continuing Office work

Roadmap 254 / PLANS 115 is complete. Preserve the confirmed save and current access contracts when extending native
editing and review workflows. Comments, tracked changes and live collaboration remain separate open work. Native Office
continues before further CRM expansion; DOCX fidelity, engine admission and interchange keep their separate gates.
