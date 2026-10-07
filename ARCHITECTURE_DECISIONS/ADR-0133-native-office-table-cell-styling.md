# ADR-0133: Native Office table cell styling

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables already preserve bounded grids, merged cells and semantic row and column headers. Authors also
need restrained visual grouping and vertical placement without admitting arbitrary CSS, remote resources or an
unbounded style vocabulary into immutable document versions.

## Decision

Table cells and headers may store an optional background token from `gray`, `blue`, `green`, `yellow` and `red`, plus
an optional vertical alignment of `middle` or `bottom`; omission means no fill and top alignment. Browser and server
independently reject unknown keys, arbitrary colors, CSS values and unsupported alignments. The renderer maps the
tokens to one fixed print-safe palette and inert data attributes in the editor and print surface.

The accessible **Zellen formatieren …** dialog applies a fill and vertical alignment to the current cell selection.
Mixed selections preserve an attribute until the author explicitly replaces it. One apply operation changes all
selected cells in one validated transaction and one undo step. Merge, split and header conversion retain the exact
canonical attributes. Comparison text exposes both attributes without evaluating style strings.

All table mutation controls start disabled in the static shell and are enabled only after the current session,
selection and write state have been checked. Reader and historical views therefore fail closed even before the first
editor-state refresh.

## Consequences

Authors can format one cell, a row, a column or an arbitrary rectangular selection with predictable editor and print
output. Confirmed save, immutable history, reload, comparison and print preserve the same bounded values. Existing
documents remain canonical because default presentation is represented by absent attributes. This adds no database
migration, arbitrary styling, spreadsheet calculation, tenant activation or document-engine admission.
