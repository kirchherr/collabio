# ADR-0208: Native Office visible accessible chart data tables

## Status

Accepted on 2026-10-27.

## Decision

Every native chart continues to expose one semantic data table derived from its canonical saved categories and series.
Authors may persist one strict optional presentation object that makes this existing table visible above or below the
chart and optionally shows fixed palette keys in the series headers. Presence means visible; omission retains the
backward-compatible visually hidden table. The presentation never stores a second value snapshot.

Visible tables use native caption, row-header and column-header semantics. The chart container is an accessible group,
while the graphical plot is explicitly decorative for assistive technology. The group description names the visible
table and references its stable chart-owned ID. Series color keys are decorative and do not replace header text.

Every visible header and data cell participates in bounded roving keyboard focus. Arrow keys move by cell, Home and
End move within a row, and Control plus Home or End moves to the first or last cell. Focus cannot leave the table
through these commands. A visible focus ring, responsive horizontal scrolling and a caption instruction support
keyboard, touch and narrow-screen inspection.

The editor offers only visibility, above/below position and fixed legend-key controls. Browser and server independently
validate the exact object, enum and boolean before immutable save. Linked-table recalculation, formulas, chart editing,
duplication, comparison, printing and save/reload always derive the table from the authoritative chart data.

## Consequences

No migration, dependency, external chart engine, alternate data store, network source, automatic action or new durable
business state is introduced. Arbitrary table styles, free-form captions, editable cells, separate table data, CSV
export and screen-reader-specific virtual-grid behavior require separate decisions.
