# ADR-0003: KMS Key Hierarchy And Crypto Boundary

Status: accepted
Date: 2026-06-10

## Context

The suite must support tenant isolation, data-class separation, key rotation, cryptographic agility, legal hold, retention, and evidence workflows. Direct cryptographic calls in business logic would make this impossible to control and audit.

## Decision

All cryptographic operations must go through a KMS/crypto adapter boundary.

Target key hierarchy:

```text
root-of-trust
  -> tenant master key
    -> data-class key
      -> object encryption key
        -> version key / envelope key
```

Business services may store and pass key references, but never raw key material.

Cryptographic shredding is policy-controlled and must be blocked for active Legal Hold and GoBD-retained records.

The first implementation is a KMS adapter boundary with canonical `kms://<tenant>/<data_class>/v<version>` references, per-data-class policy, hashable operation evidence, rotation evidence, and destruction guards. Envelope encryption is intentionally the next layer, not mixed into the boundary.

## Consequences

- The codebase needs a KMS adapter even before production KMS selection.
- Key usage must be auditable.
- Rotation must be tested before business records depend on it.
- Local dev can use a software KMS/mock, but production adapters must support stronger backends.

## Alternatives Considered

- Direct use of crypto libraries in each service: rejected due to audit and agility risk.
- One tenant-wide key only: rejected because data-class and object lifecycle requirements need finer control.
- Cryptoshred as universal deletion: rejected because GoBD and Legal Hold can override deletion.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-003, CM-004, CM-005, CM-008
- DSGVO: security of processing, deletion/restriction workflows
- BSI TR-02102: cryptographic procedure reference
- NIST CSF 2.0: Protect

## Verification

- Tests fail if business code imports forbidden crypto primitives directly after the adapter exists.
- KMS policy tests cover all data classes and forbidden operations.
- Source object and storage manifest tests reject tenant/data-class mismatched KMS refs.
- Key rotation test preserves readability.
- Key destruction simulation makes allowed objects unreadable.
- Legal Hold and GoBD tests block forbidden cryptoshred.
