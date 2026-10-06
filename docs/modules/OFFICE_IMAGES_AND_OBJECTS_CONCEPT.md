# Native Office images and objects: product design

Updated: 2026-10-01
Status: native PNG/JPEG implementation follows ADR-0091; acceptance is recorded in CURRENT_HANDOFF.md.
Roadmap 269 implements non-destructive crop under ADR-0092; its acceptance is recorded in CURRENT_HANDOFF.md.
Roadmap 270 implements bounded text wrapping under ADR-0093; acceptance is tracked in CURRENT_HANDOFF.md.
Roadmap 289 implements bounded anchored foreground/background placement under ADR-0106.
Roadmap 290 implements bounded quarter-turn rotation and mirroring under ADR-0107.
Roadmap 291 implements bounded native image groups under ADR-0108.
Roadmap 309 implements in-place file replacement with fresh immutable pixels under ADR-0126.
Roadmap 314–316 implement inert exact-version Office document objects under ADR-0129.
Other object types remain proposals. This document does not activate ordinary tenants.

## Existing foundation and gap

OFFICE_MAIL_CORE.md and SOURCE_OBJECT_MODEL.md supply versioned source storage, tenant authorization, classification,
retention, Legal Hold, content hashes, audit and recovery. ADR-0060/0061 separate preview from editing and isolate
format engines. Roadmap 268 adds document-owned native images under ADR-0091 to the original ADR-0079 schema.
External resources and active objects remain rejected. ADR-0071 rejects OLE and embedded packages in
the constrained DOCX preflight. Embedded-object semantics require a separate decision and fidelity corpus.

## First product slice: images

Provide Insert image and explicit file selection, then preview before applying it to the draft. Begin with PNG/JPEG;
validate signature/MIME, byte and decoded-pixel limits in a no-egress isolated decoder and produce an inert normalized
rendition. Strip unnecessary metadata from that rendition; retain any required original only under its own policy.
SVG, remote image URLs, animated formats and arbitrary HTML are outside the first allowlist.

The native node references an exact tenant-owned asset/version/hash, never a public URL or inline base64 body. It
contains bounded display dimensions, aspect-ratio lock, inline/block alignment, literal alternative text and an
optional caption. Start with in-flow layout; wrapping and floating anchors can follow with explicit print
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

## Non-destructive crop and subsequent layout

ADR-0092 keeps the normalized source immutable and stores a bounded integer source-pixel rectangle in each document
version. Pointer selection, keyboard movement, numeric controls, local preview/reset and isolated undo share that
geometry. Reset omits the optional property. History, comparison, independent copy and print preserve the exact
rectangle. The complete source remains readable to authorized readers; this feature is not a redaction mechanism.

ADR-0093 defines the ordered image node as a stable anchor for following top-level paragraphs. Left/right wrapping
has an integer 0-48px gap, a 45% column-width limit and a 480px displayed-image-height limit. Narrow columns and nested
images use block fallback without rewriting stored metadata. Structural blocks clear prior floats. Image/caption
request page-break avoidance in actual PDF; over-page content remains browser-fragmented. Editor, history and owned
reuse retain the exact layout choice and crop. Arbitrary page-positioned objects and DOCX anchors remain separate.

## Anchored foreground and background placement

ADR-0106 adds a mutually exclusive free-placement mode to the ordered image node. The image remains anchored at its
document position while a normalized horizontal coordinate from 0 through 1000 and a vertical offset from -1200
through 1200 CSS pixels move its presentation. The layer is exactly `front` or `behind`; arbitrary CSS, z-index,
transforms, URLs and page coordinates are never stored. The horizontal coordinate keeps the complete image inside the
current text column across paper settings and narrow views. A draggable, keyboard-operable anchor remains above the
editor surface even when the image is behind text, so the object never becomes unreachable.

The dialog places layer and coordinates directly below size and alignment. Dragging the anchor or pressing arrow keys
changes one bounded draft transaction; Shift increases the keyboard step. Numeric fields provide an exact alternative.
Text wrap is disabled while free placement is active. Resetting to **Im Textfluss** omits `position`, preserving legacy
canonical bytes. Cancel and invalid bounds are no-ops; undo, comparison, immutable history, independently owned copies,
print and recovery retain the exact geometry. Print uses the same anchored layer without adding a remote resource or
executable object. This is not an absolute DOCX page anchor and does not claim continuous editor pagination.

## Bounded rotation and mirroring

ADR-0107 adds an optional inert `transform` with exactly one quarter-turn value and two mirror booleans. The dialog
offers 90-degree right/left and 180-degree rotation plus independent horizontal and vertical mirroring. Arbitrary
angles, CSS transforms and matrices are rejected. The identity is omitted, preserving legacy canonical bytes.

