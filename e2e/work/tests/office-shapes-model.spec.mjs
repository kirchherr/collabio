import { test, expect } from "@playwright/test";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeShapeAttributes, officeShapeDescription, officeShapePosition, officeShapeWrap, OFFICE_SHAPE_LIMIT } from "../office-shapes.mjs";
import { officeShapeGroupAttributes, OFFICE_SHAPE_GROUP_LIMIT, OFFICE_SHAPE_GROUP_MEMBER_LIMIT } from "../office-shape-groups.mjs";

const attrs = { id: "shape-" + "a".repeat(24), kind: "roundedRectangle", width: 320, height: 160,
  fill: "teal", stroke: "slate", strokeWidth: 2, text: "Literal <script> text 😀", textAlign: "center" };

test("Office shapes preserve only bounded inert attributes", () => {
  expect(officeShapeAttributes(attrs)).toEqual(attrs);
  expect(officeShapeAttributes({ ...attrs, rotation: null })).toEqual(attrs);
  expect(officeShapeDescription(attrs)).toContain("Abgerundetes Rechteck · 320 × 160 px");
  expect(officeShapeAttributes({ ...attrs, rotation: 270 })).toEqual({ ...attrs, rotation: 270 });
  expect(officeShapeDescription({ ...attrs, rotation: 90 })).toContain("90° gedreht");
  expect(OFFICE_SHAPE_LIMIT).toBe(100);
  for (const invalid of [{ ...attrs, id: "shape-short" }, { ...attrs, kind: "svg" }, { ...attrs, width: 79 },
    { ...attrs, height: 801 }, { ...attrs, fill: "url(external)" }, { ...attrs, strokeWidth: true },
    { ...attrs, text: "bad\u0000text" }, { ...attrs, textAlign: "justify" }, { ...attrs, rotation: 0 },
    { ...attrs, rotation: 45 }, { ...attrs, rotation: true }, { ...attrs, onclick: "run()" }]) {
    expect(() => officeShapeAttributes(invalid)).toThrow();
  }
});

test("Office shape wrapping is bounded and mutually exclusive with positioning", () => {
  for (const wrap of [{ side: "left", gap: 0 }, { side: "right", gap: 48 }]) {
    expect(officeShapeWrap(wrap)).toEqual(wrap); expect(officeShapeAttributes({ ...attrs, wrap })).toEqual({ ...attrs, wrap });
  }
  expect(officeShapeDescription({ ...attrs, wrap: { side: "right", gap: 24 } })).toContain("Textumfluss Form rechts · Abstand 24 px");
  for (const wrap of [{}, [], "left", { side: "middle", gap: 0 }, { side: "left", gap: -1 },
    { side: "right", gap: 49 }, { side: "left", gap: true }, { side: "left", gap: 0, style: "float" }]) {
    expect(() => officeShapeAttributes({ ...attrs, wrap })).toThrow();
  }
  expect(() => officeShapeAttributes({ ...attrs, wrap: { side: "left", gap: 16 },
    position: { layer: "front", x: 0, y: 0 } })).toThrow();
});

test("Office shape positions are bounded inert and visible in comparisons", () => {
  for (const position of [{ layer: "front", x: 0, y: -1200 }, { layer: "behind", x: 1000, y: 1200 }]) {
    expect(officeShapePosition(position)).toEqual(position);
    expect(officeShapeAttributes({ ...attrs, position })).toEqual({ ...attrs, position });
  }
  expect(officeShapeDescription({ ...attrs, position: { layer: "behind", x: 500, y: 24 } })).toContain("hinter Text · X 500 · Y 24 px");
  for (const position of [{}, [], "front", { layer: "middle", x: 0, y: 0 }, { layer: "front", x: -1, y: 0 },
    { layer: "behind", x: 1001, y: 0 }, { layer: "front", x: true, y: 0 }, { layer: "front", x: 0, y: -1201 },
    { layer: "behind", x: 0, y: 1201 }, { layer: "front", x: 0, y: 0, style: "fixed" }]) {
    expect(() => officeShapeAttributes({ ...attrs, position })).toThrow();
  }
});

test("Office shape groups admit only bounded inert layout attributes", () => {
  const group = { id: "shape-group-" + "b".repeat(24), layout: "row", gap: 16 };
  expect(officeShapeGroupAttributes(group)).toEqual(group);
  expect(officeShapeGroupAttributes({ ...group, layout: "stack", gap: 48 })).toEqual({ ...group, layout: "stack", gap: 48 });
  expect(OFFICE_SHAPE_GROUP_LIMIT).toBe(20); expect(OFFICE_SHAPE_GROUP_MEMBER_LIMIT).toBe(8);
  for (const invalid of [{ ...group, id: "short" }, { ...group, layout: "grid" }, { ...group, gap: -1 },
    { ...group, gap: 49 }, { ...group, gap: true }, { ...group, style: "display:flex" }]) {
    expect(() => officeShapeGroupAttributes(invalid)).toThrow();
  }
  const block = { type: "shapeGroup", attrs: group, content: [{ type: "shape", attrs },
    { type: "shape", attrs: { ...attrs, id: "shape-" + "c".repeat(24), kind: "ellipse" } }] };
  expect(describeOfficeBlock(block).label).toContain("Formgruppe · 2 Formen · nebeneinander · Abstand 16 px");
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
