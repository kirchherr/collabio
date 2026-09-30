import { expect, test } from "@playwright/test";

import { OFFICE_BACKLINK_PAGE_MAX, officeBacklinkPage } from "../office-backlinks.mjs";

const targetObjectId = `office-doc-${"a".repeat(32)}`;
const targetVersionId = `office-version-${"b".repeat(32)}`;
const sourceObjectId = `office-doc-${"c".repeat(32)}`;
const sourceVersionId = `office-version-${"d".repeat(32)}`;

function payload(overrides = {}) {
  return {
    target_object_id: targetObjectId, target_version_id: targetVersionId, content_included: false,
    backlinks: [{ source_object_id: sourceObjectId, source_version_id: sourceVersionId,
      title: "Authorized source", reference_count: 2 }],
    page_size: 50, has_more: false, next_cursor: null, ...overrides,
  };
}

test("backlink pages accept only exact bounded freshly authorized source metadata", () => {
  expect(OFFICE_BACKLINK_PAGE_MAX).toBe(50);
  expect(officeBacklinkPage(payload(), targetObjectId, targetVersionId)).toEqual({
    backlinks: [{ sourceObjectId, sourceVersionId, title: "Authorized source", referenceCount: 2 }],
    hasMore: false, nextCursor: null,
  });
  for (const invalid of [
    payload({ target_object_id: `office-doc-${"e".repeat(32)}` }),
    payload({ content_included: true }),
    payload({ backlinks: [{ source_object_id: sourceObjectId, source_version_id: sourceVersionId,
      title: "Hidden\u0000source", reference_count: 1 }] }),
    payload({ has_more: true, next_cursor: null }),
    payload({ backlinks: Array.from({ length: 51 }, () => ({ source_object_id: sourceObjectId,
      source_version_id: sourceVersionId, title: "Duplicate", reference_count: 1 })) }),
  ]) expect(() => officeBacklinkPage(invalid, targetObjectId, targetVersionId)).toThrow();
});
