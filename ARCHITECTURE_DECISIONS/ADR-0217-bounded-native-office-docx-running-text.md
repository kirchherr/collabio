# ADR-0217 Bounded native Office DOCX running text

## Status

Accepted for the synthetic development preview.

## Decision

- Admit only default header and footer references on explicit, already supported section profiles. Resolve each
  independently in section order. An omitted reference inherits the previous effective value, starting empty.
  A referenced empty paragraph explicitly clears that value.
- Resolve a unique internal relationship from `word/_rels/document.xml.rels` to a direct canonical
  `word/header*.xml` or `word/footer*.xml` part of the matching kind and exact content type. Use only ASCII
  names with a bounded suffix. Referenced parts must have no relationship sidecar. Read bounded XML without
  DTDs or entities. Reject malformed, duplicate, external and ambiguous references and targets.
- Accept exactly one plain paragraph with text-only runs or an empty paragraph per part. Preserve literal spaces.
  Require at most 64 characters and the existing native single-line character rules. Reject fields, native field
  placeholder syntax, hyperlinks, drawing, nested markup and formatting. First-page and even-page variants
  remain outside the profile, including enabled even/odd header mode in document settings. Header and footer
  positions follow native print styling.
- Bind the resolved literals to canonical structure evidence for the document root and section markers. Keep them
  out of body text equality and existing text-only extraction. Preserve the existing parser wire shape for
  sources without running text. The API maps literal data into strict native running profiles with numbering
  set to none. The native schema independently validates text and the minimum 16 mm margin for nonempty content.
- Reuse the existing exact-source ACL, provenance, classification, memory-only preview and confirmed save path.
  Verify inheritance, clearing and ordering using an authorized stored synthetic source and real Chromium PDF
  output on desktop and mobile.

## Consequences

No new socket schema, dependency, storage, production admission or editor runtime is required. Fields, custom
placement and exact Word layout remain separate scopes.

[Microsoft header semantics](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.headerreference) ·
[Word footer inheritance](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/02af532c-6791-4f63-b4b2-cd20e58dce91)
