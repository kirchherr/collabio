# ADR-0136: Native Office table sorting

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables preserve bounded structure and presentation, but authors cannot yet reorder ordinary data rows
without manually moving their complete cell contents. A sort operation must keep each row intact, preserve headers and
cell presentation, remain deterministic across browsers and avoid introducing spreadsheet formulas or locale-dependent
parsing.

## Decision

Add one accessible **Sortieren …** dialog for simple rectangular tables with at least two data rows. Authors choose a
column, ascending or descending order and one of three explicit types: normalized text, strict decimal number or strict
ISO date (`YYYY-MM-DD`). Text comparison uses Unicode NFKC normalization and lowercase code-point ordering. Numbers
accept one decimal separator and no grouping; dates must be real calendar dates with years from 1000 through 9999.
Empty cells always sort last and equal values retain their previous row order.

The first all-header row remains fixed. Sorting moves complete row nodes, including cell type, content, marks, spans and
all bounded presentation attributes. Tables with merged cells or a non-rectangular logical grid fail closed. Invalid
values, unsupported options, stale selections, read-only documents and historical versions leave the document unchanged.

One accepted sort replaces the complete current table in one validated undo transaction and keeps selection inside that
table. Confirmed saves, immutable versions, reload, comparison and print consume the resulting canonical table without a
new stored attribute.

## Consequences

Authors can sort common text, numeric and date tables predictably on desktop and mobile while preserving semantic
headers and row integrity. The feature adds no formula evaluator, locale-sensitive number engine, automatic type
inference, database migration, tenant activation or DOCX admission.