The normalized rendition and crop rectangle remain unchanged. A responsive frame exchanges reserved width and height
for sideways orientations and scales the visual inside those bounds, keeping flow, narrow layouts and print aligned.
Captions and alternative text are not transformed. Preview, undo/redo, comparison, immutable history, independently
owned copies and printing use the same validated values. Fresh recovery proves consecutive rotate/mirror/reset versions
on one unchanged owned rendition. Arbitrary-angle transforms, wrap contours and physical-page anchors remain separate.

## Bounded native image groups

ADR-0108 adds an inert block containing two through eight exact native image nodes. A document contains at most 20
groups. Each group stores only a unique opaque identifier, ordered members, `row` or `stack` and an integer 0–48 pixel
gap. Nested groups, active attributes and grouped members with wrapping or free positioning are rejected.

Users can group with an adjacent image, extend a group, change layout/gap, move it as one block, remove members and
dissolve it. Compact row groups collapse vertically without rewriting stored metadata. Undo/redo, comparison,
immutable history, independently owned copies, printing and recovery retain exact order and image identities. Fresh
recovery proves row/gap-12, stack/gap-24 and dissolved versions of the same three images. Freeform canvases, shapes,
connectors, nested groups, wrap contours and physical-page anchors remain separate.

## In-place image-file replacement

ADR-0126 reuses the same authorized upload and isolated normalization path when a selected image receives a new PNG
or JPEG file. Upload alone creates no draft mutation. Explicit apply replaces exactly the selected image node in one
undo step while retaining alternative text, decorative state, caption, figure ID, alignment, wrapping or free
position, group membership and inert transform. Locked dimensions follow the new pixel ratio inside the established
bounds; unlocked frames remain exact. Source-pixel crop coordinates are omitted because they cannot be transferred
safely to unrelated pixels. Immutable earlier versions keep their old asset/version binding, while the replacement
uses a fresh document-owned asset/version and the existing receipt, ACL, retention and recovery controls.

## Accessible image-group member ordering

ADR-0127 exposes separate focusable controls for the selected member's reading order and the complete group's
top-level document order. A member action swaps exactly one adjacent image, stays disabled at the corresponding group
boundary and keeps selection on the moved image. Whole-group actions name **Bildgruppe** explicitly and use the
independent document boundaries. Each move is one isolated undo transaction.

The operation reuses the existing canonical ordered group representation. Group identity, layout and gap and all
member asset/version, crop, transform, accessibility, caption, figure and display attributes remain byte-for-byte
equivalent except for member sequence. Confirmed save, immutable history, reload, comparison and print consume that
same sequence. No drag-only control, nested group, arbitrary overlap layer or new schema is introduced.

## Implemented document-object slice and later object types

ADR-0129 implements the first object type as an inert Office-document card. It stores an exact target object/version
and either fixed snapshot or explicitly refreshable linked mode. The title is resolved only after a fresh target ACL
check and is never copied into the source. Refresh creates a visible draft change and historical renderings never move.
Move, duplicate, remove, open, undo, comparison, print and backlinks consume the same exact binding.

Files, native charts and later sheets/slides still require their own typed version-bound references and inert preview
contracts. Define rendition authorization, source-object retention and recovery before adding each type.

Executable OLE/ActiveX, macros, arbitrary iframes and live external content have no admission in this design. Any future
request for an active object needs a separate threat model, sandbox, compatibility tests and explicit release decision.
This distinction preserves normal image/chart/file usability without granting embedded executable code a runtime.

## Acceptance and sequencing

Roadmap 272 / ADR-0095 adds version-owned paper, orientation and four bounded margins.
It preserves ordered image anchors, crop and wrap, explicit breaks and tables. Saved settings
initialize printing and drive actual PDF geometry; the editor remains a continuous responsive
sheet. This does not introduce arbitrary page-positioned objects or section layouts.

Roadmap 271 / ADR-0094 adds an explicit top-level page boundary. Insertion after a
selected image preserves its asset, crop and wrap metadata. Printing contains the
preceding image and its float before the next page's content. An image immediately
following a boundary belongs to the following content flow. Markers inside image
captions, list items, quotes or table cells are not admitted. This does not introduce
absolute page coordinates, floating object anchors or section layouts.

Roadmap 268 follows named styles as an independent roadmap item. ADR-0091 defines native asset ownership,
schema/API/version manifest and orphan lifecycle for the complete upload-insert-save-reopen-print loop. Require
malformed/decompression/size tests, tenant/ACL and revoked-reference tests, immutable version/reuse/undo tests, literal
captions, keyboard/mobile review and nonempty PostgreSQL/S3 document-plus-asset restore. DOCX roundtrips additionally
need the existing engine admission and measured fidelity lane. This proposal does not open those gates.
