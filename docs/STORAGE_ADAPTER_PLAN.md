# S3-Compatible Storage Adapter Plan

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
- Development compatibility provider: MinIO.
- Production reference: self-hosted Ceph RGW Object Lock with OpenBao Transit-backed SSE-KMS.
- The S3 API is a protocol boundary; no AWS infrastructure, account or IAM dependency is required.
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
- S3/MinIO SDKs must stay behind `S3CompatibleObjectStoreClient`; feature code uses `SourceObjectContentStore`.
- Provider profiles must produce `s3_compatible_provider_profile_evidence.v1` before production Knowledge Base writes are wired.
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
2. [x] Add a local MinIO Compose profile for integration tests.
3. [x] Add bucket bootstrap checks for versioning and Object Lock.
4. [x] Persist source object metadata and storage-manifest references in PostgreSQL through `PgSourceObjectRepository`.
5. [x] Add an S3/MinIO-compatible content-store adapter port behind the `SourceObjectContentStore` contract, with versioning, Object Lock, and legal-hold capability checks.
6. Write object version IDs and manifest evidence into audit/outbox events.
7. [x] Add an exact-version restore command and metadata-only report for storage manifests, content hashes, target metadata, Object Lock, Legal Hold, and isolated-target evidence.
8. [x] Add provider profile tests before allowing production object writes.
9. [x] Bind the concrete S3-compatible SDK client behind `S3CompatibleObjectStoreClient` after provider-profile and restore-drill evidence are available.
10. [x] Bind the exact-version restore report to a freshly recomputed persistent runtime report in `backend_storage_foundation_gate.v1`; production cross-site replication and provider-specific failover automation remain deployment work.
11. [x] Add the self-hosted Rook/Ceph/OpenBao production reference, Proof/Production topology policy and metadata-only preflight.
12. [ ] Run the real non-content provider acceptance and isolated provider restores on a dedicated proof cluster, then bind their hashes into production readiness evidence.
