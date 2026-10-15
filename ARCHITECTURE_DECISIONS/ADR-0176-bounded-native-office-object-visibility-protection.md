# ADR-0176: Bounded native Office object visibility and editing protection

Date: 2026-10-10

Status: Accepted

## Context

Native Office authors can find, select and transform standalone shapes and complete groups, but complex documents need
a reversible way to remove an object from the working and printed view and to protect finished objects from accidental
editing. These states must remain recoverable without turning presentation metadata into access control.

Visibility and editing protection are document content. They must therefore pass identical browser and authoritative
server validation, remain bound to the current authorized document session and participate in immutable versions.
They must never be described or enforced as confidentiality, ACL, authorization or a collaborative lease.

## Decision

Standalone root shapes and complete root shape groups admit optional canonical `hidden: true` and `locked: true`
attributes. Omission means visible and editable. Only literal `true` is persisted. Browser-internal null values are
canonically omitted; false, numbers, strings, unknown keys and either state on grouped member shapes fail closed.

The responsive object navigator describes and searches both states and provides explicit show, hide, lock and unlock
actions for one through twenty complete roots. Hidden roots are absent from editor layout and semantic print/PDF but
remain in canonical document content and order, so the navigator can recover them. The UI explains that hiding neither
deletes nor protects content.

Locked roots remain selectable and navigable. Ordinary single- and multi-object dialogs, handles, pointer, touch and
keyboard mutations are disabled, while visibility controls and unlock remain available. The UI explains that this is
accidental-edit protection and does not replace authorization.

Opening and applying state actions use the established authorized editor session. Application revalidates current
write permission, the exact document instance and the strict unique root ID/type/order tuple. Stale, duplicate,
unsorted, missing or changed targets fail without mutation. One effective action updates every selected root in one
validated document transaction and one undo unit.

## Consequences

Two focused Python schema contracts, 22/22 strict model tests, targeted desktop/mobile workflows and the complete
46/46 native-shape matrix pass. Confirmed save, immutable predecessor reads, navigator recovery, semantic print and
undo/redo are covered. The complete repository gate passes Ruff, formatting, Mypy over 607 source files and Pytest to
100 percent.

The feature adds no migration, new endpoint, dependency, external request, provider, worker, recovery store, security
label, access-control change, collaborative lock, cross-document or cross-tenant transfer, ordinary-tenant activation,
document engine or DOCX DrawingML admission.
