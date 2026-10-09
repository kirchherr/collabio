# ADR-0106: Bounded anchored image layers

Status: Accepted
Date: 2026-10-01

## Context

Native images support document ownership, crop and bounded paragraph wrapping, but cannot be placed over or behind
text. Storing browser CSS or simulated page coordinates would create an active-format surface and would be unstable
because the editor does not yet implement continuous physical pagination.

## Decision

An image may optionally store exactly `position = {layer, x, y}`. `layer` is `front` or `behind`, `x` is an integer
from 0 through 1000 across the current text column, and `y` is an integer offset from -1200 through 1200 CSS pixels
relative to the ordered image anchor. `position` and `wrap` are mutually exclusive. Unknown keys, strings, booleans,
fractions, arbitrary CSS and out-of-range values fail before persistence.

The editor keeps an accessible anchor control above both layers. It supports pointer/touch dragging, arrow-key movement,
larger Shift-key steps and exact numeric fields. Every completed move is one isolated undo transaction. Horizontal
placement translates by the same percentage as its origin, keeping the figure inside the available column. Text and
other blocks sit above `behind`; `front` sits above them. The stacking rule is scoped to containers that actually hold
a positioned image so ordinary wrapping remains clickable.

Printing renders the same inert attributes. Comparison, immutable versions, owned copies and recovery retain exact
coordinates. Reset omits the optional property and therefore preserves legacy canonical bytes. Current document and
image authorization, immutable asset identity, confirmed CAS saving and print-time image reauthorization remain
unchanged.

## Consequences

Users gain foreground/background and free anchored placement without remote resources, scriptable style values or a
new database schema. Placement follows its logical document anchor when preceding content changes. Absolute physical
page anchors, wrap contours, rotation, grouping, continuous editor pagination and DOCX anchor interchange require
separate decisions and measured fidelity work.
