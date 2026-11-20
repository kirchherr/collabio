import { test, expect } from "@playwright/test";
import { officeImageAttributes, officeImageReferences, officeImageReplacementAttributes } from "../office-images.mjs";
import { findDocumentMatches } from "../office-search.mjs";
import { describeOfficeBlock, compareOfficeDocuments } from "../office-comparison.mjs";
import { officeImageGroupAttributes, officeImageGroupColumns, officeImageGroupLayoutLabel,
  OFFICE_IMAGE_GROUP_LIMIT, OFFICE_IMAGE_GROUP_MEMBER_LIMIT } from "../office-image-groups.mjs";

const attrs = { documentId: "office-doc-" + "a".repeat(32), assetId: "office-image-" + "b".repeat(32),
  versionId: "office-image-version-" + "c".repeat(32), contentHash: "sha256:" + "d".repeat(64), manifestHash: "sha256:" + "e".repeat(64),
  pixelWidth: 200, pixelHeight: 100, width: 200, height: 100, align: "left", alt: "A literal image 😀", caption: "<caption>", decorative: false, lockAspect: true };
const image = { type: "image", attrs };
const content = { type: "doc", content: [image, { type: "paragraph", content: [{ type: "text", text: "After image" }] }] };

test("Office image model keeps immutable references and correct text offsets", () => {
  expect(officeImageAttributes(attrs)).toEqual(attrs);
  expect(findDocumentMatches(content, "After")).toEqual([{ from: 2, to: 7 }]);
  expect(officeImageReferences(content)).toEqual([attrs]);
  expect(describeOfficeBlock(image).label).toBe("Bild");
  expect(describeOfficeBlock(image).text).toContain("<caption>");
});

test("Office image replacement keeps presentation and description but resets crop", () => {
  const source = { ...attrs, width: 300, height: 150, align: "right", caption: "Numbered image",
    crop: { x: 20, y: 10, width: 180, height: 90 }, position: { layer: "front", x: 640, y: 120 },
    transform: { rotation: 90, flipX: true, flipY: false }, figureId: "figure-aaaaaaaaaaaaaaaaaaaaaaaa" };
  const replacement = { ...attrs, assetId: "office-image-" + "f".repeat(32),
    versionId: "office-image-version-" + "1".repeat(32), contentHash: "sha256:" + "2".repeat(64),
    manifestHash: "sha256:" + "3".repeat(64), pixelWidth: 200, pixelHeight: 300,
    width: 200, height: 300, align: "left", alt: "", caption: "", decorative: true };
  expect(officeImageReplacementAttributes(source, replacement)).toEqual({ ...replacement,
    width: 300, height: 450, align: "right", alt: source.alt, caption: source.caption,
    decorative: false, lockAspect: true, position: source.position, transform: source.transform, figureId: source.figureId });
  expect(officeImageReplacementAttributes({ ...source, lockAspect: false }, replacement)).toMatchObject({ width: 300, height: 150 });
});

test("Office image replacement bounds a locked portrait and validates both sources", () => {
  const portrait = { ...attrs, pixelWidth: 100, pixelHeight: 400, height: 400 };
  expect(officeImageReplacementAttributes({ ...attrs, width: 800, height: 400 }, portrait)).toMatchObject({ width: 400, height: 1600 });
  expect(() => officeImageReplacementAttributes({ ...attrs, crop: { x: 0, y: 0, width: 201, height: 1 } }, portrait)).toThrow();
});

test("Office image model keeps legacy captions and admits only captioned stable figures", () => {
  const figureId = "figure-aaaaaaaaaaaaaaaaaaaaaaaa";
  expect(officeImageAttributes({ ...attrs, figureId })).toEqual({ ...attrs, figureId });
  expect(officeImageAttributes({ ...attrs, figureId: null })).toEqual(attrs);
  for (const change of [{ figureId: "figure-short" }, { figureId, caption: "" }, { figureId, caption: "   " }]) {
    expect(() => officeImageAttributes({ ...attrs, ...change })).toThrow();
  }
});

