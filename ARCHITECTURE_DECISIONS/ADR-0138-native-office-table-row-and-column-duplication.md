# ADR-0138: Native Office table row and column duplication

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables support bounded structure, styling, sorting and direct reordering, but authors cannot copy a
complete row or column selection without rebuilding its cells. Duplication must preserve content, semantic headers
and presentation, insert predictably beside the source and avoid ambiguous transformations of merged table geometry.

## Decision

Add **Auswahl duplizieren** to the existing row and column menus. A contiguous row selection is inserted directly
below its source; a contiguous column selection is inserted directly to its right. The inserted block becomes the
current rectangular selection.

The first all-header row and first all-header column remain protected and cannot be part of the source selection.
Duplication is admitted only for simple rectangular tables whose cells all have unit row and column spans. The
existing maximum of 200 rows and 20 columns is enforced before mutation. Merged or non-rectangular grids, protected
overlaps, size-limit crossings, unsupported options, stale selections, readers and historical versions fail closed.

Complete row or cell nodes are copied, including semantic type, content, marks and every bounded presentation
attribute. One accepted operation replaces the complete table in one validated transaction and therefore creates
exactly one undo step. Confirmed saves, immutable versions, reload, comparison and print consume the resulting
canonical table without a new stored attribute.

## Consequences

Authors can repeat table records and fields on desktop and mobile without losing formatting or manually copying each
cell. The feature adds no clipboard format, shared-node identity, merged-grid transformation, spreadsheet formula
engine, database migration, tenant activation or DOCX admission.
