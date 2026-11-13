# ADR-0222 Bounded native Office DOCX paragraph alignment

## Status

Accepted for the synthetic development preview.

## Decision

- Read direct `w:pPr/w:jc` on top-level ordinary paragraphs and supported headings. Admit physical `left`,
  `center`, `right` and `both`, mapping `both` to native `justify`. Apply the same direct alignment to each
  text segment when an existing inline page break splits a paragraph.
- Bind the canonical alignment to the parser block hash. The API independently accepts only the native alignment
  enum on structured paragraph or heading runs and continues to compare source text. Older paragraph and heading
  blocks keep their existing representation.
- Unsupported or malformed direct alignment in the admitted location refuses the Office preview while text
  extraction remains available. Style inheritance, direction-dependent alignment, lists, table cells, images and
  running text are outside this alignment profile.
- Reuse the existing native attributes, authorization, classification, confirmed save and print. Verify the
  editor, saved version, print markup and positions in tagged Chromium PDFs on desktop and mobile.

[WordprocessingML justification values](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.justificationvalues)
