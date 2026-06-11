# Legal Hold API

Legal Hold is a controlled source object transition.

It is not a UI flag and not a direct metadata update. Every hold placement or release creates a new source object version, rebuilds the source object manifest hash, and re-evaluates retention.

## Files

ADR:

```text
ARCHITECTURE_DECISIONS/ADR-0026-legal-hold-api-and-reevaluation.md
```

Runtime model:

```text
app/suite/storage/legal_hold.py
```

Tests:

```text
tests/test_legal_hold_service.py
```

## Commands

`PlaceLegalHoldCommand` requires:

- tenant ID
- object ID
- source version ID
- new version ID
- hold ID
- matter ID
- reason
- requested by
- approved by
- audit chain reference
- occurred-at UTC timestamp

`ReleaseLegalHoldCommand` requires the same fields plus:

- release reason
- next retention policy ID

The next retention policy ID is explicit because releasing a hold does not mean deleting data. It means lifecycle must be re-evaluated under the correct post-release retention policy.

## Decision Evidence

`LegalHoldDecision` returns:

- action
- tenant ID
- object ID
- hold ID
- matter ID
- previous version ID
- new version ID
- audit chain reference
- new source object record
- re-evaluated retention manifest

## Rules

- Hold placement requires a new source object version.
- Hold release requires a new source object version.
- Hold placement is rejected if the object is already under active hold.
- Hold release is rejected unless the object is under active hold.
- Legal Hold state changes must rebuild the source object manifest hash.
- Active Legal Hold blocks deletion, cryptoshred, and retention disposition.
- Release triggers retention-manifest re-evaluation instead of deletion.

## Future API Work

- Persist legal matters and hold scopes.
- Add role and four-eyes approval checks.
- Emit durable audit and outbox events.
- Add matter-scoped search/export controls.
- Connect hold placement and release to object-storage legal-hold/Object Lock behavior.
