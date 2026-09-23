import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import { createOfficeDocument, officeEditor, officeVersions, openOffice, saveOffice } from "./office-support.mjs";
import { collectReuseRequests, expectReuseDraft, openReuse, submitReuse } from "./office-reuse-support.mjs";

async function expectReuseLayout(page) {
  const dialog = page.locator("#reuse-dialog");
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  for (const id of ["reuse-title", "reuse-source", "reuse-submit", "reuse-close"]) await expect(page.locator(`#${id}`)).toBeInViewport();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("Office saved-version reuse and its explicit independent save fit desktop tablet and mobile", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const title = `Synthetic ${testInfo.project.name} ${"LongSavedTitle".repeat(8)}`;
  const first = await createOfficeDocument(page, title, "Responsive exact saved source remains readable.");
  const requests = collectReuseRequests(page);
  await openReuse(page, first, "A separate responsive document");
  await expectReuseLayout(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-reuse-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectReuseLayout(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-reuse-tablet-chromium.png`, fullPage: true });
  }
  await submitReuse(page, first);
  await expectReuseDraft(page, "A separate responsive document");
  await expect(officeEditor(page)).toBeInViewport();
  await expect(officeEditor(page)).toHaveText("Responsive exact saved source remains readable.");
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  const saved = await saveOffice(page);
  expect(saved.document.object_id).not.toBe(first.document.object_id);
  expect(saved.content).toEqual(first.content);
  expect(await officeVersions(page, saved.document.object_id)).toHaveLength(1);
  expect(await officeVersions(page, first.document.object_id)).toHaveLength(1);
  verifyBrowser();
});
