import path from "node:path";

import { test, expect } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, BLOCKED_BASE_URL, monitorPage } from "./support.mjs";
import { createKnowledgeArticle, openKnowledge } from "./knowledge-support.mjs";
import { closeReader, grantReaderAccess, openReaderWorkspace, readArticle } from "./knowledge-read-support.mjs";

test("the authorized Knowledge reader fits its viewport and keeps long literal content and close accessible", async ({ page, context }, testInfo) => {
  const assertAuthorClean = monitorPage(page, { baseUrls: [BASE_URL] });
  await openKnowledge(page);
  const body = `${"Synthetic long read paragraph. ".repeat(180)}\n${"UnbrokenSyntheticContent".repeat(50)}\n<script>window.responsiveKbUnsafe=true</script>`;
  const created = await createKnowledgeArticle(page, `Synthetic responsive reader ${testInfo.project.name} ${Date.now()}`, body);
  await grantReaderAccess(page, created);
  const reader = await context.newPage();
  const assertReaderClean = monitorPage(reader, { baseUrls: [BLOCKED_BASE_URL] });
  await openReaderWorkspace(reader);
  await readArticle(reader, created.article_object_id);
  const layout = await reader.locator("#knowledge-reader-dialog").evaluate((dialog) => {
    const bounds = dialog.getBoundingClientRect();
    const content = document.querySelector("#knowledge-reader-body");
    return {
      left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom,
      clientWidth: dialog.clientWidth, scrollWidth: dialog.scrollWidth,
      contentWidth: content.clientWidth, contentScrollWidth: content.scrollWidth,
      viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
    };
  });
  expect(layout.left).toBeGreaterThanOrEqual(0);
  expect(layout.right).toBeLessThanOrEqual(layout.viewportWidth + 1);
  expect(layout.top).toBeGreaterThanOrEqual(0);
  expect(layout.bottom).toBeLessThanOrEqual(layout.viewportHeight + 1);
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(layout.contentScrollWidth).toBeLessThanOrEqual(layout.contentWidth + 1);
  await reader.locator("#knowledge-reader-close").scrollIntoViewIfNeeded();
  await expect(reader.locator("#knowledge-reader-close")).toBeInViewport();
  await expect(reader.locator("#knowledge-reader-body script")).toHaveCount(0);
  expect(await reader.evaluate(() => window.responsiveKbUnsafe)).toBeUndefined();
  await reader.screenshot({ path: path.join(ARTIFACT_DIR, `work-knowledge-reader-${testInfo.project.name}.png`), fullPage: true });
  await closeReader(reader);
  assertAuthorClean();
  assertReaderClean();
  await reader.close();
});
