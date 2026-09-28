# ADR-0096: Document-owned headers, footers and page numbering

Date: 2026-09-24
Status: accepted; development validation, dev001 rollout and GitHub publication complete

Optional root `attrs.running` contains exactly header/footer literal strings (each at
most 64 Unicode code points, no C0/C1 controls, surrogate scalars or line separators)
and numbering `none`, `page` or `pageOfPages`. Absence means empty running text and no
numbers, preserving all legacy canonical bytes. No fields, links, HTML or CSS input.
Enabled header/footer regions require at least 16 mm of the corresponding saved
margin. The existing page dialog validates geometry and running text together and
applies one isolated undo transaction. Explicit empty metadata survives no-op reads;
reset removes only running metadata. Confirmed CAS Save remains the durability boundary.

History, comparison, independent copies and exact-source recovery retain the metadata.
Screen preview is illustrative; actual pagination and page totals belong to printing.
The trusted stylesheet has static top-center/bottom-center margin rules at 8 pt with
bounded wrapping and padding. Freshly authorized literals are escaped code point by
code point into CSS strings; numbering uses only fixed page/pages counters. The
rules are cleared after printing, close, failure and context invalidation. Unsupported
margin-box engines refuse this output rather than silently omitting running content.
Reference: https://developer.chrome.com/blog/print-margins

Actual multi-page PDFs must verify repeated literal text, consecutive numbers/totals,
separation from body content and reset without stale text. Include special characters,
long values, both papers/orientations and explicit/automatic page breaks. Fresh isolated
recovery binds legacy, header/footer with totals, page-only and reset versions, retaining
all prior page/image/version proofs. No SQL, endpoint, dependency or decoder change.
Sections, first-page differences, arbitrary fields, continuous editor pagination,
DOCX interchange and ordinary tenant/engine activation remain separate work.
