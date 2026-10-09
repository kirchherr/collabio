# ADR-0087: Native Office character formatting

Status: accepted; development validation complete
Date: 2026-09-22
Roadmap: 263 / PLANS 124

## Decision

Add one optional `textStyle` mark on native text with at least one attribute: integer `fontSize` in
8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36 or 48 points, and/or `textColor` from
black, slate, red, orange, green, teal, blue or purple. Colors are fixed named CSS choices, not document-supplied CSS.
Reject empty/unknown attributes, nulls, booleans, duplicate marks, code combinations and marks on blocks.
Server validation never normalizes old JSON. Native v1 MIME/schema identifiers and legacy canonical bytes remain unchanged.
No SQL migration, endpoint or dependency is added. Rollbacks require a compatible reader/validator before edits are admitted.

The compact selection-bound dialog changes only selected text or pending typing marks at a supported caret.
Mixed values stay unchanged unless selected; Standard removes the property. Reset prepares both defaults for Apply.
Caret choices alone do not dirty a saved document. Selection changes use one undo group; no-op/cancel leaves state intact.
Code is excluded, other marks and paragraph properties survive, and exact table selection ranges are respected.
Existing context/document/revision, current ACL, historical view, confirmed CAS save and uncertain retry boundaries apply.

Print renders inert spans with allowlisted data attributes and fixed CSS shared with the editor. Comparison describes
sizes and named colors at text positions. Replacement distinguishes complete mark attributes rather than just mark types.
Existing review offsets and suggestion acceptance preserve mark payloads through their current source/version checks.

## Verification and continuity

Require strict validation negatives, legacy byte preservation, actual PG/API version/receipt/CAS checks, browser editing,
caret/mixed/reset/undo/table/Unicode/permissions/retry/limits tests, actual PDF and responsive visual checks, full regression
and remote quality. A fresh nonempty PG/S3 recovery uses separate `collabio_work_e2e_263_restore`, retains both older
targets and proves one legacy plus two distinct saved character profiles under existing authoritative principals.
Keep all prior inventory/receipt/review/suggestion proofs; ordinary tenants, pilot, indexing and engine gates stay closed.

Validation completed on the unchanged product implementation through test-only closeout `75f381a`:
full Python quality, 362 focused Python checks, and passing coverage of all 231 browser/model cases.
The complete matrix retained 230 passes and one history-fixture setup failure; after isolating its editable head,
the complete eight-case history suite passed. Raw reports remain retained; this is not a single 231-pass run.
Six responsive/print screenshots and both actual A4 PDF pages passed root visual review. Fresh nonempty recovery
verified 460 documents, 935 saved versions and 1,045 source objects, including unchanged legacy bytes and both
character profiles. Release and operational evidence is recorded in `docs/CURRENT_HANDOFF.md`.
Whole-document keyboard replacement across rich tables remains a separate usability follow-up.
