# ADR-0139: Native Office table clipboard import and local formulas

Status: Accepted
Date: 2026-10-07

## Context

Native Office tables can be created and edited, but pasting a table from Word or Excel previously retained only plain
text. Authors also had no bounded calculation model inside a native table. Clipboard HTML is hostile input and Excel
formula dialects can include external workbooks, macros, vendor extensions and network-capable functions, so neither
source markup nor an unrestricted spreadsheet engine can enter the document contract.

## Decision

Translate exactly one clipboard HTML table into canonical native rows and cells outside an existing table. Strip
scripts, stylesheets, links, media, forms, embedded objects, nested tables and every unrecognized attribute. Preserve
only semantic header cells, bounded row/column spans, text paragraphs, center/right alignment, middle/bottom alignment
and five fixed fill mappings. A bounded quoted-TSV parser is the fallback when no HTML table exists. Both paths enforce
200 rows, 20 columns, 100,000 input characters and the existing canonical document limits before one undoable insert.
Unsupported Excel formula dialects keep their displayed cell value instead of rejecting an otherwise safe HTML table.

Admit an optional formula and formula result only on ordinary unit-span data cells in a simple rectangular table.
Formula source is at most 256 characters and may contain only local references A1 through T200, numeric literals,
parentheses, `+`, `-`, `*`, `/`, ranges and `SUM`, `AVERAGE`, `MIN`, `MAX` or `COUNT`. German `SUMME`, `MITTELWERT`,
`ANZAHL` and semicolons normalize to the canonical grammar. External sheets, workbook names, strings, URLs, macros,
volatile functions and arbitrary identifiers are rejected. A document may contain at most 1,000 formula cells.

The editor recalculates dependent formula cells after local cell changes and stores the canonical source, deterministic
result and identical visible cell text. Fixed errors are `#BEZUG!`, `#DIV/0!`, `#ZYKLUS!`, `#WERT!` and `#LIMIT!`.
Recalculation updates only formula-cell attributes and content outside history so the author's source edit remains one
clean undo/redo step. The server independently parses and evaluates every stored formula against the submitted table
and rejects stale or forged results. Comparison and print expose the stored source/result without executing content.

## Consequences

Authors can paste common Word and Excel tables without losing basic structure and can build small, auditable local
calculations that survive save, history, comparison and print. No clipboard markup, remote image, workbook identity,
external reference, macro, network call, locale-dependent engine, relational schema or new recovery target is added.
Rich inline clipboard formatting, paste-into-selection mapping, cross-table references, sheet semantics, relative
formula rewriting during structural edits, charts bound to formula ranges and full Excel compatibility remain separate.
