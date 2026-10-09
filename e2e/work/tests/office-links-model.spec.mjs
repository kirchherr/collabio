import { test, expect } from "@playwright/test";
import { OFFICE_LINK_MAX, officeAutomaticLinkContent, officeAutomaticLinks, officeLinkDOMAttributes, officeLinkDescription, officeLinkHref } from "../office-links.mjs";
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

test("Office automatic links recognize only complete safe HTTPS and mail tokens", () => {
  const text = "Siehe (https://example.org/a_(b)). Mail name@example.org, aber nicht http://unsafe.invalid oder javascript:alert(1).";
  expect(officeAutomaticLinks(text)).toEqual([
    { from: 7, to: 32, href: "https://example.org/a_(b)" },
    { from: 40, to: 56, href: "mailto:name@example.org" },
  ]);
  expect(officeAutomaticLinks("mailto:office@example.org https://user:secret@example.org x@y..example.org")).toEqual([
    { from: 0, to: 25, href: "mailto:office@example.org" },
  ]);
  expect(() => officeAutomaticLinks(null)).toThrow();
});

test("Office automatic link content keeps every literal character and adds only canonical marks", () => {
  expect(officeAutomaticLinkContent("A https://example.org/docs. B name@example.org! C")).toEqual([
    { type: "text", text: "A " },
    { type: "text", text: "https://example.org/docs", marks: [{ type: "link", attrs: { href: "https://example.org/docs" } }] },
    { type: "text", text: ". B " },
    { type: "text", text: "name@example.org", marks: [{ type: "link", attrs: { href: "mailto:name@example.org" } }] },
    { type: "text", text: "! C" },
  ]);
  expect(officeAutomaticLinkContent("plain text")).toEqual([{ type: "text", text: "plain text" }]);
});
