import { test, expect } from "@playwright/test";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeShapeAttributes, officeShapeDescription, OFFICE_SHAPE_LIMIT } from "../office-shapes.mjs";

const attrs = { id: "shape-" + "a".repeat(24), kind: "roundedRectangle", width: 320, height: 160,
  fill: "teal", stroke: "slate", strokeWidth: 2, text: "Literal <script> text 😀", textAlign: "center" };

test("Office shapes preserve only bounded inert attributes", () => {
  expect(officeShapeAttributes(attrs)).toEqual(attrs);
  expect(officeShapeDescription(attrs)).toContain("Abgerundetes Rechteck · 320 × 160 px");
  expect(OFFICE_SHAPE_LIMIT).toBe(100);
  for (const invalid of [{ ...attrs, id: "shape-short" }, { ...attrs, kind: "svg" }, { ...attrs, width: 79 },
    { ...attrs, height: 801 }, { ...attrs, fill: "url(external)" }, { ...attrs, strokeWidth: true },
    { ...attrs, text: "bad\u0000text" }, { ...attrs, textAlign: "justify" }, { ...attrs, onclick: "run()" }]) {
    expect(() => officeShapeAttributes(invalid)).toThrow();
  }
});

test("Office comparison exposes shape presentation and literal text changes", () => {
  const before = { type: "doc", content: [{ type: "shape", attrs }, { type: "paragraph" }] };
  const afterShape = { type: "shape", attrs: { ...attrs, kind: "ellipse", fill: "blue", text: "Changed" } };
  const after = { ...before, content: [afterShape, before.content[1]] };
  expect(describeOfficeBlock(before.content[0])).toMatchObject({ label: expect.stringContaining("Abgerundetes Rechteck") });
  expect(describeOfficeBlock(afterShape).text).toContain("Ellipse");
  const comparison = compareOfficeDocuments(before, after);
  expect(comparison.counts.changed).toBe(1);
  expect(comparison.rows.some((row) => row.before === before.content[1] || row.after === before.content[1])).toBe(true);
});
