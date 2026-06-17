# Source Object Preview Decision Ledger

Status: metadata-only decision ledger wired for blocked preview decisions

## Purpose

Document, mail, and knowledge-base previews must never release source content just because a client asks for it.
The preview decision path records content-preview requests as tenant-scoped, metadata-only evidence and keeps
`content_release_allowed=false`.

## Contract

Each ledger entry carries:

- tenant ID
- source object ID and version ID
- source object type
- preview slot and policy ID
- blocked decision status
- TenantPolicy preview switch state
- required, provided, and missing evidence names
- parser and sanitizer profile IDs
- renderer sandbox evidence reference, when supplied
- human confirmation reference, when supplied
- source detail audit event ID
- preview decision audit event ID
- requester ID
- reason hash
- evidence hash

The ledger must not store source text, mail bodies, attachment bytes, prompts, model outputs, embeddings, transcripts,
or unredacted reason text.

## Current Runtime

`POST /v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-decisions` appends a blocked decision
to the configured ledger after ACL-checked metadata detail lookup and audit logging.

Supported local adapters:

- `InMemorySourceObjectPreviewDecisionLedger` for tests and ephemeral development.
- `JsonlSourceObjectPreviewDecisionLedger` for append-only local persistence under `SUITE_DATA_DIR`.

The Docker Compose API profile sets `SUITE_SOURCE_PREVIEW_DECISION_LEDGER_BACKEND=jsonl`.

## Safety Boundary

The `content_preview_enabled` TenantPolicy switch only satisfies one evidence item. Even when tenant policy, ACL,
detail audit, parser/sanitizer evidence, renderer sandbox evidence, and human confirmation are all present, the
endpoint still returns `decision_status=blocked` and `content_release_allowed=false` until a hardened renderer service,
tenant-scoped sandbox proof, and release workflow are separately implemented.

## Next Boundary

Move the preview decision ledger to a PostgreSQL/RLS-backed adapter and bind renderer-sandbox evidence to a concrete,
audited worker execution profile before considering any content rendering path.
