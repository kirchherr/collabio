# ADR-0200: Native Office multiple-criteria aggregation

## Status

Accepted on 2026-10-13.

## Decision

Native Office extends its bounded numeric formula grammar with `SUMIFS`, `COUNTIFS` and `AVERAGEIFS`. The German
aliases `SUMMEWENNS`, `ZÄHLENWENNS` and `MITTELWERTWENNS` normalize to those canonical names before evaluation and
persistence. Sum and average accept one result range followed by criteria-range/criterion pairs; count accepts only
criteria pairs. Every criterion is one exact numeric value.

Each formula must contain one through ten criteria pairs. The result range and every criteria range must contain the
same number of values, and the shared size remains bounded to 4,000. Ranges may be local A1 rectangles or canonical
document-wide named ranges. Evaluation stays inside the existing document dependency graph with shared memoization,
cross-table cycle detection and the established reference, value, division and resource-limit errors.

The browser normalizes and calculates the local draft, while the server independently parses the canonical formula,
resolves every table and named range and recalculates every stored result before accepting a confirmed immutable
version. A missing range, mismatched size, invalid arity, stale result or forged result fails closed.

## Consequences

The block uses the existing native document JSON and needs no migration, external spreadsheet engine or network
source. Structural row and column operations keep using the existing reference and named-range remapping contracts.
Text, wildcard, comparison-string and locale-dependent criteria, external workbook links, volatile formulas, macros
and automatic saves or actions remain outside this decision.
