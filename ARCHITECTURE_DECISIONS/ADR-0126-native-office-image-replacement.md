# ADR-0126: Replace native Office image pixels in place

Status: Accepted
Date: 2026-10-05

## Context

Authors can insert, edit and duplicate a native image, but replacing an outdated source file requires removing the
image and reconstructing its placement and accessibility metadata. Reusing or mutating the old asset/version would
also make immutable historical document versions render different pixels.

## Decision

The edit dialog exposes **Neue Bilddatei** for a selected image, including a member selected inside an image group.
It reuses the existing tenant- and write-authorized PNG/JPEG upload endpoint, isolated decoder, normalized rendition,
size limits and document-owned asset contract. Upload creates a fresh immutable asset/version but does not change the
draft. **In Entwurf übernehmen** replaces the selected node in one undo transaction after resolving the selection
again; cancel, upload failure and stale context leave the draft unchanged.

Alignment, alternative text, caption, decorative state, aspect-ratio choice, wrapping or free position, quarter-turn
transformation and stable figure identity remain unchanged. With aspect-ratio locking, display height follows the new
normalized pixel ratio and both dimensions remain inside the existing 1–1600 bounds; unlocked frames keep their exact
width and height. A crop is omitted because source-pixel coordinates cannot safely transfer to different pixels.

Confirmed compare-and-swap save remains the only durable document mutation. Earlier document versions retain their
old exact image binding. The new asset follows the existing ACL, classification, retention, legal-hold, receipt,
backup and recovery contracts. No external URL, provider call, raw image logging, asset deletion or schema migration
is added.

## Consequences

Authors can refresh image content without reconstructing captions, accessibility text, numbering, transforms,
group placement or anchored layout. Interrupted uploads can leave an unreferenced retained asset, so the existing
200-asset bound remains in force until a separately confirmed retention-aware cleanup workflow exists. Automatic crop
translation, content-aware focal points, remote images, arbitrary formats and DOCX DrawingML interchange remain
separate decisions.
