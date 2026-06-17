# Source Object Preview Renderer Sandbox

Status: metadata-only worker evidence with PostgreSQL/RLS runtime store

## Purpose

The renderer sandbox path prepares the future document, mail, and knowledge-base preview pipeline without releasing
content. It records that a preview renderer worker would be bound to an ACL-checked source object and to the existing
parser/sanitizer, backup, and restore evidence chain.

## API Contract

`POST /v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-renderer-runs` records a renderer
sandbox evidence entry and returns a `renderer-sandbox:sha256:...` reference.

The response is metadata-only:

- `content_rendered=false`
- `content_included=false`
- `rendering_allowed=false`
- `output_persisted=false`
- `external_fetch_allowed=false`
- `temporary_workspace_destroyed=true`

The evidence includes tenant ID, source object ID, source version ID, source object type, manifest hash, content hash,
ACL version, preview slot, preview policy, parser profile, sanitizer profile, worker profile, worker queue ID, worker job
ID, worker idempotency key hash, worker queue binding reference, parser/sanitizer evidence reference, backup coverage
reference, restore drill reference, audit event IDs, requester ID, reason hash, sandbox boundaries, and an evidence hash.

It must not store source text, rendered HTML, mail bodies, attachment bytes, prompts, model outputs, embeddings,
transcripts, or unredacted reason text.

## Decision Binding

Preview decisions only count `renderer_sandbox_worker_evidence` as provided when the renderer reference resolves in the
tenant-scoped evidence store and matches the current source object, source version, source type, preview slot, preview
policy, parser/sanitizer reference, backup reference, and restore reference.

Invalid, missing, cross-object, or stale renderer evidence keeps `content_release_allowed=false` and adds a blocking
reason while still preserving the attempted reference on the decision response.

## Current Stores

- `InMemorySourceObjectPreviewRendererEvidenceStore` for tests and ephemeral development.
- `JsonlSourceObjectPreviewRendererEvidenceStore` for append-only local persistence under `SUITE_DATA_DIR`.
- `PgSourceObjectPreviewRendererEvidenceStore` for PostgreSQL/RLS-backed API and worker runtime.

Migration `0032_source_object_preview_renderer_evidence.sql` creates
`collabio.source_object_preview_renderer_evidence` with forced row-level security, tenant-scoped select/insert,
blocked update/delete policies, metadata-only content boundary checks, and queue/idempotency binding columns.

The Docker Compose API profile sets `SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_BACKEND=postgres`.

`docker compose run --rm preview-renderer-drill` emits a metadata-only
`source_object_preview_renderer_recovery_drill_report.v1` report. The report verifies preview decision recovery,
renderer evidence recovery, worker queue binding replay, idempotency hash replay, tenant isolation smoke checks, and the
metadata-only content boundary.

`docker compose run --rm preview-renderer-smoke` creates renderer and decision evidence through the API, then runs the
same recovery drill against the PostgreSQL-backed stores. It emits a metadata-only
`source_object_preview_renderer_api_smoke_report.v1` report with a `preview-renderer-recovery-drill:sha256:...`
release/restore evidence reference.

## Release Gate

`source_object_preview_renderer_release_gate.v1` is the hard prerequisite before any real renderer engine, viewer, or
content release workflow is wired. The gate is tenant-scoped and only becomes `ready` when both required evidence inputs
are present, hash-valid, fresh, and bound to each other:

- `source_object_preview_renderer_api_smoke_report_hash`
- `source_object_preview_renderer_recovery_drill_report_hash`

The gate keeps `renderer_connection_allowed=false`, `viewer_connection_allowed=false`, and
`content_release_workflow_allowed=false` whenever the API smoke report is stale or failed, the recovery drill is stale or
not ready, the tenant IDs do not match, the smoke report is not bound to the drill report hash, or the metadata-only
boundary is not verified. Future renderer, viewer, office, mail, knowledge-base, e-discovery, and content-release
integrations must call the gate check before attaching any content-bearing path.

`preview-renderer-smoke` now emits `source_object_preview_renderer_release_gate_smoke_report.v1` by default. It still
creates the API smoke report and bound recovery drill report, then creates and persists a
`source_object_preview_renderer_release_gate.v1` record in the configured release-gate evidence store. The Compose path
uses `PgSourceObjectPreviewRendererReleaseGateEvidenceStore` with
`collabio.source_object_preview_renderer_release_gate_evidence`, forced RLS, append-only insert/select policies, and no
content-bearing columns. JSONL remains available for local diagnostics; use `--api-only` when only the lower-level API
smoke report is needed.

## Next Boundary

Bind the first real renderer or viewer adapter behind `require_source_object_preview_renderer_release_gate_for_wiring`,
with the adapter still unable to return rendered content until a separate content-release workflow is approved.
