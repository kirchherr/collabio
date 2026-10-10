# ADR-0173: Bounded native Office exact multi-object document placement

Date: 2026-10-10

Status: Accepted

## Context

Native Office can move two through twenty selected root shapes or complete root groups to the document beginning or
end and one position earlier or later. Authors also need to place a multi-object selection directly at an arbitrary
known document position without repeating one-step actions and without losing the stable order of either the selected
objects or surrounding document content.

The position must describe canonical top-level Office JSON order rather than physical page geometry or front/behind
text layering. Complete groups must remain opaque roots. Any stale selection, changed document, lost authorization or
invalid numeric target must fail before a transaction is created.

## Decision

Two through twenty selected standalone root shapes or complete root groups may move as one stable block when at least
one unselected root remains. The target is a one-based integer start slot in the final document after selected roots
have been removed. Its exact range is 1 through `root count - selection count + 1`. Fractions, booleans, duplicate or
unsorted root indexes, unsupported root kinds and out-of-range values are rejected.

The pure planner removes every selected index, retains the remaining indexes in their original order and inserts the
selected indexes in their original order at the requested slot. It returns the full root permutation and whether that
permutation changes the document. This preserves every root node byte-for-byte at the ProseMirror model boundary and
never rebuilds a shape, group or unrelated node.

An accessible responsive **Position ...** dialog exposes the exact target with dynamic minimum and maximum, current
selection/document counts, stable-order help and live valid, invalid or already-closed status. Cancel, close and Escape
discard only dialog state. Opening and submitting require current write permission and snapshot the authorized
session, exact document instance, selected IDs, root count and entries. Any mismatch closes or rejects the dialog
without a document change.

An effective plan replaces the complete document root sequence in one validated transaction and undo unit, preserves
the selected IDs and focuses the first selected node in its new location. The existing quick-order actions reuse this
same commit path. Invalid or unchanged plans create no transaction or history.

## Consequences

Pure-model tests cover beginning, middle and end insertion, stable selected/remainder order, no-op detection and all
numeric, count, root-kind, duplicate, ordering and range boundaries. The desktop/mobile workflow covers dynamic
bounds, invalid status, cancellation, exact placement, notice, selection retention and one-step undo/redo before the
existing confirmed-save, immutable-history, print, reload and independent-reuse path. The focused run passes 3/3 in
50.4 seconds and the complete native-shape matrix passes 41/41 in 5.0 minutes.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
browser/clipboard persistence, cross-document or cross-tenant transfer, arbitrary z-index, drag ordering, physical
page anchor, nested group support, arbitrary CSS geometry or DOCX DrawingML admission. It does not activate an
ordinary tenant, pilot, indexing path or document engine.
