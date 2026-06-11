# Cryptographic Shredding Simulation

Cryptographic shredding is a controlled key-destruction workflow. It does not claim that object bytes were deleted from storage.

The current implementation is a local development simulator. Production must replace the provider operation behind the same KMS boundary.

## Files

Runtime model:

```text
app/suite/kms/cryptoshred.py
```

Tests:

```text
tests/test_cryptoshred_simulation.py
tests/test_kms_adapter.py
tests/test_envelope_encryption.py
tests/test_backup_failover.py
```

Related docs:

```text
docs/KMS_ADAPTER.md
docs/ENVELOPE_ENCRYPTION.md
docs/RESTORE_TEST_FRAMEWORK.md
docs/operations/BACKUP_FAILOVER.md
```

## Boundary

Allowed path:

```text
source object
  -> retention manifest verification
  -> legal-hold and protected-record checks
  -> human approval reference
  -> KMS key-destruction evidence
  -> cryptoshred simulation manifest
```

The simulator records that encrypted content is unreadable after the key version is destroyed. It also records that object bytes were not deleted and plaintext key material was not exported.

## Blocking Rules

Cryptoshred is denied when:

- legal hold is active
- classification is `gobd` or `legal_hold`
- lifecycle state is `business_record` or `worm_evidence`
- the retention manifest blocks deletion
- WORM retention applies
- the retention period has not ended and policy does not explicitly allow early cryptoshred
- KMS policy does not allow cryptoshred for the data class

## Manifest

Every cryptoshred simulation manifest carries:

- tenant ID
- object ID and source version ID
- classification
- retention policy ID
- legal hold state
- source and target lifecycle states
- KMS key reference
- source manifest hash
- retention manifest hash
- retention policy snapshot hash
- KMS key-destruction evidence hash
- approval reference
- requested-by and approved-by principals
- audit chain reference
- operation time and reason
- explicit `object_bytes_deleted=false`
- explicit `plaintext_key_exported=false`
- manifest hash

## Restore And Evidence

Restore checks must verify the cryptoshred manifest hash, KMS destruction evidence hash, source manifest hash, retention manifest hash, and no-plaintext-key-export claim before treating cryptoshredded content as unrecoverable.

`app/suite/operations/restore_drill.py` records this as a restore drill report with status `unrecoverable_by_policy`.
