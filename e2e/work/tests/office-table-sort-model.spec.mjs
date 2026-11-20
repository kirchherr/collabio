import { expect, test } from "@playwright/test";

import { officeTableSortInfo, sortOfficeTable } from "../office-tables.mjs";

const paragraph = (text) => ({ type: "paragraph", content: text ? [{ type: "text", text }] : undefined });
const cell = (type, text, attrs = undefined) => ({ type, ...(attrs ? { attrs } : {}), content: [paragraph(text)] });
const row = (...cells) => ({ type: "tableRow", content: cells });
const table = { type: "table", attrs: { style: "banded" }, content: [
  row(cell("tableHeader", "Name"), cell("tableHeader", "Amount"), cell("tableHeader", "Date")),
  row(cell("tableCell", "Charlie", { background: "blue" }), cell("tableCell", "2"), cell("tableCell", "2026-02-01")),
  row(cell("tableCell", "Alpha"), cell("tableCell", "10"), cell("tableCell", "2025-12-31")),
  row(cell("tableCell", "Bravo"), cell("tableCell", "2"), cell("tableCell", "2026-01-15")),
] };

const firstColumn = (value) => value.content.map((entry) => entry.content[0].content?.[0]?.content?.[0]?.text || "");

test("Office table sorting is stable and preserves headers complete rows and presentation", () => {
  expect(officeTableSortInfo(table)).toEqual({ rows: 4, columns: 3, header: true, dataRows: 3 });
  const text = sortOfficeTable(table, { column: 0, type: "text", direction: "ascending" });
  expect(firstColumn(text)).toEqual(["Name", "Alpha", "Bravo", "Charlie"]);
  expect(text.attrs).toEqual({ style: "banded" });
  expect(text.content[3].content[0].attrs).toEqual({ background: "blue" });

  const numbers = sortOfficeTable(table, { column: 1, type: "number", direction: "descending" });
  expect(firstColumn(numbers)).toEqual(["Name", "Alpha", "Charlie", "Bravo"]);
});

test("Office table sorting supports strict ISO dates and keeps empty cells last", () => {
  const dates = sortOfficeTable(table, { column: 2, type: "date", direction: "ascending" });
  expect(firstColumn(dates)).toEqual(["Name", "Alpha", "Bravo", "Charlie"]);
  const withEmpty = { ...table, content: [...table.content, row(cell("tableCell", "Empty"), cell("tableCell", ""), cell("tableCell", ""))] };
  expect(firstColumn(sortOfficeTable(withEmpty, { column: 1, type: "number", direction: "descending" })).at(-1)).toBe("Empty");
});

test("Office table sorting rejects merged grids invalid values and unsupported options", () => {
  const merged = { type: "table", content: [row(cell("tableCell", "x", { colspan: 2, rowspan: 1 })),
    row(cell("tableCell", "a"), cell("tableCell", "b"))] };
  expect(() => officeTableSortInfo(merged)).toThrow();
  expect(() => sortOfficeTable(table, { column: 0, type: "number", direction: "ascending" })).toThrow();
  expect(() => sortOfficeTable(table, { column: 2, type: "date", direction: "sideways" })).toThrow();
  const badDate = structuredClone(table); badDate.content[1].content[2] = cell("tableCell", "2026-02-30");
  expect(() => sortOfficeTable(badDate, { column: 2, type: "date", direction: "ascending" })).toThrow();
});
