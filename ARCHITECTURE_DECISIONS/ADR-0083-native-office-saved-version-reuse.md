# ADR-0083: Native Office saved-version reuse

Date: 2026-09-21
Status: accepted design; development validation pending
Scope: Roadmap 259 / PLANS 120, extending ADR-0079

## Context

Users need to reuse a completed note, brief or earlier version without replacing its source document. The existing
native reader and confirmed document-create operation already provide the required content and persistence contracts.

## Decision

Offer "Als neues Dokument" for an opened, saved current or historical version. A dialog identifies the exact saved
source and lets the user choose a bounded title. Only that saved version is reused; unsaved editor changes are excluded.
Cancellation preserves the source workspace, including unsaved document, review and suggestion drafts. Existing discard
consent applies before replacing such a workspace, followed by fresh authorization reads before the new draft is created.

Reuse the exact-version content endpoint and the document-list response's authoritative `can_create` capability.
Source read access and current create permission are sufficient; source write access is not required. The bounded list
must not be used to decide source visibility: the exact content read provides that check. Validate tenant/document/version,
saved title/content hash and native schema/resource limits, and reject late responses after close, context or session changes.
In-flight, uncertain and conflicting saves cannot be converted to an independent draft.

Create a fresh memory-only editor session without the source object's ID, version, mutation reference, metadata, history,
comments or suggestions. No source ACL, retention record or receipt is copied. The existing explicitly confirmed create
operation then generates a new object, creator ACL and first version under its normal policy and storage controls.
The source document remains unchanged. Unknown create outcomes retain the existing actor-bound exact retry contract.

This is a local drafting workflow, not a server-side copy transaction. Once the independent editable draft exists,
its later create checks the current creation rights and does not reauthorize the former source. No atomic source/create
authorization claim or persisted provenance link is introduced. Content-read and confirmed-create audits remain unchanged.

## Boundaries and validation

No new endpoint, schema, durable format, dependency, indexing or engine admission. Ordinary tenants and the pilot remain
closed. Retain Roadmap 257 recovery evidence; this UI-only slice requires no new recovery execution.

Remote browser tests must verify rich saved content and historical titles, a distinct first-version object, unchanged
source/history, independent ACLs and no copied discussion/suggestion state, fresh role/feature/ACL denial, dirty-draft
cancellation, transient failure/retry, uncertain saves, late close/context responses and responsive controls. Preserve
all 170 existing browser/model cases and run full Python quality before the controlled dev001 API-only rollout.
