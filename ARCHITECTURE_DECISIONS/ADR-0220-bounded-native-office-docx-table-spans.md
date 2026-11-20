# ADR-0220 Bounded native Office DOCX table spans

## Status

Accepted for the synthetic development preview.

## Decision

- Admit explicit `gridSpan` and `vMerge` on main-body tables with at most 20 logical columns and 200 rows.
  A vertical continuation must directly follow a restart or continuation over the exact same columns and
  contain no nonblank text. Require complete rectangular rows and at least one native cell anchor per row.
- The parser reads only local XML and hashes physical cells, spans, continuation flags and runs. The API
  independently reconstructs the rectangular native grid and checks it through the existing native schema.
  Text equality compares physical cell text in source order. Empty vertical continuation cells contribute
  only their cell boundaries.
- Preserve the old wire shape for simple tables. Reject deprecated horizontal merge markers, skipped grid
  positions, nested tables in the new profile, malformed spans, unmatched continuations and nonempty
  continuation cells. Table styles, widths and repeating header behavior remain outside the import profile.
- Reuse exact-source authorization, classification, explicit native save, stored versions and native print.
  Verify both span directions with the unmocked stored synthetic source on desktop and mobile.

No migration, storage, dependency or production admission is required.

[Grid span](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridspan) ·
[Vertical merge](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.verticalmerge)
