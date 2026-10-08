# ADR-0155: Bounded native Office text columns

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office page profiles support exactly one, two or three text columns for the complete document and for each
general section. The optional canonical token is `columns: "two"` or `columns: "three"`; absence remains one column
and preserves every existing document byte-for-byte. An explicit `"one"` value is accepted at the validation boundary
but the editor removes it when it writes the standard profile. Browser and server reject every other number, token,
dimension, CSS value, URL and object shape.

The responsive page and section dialogs expose the three bounded choices and show proportionate column guides.
Desktop editing renders two or three columns for a document without section markers. Compact editing collapses to one
column so controls and text remain usable, while print retains the saved exact count. A continuous editor cannot
faithfully render independent section column flows, so section-owned columns remain visible in the marker/dialog and
are rendered exactly in print/PDF.

Printing segments the document at existing page and section boundaries. Every print segment receives only the
validated static `one`, `two` or `three` token. Page-break segments keep the active section's count; a section marker
switches to its complete saved profile. Trusted CSS supplies fixed gaps and rules, keeps tables, figures, code,
quotations, cards and object groups together where possible, and does not accept document-provided style strings.

Confirmed CAS save, immutable history, comparison, reload, independent reuse and recovery preserve the exact token.
Recovery versions two and three bind document and section profiles with two and three columns. No migration or new
store is required because the existing immutable native-document JSON already carries version-owned page profiles.

No SQL migration, endpoint, dependency, external request, provider, worker, arbitrary column count, free column width,
mixed-width column grid, continuous section pagination, DOCX engine or ordinary tenant admission is introduced.
Acceptance requires independent browser/server rejection, schema/API/recovery coverage, responsive desktop/mobile
dialog evidence and real browser PDF output for document and section profiles.
