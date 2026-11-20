# ADR-0183: Bounded native Office macro policy

Date: 2026-10-10

Status: Accepted

## Context

ADR-0182 exposes an isolated parser-worker plan while keeping dispatch closed. Before any document can enter that
worker, active content must be identified without executing it. Filename extensions and caller-provided MIME alone
are insufficient: a nominal DOCX can contain VBA, ActiveX or OLE parts, ODF can contain Basic or event scripts, and
PDF can contain JavaScript or launch actions.

Silent sanitization is also unsafe. It can destroy signatures or evidence and make a modified derivative appear to
be the original. The product therefore needs separate block and visible-mark outcomes before a quarantine or import
workflow exists.

## Decision

Add a bounded byte-level active-content inspection to the existing no-network rich-document worker. Recognize the
macro-enabled DOCM MIME and inspect nominal DOCX ZIP inventories, content types and relationships for VBA projects,
ActiveX, OLE/packages and attached templates. Reject unsafe or ambiguous member names, encrypted entries and
unsupported compression before extraction.

Inspect ODF package names and bounded control XML for Basic/script parts, event listeners and script URIs. Inspect
PDF bytes for JavaScript, JS, Launch, OpenAction, additional actions and embedded files. Any such blocking indicator
returns `block`; the parser raises before text extraction. Execution is always false.

Treat digital-signature and external-link indicators as nonexecuting review markers. With no blocking indicator they
return `allow_marked`, allow text extraction and attach one generic warning. The warning, normal logs and audit must
not contain archive paths, relationship targets, source identifiers or content. No active content is automatically
removed.

Expose `office_macro_policy.v1` as a tenant-scoped, read-gated, metadata-only endpoint. It accepts no file or source
identifier and declares exact supported/blocked MIME behavior, block classes, mark classes and missing production
gates. Audit stores only schema, state, bounded counts and closed execution/dispatch flags.

## Consequences

The development parser now enforces a concrete pre-extraction barrier for the covered DOCX/DOCM, ODF and PDF
indicators, while the Office UI explains block versus mark behavior. A marked result remains a review candidate, not
an assurance that the entire format is safe.

A comprehensive OOXML/ODF/PDF malicious corpus, quarantine and accountable operator review, persisted and restored
policy receipts and production parser-image admission remain required. This ADR opens no upload, dispatch,
sanitization, macro execution or production path.
