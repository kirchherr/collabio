# ADR-0225 Bounded native Office DOCX paragraph pagination

## Status

Accepted for the synthetic development preview.

## Decision

- Read direct `w:pPr/w:keepNext` and `w:keepLines` on main-body ordinary paragraphs and supported headings.
  Admit empty markers and the closed OOXML boolean spellings. Preserve explicit false separately from absence.
- Bind canonical booleans to parser evidence. The preview API independently accepts only structured runs and
  actual booleans, mapping to existing native `keepWithNext` and `keepLines` attributes.
- The native print CSS explicitly maps false to automatic page breaking, including headings whose default
  print presentation otherwise avoids a following break.
- Malformed, duplicate or misplaced markers and keeping controls combined with inline page breaks refuse
  Office preview while plain text remains available. Style inheritance, lists, cells and running text keep
  their established import profile. Oversized groups remain subject to the native browser's pagination rules.
- Reuse exact source authorization, classification, confirmed save and native print. A stored synthetic source
  compares a split control paragraph with a kept heading and paragraph near equivalent page boundaries.
  Verify actual print-media CSS and independent page placement in desktop/mobile Chromium PDFs.

[Keep next paragraph](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.keepnext) ·
[Keep paragraph lines](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.keeplines)
