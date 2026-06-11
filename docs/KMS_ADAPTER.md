# KMS Adapter Boundary

The KMS adapter is the only allowed boundary for key references, key-usage evidence, rotation evidence, and key-destruction evidence.

The current implementation provides the KMS control plane, local development envelope encryption API, and local cryptoshred simulation. Production crypto providers must replace local provider behavior behind the same boundary.

## Files

Runtime model:

```text
app/suite/kms/adapter.py
app/suite/kms/envelope.py
app/suite/kms/cryptoshred.py
```

Policy:

```text
docs/kms_adapter_policy.json
```

Tests:

```text
tests/test_envelope_encryption.py
tests/test_cryptoshred_simulation.py
tests/test_kms_adapter.py
tests/test_source_objects.py
tests/test_storage_manifest.py
tests/test_architecture_guards.py
tests/test_backup_failover.py
```

## Key Reference Format

Canonical key references use:

```text
kms://<tenant_id>/<data_class>/v<positive integer>
```

Examples:

```text
kms://tenant-1/internal/v1
kms://tenant-1/gobd/v1
kms://tenant-1/legal_hold/v1
```

The parser rejects non-`kms://` refs, unknown data classes, malformed versions, non-canonical refs, tenant mismatches, and classification mismatches.

## Boundary Rules

- Business code may pass `kms_key_ref`, never raw key material.
- Source object writes must use a KMS ref matching the source tenant and data class.
- Storage manifests must use KMS refs matching the source tenant and data class.
- KMS and envelope operations produce hashable evidence.
- Envelope encryption manifests must bind ciphertext, AAD, wrapped data key hash, KMS evidence, and content hash.
- Envelope rewrap must consume KMS rotation evidence and produce a new manifest hash without changing object ciphertext.
- Raw key material export is forbidden by policy and evidence validation.
- Key destruction requires human approval evidence.
- Active legal hold blocks key destruction.
- GoBD and legal-hold data classes block key destruction.
- Business-record and WORM-evidence lifecycle states block key destruction.
- Cryptoshred simulation must record that object bytes were not deleted and plaintext key material was not exported.

## Current Adapter

`LocalKmsAdapter` is a development-safe boundary:

- validates key references
- records key-usage evidence
- simulates key-reference rotation by incrementing the version
- records key-destruction evidence for policy-allowed classes
- blocks future use of destroyed key versions

It intentionally does not expose raw keys.

`LocalEnvelopeEncryptionService` is the local development implementation for object-byte encryption. It validates KMS key references, creates envelope encryption manifests, authenticates ciphertext with AAD, rejects tampering, and refuses decryption when the referenced key version has been destroyed.

It also supports envelope rewrap for rotation drills. Rewrap verifies the existing manifest, ciphertext hash, AAD hash, current KMS key reference, and authentication tag before rotating the key reference and replacing only the wrapped data key plus rotation evidence fields.

`LocalCryptoshredSimulator` is the local development implementation for cryptographic shredding drills. It verifies the source object, retention manifest, legal-hold state, protected lifecycle state, and human approval reference before recording KMS key-destruction evidence and producing a cryptoshred manifest.

## Policy

The machine-readable policy declares:

- provider profiles
- required key hierarchy
- forbidden operations
- required evidence fields
- per-data-class rotation and cryptoshred permissions

Every `DataClass` must have a policy entry.

## Evidence

KMS operation evidence includes:

- tenant ID
- data class
- KMS key reference
- key version
- provider profile
- requested-by principal
- optional approver and approval reference
- audit chain reference
- operation time
- key use
- previous/new key references where relevant
- destruction flag where relevant
- evidence hash

The evidence model rejects `raw_key_material_exposed=true`.

## Next Work

The next layer is restore-test framework wiring. Production envelope providers must not introduce direct crypto or provider calls in feature code.
