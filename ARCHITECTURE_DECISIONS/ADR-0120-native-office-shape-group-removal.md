# ADR-0120: Atomic removal of native Office shape groups

Status: Accepted
Date: 2026-10-05

## Context

Authors can create, edit, reorder, dissolve and duplicate a native shape group, but removing a complete diagram
fragment still requires repeated member deletion. That is slower and can unintentionally leave a surviving shape or
change the group's meaning before the operation is complete.

## Decision

The shape-group section exposes an explicit focusable **Gruppe entfernen** action for an existing group. The action
resolves the group's validated opaque ID against the current editor document at activation time and removes exactly
that complete current group node. Other document nodes remain unchanged.

The removal is one isolated undo transaction. Undo restores the complete group with its exact identity, member order,
layout, gap, optional uniform connection and member attributes; redo removes it again. The change becomes durable only
through the existing confirmed compare-and-swap version save. Immutable earlier versions and static print continue to
consume their exact stored content.

The control is unavailable without an editable grouped shape. Missing, stale or read-only targets fail closed with a
visible status and no document mutation. No new saved field, schema, external content or executable presentation is
introduced.

## Consequences

The native shape-group lifecycle now includes an efficient whole-group removal without partial intermediate states.
Batch removal, document-wide search-and-delete, nested groups, arbitrary group transforms and DOCX DrawingML
interchange remain separate decisions.
