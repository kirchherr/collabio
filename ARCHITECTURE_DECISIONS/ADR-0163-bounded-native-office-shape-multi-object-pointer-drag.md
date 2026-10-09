# ADR-0163: Bounded native Office shape multi-object pointer drag

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office may move the positioned root objects in the transient selection established by ADR-0160 through one
mouse or touch gesture. The gesture begins only on the position anchor of an already selected standalone shape or
complete shape group. At least two fully positioned roots are required. Normal-flow and wrapped objects remain
ineligible and never receive a position implicitly.

Horizontal pointer movement is converted to the existing integer X scale from the current editor width. Vertical
movement uses an integer pixel delta. The complete gesture uses one shared X/Y delta. Both axes are clamped against
the intersection of all selected anchor ranges, so the selection stops as a unit at X 0 through 1000 and Y -1200
through 1200 while preserving relative geometry, stable IDs, layers and document order.

Every selected object follows a live DOM-only preview. The status announces the effective X/Y delta, selected roots
show a common dragging marker and their anchors identify that mouse or touch moves the whole selection. The preview
does not enter immutable Office JSON or history.

Pointer cancellation, Escape, a changed document or session, a non-writable state and invalid input restore the
original preview without a transaction. A completed gesture with no effective movement also creates no history.
The multi-selection capture path suppresses the individual anchor drag and its following click for that gesture.

On pointer release the implementation resolves every selected ID against the unchanged current document, validates
the complete candidate and dispatches exactly one ProseMirror transaction and undo unit. Confirmed CAS save,
immutable predecessor history, reload, semantic print/PDF and independent reuse preserve only the resulting
established positions; selection and drag state remain transient.

This decision adds no relational migration, endpoint, dependency, external request, provider, worker, recovery
store, persisted selection, free coordinate field, physical page anchor, rendered-edge geometry, nested group or
DOCX DrawingML admission.

Acceptance requires pure dual-axis boundary checks plus responsive desktop and mobile workflows covering accessible
anchors, mouse and touch pointer types, live preview, cancellation, one-step undo/redo, confirmed save, immutable
predecessor history, semantic print, reload clearing and independent reuse, followed by the complete native-shape
regression matrix.
