# ADR-0223 Bounded native Office DOCX paragraph spacing

## Status

Accepted for the synthetic development preview.

## Decision

- Read direct `w:pPr/w:spacing` on main-body ordinary paragraphs and supported headings. Convert explicit
  before/after values of 0, 120, 240, 360 and 480 twips to the existing native 0, 6, 12, 18 and 24 point values.
  Convert automatic line values 240, 276, 360 and 480 to native ratios 1, 1.15, 1.5 and 2. An omitted line rule
  and explicit `auto` have the same canonical representation.
- Preserve explicit zero and absent values separately. An empty spacing element keeps the prior block shape.
  Bind the canonical values to parser evidence. The API independently validates types and the native enums,
  including rejecting booleans used as numbers.
- Malformed markers, unsupported units, automatic/line-based paragraph spacing, fixed/minimum line height and
  spacing on paragraphs containing inline page breaks refuse Office preview while plain text remains available.
  The profile covers direct paragraph formatting. Style inheritance, lists, cells and running text retain their
  established import profile.
- Reuse existing native attributes, source authorization, classification, confirmed save and print. Verify saved
  values and computed layout in Chromium, followed by independent word-position measurements in both PDFs.
- Filter normalized MIME type on each object's latest metadata before applying the 500-candidate discovery bound.
  This prevents newer native saves from displacing stored DOCX candidates. Authoritative ACL checks still apply
  to each candidate. Filtering follows latest-version selection so an old DOCX cannot replace a newer non-DOCX.

[WordprocessingML spacing](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.spacingbetweenlines)
