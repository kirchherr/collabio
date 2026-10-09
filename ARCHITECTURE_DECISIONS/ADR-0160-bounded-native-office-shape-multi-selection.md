# ADR-0160: Bounded native Office shape multi-selection

Date: 2026-10-09
Status: accepted; development validation and isolated review deployment complete; ordinary tenant and production admission remain closed

Native Office may hold a transient selection of at most 20 root-level standalone shapes and complete shape groups.
The selection is keyed by validated object IDs and resolved against the current document order after each editor
update. Clicking a member of a group selects the owning group. The selection, its anchor and the explicit selection
mode are never written to the document JSON, server, browser storage or audit metadata and are cleared when the
document session changes.

Desktop authors may toggle objects with Ctrl/Cmd-click and extend one ordered range with Shift-click. An explicit
selection mode provides the same toggle behavior for mouse and touch without requiring modifier keys. Every selected
root object receives a visible marker and the toolbar reports the exact count. Escape clears the transient selection.
The existing single-object dialog and node selection remain available when no multi-selection gesture is active.

Duplicate, remove and group operations require at least two selected objects and run as one validated ProseMirror
transaction bounded by one history unit. Duplication assigns fresh IDs to every copied shape and group member and
uses the existing bounded 25/24 offset for positioned roots. Preflight checks enforce the existing maximum of 100
shapes and 20 groups before dispatch. Removal affects only the selected roots and remains reversible until the
existing confirmed CAS save.

Grouping accepts two through eight adjacent standalone shapes in normal flow. Positioned or wrapped shapes,
existing groups, intervening document blocks and nested groups are rejected. The new group uses the existing
canonical row layout and bounded gap; later editing remains available through the established group dialog.

Only the resulting existing shape and shape-group nodes pass through confirmed save, immutable history, comparison,
reload, semantic print/PDF, independent reuse and recovery. Browser validation checks the complete candidate document
before dispatch and the server validates it again on save. Read-only, historical, saving, uncertain and stale
sessions cannot execute a bulk mutation.

This decision adds no relational migration, endpoint, dependency, external request, provider, worker, new recovery
store, persisted UI selection, nested group, arbitrary geometry or DOCX DrawingML admission. Multi-object alignment
and distribution remain a separate bounded authoring loop.

Acceptance requires pure ordered/range/groupability checks and responsive desktop/mobile workflows covering explicit
mode, Ctrl/Cmd and Shift selection, atomic duplication, grouping and removal, one-step undo/redo, confirmed save,
immutable predecessor history, semantic print, reload clearing and independent reuse.
