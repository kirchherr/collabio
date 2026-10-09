# ADR-0088: Native Office format transfer

Date: 2026-09-22
Status: Accepted

## Context

Native Office already supports strict paragraph attributes and character marks. Reapplying the same presentation
through separate dialogs is repetitive. Users need a way to copy a uniform presentation within a document without
copying text, importing rich clipboard data or introducing another durable document format.

## Decision

Add a native **Format übertragen** menu. An editable caret or uniformly formatted selection supplies a sample of
bold, italic, underline, strike, font size/color and paragraph alignment/line/before/after spacing. Mixed samples are
rejected with guidance to place the caret in the desired source. Code is excluded. Users apply characters,
paragraphs or both to the current selection, and can reuse or explicitly discard the sample.

The sample contains normalized allowlisted presentation values plus in-memory ownership references. It belongs to
the current editor/session/context, is not serialized, and is cleared on remount/close/context change. No source text,
system clipboard, browser storage, cross-document or cross-tenant transfer is introduced. Capture and discard do not
dirty content. Empty attributes are meaningful defaults and clear the chosen target formatting.

Application uses exact supported text ranges and selected paragraphs, including CellSelection ranges. It preserves
text, code, heading levels, list/table structure and unselected content. Paragraph-only transfer preserves pending
typing marks. Character-only application at a caret selects marks for subsequent typing without dirtying the saved
document. A document edit is one validated transaction, isolated from adjacent typing in undo history. No-op stays
clean. The existing full schema, character/node/depth and ASCII-canonical-byte preflight remains authoritative.

The existing writable-session, historical/busy/uncertain-state and review/suggestion guards gate capture/application.
Only the ordinary explicit confirmed CAS Save persists a result, with fresh server authorization and immutable old
versions. There is no new endpoint, dependency, schema, migration, mark, paragraph attribute or storage contract.

## Consequences

Users can repeat an exact direct format without reconstructing it through dialogs. Format samples do not become
named styles and do not include computed browser CSS, inherited heading presentation or block types. Code and
cross-document style libraries remain outside this slice. Existing recovery evidence remains applicable to the
unchanged durable format; this UI-only addition does not claim a new recovery drill or tenant/pilot admission.

Browser checks cover combined/separate/default transfer, exact Unicode ranges, selected cells, code exclusion,
mixed/no-op/clear behavior, pending caret marks, undo/redo, confirmed versions, size rejection, context invalidation,
read-only behavior and responsive controls. Full acceptance is recorded in docs/CURRENT_HANDOFF.md.
