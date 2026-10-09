import { test, expect } from "@playwright/test";
import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeShapeAttributes, officeShapeBounds, officeShapeDescription, officeShapePosition, officeShapeWrap, OFFICE_SHAPE_LIMIT } from "../office-shapes.mjs";
import { officeShapeGroupAttributes, officeShapeGroupBounds, officeShapeGroupConnection, officeShapeGroupConnections, officeShapeGroupDescription, officeShapeGroupInsertMember, officeShapeGroupLayout, officeShapeGroupRemoveMember, OFFICE_SHAPE_GROUP_LIMIT, OFFICE_SHAPE_GROUP_MEMBER_LIMIT } from "../office-shape-groups.mjs";
import { officeShapeMultiAlignment, officeShapeMultiCanArrange, officeShapeMultiCanGroup, officeShapeMultiDistribution,
  officeShapeMultiLayer, officeShapeMultiNudge, officeShapeMultiRange, officeShapeMultiSelection,
  officeShapeMultiTranslate, OFFICE_SHAPE_MULTI_SELECTION_LIMIT } from "../office-shape-multi-selection.mjs";

const attrs = { id: "shape-" + "a".repeat(24), kind: "roundedRectangle", width: 320, height: 160,
  fill: "teal", stroke: "slate", strokeWidth: 2, text: "Literal <script> text 😀", textAlign: "center" };

