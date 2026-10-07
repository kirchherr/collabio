import { expect, test } from "@playwright/test";

import { clearOfficeTableFormula, officeTableFromTSV, pasteOfficeTableCells, recalculateOfficeTableFormulas, setOfficeTableFormula } from "../office-table-formulas.mjs";

const text = (cell) => cell.content[0].content?.[0]?.text || "";

test("Office TSV import preserves quoted cells and evaluates local arithmetic and ranges", () => {
  let table = officeTableFromTSV('Item\tQ1\tQ2\tTotal\n"Alpha\tteam"\t2\t3\t=SUM(B2:C2)\nBravo\t4\t6\t=B3+C3');
  expect(table.content.map((row) => row.content.map(text))).toEqual([
    ["Item", "Q1", "Q2", "Total"], ["Alpha\tteam", "2", "3", "5"], ["Bravo", "4", "6", "10"],
  ]);
  expect(table.content[1].content[3].attrs).toMatchObject({ formula: "=SUM(B2:C2)", formulaResult: "5" });
  table.content[1].content[1].content[0].content[0].text = "7";
  table = recalculateOfficeTableFormulas(table);
  expect(text(table.content[1].content[3])).toBe("10");
});

test("Office formulas normalize German input support functions and remain removable", () => {
  let table = officeTableFromTSV("2\t4\n6\t8");
  table = setOfficeTableFormula(table, { row: 1, column: 1, formula: "=MITTELWERT(A1;B1;A2)" });
  expect(table.content[1].content[1].attrs).toMatchObject({ formula: "=AVERAGE(A1,B1,A2)", formulaResult: "4" });
  table = clearOfficeTableFormula(table, { row: 1, column: 1 });
  expect(table.content[1].content[1].attrs.formula).toBeUndefined();
  expect(text(table.content[1].content[1])).toBe("4");
});

test("Office formulas expose deterministic reference division cycle and syntax errors", () => {
  let table = officeTableFromTSV("1\t=T200\n0\t=A1/A2");
  expect(text(table.content[0].content[1])).toBe("#BEZUG!");
  expect(text(table.content[1].content[1])).toBe("#DIV/0!");
  table = officeTableFromTSV("=B1\t=A1");
  expect(table.content[0].content.map(text)).toEqual(["#ZYKLUS!", "#ZYKLUS!"]);
  expect(() => setOfficeTableFormula(officeTableFromTSV("1\t2"), { row: 0, column: 1, formula: "=FOO(A1)" })).toThrow();
  expect(() => setOfficeTableFormula(officeTableFromTSV("1\t2"), { row: 0, column: 1, formula: "=U1" })).toThrow();
  expect(() => setOfficeTableFormula(officeTableFromTSV("1\t2"), { row: 0, column: 1,
    formula: "='[external.xlsx]Sheet1'!A1" })).toThrow();
});

test("Office table paste expands from one cell and shifts relative formulas", () => {
  const target = officeTableFromTSV("Name\tQ1\tQ2\tTotal\nExisting\t1\t1\t2");
  const source = officeTableFromTSV("Alpha\t2\t3\t=SUM(B1:C1)\nBravo\t4\t6\t=SUM(B2:C2)");
  const pasted = pasteOfficeTableCells(target, source, { top: 1, left: 0, bottom: 2, right: 1 });
  expect(pasted.content.map((row) => row.content.map(text))).toEqual([
    ["Name", "Q1", "Q2", "Total"], ["Alpha", "2", "3", "5"], ["Bravo", "4", "6", "10"],
  ]);
  expect(pasted.content[1].content[3].attrs.formula).toBe("=SUM(B2:C2)");
  expect(pasted.content[2].content[3].attrs.formula).toBe("=SUM(B3:C3)");
});

test("Office table paste fills an exact selection and rejects ambiguous dimensions", () => {
  const target = officeTableFromTSV("A\tB\nC\tD"); const source = officeTableFromTSV("7\t8");
  const pasted = pasteOfficeTableCells(target, source, { top: 1, left: 0, bottom: 2, right: 2 });
  expect(pasted.content.map((row) => row.content.map(text))).toEqual([["A", "B"], ["7", "8"]]);
  expect(() => pasteOfficeTableCells(target, source, { top: 0, left: 0, bottom: 2, right: 2 })).toThrow();
  const single = { type: "table", content: [{ type: "tableRow", content: [
    { type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "9" }] }] },
  ] }] };
  const repeated = pasteOfficeTableCells(target, single, { top: 0, left: 0, bottom: 2, right: 2 });
  expect(repeated.content.map((row) => row.content.map(text))).toEqual([["9", "9"], ["9", "9"]]);
});
