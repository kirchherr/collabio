import { test, expect } from "@playwright/test";
import { OFFICE_LINK_MAX, officeLinkDOMAttributes, officeLinkDescription, officeLinkHref } from "../office-links.mjs";
import { compareOfficeDocuments } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";

const paragraph = (href) => ({ type: "paragraph", content: [{ type: "text", text: "Reference", marks: [{ type: "link", attrs: { href } }] }] });

test("Office link model accepts canonical HTTPS and mailto targets without active content", () => {
  expect(OFFICE_LINK_MAX).toBe(2048);
  expect(officeLinkHref("https://example.org/docs?q=1#part")).toBe("https://example.org/docs?q=1#part");
  expect(officeLinkHref("mailto:name@example.org")).toBe("mailto:name@example.org");
  expect(officeLinkDOMAttributes("https://example.org/")).toEqual({ href: "https://example.org/", rel: "noopener noreferrer", target: "_blank", "data-office-link": "true" });
  expect(officeLinkDescription("mailto:name@example.org")).toBe("E-Mail: name@example.org");
  for (const href of ["http://example.org", "javascript:alert(1)", "data:text/html,x", "file:///tmp/x", "https://u:p@example.org", "mailto:a@example.org?subject=x", "https://example.org/<x>"]) {
    expect(() => officeLinkHref(href)).toThrow();
  }
});

test("Office link targets remain exact through comparison and text replacement", () => {
  const before = { type: "doc", content: [paragraph("https://example.org/old")] };
  const after = { type: "doc", content: [paragraph("https://example.org/new")] };
  expect(compareOfficeDocuments(before, after).rows[0].kind).toBe("changed");
  const matches = findDocumentMatches(before, "Reference");
  const changed = replaceDocumentMatches(before, matches, "Source").document;
  expect(changed.content[0].content[0].marks).toEqual(before.content[0].content[0].marks);
});
