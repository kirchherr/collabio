# ADR-0161: Bounded native Office shape multi-object arrangement

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office may align or equally distribute the positioned root objects in the transient selection established by
ADR-0160. Eligible objects are standalone shapes and complete shape groups with an existing validated logical
position. Alignment requires at least two selected roots and distribution requires at least three. A selection that
contains a normal-flow or wrapped object remains ineligible; the editor never assigns a position implicitly.

Horizontal alignment sets every selected X anchor to the minimum, rounded midpoint or maximum selected X value.
Vertical alignment applies the equivalent rule to Y anchors. Equal horizontal or vertical distribution keeps the
two extreme anchors fixed and interpolates bounded integer anchor values between them. Sorting is deterministic by
the active coordinate, root document order and stable object ID, so equal starting coordinates cannot produce an
ambiguous result.

These operations use the canonical logical anchors only: normalized integer X values from 0 through 1000 and integer
Y offsets from -1200 through 1200 pixels. They do not inspect DOM rectangles, rendered edges, arbitrary CSS or
physical page geometry. The untouched coordinate and front/behind-text layer remain unchanged for every object.

The responsive toolbar exposes six alignment choices and horizontal or vertical distribution. Controls remain
disabled for an insufficient or ineligible selection. Every accepted operation resolves all selected IDs against the
current document, validates the complete candidate and dispatches exactly one ProseMirror transaction and history
unit. Selection identities remain active after the mutation, while document, version and session changes continue to
clear the transient state.

Only the resulting established shape and shape-group positions enter the immutable Office JSON. Confirmed CAS save,
predecessor history, reload, semantic print/PDF and independent reuse preserve those positions. Browser validation
checks the complete candidate before dispatch and the server validates it again on save. Read-only, historical,
saving, uncertain and stale sessions cannot execute an arrangement action.

This decision adds no relational migration, endpoint, dependency, external request, provider, worker, recovery
store, persisted selection, physical page anchor, rendered-edge alignment, nested group, arbitrary geometry or DOCX
DrawingML admission.

Acceptance requires pure deterministic model checks plus responsive desktop/mobile workflows covering alignment,
distribution, one-step undo/redo, confirmed save, immutable predecessor history, semantic print, reload clearing and
independent reuse, followed by the complete native-shape regression matrix.
