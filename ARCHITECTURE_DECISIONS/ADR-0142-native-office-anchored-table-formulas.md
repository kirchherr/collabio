# ADR-0142: Native Office anchored table formulas

Status: Accepted
Date: 2026-10-07

## Context

ADR-0139 admitted bounded local A1 formulas, and ADR-0141 keeps their logical targets stable through table structure
changes. Formula normalization still removed every `$`, so authors could not preserve a row, a column or both while
copying a formula. Common Excel and Word table calculations therefore required manual correction after range paste or
row and column duplication.

## Decision

Extend the existing local reference grammar with the four canonical forms `A1`, `$A1`, `A$1` and `$A$1` inside the
unchanged A1:T200 coordinate space. A `$` is valid only immediately before a supported column letter or row number.
Malformed, repeated or detached anchors fail closed. Browser and server tokenize, evaluate and validate the same
canonical source independently; no source workbook, sheet identity or external reference is admitted.

When a clipboard range or duplicated row or column copies a formula, shift only unanchored axes. A fixed column keeps
its column, a fixed row keeps its row and a fully fixed reference keeps both. Formula ranges apply the rule separately
to both endpoints. References that move outside the global supported coordinate space reject the copy atomically.

When the table itself changes, anchored references still follow the identity of their logical source cells under
insertion, deletion, direct movement and stable sorting. Preserve the `$` markers on the rewritten coordinate. A
deleted logical dependency becomes the canonical `#BEZUG!` token from ADR-0141. Duplicated structures remain deep
clones, so formula rewriting never mutates the original cell.

Keep formula entry in the existing accessible dialog and describe the three anchor forms there. One formula edit or
structural action remains one validated undo step. Current authorization, stale-session, reader, historical-version,
simple-grid, formula-count, document-size, confirmed-save, comparison and print boundaries remain unchanged.

## Consequences

Authors can paste and duplicate practical running-total, fixed-rate and mixed lookup formulas without manual coordinate
repair. Sources and deterministic results survive immutable versions, reload, comparison and print. No relational
migration, spreadsheet runtime, workbook model or new recovery target is added. Named ranges, sheets, cross-table
references, dynamic arrays and full Excel formula compatibility remain outside this decision.
