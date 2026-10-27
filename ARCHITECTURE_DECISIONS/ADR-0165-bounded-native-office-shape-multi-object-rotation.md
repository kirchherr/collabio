# ADR-0165: Bounded native Office shape multi-object rotation

Date: 2026-10-09

Status: Accepted

## Context

Native Office supports transient selection, arrangement, shared layer changes, movement, pointer/touch dragging and
collective resizing for positioned root shapes and complete shape groups. Authors also need one predictable rotation
gesture that preserves the relationships between objects with different starting angles.

## Decision

At least two selected positioned root shapes or complete root groups may rotate through one shared relative integer
angle. The same delta is applied to every standalone shape and every member of a selected group, normalized to the
canonical absence at zero or an integer from 1 through 359. Distinct starting angles therefore remain distinct.

Standalone shapes reuse their rotation handle. Positioned groups expose an equivalent accessible handle for the
multi-selection path. Pointer and touch movement around the active root object's center produces the shortest signed
angle delta; Shift snaps the delta to 15-degree increments. Arrow keys apply one degree, Shift plus an arrow applies
15 degrees, click applies 90 degrees and Home derives the common delta that brings the active source angle to zero.

Live feedback changes editor-owned DOM only and reports the effective signed angle. Pointer cancellation, Escape,
document or session changes, read-only state and stale state restore every original angle without history. The
collective capture path suppresses the individual rotation and following click while it owns the gesture.

Completion rebuilds and validates every affected shape or group before replacing the document in exactly one
transaction and undo unit. A gesture with no effective angle change creates no history. Group attributes, member
order, connections, gap, layer, logical position, dimensions, typography and stable IDs remain unchanged.

Selection, preview and gesture state are transient. Confirmed CAS save, immutable predecessor history, undo/redo,
reload, semantic print/PDF and independent reuse consume only the established rotation values in immutable Office
JSON.

## Consequences

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, arbitrary
transform string, physical page anchor, nested group or DOCX DrawingML admission. The focused model and responsive
desktop/mobile workflows pass 5/5, and the complete native-shape model and responsive matrix pass 35/35. The isolated
review API exposes the feature without changing ordinary tenant or production admission.
