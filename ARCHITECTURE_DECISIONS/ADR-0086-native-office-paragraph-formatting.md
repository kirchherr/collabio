# ADR-0086: Native Office paragraph formatting

Status: accepted; development validation and controlled dev001 rollout complete
Date: 2026-09-21
Roadmap: 262 / PLANS 123

## Decision

Native paragraphs and headings may carry four optional, strictly validated attributes:

| Attribute | Values | Meaning |
| --- | --- | --- |
| `textAlign` | `left`, `center`, `right`, `justify` | Paragraph alignment |
| `lineSpacing` | strings `1`, `1.15`, `1.5`, `2` | Unitless line-height multiplier |
| `spacingBefore` | integers `0`, `6`, `12`, `18`, `24` | Space before in points |
| `spacingAfter` | integers `0`, `6`, `12`, `18`, `24` | Space after in points |

Absence preserves the existing type- and context-specific presentation. Explicit allowed values are retained, including
zero and left alignment. The server validates without mutating or normalizing input. Existing canonical JSON bytes,
hashes, receipts and versions remain unchanged. Browser-only ProseMirror null defaults are omitted during serialization.
The native MIME type and `collabio_document.v1` identifier stay unchanged; no SQL migration or dependency is introduced.
Old editor builds do not understand the added attributes; a rollback must retain a compatible reader/validator before
allowing edits of formatted content. Historical unformatted content remains readable with its original bytes.

A compact paragraph dialog operates on selected paragraphs/headings, including list, quote and selected table-cell
content. Mixed properties stay unchanged unless deliberately selected; Standard removes the corresponding attribute.
One Apply is one validated undo step; a no-op creates neither a dirty draft nor an undo step. Code blocks are excluded.
The dialog is bound to the current document, revision and selection. Existing write, historical, pending-save, uncertain
retry and conflict boundaries remain authoritative. Applying local formatting does not save a version automatically.

Editor and print surfaces use fixed data attributes and a CSS allowlist. No document-supplied styles, HTML or URLs enter
the DOM. Comparison describes format-only changes at their exact paragraph/heading position, including nested content.
Save, reuse, takeover, find/replace, suggestions and browser print preserve the stored attributes through their existing
version, source-object, ACL, CAS and explicit confirmation boundaries.

## Continuity and verification

The existing PostgreSQL metadata/receipt and exact-version S3 continuity domains cover these durable JSON attributes.
A fresh nonempty synthetic recovery must include an unchanged legacy version and historically different formatted
versions, compare their exact canonical hashes and receipts, and revalidate current parent ACLs. Inventory traversal
must cover every document and every history page under existing authorized principals; it must not invent grants or
turn the checker into an application superuser. Earlier recovery evidence remains retained.

Acceptance requires strict backend negative tests, real save/reopen and historical reads, mixed selection and undo,
table-cell boundaries, current write revocation, exact retry, comparison/takeover, actual browser PDF, responsive visual
review, full prior regression, full remote quality, nonempty recovery and live API verification on dev001. Ordinary
tenant admission, pilot runtime, indexing, cloud providers and DOCX/engine gates remain closed.

## Development evidence

Implementation `8b61d8d` passed all 294 focused Python checks in 18.05 seconds and all 46 focused browser/model checks
in 150.538659 seconds. Full quality passed Ruff, formatting across 712 files, Mypy across 557 sources and complete Pytest;
only the known Starlette/AnyIO warning remains. All 215 checks passed in 759.313613 seconds: 176 browser and 39 model
cases, zero skipped, unexpected or flaky. The previous 200 cases remain included. The added browser evidence also covers
heading shortcuts, Enter/input-rule/list conversion, replacement/reuse, canonical-byte rejection and print-media styles.
Focused report: `sha256:312bf9c8d93747ad8ce7e5cb8a99400ee075bc4998b141f1039e711fc61dbe7f`;
final report: `sha256:b9d422791168a5f1a8dc710eb1574a28fe373a928c44c11227bbd981380d71a6`;
quality log: `sha256:e60159bdafa33d3854347d8fdf6fc5f55bc4bb87c630f8e6ebdbefe6240d358c`.

The actual same-page PDF passed independent Poppler/QPDF verification: three A4 pages, 5,233 extracted characters,
all numbered paragraphs and final sentinel, H1/H2/P structure, no empty page and no shell/context leakage. Independent
visual review passed nine artifacts: three paragraph viewports, print preview, two Work viewports and three PDF pages.
PDF: `sha256:ab04640d1bb33ad12712de3303fa98037ebad2ae1ff7689baac1419de608222f`;
PDF-QA report: `sha256:b271848bc5b5c2e3f13f6a2c99621d64f69600cb203946d8ee5eb56ae17023b1`.

Fresh nonempty PostgreSQL/S3 recovery into `collabio_work_e2e_262_restore` verified 330 documents, 666 versions and
721 source objects. The designated three-version fixture proved one unchanged legacy source and two historical format
profiles through exact canonical hashes and receipts. Complete paginated inventories, current parent ACLs, read-only
capabilities, foreign denial and existing review/suggestion recovery passed. Ten review threads/18 events and eleven
suggestions/seven decisions remain covered. Embedded recovery `report_hash`:
`sha256:bfc720ee2ec275061c5f934369a5864259071d5409f7bd4f99368b431951c7f7`.
The older synthetic database/dump/evidence remains retained; this slice requires no main-database migration.

Roadmap 262 development validation, both release gates, controlled API rollout, live verification and exact cleanup
are complete; host and gate evidence is recorded in `docs/CURRENT_HANDOFF.md`. All generated evidence is ignored under
`e2e/work/artifacts/roadmap-262/`. No ordinary-tenant, production, indexing, cloud-provider or engine admission follows.
