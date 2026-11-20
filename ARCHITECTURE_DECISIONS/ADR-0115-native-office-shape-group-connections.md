# ADR-0115: Bounded connections inside native Office shape groups

Status: Accepted
Date: 2026-10-02

## Context

Bounded shape groups preserve ordered flow shapes in responsive rows or stacks. Simple process and organization
diagrams also need a visible relationship between consecutive members. Arbitrary connector endpoints, SVG paths,
freeform routing and executable styling would weaken validation, responsive behavior and print fidelity.

## Decision

A shape group may optionally store `connection` with exactly `kind` (`line`, `arrow` or `doubleArrow`), `color`
(`slate`, `red`, `green`, `teal`, `blue`, `purple` or `black`) and integer `width` from 1 through 8 pixels. Absence is
the canonical unconnected group. Unknown keys, arbitrary colors, paths, endpoint IDs, URLs, CSS and out-of-range or
boolean widths fail closed in browser and server validation.

The connection applies uniformly between each consecutive pair in the group's exact member order. Row groups render
horizontal connections; stack groups and compact row fallback render vertical connections. The editor dialog exposes
explicit connection type, color and width controls and disables color and width when no connection is selected.

Comparison, accessible group descriptions, isolated undo, immutable versions, historical reuse, independent copies
and static print preserve the exact connection. The connection uses trusted product CSS only and stores no markup,
path commands or executable presentation.

## Consequences

Authors can create bounded flow and organization diagrams that stay responsive and printable. Per-edge styles,
arbitrary endpoints, curved or orthogonal routing, connectors outside a group, mixed image/shape graphs, overlapping
canvases and DOCX DrawingML interchange remain separate decisions.
