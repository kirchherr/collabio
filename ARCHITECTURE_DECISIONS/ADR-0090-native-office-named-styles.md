# ADR-0090: Document-owned native Office format styles

Date: 2026-09-22
Status: accepted for implementation; acceptance evidence belongs in CURRENT_HANDOFF.md

## Decision

Extend native v1 additively with an optional root `attrs.styles` catalog (maximum 20 definitions) and optional
`styleId` on paragraphs/headings. A definition contains a stable local ID, unique literal name of 1–60 Unicode
characters, paragraph values and character base values. Only existing enum-based alignment, spacing, font sizes and
colors are accepted. Unknown fields, duplicate IDs/names, invalid references, controls and unsupported placements
fail closed. The complete catalog counts toward the existing canonical byte limit. Absent attributes preserve legacy
canonical bytes. There is no new SQL table, endpoint, dependency or global template registry.

Styles govern presentation; semantic paragraph/heading types remain the separate Texttyp choice. Presets for body,
title and heading appearance become document definitions only on explicit application. The single Formatvorlagen
dialog provides selection count, catalog choice, name, six bounded presentation fields, live inert preview and the
number of paragraphs affected by a shared update. Updates change all bound blocks, including nested lists/tables.
Apply sets a style reference and clears direct paragraph attributes on the selected supported blocks. Inline marks
remain explicit overrides. Subsequent direct paragraph values override the style; their Standard choice inherits it.
Removing the binding returns to direct/default formatting. It does not delete text or the reusable catalog entry.
All operations remain local until an ordinary confirmed CAS save creates a new immutable version.

The editor uses existing ProseMirror document-attribute transactions and inert node decorations. Explicit paragraph
attributes win over inherited decorations; existing fixed CSS allowlists render character base values. Print resolves
the same effective values. Comparison expands inherited presentation for block identity and includes catalog changes,
including unused definitions. Neither comparison nor rendering rewrites the saved source. Draft reuse and historical
takeover own the exact source catalog; catalogs never cross a document boundary implicitly.

Actions bind editor, session, context, revision, document, selection and pending marks. Current read/history/busy/
uncertain/review/suggestion guards, full document validation, isolated undo and pending typing marks apply. Structural
paragraph transformations preserve bindings where the target supports them; code has no style binding. Plain text
paste introduces no foreign catalog. Format transfer remains explicitly limited to direct presentation values and
does not transfer style identity. Document resets preserve reusable definitions.

This adds durable native metadata: acceptance requires Python schema/API/PostgreSQL tests, model/browser/responsive
proofs, actual print checks and a fresh nonempty PostgreSQL/S3 recovery with legacy and styled versions before rollout.
Ordinary tenant, pilot, engines and indexing remain closed. Office remains ahead of CRM.

## References

- Existing ADR-0086/0087 paragraph and character enum contracts.
- [ProseMirror document-attribute transactions](https://github.com/ProseMirror/prosemirror-transform/blob/master/src/transform.ts).
- [Tiptap pinned extension manager](https://github.com/ueberdosis/tiptap/blob/v3.31.3/packages/core/src/ExtensionManager.ts).
