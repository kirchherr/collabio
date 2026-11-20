# ADR-0152: Bounded native Office baseline and character spacing

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office stores two optional direct character attributes. `verticalPosition` accepts exactly `superscript` or
`subscript`; `letterSpacing` accepts exactly `tight` or `wide`. Absence remains the canonical default and preserves
legacy document bytes. Browser and server reject numeric offsets, dimensions, percentages, arbitrary CSS, URLs and
unknown values.

The responsive character dialog exposes Standard, mixed values, Hochgestellt, Tiefgestellt, Eng and Weit for a text
selection or pending caret input. Reset removes the direct value canonically. One application is one isolated undo
step and remains unavailable for code, readers, historical versions, stale dialogs and uncertain saves.

Baseline position is direct text formatting only. A block-level paragraph style cannot meaningfully raise or lower
its inline contents, so document-owned styles reject `verticalPosition`. Character spacing is inheritable and may be
stored in a document-owned style. Direct text spacing continues to take precedence over inherited spacing.

Trusted static CSS maps the accepted tokens to `vertical-align` and fixed `em` letter spacing in both editor and
print. Documents never provide style strings. Format transfer, text-type conversion, lists, tables, search and
replacement, comparison, suggestions, confirmed CAS saves, immutable history, reuse and semantic print/PDF retain
the canonical values. The existing character recovery fixture binds exact superscript/wide and subscript/tight
versions without a migration or new store.

No SQL migration, endpoint, dependency, external request, provider, worker, arbitrary numeric typography, DOCX
engine or ordinary tenant admission is introduced. Acceptance requires schema/API/PostgreSQL/recovery/style-boundary
coverage plus pure model and responsive desktop/mobile browser evidence for selection, mixed values, caret input,
reset, undo/redo, save, immutable predecessor, reload, comparison, reuse and real PDF output.
