# ADR-0210: Native Office chart-series management

## Status

Accepted on 2026-10-27.

## Decision

Native bar, stacked-bar, line, area and combo charts may persist one strict optional series-management object. It
contains a complete permutation of canonical series indices and a sorted unique list of hidden canonical indices.
Authors can therefore change the displayed order and exclude individual series from the presentation without
rewriting, dropping or duplicating source data.

The derived series view drives the graphical plot, legend, value labels and semantic data table. Canonical series,
values, colors, linked-table references and formulas retain source order. Omission remains backward-compatible and
means canonical order with every series visible. At least one series must remain visible. A visible combo chart must
retain at least one bar and one line series.

Trendlines, error bars and secondary axes remain bound to canonical series indices in saved data. A referenced series
cannot be hidden. The derived view remaps those indices only while rendering; persisted analytical and axis contracts
are unchanged. Category-axis direction remains independent: semantic tables use canonical category order while plots
may derive the previously approved reversed category view.

The editor exposes named visibility checkboxes and accessible earlier/later controls. It prevents authors from hiding
the final visible series. Browser and server independently require exact keys, a full integer permutation, sorted
unique hidden indices, supported chart kinds and compatible combo, analysis and secondary-axis relationships.

## Consequences

No migration, dependency, external chart engine, alternate data store, network source, automatic action or new
durable business state is introduced. Scatter-series filtering, circular slice filtering, computed filters, arbitrary
sorting and destructive source-series deletion require separate decisions.
