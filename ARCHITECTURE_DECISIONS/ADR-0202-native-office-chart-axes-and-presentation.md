# ADR-0202: Native Office chart axes and presentation

## Status

Accepted on 2026-10-14.

## Decision

Native Office bar and line charts may carry one strict `axes` object with bounded category and value titles, automatic
or manual value scaling, optional major gridlines and one deterministic number format. Automatic scaling includes
zero, derives stable 1/2/5 major steps and emits at most thirteen ticks. Manual scaling requires finite minimum,
maximum and positive major-unit values, an exact whole number of at most twelve intervals, and every plotted value
inside the selected range. Pie charts reject axes.

Charts may place a visible legend at the top, bottom, left or right. Number formats are restricted to general,
integer, two-decimal, percent and euro currency presentation. They affect tick and data labels only; canonical numeric
chart data remains unchanged. Axis titles, legend content and the existing hidden data table remain part of the
accessible chart description.

The browser validates the complete prospective chart before insertion or replacement and preserves the presentation
contract across linked-table recalculation, immutable save and reload. The server independently validates the same
closed schema, range, interval and data-bound rules before accepting a document version. Invalid, surplus, pie-axis,
non-finite, out-of-range or uneven-scale values fail closed.

## Consequences

The block reuses native chart nodes and immutable Office versions. It requires no migration, external chart engine,
network source or new durable state. Secondary axes, logarithmic scales, free-form format strings, three-dimensional
charts, external data connections and automatic actions remain outside this decision.
