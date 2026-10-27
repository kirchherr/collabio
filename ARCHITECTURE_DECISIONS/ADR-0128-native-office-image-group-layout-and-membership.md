# ADR-0128: Native Office image-group layout and membership editing

Status: Accepted
Date: 2026-10-06

## Context

Native image groups supported one horizontal row or one vertical stack. Authors could reorder members, duplicate or
remove the complete group and dissolve it, but they could not build a responsive multi-column composition, copy one
member independently inside the group or extract one member at a deliberate document position. Nested images also
needed a deterministic keyboard-accessible way to open their existing edit dialog.

## Decision

The bounded image-group layout vocabulary adds `grid-2`, `grid-3` and `grid-4`. A shared canonical layout model maps
each value to its German label and exact column count for editor, comparison and print rendering. Desktop uses the
selected column count. Narrow viewports retain two columns for three- and four-column groups so that images and
captions remain readable without horizontal overflow. The existing zero-to-48-pixel group gap remains authoritative.

Every image object exposes a focusable **Bild bearbeiten** button. It selects that exact image node and opens the
existing dialog, including for nested group members. **Bild duplizieren** may then copy the selected member through
the existing tenant- and write-authorized duplication endpoint. The response must contain fresh asset and version
identities with the same normalized pixel hash and source dimensions. Only after validation is the copy inserted
immediately after the source as one undo transaction. Existing 40-image, 200-retained-asset and eight-member group
limits remain closed before mutation.

**Bild vor Gruppe lösen** and **Bild nach Gruppe lösen** remove the selected member from its group and insert it at
the chosen adjacent top-level position in one undo transaction. A group with more than two members is rebuilt with
its exact ID, layout, gap and remaining member attributes. Extracting from a two-member group dissolves the group and
places both existing images in reading order. No asset is created or deleted by extraction.

Confirmed compare-and-swap save remains the only durable mutation. The new layouts are bounded values inside the
existing immutable Office version JSON and require no relational schema migration. Independent asset duplication is
the already recovery-proven transaction from ADR-0125; extraction only changes document structure. Exact saved
content, reload, immutable predecessor, readable copied bytes and print rendering are therefore the acceptance and
recovery boundary for this combined authoring loop.

## Consequences

Authors can create responsive two-, three- and four-column image compositions and edit individual members without
dissolving the group. Copying and extraction remain predictable for keyboard users and produce one undo step each.
Arbitrary masonry, overlapping group members, nested or mixed groups, free-positioned group members, drag ordering,
automatic crop translation and DOCX DrawingML interchange remain separate decisions.
