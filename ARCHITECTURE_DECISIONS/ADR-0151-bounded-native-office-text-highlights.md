# ADR-0151: Bounded native Office text highlights

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office stores an optional direct `highlightColor` character attribute with exactly six tokens: `yellow`,
`lime`, `cyan`, `pink`, `lavender` and `gray`. Absence remains the canonical default and preserves legacy document
bytes. Trusted static CSS maps the tokens to fixed opaque, print-safe colors. Documents cannot store CSS, color
literals, alpha values, gradients, URLs, files or arbitrary names.

The responsive character dialog exposes Standard, the six colors and the existing mixed-selection behavior. It
applies to a selection or pending caret input, resets canonically and remains unavailable for code, readers,
historical versions, stale dialogs and uncertain saves. One application is one isolated undo step.

Highlights remain direct character formatting. Document-owned paragraph styles reject the attribute so a text
highlight cannot silently become full-width paragraph shading. Format transfer, text-type conversion, lists, tables,
search/replacement, comparison, suggestions, confirmed CAS saves, immutable history, reuse and print/PDF preserve the
canonical direct value.

Browser and server validate the token independently. Rendering emits only `data-office-highlight-color` and fixed
CSS with print color adjustment; there is no `style` attribute, external request, provider or document-engine call.
The existing Office JSON version, canonical-size, tenant, ACL, classification, audit and recovery boundaries remain
authoritative.

No SQL migration, endpoint, dependency, background worker, new recovery store, arbitrary color picker, paragraph
shading, DOCX engine or ordinary tenant admission is introduced. Acceptance requires schema/API/PostgreSQL/recovery
coverage plus pure model and responsive desktop/mobile browser evidence for selection, mixed values, caret input,
reset, undo/redo, save, immutable predecessor, reload, comparison, reuse and semantic PDF output.
