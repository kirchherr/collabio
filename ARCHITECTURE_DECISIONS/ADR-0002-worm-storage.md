# ADR-0002: WORM Storage And Object Lock Strategy

Status: accepted
Date: 2026-06-10

## Context

Business records, GoBD-relevant records, audit snapshots, export packages, and evidence records need immutability and reproducible verification. A normal object store without lock semantics is not enough.

## Decision

The storage architecture must support S3-compatible Object Lock / WORM semantics through a storage adapter.

No productive business or evidence record may be written without:

```text
tenant_id
object_id
object_type
content_hash
classification
retention_policy_id
retain_until
legal_hold_state
kms_key_ref
manifest_hash
schema_version
```

WORM-capable storage is required for:

- business records
- GoBD records
- evidence records
- audit snapshots
- export packages

MinIO is the initial self-hosted candidate for development and evaluation; the adapter must remain S3-compatible and portable.

## Consequences

- Storage writes become policy-controlled operations, not raw SDK calls.
- Deleting a database row must never imply deleting a WORM object.
- Legal Hold must affect storage and lifecycle behavior, not just metadata.
- Object versioning and manifests become part of record identity.

## Alternatives Considered

- Filesystem-only storage: rejected because it lacks portable WORM semantics.
- Database blobs for records: rejected for large objects and object-lock portability.
- Add WORM later: rejected because record provenance would be weak from day one.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-004, CM-005, CM-006, CM-007
- GoBD: immutability, traceability, data access
- E-discovery: chain of custody and reproducible exports

## Verification

- Adapter tests require classification, retention, KMS ref, and manifest hash.
- Retention tests prove protected objects cannot be deleted before expiry.
- Legal-hold tests prove held objects remain immutable after retention expiry.
- Export tests verify manifests and hashes.

