# ADR-0101: Native Office figure captions, numbering and references

Date: 2026-09-29
Status: accepted; development validation in progress; ordinary tenant and production admission remain closed

Native Office keeps the existing bounded literal image caption for backward compatibility. A caption becomes a
numbered semantic figure only when the image also owns a stable `figureId`. The identifier is generated locally,
contains no tenant, object, URL or executable data, remains stable when an image moves, and is unique within the
document. Legacy images and unnumbered captions retain their exact stored representation.

The visible figure number is derived from the current root document order. It is never stored. Moving, inserting or
removing figures therefore updates numbering deterministically without mutating unrelated image nodes. Editor,
comparison and print surfaces use the same ordered inventory. A numbered figure requires non-empty caption text;
removing numbering preserves the literal caption and removes only the stable destination identity.

Existing internal cross-reference marks may target either a bookmark or a figure ID. The selection UI names the target
kind and current figure number. Deliberate jump changes only the local editor selection and scroll position. Removing
a figure leaves an inert visible broken reference. IDs are unique across bookmark and figure destinations so a target
can never resolve ambiguously.

Print output emits a semantic `figure`/`figcaption`, a fixed local destination and the derived label
`Abbildung N: …`. Resolved references become local anchors; broken references remain spans. No URL, fetch, browser
history change, field expression or cross-document lookup is introduced. Acceptance requires strict schema/model
validation, responsive numbered/unnumbered editing, reorder renumbering, exact save/history/copy behavior, local PDF
links and a fresh legacy/add/reorder/broken/reset recovery sequence. Table captions, arbitrary page fields,
cross-document references, backlinks and DOCX interchange remain separate.
