# ADR-0123: Atomic removal of native Office image groups

Status: Accepted
Date: 2026-10-05

## Context

Authors can create, extend, arrange, move and dissolve a native image group, but removing a complete grouped figure
set still requires repeated member removal. That creates unnecessary intermediate states and can leave part of the
intended visual unit behind.

## Decision

The image-group section exposes an explicit focusable **Bildgruppe entfernen** action. At activation, the editor
resolves the group's validated opaque ID against the current document and removes exactly that complete current group
node. Other document nodes and the document-owned source assets remain unchanged.

The removal is one isolated undo transaction. Undo restores the complete group with its exact identity, member order,
row or stack layout, gap and every member's immutable asset/version binding, crop, transform, alternative text,
caption and figure identity. Redo removes it again. The change becomes durable only through the existing confirmed
compare-and-swap version save. Immutable earlier versions and static print continue to consume their exact stored
content; removing a draft node does not delete its retained source assets.

The control is unavailable without an editable grouped image. Missing, stale or read-only targets fail closed with
no document mutation. No new saved field, schema, external content or asset deletion path is introduced.

## Consequences

The native image-group lifecycle now supports efficient whole-group removal without partial intermediate states.
Asset lifecycle cleanup remains governed by retention, legal hold and document ownership. Batch removal, nested
groups, arbitrary group transforms and DOCX DrawingML interchange remain separate decisions.
