import { expect, test } from "@playwright/test";

import { ARTIFACT_DIR, BASE_URL, monitorPage } from "./support.mjs";
import {
  createOfficeVersionPair, loadOfficeComparison, officeEditor, officeVersions,
  openOffice, openOfficeComparison, saveOffice,
} from "./office-support.mjs";

async function expectContainedComparison(page) {
  const box = await page.locator("#compare-dialog").boundingBox();
  expect(box).not.toBeNull();
  const viewport = page.viewportSize();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  await expect(page.locator("#compare-close")).toBeInViewport();
  await expect(page.locator("#compare-restore")).toBeInViewport();
  expect(await page.locator("#compare-dialog").evaluate((dialog) => dialog.scrollWidth <= dialog.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("Office version comparison and explicit historical takeover fit the viewport", async ({ page }, testInfo) => {
  const verifyBrowser = monitorPage(page, { baseUrls: [BASE_URL] });
  await openOffice(page);
  const earlier = `Earlier decision: ${"Historical wording remains fully readable. ".repeat(8)}${"LongIdentifier".repeat(18)}`;
  const current = `Current decision: ${"Revised wording also remains fully readable. ".repeat(8)}${"RevisedIdentifier".repeat(18)}`;
  const pair = await createOfficeVersionPair(page, `Synthetic responsive versions ${testInfo.project.name}`, earlier, current);
  await openOfficeComparison(page);
  await expect(page.locator("#compare-left")).toBeInViewport();
  await expect(page.locator("#compare-right")).toBeInViewport();
  await loadOfficeComparison(page, pair.objectId, pair.first.version.version_id, pair.second.version.version_id);
  await expect(page.locator("#compare-results")).toContainText(earlier);
  await expect(page.locator("#compare-results")).toContainText(current);
  await expectContainedComparison(page);
  await page.screenshot({ path: `${ARTIFACT_DIR}/office-versions-${testInfo.project.name}.png`, fullPage: true });
  if (testInfo.project.name === "desktop-chromium") {
    await page.setViewportSize({ width: 900, height: 900 });
    await expectContainedComparison(page);
    await page.screenshot({ path: `${ARTIFACT_DIR}/office-versions-tablet-chromium.png`, fullPage: true });
  }
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(officeEditor(page)).toHaveText(earlier);
  await expect(page.locator("#document-title")).toHaveValue(pair.first.version.title);
  await expect(page.locator("#document-status")).toContainText("Ungespeicherte Änderungen");
  expect(await officeVersions(page, pair.objectId)).toHaveLength(2);
  const saved = await saveOffice(page, { objectId: pair.objectId });
  expect(saved.content).toEqual(pair.first.content);
  expect(saved.version.previous_version_id).toBe(pair.second.version.version_id);
  expect(await officeVersions(page, pair.objectId)).toHaveLength(3);
  await openOfficeComparison(page);
  await loadOfficeComparison(page, pair.objectId, pair.first.version.version_id, saved.version.version_id);
  await expect(page.locator("#compare-summary")).toContainText("0 geändert");
  await page.locator("#compare-restore").click();
  await expect(page.locator("#compare-dialog")).toBeHidden();
  await expect(officeEditor(page)).toHaveText(earlier);
  await expect(page.locator("#document-title")).toHaveValue(pair.first.version.title);
  await expect(page.locator("#document-save")).toBeDisabled();
  await expect(page.locator("#document-status")).toContainText("Gespeichert");
  await expect(page.locator("#document-status")).not.toContainText("Ungespeicherte Änderungen");
  await expect(page.locator("#document-notice")).toContainText("entspricht bereits der aktuellen Version");
  expect(await officeVersions(page, pair.objectId)).toHaveLength(3);
  verifyBrowser();
});
