# Content Hash Verification

Content hashes are the reusable integrity boundary for storage writes, reads, restore drills, parser inputs, and future export packages.

The rule: no restored or served object bytes are trustworthy until their canonical hash has been verified against authoritative source object metadata.

## Canonical Format

The first supported format is:

```text
sha256:<64 lowercase hex chars>
```

The implementation intentionally rejects unsupported algorithms and malformed digests. Future algorithms can be added through the same parser and verification boundary without changing feature code.

## Verification Boundary

Code:

```text
app/suite/storage/content_hash.py
```

Tests:

```text
tests/test_content_hash.py
tests/test_source_objects.py
tests/test_backup_failover.py
```

`verify_content_hash` returns structured evidence:

- algorithm
- expected hash
- actual hash
- byte length
- verification context
- verified flag

The verification context names why bytes were checked, for example:

- `source_object_write`
- `read`
- `restore`
- `export`
- `parser_input`

This makes the same primitive usable by storage adapters, restore commands, parser workers, and e-discovery exports.

Storage manifest verification consumes this result and records it as restore evidence.

## Source Object Integration

`SourceObjectWriteGuard` now calls the shared verifier before accepting source object records.

The guard still rejects writes when:

- required compliance metadata is missing
- `kms_key_ref` does not use `kms://`
- `content_hash` is malformed or does not match the stored bytes
- `manifest_hash` no longer matches canonical metadata

## Restore Rule

Object restore must verify content before serving data back to any feature:

```text
restored object bytes
  -> source object metadata lookup
  -> verify_content_hash(context="restore")
  -> manifest verification
  -> retention/legal-hold/KMS checks
  -> controlled read/export path
```

If hash verification fails, the restore is evidence of corruption or mismatch and must not be promoted.

## Continuity

The backup/failover policy tracks this as `content_hash_verifier_check` for object storage records.

Any future storage, office, mail, parser, or e-discovery path that creates durable bytes must either use this verifier directly or document a stricter equivalent.
