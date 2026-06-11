# Retention Manifest

Retention is a shared compliance decision, not a background cleanup detail.

The retention manifest is the bridge between source objects, object storage, WORM/Object Lock, Legal Hold, backup/restore, search/vector lifecycle, and e-discovery.

## Files

ADR:

```text
ARCHITECTURE_DECISIONS/ADR-0025-retention-defaults-and-manifest.md
```

Policy:

```text
docs/retention_manifest_policy.json
```

Runtime model:

```text
app/suite/storage/retention.py
```

Storage object manifests consume retention manifests:

```text
app/suite/storage/storage_manifest.py
docs/STORAGE_MANIFEST.md
```

Tests:

```text
tests/test_retention_manifest.py
```

## Manifest Fields

Every retention manifest carries:

- tenant ID
- source object ID
- source object type
- version ID
- classification
- lifecycle state
- retention policy ID
- retention mode
- retention days where fixed retention applies
- retain-from timestamp
- retain-until timestamp where fixed retention applies
- legal-hold state
- disposition after retention
- deletion-blocked state
- WORM requirement
- object-lock mode
- storage bucket profile
- cryptoshred permission before retention end
- audit requirement
- source manifest hash
- policy snapshot hash

## Default Policies

Initial default policies:

- `rp-temporary-7d`
- `rp-standard`
- `rp-restricted`
- `rp-gobd-10y`
- `rp-legal-hold`
- `rp-ai-draft-365d`
- `rp-parser-artifact-90d`
- `rp-embedding-follows-source`
- `rp-export-10y`

These defaults are intentionally conservative. They are not tenant-specific overrides yet.

## Rules

- Active Legal Hold blocks disposition until release.
- Legal Hold placement and release trigger manifest re-evaluation.
- Business records and WORM evidence require WORM-capable policies.
- GoBD and Legal Hold records cannot allow early cryptoshred.
- Embeddings and RAG chunks follow source lifecycle.
- Retention policies must point to known storage bucket profiles.
- Retention manifests carry policy snapshot hashes so restored evidence can be checked against the policy that produced it.
- Storage manifests carry retention manifest hashes so restored object bytes can be checked against the retention decision that governed the write.

## Next Implementation Work

- Persist retention manifests with source object metadata.
- Add tenant-specific retention overrides.
- Add Legal Hold APIs that update objects and trigger manifest re-evaluation.
- Persist Legal Hold decisions and matter scopes.
- Add retention worker simulations before destructive actions exist.
- Persist storage manifests and retention manifests with source object metadata.
- Add object-store restore commands that call storage manifest verification before serving restored bytes.
