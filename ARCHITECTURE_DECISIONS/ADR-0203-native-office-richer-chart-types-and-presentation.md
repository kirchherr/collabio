# ADR-0203: Native Office richer chart types and presentation

## Status

Accepted on 2026-10-26.

## Decision

Native Office extends its closed chart-kind vocabulary with `stacked-bar`, `area` and `doughnut`. Stacked bars use
nonnegative series and a zero-based value scale whose automatic and manual bounds cover every per-category stack
total. Area charts retain the line-chart numeric contract, including finite negative values. Doughnut charts share the
pie-chart source contract: exactly one nonnegative series with at least one positive value and no axes.

Charts may carry one optional strict `presentation` object. It selects one of four fixed palettes (`standard`,
`accessible`, `warm`, `monochrome`), one of three bounded styles (`clean`, `soft`, `focus`) and left, center or right
title alignment. These options affect rendering only; canonical chart values, linked-table bindings, accessible
descriptions and hidden source-data tables remain unchanged.

The browser validates the complete prospective node before insertion or replacement and preserves it through linked
table recalculation, chart-kind conversion, immutable save and reload. The server independently validates the same
closed schema, kind-specific data, axis and scale rules. Unknown or surplus presentation fields, forged linked
snapshots, invalid source ranges, circular-chart axes and manual stacked scales that do not contain every stack total
fail closed.

## Consequences

The block reuses native chart nodes and immutable Office versions. It requires no migration, external chart engine,
network source or new durable state. Scatter, combo and three-dimensional charts, secondary or logarithmic axes,
per-series free-form styling, external data connections and automatic actions remain outside this decision.
