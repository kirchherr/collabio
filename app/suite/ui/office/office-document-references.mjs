export const OFFICE_DOCUMENT_REFERENCE_LIMIT = 100;
const OBJECT_ID = /^office-doc-[a-f0-9]{32}$/;
const VERSION_ID = /^office-version-[a-f0-9]{32}$/;

export function officeDocumentReferenceAttributes(value) {
  if (!value || !OBJECT_ID.test(value.targetObjectId) || !VERSION_ID.test(value.targetVersionId) ||
      Object.keys(value).some((key) => !["targetObjectId", "targetVersionId"].includes(key))) {
    throw new Error("Invalid document reference");
  }
  return { targetObjectId: value.targetObjectId, targetVersionId: value.targetVersionId };
}

export function officeDocumentReferenceKey(value) {
  const attrs = officeDocumentReferenceAttributes(value);
  return `${attrs.targetObjectId}:${attrs.targetVersionId}`;
}

export function officeDocumentReferenceResolutions(payload, sourceObjectId, sourceVersionId) {
  if (!payload || payload.source_object_id !== sourceObjectId || payload.source_version_id !== sourceVersionId ||
      payload.content_included !== false || !Array.isArray(payload.references) ||
      payload.references.length > OFFICE_DOCUMENT_REFERENCE_LIMIT) throw new Error("Invalid reference response");
  const result = new Map();
  for (const item of payload.references) {
    const attrs = officeDocumentReferenceAttributes({ targetObjectId: item?.target_object_id,
      targetVersionId: item?.target_version_id });
    if (!["resolved", "unavailable"].includes(item.status)) throw new Error("Invalid reference response");
    if (item.status === "resolved") {
      if (typeof item.title !== "string" || !item.title.trim() || typeof item.is_current_version !== "boolean") {
        throw new Error("Invalid reference response");
      }
      result.set(officeDocumentReferenceKey(attrs), { ...attrs, status: "resolved", title: item.title,
        isCurrentVersion: item.is_current_version });
    } else {
      if (item.title != null || item.is_current_version != null) throw new Error("Invalid reference response");
      result.set(officeDocumentReferenceKey(attrs), { ...attrs, status: "unavailable" });
    }
  }
  return result;
}

export function officeDocumentReferenceDescription(attrs, resolutions = new Map()) {
  const resolved = resolutions.get(officeDocumentReferenceKey(attrs));
  if (!resolved || resolved.status !== "resolved") return "Dokumentziel nicht verfügbar";
  return `${resolved.title} · ${resolved.isCurrentVersion ? "aktuelle Version" : "gespeicherte Version"}`;
}
