# ADR-0134: Native Office table layouts

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables preserve semantic grids, spans and bounded cell formatting, but every table still uses one full
width grid presentation. Authors need useful visual hierarchy and page placement without arbitrary CSS, pixel widths,
drag-only resizing or a spreadsheet layout engine.

## Decision

Admit optional table-level tokens for style (`minimal`, `banded`, `accent`), width (`wide`, `compact`), alignment
(`center`, `right`), column distribution (`first-wide`, `first-narrow`) and top caption placement. Omission means the
existing grid, full width, left alignment, equal columns and bottom caption. Browser and server independently reject
unknown keys, arbitrary dimensions, style strings and layout expressions.

The accessible **Tabellenlayout …** dialog edits all five dimensions and resets them together. Apply and reset each
produce one validated undo step. Caption add, edit and remove preserve layout; layout changes preserve caption IDs and
text. Editor, comparison and print consume the same canonical attributes and fixed CSS mappings. Narrow viewports
use the available width while retaining style, column emphasis and semantics. The mobile table toolbar remains
scrollable and compact enough to keep the document canvas reachable.

## Consequences

Authors can create restrained report, comparison and compact reference tables with predictable responsive and print
output. Existing documents and default layouts retain their canonical bytes because defaults remain absent. The
change adds no arbitrary styling, absolute dimensions, spreadsheet calculation, database migration, tenant
activation or document-engine admission.
