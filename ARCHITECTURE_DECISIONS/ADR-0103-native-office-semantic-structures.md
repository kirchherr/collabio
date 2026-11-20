# ADR-0103: Native Office semantic structures

## Status

Accepted

## Context

Collabio Office already preserves literal rich text, page structures, images, links, bookmarks and numbered figures and tables. Reusable fields, generated navigation, notes, citations and formulas still required manual text. Persisting their rendered output would become stale after edits, while scripts, remote resolvers or formula engines would widen the document attack surface.

## Decision

The native document format adds a bounded document-owned field catalog and citation-source catalog. Inline atoms identify field uses, footnotes, endnotes and citations. Top-level atoms identify a table of contents, bibliography, inert equation and reference navigator. IDs are stable and opaque where identity matters; visible numbering is derived from document order.

All source strings remain literal data. Formulas are never evaluated. Sources are never fetched. Generated views read only the current validated document. Missing field and citation catalog entries remain visible as broken references. Removing a catalog entry never removes its uses. The server and browser enforce exact shapes, identifier syntax, control-character restrictions, uniqueness and limits.

The editor offers one keyboard-reachable structure dialog. Catalog updates and insertions are ordinary ProseMirror transactions, so undo and redo retain their normal boundaries. Stored JSON remains authoritative for saves, immutable versions, comparisons, reuse and recovery. Print builds semantic DOM using `textContent` and appends note lists; it never parses document HTML.

Running text may use the explicit token `{{field:key}}`. Print resolves it only against the same version-owned field catalog. Missing fields render visibly and resolved running text must still satisfy the 64-character running-text limit.

## Consequences

- Reordering notes and equations deterministically renumbers their derived presentation without changing stable IDs.
- Generated tables of contents, bibliographies and reference overviews cannot become silently stale persisted copies.
- Field values and source metadata travel with copied documents and exact historical versions.
- Formula layout is deliberately a literal accessible first slice; mathematical evaluation, macros and external engines remain outside this format.
- Cross-document references, global backlinks and DOCX interchange remain separate because they require fresh authorization, lifecycle and fidelity contracts.
