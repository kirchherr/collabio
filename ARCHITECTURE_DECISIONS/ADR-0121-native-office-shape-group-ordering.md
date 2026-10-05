# ADR-0121: Direct ordering of native Office shape groups

Status: Accepted
Date: 2026-10-05

## Context

Authors can edit, duplicate and remove a complete native shape group, but changing its position among top-level
document blocks still requires dissolving and recreating the group. That loses the concise intent of moving one
diagram fragment and creates avoidable intermediate states.

## Decision

The shape-group section exposes focusable actions to move the selected group exactly one top-level document position
earlier or later. Each action resolves the group's validated opaque ID against the current editor document at
activation time and swaps the complete group node with its single adjacent top-level node. Controls are disabled at
the corresponding document boundary.

The move is one isolated undo transaction and keeps selection on the moved group. Group identity, member identities,
member order, layout, gap, optional uniform connection and every member attribute remain unchanged. The new order
becomes durable only through the existing confirmed compare-and-swap version save. Immutable earlier versions and
static print continue to consume their exact stored order and content.

Missing, stale and read-only targets fail closed with no document mutation. The operation introduces no new saved
field, schema, external content or executable presentation.

## Consequences

Authors can place a complete diagram fragment precisely among paragraphs and other document blocks without
reconstructing it. Arbitrary drag ordering, multi-position jumps, nested groups, overlap ordering, arbitrary z-index
behavior and DOCX DrawingML interchange remain separate decisions.
