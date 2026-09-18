# Native Office Documents

Status: product foundation complete; remote acceptance and nonempty recovery passed
Roadmap: 252 / PLANS 113
Module: `office_documents` / version 0.1.0
Decision: `ARCHITECTURE_DECISIONS/ADR-0079-native-office-document-workspace.md`

## User workflow and scope

`/office` is a focused writing workspace linked from `/work`. Users can start from an empty document or a local template,
apply text styles, headings, lists and tables, navigate an outline, search within text, inspect word count, use focus mode,
save a confirmed version and read previous versions. Search covers the current document or loaded document titles;
it does not enable a global content index. Desktop, tablet and mobile layouts support keyboard controls and keep reload
available. Formatting returns focus to the editor before immediate typing.

This slice stores native structured documents. DOCX interchange, tracked changes, comments, live collaboration, spreadsheets,
presentations and mail remain separate product work. Existing DOCX engine fidelity and admission gates are unchanged.

## Features and authoritative access

| Feature | Normal behavior | Default |
| --- | --- | --- |
| `office_documents.documents.read` | List authorized documents, open exact content, read version history | false |
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

## Acceptance evidence

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

## Next Office step

Roadmap 253 / PLANS 114 remains pending: compare authorized saved versions and open an earlier version as a new local
draft. Refresh the current head and capabilities before preparing that draft, recheck current ACLs and CAS on save,
and require explicit confirmation to append a new version. Existing history must remain unchanged. Native Office work
continues before further CRM expansion; DOCX fidelity, engine admission and interchange keep their separate gates.
