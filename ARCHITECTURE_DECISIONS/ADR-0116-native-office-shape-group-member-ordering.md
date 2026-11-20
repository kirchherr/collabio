# ADR-0116: Direct ordering of native Office shape-group members

Status: Accepted
Date: 2026-10-05

## Context

Native shape groups already preserve an exact ordered sequence, but changing that sequence required dissolving and
recreating the group. A drag-only solution would exclude keyboard and assistive-technology users, while introducing
arbitrary overlap order would conflate reading order with visual layers.

## Decision

The shape dialog exposes explicit controls that move the selected group member exactly one position earlier or later
in the group's reading order. The earlier control is disabled for the first member and the later control for the last.
Both are ordinary focusable buttons and remain usable without pointer dragging.

A move swaps only the selected shape with its adjacent member, recreates the group with its existing validated
attributes and keeps node selection on the moved shape. The complete replacement is dispatched as one isolated undo
transaction. Existing group ID, layout, gap and optional uniform connection remain exact, as do all validated member
attributes. No new saved attribute, markup or external content is admitted.

Immutable versions, historical reuse, independent copies, comparison and print consume the already canonical member
sequence. Server validation therefore remains the authority for the unchanged bounded group representation.

## Consequences

Authors can correct diagram reading order directly and accessibly while undo and redo remain predictable. Freeform
drag ordering, overlapping canvases, arbitrary z-index values, nested or mixed groups, per-edge connector routing and
DOCX DrawingML interchange remain separate decisions.
