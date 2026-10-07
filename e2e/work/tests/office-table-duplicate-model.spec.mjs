import { expect, test } from "@playwright/test";

import { duplicateOfficeTableColumns, duplicateOfficeTableRows } from "../office-tables.mjs";

const paragraph = (text) => ({ type: "paragraph", content: [{ type: "text", text }] });
const cell = (type, text, attrs = undefined) => ({ type, ...(attrs ? { attrs } : {}), content: [paragraph(text)] });
const row = (...cells) => ({ type: "tableRow", content: cells });
const table = { type: "table", attrs: { style: "accent" }, content: [
  row(cell("tableHeader", "Name"), cell("tableHeader", "Q1"), cell("tableHeader", "Q2")),
  row(cell("tableHeader", "Alpha"), cell("tableCell", "1", { background: "blue" }), cell("tableCell", "2")),
  row(cell("tableHeader", "Bravo"), cell("tableCell", "3"), cell("tableCell", "4")),
  row(cell("tableHeader", "Charlie"), cell("tableCell", "5"), cell("tableCell", "6")),
] };
const texts = (value) => value.content.map((entry) => entry.content.map((item) => item.content[0].content[0].text));

test("Office table rows duplicate complete selections directly below", () => {
  const duplicated = duplicateOfficeTableRows(table, { from: 1, to: 3 });
  expect(texts(duplicated).map((entry) => entry[0]))
    .toEqual(["Name", "Alpha", "Bravo", "Alpha", "Bravo", "Charlie"]);
  expect(duplicated.content[3].content[1].attrs).toEqual({ background: "blue" });
  expect(duplicated.attrs).toEqual({ style: "accent" });
  duplicated.content[3].content[0].content[0].content[0].text = "Copied Alpha";
  expect(duplicated.content[1].content[0].content[0].content[0].text).toBe("Alpha");
});

test("Office table columns duplicate every cell directly to the right", () => {
  const duplicated = duplicateOfficeTableColumns(table, { from: 1, to: 3 });
  expect(texts(duplicated)).toEqual([
    ["Name", "Q1", "Q2", "Q1", "Q2"], ["Alpha", "1", "2", "1", "2"],
    ["Bravo", "3", "4", "3", "4"], ["Charlie", "5", "6", "5", "6"],
  ]);
  expect(duplicated.content[1].content[3].attrs).toEqual({ background: "blue" });
  duplicated.content[1].content[3].content[0].content[0].text = "Copied 1";
  expect(duplicated.content[1].content[1].content[0].content[0].text).toBe("1");
});

test("Office table duplication rejects protected headers merged grids invalid options and limits", () => {
  expect(() => duplicateOfficeTableRows(table, { from: 0, to: 1 })).toThrow();
  expect(() => duplicateOfficeTableColumns(table, { from: 0, to: 1 })).toThrow();
  expect(() => duplicateOfficeTableRows(table, { from: 1, to: 2, extra: true })).toThrow();
  expect(() => duplicateOfficeTableColumns(table, { from: 1, to: 1 })).toThrow();
  const merged = { type: "table", content: [row(cell("tableCell", "x", { colspan: 2, rowspan: 1 })),
    row(cell("tableCell", "a"), cell("tableCell", "b"))] };
  expect(() => duplicateOfficeTableRows(merged, { from: 0, to: 1 })).toThrow();
  const fullRows = { type: "table", content: Array.from({ length: 200 }, (_, index) =>
    row(cell("tableCell", String(index)))) };
  expect(() => duplicateOfficeTableRows(fullRows, { from: 0, to: 1 })).toThrow();
  const fullColumns = { type: "table", content: [row(...Array.from({ length: 20 }, (_, index) =>
    cell("tableCell", String(index))))] };
  expect(() => duplicateOfficeTableColumns(fullColumns, { from: 0, to: 1 })).toThrow();
});
