import { officeDocumentReferenceAttributes, officeDocumentReferenceDescription,
  officeDocumentReferenceKey } from "./office-document-references.mjs";

export const OFFICE_DOCUMENT_CARD_MODES = ["snapshot", "linked"];

export function officeDocumentCardAttributes(value) {
  const reference = officeDocumentReferenceAttributes(value);
  if (!OFFICE_DOCUMENT_CARD_MODES.includes(value?.mode) ||
      Object.keys(value).some((key) => !["targetObjectId", "targetVersionId", "mode"].includes(key))) {
    throw new Error("Invalid document object");
  }
  return { ...reference, mode: value.mode };
}

export function officeDocumentCardDescription(attrs, resolutions = new Map()) {
  attrs = officeDocumentCardAttributes(attrs);
  const target = officeDocumentReferenceDescription(attrs, resolutions);
  return `Dokumentobjekt · ${attrs.mode === "linked" ? "explizit aktualisierbar" : "feste Momentaufnahme"} · ${target}`;
}
