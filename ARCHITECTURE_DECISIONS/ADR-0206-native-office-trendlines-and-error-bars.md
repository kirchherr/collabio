# ADR-0206: Native Office trendlines and fixed error bars

## Status

Accepted on 2026-10-26.

## Decision

Line and area series, scatter Y series and line-rendered combination-chart series may carry one optional linear
trendline and one optional fixed symmetric absolute error-bar definition. At least one analysis must be present. Each
analysis targets one saved series index and uses only a fixed palette color; trendlines additionally select a solid or
dashed style, while error bars select one finite positive bounded absolute amount.

Trendlines are derived deterministically by ordinary least squares from canonical saved values. Line, area and combo
charts use zero-based ordinal X positions; scatter charts use the first saved numeric series as X coordinates. If all
X coordinates are equal, the slope is exactly zero and the intercept is the Y mean. No clock, locale, random value,
network source, external workbook or calculation service participates.

Automatic value scales include both trendline endpoint predictions and every upper and lower error bound. Manual
scales must contain those values in addition to canonical series, stack totals and reference lines. Any non-finite or
out-of-contract derived value fails closed. Browser and server independently validate exact keys, target eligibility,
numeric bounds and manual-scale containment before immutable save.

The editor exposes dynamic accessible target-series, color, line-style and amount controls. SVG overlays are derived
presentation only. Canonical chart values, linked-table snapshots, hidden authoritative data tables, undo, comparison,
printing and exact saved versions remain unchanged. Accessible descriptions name the selected series and error amount.

## Consequences

No migration, new durable state, dependency, external chart engine, provider call, automatic action or network source
is introduced. Polynomial, moving-average and exponential trendlines, relative/percentage or per-point error values,
confidence intervals, secondary axes, logarithmic axes and free-form analytical overlays require separate decisions.
