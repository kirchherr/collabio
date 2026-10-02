# ADR-0083: Native Office saved-version reuse

Date: 2026-09-21
Status: accepted; development verification and controlled dev001 rollout complete
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

## Verification state

The ten focused reuse checks passed on `e7fec24` in 41.7 seconds. They exercise real PostgreSQL/S3 content and creates,
independent identity/creator ACLs, unchanged source/history, excluded source discussions and grants, fresh capability
checks after discard consent, failure/retry and responsive controls. Focused report:
`sha256:95646616c21d7d1d140dfc05ddda7998e035551440cc5a74ef5a203711240385`.
The preceding 9/10 run required only a canonical table-attribute correction in its synthetic fixture; exact equality
assertions and product behavior remain unchanged. Initial desktop/tablet/mobile screenshots passed visual review.
Full verification on `e7fec24` passed 180/180 checks in 664.306054 seconds: 145 browser cases and 35 model cases,
zero skipped, unexpected or flaky, retaining all previous 170 checks. Ruff, formatting across 691 files, Mypy across
541 sources and full Pytest passed; only the known Starlette/AnyIO warning remains.
Full browser report: `sha256:9792822a6de9a37b6b92acd67805e3f52ae535ad63836a70be176d72ea8f3237`;
quality log: `sha256:f66e1d0bacac61ebd7625e182d4293791b5b1c4856bd466d6b0a6db0f65a5cfe`.
Independent final desktop/tablet/mobile review passed without clipping, overflow or unreachable controls. The controlled
API-only `--no-deps` rollout reached healthy at 2026-09-21 12:21:23 UTC with pilot 0; live checks confirmed the thirteen
Office OpenAPI operation definitions, controls and closed tenant gates. Scoped cleanup finished healthy at 12:22:11 UTC
with main storage and other projects unchanged.
Roadmap 259 development is complete. This design and its evidence do not constitute production or ordinary-user admission;
no main-database migration or new recovery execution is claimed.
