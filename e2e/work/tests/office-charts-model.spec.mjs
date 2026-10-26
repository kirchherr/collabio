import { expect, test } from "@playwright/test";

import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeChartAttributes, officeChartAxisScale, officeChartBindingMatches, officeChartDataFromDocument, officeChartDescription,
  officeChartSecondaryAxisScale, validateOfficeChartBindings } from "../office-charts.mjs";
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

test("Office scatter and combo charts retain strict per-series presentation", () => {
  const scatter = officeChartAttributes({ ...attrs, kind: "scatter",
    seriesPresentation: [{ renderAs: "points", marker: "diamond", lineStyle: "dashed" }] });
  expect(scatter.seriesPresentation[0]).toEqual({ renderAs: "points", marker: "diamond", lineStyle: "dashed" });
  expect(officeChartAxisScale(scatter)).toMatchObject({ minimum: 0, maximum: 200 });
  expect(officeChartDescription(scatter)).toContain("Streudiagramm");
  const combo = officeChartAttributes({ ...attrs, kind: "combo", seriesPresentation: [
    { renderAs: "bar", marker: "none", lineStyle: "none" },
    { renderAs: "line", marker: "square", lineStyle: "dashed" },
  ] });
  expect(combo.seriesPresentation.map((entry) => entry.renderAs)).toEqual(["bar", "line"]);
  expect(officeChartDescription(combo)).toContain("Kombinationsdiagramm");
  for (const invalid of [
    { ...scatter, seriesPresentation: [] },
    { ...scatter, seriesPresentation: [{ renderAs: "points", marker: "none", lineStyle: "none" }] },
    { ...combo, seriesPresentation: combo.seriesPresentation.map(() => ({ renderAs: "bar", marker: "none", lineStyle: "none" })) },
    { ...combo, seriesPresentation: [{ renderAs: "bar", marker: "circle", lineStyle: "none" }, combo.seriesPresentation[1]] },
  ]) expect(() => officeChartAttributes(invalid)).toThrow();
});

test("Office reference lines and data labels remain bounded and scale-aware", () => {
  const referenceLines = [
    { label: "Target", value: 190, color: "orange", lineStyle: "dashed" },
    { label: "Floor", value: 100, color: "purple", lineStyle: "solid" },
  ];
  const labelled = officeChartAttributes({ ...attrs, dataLabels: true,
    dataLabelPresentation: { content: "series-value", position: "top" }, referenceLines });
  expect(labelled.referenceLines).toEqual(referenceLines);
  expect(officeChartAxisScale(labelled).maximum).toBeGreaterThanOrEqual(190);
  expect(officeChartDescription(labelled)).toContain("Referenzlinien Target: 190, Floor: 100");
  for (const invalid of [
    { ...labelled, dataLabels: false },
    { ...labelled, referenceLines: [...referenceLines, { ...referenceLines[0] }] },
    { ...labelled, referenceLines: [{ ...referenceLines[0], value: Infinity }] },
    { ...labelled, kind: "pie", series: [labelled.series[0]] },
    { ...labelled, axes: { mode: "manual", categoryTitle: "", valueTitle: "", minimum: 0, maximum: 180,
      majorUnit: 20, gridlines: true, numberFormat: "general" } },
  ]) expect(() => officeChartAttributes(invalid)).toThrow();
});

