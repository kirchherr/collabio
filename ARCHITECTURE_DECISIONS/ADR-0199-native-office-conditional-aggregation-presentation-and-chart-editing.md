# ADR-0199: Native Office conditional aggregation, numeric presentation and linked-chart editing

## Status

Accepted on 2026-10-12.

## Decision

Native Office extends its bounded numeric formula grammar with `SUMIF`, `COUNTIF` and `AVERAGEIF`. The German aliases
`SUMMEWENN`, `ZÄHLENWENN` and `MITTELWERTWENN` normalize to those canonical names. This first contract compares every
numeric range member with one exact numeric criterion. Sum and average may read a second equally sized local or named
range; count accepts no result range. All participating ranges remain bounded to 4,000 values and use the existing
document-wide dependency graph, cycle detection and deterministic error vocabulary.

Table cells may store one fixed presentation identifier for integer, two-decimal, percent, EUR or deterministic date
display. The underlying cell text and every `formulaResult` remain canonical numeric values. The browser derives the
localized visible text through a ProseMirror decoration and never writes that presentation back into the calculation
input. The server admits presentation only for a finite numeric value and additionally requires date formats to resolve
to a real UTC date between 1900 and 9999. Free format strings, locale programs and executable expressions are rejected.

Linked charts may interpret their exact same-document table rectangle by columns or by rows. The chosen orientation is
part of the immutable source binding and therefore covered by the existing stale-snapshot verification in browser and
server. Authors may also persist a boolean values-label presentation and may continue to edit source table, range,
orientation, chart type, title, alternative text and legend before the next explicitly confirmed version save.

## Consequences

The block uses the existing native document JSON and needs no migration, external spreadsheet engine or network source.
Conditional text or wildcard criteria, custom currencies/locales, arbitrary format strings, live external data,
volatile formulas, macros and automatic saves or actions remain outside this decision.
