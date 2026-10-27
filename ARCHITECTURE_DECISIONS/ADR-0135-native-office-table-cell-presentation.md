# ADR-0135: Native Office table-cell presentation

Status: Accepted
Date: 2026-10-07

## Context

Native Office table cells already preserve bounded fills and vertical alignment. Authors also need common numeric,
summary and emphasis layouts without storing CSS, pixel expressions, per-edge border models or spreadsheet formats.

## Decision

Admit three optional cell-level presentation dimensions: horizontal alignment (`center` or `right`), padding
(`compact` or `spacious`) and border treatment (`none` or `strong`). Omission retains left alignment, normal padding
and the surrounding table style. Browser and server independently reject unknown attributes, arbitrary alignment,
dimensions, colors, URLs, CSS and per-edge border expressions.

The existing accessible **Zellen formatieren …** dialog edits fills, vertical/horizontal alignment, padding and border
for the current cell, row, column or rectangular selection. Mixed values remain unchanged until explicitly selected.
Apply and the complete standard reset each produce one validated undo step. Explicit paragraph formatting remains
independent of the cell-level default.

Merge, split and header conversion preserve the validated attributes. Editor, comparison and print consume the same
canonical model and fixed CSS mappings. Confirmed saves and immutable versions retain the exact values, while reader
and historical controls remain disabled from the initial shell state.

## Consequences

Authors can build compact numeric tables, spacious summaries and bounded visual emphasis with predictable responsive
and print output. Existing documents retain identical canonical bytes because all defaults remain absent. The change
adds no arbitrary style engine, spreadsheet calculation, database migration, tenant activation or document-engine
admission.
