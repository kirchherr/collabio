import { expect, test } from "@playwright/test";

import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeChartAttributes, officeChartAxisScale, officeChartBindingMatches, officeChartDataFromDocument, officeChartDescription,
  validateOfficeChartBindings } from "../office-charts.mjs";
import { officeTableFromTSV, setOfficeTableFormula } from "../office-table-formulas.mjs";

const attrs = { id: "chart-" + "a".repeat(24), kind: "bar", title: "Quarterly plan",
  altText: "Plan and actual values rise across four quarters.", legend: true,
  categories: ["Q1", "Q2", "Q3", "Q4"], series: [
    { name: "Plan", color: "teal", values: [120, 140, 160, 180] },
    { name: "Actual", color: "blue", values: [110, 152, 171, 176] },
  ] };

test("Office charts admit bounded literal decimal datasets", () => {
  expect(officeChartAttributes(attrs)).toEqual(attrs);
  expect(officeChartAttributes({ ...attrs, kind: "pie", series: [{ name: "Share", color: "orange", values: [1, 2, 3, 4] }] }).kind).toBe("pie");
  for (const invalid of [{ ...attrs, kind: "script" }, { ...attrs, title: "" }, { ...attrs, onclick: "run()" },
    { ...attrs, categories: ["Q1", "Q1"] }, { ...attrs, series: [{ name: "Plan", color: "url", values: [1, 2, 3, 4] }] },
    { ...attrs, series: [{ name: "Plan", color: "teal", values: [-1, 2, 3, 4] }] }]) {
    expect(() => officeChartAttributes(invalid)).toThrow();
  }
  expect(officeChartAttributes({ ...attrs, kind: "line",
    series: [{ name: "Delta", color: "purple", values: [-1, 2, 3, 4] }] }).kind).toBe("line");
  expect(officeChartAttributes({ ...attrs, kind: "area",
    series: [{ name: "Delta", color: "purple", values: [-1, 2, 3, 4] }] }).kind).toBe("area");
  expect(officeChartAttributes({ ...attrs, kind: "doughnut",
    series: [{ name: "Share", color: "orange", values: [1, 2, 3, 4] }] }).kind).toBe("doughnut");
  expect(officeChartAttributes({ ...attrs,
    series: [{ name: "Plan", color: "teal", values: [1.5, 2.25, 3.75, 4.125] }] }).series[0].values[3]).toBe(4.125);
});

test("Office charts derive exact decimal snapshots from a numbered table and detect stale data", () => {
  let table = officeTableFromTSV("Quartal\tPlan\tIst\nQ1\t1.5\t2.25\nQ2\t3\t0");
  table.attrs = { tableId: "table-" + "b".repeat(24), caption: "Quartalswerte" };
  table = setOfficeTableFormula(table, { row: 2, column: 2, formula: "=ROUND(B3*1.25,2)" });
  const source = { tableId: table.attrs.tableId, range: "A1:C3" };
  const data = officeChartDataFromDocument({ type: "doc", content: [table] }, source, "bar");
  expect(data).toEqual({ categories: ["Q1", "Q2"], series: [
    { name: "Plan", color: "teal", values: [1.5, 3] },
    { name: "Ist", color: "blue", values: [2.25, 3.75] },
  ] });
  const linked = { ...attrs, categories: data.categories, series: data.series, source };
  const document = { type: "doc", content: [table, { type: "chart", attrs: linked }] };
  expect(officeChartBindingMatches(document, linked)).toBe(true);
  expect(validateOfficeChartBindings(document)).toBe(document);
  const stale = structuredClone(document); stale.content[1].attrs.series[0].values[0] = 99;
  expect(officeChartBindingMatches(stale, stale.content[1].attrs)).toBe(false);
  expect(() => validateOfficeChartBindings(stale)).toThrow();
  expect(officeChartDescription(linked)).toContain("verknüpft mit A1:C3");
});

