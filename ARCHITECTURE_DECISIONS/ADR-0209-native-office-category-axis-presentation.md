# ADR-0209: Native Office category-axis presentation

## Status

Accepted on 2026-10-27.

## Decision

Native bar, stacked-bar, line, area and combo charts may persist one strict optional category-axis presentation.
Authors can keep or reverse the visual category direction, show every first, second or third category label, and use
horizontal, diagonal or vertical labels. Omission remains backward-compatible and means forward order, every label
and horizontal text.

The presentation changes only the derived graphical view. Canonical categories, every positional series value,
linked-table references, accessible data tables and saved formula results retain their original order. Reversing the
axis derives a reversed category list and reverses every plotted series in lockstep; it never rewrites the source.
The label interval suppresses only graphical tick text. Semantic tables continue to expose every category and value.

The editor enables these controls only for chart kinds with a categorical horizontal axis. Pie, doughnut and scatter
charts reject the object. Browser and server independently require the exact keys `direction`, `labelInterval` and
`labelRotation`; direction is `forward` or `reverse`, rotation is `horizontal`, `diagonal` or `vertical`, and the
interval is an integer from one through three. Booleans, surplus keys and unsupported chart combinations fail closed.

The accessible chart description names every non-default presentation choice. Responsive CSS rotates only the
graphical label text, while the chart container, semantic data table and document page remain contained at desktop
and narrow-screen widths.

## Consequences

No migration, dependency, external chart engine, alternate data store, network source, automatic action or new
durable business state is introduced. Date axes, numeric category axes, arbitrary angles, automatic collision
avoidance, multi-level labels and free-form label formatting require separate decisions.
