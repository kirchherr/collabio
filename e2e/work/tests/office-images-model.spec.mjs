import { test, expect } from "@playwright/test";
import { officeImageAttributes, officeImageReferences } from "../office-images.mjs";
import { findDocumentMatches } from "../office-search.mjs";
import { describeOfficeBlock, compareOfficeDocuments } from "../office-comparison.mjs";

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
