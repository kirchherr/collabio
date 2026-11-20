# ADR-0197: Native Office calculations and linked charts

Date: 2026-10-12

Status: Accepted

## Context

Native Office already stored bounded formulas in table cells and supported inert charts with manually entered integer
series. Authors could not express common conditional, logical or numeric calculations, use decimal chart values or
bind a chart to a calculated table range. Copying results into a chart created a second state that could silently
become stale.

## Decision

Extend the existing local table evaluator with comparisons and the canonical functions `IF`, `AND`, `OR`, `NOT`,
`ROUND`, `ABS`, `POWER`, `SQRT`, `PRODUCT` and `MEDIAN`. German input aliases are normalized before storage. `IF`
evaluates only its selected branch. Results remain bounded, deterministic and independently recalculated by the
browser and server; invalid syntax, arity, references, domains, cycles, division by zero and excessive values retain
explicit fail-closed error tokens.

A chart may optionally bind to one exact rectangular range of a numbered table in the same native document. The
first selected row supplies series names, the first selected column supplies categories and the remaining cells must
contain bounded decimal literals or verified formula results. Bar and line charts accept two through five columns and
two through thirteen rows; pie charts require exactly one value series. The stored chart contains both the source
identity/range and a derived data snapshot so rendering, history, comparison and print stay deterministic.

Any accepted table edit recalculates formulas and every affected linked chart in the same local editor transaction.
Before a confirmed save, the browser verifies that every snapshot still equals its source. The server independently
resolves the numbered table, re-derives the range and rejects missing tables, stale snapshots, merged grids,
out-of-range cells, forged results, URLs and unknown source fields. Manual charts remain supported and now accept
bounded finite decimal values.

## Consequences

Authors can build common document calculations and keep native bar, line and pie charts synchronized without a
spreadsheet engine, external workbook, network source or embedded executable object. Immutable version history keeps
the exact table, formulas, formula results, source binding and chart snapshot for each confirmed save.

This decision adds no migration, cross-table reference, cross-document link, volatile function, date/time function,
lookup function, macro, external data refresh, workbook runtime or production collaboration admission. Those remain
separate roadmap work.
