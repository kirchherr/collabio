# ADR-0174: Bounded native Office object selection navigator

Date: 2026-10-10

Status: Accepted

## Context

Native Office already supports bounded multi-selection and a broad set of atomic shape and group actions. Direct page
selection is insufficient for objects behind text, visually covered roots or documents with many similar objects.
Authors need a complete document-ordered list that can find and select those existing roots without changing content
or introducing a persistent selection model.

The list must remain bound to the current authorized document session. Document-derived text is untrusted UI data,
and any changed root set, stale authorization or incomplete group must fail before the current selection is replaced.

## Decision

An accessible responsive **Objektliste ...** dialog lists all standalone root shapes and complete root shape groups
in canonical document order. Each entry carries a validated opaque ID, root kind, strictly increasing root index and
a plain-text label derived from established shape text, kind, group members, document position and logical anchor.
The UI inserts these labels through text nodes only.

Search operates on normalized labels and a type filter limits the visible set to all objects, standalone shapes or
complete groups. Select-all-matches, invert-matches and clear operate on the candidate selection. Every operation is
atomic and the candidate is bounded to zero through twenty unique roots; exceeding the bound rejects the requested
change.

Opening records the authorized editor session, exact document instance and current root-ID/type/order tuple. Applying
requires current write permission and revalidates the complete tuple, unique IDs, supported root kinds and strictly
increasing nonnegative root indexes. Unknown, duplicate, unsorted, changed or no-longer-complete roots fail closed.

An accepted plan sorts the selected roots by current document order and replaces only the established transient
multi-selection. It does not dispatch a ProseMirror transaction, create history or write Office JSON. Cancel, close,
Escape, session/document change, historical mode and lost write permission preserve or clear transient state as
appropriate without a content mutation.

## Consequences

Strict model tests cover input type, cardinality, uniqueness, root kind, order and unknown-ID boundaries. Responsive
desktop/mobile coverage proves search, type filtering, match operations, application, cancellation, hidden roots,
complete groups and immediate use by existing multi-object commands. The focused run passes 3/3 in 51.0 seconds, the
targeted mobile rotation regression passes 1/1 and the complete native-shape matrix passes 42/42 in 5.0 minutes. The
initial 41/42 run remains diagnostic evidence for the compact mobile-toolbar correction.

The feature adds no migration, endpoint, dependency, external request, provider, worker, recovery store,
browser/clipboard persistence, cross-document or cross-tenant transfer, content write, nested group, arbitrary
connector, physical page anchor or DOCX DrawingML admission. It does not activate an ordinary tenant, pilot, indexing
path or document engine.
