# ADR-0131: Native Office merged table cells and semantic headers

Status: Accepted
Date: 2026-10-06

## Context

Native Office tables supported bounded rows, columns, captions and contextual editing, but every row had to contain
the same physical number of cells. Authors could not build grouped headings, row-spanning labels or a semantic first
column. Flattening these structures during save or print would lose meaning and make historical versions differ from
the edited document.

## Decision

Allow canonical `colspan` values from one through twenty and `rowspan` values from one through two hundred on native
table header and data cells. Browser and server independently expand each row into a bounded logical grid, reject
overlaps, gaps, truncated row spans and shapes wider than twenty columns or taller than two hundred rows, and require
the resulting grid to remain rectangular. Editor-only attributes are removed before this canonical validation and
never enter a saved version.

Expose focusable **Zellen verbinden** and **Zelle teilen** actions for valid selections. Each successful action is one
isolated undo transaction. Add a separate **Kopfspalte** toggle alongside the existing header-row action. Header-row
and header-column state are derived from the logical grid so merged cells remain deterministic.

Confirmed compare-and-swap save remains the only durable mutation. Reload, immutable history and comparison retain
the exact span geometry. Print emits native `colspan` and `rowspan`; column headers use `scope="col"` and first-column
headers in the table body use `scope="row"`. No formula, spreadsheet runtime, external source or active payload is
introduced.

## Consequences

Authors can create grouped headings and semantic row labels while retaining exact version and print fidelity. The
bounded rectangular-grid algorithm prevents ambiguous or pathological layouts. Cell borders, colors, formulas,
sorting, filtering, repeated printed headers, arbitrary nested tables and spreadsheet behavior remain separate
decisions.
