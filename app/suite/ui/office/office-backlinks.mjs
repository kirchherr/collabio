export const OFFICE_BACKLINK_PAGE_MAX = 50;

const objectPattern = /^office-doc-[a-f0-9]{32}$/;
const versionPattern = /^office-version-[a-f0-9]{32}$/;

function safeTitle(value) {
  return typeof value === "string" && value.length >= 1 && value.length <= 200 &&
    ![...value].some((character) => character.codePointAt(0) < 32 ||
      (character.codePointAt(0) >= 0x7f && character.codePointAt(0) <= 0x9f));
}

export function officeBacklinkPage(payload, targetObjectId, targetVersionId) {
  if (!objectPattern.test(targetObjectId) || !versionPattern.test(targetVersionId) || !payload ||
      payload.target_object_id !== targetObjectId || payload.target_version_id !== targetVersionId ||
      payload.content_included !== false || !Array.isArray(payload.backlinks) ||
      payload.backlinks.length > OFFICE_BACKLINK_PAGE_MAX || typeof payload.has_more !== "boolean" ||
      !Number.isInteger(payload.page_size) || payload.page_size < 1 || payload.page_size > OFFICE_BACKLINK_PAGE_MAX ||
      (payload.has_more ? typeof payload.next_cursor !== "string" || !payload.next_cursor.length : payload.next_cursor !== null)) {
    throw new Error("invalid-backlink-page");
  }
  const seen = new Set();
  const backlinks = payload.backlinks.map((entry) => {
    if (!entry || !objectPattern.test(entry.source_object_id) || !versionPattern.test(entry.source_version_id) ||
        !safeTitle(entry.title) || !Number.isInteger(entry.reference_count) ||
        entry.reference_count < 1 || entry.reference_count > 100) throw new Error("invalid-backlink");
    const key = `${entry.source_object_id}:${entry.source_version_id}`;
    if (seen.has(key)) throw new Error("duplicate-backlink");
    seen.add(key);
    return { sourceObjectId: entry.source_object_id, sourceVersionId: entry.source_version_id,
      title: entry.title, referenceCount: entry.reference_count };
  });
  return { backlinks, hasMore: payload.has_more, nextCursor: payload.next_cursor };
}
