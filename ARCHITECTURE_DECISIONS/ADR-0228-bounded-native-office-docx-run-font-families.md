# ADR-0228 Bounded native Office DOCX run font families

## Status

Accepted for the synthetic development preview.

## Decision

- Admit direct `w:rPr/w:rFonts` with exactly matching case-insensitive `ascii` and `hAnsi` names Arial,
  Georgia or Consolas. Map them to native sans, serif and mono choices, whose primary CSS faces match those
  source names. Preserve absent font assignment in the old run shape.
- Require exactly those two font attributes, one property container and one font marker. Refuse theme bindings,
  mixed names, additional script/hint attributes, explicit complex-script selection and malformed evidence.
- Limit these directly assigned runs to Latin blocks U+0000–024F and U+1E00–1EFF, combining marks U+0300–036F,
  common punctuation U+2000–206F and currency U+20A0–20CF. Other script selection remains outside this profile.
  Unsupported font evidence refuses Office preview while plain extracted text stays available.
- The API independently validates the native family enum and combines family, size and color in one text-style
  mark. Reuse shared conversion for headings, lists, cells, admitted links and supported page-break segments.
- Reuse existing browser font fallbacks. Font files, font installation, embedded-font fidelity, style inheritance
  and exact Word layout remain outside this native-family import. No source font data is loaded or executed.
- Verify an authorized stored synthetic source through classification, exact provenance, confirmed save, reopening,
  actual print CSS, distinct PDF font families and equal monospace glyph advances on desktop and mobile.

[WordprocessingML run fonts](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.runfonts)
defines separate ASCII, High ANSI, complex-script and East Asian assignments; this profile admits the paired Latin assignment.
