# ADR-0154: Bounded native Office paragraph indentation

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office stores optional paragraph attributes `indentLeft`, `indentRight` and `specialIndent`. Left and right
indent accept exactly 0, 18, 36, 54 or 72 pt. The special indent accepts exactly `none`, `firstLine18`,
`firstLine36`, `hanging18` or `hanging36`. Absence remains the canonical default and preserves legacy document
bytes. Browser and server reject other numbers, fractional or negative values, dimensions, percentages, arbitrary
CSS, URLs and unknown tokens.

Trusted static CSS maps the two side indents to logical margins. First-line indentation uses a fixed text indent.
Hanging indentation uses equal fixed inline-start padding and a negative text indent, so the first line stays at the
paragraph origin while following lines move inward. The same mappings render in the editor, style preview and
semantic print/PDF. Documents never provide style strings.

The responsive paragraph dialog supports Standard, mixed state, explicit zero side indents and each bounded special
indent. One application across the selected paragraphs is one isolated undo step. The controls remain unavailable
for code, readers, historical versions, stale dialogs and uncertain saves. Document-owned named styles may carry
the same values; a direct value has priority, while Standard returns to the linked style or text-type default.

Text-type conversion, paragraph splitting, lists, quotations, selected table cells, format transfer, search and
replacement, comparison, suggestions, confirmed CAS saves, immutable history, reload and independent reuse retain
the exact values. Recovery versions two and three bind first-line and hanging profiles without a migration or new
store.

The preceding section-page-number feasibility gate remains closed. In the deployed Chromium print path, resetting
the built-in page counter in a named `@page` rule produced `1, 2, 4, 4`, because the rule reset every page in that
section. Resetting on the first section element produced the unchanged global sequence `1, 2, 3, 4`. This matches
the unresolved first-page-of-named-sequence limitation described by CSS Paged Media. The document schema therefore
does not accept a restart value. A future implementation requires a separately proven segmented PDF render and merge
pipeline, including semantic structure, classification, headers/footers, exact section sizes and fail-closed output.

No SQL migration, endpoint, dependency, external request, provider, worker, arbitrary length, DOCX engine,
section-number restart or ordinary tenant admission is introduced. Acceptance requires schema, API, PostgreSQL,
recovery and named-style coverage plus pure model and responsive desktop/mobile browser evidence for mixed values,
reset, undo/redo, save, immutable predecessors, reload, direct precedence and real PDF output.
