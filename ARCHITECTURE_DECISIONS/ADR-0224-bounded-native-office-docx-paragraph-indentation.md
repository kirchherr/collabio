# ADR-0224 Bounded native Office DOCX paragraph indentation

## Status

Accepted for the synthetic development preview.

## Decision

- Read direct `w:pPr/w:ind` on main-body ordinary paragraphs and supported headings. Admit physical left/right
  values of 0, 360, 720, 1080 and 1440 twips and map to native 0, 18, 36, 54 and 72 point values. Admit explicit
  first-line and hanging values 0, 360 and 720 twips.
- Map positive hanging indentation only with an explicit left value at least as large. Subtract the hanging
  amount from the native left margin because the native hanging format adds padding before shifting the first
  line back. This preserves the WordprocessingML first-line and continuation-line positions.
- Preserve explicit zero and absence separately. Zero special indentation maps to native `none`; an empty
  indentation element keeps the old block shape. Bind the canonical values to parser evidence and validate
  native types and enums independently in the preview API.
- Refuse malformed or conflicting markers, negative/unsupported values, character-based or directional units,
  bidirectional/mirrored paragraphs and inline page breaks with indentation. Extracted text remains available.
  Style inheritance, lists, cells and running text retain their existing import profile.
- Reuse source authorization, classification, confirmed save and native print. Check saved values, computed
  layout and independent word positions in desktop/mobile Chromium PDFs.

[WordprocessingML indentation](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.indentation)
