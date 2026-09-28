# ADR-0097: First-page headers, footers and page-number visibility

Date: 2026-09-28
Status: accepted; development validation and dev001 rollout complete; ordinary tenant and production admission remain closed

The optional `attrs.running.firstPage` object contains exactly a literal `header`,
literal `footer` and boolean `showNumber`. Its text follows the same 64-code-point
and control-character limits as the document's general running text. Absence means
the first printed page inherits the general header, footer and numbering, so every
ADR-0096 document retains its exact canonical bytes and behavior. Presence selects
an explicit first-page profile; empty strings intentionally clear inherited text.
`showNumber` may be true only when general numbering is `page` or `pageOfPages`.
Hiding page one does not renumber later pages: page two remains page two.

The existing page dialog owns this setting and validates it with saved margins.
It presents separate first-page and following-page previews, disables unavailable
controls, applies one isolated undo transaction and removes all running metadata on
the established reset action. Confirmed CAS Save remains the durability boundary.
History, comparison, independent copies and exact-version recovery retain the nested
metadata. No HTML, URL, field expression, arbitrary CSS or external content is admitted.

Printing uses a trusted static `@page office-document:first` rule alongside the
existing named-page rules. The application writes only code-point-escaped literal
strings and fixed page counters through CSSOM, then clears all four margin boxes after
success, cancellation, failure and context invalidation. An engine missing any required
margin rule refuses visible running-text output. Real three-page PDFs must prove the
different first-page text, hidden and visible first-page number states, unchanged
subsequent numbering and absence of stale text after reset.

Fresh isolated recovery adds exact first-page-hidden, first-page-visible,
explicitly-empty-first-page and full-reset versions while retaining all prior Office
recovery evidence. No endpoint, SQL migration, dependency or image-decoder change is
needed. General sections, arbitrary fields, editor pagination, floating objects and
DOCX interchange remain separate work.
