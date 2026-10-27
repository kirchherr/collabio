# ADR-0124: Independent duplication of native Office image groups

Status: Accepted
Date: 2026-10-05

## Context

Native image groups can be created, arranged, moved, dissolved and removed, but authors cannot reuse a complete
visual unit inside the same document without rebuilding it member by member. Reusing the existing asset identities
would also couple the copy to the source bindings instead of giving the duplicated unit independent ownership.

## Decision

The image-group section exposes a focusable **Bildgruppe duplizieren** action. The server receives two through eight
validated flow-image references for the current document, rechecks current tenant and write authorization, validates
every source against its document-owned immutable bytes and creates a fresh asset and version for every member in one
database transaction. Storage and the existing 200-asset retention bound are checked before any result is returned.

Only after the complete server response has passed client validation does the editor resolve the source group's stable
ID again and insert one copied group immediately after it. The copy receives a fresh opaque group ID and every numbered
member receives a fresh figure ID. Member order, normalized pixels, content hashes, dimensions, crop, transform,
alignment, alternative text, caption and decorative state stay exact. Layout and gap stay exact. The existing limits
of 20 groups, 40 document images and eight group members disable the action before mutation.

Insertion is one isolated undo transaction and becomes document content only through the existing confirmed
compare-and-swap save. A failed, incomplete, stale, unauthorized or invalid response leaves the draft unchanged.
Created image objects follow the existing document retention, legal-hold, receipt, backup and recovery contracts.

## Consequences

Authors can reuse complete image compositions without shared asset or figure identities. The endpoint writes retained
document-owned assets before a later document save, so abandoned copies remain governed by the existing 200-asset
bound until a separately confirmed retention-aware cleanup workflow exists. Nested groups, mixed image/shape groups,
group-wide transforms, physical page anchors and DOCX DrawingML interchange remain separate decisions.
