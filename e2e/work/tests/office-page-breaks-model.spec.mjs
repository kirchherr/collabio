import { test, expect } from "@playwright/test";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const marker = { type: "pageBreak" };
test("native page breaks retain UTF-16 search replacement positions and immutable boundaries", () => {
  const before = { type: "doc", content: [p("A😀"), marker, p("After")] };
  const matches = findDocumentMatches(before, "After");
  expect(matches).toEqual([{ from: 7, to: 12 }]);
  expect(replaceDocumentMatches(before, matches, "Changed").document).toEqual({ type: "doc", content: [p("A😀"), marker, p("Changed")] });
  expect(before.content[2]).toEqual(p("After"));
});
test("native page breaks appear as positioned additions and removals in comparison", () => {
  const before = { type: "doc", content: [p("Before"), p("After")] };
  const after = { type: "doc", content: [before.content[0], marker, before.content[1]] };
  const compared = compareOfficeDocuments(before, after);
  expect(compared.rows.map((row) => row.kind)).toEqual(["equal", "added", "equal"]);
  expect(describeOfficeBlock(compared.rows[1].after)).toEqual({ label: "Seitenumbruch", text: "Neue Seite" });
  expect(compareOfficeDocuments(after, before).rows.map((row) => row.kind)).toEqual(["equal", "removed", "equal"]);
});
