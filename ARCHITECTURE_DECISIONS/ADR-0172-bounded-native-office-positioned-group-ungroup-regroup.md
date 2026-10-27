# ADR-0172: Bounded native Office positioned-group ungroup and regroup

Date: 2026-10-10

Status: Accepted

## Context

Native Office can dissolve and restore several complete normal-flow shape groups. Freely positioned groups previously
remained excluded because one group-level anchor and layer cannot be copied directly to several standalone members.
Authors nevertheless need to dissolve positioned diagrams without losing the visible arrangement, canonical member
geometry or the ability to reconstruct the exact group wrappers during the current editing session.

Responsive group layout may shrink members while standalone shapes retain their canonical dimensions. Rotated member
bounding boxes also differ from their logical boxes. Therefore a valid design needs an explicit, bounded mapping from
the currently rendered member centers to the existing standalone position model and must reject unrepresentable state.

## Decision

Two through twenty selected complete groups may be ungrouped together when they all use the same anchor kind. Flow
groups retain the established direct wrapper removal. For positioned groups, every member must itself be an ordinary
unpositioned, unwrapped shape and every group must share one valid layer. Mixed flow/position selections, partial or
nested groups and invalid members fail closed.

Immediately before the transaction, the control reads each rendered member's visible center and the editor root
geometry. It derives the member's existing standalone position while preserving canonical width, height, rotation,
text and appearance. X uses the established integer 0-through-1000 scale, Y uses -1200 through 1200 pixels and every
member inherits the group layer. The calculation accounts for responsive member shrink, selection expansion and the
one-pixel contribution of each newly inserted root. Non-finite values or mappings outside the model are rejected.

When responsive shrink makes an exact edge center impossible at canonical standalone size, the mapping clamps to the
nearest legal X/Y anchor only if the resulting visible center remains within four CSS pixels of the source. This is a
rendering tolerance, not a new durable unit or a physical page coordinate. Larger drift rejects the entire operation.
All selected wrappers are replaced from document end to beginning in one validated ProseMirror transaction and undo
unit. Only established standalone shapes and positions enter Office JSON.

The current-session regroup record stores the original canonical wrappers plus the exact derived member positions.
Regroup revalidates stable IDs, standalone roots, exact order and contiguous ranges, exact positions and common layer,
group/member limits, connections and collisions. It removes the derived position from each member and restores the
original group ID, positioned anchor and layer, layout, gap, alignment, distribution and connection metadata while
retaining other permitted member edits. Moved, missing, duplicated or stale members fail closed.

Memory remains bound to the current authorized document session and is never written to browser storage, clipboard,
an API request, another document or another tenant. Document/session changes, historical mode and lost write access
clear it. Confirmed saves in the same session may preserve an ungrouped version and a later regrouped version as
distinct immutable predecessors.

## Consequences

The pure model and desktop/mobile workflows cover same-anchor eligibility, exact derived-position snapshots, edge
clamping, moved-member rejection, one-step undo/redo, confirmed ungroup and regroup saves, immutable predecessors,
semantic print, reload and independent reuse. The final focused run passes 3/3 in 33.7 seconds and the complete
native-shape matrix passes 40/40 in 4.9 minutes. Earlier geometry failures and the live-review narrow-viewport edge
case remain in the operations record as diagnostic evidence.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
browser/clipboard persistence, cross-document or cross-tenant transfer, nested group support, arbitrary physical page
anchor, arbitrary CSS geometry or DOCX DrawingML admission. It does not activate an ordinary tenant, pilot, indexing
path or document engine.
