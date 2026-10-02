# ADR-0108: Bounded native image groups

Status: Accepted
Date: 2026-10-01

## Context

Native Office images already support document-owned renditions, crop, text wrapping, anchored layers and bounded
transforms. Users also need to arrange several related images as one movable and printable unit. Persisting arbitrary
HTML containers, CSS layout or overlapping drawing canvases would expand the active-format surface and make narrow
layouts, history, copying and recovery ambiguous.

## Decision

A document may contain at most 20 native `imageGroup` block nodes. Each group contains two through eight existing
native image nodes, has an opaque `image-group-` identifier, chooses exactly `row` or `stack`, and stores an integer
gap from 0 through 48 pixels. Group identifiers are unique within the document. Unknown keys, nested groups, duplicate
members, active attributes and grouped images with text wrapping or free positioning fail before persistence.

The editor can group an image with its adjacent image, extend a group with an adjacent image, switch row/stack layout,
change the bounded gap and dissolve the group without changing its images. Removing the penultimate member unwraps
the remaining image. Moving a grouped image moves the whole group. A dedicated group control selects the stable group
node and the image dialog derives the first member for editing, so Undo/Redo cannot leave a fragile nested selection.
Every command is one isolated undo transaction; only an explicit confirmed CAS save appends an immutable version.

Wide row groups use equal responsive columns. Compact row groups collapse to one column, while explicit stack groups
remain vertical. Print, comparison, history and independent document copies preserve the group and its exact member
order. Copying still creates independently owned image assets. Recovery requires consecutive row/gap-12,
stack/gap-24 and dissolved versions of the same three exact image versions.

## Consequences

Users can create bounded galleries and move, save, print, copy and recover them as native document structure without
introducing executable layout content or changing source pixels. Freeform overlapping canvases, shapes, connectors,
arbitrary group nesting, wrap contours, absolute physical-page anchors and DOCX drawing-group interchange require
separate decisions and measured fidelity work.
