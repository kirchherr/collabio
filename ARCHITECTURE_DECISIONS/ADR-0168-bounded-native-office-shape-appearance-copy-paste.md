# ADR-0168: Bounded native Office shape appearance copy and paste

Date: 2026-10-09

Status: Accepted

## Context

Native Office can apply seven established appearance values to a bounded multi-selection. Authors also need to reuse
an already designed shape appearance without reopening the seven-field inspector or moving untrusted shape data
through a system clipboard, browser store or cross-document channel.

## Decision

One selected root standalone shape or one complete root shape group may become an appearance source. A group is
eligible only when every member has the same normalized appearance. The remembered sample contains exactly fill,
stroke, stroke width, font size, text color, text style and text alignment. Established defaults normalize to font
size 16, automatic text color and normal text style; canonical omission is restored when the sample is applied.
Mixed groups, partial or nested groups, unknown keys, null values, arbitrary colors, CSS, URLs, fonts, fractions,
numeric booleans and values outside the established bounds fail closed.

The sample exists only in memory for the current authorized editor session and document. It is cleared on document
or session change and when write permission is lost. It never enters the operating-system clipboard, browser storage,
Office JSON, an API request, observability or another tenant. Paste is enabled only for two through twenty selected
standalone roots or complete groups in the same writable document.

Paste rebuilds and validates every affected standalone root and every member of a complete group before replacing
the document in one transaction and undo unit. IDs, group identity and membership, order, connections, gaps, text,
anchors, layers, positions, dimensions and rotations remain intact. Repeated paste is allowed while the session and
authorization remain current. A target already carrying the sample creates no history.

The existing common-appearance preview also supports normal-flow groups. A group without a free position does not
receive position data or positioning CSS during preview; Cancel restores the complete source DOM without a
transaction. This prevents the preview from treating an intentional normal-flow group as a positioned group.

## Consequences

The responsive multi-selection tools expose accessible `Darstellung merken` and `Darstellung uebertragen` actions
plus an explicit memory status. Model and desktop/mobile workflows cover normalized sources, uniform/mixed group
eligibility, bounded paste, flow-group preview, one-step undo/redo, save, immutable predecessor history, print,
reload clearing and independent reuse. The complete native-shape matrix passes 37/37.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store, system
clipboard access, browser persistence, cross-document or cross-tenant transfer, arbitrary appearance value, physical
page anchor, nested group or DOCX DrawingML admission. The isolated review API exposes the feature without changing
ordinary tenant or production admission.
