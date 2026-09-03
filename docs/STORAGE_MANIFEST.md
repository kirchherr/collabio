# Storage Manifest

Storage manifests are the object-store evidence boundary for source object bytes.

The rule: a storage object is not restorable, readable, exportable, indexable, or admissible as evidence until its storage manifest, source manifest, retention manifest, and content hash all verify together.

## Files

Runtime model:

```text
app/suite/storage/storage_manifest.py
```

Tests:

```text
tests/test_storage_manifest.py
tests/test_storage_adapter_policy.py
tests/test_backup_failover.py
```

Related docs:

```text
docs/SOURCE_OBJECT_MODEL.md
docs/CONTENT_HASH_VERIFICATION.md
docs/RETENTION_MANIFEST.md
docs/STORAGE_ADAPTER_PLAN.md
docs/KMS_ADAPTER.md
docs/ENVELOPE_ENCRYPTION.md
docs/RESTORE_TEST_FRAMEWORK.md
docs/operations/BACKUP_FAILOVER.md
```

## Manifest Fields

Every storage object manifest carries:

- tenant ID
- source object ID
- source object type
- source version ID
- bucket profile ID
- object key
- object version ID
- storage provider
- stored-at timestamp
- classification
- lifecycle state
- retention policy ID
- legal-hold state
- KMS key reference
- source object manifest hash
- content hash
- content byte length
- retention manifest hash
- retention policy snapshot hash
- object-lock mode
- object-lock retain-until timestamp where applicable
- object-lock legal-hold evidence where applicable
- WORM requirement
- audit chain reference
- storage manifest hash

## Build Boundary

`build_storage_object_manifest` requires:

- source object metadata and bytes
- retention manifest
- bucket profile
- object-store version ID
- stored-at timestamp

It rejects manifests when:

- the retention manifest does not match the source object
- the bucket profile does not match the retention manifest
- the bucket profile does not allow the source object type or lifecycle state
- the KMS key reference does not match the source tenant and data class
- WORM retention is mapped to a non-object-lock bucket
- active legal hold cannot be represented by an object-lock bucket when object lock is required
- content hash verification fails

## Restore Boundary

`verify_storage_object_restore` verifies:

- storage object manifest hash
- source object manifest hash
- retention manifest hash
- retention policy snapshot hash
- content hash with context `restore`
- object-lock configuration
- legal-hold evidence
- KMS key reference alignment with source metadata
- envelope encryption manifest hash before encrypted object restore

Restore verification returns structured evidence with the manifest hash, source manifest hash, retention manifest hash, content hash, bucket, object key, object version ID, checks performed, and content hash verification result.

Suite-level restore drills are orchestrated by `app/suite/operations/restore_drill.py`, which combines storage, retention, envelope, KMS, and cryptoshred evidence into a hashable restore drill report.

## Adapter Rule

The S3/MinIO-compatible adapter port must treat this model as the acceptance boundary:

```text
source object
  -> retention manifest
  -> bucket profile
  -> KMS key reference validation
  -> envelope encryption manifest
  -> content hash verifier
  -> storage object manifest
  -> encrypted object write
  -> restore verification before read/export/index
```

Feature code must not call S3, MinIO, or provider SDKs directly.

`S3CompatibleSourceObjectContentStore` enforces the `SourceObjectContentStore` contract, verifies content hashes on write/read, checks bucket versioning and Object Lock/legal-hold capability before WORM writes, and exposes inventory for `source_object_content_recovery_evidence.v1`. `Boto3S3CompatibleObjectStoreClient` is the concrete S3-compatible SDK adapter behind `S3CompatibleObjectStoreClient`; feature code still never imports or calls the SDK directly. `s3_compatible_provider_profile_evidence.v1` records provider capability readiness before production writes are wired. MinIO supplies development compatibility; self-hosted Ceph RGW plus OpenBao is the production reference.

## Continuity

The backup/failover policy tracks this as `storage_object_manifest_hash_check`.

Object-store restore evidence must include storage manifest hash, source manifest hash, retention manifest hash, content hash result, restore drill report hash, object version ID, bucket profile, object-lock state, legal-hold state, KMS key reference, and audit chain reference.
