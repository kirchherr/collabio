# ADR-0024: S3-Compatible Object Storage And MinIO/AWS Compatibility Target

Status: accepted
Date: 2026-06-11

## Context

Office documents, mail attachments, parser artifacts, export packages, audit snapshots, and WORM evidence records need portable object storage semantics. The suite must support self-hosted deployments without binding the domain model to one cloud provider, while still preserving versioning, retention, legal hold, restore verification, and KMS references.

Raw filesystem storage is not enough for production records. Direct SDK calls from feature code would also bypass the compliance path we already introduced with source object metadata and `SourceObjectWriteGuard`.

## Decision

Use an S3-compatible object storage adapter boundary as the first object-storage target.

MinIO is the development and self-hosted evaluation provider. AWS S3 Object Lock compatibility is the production reference target. Other enterprise S3-compatible stores may be supported only when they satisfy the same adapter policy.

The adapter policy is machine-readable in:

```text
docs/storage_adapter_policy.json
```

The adapter must enforce:

- no direct S3/MinIO SDK use from feature code
- `SourceObjectWriteGuard` before accepting object data
- bucket versioning for every object bucket
- Object Lock in compliance mode for business records, WORM evidence, audit snapshots, and e-discovery packages
- legal hold mapping for object-lock buckets
- retention-policy mapping for object-lock buckets
- KMS key references and encryption metadata on every object write
- restore verification through source object manifest hash and content hash checks before restored content is served

Initial bucket profiles:

- `working-objects`
- `business-records`
- `evidence-records`
- `parser-artifacts`

Metadata authority remains PostgreSQL. Native bytes, object versions, retained manifests, parser artifacts, evidence packages, and WORM snapshots live in object storage.

## Consequences

Easier:

- Self-hosted and cloud deployments share one storage contract.
- Versioning, object lock, legal hold, and restore checks become adapter requirements rather than scattered feature behavior.
- MinIO can be used for local and self-hosted development while keeping AWS S3 Object Lock semantics as the compatibility target.
- E-discovery and backup evidence can rely on manifest and content-hash checks.

Harder:

- Production readiness requires object-store configuration checks, not just app tests.
- Retention and legal-hold behavior must be validated against the provider profile before enabling record writes.
- Cross-bucket replication and failover remain separate deployment work.
- We need license and operating-model review before claiming MinIO as an enterprise default.

## Alternatives Considered

### Provider-specific AWS S3 first

Rejected for the core adapter because the suite must be self-hostable. AWS S3 remains the production compatibility reference, especially for Object Lock behavior.

### Filesystem storage

Rejected for production because it does not provide portable object-lock, legal-hold, versioning, replication, and restore-verification semantics.

### Database blobs

Rejected for native document and attachment bodies because large objects, WORM semantics, object-lock retention, and e-discovery package handling are better served by an object store.

### Add object lock later

Rejected because business-record provenance, GoBD posture, and evidence-chain semantics would be weak from the first stored object onward.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-004, CM-005, CM-006, CM-007
- `docs/SOURCE_OBJECT_MODEL.md`: source metadata, manifest hash, content hash, KMS key reference
- `docs/operations/BACKUP_FAILOVER.md`: restore verification and failover posture
- GoBD: immutability, traceability, data access
- DSGVO: restriction, deletion conflict handling, tenant-scoped safeguards
- E-discovery: chain of custody and reproducible export packages

## Verification

- `tests/test_storage_adapter_policy.py` validates the machine-readable adapter policy.
- `tests/test_source_objects.py` validates the write guard before storage acceptance.
- Backup/failover policy includes source object manifest, content hash, retention, legal hold, and chain-of-custody checks.
- Future adapter integration tests must create buckets with versioning and Object Lock before enabling record/evidence writes.
