# ADR-0113: Bounded text wrapping around native Office shapes

Status: Accepted
Date: 2026-10-02

## Context

Native shapes can remain in normal flow or use bounded logical front/behind positioning. Authors also need simple
callouts that sit beside following paragraph text. Arbitrary CSS floats, contour paths or simultaneous free positioning
and wrapping would create ambiguous layout state and weaken responsive and print behavior.

## Decision

A native shape may optionally store `wrap` with exactly `side` (`left` or `right`) and integer `gap` from 0 through 48
pixels. Wrapping and the optional free `position` are mutually exclusive in browser and server validation. Unknown
keys, booleans, arbitrary units and out-of-range gaps fail closed. Absence remains the canonical block-flow form.

The shape dialog offers explicit no-wrap, shape-left and shape-right choices and disables wrapping while a free layer
is selected. Choosing a free layer clears wrap in the draft. Wrapped shapes occupy at most 45 percent of the available
text width and are additionally bounded to a 480-pixel visual height. At narrow container widths they return to a
full-width block so text and controls remain usable.

Rotation, direct resizing and literal shape text remain independent canonical attributes. Comparison, isolated undo,
immutable versions, historical reads, independent copies and print preserve the exact side and gap.

## Consequences

Authors can create bounded left/right callouts without executable styling or physical page coordinates. Arbitrary
wrap contours, through/tight wrapping, overlap ordering, simultaneous free positioning, grouped shapes, connectors
and DOCX DrawingML interchange remain separate decisions.
