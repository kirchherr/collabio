# ADR-0127: Direct ordering of native Office image-group members

Status: Accepted
Date: 2026-10-06

## Context

Native image groups preserve an exact ordered sequence, but changing that sequence required dissolving and rebuilding
the group. The existing image movement buttons move the complete group among top-level document nodes, which is a
different operation. Pointer-only dragging would also exclude keyboard and assistive-technology users.

## Decision

The image dialog exposes ordinary focusable buttons that move the selected group member exactly one position earlier
or later in the group's reading order. The earlier action is disabled for the first member and the later action for
the last. Separate controls explicitly name movement of the complete **Bildgruppe** among top-level document nodes
and are disabled at their own boundaries.

A member move swaps only the selected image with its adjacent member, recreates the group with its existing validated
attributes and keeps node selection on the moved image. The complete replacement is dispatched as one isolated undo
transaction. Group ID, layout and gap remain exact, as do every member's asset/version binding, crop, transformation,
alternative text, caption, figure identity and display dimensions. No new saved attribute or external content is
admitted.

Confirmed compare-and-swap save remains the only durable mutation. Immutable history, independently owned copies,
comparison, reload and print consume the existing canonical member sequence. Current server validation therefore
remains authoritative for the unchanged bounded group representation.

## Consequences

Authors can correct image reading and display order directly with keyboard-accessible controls while undo and redo
remain predictable. Drag ordering, overlapping image canvases, arbitrary z-index values, nested or mixed groups,
free-positioned group members and DOCX DrawingML interchange remain separate decisions.
