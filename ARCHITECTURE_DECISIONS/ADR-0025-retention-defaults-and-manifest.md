# ADR-0025: Retention Defaults And Manifest Model

Status: accepted
Date: 2026-06-11

## Context

Source objects, object storage, WORM records, legal holds, backup/restore, vector lifecycle, and e-discovery all depend on the same retention decision. If each subsystem interprets retention independently, the suite will eventually delete too early, keep too long, cryptoshred incorrectly, or produce weak audit evidence.

The suite already has source object metadata, a storage write guard, S3-compatible object-storage bucket profiles, and backup/failover continuity domains. The next step is a shared retention manifest that can be computed, stored, audited, restored, and checked before lifecycle actions run.

## Decision

Define retention defaults and a versioned `RetentionManifest` model.

Machine-readable policy:

```text
docs/retention_manifest_policy.json
```

Schema:

```text
retention_manifest_policy.v1
```

Runtime model:

```text
app/suite/storage/retention.py
```

The retention manifest records:

- tenant, object, source type, version, classification, and lifecycle state
- retention policy ID
- retention mode and retention days
- retain-from and retain-until timestamps where fixed retention applies
- legal-hold state
- disposition after retention
- deletion-blocked state
- WORM and object-lock requirements
- storage bucket profile
- cryptoshred permission before retention end
- audit requirement
- source manifest hash
- policy snapshot hash

Initial retention policy defaults:

- `rp-temporary-7d`
- `rp-standard`
- `rp-restricted`
- `rp-gobd-10y`
- `rp-legal-hold`
- `rp-ai-draft-365d`
- `rp-parser-artifact-90d`
- `rp-embedding-follows-source`
- `rp-export-10y`

Legal hold wins over disposition. GoBD, legal-hold, business-record, and WORM-evidence objects require WORM-capable retention policies. Embeddings and RAG chunks follow the authoritative source lifecycle.

## Consequences

Easier:

- Storage, Legal Hold, lifecycle workers, e-discovery, backup, and restore can share one retention artifact.
- Restore checks can validate source manifest hash, content hash, retention manifest hash, and policy snapshot.
- WORM and Object Lock decisions have a policy source before bucket implementation.
- The future retention worker can evaluate manifests rather than inventing rules.

Harder:

- Policy changes need migration and audit strategy because old manifests carry old policy snapshot hashes.
- Tenant-specific overrides must preserve the conflict-order model.
- The implementation still needs a persistent store and worker before retention is enforceable at runtime.

## Alternatives Considered

### Retention only in source metadata

Rejected because a single `retention_policy_id` does not preserve policy snapshot, retain-until, object-lock requirement, disposition, or restore evidence.

### Retention only in object-store metadata

Rejected because PostgreSQL metadata, legal-hold services, search/vector lifecycle, and e-discovery must reason about retention before object-store calls.

### Implement lifecycle worker before manifest

Rejected because workers without a stable manifest would spread retention logic across code paths.

## Compliance Mapping

- `COMPLIANCE_MATRIX.md`: CM-004, CM-005, CM-006, CM-007
- `DATA_CLASSIFICATION.md`: lifecycle conflict order and deletion semantics
- `LEGAL_HOLD_MODEL.md`: legal hold precedence and release re-evaluation
- `docs/STORAGE_ADAPTER_PLAN.md`: bucket profiles and Object Lock posture
- GoBD: retention and immutability for business records
- DSGVO: policy-based deletion, restriction, and conflict handling
- E-discovery: chain-of-custody and reproducible export evidence

## Verification

- `tests/test_retention_manifest.py` validates defaults, manifest generation, WORM requirements, legal-hold blocking, and ADR/backlog sync.
- `tests/test_storage_adapter_policy.py` validates bucket profiles referenced by retention policies.
- Backup/failover policy includes retention manifest evidence and restore checks.
- Future worker tests must prove that lifecycle actions consume manifests and deny deletion or cryptoshred when policy blocks them.
