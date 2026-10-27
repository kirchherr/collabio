# ADR-0162: Bounded native Office shape multi-object layer and nudge

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office may change the front/behind-text layer or move the logical anchors of the positioned root objects in
the transient selection established by ADR-0160. Eligible objects are standalone shapes and complete shape groups
with existing validated positions. Every operation requires at least two eligible roots. A selection containing a
normal-flow or wrapped object remains ineligible and never receives a position implicitly.

The common layer control writes exactly `front` or `behind` to every selected position while preserving both
coordinates. Arrow keys move all selected anchors by one logical unit; Shift plus an arrow moves them by ten. Four
responsive direction buttons expose one-unit movement to pointer and touch users and provide explicit accessible
names. Keyboard movement is intercepted only while the editor or multi-selection tools have focus and no dialog or
text-entry control owns the key event.

Movement derives one shared bounded delta for the complete selection. The delta is clamped against the intersection
of all permitted anchor ranges: X remains from 0 through 1000 and Y from -1200 through 1200. If any selected object
has reached the requested boundary, the complete selection stops. Relative anchor distances, stable IDs, object
order and every layer remain unchanged.

Every accepted layer or movement action resolves all selected IDs against the current document, validates the
complete candidate and dispatches exactly one ProseMirror transaction and history unit. The transient selection
remains active after the mutation. Read-only, historical, saving, uncertain and stale sessions cannot execute these
actions, and document, version and session changes continue to clear selection state.

Only resulting established shape and shape-group positions enter immutable Office JSON. Confirmed CAS save,
predecessor history, reload, semantic print/PDF and independent reuse preserve them. Browser validation checks the
complete candidate before dispatch and the server validates it again on save.

This decision adds no relational migration, endpoint, dependency, external request, provider, worker, recovery
store, persisted selection, arbitrary movement value, physical page anchor, rendered-edge geometry, nested group or
DOCX DrawingML admission.

Acceptance requires pure bounded-model checks plus responsive desktop/mobile workflows covering common layer,
one-unit and ten-unit keyboard movement, boundary preservation, one-step undo/redo, confirmed save, immutable
predecessor history, semantic print, reload clearing and independent reuse, followed by the complete native-shape
regression matrix.
