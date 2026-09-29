# ADR-0102: Native Office table captions, numbering and references

Date: 2026-09-29
Status: proposed; development validation pending; ordinary tenant and production admission remain closed

Native Office tables may carry an optional literal `caption` and stable `tableId`. Both attributes are present together
or absent together, so every captioned table is an unambiguous document-local destination while legacy tables retain
their exact representation. Captions are bounded inert text. Identifiers contain no tenant, object, URL or executable
data, remain stable across table edits and moves, and are unique within the document.

Visible table numbers are derived from the order of captioned tables in the current document and are never stored.
Figures and tables use independent sequences. Inserting, removing or reordering a table therefore renumbers only the
visible table labels and does not rewrite references or unrelated nodes. Caption add, edit and removal are isolated
undo groups and persist only through the existing confirmed CAS save.

The existing internal cross-reference mark may target bookmarks, figures or tables. Deliberate jump changes only the
local editor selection. Removing a caption removes its destination identity and leaves any reference as visible inert
text with an explicit unavailable-target state. No URL, request, cross-document lookup or implicit replacement is
introduced.

Print emits native `table`/`caption` markup with a fixed local destination and the same derived `Tabelle N: …` label.
Resolved references become local anchors; broken references remain spans. Acceptance requires strict schema/model
validation, responsive add/edit/remove and undo behavior, separate figure/table numbering, exact immutable history,
comparison and copies, local PDF links, and a fresh legacy/add/reorder/broken/reset recovery sequence. Arbitrary page
fields, cross-document references, backlinks and DOCX interchange remain separate.