test("Office shapes preserve only bounded inert attributes", () => {
  expect(officeShapeAttributes(attrs)).toEqual(attrs);
  expect(officeShapeAttributes({ ...attrs, rotation: null })).toEqual(attrs);
  expect(officeShapeDescription(attrs)).toContain("Abgerundetes Rechteck · 320 × 160 px");
  expect(officeShapeAttributes({ ...attrs, rotation: 37 })).toEqual({ ...attrs, rotation: 37 });
  expect(officeShapeAttributes({ ...attrs, rotation: 359 })).toEqual({ ...attrs, rotation: 359 });
  expect(officeShapeDescription({ ...attrs, rotation: 37 })).toContain("37° gedreht");
  expect(officeShapeBounds({ ...attrs, rotation: 90 })).toEqual({ width: 160, height: 320 });
  expect(officeShapeBounds({ ...attrs, rotation: 45 })).toEqual({ width: 340, height: 340 });
  const formatted = { ...attrs, fontSize: 28, textColor: "purple", textStyle: "boldItalic" };
  expect(officeShapeAttributes(formatted)).toEqual(formatted);
  expect(officeShapeDescription(formatted)).toContain("Schrift 28 px · Textfarbe violett · fett und kursiv");
  expect(OFFICE_SHAPE_LIMIT).toBe(100);
  for (const invalid of [{ ...attrs, id: "shape-short" }, { ...attrs, kind: "svg" }, { ...attrs, width: 79 },
    { ...attrs, height: 801 }, { ...attrs, fill: "url(external)" }, { ...attrs, strokeWidth: true },
    { ...attrs, text: "bad\u0000text" }, { ...attrs, textAlign: "justify" }, { ...attrs, rotation: 0 },
    { ...attrs, rotation: -1 }, { ...attrs, rotation: 360 }, { ...attrs, rotation: 90.5 },
    { ...attrs, rotation: true }, { ...attrs, fontSize: 9 }, { ...attrs, fontSize: 16 },
    { ...attrs, fontSize: 73 }, { ...attrs, fontSize: true }, { ...attrs, textColor: "transparent" },
    { ...attrs, textColor: "url(external)" }, { ...attrs, textStyle: "normal" },
    { ...attrs, textStyle: "bold;position:fixed" }, { ...attrs, onclick: "run()" }]) {
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

test("Office shape groups align members and distribute bounded gaps", () => {
  const group = { id: "shape-group-" + "b".repeat(24), layout: "stack", gap: 16,
    alignment: "center", distributionExtent: 600 };
  expect(officeShapeGroupAttributes(group)).toEqual(group);
  const second = { ...attrs, id: "shape-" + "c".repeat(24), width: 160, height: 80 };
  expect(officeShapeGroupLayout(group, [attrs, second])).toEqual({ width: 320, height: 600, gap: 360 });
  expect(officeShapeGroupBounds(group, [attrs, second])).toEqual({ width: 320, height: 600 });
  expect(officeShapeGroupDescription(group, 2)).toContain("Ausrichtung Mitte · gleichmäßig auf 600 px verteilt");
  expect(officeShapeGroupAttributes({ ...group, alignment: "end", distributionExtent: 2400 })).toEqual({
    ...group, alignment: "end", distributionExtent: 2400,
  });
  for (const invalid of [{ ...group, alignment: "start" }, { ...group, alignment: "stretch" },
    { ...group, distributionExtent: 159 }, { ...group, distributionExtent: 2401 },
    { ...group, distributionExtent: true }, { ...group, distributionExtent: 600.5 }]) {
    expect(() => officeShapeGroupAttributes(invalid)).toThrow();
  }
});

test("Office shape groups preserve bounded positions and rotated member bounds", () => {
  const group = { id: "shape-group-" + "b".repeat(24), layout: "row", gap: 16,
    position: { layer: "behind", x: 500, y: 24 } };
  expect(officeShapeGroupAttributes(group)).toEqual(group);
  const rotated = { ...attrs, id: "shape-" + "c".repeat(24), rotation: 90 };
  expect(officeShapeGroupBounds(group, [attrs, rotated])).toEqual({ width: 496, height: 320 });
  expect(officeShapeGroupBounds({ ...group, layout: "stack" }, [attrs, rotated])).toEqual({ width: 320, height: 496 });
  const block = { type: "shapeGroup", attrs: group,
    content: [{ type: "shape", attrs }, { type: "shape", attrs: rotated }] };
  expect(describeOfficeBlock(block).label).toContain("hinter Text · X 500 · Y 24 px");
  for (const position of [{}, [], "front", { layer: "middle", x: 0, y: 0 },
    { layer: "front", x: -1, y: 0 }, { layer: "behind", x: 1001, y: 0 },
    { layer: "front", x: true, y: 0 }, { layer: "front", x: 0, y: -1201 },
    { layer: "behind", x: 0, y: 1201 }, { layer: "front", x: 0, y: 0, style: "fixed" }]) {
    expect(() => officeShapeGroupAttributes({ ...group, position })).toThrow();
  }
  expect(() => officeShapeGroupBounds(group, [attrs])).toThrow();
});

test("Office shape group connections are bounded inert and visible in comparisons", () => {
  const connection = { kind: "doubleArrow", color: "purple", width: 8 };
  expect(officeShapeGroupConnection(connection)).toEqual(connection);
  const group = { id: "shape-group-" + "b".repeat(24), layout: "stack", gap: 24, connection };
  expect(officeShapeGroupAttributes(group)).toEqual(group);
  for (const invalid of [{ kind: "curve", color: "blue", width: 2 }, { kind: "arrow", color: "url", width: 2 },
    { kind: "line", color: "black", width: 0 }, { kind: "line", color: "black", width: 9 },
    { kind: "line", color: "black", width: true }, { kind: "line", color: "black", width: 2, path: "M0 0" }]) {
    expect(() => officeShapeGroupConnection(invalid)).toThrow();
  }
  const block = { type: "shapeGroup", attrs: group, content: [{ type: "shape", attrs },
    { type: "shape", attrs: { ...attrs, id: "shape-" + "c".repeat(24) } }] };
  expect(describeOfficeBlock(block).label).toContain("Verbindung doubleArrow, purple, 8 px");
});

test("Office shape group connections can be controlled per bounded edge", () => {
  const group = { id: "shape-group-" + "b".repeat(24), layout: "row", gap: 24,
    connections: [{ kind: "arrow", color: "red", width: 3 }, null, { kind: "line", color: "blue", width: 5 }] };
  expect(officeShapeGroupConnections(group, 4)).toEqual(group.connections);
  expect(officeShapeGroupAttributes(group)).toEqual(group);
  expect(officeShapeGroupInsertMember(group, 4, 2).connections).toEqual([
    group.connections[0], null, null, group.connections[2],
  ]);
  expect(officeShapeGroupRemoveMember(group, 4, 2).connections).toEqual([group.connections[0], group.connections[2]]);
  const block = { type: "shapeGroup", attrs: group, content: Array.from({ length: 4 }, (_, index) => ({
    type: "shape", attrs: { ...attrs, id: `shape-${String(index + 1).repeat(24)}` },
  })) };
  expect(describeOfficeBlock(block).label).toContain("2 individuelle Verbindungen");
  expect(() => officeShapeGroupConnections(group, 3)).toThrow();
  expect(() => officeShapeGroupAttributes({ ...group, connection: group.connections[0] })).toThrow();
  for (const connections of [[], Array(8).fill(null), [false], [{ kind: "curve", color: "red", width: 2 }],
    [{ kind: "line", color: "red", width: 2, path: "M0 0" }]]) {
    expect(() => officeShapeGroupAttributes({ ...group, connections })).toThrow();
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

test("Office shape multi-selection is bounded ordered and groups only adjacent flow shapes", () => {
  const nodes = [
    { id: "shape-" + "1".repeat(24), type: "shape", rootIndex: 1, node: { attrs: { position: null, wrap: null } } },
    { id: "shape-group-" + "2".repeat(24), type: "shapeGroup", rootIndex: 2, node: { attrs: {} } },
    { id: "shape-" + "3".repeat(24), type: "shape", rootIndex: 4, node: { attrs: { position: null, wrap: null } } },
  ];
  expect(OFFICE_SHAPE_MULTI_SELECTION_LIMIT).toBe(20);
  expect(officeShapeMultiSelection(nodes, [nodes[2].id, nodes[0].id])).toEqual([nodes[0], nodes[2]]);
  expect(officeShapeMultiRange(nodes, nodes[0].id, nodes[2].id)).toEqual(nodes.map((entry) => entry.id));
  expect(officeShapeMultiCanGroup([nodes[0], { ...nodes[2], rootIndex: 2 }])).toBe(true);
  expect(officeShapeMultiCanGroup([nodes[0], nodes[2]])).toBe(false);
  expect(officeShapeMultiCanGroup([nodes[0], nodes[1]])).toBe(false);
  expect(officeShapeMultiCanGroup([nodes[0], { ...nodes[2], rootIndex: 2,
    node: { attrs: { position: { layer: "front", x: 0, y: 0 }, wrap: null } } }])).toBe(false);
  expect(() => officeShapeMultiSelection(nodes, [nodes[0].id, nodes[0].id])).toThrow();
  expect(() => officeShapeMultiSelection(nodes, Array(21).fill(0).map((_, index) => `shape-${String(index).padStart(24, "0")}`))).toThrow();
});

test("Office positioned root objects align and distribute through bounded integer anchors", () => {
  const positioned = [
    { id: "shape-" + "1".repeat(24), type: "shape", rootIndex: 4,
      node: { attrs: { position: { layer: "front", x: 100, y: -300 } } } },
    { id: "shape-group-" + "2".repeat(24), type: "shapeGroup", rootIndex: 2,
      node: { attrs: { position: { layer: "behind", x: 900, y: 200 } } } },
    { id: "shape-" + "3".repeat(24), type: "shape", rootIndex: 8,
      node: { attrs: { position: { layer: "front", x: 300, y: 900 } } } },
  ];
  expect(officeShapeMultiCanArrange(positioned)).toBe(true);
  expect(officeShapeMultiCanArrange(positioned, 3)).toBe(true);
  expect(officeShapeMultiAlignment(positioned, "horizontal", "start").map((entry) => entry.position.x))
    .toEqual([100, 100, 100]);
  expect(officeShapeMultiAlignment(positioned, "horizontal", "center").map((entry) => entry.position.x))
    .toEqual([500, 500, 500]);
  expect(officeShapeMultiAlignment(positioned, "vertical", "end").map((entry) => entry.position.y))
    .toEqual([900, 900, 900]);
  const distributed = officeShapeMultiDistribution(positioned, "vertical");
  expect(distributed.map((entry) => entry.position.y)).toEqual([-300, 300, 900]);
  expect(distributed.map((entry) => entry.position.layer)).toEqual(["front", "behind", "front"]);
  expect(officeShapeMultiDistribution(positioned, "horizontal").map((entry) => entry.position.x))
    .toEqual([100, 900, 500]);
  expect(officeShapeMultiLayer(positioned, "behind").map((entry) => entry.position.layer))
    .toEqual(["behind", "behind", "behind"]);
  expect(officeShapeMultiNudge(positioned, "horizontal", 10).map((entry) => entry.position.x))
    .toEqual([110, 910, 310]);
  expect(officeShapeMultiNudge(positioned, "vertical", -1).map((entry) => entry.position.y))
    .toEqual([-301, 199, 899]);
  expect(officeShapeMultiTranslate(positioned, 75, -40).map((entry) => entry.position))
    .toEqual([{ layer: "front", x: 175, y: -340 }, { layer: "behind", x: 975, y: 160 },
      { layer: "front", x: 375, y: 860 }]);
  expect(officeShapeMultiTranslate(positioned, 5000, -5000).map((entry) => entry.position))
    .toEqual([{ layer: "front", x: 200, y: -1200 }, { layer: "behind", x: 1000, y: -700 },
      { layer: "front", x: 400, y: 500 }]);
  const atEdge = positioned.map((entry, index) => ({ ...entry, node: { attrs: { position: {
    ...entry.node.attrs.position, x: index === 1 ? 1000 : entry.node.attrs.position.x } } } }));
  expect(officeShapeMultiNudge(atEdge, "horizontal", 10).map((entry) => entry.position.x))
    .toEqual([100, 1000, 300]);
  expect(officeShapeMultiCanArrange([positioned[0], { ...positioned[1], node: { attrs: { position: null } } }])).toBe(false);
  expect(() => officeShapeMultiAlignment(positioned, "depth", "center")).toThrow();
  expect(() => officeShapeMultiAlignment(positioned, "horizontal", "stretch")).toThrow();
  expect(() => officeShapeMultiDistribution(positioned.slice(0, 2), "vertical")).toThrow();
  expect(() => officeShapeMultiLayer(positioned, "middle")).toThrow();
  expect(() => officeShapeMultiNudge(positioned, "horizontal", 2)).toThrow();
  expect(() => officeShapeMultiTranslate(positioned, 1.5, 2)).toThrow();
  expect(() => officeShapeMultiTranslate(positioned, 1, Number.POSITIVE_INFINITY)).toThrow();
});
