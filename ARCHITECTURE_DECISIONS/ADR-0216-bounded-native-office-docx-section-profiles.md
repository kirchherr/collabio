# ADR-0216 Bounded native Office DOCX section profiles

## Status

Accepted for the synthetic development preview.

## Decision

- Use only the main document part. A nonfinal section ends at the direct `w:pPr/w:sectPr` of a main-body
  paragraph. The final profile comes from the last direct child of the body. Map the first profile to the native
  document root and each later one to a native marker immediately after the preceding section's last paragraph.
  A missing or empty final profile without intermediate boundaries retains the earlier default-page behavior.
- Require explicit geometry for each admitted profile. Accept A4 and Letter with matching portrait or landscape
  dimensions, four nonnegative margins equivalent to 5–50 mm at twip precision, and zero gutter. Round margins to
  the nearest whole millimeter. Accept one, two or three equal-width columns with native gap and rule styling.
  Accept omitted or standard half-inch source column spacing. Ignore bounded unused header/footer offsets.
- Accept at most twelve section markers with default or explicit next-page transitions. Reject custom geometry,
  nested or duplicate properties, missing final profiles in multisection sources, tracked section changes,
  unequal columns, header/footer references, page number restarts and other unmodeled section settings.
  Leading, trailing, consecutive and page-break-adjacent markers fail closed. A following page-break-before flag
  also makes that boundary ambiguous.
- Hash the canonical page profile and section markers as structure evidence. Keep these records out of normalized
  text equality. Unsupported section layout is represented by a fixed nontext parser block so existing callers
  can still extract text and Office refuses the unsafe structured preview. No new socket fields are needed.
- Map profiles through the strict existing native schema and use the existing editor and print surfaces. Retain
  current source ACL and exact-version checks, classification, memory-only preview and confirmed native save.
  Prove the root and following-section profiles using an authorized synthetic stored source on desktop and mobile
  and inspect the ordered page dimensions of the real Chromium print output.

## Consequences

Native PDF uses Collabio's paper, margin and column semantics. Word pagination, running content, continuous
sections and productive interchange remain separate scopes. No migration, dependency or runtime admission change
is needed.

[Section properties placement](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sectionproperties?view=openxml-3.0.1) ·
[Section type semantics](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.sectiontype?view=openxml-3.0.1) ·
[Page dimensions](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.pagesize?view=openxml-2.8.1)
