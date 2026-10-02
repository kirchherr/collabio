import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, officeVersions, openOffice } from "./office-support.mjs";
import { confirmComment, openComments, openThread, prepareComment, reviewEvent, selectEditorText } from "./office-review-support.mjs";

async function expectReviewLayout(page) {
  for (const id of ["comments-panel", "comments-close", "comments-refresh", "comment-new"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  await expect(page.locator("#comment-thread-quote")).toBeInViewport();
  await expect(page.locator("#comment-events")).toContainText("Responsible team");
  expect(await page.locator("#comments-panel").evaluate((panel) => panel.scrollWidth <= panel.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("Office saved-version comments and explicit confirmation fit desktop, tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const saved = await createOfficeDocument(page, `Synthetic responsive review ${testInfo.project.name}`, "Delivery 😀 review: discuss the next step.");
  const objectId = saved.document.object_id;
  await openComments(page, objectId);
  await selectEditorText(page, "Delivery 😀 review");
  await prepareComment(page, "Responsible team: please verify the next step.", { selection: true });
  for (const id of ["comment-confirm-summary", "comment-confirm-checkbox", "comment-confirm-submit", "comment-confirm-cancel"]) {
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await page.locator("#comment-confirm-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
  const created = await confirmComment(page, objectId);
  await openThread(page, objectId, created.thread.thread_id);
  await reviewEvent(page, objectId, created.thread.thread_id, "reply", "The assigned team has checked it.");
  await expectReviewLayout(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-review-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expect(page.locator("#document-inspector")).toBeHidden();
    // Deliberately reopen the inspector after the compact-layout transition.
    await openComments(page, objectId);
    await openThread(page, objectId, created.thread.thread_id);
    await expectReviewLayout(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-review-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#comments-close").click();
  await expect(officeEditor(page)).toBeInViewport();
  await expect(page.locator("#document-save")).toBeDisabled();
  expect(await officeVersions(page, objectId)).toHaveLength(1);
  verifyBrowser();
});
