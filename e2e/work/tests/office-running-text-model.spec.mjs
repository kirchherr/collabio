import { test, expect } from "@playwright/test";
import { officeRunningSettings, officeRunningCssString, officeRunningNumber } from "../office-running.mjs";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { findDocumentMatches, replaceDocumentMatches } from "../office-search.mjs";
const running = () => ({ header: 'Café "quote" \\ 😀', footer: "Internal", numbering: "pageOfPages" });
const doc = () => ({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Café 😀 text" }] }] });

test("running text validates literal shapes Unicode bounds and occupied margins", () => {
  for (const value of [null, {}, [], true, { ...running(), extra: 1 }, { ...running(), numbering: "counter(x)" },
    ...[null, true, {}, "x".repeat(65), "\n", "\t", "\u0085", "\u2028", "\ud800"].map((header) => ({ ...running(), header }))]) {
    expect(() => officeRunningSettings(value)).toThrow();
  }
  expect(officeRunningSettings({ ...running(), header: "😀".repeat(64) }).header).toBe("😀".repeat(64));
  expect(() => officeRunningSettings(running(), { margins: { top: 15, bottom: 18 } })).toThrow();
  expect(() => officeRunningSettings(running(), { margins: { top: 18, bottom: 15 } })).toThrow();
  expect(officeRunningSettings(undefined, { margins: { top: 5, bottom: 5 } }).numbering).toBe("none");
});
test("running text encodes all CSS delimiters literally and exposes fixed numbering examples", () => {
  const text = '";content:url(https://bad.invalid);\\😀';
  const encoded = officeRunningCssString(text);
  expect(encoded).toMatch(/^"(?:\\[a-f0-9]+ )*"$/);
  expect([...encoded.matchAll(/\\([a-f0-9]+) /g)].map((match) => String.fromCodePoint(parseInt(match[1], 16))).join("")).toBe(text);
  expect(officeRunningNumber(running(), 2, 4)).toBe("Seite 2 von 4");
  expect(officeRunningNumber({ numbering: "page" }, 2, 4)).toBe("Seite 2");
});
test("running metadata comparison includes reset without changing body identity", () => {
  const before = doc(), after = { ...before, attrs: { running: running() } };
  for (const [left, right] of [[before, after], [after, before]]) {
    const result = compareOfficeDocuments(left, right);
    expect(result.counts).toEqual({ equal: 1, changed: 1, added: 0, removed: 0 });
    expect(describeOfficeBlock(result.rows[1].after).label).toBe("Kopf-/Fußzeilen und Seitenzahlen");
  }
});
test("running metadata preserves body Unicode search and replacement positions", () => {
  const before = { ...doc(), attrs: { running: running() } }, snapshot = structuredClone(before);
  const matches = findDocumentMatches(before, "text");
  expect(matches[0].from).toBe(9);
  expect(replaceDocumentMatches(before, matches, "new").document.attrs).toEqual(before.attrs);
  expect(before).toEqual(snapshot);
});
