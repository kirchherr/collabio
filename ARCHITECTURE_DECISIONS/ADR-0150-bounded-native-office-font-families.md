# ADR-0150: Bounded native Office font families

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office stores an optional `fontFamily` character attribute with exactly three tokens: `sans`, `serif` and
`mono`. Absence remains the canonical default and preserves every legacy document byte. Each token maps through
trusted static CSS to a fixed local fallback stack; documents cannot store CSS, font filenames, URLs, provider names
or arbitrary family strings.

The character dialog exposes Standard, Sans Serif, Serif and Monospace with the existing mixed-selection behavior.
It applies to a selection or pending caret input, resets canonically and remains unavailable for code, readers,
historical versions, stale dialogs and uncertain saves. One application is one isolated undo step.

Document-owned named styles use the same tokens. A style family is inherited by every bound paragraph or heading,
while an explicit text mark retains precedence. Preview, format transfer, text-type conversion, lists, tables,
search/replacement, comparison, suggestions, confirmed CAS saves, immutable history, reuse and print/PDF preserve the
same canonical value.

Browser and server validate the token independently. Rendering emits only `data-office-font-family` and fixed CSS;
there is no `style` attribute, font download, network resolution, embedded font, external provider or document-engine
call. The existing Office JSON version, canonical-size, tenant, ACL, classification, audit and recovery boundaries
remain authoritative.

No SQL migration, endpoint, dependency, background worker, new recovery store, arbitrary font catalog, DOCX engine
or ordinary tenant admission is introduced. Acceptance requires server schema/API coverage plus pure model and
responsive desktop/mobile browser evidence for direct formatting, mixed values, caret input, undo/redo, named-style
inheritance, explicit override, save, immutable predecessor, reload, comparison, reuse and semantic PDF output.
