# ADR-0153: Bounded native Office text case

Date: 2026-10-08
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office stores one optional character attribute named `textCase`. It accepts exactly `uppercase` or
`smallCaps`; absence remains the canonical default and preserves legacy document bytes. The literal source text is
never rewritten. Browser and server reject lowercase, title case, locale or script controls, arbitrary CSS, URLs and
unknown values.

The responsive character dialog exposes Standard, mixed values, Großbuchstaben and Kapitälchen for a selection or
pending caret input. Reset removes the direct value canonically. One application is one isolated undo step and
remains unavailable for code, readers, historical versions, stale dialogs and uncertain saves.

Text case is inheritable and may be stored in document-owned named styles. A direct text mark has priority over the
inherited style. Each trusted static CSS mapping also neutralizes the other case property so direct uppercase does
not retain inherited small caps and direct small caps does not retain inherited uppercase.

Trusted CSS maps the accepted tokens to `text-transform` and `font-variant-caps` in both editor and print.
Documents never provide style strings. Search, replacement, comparison, suggestions, confirmed CAS saves,
immutable history, reload, reuse and semantic print/PDF operate on and retain the original literal text plus its
canonical presentation token. Recovery versions two and three bind exact uppercase and small-caps profiles.

No SQL migration, endpoint, dependency, external request, provider, worker, locale-sensitive case conversion,
arbitrary typography, DOCX engine or ordinary tenant admission is introduced. Acceptance requires schema, API,
PostgreSQL, recovery and named-style coverage plus pure model and responsive desktop/mobile browser evidence for
selection, mixed values, caret input, reset, undo/redo, save, immutable predecessor, reload, direct precedence,
source-text preservation and real PDF output.
