import { test, expect } from "@playwright/test";
import { OFFICE_SECTION_LIMIT, officeSectionDescription, officeSectionProfile } from "../office-sections.mjs";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";

const p = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const profile = () => ({ page: { paper: "letter", orientation: "landscape",
  columns: "three", margins: { top: 20, right: 12, bottom: 22, left: 14 } },
running: { header: "Appendix", footer: "Internal", numbering: "pageOfPages" } });
const marker = () => ({ type: "sectionBreak", attrs: profile() });

test("section profiles are exact bounded inert page and running settings", () => {
  expect(OFFICE_SECTION_LIMIT).toBe(12);
  expect(officeSectionProfile(profile())).toEqual(profile());
  expect(officeSectionDescription(profile())).toContain("Letter · Querformat");
  for (const value of [null, {}, [], { ...profile(), extra: true },
    { ...profile(), running: { ...profile().running, firstPage: { header: "x", footer: "", showNumber: false } } },
    { ...profile(), running: { ...profile().running, header: "x".repeat(65) } },
    { ...profile(), page: { ...profile().page, columns: "var(--secret)" } },
    { ...profile(), page: { ...profile().page, margins: { ...profile().page.margins, bottom: 15 } } }]) {
    expect(() => officeSectionProfile(value)).toThrow();
  }
});

test("section boundaries preserve UTF-16 search replacement positions and profiles", () => {
  const before = { type: "doc", content: [p("A😀"), marker(), p("After")] }, snapshot = structuredClone(before);
  const matches = findDocumentMatches(before, "After");
  expect(matches).toEqual([{ from: 7, to: 12 }]);
  const changed = replaceDocumentMatches(before, matches, "Changed").document;
  expect(changed.content[1]).toEqual(marker());
  expect(changed.content[2]).toEqual(p("Changed"));
  expect(before).toEqual(snapshot);
});

test("section boundaries appear as positioned additions and profile changes", () => {
  const before = { type: "doc", content: [p("Before"), p("After")] };
  const after = { type: "doc", content: [before.content[0], marker(), before.content[1]] };
  const added = compareOfficeDocuments(before, after);
  expect(added.rows.map((row) => row.kind)).toEqual(["equal", "added", "equal"]);
  expect(describeOfficeBlock(added.rows[1].after)).toEqual({ label: "Abschnittsumbruch", text: "Neuer Abschnitt" });
  const altered = structuredClone(after); altered.content[1].attrs.page.orientation = "portrait";
  expect(compareOfficeDocuments(after, altered).rows[1].kind).toBe("changed");
});
