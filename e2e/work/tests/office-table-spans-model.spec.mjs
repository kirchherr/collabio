import { expect, test } from "@playwright/test";

import { compareOfficeDocuments } from "../office-comparison.mjs";
import { officeTableCellAttributes, officeTableGrid } from "../office-tables.mjs";

const paragraph = (text = "") => ({ type: "paragraph", content: text ? [{ type: "text", text }] : undefined });
const cell = (type, text, attrs = {}) => ({ type, attrs, content: [paragraph(text)] });
const merged = { type: "table", content: [
  { type: "tableRow", content: [cell("tableHeader", "Summary", { colspan: 3, rowspan: 1 })] },
  { type: "tableRow", content: [cell("tableHeader", "Q1", { colspan: 1, rowspan: 2 }),
    cell("tableCell", "Plan"), cell("tableCell", "Actual")] },
  { type: "tableRow", content: [cell("tableCell", "120"), cell("tableCell", "110")] },
] };

test("Office table grids accept bounded rectangular row and column spans", () => {
  expect(officeTableGrid(merged)).toEqual({ rows: 3, columns: 3 });
  expect(officeTableCellAttributes({ colspan: 3, rowspan: 2, colwidth: null })).toEqual({ colspan: 3, rowspan: 2 });
  for (const invalid of [
    { ...merged, content: merged.content.slice(0, 2) },
    { ...merged, content: [merged.content[0], merged.content[1], { type: "tableRow", content: [] }] },
    { type: "table", content: [{ type: "tableRow", content: [cell("tableCell", "x", { colspan: 21, rowspan: 1 })] }] },
  ]) expect(() => officeTableGrid(invalid)).toThrow();
});

test("Office comparison exposes merged-cell geometry", () => {
  const before = { type: "doc", content: [{ type: "table", content: [
    { type: "tableRow", content: [cell("tableHeader", "Summary"), cell("tableHeader", ""), cell("tableHeader", "")] },
  ] }] };
  const after = { type: "doc", content: [merged] };
  const comparison = compareOfficeDocuments(before, after);
  expect(comparison.counts.changed).toBe(1);
  expect(comparison.blocks.find((block) => block.status === "changed").after).toContain("3 Spalten × 1 Zeilen");
});
