# ADR-0137: Native Office table row and column reordering

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables can be structured, styled and sorted, but authors cannot directly move selected rows or columns
without recreating their contents. Direct movement must preserve complete cells, semantic headers and presentation,
remain one predictable undo step and avoid ambiguous edits across merged table geometry.

## Decision

Add **Auswahl nach oben/unten** to the row menu and **Auswahl nach links/rechts** to the column menu. Each action
moves the current contiguous row or column selection by exactly one position. Boundary actions are disabled, and a
rejected command leaves the document unchanged.

The first all-header row and first all-header column are fixed. A selection that overlaps either protected area cannot
move in either direction. Reordering is admitted only for simple rectangular tables whose cells all have unit row and
column spans. Merged or non-rectangular grids, unsupported options, stale selections, read-only documents and
historical versions fail closed.

Movement preserves complete row or cell nodes, including semantic type, content, marks and every bounded presentation
attribute. One accepted action replaces the complete table in one validated transaction and restores the same
rectangular selection at its new position. Confirmed saves, immutable versions, reload, comparison and print consume
the resulting canonical order without a new stored attribute.

## Consequences

Authors can directly arrange table records and fields on desktop and mobile without copying cell content or losing
formatting. The feature adds no drag-and-drop protocol, arbitrary overlap ordering, merged-grid transformation,
spreadsheet formula engine, database migration, tenant activation or DOCX admission.
