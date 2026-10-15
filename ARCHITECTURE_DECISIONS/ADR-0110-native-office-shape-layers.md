# ADR-0110: Bounded anchored native Office shape layers

Status: Accepted
Date: 2026-10-02

## Context

Roadmap 292 introduced inert native shapes in normal document flow. Authors also need callouts and simple background
elements that can sit in front of or behind nearby text. Arbitrary CSS positioning or physical page coordinates would
create active layout input and would not remain stable across responsive editor widths, print profiles and future
pagination.

## Decision

A native shape may optionally store one bounded logical anchor with exactly `layer`, `x` and `y`. Layer is `front` or
`behind`; horizontal position is an integer from 0 through 1,000 relative to the current content width, and vertical
offset is an integer from -1,200 through 1,200 pixels relative to the shape's document boundary. Unknown keys,
nonintegers, arbitrary CSS units and out-of-range coordinates fail in both browser and server validation. Omitting the
anchor is the canonical normal-flow representation.

The shape dialog switches explicitly among normal flow, front and behind layers. Positioned shapes expose a separate
keyboard- and pointer-operable anchor above document content even when the shape itself is behind text. Pointer,
touch and arrow-key movement clamp to the same bounds and commit one isolated undo transaction. Comparison, immutable
history, independent copies and print preserve the exact logical anchor. Responsive rendering recomputes horizontal
placement from the available content width rather than storing device pixels.

## Consequences

Authors can place bounded callouts and background shapes without admitting executable style or remote content. The
logical anchor is not a physical page coordinate and makes no pagination promise. Text wrap contours, arbitrary
overlap ordering, connectors, grouped shapes, freehand paths, rotation and DOCX DrawingML anchors remain separate
decisions.
