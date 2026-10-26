# ADR-0205: Native Office chart reference lines and data labels

## Status

Accepted on 2026-10-26.

## Decision

Non-circular native charts may carry one to four strict horizontal reference lines. Each line has a unique bounded
label, finite bounded value, one palette color and a solid or dashed style. Automatic scales include every reference
value; manual scales must contain all series, stack totals and reference values. Pie and doughnut charts reject lines.

Visible chart labels may carry one strict presentation object when labels are enabled. Content is limited to value,
category and value, series and value, or the complete bounded label. Position is limited to above or below the chart.
Canonical values and the hidden accessible data table remain unchanged.

Browser and server independently validate the closed schema before immutable save. Linked recalculation, editing,
save/reload and accessible descriptions preserve reference lines and label presentation. Free CSS, coordinates, HTML,
URLs, scripts and automatic actions are rejected.

## Consequences

No migration, external chart engine, network source or new durable state is introduced. Trendlines, error bars,
secondary/logarithmic axes and free-form analytical overlays remain outside this decision.
