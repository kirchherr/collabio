import { expect, test } from "@playwright/test";

import { moveOfficeTableColumns, moveOfficeTableRows, officeTableReorderInfo } from "../office-tables.mjs";

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

test("Office table row moves preserve fixed headers complete rows and presentation", () => {
  expect(officeTableReorderInfo(table)).toEqual({ rows: 4, columns: 3, header: true, dataRows: 3, headerColumn: true });
  const moved = moveOfficeTableRows(table, { from: 2, to: 3, direction: "before" });
  expect(texts(moved).map((entry) => entry[0])).toEqual(["Name", "Bravo", "Alpha", "Charlie"]);
  expect(moved.content[2].content[1].attrs).toEqual({ background: "blue" });
  expect(moved.attrs).toEqual({ style: "accent" });
});

test("Office table column moves preserve the semantic first column and every cell", () => {
  const moved = moveOfficeTableColumns(table, { from: 2, to: 3, direction: "before" });
  expect(texts(moved)).toEqual([
    ["Name", "Q2", "Q1"], ["Alpha", "2", "1"], ["Bravo", "4", "3"], ["Charlie", "6", "5"],
  ]);
  expect(moved.content[1].content[2].attrs).toEqual({ background: "blue" });
});

test("Office table moves reject protected boundaries merged grids and unsupported options", () => {
  expect(() => moveOfficeTableRows(table, { from: 0, to: 1, direction: "after" })).toThrow();
  expect(() => moveOfficeTableColumns(table, { from: 1, to: 2, direction: "before" })).toThrow();
  expect(() => moveOfficeTableRows(table, { from: 1, to: 2, direction: "sideways" })).toThrow();
  const merged = { type: "table", content: [row(cell("tableCell", "x", { colspan: 2, rowspan: 1 })),
    row(cell("tableCell", "a"), cell("tableCell", "b"))] };
  expect(() => officeTableReorderInfo(merged)).toThrow();
});
