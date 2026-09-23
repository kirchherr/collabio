# ADR-0095: Document-owned native page settings

Date: 2026-09-23
Status: accepted; implementation and remote validation in progress

Optional root `attrs.page` contains exactly `paper` (a4/letter), `orientation`
(portrait/landscape) and `margins` with integer `top`, `right`, `bottom`, `left`
values from 5 through 50 millimetres. No CSS, strings for numbers, extra keys,
partial objects or nested page settings are admitted. Absence means A4 portrait
with 18 mm on every side and leaves all legacy canonical bytes unchanged.
Explicit valid default metadata remains readable without rewriting saved bytes;
reset in the editor removes the optional attribute. Existing styles coexist.

The Page dialog previews paper proportions and margins without changing the draft.
Apply makes one prevalidated, context-bound document transaction, isolated from
typing in undo history and retaining selection/pending marks. Cancel/no-op stays
clean. Read-only/history, loading, pending or uncertain saves and existing review
guards remain enforced. Only confirmed CAS Save creates a durable version.
The responsive editor shows a continuous sheet; it does not claim exact pagination.

History, comparison, takeover, independent copies, search and suggestion replacement
preserve page metadata. Comparison explicitly names page-setting changes, including
reset. Print initializes paper/orientation from the freshly authorized saved version
and uses its four margins. Existing paper/orientation controls remain temporary
print overrides, clearly labelled and never saved. They reset on a new print session.
Final output reauthorizes content/images and constructs its page rule from validated
enums/numbers through the trusted local stylesheet's CSSOM; CSP stays unchanged.
Browser destination/settings still determine final physical output.

Actual A4/Letter portrait/landscape PDFs must verify dimensions, asymmetric margins,
explicit page breaks, wrapped images and tables. Fresh nonempty isolated recovery
must bind a four-version legacy/custom/second-profile/reset fixture with exact
JSON, canonical hashes and lineage, plus the previous document/image proofs.
No endpoint, SQL migration, dependency, decoder or tenant admission change is needed.
Compatible historical readers are required after rollback. Section layouts,
headers/footers, continuous pagination and DOCX interchange remain separate.
