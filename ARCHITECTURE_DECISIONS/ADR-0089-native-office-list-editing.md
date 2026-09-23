# ADR-0089: Native Office list levels and numbering

Date: 2026-09-22
Status: Accepted

## Context

Native documents already support nested bullet/ordered lists and bounded ordered-list start values. The workspace
needs discoverable editing of those structures with the same selection, undo and size guarantees as other formatting.

## Decision

Add **Listenebenen und Nummerierung** beside the existing list controls. An editor caret or text selection inside
one nearest list opens a selection-bound dialog. Indent moves selected sibling items under the previous item;
outdent lifts them one level, or into paragraphs at the outer level. Existing ProseMirror schema-list commands
construct candidate transactions. Text, marks, paragraph attributes and contained sublists remain in the document.

An ordered list exposes an integer start from 1 through 1,000,000, changing that entire nearest list only. This uses
the existing native start attribute; it does not introduce automatic continuation or named numbering styles.
Mixed-list, cell, whole-document and code selections are excluded. Disabled actions explain their scope in the dialog.

Every action uses the existing writable-session/review/suggestion guards and full schema/character/node/depth/
canonical-byte preflight before dispatch. A dialog binds editor, session, context, revision, document, selection and
pending marks; changes invalidate it. Cancel, invalid input and no-op stay clean. Each change is one undo group,
separate from typing, and pending marks are retained. Only the ordinary confirmed CAS Save appends a durable version.

Alt+Shift+Right/Left use the same validated commands. Outside tables, Tab/Shift+Tab also use them; unavailable Tab
actions leave through a reachable toolbar control. Table Tab navigation takes precedence. Unsupported list selections
consume list shortcuts rather than falling through to an unscoped default command. Other typing shortcuts are unchanged.

No backend, endpoint, dependency, SQL migration or native-format change is introduced. Existing comparison, print and
recovery paths already support list nesting/start. Roadmap 263 recovery is retained; this UI slice does not authorize
tenant/pilot/engine/indexing activation or claim a new recovery drill. Acceptance is recorded in CURRENT_HANDOFF.md.

## References

- [ProseMirror schema-list source](https://github.com/ProseMirror/prosemirror-schema-list/blob/master/src/schema-list.ts)
- [Tiptap list-item shortcuts](https://tiptap.dev/docs/editor/extensions/nodes/list-item)
