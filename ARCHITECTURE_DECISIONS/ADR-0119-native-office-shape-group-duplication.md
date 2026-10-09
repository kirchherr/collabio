# ADR-0119: Direct duplication of native Office shape groups

Status: Accepted
Date: 2026-10-05

## Context

Repeated process lanes and diagram fragments often reuse a complete group rather than one member. Rebuilding the
group loses time, while copying group or member identities would violate document uniqueness and make later editing
ambiguous.

## Decision

The shape-group section exposes an explicit focusable **Gruppe duplizieren** action for a member of an existing group.
The action creates one new cryptographically random opaque group ID and one new cryptographically random opaque shape
ID for each copied member. Exact member order, layout, gap, optional uniform connection and all validated member
attributes remain unchanged.

The new group is inserted immediately after its source and selected as a unit. The control is disabled before the
document would exceed 20 groups or 100 total shapes. Browser and server validation remain authoritative before the
transaction is dispatched. The complete insertion and selection are one isolated undo transaction.

Confirmed versions, comparison and static print consume both structures independently. No reference, shared identity,
external content, executable presentation or new saved field is introduced.

## Consequences

Authors can reuse complete diagram fragments while editing either copy independently. Cross-document group clipboard,
linked clones, nested groups, bulk duplication, cascade placement and DOCX DrawingML interchange remain separate
decisions.
