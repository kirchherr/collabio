# ADR-0159: Bounded native Office shape-group alignment and distribution

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

A native Office shape group may retain optional cross-axis `alignment` and `distributionExtent` attributes. Canonical
start alignment is omitted so existing documents remain byte-compatible. `center` and `end` are the only stored
alignment values. For rows they mean middle and bottom relative to the tallest rotated member; for stacks they mean
middle and right relative to the widest rotated member.

An optional integer distribution extent from 160 through 2400 pixels requests equal spacing across the group's main
axis. The existing bounded group gap remains the minimum. One deterministic effective gap is derived from the ordered
member count, exact arbitrary-angle member bounds and the larger of the natural or requested extent. A group never
compresses below its natural size.

The responsive group dialog exposes beginning, middle and end alignment plus fixed or equal distribution. The extent
control is enabled only for an existing group using equal distribution. Contextual help names the row or stack axis
and explains that the existing gap remains authoritative as a minimum.

Editor and semantic print/PDF call the same layout function. Trusted static flex rules consume only validated tokens
and product-generated pixel values. Compact row layout falls back to a vertical presentation without horizontal
overflow. Uniform and per-edge connections span the computed effective gap and retain their exact ordered values.
Saved content cannot provide CSS, calculations, URLs or executable style expressions.

Browser and server independently reject explicit `start`, unknown values, booleans, fractions and extents outside the
bounded range. Confirmed save, immutable history, comparison, undo/redo, reload, independent reuse, recovery and print
preserve the attributes in the existing native-document JSON. No SQL migration, endpoint, dependency, external
request, provider, worker, new recovery store, free CSS geometry, multi-selection, nested group or DOCX DrawingML
admission is introduced.

Acceptance requires exact model and server validation plus responsive desktop/mobile workflows covering direct
editing, equal distribution of three members, arbitrary-angle bounds, per-edge connections, isolated undo/redo,
confirmed save, predecessor history, print and independent reuse.
