# ADR-0026: Legal Hold API And Retention Re-Evaluation

Status: accepted
Date: 2026-06-11

## Context

Legal Hold cannot remain a UI flag or a manual metadata edit. It must create auditable source object versions, block destructive lifecycle actions, and trigger retention-manifest re-evaluation. The suite already has source object metadata, a write guard, storage bucket profiles, and a `RetentionManifest` model.

The next step is an API/service boundary that turns hold placement and release into controlled source object transitions.

## Decision

Introduce `LegalHoldService` as the first legal-hold API boundary for source objects.

Runtime model:

```text
app/suite/storage/legal_hold.py
```

The service supports:

- `PlaceLegalHoldCommand`
- `ReleaseLegalHoldCommand`
- `LegalHoldDecision`

Both placement and release:

- require tenant, object, source version, new version, hold ID, matter ID, requester, approver, audit reference, and UTC timestamp
- create a new immutable source object version
- rebuild the source object manifest hash
- write through the guarded source object repository
- rebuild a `RetentionManifest`
- return structured decision evidence

Legal Hold placement sets `legal_hold_state=active`. Legal Hold release sets `legal_hold_state=none` and requires an explicit next retention policy so lifecycle can be re-evaluated instead of silently deleting or retaining data forever.

## Consequences

Easier:

- Hold placement and release are versioned and auditable.
- Retention-manifest re-evaluation happens in the same boundary as the hold transition.
- Future API endpoints, workers, and admin UI can use one service instead of duplicating hold logic.
- Legal Hold can later be connected to matter/case management and outbox/audit persistence.

Harder:

- The service still needs persistent source object metadata and durable audit/outbox integration.
- Release workflow needs role, approval, and matter-state checks before production.
- Active holds on working data may require storage promotion or stricter bucket behavior once object storage is implemented.

## Alternatives Considered

### Directly update source object metadata

Rejected because silent mutation weakens auditability and makes restore evidence ambiguous.

### Only change retention policy ID

Rejected because legal hold state and matter evidence must be explicit and searchable.

### Delay Legal Hold until full e-discovery

Rejected because storage, retention, KMS, search, RAG, and export all need hold semantics before product surfaces are built.

## Compliance Mapping

- `LEGAL_HOLD_MODEL.md`: hold placement, release, and lifecycle re-evaluation.
- `docs/RETENTION_MANIFEST.md`: retention-manifest recomputation.
- `docs/SOURCE_OBJECT_MODEL.md`: versioned source object metadata and manifest hash.
- `COMPLIANCE_MATRIX.md`: CM-004, CM-005, CM-006, CM-007.
- GoBD: held or retained records cannot be deleted early.
- DSGVO: deletion/restriction requests must respect legal hold and retention conflict order.
- E-discovery: matter-linked hold evidence and chain-of-custody preparation.

## Verification

- `tests/test_legal_hold_service.py` validates hold placement, release, new source versions, manifest rehashing, retention-manifest re-evaluation, and invalid transition rejection.
- `tests/test_retention_manifest.py` validates active hold disposition blocking.
- Future API tests must verify role checks, four-eyes approval, audit/outbox events, and matter-scoped hold release.
