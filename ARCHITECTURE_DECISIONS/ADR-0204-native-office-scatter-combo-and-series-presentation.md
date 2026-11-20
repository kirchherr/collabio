# ADR-0204: Native Office scatter, combo and series presentation

## Status

Accepted on 2026-10-26.

## Decision

Native Office adds strict `scatter` and `combo` chart kinds. A scatter chart requires at least two numeric series. The
first series supplies the bounded X coordinates; every following series supplies Y coordinates for the same named
points. X and Y scales are deterministic and zero-inclusive. The established chart axis contract controls the Y scale
and labels the numerical X and Y dimensions.

A combo chart requires at least two series and one strict presentation entry per series. At least one series renders as
bars and at least one as a line on the common value scale. Bar series remain nonnegative. Line series may contain
finite negative values. Secondary axes are not inferred or admitted.

The optional `seriesPresentation` array is positional, bounded by the chart's verified series, and uses only fixed
renderers, markers and line styles. Bars require no marker or line. Lines allow no marker, circle, square or diamond
with a solid or dashed line. Scatter Y series require a visible marker and may optionally connect points with a solid
or dashed line. Free colors, CSS, URLs, scripts and surplus fields are rejected.

The browser validates the complete prospective chart before insertion or replacement. The server independently
validates kind, series count, per-series presentation, negative-value rules, linked-table snapshot and scale before an
immutable version is accepted. Editing, kind conversion, linked recalculation, save/reload, accessible descriptions
and hidden source-data tables preserve the closed contract.

## Consequences

The block reuses native chart nodes and immutable Office versions. It requires no migration, external chart engine,
network source or new durable state. Secondary or logarithmic axes, trendlines, error bars, free-form series styling,
three-dimensional charts, external data connections and automatic actions remain outside this decision.
