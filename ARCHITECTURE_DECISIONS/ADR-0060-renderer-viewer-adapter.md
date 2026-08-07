# ADR-0060: Renderer and Viewer Adapter Boundary

Status: accepted
Date: 2026-08-07

## Context

The suite already has tenant-scoped SourceObject metadata, authoritative ACL checks, parser and sanitizer boundaries,
metadata-only renderer evidence, recovery drills, and a fresh release gate. It did not yet have a concrete renderer or
viewer adapter port. Connecting an office engine directly to SourceObject storage would give a large native parser access
to tenant content and would couple preview, editing, storage, and browser delivery into one security boundary.

Office preview and collaborative office editing are different workloads:

- Preview needs deterministic, read-only visual fidelity and can use a canonical immutable output.
- Collaborative editing needs sessions, locks, callbacks, short-lived access tokens, and controlled writes.
- Browser viewing needs a separate origin, a strict content security policy, and authorized byte-range delivery.

Treating one vendor product as all three layers would make tenant isolation, audit, retention, incident response, and
provider replacement harder.

## Options Reviewed

| Option | Strength | Limitation | Decision |
| --- | --- | --- | --- |
| LibreOffice headless to canonical PDF plus PDF.js | Self-hosted, broad OOXML/ODF conversion, deterministic read-only artifact, independent browser viewer | Native parser attack surface, conversion fidelity must be tested, no collaboration | Selected for the first preview architecture |
| Collabora Online over WOPI | Self-hosted collaborative editing, LibreOffice-based format support, browser editor | Stateful service, WOPI host, locks, tokens, network and content flow required | Preferred candidate for a later editing adapter, not part of preview |
| ONLYOFFICE Docs over WOPI | Strong OOXML-oriented editor, co-authoring and conversion APIs | Separate service and content flow; Community Edition is AGPL-3.0 and product embedding needs legal review | Retained as an editing alternative |
| Direct DOCX/ODF rendering in application JavaScript | Small initial deployment | Incomplete fidelity, fragmented format support, parser code in the trusted application/browser origin | Rejected as the canonical path |
| Microsoft 365 for the web over WOPI | High Office fidelity | External cloud content processing, partner-program and tenant-policy requirements | Optional future provider only, never the default |

## Decision

Use two independent provider-neutral ports.

The first **preview port** uses the architecture ID `canonical-pdf-libreoffice-pdfjs.v1`:

1. A future isolated worker receives one ACL- and version-bound SourceObject through a narrow broker.
2. LibreOffice headless converts allowlisted non-macro OOXML, ODF, RTF, or text inputs to canonical PDF.
3. Existing PDFs skip conversion but still pass validation and policy checks.
4. The PDF output is reparsed, policy-checked, hash-bound to the source version, and stored as a derived SourceObject.
5. A customized PDF.js viewer runs on a separate origin and receives only short-lived authorized range access.

The later **editing port** uses WOPI and is not reachable through the preview adapter. Collabora Online and ONLYOFFICE
remain replaceable candidates. WOPI proof validation, token lifetime, permission projection, lock semantics, callbacks,
save-as behavior, and write receipts require a separate ADR and release gate.

The implementation in this change is intentionally a metadata-only dry-run:

- The adapter input model has no content or byte field.
- The adapter module imports no object-content store, HTTP client, process runner, or renderer SDK.
- The source metadata is resolved only after authoritative tenant and object ACL checks.
- A hash-valid and current tenant renderer release gate is required before adapter selection.
- The configured adapter must be present in the static registry; unknown configuration fails application startup.
- The response and audit event prove the selected route and required controls while recording that no renderer, viewer,
  WOPI session, content read, output generation, persistence, or network access occurred.

## Required Production Controls

Real engine execution remains blocked until a later gate proves all of the following:

- Digest-pinned and attested renderer and viewer artifacts.
- A per-job gVisor sandbox or microVM, not only a default container boundary.
- No network egress, read-only root filesystem, non-root UID, dropped capabilities, and ephemeral job workspace.
- CPU, memory, wall-clock, source-size, archive-expansion, page-count, and output-size limits.
- Magic-byte/container validation, malware scan, and applicable content disarm and reconstruction before conversion.
- Macro and active-content execution disabled; external links, fonts, images, and templates are never fetched.
- A fresh LibreOffice user profile and controlled, versioned font package per job.
- PDF output revalidation, source/version/content-hash binding, and derived-object retention and Legal Hold policy.
- Separate viewer origin with strict CSP, no direct object-store URL, fresh ACL validation, and short-lived range access.
- Restore evidence for derived previews and explicit deletion propagation when the source becomes inaccessible.

## Self-Review

The selected path is not universally best. Conversion to PDF can lose advanced spreadsheet behavior, animations,
embedded objects, comments, and exact pagination when fonts differ. That is acceptable for read-only preview but not for
authoritative editing. The adapter therefore declares its route and target media type and does not claim edit fidelity.

A plain container with seccomp is insufficient for hostile office files because the converter is a large native parser.
The contract requires a stronger sandbox for production. PDF.js also parses untrusted content, so canonical conversion
does not remove the need for output validation and browser isolation.

WOPI is deliberately deferred rather than hidden inside the preview adapter. It introduces content transfer and write
capabilities that require different authorization, auditing, data residency, and failure semantics. This costs an extra
integration boundary but prevents a preview feature from silently becoming an editing or external-data channel.

## Consequences

Easier:

- Preview, viewing, and collaborative editing can evolve or change providers independently.
- The API can prove adapter eligibility without exposing content.
- The future worker has an explicit security and supply-chain contract.
- Source-version and ACL binding remain authoritative across every provider.

Harder:

- Preview artifacts add lifecycle, storage, and restore obligations.
- Format fidelity requires a maintained golden corpus and font baseline.
- A real worker needs stronger isolation than ordinary application containers.
- Collaborative editing still requires a dedicated WOPI design and implementation.

## Verification

- Unit tests validate descriptor invariants, MIME routing, macro/mail rejection, and the absence of content fields.
- API tests prove authoritative ACL lookup, fresh release-gate binding, metadata-only output, and hash-only audit logging.
- Architecture tests reject content-store, network-client, and process-execution imports in the adapter module.
- Docker Compose quality gates must pass before merge.

## References

- LibreOffice command-line and headless parameters: https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html
- LibreOffice PDF export parameters: https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html
- PDF.js architecture and viewer: https://mozilla.github.io/pdf.js/getting_started/
- Collabora Online SDK: https://sdk.collaboraonline.com/CO-SDK-manual.pdf
- ONLYOFFICE WOPI overview: https://api.onlyoffice.com/docs/docs-api/using-wopi/overview/
- Microsoft WOPI security and privacy: https://learn.microsoft.com/en-us/microsoft-365/cloud-storage-partner-program/online/security
- OWASP File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- gVisor security architecture: https://gvisor.dev/docs/architecture_guide/intro/
- Content Security Policy Level 3: https://www.w3.org/TR/CSP/
