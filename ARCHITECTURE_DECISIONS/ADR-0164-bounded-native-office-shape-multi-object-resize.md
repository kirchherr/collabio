# ADR-0164: Bounded native Office shape multi-object resize

Date: 2026-10-09

Status: Accepted

## Context

Native Office already supports transient selection, arrangement, shared layer changes, keyboard movement and
pointer/touch dragging for positioned root shapes and complete shape groups. Authors also need to resize the selected
objects as one operation without introducing arbitrary CSS geometry, implicit positioning or separate partial writes.

## Decision

At least two selected positioned root shapes or complete root groups may be resized from the resize handle of any
selected object. Standalone shapes reuse their existing handle; positioned groups expose an equivalent accessible
handle. Normal-flow and wrapped objects remain ineligible and are never positioned implicitly.

The source handle derives common X and Y scale factors on a fixed base of 1000. Pointer and touch gestures may scale
the axes independently; holding Shift applies one common aspect-locked factor. Arrow keys change the corresponding
source dimension by one pixel and Shift plus an arrow by ten pixels. The implementation intersects the legal scale
range of every member before applying it, so all widths remain 80 through 1200 and all heights remain 40 through 800.

Live feedback changes editor-owned DOM only and reports the effective percentages. Pointer cancellation, Escape,
document or session changes, read-only state and stale state restore the original dimensions without a transaction.
Individual resize and click handlers are suppressed while a collective gesture owns the handle.

Completion rebuilds and validates every affected shape or group before replacing the document in exactly one
transaction and undo unit. A gesture with no effective dimension change creates no history. Group attributes,
member order, connections, gap, layer, logical position, rotation, typography and stable IDs are preserved.

Selection, preview and gesture state are transient. Confirmed CAS save, immutable predecessor history, undo/redo,
reload, semantic print/PDF and independent reuse consume only the established shape dimensions already present in
the immutable Office JSON.

## Consequences

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, free CSS
value, physical page anchor, nested group or DOCX DrawingML admission. The pure model and focused responsive
desktop/mobile workflow pass 5/5, and the complete native-shape model and responsive matrix pass 34/34. The isolated
review API exposes the feature without changing ordinary tenant or production admission.
