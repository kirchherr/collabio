import { expect, test } from "@playwright/test";

import {
  OFFICE_DOCUMENT_REFERENCE_LIMIT, officeDocumentReferenceAttributes, officeDocumentReferenceDescription,
  officeDocumentReferenceKey, officeDocumentReferenceResolutions,
} from "../office-document-references.mjs";

const objectId = `office-doc-${"a".repeat(32)}`;
const versionId = `office-version-${"b".repeat(32)}`;
const attrs = { targetObjectId: objectId, targetVersionId: versionId };

test("document references validate exact immutable identities and safe unavailable responses", () => {
  expect(OFFICE_DOCUMENT_REFERENCE_LIMIT).toBe(100);
  expect(officeDocumentReferenceAttributes(attrs)).toEqual(attrs);
  expect(officeDocumentReferenceKey(attrs)).toBe(`${objectId}:${versionId}`);
  for (const invalid of [
    { ...attrs, targetObjectId: "office-doc-invalid" },
    { ...attrs, targetVersionId: "office-version-invalid" },
    { ...attrs, title: "must not be stored" },
  ]) expect(() => officeDocumentReferenceAttributes(invalid)).toThrow();

  const sourceObject = `office-doc-${"c".repeat(32)}`, sourceVersion = `office-version-${"d".repeat(32)}`;
  const unavailable = officeDocumentReferenceResolutions({ source_object_id: sourceObject, source_version_id: sourceVersion,
    content_included: false, references: [{ target_object_id: objectId, target_version_id: versionId,
      status: "unavailable", title: null, is_current_version: null }] }, sourceObject, sourceVersion);
  expect(officeDocumentReferenceDescription(attrs, unavailable)).toBe("Dokumentziel nicht verfügbar");
  expect(() => officeDocumentReferenceResolutions({ source_object_id: sourceObject, source_version_id: sourceVersion,
    content_included: false, references: [{ target_object_id: objectId, target_version_id: versionId,
      status: "unavailable", title: "leak", is_current_version: null }] }, sourceObject, sourceVersion)).toThrow();
});

test("document reference descriptions use only a freshly validated resolved title", () => {
  const sourceObject = `office-doc-${"c".repeat(32)}`, sourceVersion = `office-version-${"d".repeat(32)}`;
  const resolutions = officeDocumentReferenceResolutions({ source_object_id: sourceObject, source_version_id: sourceVersion,
    content_included: false, references: [{ target_object_id: objectId, target_version_id: versionId,
      status: "resolved", title: "Approved title", is_current_version: false }] }, sourceObject, sourceVersion);
  expect(officeDocumentReferenceDescription(attrs, resolutions)).toBe("Approved title · gespeicherte Version");
});
