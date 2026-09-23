# ADR-0094: Explicit native page breaks

Date: 2026-09-23
Status: accepted; implementation and remote validation pending

Represent an explicit page boundary by the inert, attribute-free leaf
`{"type":"pageBreak"}` at document root depth only, with at most 100 per
document. Existing documents retain their exact canonical bytes. No SQL migration,
endpoint, dependency, image decoder or tenant admission change is required.

Insert through the existing menu or Mod+Enter at an empty top-level paragraph or
heading selection. Split that text block at the caret, preserving both fragments'
attributes and inline marks. At a root gap or a selected root image/rule/table,
insert at the boundary (after the selected block), preserving the selected block.
Reject text ranges and insertion inside lists, quotes, code or table cells.
The visible, selectable marker can be removed through the menu, Delete/Backspace
when selected, or the adjacent paragraph boundary. Each insertion/removal has an
isolated undo transaction, subject to current editing and document-size guards.

Print clears image floats and starts following content on a new page. Headings and
tables following a marker retain their normal pagination behavior. Repeated markers
at one boundary coalesce; a trailing marker requests no empty final page. Leading
markers separate the printed document title from body content. This is a forced
content boundary, not a blank-page or section-layout feature. Markers remain visible
in the screen preview but their labels/borders do not appear in printed output.
Actual A4/Letter PDFs must prove the resulting page boundaries, including images
and tables. Continuous paginated editing and DOCX interchange remain separate.

History, comparison, independent copies and exact source/receipt hashes preserve
the leaf's position. Fresh nonempty isolated recovery must prove a consecutive
insert/remove version chain with exact restored JSON and current ACL enforcement.
Rollback must retain a compatible reader for existing page-break versions.
