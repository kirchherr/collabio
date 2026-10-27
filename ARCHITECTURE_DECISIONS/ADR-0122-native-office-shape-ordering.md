# ADR-0122: Direct ordering of standalone native Office shapes

Status: Accepted
Date: 2026-10-05

## Context

Authors can order images, members inside shape groups and complete shape groups, but a standalone native shape cannot
be moved directly among top-level document blocks. Recreating or grouping it merely to change its document position
is inefficient and risks changing presentation or identity.

## Decision

The shape dialog exposes focusable actions to move an ungrouped selected shape exactly one top-level document
position earlier or later. Each action swaps the complete shape node with its single adjacent top-level node. The
unavailable direction is disabled at the corresponding document boundary. Group members continue to use their
dedicated member-order controls.

The move is one isolated undo transaction and keeps selection on the moved shape. Its stable opaque ID, kind, literal
text, dimensions, colors, stroke, alignment, typography, rotation, wrapping and optional logical position remain
unchanged. The new order becomes durable only through the existing confirmed compare-and-swap version save.
Immutable earlier versions and static print continue to consume their exact stored order and content.

Missing, stale, grouped and read-only targets fail closed with no document mutation. The operation introduces no new
saved field, schema, external content or executable presentation.

## Consequences

Standalone shapes now have the same precise document-order workflow as images and complete shape groups. Arbitrary
drag ordering, multi-position jumps, overlap ordering, arbitrary z-index behavior and DOCX DrawingML interchange
remain separate decisions.