test("Office image model rejects active attributes and counts references", () => {
  for (const change of [{ src: "https://external.invalid/image.png" }, { width: true }, { decorative: true }, { alt: "" }, { align: "float" }, { pixelWidth: 4097 }]) {
    expect(() => officeImageAttributes({ ...attrs, ...change })).toThrow();
  }
  expect(() => officeImageReferences({ type: "doc", content: Array(41).fill(image) })).toThrow();
});

test("Office image comparison retains untouched nodes and reports presentation edits", () => {
  const changed = { ...content, content: [{ ...image, attrs: { ...attrs, width: 100 } }, content.content[1]] };
  const result = compareOfficeDocuments(content, changed);
  expect(result.rows.some((row) => row.before === content.content[1] || row.after === content.content[1])).toBe(true);
  expect(describeOfficeBlock(changed.content[0]).text).toContain("100 × 100");
});

test("Office crop preserves source identity and omits the editor's empty default", () => {
  expect(officeImageAttributes({ ...attrs, crop: null })).toEqual(attrs);
  const crop = { x: 100, y: 10, width: 100, height: 80 };
  expect(officeImageAttributes({ ...attrs, crop })).toEqual({ ...attrs, crop });
  expect(describeOfficeBlock({ ...image, attrs: { ...attrs, crop } }).text).toContain("Zuschnitt: 100, 10 · 100 × 80");
});

test("Office crop rejects out-of-source noninteger and ambiguous geometry", () => {
  for (const crop of [{}, { x: -1, y: 0, width: 1, height: 1 }, { x: 100, y: 0, width: 101, height: 1 },
    { x: 0, y: 0, width: 1, height: 101 }, { x: false, y: 0, width: 1, height: 1 },
    { x: 0.5, y: 0, width: 1, height: 1 }, { x: 0, y: 0, width: 1, height: 1, source: "other" }]) {
    expect(() => officeImageAttributes({ ...attrs, crop })).toThrow();
  }
});

test("Office wrapping keeps crop source and legacy defaults and describes layout changes", () => {
  expect(officeImageAttributes({ ...attrs, crop: null, wrap: null })).toEqual(attrs);
  const crop = { x: 100, y: 0, width: 100, height: 100 }, wrap = { side: "right", gap: 48 };
  expect(officeImageAttributes({ ...attrs, crop, wrap })).toEqual({ ...attrs, crop, wrap });
  const after = { ...image, attrs: { ...attrs, crop, wrap } };
  expect(describeOfficeBlock(after).text).toContain("Textumfluss: Bild rechts · Abstand 48 px");
  expect(compareOfficeDocuments(content, { ...content, content: [after, content.content[1]] }).rows.some((row) => row.before === content.content[1] || row.after === content.content[1])).toBe(true);
});

test("Office wrapping rejects CSS coordinates invalid sides and noninteger gaps", () => {
  for (const wrap of [{}, [], "left", { side: "center", gap: 16 }, { side: "left", gap: -1 },
    { side: "left", gap: 49 }, { side: "right", gap: true }, { side: "left", gap: "16" },
    { side: "right", gap: 0.5 }, { side: "left", gap: 16, position: "absolute" }]) {
    expect(() => officeImageAttributes({ ...attrs, wrap })).toThrow();
  }
});

