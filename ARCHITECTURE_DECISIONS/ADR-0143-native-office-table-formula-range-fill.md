# ADR-0143: Native Office table formula range fill

Status: Accepted
Date: 2026-10-07

## Context

ADR-0139 introduced bounded local table formulas and ADR-0142 added absolute and mixed references. Authors still had
to open every target cell separately when the same calculation belonged in a row, column or rectangular range. That
made common table work slow and invited manual reference errors even though the existing copy grammar already knew
how to shift anchored coordinates safely.

## Decision

Extend the existing formula dialog to every rectangular selection containing only ordinary data cells in a simple
table. The entered formula belongs to the top-left cell. Fill every other selected cell by its row and column offset,
shifting only unanchored reference axes under ADR-0142. Normalize the source once, reject any shifted reference outside
A1:T200 and recalculate the complete resulting table before committing it.

Treat the complete fill as one table replacement and one undo step, then restore the rectangular cell selection. The
dialog names the selected range and formula count. Removing formulas clears every selected formula and stored result
in the same atomic operation while retaining each last visible result as ordinary cell content. Remaining formulas
are recalculated against that result.

Keep the unchanged simple-grid, ordinary-data-cell, 1,000-formula, document-size, authorization, stale-session,
reader, historical-version and confirmed-save boundaries. Browser and server continue validating every persisted
formula and result independently. Header cells, merged grids, invalid dimensions and any formula or coordinate error
leave the draft unchanged.

## Consequences

Authors can fill or clear a bounded row, column or rectangle from one accessible dialog with spreadsheet-like relative,
absolute and mixed copy behavior. The operation survives undo/redo, immutable save, reload, comparison and print without
a relational migration or new recovery target. Fill handles are not introduced; sheets, named ranges, cross-table
references, dynamic arrays and a workbook runtime remain outside this decision.
