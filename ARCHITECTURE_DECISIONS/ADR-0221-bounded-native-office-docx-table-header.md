# ADR-0221 Bounded native Office DOCX table header

## Status

Accepted for the synthetic development preview.

## Decision

- Admit one explicitly enabled `w:tblHeader` in the first physical row of a rectangular main-body table.
  The parser accepts the empty marker and the closed OOXML boolean spellings. Explicitly disabled markers
  have the same canonical representation as an absent marker.
- Reject misplaced, duplicated or malformed markers, enabled markers after the first row, and layouts with
  nested tables or skipped grid positions. The existing row and column bounds apply.
- Bind `header_row: true` to canonical parser evidence. The API independently accepts only the canonical
  boolean and maps the first row to native header cells. Horizontal spans are supported. Vertical spans from
  the header into the body are rejected because the native print renderer uses separate row groups.
- Reuse the exact-source access check, classification, confirmed save and existing native print renderer.
  Verify semantic header cells and repeated visible header text in a multi-page Chromium PDF from a stored
  synthetic source on desktop and mobile.

[WordprocessingML table header](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tableheader)
