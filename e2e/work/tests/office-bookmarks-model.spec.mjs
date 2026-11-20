import { test, expect } from "@playwright/test";
import {
  OFFICE_BOOKMARK_LIMIT, officeBookmarkAttributes, officeBookmarkFragment, officeBookmarkInventory,
  officeCrossReferenceAttributes, officeCrossReferenceDescription,
} from "../office-bookmarks.mjs";
import { compareOfficeDocuments } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";

const content = (targetId = "bookmark-overview") => ({ type: "doc", content: [{ type: "paragraph", content: [
  { type: "bookmark", attrs: { id: "bookmark-overview", label: "Overview" } },
  { type: "text", text: "Overview" },
  { type: "text", text: "See overview", marks: [{ type: "crossReference", attrs: { targetId } }] },
] }] });

test("Office bookmark model keeps stable local-only identifiers and explicit broken references", () => {
  expect(OFFICE_BOOKMARK_LIMIT).toBe(100);
  expect(officeBookmarkAttributes({ id: "bookmark-overview", label: "Overview" })).toEqual({ id: "bookmark-overview", label: "Overview" });
  expect(officeCrossReferenceAttributes({ targetId: "bookmark-overview" })).toEqual({ targetId: "bookmark-overview" });
  expect(officeBookmarkFragment("bookmark-overview")).toBe("office-bookmark-bookmark-overview");
  expect(officeBookmarkInventory(content())).toEqual([{ id: "bookmark-overview", label: "Overview" }]);
  expect(officeCrossReferenceDescription({ targetId: "bookmark-overview" }, [])).toContain("Ziel nicht verfügbar");
  for (const invalid of ["Bookmark", "1-bookmark", "bookmark space", `bookmark-${"x".repeat(48)}`]) {
    expect(() => officeCrossReferenceAttributes({ targetId: invalid })).toThrow();
  }
});

test("Office bookmark targets remain exact through comparison and replacement", () => {
  const before = content();
  const after = content("bookmark-other");
  expect(compareOfficeDocuments(before, after).rows[0].kind).toBe("changed");
  const matches = findDocumentMatches(before, "See overview");
  const changed = replaceDocumentMatches(before, matches, "Read overview").document;
  expect(changed.content[0].content.at(-1).marks).toEqual(before.content[0].content.at(-1).marks);
  expect(changed.content[0].content[0]).toEqual(before.content[0].content[0]);
});
