# ADR-0227 Bounded native Office DOCX run text colors

## Status

Accepted for the synthetic development preview.

## Decision

- Admit direct `w:rPr/w:color` with exactly one `w:val` from the eight RGB values of the existing native palette.
  RGB spelling is case-insensitive; canonical evidence contains the native color name. Absent color preserves
  the legacy run shape. Colors are exact; no nearest-color conversion is performed.
- Map 111827/475569/B91C1C/9A3412/166534/115E59/1D4ED8/7E22CE to
  black/slate/red/orange/green/teal/blue/purple. Native black is specifically 111827, not 000000.
- Refuse automatic, theme-based, tinted, shaded, malformed, duplicate, misplaced and out-of-palette colors in
  Office preview while extracted text stays available. Style inheritance remains outside this profile.
- Validate actual string type and native palette independently at the API. Combine color and size in one native
  text-style mark, preserving existing marks, admitted internal links and shared list/table/page-break conversion.
- Reuse exact source authorization, classification and confirmed save. Verify an editor-only stored synthetic
  source through desktop/mobile import, readback, reopening, actual print-media colors and independent PDF colors.

[WordprocessingML run content color](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.color)
defines explicit, automatic and theme-based colors separately. Only explicit native-palette values are admitted here.
