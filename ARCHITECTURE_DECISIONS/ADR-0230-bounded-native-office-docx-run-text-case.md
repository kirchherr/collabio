# ADR-0230 Bounded native Office DOCX run text case

## Status

Accepted for the synthetic development preview.

## Decision

- Admit one direct `w:rPr/w:caps` or `w:rPr/w:smallCaps` leaf per run. Missing `w:val` enables the property;
  admit the explicit on/off values true/false, 1/0 and on/off with their exact spelling.
- Canonical evidence carries `text_case` as uppercase, smallCaps or normal. Absence retains the prior shape;
  explicit disabling is distinct from absence and omits the native case attribute. Source Unicode text stays
  unchanged in extraction, preview, saved content and provenance.
- Refuse duplicate, misplaced, non-leaf, malformed and jointly present caps/smallCaps declarations, including
  disabled combinations. Preserve text extraction but refuse the Office preview for unsupported evidence.
- Validate the enum independently in the API and merge enabled casing into the existing native text-style mark.
  Shared conversion covers headings, lists, cells, admitted internal links and supported page-break segments.
- Use the existing native uppercase and small-caps CSS rendering, including its browser/font fallback behavior.
  Permit small-cap synthesis on explicitly small-caps-marked native ranges so local fallback fonts render the
  requested glyphs despite the global synthesis restriction. Other synthesis controls retain their existing values.
  Exact Word small-cap sizing, glyph metrics, locale-specific fidelity and style inheritance remain separate.
- Reuse stored-source authorization, classification, exact provenance and confirmed save. Prove unchanged stored
  text and actual print CSS in real desktop/mobile browsers and independently inspect the complete PDFs.

Microsoft documents [caps](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.caps)
and [smallCaps](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.smallcaps)
as display properties which leave the underlying Unicode text unchanged and cannot coexist on one run.
The [CSS Fonts small-cap synthesis control](https://www.w3.org/TR/css-fonts-4/#font-synthesis-small-caps)
allows this fallback independently of weight and style synthesis.
