# ADR-0169: Bounded native Office multi-object document order

Date: 2026-10-10

Status: Accepted

## Context

Native Office can move one standalone shape or one complete shape group through the top-level document order. Authors
also need to move several selected objects together without repeating an action, reversing their relative order or
splitting a group. This is document order, distinct from the established front/behind-text layer of positioned
objects.

## Decision

Two through twenty selected root standalone shapes or complete root shape groups may move one top-level position
earlier, one position later, to the document beginning or to the document end. Positioned, wrapped and normal-flow
roots are eligible together because the operation changes only the canonical top-level node order. Partial, nested,
duplicate, stale, out-of-range or unknown roots and actions fail closed.

The operation computes a permutation of every top-level document node. One-step movement swaps each selected run
across at most one adjacent unselected node. Beginning/end movement forms one selected block. In every case, selected
roots retain their relative order and unselected nodes retain theirs. A complete group remains one root; member
order, connections and group identity are never rewritten. Boundary actions that would change nothing are disabled
and create no history.

One accepted action replaces the top-level sequence in one validated ProseMirror transaction and one undo unit. The
same stable object IDs remain selected. Content, group membership, text, appearance, dimensions, rotations, anchors,
wrap, positions and front/behind-text layers remain unchanged. Confirmed CAS save stores only the resulting canonical
document order in the existing immutable Office version JSON.

## Consequences

The responsive multi-selection tools expose an explicitly labelled document-order group with beginning, earlier,
later and end actions. Eligibility is recalculated from current document state and write permission after every
change. Model and desktop/mobile workflows cover stable permutations, mixed top-level content, boundary disabling,
selection retention, one-step undo/redo, confirmed save, immutable predecessor history, print, reload and independent
reuse. The complete native-shape matrix passes 38/38.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, arbitrary
z-index, drag ordering, physical page anchor, nested group or DOCX DrawingML admission. It does not change the
established positioned-object layer contract or activate an ordinary tenant, pilot, indexing or document engine.
