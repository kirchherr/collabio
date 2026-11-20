# ADR-0207: Native Office logarithmic and secondary chart axes

## Status

Accepted on 2026-10-26.

## Decision

Line, area, scatter and combination charts may carry one strict optional advanced-axis object. It explicitly selects a
linear or logarithmic primary value scale and may assign exactly one saved value series to a secondary axis. At least
one value series remains on the primary axis. Pie, doughnut, ordinary bar and stacked-bar charts reject this object.

The secondary axis has one bounded literal title, one linear or logarithmic scale, automatic or manual bounds and one
closed number format. Assignment uses an exact saved series index; scatter X coordinates are never assignable. The
editor never guesses a scale or moves a series automatically.

Automatic logarithmic scales derive bounded power-of-ten ticks from canonical values and contain at most twelve
intervals. Manual logarithmic scales interpret the major unit as an exact multiplicative factor greater than one.
Linear scales retain the existing additive interval contract. Every canonical value, reference line, trend endpoint
and error-bar bound assigned to a logarithmic axis must be finite, bounded and strictly positive.

Series, trendlines and error bars render against their assigned scale. Primary gridlines remain authoritative; the
right axis shows its own readable ticks and title. Accessible descriptions name the scale and secondary series.
Canonical chart data, linked snapshots, hidden source tables, versioning, comparison and printing remain unchanged.

Browser and server independently validate exact keys, target eligibility, scale arithmetic, analytical extents and
manual containment before immutable save. Surplus fields, booleans, nonpositive logarithmic values and ambiguous or
impossible assignments fail closed.

## Consequences

No migration, dependency, external chart engine, workbook link, provider call, automatic action, network source or new
durable state is introduced. Multiple secondary series or axes, logarithmic X axes, broken-axis views, arbitrary tick
lists and free-form axis styling require separate decisions.
