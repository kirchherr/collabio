# ADR-0157: Freely positioned native Office shape groups

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

A root-level native Office shape group may carry one optional bounded logical position. The position contains exactly
a `front` or `behind` text layer, an integer normalized X coordinate from 0 through 1000 and an integer Y offset from
-1200 through 1200 pixels. Omission remains the canonical normal-flow representation, preserving existing document
bytes. Group members continue to reject their own positions and wrapping, and groups cannot be nested.

The responsive group dialog exposes the layer and coordinates. A positioned group also exposes one focusable direct
anchor. Pointer or touch movement previews the complete group, arrow keys move one pixel, Shift plus an arrow moves ten
pixels and Home returns to the logical origin. A completed gesture commits one isolated undo transaction. Temporary
DOM attributes used for the live preview are editor-owned presentation state and are ignored by ProseMirror's content
mutation observer; saved state still changes only through the validated transaction.

The group derives its exact axis-aligned bounds from row or stack layout, the validated gap and each member's bounded
dimensions and arbitrary whole-degree rotation. Editor, comparison and semantic print/PDF consume the same trusted
numeric geometry. Static CSS maps only the validated layer and product-generated numeric custom properties; document
content cannot provide CSS, z-index expressions, URLs or transform matrices.

Duplication generates a fresh group ID and fresh IDs for every member, preserves validated presentation and offsets a
positioned copy by a bounded 25 normalized X units and 24 Y pixels, reversing near the maximum edges. A group must be
returned to normal flow before it can be dissolved. When one member is removed from a two-member positioned group,
the remaining member is atomically promoted to a standalone shape at the group's position so that it does not jump
back into normal flow.

Confirmed save, immutable history, comparison, undo/redo, reload, independent reuse, recovery and print preserve the
exact position in the existing native-document JSON. No SQL migration, endpoint, dependency, external request,
provider, worker, new recovery store, physical page anchor, arbitrary z-index, mixed member anchor, nested group or
DOCX DrawingML admission is introduced.

Acceptance requires independent browser/server rejection, exact rotated-member bound checks and responsive desktop
and mobile workflows covering dialog, keyboard, pointer, isolated history, offset duplication, save, print, safe
ungrouping and survivor promotion.
