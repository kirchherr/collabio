# ADR-0167: Bounded native Office shape multi-object appearance

Date: 2026-10-09

Status: Accepted

## Context

Native Office supports transient root-object multi-selection and collective positioning, size, rotation, layer and
exact transform operations. Authors also need to apply established visual attributes to several shapes without
repeating the same dialog interaction and creating a separate undo unit for every object.

## Decision

Two through twenty selected root standalone shapes or complete root shape groups may be formatted through one modal
inspector. Eligibility includes established positioned and normal-flow roots. Mixed object kinds, partial groups,
nested groups and stale or non-writable selections fail closed.

The command accepts exactly seven keys. Fill and stroke are null or an established shape color. Stroke width is null
or an integer from zero through eight. Font size is null or an integer from 10 through 72; the canonical 16-point
default is omitted. Text color is null, `auto` or an established text color. Text style is null, `normal`, `bold`,
`italic` or `bold-italic`; normal is omitted. Text alignment is null, `left`, `center` or `right`; left is omitted.
Null means unchanged. Unknown keys, arbitrary colors, CSS, URLs, font families, fractions, numeric booleans and values
outside these sets are rejected before mutation.

Every valid input change previews complete standalone shapes and every member of complete groups in editor-owned DOM
only. Common source values are shown directly and mixed values remain explicit. Invalid input disables application
and restores the source preview. Close, Cancel, Escape, document/session changes, read-only state and stale selection
restore all original attributes without a transaction.

Apply rebuilds and validates every affected standalone shape and group before replacing the document in exactly one
transaction and undo unit. Stable IDs, group identity, membership/order, connections, gaps, anchors, layer, position,
dimensions and rotation remain intact. Confirmed CAS save, immutable predecessor history, undo/redo, reload, semantic
print/PDF and independent reuse consume only established canonical Office JSON attributes. Selection, dialog and
preview state remain transient.

Direct root selection occurs before the editor can retarget or rerender a pointer event. Capture-phase `mousedown`
handles a mouse exactly once; `pointerdown` handles touch and pen. Existing drag, resize and rotation handlers are
registered first and stop propagation when they own the gesture. Keyboard and synthetic click selection remain
available, and Ctrl/Cmd plus Shift preserve their established additive and range behavior.

## Consequences

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, arbitrary
color, CSS or font value, physical page anchor, nested group or DOCX DrawingML admission. Focused model, real mouse
selection and responsive desktop/mobile workflows pass, and the complete native-shape model and responsive matrix
passes 37/37. The isolated review API exposes the feature without changing ordinary tenant or production admission.
