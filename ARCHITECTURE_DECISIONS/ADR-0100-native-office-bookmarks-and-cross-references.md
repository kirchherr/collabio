# ADR-0100: Native Office bookmarks and internal cross-references

Date: 2026-09-29
Status: accepted; development validation in progress; ordinary tenant and production admission remain closed

Native Office stores a bookmark as an inline atom with exactly `id` and `label` attributes. The stable ID uses a
restricted lowercase identifier and never comes from HTML. Labels are trimmed, bounded Unicode text and unique within
the document under case-insensitive comparison. A document contains at most 100 bookmarks. Bookmarks carry no content,
URL, script, field expression or external object identity.

An internal cross-reference is an inline text mark with exactly one `targetId`. Its selected visible text remains
ordinary document content. A target may be absent after editing; this is a deliberate, safe broken-reference state.
The UI identifies it clearly and disables navigation. It never guesses by label, retargets automatically or crosses a
document/version boundary.

Users insert or edit a bookmark at the current caret and apply or remove a cross-reference on explicit selected text.
Navigation occurs only through **Zum Lesezeichen springen** and changes only the local editor selection/scroll position;
it does not mutate browser history, load a URL or issue a request. Every edit is one isolated undo step and persists
only through the existing confirmed CAS save.

Printing emits fixed document-local fragment IDs and internal anchors only when the saved target exists. Broken
references print as inert text. History, comparison, copies, search/replacement, reviews and suggestions retain exact
nodes, marks and positions. Acceptance requires strict server/model validation, responsive insert/edit/remove/jump,
broken-target behavior, undo/redo, exact saved versions/copies, semantic PDF output and fresh isolated recovery with
legacy/add/rename/broken/reset versions. Automatic captions, page-number fields, cross-document references, backlinks,
URL previews, DOCX interchange and ordinary admission remain separate.
