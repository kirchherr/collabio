# ADR-0079: Native Office document workspace

Date: 2026-09-18
Status: accepted for the native document development slice; tenant activation remains separate

## Problem and decision

The existing Office engine adapters, DOCX validation and fidelity harness do not provide an everyday writing surface.
The user prioritized Office over further CRM expansion and requested substantial improvements in function and usability.
Build a complete native document loop now: create, format, navigate, save a version, reopen and inspect history.
Do not interpret this decision as DOCX fidelity approval, an engine admission or a claim of parity with mature Office suites.

Use the open-source Tiptap 3.31.3 editor over ProseMirror, bundled locally with esbuild 0.28.2. Direct ProseMirror offers
equivalent structural control but requires more custom editor commands and selection management. Tiptap provides those
primitives while retaining a bounded, inspectable JSON model. Lexical is another credible editor framework but would add
a different document model and integration path; the existing research baseline already evaluated ProseMirror/Tiptap.
A full external Office engine remains appropriate for future format fidelity, but its runtime and human review gates are
independent. No Tiptap Cloud, commercial extensions, telemetry service or external asset host is used.

Exact package versions and transitive integrity values are committed in `frontend/office/package-lock.json`. A digest-pinned
Compose tooling job creates the lock on dev001 and checks production dependencies for high-severity advisories. Docker
uses `npm ci --ignore-scripts`; the build emits a local bundle, dependency inventory and complete license notices. The final
Python image contains assets, not Node or browser processes. A strict same-origin CSP excludes remote scripts and inline
styles. Future dependency updates require rebuilding and rerunning the editor/browser and supply-chain checks.

## Document and security contract

The native format is `collabio_document.v1`, MIME `application/vnd.collabio.document+json`. It supports bounded text,
headings, lists, quotations, code, rules and rectangular tables with a small mark allowlist. Active content, HTML nodes,
links, images, external resources and arbitrary node attributes are rejected. Limits apply before request parsing and
again to characters, serialized bytes, nesting and node counts. DOCX import/export is a separate implementation step.

The `office_documents` module declares `office_documents.documents.read` and `.write`. Both default closed for tenants.
Creation requires an authorized editor role; existing documents require a current explicit write/admin ACL. Read grants
and client-supplied identifiers never create write authority. Every historical version uses the current document ACL.
Native documents use the shared DOCUMENT SourceObject metadata, content store, manifest and write-receipt contracts.
Migration 0083 adds PostgreSQL heads and append-only versions, forced tenant RLS, narrow grants and source/ACL triggers.

Saving is explicit, confirmed and bound to the expected current version. A tenant lock serializes writes before S3 PUT;
actor-bound mutation references permit exact retries after lost responses. PostgreSQL metadata, head, version, creator ACL
and receipt commit together. S3 is outside that transaction: a later database failure can leave orphan content, which the
existing recovery inventory detects. The runtime refuses ephemeral writes when configured with a demo source repository.

Draft content remains only in page memory. Context changes clear protected editor state and invalidate late responses.
The UI retains a failed draft, requires a decision before discarding changes and never silently resolves a conflict.
No background AI, microphone, collaboration channel, search indexing or RAG is enabled by this slice.

## Consequences and next steps

Roadmap 253 adds comparison and historical takeover as local UI operations over the existing authorized version reads.
A small bounded block comparison uses the native tree model directly; it adds no diff service, third-party executable,
document copy or dependency. Structural and formatting changes remain distinguishable from text equality. Taking over
an old version creates only an in-memory draft against a freshly authorized current head; the existing confirmed CAS
save appends a successor. It neither rewrites history nor bypasses the source/receipt/recovery contracts.

This creates a useful first document editor, not a full Word/Excel/PowerPoint replacement. Next steps are evaluated DOCX
interchange, comments/review, accessible shared editing, then spreadsheet and presentation workflows with their own
version and recovery contracts. Real Word/GenOffice fidelity evidence and existing engine release gates remain required.
No intervention on the original Windows workstation or implicit real-tenant activation is authorized by this ADR.

Primary references: [Tiptap installation](https://tiptap.dev/docs/editor/getting-started/install/vanilla-javascript),
[Tiptap overview](https://tiptap.dev/docs/editor/getting-started/overview),
[StarterKit](https://tiptap.dev/docs/editor/extensions/functionality/starterkit),
[ProseMirror guide](https://prosemirror.net/docs/guide/).
