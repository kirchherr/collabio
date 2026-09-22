# Native Office images and objects: proposed product design

Date: 2026-09-22
Status: proposal for a subsequent product slice; no image/object support or activation is implemented by this document

## Existing foundation and gap

OFFICE_MAIL_CORE.md and SOURCE_OBJECT_MODEL.md supply versioned source storage, tenant authorization, classification,
retention, Legal Hold, content hashes, audit and recovery. ADR-0060/0061 separate preview from editing and isolate
format engines. These are reusable boundaries, not a finished native image insertion workflow. ADR-0079 and the current
native schema reject image nodes, external resources and active objects. ADR-0071 rejects OLE and embedded packages in
the constrained DOCX preflight. Embedded-object semantics require a separate decision and fidelity corpus.

## First product slice: images

Provide Insert image and explicit file selection, then preview before applying it to the draft. Begin with PNG/JPEG;
validate signature/MIME, byte and decoded-pixel limits in a no-egress isolated decoder and produce an inert normalized
rendition. Strip unnecessary metadata from that rendition; retain any required original only under its own policy.
SVG, remote image URLs, animated formats and arbitrary HTML are outside the first allowlist.

The native node references an exact tenant-owned asset/version/hash, never a public URL or inline base64 body. It
contains bounded display dimensions, aspect-ratio lock, inline/block alignment, literal alternative text and an
optional caption. Start with in-flow layout; wrapping, cropping and floating anchors can follow with explicit print
and interchange behavior. Keyboard selection, resize fields, move, remove, undo and mobile reachability are required.
Alternative text describes the image; an explicit decorative choice can suppress redundant screen-reader output.

Server-authorized reads resolve document access and current asset access together. Upload, attachment and reference
validation must not become an ACL bypass. Define document-owned assets and reuse rules explicitly; deny foreign or
unreadable references without exposing names/thumbnails. Do not add a raw unauthenticated image URL path. An authorized
same-origin fetch may deliver bytes for a short-lived browser object URL, revoked on close/context change. No provider
fetch or cloud AI is needed. Normal observability records only IDs and bounded metadata/hashes.

Saving binds the complete reference manifest atomically to the new document version. Old versions retain their exact
assets and renditions. Removing an image from a draft does not delete an asset referenced by history or Legal Hold.
Retention-aware orphan cleanup is a separate confirmed lifecycle action. A copied document must acquire its own
authorized asset ownership/reference contract instead of silently inheriting source sharing. Print/export uses the
same exact renditions, reauthorizes them and fails visibly on missing/denied assets rather than fetching fallbacks.

## Next slice: inert linked or embedded objects

Represent files, native tables, charts and later sheets/slides through a typed, version-bound object reference and an
inert preview. Show object type, title, source version and whether it is a fixed snapshot or an explicitly refreshable
link. Opening or refreshing rechecks both document and target ACLs. Updating a linked object creates a visible draft
change; it must never silently alter historical document renderings. Define how preview renditions, source objects and
cross-document references are restored and retained before adding each type.

Executable OLE/ActiveX, macros, arbitrary iframes and live external content have no admission in this design. Any future
request for an active object needs a separate threat model, sandbox, compatibility tests and explicit release decision.
This distinction preserves normal image/chart/file usability without granting embedded executable code a runtime.

## Acceptance and sequencing

Implement after the current named-style slice as an independent roadmap item. First decide native asset ownership,
schema/API/version manifest and orphan lifecycle, then ship the complete upload-insert-save-reopen-print loop. Require
malformed/decompression/size tests, tenant/ACL and revoked-reference tests, immutable version/reuse/undo tests, literal
captions, keyboard/mobile review and nonempty PostgreSQL/S3 document-plus-asset restore. DOCX roundtrips additionally
need the existing engine admission and measured fidelity lane. This proposal does not open those gates.
