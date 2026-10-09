import { officeDocumentReferenceAttributes, officeDocumentReferenceDescription,
  officeDocumentReferenceKey } from "./office-document-references.mjs";

export const OFFICE_DOCUMENT_CARD_MODES = ["snapshot", "linked"];

export function officeDocumentCardAttributes(value) {
  if (!value || !OFFICE_DOCUMENT_CARD_MODES.includes(value.mode) ||
      Object.keys(value).some((key) => !["targetObjectId", "targetVersionId", "mode"].includes(key))) {
    throw new Error("Invalid document object");
  }
  const reference = officeDocumentReferenceAttributes({ targetObjectId: value.targetObjectId,
    targetVersionId: value.targetVersionId });
  return { ...reference, mode: value.mode };
}

export function officeDocumentCardKey(value) {
  const attrs = officeDocumentCardAttributes(value);
  return officeDocumentReferenceKey({ targetObjectId: attrs.targetObjectId, targetVersionId: attrs.targetVersionId });
}

export function officeDocumentCardDescription(attrs, resolutions = new Map()) {
  attrs = officeDocumentCardAttributes(attrs);
  const target = officeDocumentReferenceDescription({ targetObjectId: attrs.targetObjectId,
    targetVersionId: attrs.targetVersionId }, resolutions);
  return `Dokumentobjekt · ${attrs.mode === "linked" ? "explizit aktualisierbar" : "feste Momentaufnahme"} · ${target}`;
}
