# ADR-0148: Native Office paragraph pagination controls

Date: 2026-10-08
Status: accepted; development validation, isolated review deployment and publication complete; ordinary tenant and production admission remain closed

Native Office paragraphs and headings may carry the optional boolean attributes `keepWithNext`, `keepLines` and
`pageBreakBefore`. Absence preserves the exact legacy bytes and presentation. Explicit `false` is retained when an
author deliberately overrides an inherited named style. Values are fixed booleans; CSS, HTML, measurements, URLs and
arbitrary break expressions never enter the document format.

The existing multi-paragraph dialog presents each rule as Standard, enabled or disabled and retains the established
mixed-selection behavior. One transaction applies the complete selection and one undo step restores it. The same
fixed controls are available in document-owned named styles, while direct paragraph values continue to override the
style. Text-type conversion, splitting, copying, format transfer, review positions and suggestion replacement retain
the pagination metadata through the existing text-block attribute contract.

The editor and inert print renderer emit only fixed `data-office-*` attributes. Trusted static CSS maps
`keepWithNext` to `break-after: avoid-page`, `keepLines` to `break-inside: avoid-page` and `pageBreakBefore` to a page
break. Legacy page-break aliases are included for the pinned Chromium print engine. These rules affect pagination only;
they do not synthesize content, estimate pages or mutate saved text. Confirmed CAS Save remains the only durability
boundary, and an explicit page break node remains a separate authoring object.

Server validation requires strict Python booleans for direct values and named styles, rejecting integer/string
coercion and nulls in persisted JSON. Existing document-size, node-count, tenant, ACL, classification, immutable
version, audit and recovery boundaries remain unchanged. No SQL migration, endpoint, scheduler, AI provider, external
content, DOCX engine or ordinary tenant admission is introduced.

Acceptance requires server validation, named-style, recovery and model proofs plus desktop/mobile browser evidence for
multi-step editing, undo/redo, confirmed save, immutable predecessor, reload, inert print attributes and a real PDF
with the requested new page. Responsive screenshots must remain readable without horizontal overflow.
