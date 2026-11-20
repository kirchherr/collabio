# ADR-0198: Native Office named ranges and cross-table formulas

## Status

Accepted on 2026-10-12.

## Decision

Native Office stores at most 100 document-wide named table ranges in the document root. Each canonical uppercase name
binds one stable numbered-table ID to one bounded rectangular `A1:T200` range. Names are unique, cannot collide with a
cell reference or supported function, and contain only letters, digits and underscores. A definition never contains a
URL, workbook path, query, macro or executable expression.

The browser recalculates every table formula as one document dependency graph. Local cell references stay relative to
their containing table; named ranges may resolve cells in another numbered table. Formula cells and named targets share
one memo, error cache and cycle detector. Structural table operations remap rectangular definitions when the selected
cells remain contiguous and remove definitions that lose their target. Removing a numbered table or its caption removes
its definitions in the same editor transaction.

`XLOOKUP` performs an exact numeric lookup across two equal-length local or named ranges. `DATE`, `YEAR`, `MONTH` and
`DAY` use deterministic UTC day numbers relative to 1970-01-01. German aliases and semicolon separators normalize to
the canonical grammar. Volatile clock functions, approximate lookup, external workbooks, formulas containing strings,
network access, macros and automatic actions remain outside this decision.

Before accepting a saved version, the server independently validates every definition, resolves current table IDs and
ranges, evaluates the complete cross-table dependency graph, detects cycles and compares each stored result with its
derived value. Missing names or lookup values fail with `#BEZUG!`; malformed values, range shapes, arity or dates fail
with `#WERT!`; existing division, resource and cycle errors remain deterministic.

## Consequences

Named ranges are part of the immutable native document version and require no database migration or external formula
engine. The initial lookup contract is deliberately numeric and exact. Text lookup, display-level date formatting,
volatile values, external data connections and spreadsheet-style sheet syntax require separate decisions and tests.
