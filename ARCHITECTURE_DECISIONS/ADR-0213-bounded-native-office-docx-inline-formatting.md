# ADR-0213: Bounded native Office DOCX inline formatting

## Status

Accepted for the bounded development preview path. Style fidelity, tracked changes, productive DOCX import/export and
automatic persistence remain closed.

## Context

ADR-0212 preserves headings, flat lists and simple tables, but flattens every text run. This loses common emphasis and
does not independently prove that the parser's plain-text evidence describes the same content as its structured tree.

## Decision

- Extend inert DOCX blocks with ordered text runs carrying only `bold`, `italic`, `underline` and `strike` marks.
  Mark order is canonical; duplicates, unknown marks, empty runs, surplus fields and excessive run counts fail closed.
- Read only direct OOXML run properties from the already authorized local `word/document.xml`. Do not resolve themes,
  styles, relationships, fonts, colors, fields, URLs or any external resource.
- Preserve allowed runs in ordinary paragraphs, heading levels 1-3, flat list items and simple table cells. Existing
  legacy string blocks remain readable during the parser/API rolling boundary.
- Reject tracked insertions, deletions and moves because selecting a revision view requires a separate user-visible
  policy. Do not silently merge accepted and rejected revision states.
- Derive plain text independently from the structured tree and require its normalized value to equal the separately
  hash-bound parser text before native mapping. Continue binding the canonical tree to its structure hash.
- Translate marks to the existing strict native Office schema. Saving remains an explicit confirmation and retains
  exact source/version, ACL, content, parser-text and parser-structure provenance.
- Audit only identifiers, hashes, counts and bounded state. No source text, extracted runs or document body enters
  ordinary logs or audit metadata.

## Consequences

Common inline emphasis survives the bounded preview/save round trip without introducing an external document engine.
Run styles, colors, fonts, sizes, highlighting, hyperlinks, fields, comments, revision acceptance, images, drawings,
headers/footers, sections, merged tables and round-trip fidelity remain outside this gate. Productive candidate writes,
export, WOPI, indexing, tenant activation and production admission remain separate decisions.
