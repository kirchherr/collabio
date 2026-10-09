# ADR-0118: Direct duplication of native Office shapes

Status: Accepted
Date: 2026-10-05

## Context

Authors frequently reuse a visual style or diagram member. Re-entering every shape attribute is slow and error-prone,
while copying the durable identity would violate document uniqueness. Positioned copies also need a visible result
instead of silently overlapping their source.

## Decision

The shape dialog exposes an explicit focusable **Form duplizieren** action only while editing an existing shape. The
action creates a fresh cryptographically random opaque shape ID and preserves all validated content, presentation and
layout attributes.

A grouped copy is inserted immediately after its source and retains no independent wrap or position. Existing group
ID, layout, gap and optional connection remain unchanged. The action is disabled when the group already has eight
members or the document already has 100 shapes.

A standalone copy is inserted immediately after its source. Flow and wrapped shapes retain their exact layout.
Positioned copies retain their layer and receive a 25-unit horizontal and 24-pixel vertical offset. Near the maximum
right or lower bound, the offset reverses so the new position remains valid and visible. No arbitrary CSS, z-index or
physical-page coordinate is introduced.

The insertion and new selection are one isolated undo transaction. Existing browser and server validation remains
authoritative before dispatch and confirmed version saving.

## Consequences

Authors can build repeated diagrams quickly without weakening identity or limits. Multi-selection duplication,
cross-document clipboard formats, arbitrary cascade placement, group duplication as a unit and DOCX DrawingML
interchange remain separate decisions.
