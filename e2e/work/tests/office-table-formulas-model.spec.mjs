import { expect, test } from "@playwright/test";

import { clearOfficeTableFormula, clearOfficeTableFormulas, fillOfficeTableFormulas, officeTableFromTSV, pasteOfficeTableCells, recalculateOfficeTableFormulas, remapOfficeTableFormulas, setOfficeTableFormula } from "../office-table-formulas.mjs";

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

test("Office formulas preserve absolute and mixed row and column anchors", () => {
  let table = officeTableFromTSV("2\t3\t0\n4\t6\t0");
  table = setOfficeTableFormula(table, { row: 1, column: 2, formula: "=SUM($A$1;$B1;A$2)" });
  expect(table.content[1].content[2].attrs).toMatchObject({
    formula: "=SUM($A$1,$B1,A$2)", formulaResult: "9",
  });
  for (const formula of ["=$$A1", "=A$$1", "=$A$", "=$1+A1"]) {
    expect(() => setOfficeTableFormula(table, { row: 1, column: 2, formula })).toThrow();
  }
});

test("Office formulas fill and clear a range with anchored reference axes", () => {
  let table = officeTableFromTSV("1\t2\t0\t0\n3\t4\t0\t0");
  table = fillOfficeTableFormulas(table, { top: 0, left: 2, bottom: 2, right: 4, formula: "=$A1+B$1" });
  expect(table.content.slice(0, 2).map((row) => row.content.slice(2).map((cell) => cell.attrs.formula))).toEqual([
    ["=$A1+B$1", "=$A1+C$1"], ["=$A2+B$1", "=$A2+C$1"],
  ]);
  expect(table.content.slice(0, 2).map((row) => row.content.slice(2).map(text))).toEqual([["3", "4"], ["5", "6"]]);
  table = clearOfficeTableFormulas(table, { top: 0, left: 2, bottom: 2, right: 4 });
  expect(table.content.slice(0, 2).map((row) => row.content.slice(2).map(text))).toEqual([["3", "4"], ["5", "6"]]);
  expect(table.content[1].content[3].attrs.formula).toBeUndefined();
});

test("Office formula ranges reject headers invalid bounds and shifted overflow", () => {
  const table = officeTableFromTSV("1\t2\n3\t4");
  table.content[0].content[0].type = "tableHeader";
  expect(() => fillOfficeTableFormulas(table,
    { top: 0, left: 0, bottom: 1, right: 2, formula: "=A1" })).toThrow();
  expect(() => clearOfficeTableFormulas(table, { top: 1, left: 0, bottom: 3, right: 1 })).toThrow();
  expect(() => fillOfficeTableFormulas(officeTableFromTSV("1\t2"),
    { top: 0, left: 0, bottom: 1, right: 2, formula: "=T1" })).toThrow();
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

test("Office table paste shifts only relative reference axes", () => {
  const target = officeTableFromTSV("10\t20\t30\t40\t50\n11\t21\t31\t41\t51\n12\t22\t32\t42\t52");
  const source = officeTableFromTSV("1\t2\t3\t=SUM($A$1,$B1,A$1,B1)");
  const pasted = pasteOfficeTableCells(target, source, { top: 1, left: 1, bottom: 2, right: 2 });
  expect(pasted.content[1].content[4].attrs).toMatchObject({
    formula: "=SUM($A$1,$B2,B$1,C2)", formulaResult: "33",
  });
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

test("Office structural formula mapping preserves logical cells and exposes deleted references", () => {
  const original = officeTableFromTSV("2\t3\t=SUM(A1:B1)\n4\t6\t=SUM(A2:B2)");
  const entry = (source, duplicate = false) => ({ source, duplicate });
  const inserted = structuredClone(original);
  inserted.content.splice(0, 0, { type: "tableRow", content: Array.from({ length: 3 }, () =>
    ({ type: "tableCell", content: [{ type: "paragraph" }] })) });
  const shifted = remapOfficeTableFormulas(original, inserted,
    { rows: [entry(0, true), entry(0), entry(1)], columns: [entry(0), entry(1), entry(2)] });
  expect(shifted.content[1].content[2].attrs).toMatchObject({ formula: "=SUM(A2:B2)", formulaResult: "5" });
  expect(shifted.content[2].content[2].attrs).toMatchObject({ formula: "=SUM(A3:B3)", formulaResult: "10" });

  const removed = { ...original, content: original.content.map((row) => ({ ...row, content: row.content.slice(1) })) };
  const broken = remapOfficeTableFormulas(original, removed,
    { rows: [entry(0), entry(1)], columns: [entry(1), entry(2)] });
  expect(broken.content[0].content[1].attrs).toMatchObject({ formula: "=SUM(#BEZUG!:A1)", formulaResult: "#BEZUG!" });
  expect(() => setOfficeTableFormula(original, { row: 0, column: 2, formula: "=#BROKEN!" })).toThrow();
});

test("Office structural formula mapping follows moves and gives duplicates relative references", () => {
  const original = officeTableFromTSV("2\t3\t=SUM(A1:B1)\n4\t6\t=SUM(A2:B2)");
  const entry = (source, duplicate = false) => ({ source, duplicate });
  const movedRows = { ...original, content: [original.content[1], original.content[0]] };
  const moved = remapOfficeTableFormulas(original, movedRows,
    { rows: [entry(1), entry(0)], columns: [entry(0), entry(1), entry(2)] });
  expect(moved.content[0].content[2].attrs.formula).toBe("=SUM(A1:B1)");
  expect(moved.content[1].content[2].attrs.formula).toBe("=SUM(A2:B2)");

  const duplicatedRows = { ...original, content: [original.content[0], structuredClone(original.content[0]), original.content[1]] };
  const duplicated = remapOfficeTableFormulas(original, duplicatedRows,
    { rows: [entry(0), entry(0, true), entry(1)], columns: [entry(0), entry(1), entry(2)] });
  expect(duplicated.content[0].content[2].attrs).toMatchObject({ formula: "=SUM(A1:B1)", formulaResult: "5" });
  expect(duplicated.content[1].content[2].attrs).toMatchObject({ formula: "=SUM(A2:B2)", formulaResult: "5" });
  expect(duplicated.content[2].content[2].attrs).toMatchObject({ formula: "=SUM(A3:B3)", formulaResult: "10" });
});

test("Office structural formula mapping follows anchored cells but copies only relative axes", () => {
  const original = officeTableFromTSV("2\t3\t=SUM($A$1,B1)\n4\t6\t=SUM($A2,B$2)");
  const entry = (source, duplicate = false) => ({ source, duplicate });
  const duplicatedRows = { ...original,
    content: [original.content[0], structuredClone(original.content[0]), original.content[1]] };
  const duplicated = remapOfficeTableFormulas(original, duplicatedRows,
    { rows: [entry(0), entry(0, true), entry(1)], columns: [entry(0), entry(1), entry(2)] });
  expect(duplicated.content[0].content[2].attrs.formula).toBe("=SUM($A$1,B1)");
  expect(duplicated.content[1].content[2].attrs).toMatchObject({ formula: "=SUM($A$1,B2)", formulaResult: "5" });
  expect(duplicated.content[2].content[2].attrs).toMatchObject({ formula: "=SUM($A3,B$3)", formulaResult: "10" });
});
