# ADR-0229 Bounded native Office DOCX run vertical position

## Status

Accepted for the synthetic development preview.

## Decision

- Admit direct `w:rPr/w:vertAlign` values baseline, superscript and subscript. Preserve absence in the prior run
  shape and explicit baseline separately in canonical evidence. Native baseline omits the vertical-position
  attribute; existing native styles do not inherit this attribute.
- Require one marker, one property container, exactly the value attribute and an empty leaf. Refuse duplicates,
  malformed or misplaced markers and manual `w:position` shifts, including zero and mixed declarations, while
  preserving extracted text.
- The API independently validates the position enum and merges super/subscript into the existing native text-style
  mark alongside family, size and color. Shared conversion covers headings, lists, cells, admitted links and
  supported inline page-break segments.
- Reuse existing native vertical-align rendering and declared font sizes. Exact Word glyph-size reduction and
  style inheritance remain outside this native-position profile; no font-size approximation is introduced.
- Reuse source authorization, classification, exact provenance and confirmed save. Verify baseline, mixed marks,
  tables, reopening, actual print-media alignment and measured above/below-baseline PDF text on desktop/mobile.

[WordprocessingML vertical text alignment](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticaltextalignment)
and [manual run position](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.position)
are distinct controls; only the three named alignment values are admitted here.
