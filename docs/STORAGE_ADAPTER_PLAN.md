# S3/MinIO Storage Adapter Plan

The storage adapter is the object-content boundary beneath source objects.

Product code must not call S3, MinIO, or any object-store SDK directly. It writes source objects through storage APIs that validate metadata, content hashes, manifest hashes, retention, legal hold, KMS references, and audit references first.

Retention manifests are defined in `docs/RETENTION_MANIFEST.md` and must be available before record/evidence object writes are enabled.

Content hash verification is defined in `docs/CONTENT_HASH_VERIFICATION.md` and must be reused for writes, reads, restore drills, parser inputs, and exports.

Storage manifests are defined in `docs/STORAGE_MANIFEST.md` and must be produced for every object-store write before the future adapter serves restored content.

KMS adapter rules are defined in `docs/KMS_ADAPTER.md` and must validate tenant/data-class key references before envelope encryption is introduced.

Envelope encryption is defined in `docs/ENVELOPE_ENCRYPTION.md`; encrypted object writes must carry envelope manifest evidence before restored bytes are trusted.

## First Decision

ADR:

```text
ARCHITECTURE_DECISIONS/ADR-0024-s3-compatible-object-storage.md
```

Policy:

```text
docs/storage_adapter_policy.json
```

Decision summary:

- Provider API: S3-compatible.
- Development and self-hosted evaluation provider: MinIO.
- Production compatibility target: AWS S3 Object Lock semantics.
- Metadata authority: PostgreSQL.
- Native object bytes, object versions, manifests, parser artifacts, audit snapshots, and export packages: object storage.

## Required Adapter Path

```text
SourceObjectRecord
  -> SourceObjectWriteGuard
  -> content hash verifier
  -> Storage adapter policy
  -> object bucket profile
  -> KMS key reference validation
  -> envelope encryption manifest
  -> retention manifest
  -> storage object manifest
  -> encrypted object write
  -> version ID and manifest evidence
  -> audit event / outbox event
```

The storage adapter must never be an authorization source. Read flows still require tenant context, authoritative authz, lifecycle checks, and audit.

## Bucket Profiles

`working-objects`:

- working data, drafts, comments, collaborative state, non-record saved versions
- versioning required
- Object Lock not required yet
- restore checks: source object manifest, content hash, tenant metadata

`business-records`:

- saved business records and GoBD-relevant versions
- versioning required
- Object Lock compliance mode
- legal hold supported
- restore checks: source object manifest, object manifest, content hash, retention, legal hold, chain of custody

`evidence-records`:

- audit snapshots, e-discovery packages, legal evidence, forensic exports
- versioning required
- Object Lock compliance mode
- legal hold supported
- longer default retention baseline
- restore checks: source object manifest, object manifest, content hash, retention, legal hold, chain of custody

`parser-artifacts`:

- parser manifests, extracted text artifacts, warnings, sandbox evidence
- versioning required
- Object Lock not required by default
- restore checks: parser manifest, source object manifest, content hash, parser version

## Hard Requirements

- No direct SDK calls from feature code.
- Every object write must pass `SourceObjectWriteGuard`.
- Every bucket uses versioning.
- Record/evidence buckets require Object Lock compliance mode.
- Object-lock buckets support legal hold.
- Every write carries KMS reference metadata.
- KMS references must be canonical and match tenant plus data class before object writes.
- Restore cannot serve content until storage object manifest hash, envelope encryption manifest hash, source object manifest hash, retention manifest hash, Object Lock evidence, legal-hold state, KMS evidence, and shared content hash verification pass.
- Deleting metadata must not delete WORM object versions.
- Cryptoshred must be policy-gated and must not apply to GoBD or legal-hold records.

## Future Implementation Steps

1. Add a `StorageObjectAdapter` protocol with write/read/manifest/restore-check methods.
2. Add a local MinIO Compose profile for integration tests.
3. Add bucket bootstrap checks for versioning and Object Lock.
4. Persist source object metadata in PostgreSQL.
5. Write object version IDs and manifest evidence into audit/outbox events.
6. Add restore verification commands for storage manifests, object manifests, and content hash evidence.
7. Add provider profile tests before allowing production object writes.
