# ADR-0020: Audit Persistence and Runtime Permissions

## Status

Accepted

## Context

The JSONL audit store proves the hash-chain model, but it is not enough for a multi-tenant suite that will later attach Office, mail, CRM/ERP, RAG, voice, ticketing, LMS, time tracking, and compliance exports. Audit evidence must survive process restarts, enforce tenant isolation at the database layer, and keep normal application roles away from mutable audit rows.

Audit also must not become a sensitive-data lake. Prompts, generated output, source text, mail bodies, transcripts, raw audio, tokens, secrets, and document bodies remain outside normal logs and outside audit rows. Audit may store IDs, hashes, versions, policy metadata, and controlled evidence references.

## Decision

Audit events are persisted in PostgreSQL as tenant-scoped append-only rows:

- `collabio.audit_events` stores a per-tenant sequence number, event ID, actor, type, source IDs, input/output hashes, controlled metadata, previous event hash, and event hash.
- `collabio.audit_checkpoints` stores HMAC-signed checkpoint evidence over a tenant chain prefix.
- `collabio.audit_worm_exports` stores evidence that a chain prefix was exported to WORM-capable storage.
- `collabio_audit_writer` is the only runtime role granted `SELECT` and `INSERT` on audit tables.
- `collabio_app` receives no audit-table grants.
- Row-level security restricts reads and inserts to `collabio.current_tenant_id()`.
- Runtime `UPDATE` and `DELETE` are not granted and have fail-closed RLS policies.
- Audit sequence assignment is protected by a tenant advisory transaction lock.

Checkpoint signatures use HMAC-SHA256 in the development implementation and store only a key reference plus signature output. Production KMS-backed signing can replace the signing primitive without changing event-chain semantics.

## Consequences

- Audit verification can be done per tenant and per checkpoint prefix.
- Application features cannot silently read, alter, or delete audit rows through the normal app role.
- WORM object writes are still a future storage adapter responsibility, but export evidence is now modeled and testable.
- Replaying a tenant audit prefix after restore can compare row hash chain, checkpoint hash, export manifest hash, migration checksum, and backup evidence.

## Rejected Options

- Store full prompts, outputs, transcripts, or source text in audit rows: rejected because audit would become a high-risk data store.
- Let the normal application role write audit rows: rejected because audit must remain a stricter boundary than product writes.
- Use only object storage for audit events: rejected for MVP because transaction-local sequencing and DB tenant checks are needed first.
