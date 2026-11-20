# ADR-0111: Bounded direct resizing of native Office shapes

Status: Accepted
Date: 2026-10-02

## Context

Roadmaps 292 and 293 introduced bounded inert shapes and optional logical front/behind anchors. Authors could set exact
dimensions in the shape dialog, but ordinary visual editing also needs a direct way to resize the selected shape.
Unbounded browser geometry, arbitrary transforms or a stream of history entries during pointer movement would weaken
the existing canonical shape and undo contracts.

## Decision

Every selected native shape exposes a separate visible resize control. It works for normal-flow, front-layer and
behind-layer shapes. Pointer or touch movement previews width and height directly, clamps them to the existing
80–1,200 pixel width and 40–800 pixel height limits, and commits only the final dimensions as one isolated undo
transaction. Pointer cancellation restores the previous rendered dimensions without a document change.

The control is a focusable button with its current dimensions in the accessible name. Arrow keys change the relevant
dimension by one pixel; Shift plus an arrow changes it by ten pixels. Keyboard changes use the same canonical
validation and each commit remains independently undoable. The control is editor UI only and is absent from saved
content, comparison and print.

No schema extension is introduced. Saved width and height remain the existing bounded integer shape attributes, and
server validation continues to reject unknown keys and out-of-range values. Immutable history, independently owned
copies and print therefore preserve the same canonical shape representation.

## Consequences

Authors can resize a shape without reopening the dialog, including when the shape itself sits behind text. Direct
resizing remains responsive: the stored logical dimensions may render smaller when the available editor or print
width is narrower. Aspect locking, rotation, grouped shapes, connectors, arbitrary transforms, text-wrap contours and
DOCX DrawingML interchange remain separate decisions.
