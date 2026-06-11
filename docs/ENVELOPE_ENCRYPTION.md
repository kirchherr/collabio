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
- previous manifest hash, when rewrapped
- previous KMS key reference, when rewrapped
- rotation evidence hash, when rewrapped
- rotation timestamp and reason, when rewrapped
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
```

The wrapping KMS key reference is intentionally not part of the canonical AAD. The manifest and request still require the KMS key reference to match, but excluding it from AAD lets the service rotate the wrapped data key without re-encrypting object bytes.

If AAD changes, decryption and rewrap fail.

## Key Rotation And Rewrap

Envelope rewrap rotates the KMS key reference for an already encrypted object without changing ciphertext, nonce, plaintext hash, ciphertext hash, or AAD hash.

The rewrap path is:

```text
encrypted object bytes
  -> envelope manifest hash verification
  -> AAD and ciphertext hash verification
  -> current KMS key reference validation
  -> ciphertext authentication with current wrapped data key
  -> KMS rotation evidence
  -> data key rewrapped under new KMS key reference
  -> new envelope manifest hash
```

The rewrapped manifest records the previous manifest hash, the previous KMS key reference, the new KMS key reference, the rotation evidence hash, the new wrapped data key hash, the rewrap timestamp, and the rotation reason. Destroyed current key versions cannot be rewrapped.

## Local Development Adapter

`LocalEnvelopeEncryptionService` provides deterministic tests for:

- KMS key-reference validation
- ciphertext authentication
- AAD mismatch rejection
- manifest tamper detection
- destroyed key rejection
- key rewrap with rotation evidence
- no raw key exposure in manifests or KMS evidence

This implementation is intentionally scoped to development and tests. Production must use an approved KMS/HSM/cloud/OpenBao-compatible provider behind this boundary.

## Continuity

Backup/failover evidence must include:

- envelope encryption manifest hash
- wrapped data key hash
- rewrapped data key hash
- KMS evidence hash
- rotation evidence hash
- ciphertext hash
- AAD hash
- KMS provider profile
- no-plaintext-key-export check
