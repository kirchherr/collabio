# ADR-0158: Per-edge native Office shape-group connections

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

A native Office shape group may retain its existing optional uniform `connection` or replace it with one exact
`connections` list. The two forms are mutually exclusive. A per-edge list has exactly one entry for every gap between
consecutive members, in reader order. Each entry is either `null` or the existing bounded line, direction-arrow or
double-arrow value with one fixed color token and an integer width from 1 through 8 pixels. Existing documents with a
uniform connection remain byte-compatible.

The responsive group dialog offers **Alle Verbindungen** plus one numbered choice for every current gap, such as
**1 → 2**. Choosing a single gap converts an existing uniform value into an explicit list before applying that edit,
so untouched gaps preserve their presentation. Choosing the uniform scope deliberately returns the group to the
single-value representation. Color and width remain disabled while the active scope has no connection.

Editor and semantic print/PDF resolve both representations into the same exact edge sequence. Rows render each
connection horizontally; stacks and compact row fallback render it vertically. Trusted static CSS consumes only the
validated kind, color and integer width. Saved content cannot supply paths, endpoints, SVG, CSS, URLs or executable
style expressions.

Per-edge values belong to ordered gaps. Reordering members leaves the gap presentation in place. Inserting a member
adds one disconnected gap without changing existing edges. Removing a member removes exactly one adjacent gap.
Whole-group duplication preserves the exact list, while member and group copies still receive fresh identities.
Every edit and structure mutation remains one isolated undo transaction.

Confirmed save, immutable history, comparison, undo/redo, reload, independent reuse, recovery and print preserve the
exact connections in the existing native-document JSON. No SQL migration, endpoint, dependency, external request,
provider, worker, new recovery store, freehand path, arbitrary endpoint, nested group or DOCX DrawingML admission is
introduced.

Acceptance requires independent browser/server rejection, exact list-length and mutual-exclusion checks, deterministic
insert/remove behavior and responsive desktop/mobile workflows covering uniform-to-per-edge editing, member
duplication, undo/redo, confirmed save, predecessor history, print and independent reuse.
