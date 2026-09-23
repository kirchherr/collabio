# ADR-0082: Native Office saved-version browser printing

Date: 2026-09-21
Status: accepted; development validation complete, rollout evidence tracked separately
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

Remote browser checks cover exact historical content, read-only output, literal hostile text, supported native
structures, settings, output isolation, fresh access revocation, transient failures, late responses and responsive
layout. Real browser-generated PDFs supplement the controlled print-dialog test.

## Development acceptance

On `cf2244c`, the complete matrix passed 170/170 checks in 562.233916 seconds: 135 browser cases and 35 model cases,
zero skipped, unexpected or flaky. Full Python quality passed Ruff/format across 689 files, Mypy across 541 sources
and full Pytest, with only the known Starlette/AnyIO deprecation warning. All previous 162 checks remain included.
Final desktop/tablet/mobile screenshots and PDF pages passed independent visual review.

Same-page Chromium output and independent Poppler/QPDF inspection verified nine rich Letter-landscape pages, one
historical A4-portrait page and one unprepared-print guidance page. All 80 rich text paragraphs, the final sentinel,
literal markup, whitespace and table content are present; no application shell or protected panel content is printed.
Both prepared PDFs carry actual heading/paragraph structure tags; the rich document additionally carries two lists,
two list items, one table, 20 header cells and 40 data cells. No PDF/UA or cross-browser equivalence is claimed.

Browser report: `sha256:8198c66138af5af63d6d767ab9e8c4c06acaf18e60013809ed31879f39faa86f`.
PDF QA report: `sha256:598c1e210e3cb3f4920d78120b479d36f42bb8f8d8bfb6cf3677b61a3bedb63b`.
Full artifact hashes and exact scope are in `docs/modules/OFFICE_NATIVE_DOCUMENTS.md`; ignored artifacts live under
`e2e/work/artifacts/roadmap-258/`. The later test-cleanup-only change `d8300aa` is distinct from the full matrix source.
Its affected-case recheck passed in 9.001 seconds. Dev001 API-only rollout, live verification and cleanup passed;
final health was ok at 2026-09-21 11:32:51 UTC. Exact operating evidence is recorded separately in the operations log
and current handoff. Retained item 257 recovery was not rerun for this UI slice.