test("Office free image positions are inert bounded and mutually exclusive with wrapping", () => {
  for (const position of [{ layer: "front", x: 0, y: -1200 }, { layer: "behind", x: 1000, y: 1200 }]) {
    expect(officeImageAttributes({ ...attrs, position })).toEqual({ ...attrs, position });
  }
  const position = { layer: "front", x: 500, y: 24 };
  expect(describeOfficeBlock({ ...image, attrs: { ...attrs, position } }).text).toContain("Freie Position: vor Text · X 500 · Y 24 px");
  for (const invalid of [{}, [], "front", { layer: "middle", x: 0, y: 0 }, { layer: "front", x: -1, y: 0 },
    { layer: "behind", x: 1001, y: 0 }, { layer: "front", x: true, y: 0 }, { layer: "front", x: 0.5, y: 0 },
    { layer: "front", x: 0, y: -1201 }, { layer: "behind", x: 0, y: 1201 }, { layer: "front", x: 0, y: 0, style: "fixed" }]) {
    expect(() => officeImageAttributes({ ...attrs, position: invalid })).toThrow();
  }
  expect(() => officeImageAttributes({ ...attrs, position, wrap: { side: "left", gap: 16 } })).toThrow();
});

test("Office image transforms are inert bounded canonical and visible in comparisons", () => {
  expect(officeImageAttributes({ ...attrs, transform: null })).toEqual(attrs);
  for (const transform of [{ rotation: 90, flipX: false, flipY: false }, { rotation: 270, flipX: true, flipY: true },
    { rotation: 0, flipX: false, flipY: true }]) {
    expect(officeImageAttributes({ ...attrs, transform })).toEqual({ ...attrs, transform });
  }
  const transform = { rotation: 90, flipX: true, flipY: false };
  expect(describeOfficeBlock({ ...image, attrs: { ...attrs, transform } }).text).toContain("Darstellung: 90° · horizontal gespiegelt");
  for (const invalid of [{}, [], "rotate(90deg)", { rotation: 45, flipX: false, flipY: false },
    { rotation: true, flipX: false, flipY: false }, { rotation: 0, flipX: false, flipY: false },
    { rotation: 90, flipX: 1, flipY: false }, { rotation: 90, flipX: false, flipY: false, style: "fixed" }]) {
    expect(() => officeImageAttributes({ ...attrs, transform: invalid })).toThrow();
  }
});

test("Office image groups are bounded inert containers visible in comparisons", () => {
  const groupAttrs = { id: "image-group-" + "a".repeat(24), layout: "row", gap: 16 };
  expect(officeImageGroupAttributes(groupAttrs)).toEqual(groupAttrs);
  expect(OFFICE_IMAGE_GROUP_LIMIT).toBe(20); expect(OFFICE_IMAGE_GROUP_MEMBER_LIMIT).toBe(8);
  const group = { type: "imageGroup", attrs: groupAttrs, content: [image, { ...image, attrs: { ...attrs, alt: "Second" } }] };
  expect(describeOfficeBlock(group)).toMatchObject({ label: "Bildgruppe · 2 Bilder · nebeneinander · Abstand 16 px" });
  expect(officeImageReferences({ type: "doc", content: [group] })).toHaveLength(2);
  for (const invalid of [{ ...groupAttrs, id: "group-short" }, { ...groupAttrs, layout: "grid" },
    { ...groupAttrs, gap: -1 }, { ...groupAttrs, gap: 49 }, { ...groupAttrs, gap: true }, { ...groupAttrs, style: "active" }]) {
    expect(() => officeImageGroupAttributes(invalid)).toThrow();
  }
});

test("Office image groups expose canonical responsive grid layouts", () => {
  for (const [layout, columns] of [["grid-2", 2], ["grid-3", 3], ["grid-4", 4]]) {
    const groupAttrs = { id: "image-group-" + "a".repeat(24), layout, gap: 12 };
    expect(officeImageGroupAttributes(groupAttrs)).toEqual(groupAttrs);
    expect(officeImageGroupColumns(layout, 8)).toBe(columns);
    expect(officeImageGroupLayoutLabel(layout)).toBe(`Raster mit ${columns} Spalten`);
  }
  expect(officeImageGroupColumns("row", 6)).toBe(6);
  expect(officeImageGroupColumns("stack", 6)).toBe(1);
  expect(() => officeImageGroupColumns("grid-3", 1)).toThrow();
});
