# Envelope Encryption API

Envelope encryption is the object-byte encryption boundary on top of the KMS adapter.

The current implementation is a local development adapter and evidence model. It is not the final production crypto provider. Production providers must replace the local implementation behind the same API and evidence contracts.

## Files

Runtime model:

```text
app/suite/kms/envelope.py
```

Tests:

```text
tests/test_envelope_encryption.py
tests/test_kms_adapter.py
tests/test_architecture_guards.py
tests/test_backup_failover.py
```

Related docs:

```text
docs/KMS_ADAPTER.md
docs/STORAGE_MANIFEST.md
docs/operations/BACKUP_FAILOVER.md
```

## Boundary Rule

No feature code may encrypt, decrypt, wrap, unwrap, or export keys directly.

Allowed path:

```text
source bytes
  -> KMS key reference validation
  -> envelope encryption service
  -> envelope encryption manifest
  -> storage object manifest
  -> object storage adapter
```

Restore path:

```text
encrypted object bytes
  -> storage manifest verification
  -> envelope manifest verification
  -> KMS key reference validation
  -> authenticated decrypt
  -> content hash verification
  -> controlled read/export/index path
```

## Manifest Fields

Every envelope encryption manifest carries:

- tenant ID
- object ID
- source version ID
- data class
- KMS key reference
- encryption algorithm
- key-wrap algorithm
- nonce
- AAD hash
- plaintext hash
- ciphertext hash
- ciphertext byte length
- wrapped data key
- wrapped data key hash
- KMS evidence hash
- encryption timestamp
- requested-by principal
- audit chain reference
- manifest hash

The manifest never carries raw data keys, plaintext keys, provider master keys, or other raw key material.

## AAD

Additional authenticated data binds encryption to the surrounding evidence, for example:

```text
storage_manifest_hash
tenant_id
object_id
source_version_id
data_class
kms_key_ref
```

If AAD changes, decryption fails.

## Local Development Adapter

`LocalEnvelopeEncryptionService` provides deterministic tests for:

- KMS key-reference validation
- ciphertext authentication
- AAD mismatch rejection
- manifest tamper detection
- destroyed key rejection
- no raw key exposure in manifests or KMS evidence

This implementation is intentionally scoped to development and tests. Production must use an approved KMS/HSM/cloud/OpenBao-compatible provider behind this boundary.

## Continuity

Backup/failover evidence must include:

- envelope encryption manifest hash
- wrapped data key hash
- KMS evidence hash
- ciphertext hash
- AAD hash
- KMS provider profile
- no-plaintext-key-export check