test("Office linked charts can interpret rows as series and retain data-label presentation", () => {
  const table = officeTableFromTSV("Series\tQ1\tQ2\nPlan\t10\t20\nActual\t12\t18");
  table.attrs = { tableId: "table-" + "c".repeat(24), caption: "Quarterly rows" };
  const source = { tableId: table.attrs.tableId, range: "A1:C3", orientation: "rows" };
  const data = officeChartDataFromDocument({ type: "doc", content: [table] }, source, "line");
  expect(data).toEqual({ categories: ["Q1", "Q2"], series: [
    { name: "Plan", color: "teal", values: [10, 20] },
    { name: "Actual", color: "blue", values: [12, 18] },
  ] });
  expect(officeChartAttributes({ ...attrs, ...data, source, dataLabels: true })).toMatchObject({
    source, dataLabels: true,
  });
});

test("Office chart axes use deterministic automatic and bounded manual scales", () => {
  expect(officeChartAxisScale(attrs)).toMatchObject({ minimum: 0, maximum: 200, majorUnit: 50,
    ticks: [0, 50, 100, 150, 200], gridlines: true, numberFormat: "general" });
  const axes = { mode: "manual", categoryTitle: "Quartal", valueTitle: "Umsatz", minimum: 100, maximum: 200,
    majorUnit: 20, gridlines: true, numberFormat: "currency-eur" };
  const presented = officeChartAttributes({ ...attrs, legendPosition: "right", dataLabels: true, axes });
  expect(presented).toMatchObject({ legendPosition: "right", dataLabels: true, axes });
  expect(officeChartAxisScale(presented)).toMatchObject({ minimum: 100, maximum: 200, majorUnit: 20,
    ticks: [100, 120, 140, 160, 180, 200] });
  for (const invalid of [
    { ...attrs, legendPosition: "floating" },
    { ...attrs, axes: { ...axes, maximum: 160 } },
    { ...attrs, axes: { ...axes, majorUnit: 30 } },
    { ...attrs, kind: "pie", series: [{ name: "Share", color: "orange", values: [1, 2, 3, 4] }], axes },
  ]) expect(() => officeChartAttributes(invalid)).toThrow();
  expect(officeChartDescription(presented)).toContain("Achsen Quartal / Umsatz");
});

test("Office richer chart types retain bounded presentation and stacked totals", () => {
  const presentation = { palette: "accessible", style: "soft", titleAlignment: "left" };
  const stacked = officeChartAttributes({ ...attrs, kind: "stacked-bar", presentation,
    axes: { mode: "manual", categoryTitle: "Quartal", valueTitle: "Gesamt", minimum: 0, maximum: 400,
      majorUnit: 100, gridlines: true, numberFormat: "integer" } });
  expect(stacked.presentation).toEqual(presentation);
  expect(officeChartAxisScale(stacked)).toMatchObject({ minimum: 0, maximum: 400, majorUnit: 100 });
  expect(officeChartDescription(stacked)).toContain("Gestapeltes Säulendiagramm");
  for (const invalid of [
    { ...stacked, presentation: { ...presentation, palette: "script" } },
    { ...stacked, axes: { ...stacked.axes, maximum: 300, majorUnit: 50 } },
    { ...stacked, axes: { ...stacked.axes, minimum: 100, maximum: 400 } },
  ]) expect(() => officeChartAttributes(invalid)).toThrow();
});

test("Office chart descriptions and comparisons expose exact data changes", () => {
  expect(officeChartDescription(attrs)).toContain("Säulendiagramm · Quarterly plan · 4 Kategorien · 2 Datenreihen");
  const before = { type: "doc", content: [{ type: "chart", attrs }] };
  const after = { type: "doc", content: [{ type: "chart", attrs: { ...attrs, kind: "line",
    series: [attrs.series[0], { ...attrs.series[1], values: [110, 152, 171, 190] }] } }] };
  expect(describeOfficeBlock(before.content[0]).label).toContain("Säulendiagramm");
  expect(compareOfficeDocuments(before, after).counts.changed).toBe(1);
});
