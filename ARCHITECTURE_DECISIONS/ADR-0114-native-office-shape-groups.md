# ADR-0114: Bounded native Office shape groups

Status: Accepted
Date: 2026-10-02

## Context

Native shapes support bounded geometry, quarter-turn rotation, logical layers and simple text wrapping. Authors also
need to keep related flow shapes together without introducing arbitrary SVG containers, DrawingML transforms or
overlapping freeform canvases. A group must remain responsive, printable and exactly recoverable.

## Decision

A root-level `shapeGroup` contains two through eight existing `shape` nodes in exact order. At most 20 groups are
allowed per document. The group stores exactly a restricted opaque ID, `layout` (`row` or `stack`) and an integer
`gap` from 0 through 48 pixels. Unknown keys, nested groups, other member types and out-of-range values fail closed.

Grouped members cannot carry free `position` or `wrap`. They retain their own validated kind, text, colors, dimensions,
stroke, alignment and optional quarter-turn rotation. The responsive row layout collapses to one column on narrow
screens. Authors can group a flow shape with an adjacent shape, extend a group, change layout and gap, edit or remove
members, undo or redo the group transaction and dissolve the group.

Comparison, immutable versions, historical reuse, independent copies and static print preserve the exact group ID,
member order, member attributes, layout and gap. Group controls are editor-only and never enter saved or printed
content.

## Consequences

Authors can manage related native shapes as one bounded structural block while every member remains independently
editable. Nested groups, mixed image/shape groups, grouped free positioning, arbitrary group transforms, connectors,
freeform paths and DOCX DrawingML interchange remain separate decisions.
