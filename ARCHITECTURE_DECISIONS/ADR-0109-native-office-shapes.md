# ADR-0109: Bounded native Office shapes

Status: Accepted
Date: 2026-10-02

## Context

Native Office supports rich text, tables and document-owned images, but authors also need simple visual callouts and
diagram elements. Persisting arbitrary SVG, HTML, CSS, paths, macros, OLE objects or remote resources would create an
active-content surface and make responsive layout, comparison, printing and recovery difficult to validate.

## Decision

A document may contain at most 100 top-level native `shape` blocks. Each shape has a unique opaque `shape-` identifier
and exactly one type: rectangle, rounded rectangle or ellipse. Width is an integer from 80 through 1,200 pixels,
height from 40 through 800 pixels and stroke width from 0 through 8 pixels. Fill and stroke use a fixed color-token
allowlist. Text is literal, limited to 1,000 characters and aligned left, center or right. Unknown keys, nested shapes,
duplicate identifiers, controls, surrogate code points and active/freeform values fail before persistence.

The editor provides one responsive insert/edit dialog with a live inert preview. Selection or double-click opens the
same editor. Insert, edit and remove are separate undo transactions and remain draft-only until the existing explicit
confirmed CAS save. Shapes scale down to the available page width without horizontal overflow. Comparison, immutable
history, independent document copies and print retain the exact canonical attributes and literal text.

## Consequences

Authors can create accessible bounded callouts and simple diagram elements without introducing executable document
content. Freehand paths, arbitrary polygons, connectors, rotation, grouping, overlap layers, text flow around shapes,
OLE, SVG import and DOCX DrawingML interchange remain separate work requiring their own bounded models and fidelity
evidence.
