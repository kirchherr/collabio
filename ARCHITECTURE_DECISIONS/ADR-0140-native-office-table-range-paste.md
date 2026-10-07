# ADR-0140: Native Office table range paste

Status: Accepted
Date: 2026-10-07

## Context

ADR-0139 translates a Word or Excel clipboard table into a new native Collabio table. Inside an existing table the
editor still fell back to plain text, so a copied range was appended to one cell. Authors could not replace a selected
range or extend an existing table with copied rows, and formulas retained coordinates from the clipboard source.
Clipboard markup remains hostile input and range mapping must not weaken the existing document, formula or ACL limits.

## Decision

Map a sanitized simple rectangular clipboard table into a simple native target table. A single target cell is the
origin of the pasted range and may extend the target up to the existing limits of 200 rows and 20 columns. A rectangular
multi-cell selection accepts an exactly matching source rectangle or repeats one source cell across the selection.
Dimension mismatches, merged grids, invalid spans and limit overflow leave the draft unchanged.

Preserve the target cell's semantic header or data-cell type. Replace its content and bounded cell presentation with
the sanitized source values. Admit only bold, italic, underline, strike and inline-code marks from clipboard cell text;
links remain plain text, while scripts, stylesheets, media, forms, frames, embedded objects and nested tables remain
excluded. Added cells continue a complete first header row or first header column without accepting clipboard-defined
structural privilege changes inside the target.

Shift every admitted local A1:T200 formula by the pasted row and column offset before recalculating the complete target
table. Any shifted reference outside the supported coordinate space rejects the paste. The existing browser and server
formula validators remain authoritative; no workbook, sheet, external reference, macro or network-capable expression
is introduced.

Replace the complete target table in one validated transaction, select the resulting pasted range and create one
undoable history step. Current write authorization, session freshness, canonical document limits, confirmed save,
immutable versions, comparison and print remain unchanged.

## Consequences

Authors can copy common formatted ranges and local formulas from Word or Excel directly into an existing Collabio table,
including adding rows or columns from one starting cell. Failed imports are atomic. No raw clipboard markup, external
resource, relational schema, spreadsheet runtime or new recovery target is added. Absolute references, workbook/sheet
semantics, merged-range mapping and formula-aware row or column restructuring remain outside this decision.
