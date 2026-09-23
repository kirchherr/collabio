import { test, expect } from "@playwright/test";
import { officePageSettings, officePageDimensions, officePageDescription } from "../office-page.mjs";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";

const profile = () => ({ paper: "letter", orientation: "landscape", margins: { top: 12, right: 25, bottom: 30, left: 40 } });
const doc = () => ({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Café 😀 text" }] }] });

test("page settings validate complete inert geometry and isolate defaults", () => {
  for (const value of [null, {}, [], true, { ...profile(), paper: "url(SECRET)" }, { ...profile(), orientation: {} },
    { ...profile(), margins: [] }, { ...profile(), extra: "SECRET" },
    ...[4, 51, 18.5, true, "18", null, Infinity].map((left) => ({ ...profile(), margins: { ...profile().margins, left } }))]) {
    expect(() => officePageSettings(value)).toThrow();
  }
  const defaults = officePageSettings(); defaults.margins.left = 50;
  expect(officePageSettings().margins.left).toBe(18);
  expect(officePageSettings(profile())).toEqual(profile());
});

test("page dimensions resolve all papers orientations and asymmetric margins", () => {
  for (const paper of ["a4", "letter"]) for (const orientation of ["portrait", "landscape"]) {
    const value = { ...profile(), paper, orientation }, size = officePageDimensions(value);
    expect(size.width > size.height).toBe(orientation === "landscape");
    expect(size.contentWidth).toBeCloseTo(size.width - 65);
    expect(size.contentHeight).toBeCloseTo(size.height - 42);
    expect(officePageDescription(value)).toContain("links 40 mm");
  }
});

test("page-only changes and reset are explicit without changing content identity", () => {
  const before = doc(), after = { ...before, attrs: { page: profile() } };
  for (const [left, right] of [[before, after], [after, before]]) {
    const result = compareOfficeDocuments(left, right);
    expect(result.counts).toEqual({ equal: 1, changed: 1, added: 0, removed: 0 });
    expect(result.rows[0].before).toBe(before.content[0]);
    expect(describeOfficeBlock(result.rows[1].after).label).toBe("Seiteneinstellungen");
  }
  expect(compareOfficeDocuments(before, doc()).rows).toHaveLength(1);
});

test("page metadata does not shift Unicode search or replacement positions", () => {
  const before = { ...doc(), attrs: { page: profile() } }, snapshot = structuredClone(before);
  const matches = findDocumentMatches(before, "text");
  expect(matches[0].from).toBe(9);
  const result = replaceDocumentMatches(before, matches, "new");
  expect(result.document.attrs).toEqual(before.attrs);
  expect(before).toEqual(snapshot);
});
