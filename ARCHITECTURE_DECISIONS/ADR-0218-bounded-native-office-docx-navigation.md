# ADR-0218 Bounded native Office DOCX navigation

## Status

Accepted for the synthetic development preview.

## Decision

- Import up to 100 visible, uniquely named bookmarks. Each start/end pair must be ordered, nonoverlapping and
  contained in one top-level nonlist paragraph or heading. The native point sits at the range start. Its ID is
  derived from the canonical nonnegative decimal DOCX bookmark ID, and its label is the original bounded ASCII
  name. Hidden underscore-prefixed bookmarks stay inert.
- Admit only direct main-body paragraph or heading hyperlinks with a literal `w:anchor` to an exact admitted
  bookmark name. Keep up to 200 linked text runs and their admitted inline marks. Link text remains in the body
  text. Bookmark points do not contribute text. Reject ambiguous pairs, missing destinations, mixed local and
  relationship targets, paragraphs containing explicit hard or cached page breaks or fields, and marked-up
  link bodies outside the bounded run grammar.
- Preserve the existing inert text behavior for relationship hyperlinks and fields without an admitted anchor.
  Never resolve an external destination or load relationship data for navigation. Ambiguous navigation refuses
  the structured preview while retaining existing body extraction.
- Bind positions and target IDs to canonical parser structure evidence. The API independently checks the closed
  wire shape, target namespace, count and resolved destination before native schema validation. Normal native
  editing retains its existing behavior for bookmarks removed after import.
- Verify exact-source authorization, classification, explicit save and readback with an unmocked synthetic
  stored source. Exercise the native navigation action and actual PDF destination on desktop and mobile.
  Temporarily detach the screen preview during printing so only the fresh print surface owns fragment IDs.

## Consequences

The scope covers point destinations and explicit internal text links. Range highlighting, fields, table and list
navigation, and external links remain separate. No new storage, migration, runtime admission or dependency is
required.

[Bookmark pair semantics](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bookmarkend) ·
[Word hyperlink targets](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/df06e423-11a6-4a36-bfb3-82139e531781)