test("Office trendlines and fixed error bars are deterministic, bounded, and scale-aware", () => {
  const analysis = { trendline: { seriesIndex: 1, color: "orange", lineStyle: "dashed" },
    errorBars: { seriesIndex: 1, amount: 15, color: "purple" } };
  const chart = officeChartAttributes({ ...attrs, kind: "line", analysis });
  expect(chart.analysis).toEqual(analysis);
  expect(officeChartAxisScale(chart)).toMatchObject({ minimum: 0, maximum: 200 });
  expect(officeChartDescription(chart)).toContain("Trendlinie Actual · Fehlerbalken Actual: ±15");
  expect(officeChartAttributes({ ...chart, axes: { mode: "manual", categoryTitle: "", valueTitle: "",
    minimum: 80, maximum: 200, majorUnit: 20, gridlines: true, numberFormat: "general" } }).analysis).toEqual(analysis);
  const combo = { ...attrs, kind: "combo", seriesPresentation: [
    { renderAs: "bar", marker: "none", lineStyle: "none" },
    { renderAs: "line", marker: "circle", lineStyle: "solid" },
  ] };
  const scatter = { ...attrs, kind: "scatter",
    seriesPresentation: [{ renderAs: "points", marker: "circle", lineStyle: "none" }] };
  for (const invalid of [
    { ...chart, analysis: { trendline: null, errorBars: null } },
    { ...chart, analysis: { ...analysis, errorBars: { ...analysis.errorBars, amount: 0 } } },
    { ...chart, analysis: { ...analysis, trendline: { ...analysis.trendline, seriesIndex: 7 } } },
    { ...chart, axes: { mode: "manual", categoryTitle: "", valueTitle: "", minimum: 100, maximum: 200,
      majorUnit: 20, gridlines: true, numberFormat: "general" } },
    { ...combo, analysis: { trendline: { ...analysis.trendline, seriesIndex: 0 }, errorBars: null } },
    { ...scatter, analysis: { trendline: { ...analysis.trendline, seriesIndex: 0 }, errorBars: null } },
    { ...attrs, kind: "pie", series: [attrs.series[0]], analysis },
  ]) expect(() => officeChartAttributes(invalid)).toThrow();
});

test("Office logarithmic and secondary axes remain explicit, bounded, and series-aware", () => {
  const secondary = { seriesIndex: 1, title: "Actual scale", scale: "linear", mode: "auto",
    minimum: null, maximum: null, majorUnit: null, numberFormat: "decimal" };
  const chart = officeChartAttributes({ ...attrs, kind: "line",
    axisOptions: { primaryScale: "logarithmic", secondary } });
  expect(officeChartAxisScale(chart)).toMatchObject({ minimum: 100, maximum: 1000, majorUnit: 10,
    scaleType: "logarithmic", ticks: [100, 1000] });
  expect(officeChartSecondaryAxisScale(chart)).toMatchObject({ minimum: 0, maximum: 200, majorUnit: 50,
    scaleType: "linear", valueTitle: "Actual scale" });
  expect(officeChartDescription(chart)).toContain("logarithmische Hauptachse · Sekundärachse Actual scale: Actual");
  const manual = { ...chart, axes: { mode: "manual", categoryTitle: "", valueTitle: "Plan scale",
    minimum: 100, maximum: 1000, majorUnit: 10, gridlines: true, numberFormat: "integer" },
  axisOptions: { ...chart.axisOptions, secondary: { ...secondary, mode: "manual", minimum: 100, maximum: 200,
    majorUnit: 20 } } };
  expect(officeChartSecondaryAxisScale(officeChartAttributes(manual)).ticks).toEqual([100, 120, 140, 160, 180, 200]);
  for (const invalid of [
    { ...attrs, axisOptions: { primaryScale: "logarithmic", secondary: null } },
    { ...attrs, kind: "line", series: [{ name: "Delta", color: "teal", values: [-1, 2, 3, 4] }],
      axisOptions: { primaryScale: "logarithmic", secondary: null } },
    { ...attrs, kind: "line", axisOptions: { primaryScale: "linear", secondary: { ...secondary, seriesIndex: 7 } } },
    { ...attrs, kind: "line", series: [attrs.series[0], { ...attrs.series[1], values: [0, 152, 171, 176] }],
      axisOptions: { primaryScale: "linear", secondary: { ...secondary, scale: "logarithmic" } } },
    { ...attrs, kind: "pie", series: [attrs.series[0]], axisOptions: { primaryScale: "linear", secondary: null } },
    { ...manual, axes: { ...manual.axes, majorUnit: 5 } },
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
