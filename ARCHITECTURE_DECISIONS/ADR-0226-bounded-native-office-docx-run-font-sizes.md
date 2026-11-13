# ADR-0226 Bounded native Office DOCX run font sizes

## Status

Accepted for the synthetic development preview.

## Decision

- Admit direct run `w:rPr/w:sz` values that exactly map from half-points to the existing native point sizes
  8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36 and 48. Preserve absent size in the old run representation.
- Optional `szCs` must agree with `sz`. Complex-script-only, conflicting, malformed and unsupported sizes refuse
  Office preview. Script-based size selection and style inheritance remain outside the profile. Extracted text
  remains available when unsupported size evidence is carried by a text run.
- Bind canonical integer size to parser structure evidence. The API independently validates the native enum
  and actual integer type and emits a native `textStyle` mark. Unknown run fields remain invalid.
- Reuse shared run conversion for paragraphs, headings, list text and table cells. Preserve existing marks,
  admitted internal links and the size of text segments across supported inline page breaks.
- Reuse exact source authorization, classification, confirmed save and print. Verify mixed sizes, bold text and
  header cells from a stored source on desktop/mobile, including actual print-media CSS and PDF text dimensions.

[WordprocessingML run font size](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.fontsize)
