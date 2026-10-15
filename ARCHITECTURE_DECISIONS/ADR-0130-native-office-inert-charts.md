# ADR-0130: Native inert Office charts

Status: Accepted
Date: 2026-10-06

## Context

Native Office documents could already contain text, tables, images, shapes and inert document objects. Authors still
lacked a compact visual summary for small literal datasets. Reusing an embedded spreadsheet, remote chart service,
arbitrary SVG or formula engine would introduce active content, external reads and a much larger validation surface.

## Decision

Add one top-level atomic `chart` block with a fresh stable ID, a bounded kind (`bar`, `line` or `pie`), literal title
and alternative text, an explicit legend flag, one to twelve unique categories and one to four uniquely named series.
Series use four fixed accessible colors and integer values from -1,000,000,000 through 1,000,000,000. Bar and pie
values are nonnegative; line charts may include negative values. Pie charts contain exactly one series and at least
one positive value. A document contains at most twenty charts.

The stored object contains no formula, URL, query, remote source, arbitrary style, SVG, HTML, script or executable
payload. Editor and print construct their own DOM and line-chart SVG from the validated model. A visually hidden
table exposes the exact categories, series and values to assistive technology; title, alternative text and the
optional legend remain part of the immutable document version.

Authors enter tab-separated literal data and receive an immediate preview. Insert, edit, duplicate with a fresh ID,
move one top-level position earlier or later and remove are focusable operations. Every accepted operation is one
isolated undo step. Confirmed compare-and-swap save remains the only durable mutation. Reload, immutable history,
comparison and print consume the same canonical representation.

Server and browser independently enforce exact keys, limits, IDs, control-character rejection, value domains and
top-level placement. Charts use the existing Office version JSON, authorization and recovery contracts. No database
migration, object storage write, background calculation or network access is added.

## Consequences

Authors can create useful small charts without admitting a spreadsheet runtime or external data connector. The fixed
model keeps rendering deterministic and historical versions stable. Axis editing, stacked charts, scatter plots,
continuous values, formula evaluation, live data binding, arbitrary palettes, chart animation and DOCX chart
interchange remain separate decisions.
