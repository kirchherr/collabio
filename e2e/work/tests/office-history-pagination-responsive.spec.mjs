import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR } from "./support.mjs";
import { loadOfficeComparison, officeEditor } from "./office-support.mjs";
import {
  appendHistory, historyRows, openHistoryComparison, openHistoryFixture,
} from "./office-history-pagination-support.mjs";

async function expectHistoryDialogLayout(page) {
  const dialog = page.locator("#compare-dialog");
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  for (const id of ["compare-left", "compare-right", "compare-history-more", "compare-history-refresh", "compare-close"]) {
    await page.locator(`#${id}`).scrollIntoViewIfNeeded();
    await expect(page.locator(`#${id}`)).toBeInViewport();
  }
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("Office older-version history and comparison controls fit desktop tablet and mobile", async ({ page }, testInfo) => {
  const { objectId, saved, first } = await openHistoryFixture(page);
  await appendHistory(page, objectId, first);
  await expect(historyRows(page)).toHaveCount(100);
  await page.locator("#history-more").scrollIntoViewIfNeeded();
  await expect(page.locator("#history-more")).toBeInViewport();
  const comparison = await openHistoryComparison(page, objectId);
  const second = await appendHistory(page, objectId, comparison, { comparison: true });
  await loadOfficeComparison(page, objectId, second.versions.at(-1).version_id, saved.version.version_id);
  await expectHistoryDialogLayout(page);
  await page.locator("#compare-dialog").evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-history-pagination-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectHistoryDialogLayout(page);
    await page.locator("#compare-dialog").evaluate((element) => { element.scrollTop = 0; });
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-history-pagination-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#compare-close").click();
  if (await page.locator("#inspector-toggle").getAttribute("aria-expanded") === "true" && page.viewportSize().width <= 1000) {
    await page.locator("#inspector-toggle").click();
  }
  await expect(officeEditor(page)).toBeInViewport();
  await expect(page.locator("#document-version")).toContainText(saved.version.version_id);
});
