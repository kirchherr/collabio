# ADR-0141: Native Office structural table formulas

Status: Accepted
Date: 2026-10-07

## Context

ADR-0139 introduced bounded local A1 formulas and ADR-0140 added relative range paste, but later row and column
operations still treated stored formula coordinates as literal text. Inserting, deleting, moving, sorting or duplicating
table structure could therefore make a formula point at a different logical cell. A deleted reference also needed a
canonical, persistable failure representation that browser and server could validate independently.

## Decision

Represent every accepted structural transformation with explicit output-to-source row and column maps. Each entry names
one prior coordinate and whether the output is a duplicate. Existing rows and columns map every surviving source
coordinate to its canonical non-duplicate destination. Formula references in those cells follow that identity through
insertion, deletion, direct movement and stable row sorting. A reference whose source row or column was deleted becomes
the exact inert token `#BEZUG!` while every surviving range endpoint continues to map independently.

Duplicated rows and columns receive independent deep-cloned nodes. A copied formula shifts its relative references by
the copy's row and column displacement, while the original formula continues to target the original logical cells.
This preserves spreadsheet-style relative-copy behavior without adding absolute, mixed, sheet or workbook references.

Permit `#BEZUG!` only as the exact canonical error token inside an otherwise supported formula. The browser evaluator
and the independent server parser both treat it as an error value, recalculate the complete simple table and require
the stored visible result to be exactly `#BEZUG!`. Other `#` or `!` forms remain invalid.

Replace the transformed table once in one validated editor transaction and restore the relevant cell selection.
Current write authorization, stale-session checks, readers, historical views, confirmed save, immutable versions,
comparison, print, the 200 x 20 grid and 1,000-formula limit remain unchanged. Formula-bearing merged grids continue to
fail closed under ADR-0139.

## Consequences

Local formulas retain their logical meaning across supported row and column insertion, deletion, movement, stable sort
and duplication. Deleted dependencies remain explicit, deterministic and server-verifiable across save and reload.
No relational migration, workbook runtime, recalculation service or new recovery target is introduced. Absolute and
mixed references, sheet names, cross-table formulas, formula-aware merged cells and full spreadsheet semantics remain
outside this decision.
