# ADR-0082: Native Office saved-version browser printing

Date: 2026-09-21
Status: accepted design; development validation pending
Scope: Roadmap 258 / PLANS 119, extending ADR-0079

## Context

Native documents support authoring and review but need a practical paper/PDF output workflow. The browser already
provides a user-controlled print dialog. Reusing it avoids adding a conversion engine, stored derivative or runtime
dependency before those separately governed capabilities are admitted.

## Decision

Print a selected immutable saved version through a dedicated preview and an explicit browser print/PDF action.
Use the existing exact-version content read both when opening the preview and immediately before calling the browser.
The server rechecks current tenant/module/read-feature and authoritative parent ACLs and verifies exact source bytes.
Use the version's title, including for historical versions; a newer current head cannot silently replace the selection.
Readers may print; write permission is not required. New or dirty drafts and unresolved save states cannot be printed
through this workflow. Drafts remain memory-only and are never implicitly saved or discarded.

Build only allowlisted native document elements and attributes, with literal text nodes. Never interpret source text
as HTML or load remote assets. Offer A4/Letter and portrait/landscape as session-only output choices. The continuous
preview shows typography and width; final pagination and destination selection belong to the browser dialog.
Separate print media from the application shell, editor, context, discussion and suggestion panels. Only content
prepared by the explicit freshly authorized action is printable; other browser-print entry points show neutral guidance.
Close, context changes, access denial, afterprint and failure cleanup invalidate or remove prepared content.
During the browser call, the preview temporarily becomes nonmodal so its sibling print content remains available to
native PDF accessibility export. Restore modal state only while the original print session is still valid. Browser
regressions inspect actual heading/list/table structure dictionaries, not merely the requested tagged-output flag.

The normal metadata-only content-read audit remains the evidence of authorization. Calling the print dialog is not
evidence that the user printed or saved a PDF. No completion receipt, export audit, download guarantee, stable page
count or cross-browser fidelity claim is introduced. The user's browser controls its final settings and local files.

## Boundaries and validation

No new API, schema, durable record, object-storage derivative, dependency or engine admission. DOCX interchange,
server-side PDF conversion, production export policy and archival/signing remain separate work. Normal Office tenant
and pilot gates remain closed. Retain Roadmap 257 recovery evidence without claiming a new recovery execution.

Remote browser checks must cover exact historical content, read-only output, literal hostile text, all supported native
structures, settings, output isolation, fresh access revocation, transient failures, late responses and responsive
layout. A real browser-generated PDF supplements the controlled print-dialog test; full Python quality and existing
browser/model regressions remain required before dev001 API-only rollout.
