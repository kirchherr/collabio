# ADR-0170: Bounded native Office multi-group ungroup

Date: 2026-10-10

Status: Accepted

## Context

Native Office can dissolve one normal-flow shape group into its member shapes. Authors also need to dissolve several
selected groups together without repeating the command, losing member identity or creating several unrelated undo
steps. Freely positioned groups carry one group-level anchor and layer that cannot be mapped losslessly to several
independent shapes, so they require a separate placement design.

## Decision

Two through twenty selected complete root shape groups may be dissolved together when every group is in normal flow.
Mixed shape/group selections, a single group, partial or nested groups, positioned groups, duplicate, stale,
out-of-range or unknown selections and invalid members fail closed. The established two-through-eight member bound
continues to apply independently to every selected group.

The operation removes only the selected group wrapper nodes. Each group's member shapes replace that wrapper at the
same top-level document position and retain their existing member order, stable IDs, text, appearance, dimensions,
rotations and other canonical shape attributes. Unselected document nodes and unselected groups retain their relative
order and content. Group-only identity, layout, gap and connection metadata disappear with the wrapper.

One accepted action performs all replacements from the end of the document toward the beginning in one validated
ProseMirror transaction and one undo unit. The transient multi-selection is cleared and the first resulting member is
focused as an ordinary node selection. Invalid and ineligible actions are disabled and create no transaction or
history. Confirmed CAS save stores only the resulting established top-level shapes in the existing immutable Office
version JSON.

## Consequences

The responsive multi-selection tools expose **Gruppen auflösen** only for at least two eligible complete normal-flow
groups. Model and desktop/mobile workflows cover eligibility, wrapper removal, exact identity and order preservation,
single-step undo/redo, transient-selection clearing, confirmed save, immutable predecessor history, semantic print,
reload, range selection and independent reuse. The complete native-shape matrix passes 39/39.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, inferred
position, layer conversion, member rewrite, nested group, arbitrary connector or DOCX DrawingML admission. It does
not activate an ordinary tenant, pilot, indexing path or document engine.
