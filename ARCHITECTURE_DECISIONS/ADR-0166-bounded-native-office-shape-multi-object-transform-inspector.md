# ADR-0166: Bounded native Office shape multi-object transform inspector

Date: 2026-10-09

Status: Accepted

## Context

Native Office supports transient selection plus collective alignment, distribution, layer changes, movement,
pointer/touch dragging, resizing and relative rotation for positioned root shapes and complete shape groups. Authors
also need a precise keyboard-friendly surface that combines these established operations without repeating several
gestures or creating several undo units.

## Decision

At least two selected positioned root shapes or complete root groups may be transformed through one modal inspector.
The inspector accepts relative logical X and pixel Y movement, independent width and height percentages or one
aspect-locked percentage, a relative whole-degree rotation and an optional common front/behind-text layer.

The command contract accepts exactly seven typed keys. X movement is an integer from -1000 through 1000, Y movement
an integer from -2400 through 2400, each scale an integer per-mille value from 100 through 5000, aspect locking a
boolean, rotation an integer from -359 through 359 and layer either null, `front` or `behind`. Unknown keys,
fractions, booleans in numeric fields and values outside these bounds are rejected. Existing shared movement and
size constraints derive the effective common deltas and factors, so no selected position or member size can leave
its established canonical range.

Every valid edit produces a DOM-only preview of complete standalone shapes and complete groups, including root
position/layer, member dimensions and member rotations. The status exposes the effective clamped movement, scale
and rotation. Invalid combinations disable application and restore the source preview. Close, Cancel, Escape,
document/session changes, read-only state and stale selection restore every original value without a transaction.

Apply rebuilds and validates all affected shapes and groups before replacing the document in exactly one transaction
and undo unit. Stable IDs, group membership/order, connections, gaps, text and typography remain intact. Selection,
dialog and preview state stay transient. Confirmed CAS save, immutable predecessor history, undo/redo, reload,
semantic print/PDF and independent reuse consume only the established bounded attributes in immutable Office JSON.

The responsive dialog uses three predictable two-field rows and one inline aspect-lock control. The Office
stylesheet URL advances to `v=2` so long-lived browser sessions fetch the accepted layout instead of retaining the
previous cached CSS.

## Consequences

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, arbitrary
transform string or CSS value, physical page anchor, nested group or DOCX DrawingML admission. The focused model and
responsive desktop/mobile workflows pass 3/3, and the complete native-shape model and responsive matrix pass 36/36.
The isolated review API exposes the feature without changing ordinary tenant or production admission.
