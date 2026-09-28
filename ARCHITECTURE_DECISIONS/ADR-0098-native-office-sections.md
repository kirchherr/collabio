# ADR-0098: Native Office sections and section-bound page profiles

Date: 2026-09-28
Status: accepted; development validation in progress; ordinary tenant and production admission remain closed

A root-level `sectionBreak` node starts a new printed page and owns the complete page and running-text profile for
the following section. Its `attrs` object contains exactly `page` and `running`. Page values reuse the closed
A4/Letter, portrait/landscape and 5–50 mm margin contract. Running values reuse bounded literal header/footer text
and `none`, `page` or `pageOfPages` numbering. A document may contain at most twelve section breaks. They cannot be
leading, trailing, nested, adjacent to another section break or adjacent to an explicit page break.

The complete profile avoids ambiguous inheritance when a saved version is reopened, compared, copied, printed or
restored. The document root governs the first section. Each marker governs the next section until another marker.
The root `running.firstPage` profile applies only to the document's first printed page; Chromium does not provide a
reliable per-named-section `:first` contract. Page numbering remains global and continuous. Number restarts need a
separate counter and interchange contract.

The editor exposes insertion at a valid root boundary plus edit and removal for a selected marker. The responsive
dialog previews paper, orientation, margins, literal running text and numbering before one isolated undo transaction.
Only confirmed CAS Save persists the node. History, comparison, independent copies, reviews and suggestions retain
exact structure and positions. Invalid profiles fail before commit without echoing untrusted values.

Printing uses twelve static trusted named `@page` slots. Validated enums and integer dimensions set size and margins;
code-point-escaped literals and fixed counters set margin boxes through CSSOM. The application never accepts CSS,
HTML, URLs, field expressions or arbitrary rule names. Section wrappers use fixed ordinal classes and force the
section onto a new page. All temporary running text is cleared after printing and context invalidation.

Acceptance requires desktop/mobile insertion, edit, remove, undo/redo, exact save/history and invalid-input proofs;
real two-page PDFs must contain an A4 portrait first page followed by a Letter landscape section with the expected
header, footer and global `Seite 2 von 2`. Fresh isolated recovery binds legacy, one-section, two-section and reset
versions by exact JSON, canonical hash and lineage. No SQL migration, endpoint, dependency, image-decoder, DOCX,
continuous editor pagination, floating object, arbitrary field or ordinary admission change is included.
