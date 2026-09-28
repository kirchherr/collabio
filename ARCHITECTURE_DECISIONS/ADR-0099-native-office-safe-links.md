# ADR-0099: Native Office safe links

Date: 2026-09-28
Status: accepted; development validation in progress; ordinary tenant and production admission remain closed

Native Office stores links as an inline `link` mark with exactly one `href` attribute. The target is bounded to 2,048
characters and must be either an absolute HTTPS URL without credentials or a simple `mailto:` address without query,
fragment or multiple recipients. HTTP, script/data/file schemes, controls, whitespace, backslashes and HTML-delimiter
characters are rejected by both client and authoritative server validation.

Users select explicit text and open a responsive dialog to add, replace or remove its target. No autolinking, paste
rule, background fetch, preview request, redirect resolution or automatic navigation is permitted. The stored link is
opened only by the user's dedicated **Link bewusst öffnen** action in a new `noopener,noreferrer` browsing context.
Editing is one isolated undo step and persists only through the existing confirmed CAS version save.

Printing creates an inert semantic anchor with the validated target and `noopener noreferrer`. Search/replacement,
comparison, history, independent copies, reviews and suggestions retain exact mark boundaries and targets. Links do
not participate in format transfer. Inline code cannot carry a link.

Acceptance requires server/model rejection of unsafe targets, responsive add/edit/remove and explicit-open controls,
isolated undo/redo, exact saved/historical/copy behavior, semantic PDF output, and fresh isolated recovery with
legacy/add/edit/remove versions. No bookmark, cross-reference, automatic link recognition, URL metadata fetch,
tracking parameter rewrite, arbitrary field, DOCX interchange or ordinary admission change is included.
