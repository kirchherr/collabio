# ADR-0112: Bounded quarter-turn rotation of native Office shapes

Status: Accepted
Date: 2026-10-02

## Context

Roadmaps 292 through 294 provide inert native shapes, bounded logical layers and direct resizing. Authors also need to
change a shape's orientation without admitting arbitrary transform strings, matrices or free-angle geometry. Rotation
must remain stable across the responsive editor, immutable versions, comparison, copies and print.

## Decision

A native shape may optionally store `rotation` with the exact integer value 90, 180 or 270. Zero degrees is the
canonical absence of the attribute. Unknown keys, booleans, arbitrary angles, strings and explicit zero fail in both
browser and server validation.

The shape dialog exposes the four user choices, while a separate focusable **90° drehen** button advances the selected
shape clockwise and wraps 270 degrees back to the canonical unrotated state. Each direct rotation commits one isolated
undo transaction. The accessible shape description includes a nonzero angle.

Rotation applies to the complete inert shape, including its literal text. For normal-flow 90- and 270-degree shapes,
the editor reserves the responsive transposed outer bounds. Positioned shapes retain their logical anchor, layer and
canonical width/height. Comparison, immutable history, independent copies and print preserve the exact angle.

## Consequences

Authors gain predictable orientation changes with a small auditable value set and no executable styling surface.
Arbitrary angles, transform matrices, separate text rotation, rotation handles, grouped shapes, connectors, wrap
contours and DOCX DrawingML interchange remain separate decisions.
