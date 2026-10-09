import { expect, test } from "@playwright/test";

import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeChartAttributes, officeChartDescription } from "../office-charts.mjs";

const attrs = { id: "chart-" + "a".repeat(24), kind: "bar", title: "Quarterly plan",
  altText: "Plan and actual values rise across four quarters.", legend: true,
  categories: ["Q1", "Q2", "Q3", "Q4"], series: [
    { name: "Plan", color: "teal", values: [120, 140, 160, 180] },
    { name: "Actual", color: "blue", values: [110, 152, 171, 176] },
  ] };

test("Office charts admit only bounded inert literal datasets", () => {
  expect(officeChartAttributes(attrs)).toEqual(attrs);
  expect(officeChartAttributes({ ...attrs, kind: "pie", series: [{ name: "Share", color: "orange", values: [1, 2, 3, 4] }] }).kind).toBe("pie");
  for (const invalid of [{ ...attrs, kind: "script" }, { ...attrs, title: "" }, { ...attrs, onclick: "run()" },
    { ...attrs, categories: ["Q1", "Q1"] }, { ...attrs, series: [{ name: "Plan", color: "url", values: [1, 2, 3, 4] }] },
    { ...attrs, series: [{ name: "Plan", color: "teal", values: [1.5, 2, 3, 4] }] },
    { ...attrs, series: [{ name: "Plan", color: "teal", values: [-1, 2, 3, 4] }] }]) {
    expect(() => officeChartAttributes(invalid)).toThrow();
  }
  expect(officeChartAttributes({ ...attrs, kind: "line",
    series: [{ name: "Delta", color: "purple", values: [-1, 2, 3, 4] }] }).kind).toBe("line");
});

test("Office chart descriptions and comparisons expose exact data changes", () => {
  expect(officeChartDescription(attrs)).toContain("Säulendiagramm · Quarterly plan · 4 Kategorien · 2 Datenreihen");
  const before = { type: "doc", content: [{ type: "chart", attrs }] };
  const after = { type: "doc", content: [{ type: "chart", attrs: { ...attrs, kind: "line",
    series: [attrs.series[0], { ...attrs.series[1], values: [110, 152, 171, 190] }] } }] };
  expect(describeOfficeBlock(before.content[0]).label).toContain("Säulendiagramm");
  expect(compareOfficeDocuments(before, after).counts.changed).toBe(1);
});
