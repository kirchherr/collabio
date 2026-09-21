# ADR-0086: Native Office paragraph formatting

Status: accepted for development; validation and rollout pending
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
