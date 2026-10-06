import { expect, test } from "@playwright/test";

import { compareOfficeDocuments, describeOfficeBlock } from "../office-comparison.mjs";
import { officeDocumentCardAttributes, officeDocumentCardDescription } from "../office-document-cards.mjs";
import { officeDocumentReferenceKey } from "../office-document-references.mjs";

const attrs = { targetObjectId: "office-doc-" + "a".repeat(32),
  targetVersionId: "office-version-" + "b".repeat(32), mode: "snapshot" };

test("Office document objects admit only exact inert snapshot or linked bindings", () => {
  expect(officeDocumentCardAttributes(attrs)).toEqual(attrs);
  expect(officeDocumentCardAttributes({ ...attrs, mode: "linked" })).toEqual({ ...attrs, mode: "linked" });
  for (const invalid of [{ ...attrs, mode: "live" }, { ...attrs, title: "stored title" },
    { ...attrs, targetObjectId: "office-doc-invalid" }, { ...attrs, targetVersionId: "office-version-invalid" }]) {
    expect(() => officeDocumentCardAttributes(invalid)).toThrow();
  }
});

test("Office document object descriptions and comparisons expose exact version changes", () => {
  const resolutions = new Map([[officeDocumentReferenceKey(attrs), { ...attrs, status: "resolved",
    title: "Approved plan", isCurrentVersion: false }]]);
  expect(officeDocumentCardDescription(attrs, resolutions)).toBe(
    "Dokumentobjekt · feste Momentaufnahme · Approved plan · gespeicherte Version");
  const before = { type: "doc", content: [{ type: "documentCard", attrs }] };
  const after = { type: "doc", content: [{ type: "documentCard", attrs: { ...attrs,
    targetVersionId: "office-version-" + "c".repeat(32), mode: "linked" } }] };
  expect(describeOfficeBlock(before.content[0])).toEqual({ label: "Dokumentobjekt",
    text: expect.stringContaining(attrs.targetVersionId) });
  expect(compareOfficeDocuments(before, after).counts.changed).toBe(1);
});
