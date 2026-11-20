# ADR-0214: Bounded native Office DOCX page breaks

## Status

Accepted for the bounded development preview path. Section profiles, headers/footers, pagination fidelity and
productive DOCX import/export remain closed.

## Context

ADR-0213 preserves bounded inline marks but still treats DOCX page transitions as plain line breaks. Native Office
already has strict page-break nodes and paragraph `pageBreakBefore`, so the safe subset can be preserved without an
external layout engine.

## Decision

- Recognize only explicit `w:br w:type="page"`, `w:lastRenderedPageBreak` and enabled paragraph
  `w:pageBreakBefore` in the already authorized local `word/document.xml`.
- Split ordinary paragraph runs around hard page breaks and emit at most 100 inert page-break blocks. Preserve
  paragraph `pageBreakBefore` as a strict boolean native attribute.
- Reject hard breaks inside headings, numbered/list paragraphs and table cells because their cross-break structure is
  ambiguous in the bounded preview. Continue rejecting tracked revisions and active content.
- Exclude page-break nodes from plain-text derivation while independently requiring normalized structured text to
  equal the separately hash-bound parser text. The canonical structure hash includes every break and attribute.
- Reuse the existing native page-break schema, rendering, explicit confirmed save and exact provenance round trip.
  Add no page geometry inference, automatic pagination or hidden external layout call.

## Consequences

Explicit DOCX page transitions survive the bounded preview/save path and are visible in editor and print semantics.
Section breaks, page sizes, margins, columns, headers/footers, page numbering, widow/orphan layout and exact Word
pagination remain separate fidelity work. Images and relationships remain a separate hardened import boundary.
