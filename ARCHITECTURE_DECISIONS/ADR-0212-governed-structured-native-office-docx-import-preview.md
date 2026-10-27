# ADR-0212: Governed structured native Office DOCX import preview

## Status

Accepted for the bounded development preview path. Productive DOCX import/export, round-trip fidelity, external
engines and automatic persistence remain closed.

## Context

ADR-0211 accepts one exact, currently readable DOCX source version and produces a non-persisting native preview, but
requires manual object/version identifiers and flattens all extracted content into paragraphs. That is secure but not
usable enough for ordinary source selection and loses basic document structure.

## Decision

- Add a metadata-only source-discovery endpoint over current source heads. It returns at most 50 DOCX entries whose
  current authoritative ACL is readable by the current tenant user. It never returns source bytes or extracted text.
- Bind selection to the returned immutable object/version pair. Preview execution repeats tenant, current-ACL,
  manifest and content-hash validation before dispatch, so discovery is not authorization.
- Extend the bounded parser artifact with an inert `document_blocks` collection. The API accepts only paragraphs,
  heading levels 1-3, flat bullet/ordered lists and rectangular unmerged tables up to 200 rows by 20 columns.
- Parse only `word/document.xml` and optional `word/numbering.xml`; reject DTD/entity declarations, malformed XML,
  merged/non-rectangular/oversized tables, active content and transport/schema drift. No relationships are fetched and
  no external process, network, storage, database, provider or vector credential is available to the parser.
- Bind the canonical structure to a dedicated SHA-256 evidence value, then independently translate and validate the
  parser structure against the existing native Office document schema.
  Unsupported formatting remains flattened or rejected and `fidelity_preserved` remains false.
- Preserve exact source object/version/content hash, current ACL version, parser profile and parsed-text hash under
  `bounded_structured_docx_preview`. Saving still requires the existing explicit user confirmation.
- Audit only identifiers, counts, hashes and boolean state. Search terms, source bodies and extracted text are not
  written to ordinary logs or audit metadata.

## Consequences

The import dialog is usable without knowing internal IDs and basic headings, lists and simple tables survive the
preview/save round trip. The endpoint deliberately lists only current heads and does not promise folder browsing,
historical discovery, styles, drawings, images, headers/footers, comments, tracked changes, fields, merged tables or
OOXML fidelity. Productive candidate-version writes, export, engine admission, WOPI and indexing remain separate
release gates.
