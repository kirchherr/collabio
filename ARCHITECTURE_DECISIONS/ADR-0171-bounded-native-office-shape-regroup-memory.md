# ADR-0171: Bounded native Office shape regroup memory

Date: 2026-10-10

Status: Accepted

## Context

Native Office can dissolve several complete normal-flow shape groups in one action. Undo can recover the immediate
predecessor, but authors also need an explicit regroup action after editing or saving the resulting standalone shapes.
Requiring users to reconstruct every wrapper, connection and layout option manually would lose established group
identity and make a common editing sequence unnecessarily fragile.

Persisting regroup data would introduce a new document schema, recovery and authorization surface for information
that is useful only during the current editing session. Positioned groups remain unsuitable because one group-level
anchor and layer cannot be mapped losslessly to standalone members during ungrouping.

## Decision

After a successful collective ungroup, the editor keeps the exact original group wrappers in memory for the current
authorized document session. Two through twenty remembered normal-flow groups may be restored, with two through eight
members in each group. The memory includes only canonical group attributes and stable member IDs and is never written
to Office JSON, browser storage, the system clipboard, an API request, another document or another tenant.

Before every regroup, the editor revalidates the current document. Every remembered member must exist exactly once as
a standalone normal-flow root shape; members must retain their original order and form one contiguous range per
group; group and member limits, connections and IDs must remain valid; group ranges must not overlap; and restored
group IDs must not collide with current roots. Stale, partial, moved, positioned, nested, duplicated, unknown or
otherwise invalid state fails closed.

Regroup restores the original group ID, layout, gap, alignment, distribution and connection metadata while consuming
the current member nodes. Thus permitted text, appearance, geometry and rotation edits made after ungroup remain
intact. Unrelated document nodes retain their order and content. Every remembered range is replaced from the document
end toward the beginning in one validated ProseMirror transaction and one undo unit.

The responsive **Gruppen wiederherstellen** action is visible only while matching session memory exists and is enabled
only while the current document still satisfies the complete plan. It requires no renewed object selection. Memory
survives transient save-disabled states and a confirmed save in the same editor session, allowing an ungrouped version
and a later regrouped version to remain distinct immutable predecessors. A document/session change, historical mode or
loss of write permission clears memory. Keeping memory after regroup lets undo and redo dynamically re-enable or
disable the action from actual document state.

## Consequences

The pure model and desktop/mobile workflows cover canonical wrapper restoration, current-member preservation,
connection, order and collision validation, one-step undo/redo, confirmed ungroup and regroup saves, immutable version
lineage, semantic print, reload/session clearing and independent reuse. The corrected focused workflow passes 4/4 in
46.2 seconds and the complete native-shape matrix passes 40/40 in 4.8 minutes. The initial three failed cases exposed
one canonical-attribute expectation and premature memory clearing during save; both corrections remain documented.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
browser/clipboard persistence, cross-document or cross-tenant transfer, positioned or nested group support, inferred
anchor mapping, arbitrary connector or DOCX DrawingML admission. It does not activate an ordinary tenant, pilot,
indexing path or document engine.
