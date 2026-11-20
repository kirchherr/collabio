# ADR-0219 Bounded native Office DOCX lists

## Status

Accepted for the synthetic development preview.

## Decision

- Resolve direct main-body paragraph numbering against package-local `word/numbering.xml`. Admit three levels
  of native bullet or simple decimal lists. Require an existing parent item in the same contiguous instance
  before descending. Reject skipped levels, ambiguous definitions, implicit style links, unsupported label
  formats, full level overrides, unsupported restart rules and list headings or page-break-before flags.
- Resolve each referenced instance and level independently. Preserve the bounded start value and start-only
  overrides. Keep a decimal instance's root ordinal across interruptions and reset descendants when their
  parent or an ancestor advances. A different instance starts with its own value. The absent start and label
  in legacy flat fixtures retain the existing native defaults.
- Use the existing flat parser shapes for simple lists. Bind nested structure and nondefault starts through a
  closed list-tree shape. Validate depth, counts, exact wire keys, starts and independent body text equality in
  the API. Unrepresentable list layouts refuse Office preview while preserving existing text-only extraction.
- Reuse exact-source authorization, classification, provenance and explicit native save. Prove nesting, reset,
  continuation and exact saved-version readback with a stored synthetic source on desktop and mobile.

## Consequences

Native styling owns bullet glyphs, indentation and decimal presentation. Compound labels, letter and Roman
formats and arbitrary restart policies remain outside this preview. No migration, dependency or release
admission is required.

[Numbering level restart](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.levelrestart) ·
[Word numbering restart semantics](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/140a2cd9-2f26-456d-9760-ae6ecef4e8b5)
