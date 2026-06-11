# Restore Test Framework

The restore test framework turns restore drills into hashable evidence.

It does not expose restored content in reports. Reports carry hashes, check names, manifest references, KMS evidence hashes, and status.

## Files

Runtime model:

```text
app/suite/operations/restore_drill.py
```

Tests:

```text
tests/test_restore_drill.py
tests/test_storage_manifest.py
tests/test_envelope_encryption.py
tests/test_cryptoshred_simulation.py
tests/test_backup_failover.py
```

## Restored Object Flow

```text
source object
  -> storage manifest verification
  -> retention manifest verification
  -> content hash verification
  -> envelope manifest verification
  -> KMS key reference validation
  -> authenticated decrypt
  -> restore drill report hash
```

The restored report status is `restored`. It records storage, source, retention, envelope, content, and KMS evidence hashes. It marks `restored_content_released=true` only after all checks pass.

## Cryptoshredded Object Flow

```text
source object
  -> storage manifest hash verification
  -> retention manifest hash verification
  -> cryptoshred manifest verification
  -> KMS destruction evidence hash verification
  -> no-plaintext-key-export check
  -> restore drill report hash
```

The cryptoshredded report status is `unrecoverable_by_policy`. It records that encrypted content is unreadable and that restored content was not released.

## Report Fields

Every restore drill report carries:

- tenant ID
- object ID and source version ID
- restore status
- storage manifest hash
- source manifest hash
- retention manifest hash
- retention policy snapshot hash
- optional content hash
- optional envelope manifest hash
- optional KMS evidence hash
- optional cryptoshred manifest hash
- optional key-destruction evidence hash
- check list
- requested-by principal
- audit chain reference
- operation time
- report hash

## Rule

A restore drill is not accepted until the report hash can be recomputed from the report payload.
