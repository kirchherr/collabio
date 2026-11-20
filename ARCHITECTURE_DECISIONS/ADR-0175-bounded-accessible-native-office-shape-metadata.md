# ADR-0175: Bounded accessible native Office shape metadata

Date: 2026-10-10

Status: Accepted

## Context

Native Office shapes and complete groups have opaque stable IDs and visible content, but authors cannot assign a
concise object name or a purpose-oriented alternative description. This makes complex diagrams harder to navigate in
the object list and leaves assistive technology with technical geometry plus visible text only.

The metadata is document content and therefore must pass the same browser and authoritative server validation. It
must remain inert plain text, preserve legacy omission, participate in immutable versions and never become HTML,
style, URL or an external reference.

## Decision

Standalone shapes, grouped member shapes and complete root shape groups admit two optional canonical attributes:
`name` is one through 80 characters and `altText` is one through 500 characters. Values must be strings, exactly
trimmed and free of C0/C1 controls, surrogate code points and Unicode line or paragraph separators. Empty strings,
booleans, unknown keys and out-of-range values fail closed in browser and server validators. Null UI values are
canonically omitted.

The responsive shape dialog exposes **Objektname** and **Alternativtext** for the selected or new member shape. When a
complete group is being edited, **Gruppenname** and **Alternativtext der Gruppe** edit its wrapper metadata. The
existing transaction, validation and history boundary applies; no separate metadata endpoint or store exists.

The object navigator uses an available name as the primary label and includes alternative text in searchable details.
Visible shape text, kind, document position and logical anchor remain searchable. DOM text nodes render every value.
Shape and group descriptions feed editor accessibility names, comparison and semantic print/PDF. Save, immutable
history, duplication, grouping operations and independent reuse carry the attributes with their canonical objects.

## Consequences

Two focused Python schema tests cover valid and hostile shape/group values. Twenty-one strict model tests, four
targeted desktop/mobile workflows and the complete 43/43 native-shape matrix pass. The initial targeted browser run
received 422 from the server and exposed the missing authoritative allowlist; adding the identical server contract
closed the gap before acceptance. Live review finds **Freigabeschritt** by name and displays its alternative text,
visible text and document position.

The feature adds no migration, new endpoint, dependency, external request, provider, worker, recovery store, HTML,
URL, arbitrary attribute, cross-document or cross-tenant transfer, ordinary-tenant activation, document engine or
DOCX DrawingML admission.
